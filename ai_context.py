"""Builds the data context the chat model sees: the person's complete WHOOP
history, re-encoded as compact pipe-separated tables instead of raw JSON.

Why tables: the raw export (whoop_data.json) is ~1.3MB — mostly the same field
names and IDs repeated thousands of times. The same values as tables are a
fraction of the tokens, which keeps every request cheap, fast, and well inside
the model's context window. Nothing scored is dropped; only formatting is.

Privacy: only the first name leaves this machine — email, last name, WHOOP
user id, and record ids are never included.

Dates use the same convention as the dashboard (the calendar day of the record's
created_at timestamp), so a number the model quotes matches the page. Clock
times (sleep onset, wake, workout start) are converted to the local time zone
WHOOP recorded with each record.
"""
import json, math, os
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
RAW_FILE = os.path.join(HERE, "whoop_data.json")
DASH_FILE = os.path.join(HERE, "dashboard_data.json")

# dashboard_data.json keys that are already covered, in full, by the tables below
# (or are identifying) — everything else there is a small computed summary and is
# included as-is, since it's exactly what the person sees on the page.
DASH_SKIP = {"profile", "full_series", "workout_log", "acwr"}


def _parse(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _day(s):
    return _parse(s).date().isoformat()


def _local_hm(ts, offset):
    """'23:32' in the time zone WHOOP stored with the record (e.g. '+03:00')."""
    try:
        sign = 1 if offset[0] == "+" else -1
        h, m = offset[1:].split(":")
        tz = timezone(sign * timedelta(hours=int(h), minutes=int(m)))
        return _parse(ts).astimezone(tz).strftime("%H:%M")
    except Exception:
        return _parse(ts).strftime("%H:%MZ")


def _n(v, digits=1):
    """Compact number: None → '', ints without a trailing .0."""
    if v is None:
        return ""
    v = round(float(v), digits)
    return str(int(v)) if v == int(v) else str(v)


def _h(ms):
    """Duration as h:mm ('2:26'), the way the WHOOP app shows it. Decimal hours ('2.44')
    read like clock time and were quoted wrongly as 2h 44m."""
    if ms is None:
        return ""
    m = int(round(ms / 60000))
    return f"{'-' if m < 0 else ''}{abs(m) // 60}:{abs(m) % 60:02d}"


def _min(ms):
    return "" if ms is None else _n(ms / 60000, 0)


STAGE_KEYS = ("total_awake_time_milli", "total_light_sleep_time_milli", "total_slow_wave_sleep_time_milli",
              "total_rem_sleep_time_milli", "total_no_data_time_milli")
_CUMULATIVE_ORDER = ("total_light_sleep_time_milli", "total_slow_wave_sleep_time_milli",
                     "total_rem_sleep_time_milli", "total_awake_time_milli", "total_no_data_time_milli")


def _stage_minutes(stage):
    """Whole minutes per stage, rounded the way the WHOOP app shows them: the running total
    (light → deep → REM → awake) is rounded, so the stages always add up to time in bed and
    light + deep + REM equals hours of sleep. Checked against the app: 91.6/146.6/126.1/28.8 min
    → 1:32 / 2:26 / 2:06 / 0:29 = 6:33 in bed, 6:04 asleep."""
    out, run, prev = {}, 0.0, 0
    for k in _CUMULATIVE_ORDER:
        run += (stage.get(k) or 0) / 60000
        cur = int(math.floor(run + 0.5))
        out[k], prev = cur - prev, cur
    return out


def _hm(minutes):
    return f"{minutes // 60}:{minutes % 60:02d}"


def _vs_needed(stage, need):
    """Hours vs needed % (time asleep ÷ WHOOP sleep need) — the app's 'Hours vs. Needed'."""
    need_ms = sum(need.get(k) or 0 for k in ("baseline_milli", "need_from_sleep_debt_milli",
                                            "need_from_recent_strain_milli", "need_from_recent_nap_milli"))
    if need_ms <= 0 or stage.get("total_in_bed_time_milli") is None:
        return ""
    asleep = stage["total_in_bed_time_milli"] - (stage.get("total_awake_time_milli") or 0)
    return _n(100 * asleep / need_ms, 0)


def _table(name, note, header, rows):
    lines = [f"## {name}", note, "|".join(header)]
    lines += ["|".join(r) for r in rows]
    return "\n".join(lines)


def build_context_text():
    with open(RAW_FILE) as f:
        raw = json.load(f)
    with open(DASH_FILE) as f:
        dash = json.load(f)

    scored = lambda items: [x for x in items if x.get("score_state") == "SCORED" and x.get("score")]

    # ---- days: one row per WHOOP physiological cycle, joined with its recovery ----
    rec_by_cycle = {r["cycle_id"]: r["score"] for r in scored(raw["recovery"])}
    days = []
    for c in sorted(scored(raw["cycles"]), key=lambda c: c["created_at"]):
        s, r = c["score"], rec_by_cycle.get(c["id"], {})
        days.append([
            _day(c["created_at"]), _n(s.get("strain")), _n(s.get("kilojoule") and s["kilojoule"] / 4.184, 0),
            _n(s.get("average_heart_rate"), 0), _n(s.get("max_heart_rate"), 0),
            _n(r.get("recovery_score"), 0), _n(r.get("hrv_rmssd_milli")), _n(r.get("resting_heart_rate"), 0),
            _n(r.get("spo2_percentage")), _n(r.get("skin_temp_celsius"), 2),
            "1" if r.get("user_calibrating") else "",
        ])

    # ---- sleeps: every scored sleep, naps included and marked ----
    sleeps = []
    for s in sorted(scored(raw["sleep"]), key=lambda s: s["start"]):
        sc, st, need = s["score"], s["score"].get("stage_summary", {}), s["score"].get("sleep_needed", {})
        sm = _stage_minutes(st)
        off = s.get("timezone_offset", "+00:00")
        sleeps.append([
            _day(s["created_at"]), "nap" if s.get("nap") else "sleep",
            _local_hm(s["start"], off), _local_hm(s["end"], off),
            _h(st.get("total_in_bed_time_milli")),
            _hm(sum(sm[k] for k in _CUMULATIVE_ORDER[:3])) if st.get("total_light_sleep_time_milli") is not None else "",
            *[_hm(sm[k]) if st.get(k) is not None else "" for k in STAGE_KEYS[:4]],
            _n(st.get("sleep_cycle_count"), 0),
            _n(st.get("disturbance_count"), 0), _n(sc.get("respiratory_rate")),
            _n(sc.get("sleep_performance_percentage"), 0), _vs_needed(st, need),
            _n(sc.get("sleep_consistency_percentage"), 0),
            _n(sc.get("sleep_efficiency_percentage"), 0),
            _h(need.get("baseline_milli")), _h(need.get("need_from_sleep_debt_milli")),
            _h(need.get("need_from_recent_strain_milli")), _h(need.get("need_from_recent_nap_milli")),
        ])

    # ---- workouts ----
    workouts = []
    for w in sorted(scored(raw["workouts"]), key=lambda w: w["start"]):
        sc, z = w["score"], w["score"].get("zone_durations") or {}
        off = w.get("timezone_offset", "+00:00")
        dur = (_parse(w["end"]) - _parse(w["start"])).total_seconds() / 60
        workouts.append([
            _day(w["created_at"]), _local_hm(w["start"], off), _n(dur, 0),
            "other activity" if w["sport_name"] == "activity" else w["sport_name"].replace("_", " "),
            _n(sc.get("strain")), _n(sc.get("average_heart_rate"), 0), _n(sc.get("max_heart_rate"), 0),
            _n(sc.get("kilojoule") and sc["kilojoule"] / 4.184, 0),
            _n(sc.get("distance_meter") and sc["distance_meter"] / 1000, 2), _n(sc.get("altitude_gain_meter"), 0),
            _n(sc.get("percent_recorded") and sc["percent_recorded"] * 100, 0),
            *[_min(z.get(k)) for k in ("zone_zero_milli", "zone_one_milli", "zone_two_milli",
                                       "zone_three_milli", "zone_four_milli", "zone_five_milli")],
        ])

    body = raw.get("body") or {}
    summaries = {k: v for k, v in dash.items() if k not in DASH_SKIP}
    summaries["acwr_last_120_days"] = dash.get("acwr", [])[-120:]

    parts = [
        "# WHOOP data",
        f"Name: {raw.get('profile', {}).get('first_name', '')}. "
        f"Height {body.get('height_meter')} m, weight {body.get('weight_kilogram')} kg, "
        f"max heart rate {body.get('max_heart_rate')} bpm.",
        f"Data last pulled from WHOOP: {dash.get('asOf')}. History: {dash.get('date_range')}.",
        "Tables are pipe-separated; an empty field means WHOOP has no value for it.",
        _table("days", "One row per WHOOP day (cycle). strain 0–21; kcal = total energy; "
               "recovery 0–100 (0–33 red, 34–66 yellow, 67–100 green); hrv = RMSSD in ms; "
               "rhr = resting HR bpm; spo2 %; skin_temp °C; calibrating=1 while WHOOP is still learning.",
               ["date", "strain", "kcal", "avg_hr", "max_hr", "recovery", "hrv", "rhr", "spo2", "skin_temp", "calibrating"],
               days),
        _table("sleeps", "One row per sleep. Times are local. Durations are h:mm (2:26 = 2 hours 26 minutes), "
               "rounded like the WHOOP app; asleep = light + deep + rem (the app's 'Hours of Sleep'); "
               "resp = breaths/min; perf = WHOOP Sleep Performance % (since WHOOP's 2025 update it blends hours vs "
               "needed with consistency, efficiency and sleep stress); vs_needed = time asleep ÷ sleep need % "
               "(the app's 'Hours vs. Needed'); consistency/efficiency are %; need_* = sleep WHOOP says was needed "
               "from baseline, sleep debt, recent strain, and recent naps.",
               ["date", "type", "start", "end", "in_bed", "asleep", "awake", "light", "deep", "rem", "cycles",
                "disturbances", "resp", "perf", "vs_needed", "consistency", "efficiency",
                "need_baseline", "need_debt", "need_strain", "need_nap"],
               sleeps),
        _table("workouts", "One row per workout. start is local time; dur and z0–z5 (heart-rate zone time) in minutes; "
               "dist in km; alt_gain in m; recorded = % of the session with heart-rate data.",
               ["date", "start", "dur", "sport", "strain", "avg_hr", "max_hr", "kcal", "dist", "alt_gain",
                "recorded", "z0", "z1", "z2", "z3", "z4", "z5"],
               workouts),
        "## dashboard_summaries",
        "The exact computed numbers shown on the dashboard (JSON): thresholds, weekly/monthly rollups, "
        "records, anomaly flags, load ratio, today's snapshot.",
        json.dumps(summaries, separators=(",", ":")),
    ]
    return "\n\n".join(parts)


if __name__ == "__main__":
    text = build_context_text()
    print(f"{len(text):,} characters ≈ {len(text) // 4:,} tokens (rough estimate)")
