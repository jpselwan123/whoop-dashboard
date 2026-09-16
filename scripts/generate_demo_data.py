"""Generate a realistic, entirely synthetic WHOOP export for a fictional athlete.

Used for the demo dashboard, README screenshots, and the test suite — so none of
them ever depend on a real person's health data. The output has the same shape
as what whoop.py saves from the WHOOP API (v2), with physiologically plausible
relationships baked in: hard days lower the next morning's HRV and recovery,
short sleep does too, and a heavy final training block pushes the load ratio up.

Usage: python3 scripts/generate_demo_data.py [out_dir] [--days N] [--seed S]
       (default out_dir: demo/, 420 days, seed 23)
"""
import argparse, json, math, os, random, uuid
from datetime import datetime, timedelta, timezone

TZ = "+01:00"
TZ_DELTA = timedelta(hours=1)

# sport_name → (typical minutes, strain range, intensity 0–1, has distance)
SPORTS = {
    "running": (45, (9, 15), 0.75, True),
    "weightlifting_msk": (60, (6, 11), 0.35, False),
    "soccer": (80, (12, 17), 0.85, False),
    "cycling": (90, (10, 16), 0.65, True),
    "yoga": (40, (3, 6), 0.15, False),
    "tennis": (70, (9, 14), 0.7, False),
}
# weekday (Mon=0) → sports that athlete tends to do that day, with probability
PLAN = {
    0: [("weightlifting_msk", 0.8)],
    1: [("running", 0.75)],
    2: [("tennis", 0.55), ("yoga", 0.35)],
    3: [("weightlifting_msk", 0.7), ("running", 0.3)],
    4: [("yoga", 0.3)],
    5: [("soccer", 0.8)],
    6: [("cycling", 0.5)],
}


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def generate(days=420, seed=23, now=None):
    rng = random.Random(seed)
    now = now or datetime.now(timezone.utc)
    today_local = (now + TZ_DELTA).date()
    start_day = today_local - timedelta(days=days - 1)

    uid = lambda: str(uuid.UUID(int=rng.getrandbits(128)))
    cycles, sleeps, recoveries, workouts = [], [], [], []
    cycle_id = 900000000
    prev_strain, fitness = 10.0, 0.0
    hrv_base, rhr_base = 68.0, 54.0

    for i in range(days):
        d = start_day + timedelta(days=i)
        local_midnight = datetime(d.year, d.month, d.day, tzinfo=timezone.utc) - TZ_DELTA
        is_today = d == today_local
        final_block = i >= days - 9           # a slightly heavier last week → load ratio climbs
        fitness = min(1.0, fitness + 0.003)    # slow long-term improvement

        # ---- sleep (the night before this day) ----
        onset = local_midnight - timedelta(minutes=rng.gauss(35, 40))
        dur_h = clamp(rng.gauss(7.3 - (0.6 if d.weekday() in (4, 5) else 0), 0.75), 4.8, 9.6)
        wake = onset + timedelta(hours=dur_h)
        awake_h = clamp(rng.gauss(0.55, 0.2), 0.15, 1.5)
        asleep_h = dur_h - awake_h
        deep = asleep_h * clamp(rng.gauss(0.2, 0.03), 0.12, 0.28)
        rem = asleep_h * clamp(rng.gauss(0.24, 0.035), 0.15, 0.32)
        light = asleep_h - deep - rem
        need_h = 7.9 + prev_strain * 0.04
        debt_h = clamp(need_h - asleep_h + rng.gauss(0, 0.2), 0, 2.5)
        perf = clamp(round(100 * asleep_h / need_h), 45, 100)
        resp = round(clamp(rng.gauss(15.2 + (0.9 if prev_strain > 16 else 0), 0.35), 13, 18.5), 1)
        sleep_id = uid()
        cycle_id += 1

        # ---- recovery: driven by yesterday's strain, sleep, fitness, noise ----
        strain_pen = (prev_strain - 11) * 2.4
        sleep_pen = (7.2 - asleep_h) * 7
        hrv = clamp(rng.gauss(hrv_base + 10 * fitness - strain_pen * 0.9 - sleep_pen * 0.6, 8), 28, 140)
        rhr = clamp(rng.gauss(rhr_base - 3 * fitness + strain_pen * 0.25 + sleep_pen * 0.15, 2.2), 42, 75)
        rec_score = clamp(round(50 + (hrv - 68) * 1.25 - (rhr - 53) * 1.6 + rng.gauss(0, 7)), 1, 99)

        sleeps.append({
            "id": sleep_id, "cycle_id": cycle_id, "v1_id": None, "user_id": 1,
            "created_at": iso(wake + timedelta(minutes=12)), "updated_at": iso(wake + timedelta(minutes=40)),
            "start": iso(onset), "end": iso(wake), "timezone_offset": TZ, "nap": False, "score_state": "SCORED",
            "score": {
                "stage_summary": {
                    "total_in_bed_time_milli": int(dur_h * 3.6e6), "total_awake_time_milli": int(awake_h * 3.6e6),
                    "total_no_data_time_milli": 0, "total_light_sleep_time_milli": int(light * 3.6e6),
                    "total_slow_wave_sleep_time_milli": int(deep * 3.6e6), "total_rem_sleep_time_milli": int(rem * 3.6e6),
                    "sleep_cycle_count": int(asleep_h / 1.5), "disturbance_count": rng.randint(3, 14),
                },
                "sleep_needed": {
                    "baseline_milli": int(7.9 * 3.6e6), "need_from_sleep_debt_milli": int(debt_h * 3.6e6),
                    "need_from_recent_strain_milli": int(prev_strain * 0.04 * 3.6e6), "need_from_recent_nap_milli": 0,
                },
                "respiratory_rate": resp, "sleep_performance_percentage": perf,
                "sleep_consistency_percentage": clamp(round(rng.gauss(74, 9)), 35, 98),
                "sleep_efficiency_percentage": round(100 * asleep_h / dur_h, 1),
            },
        })
        recoveries.append({
            "cycle_id": cycle_id, "sleep_id": sleep_id, "user_id": 1,
            "created_at": iso(wake + timedelta(minutes=15)), "updated_at": iso(wake + timedelta(minutes=45)),
            "score_state": "SCORED",
            "score": {"user_calibrating": i < 4, "recovery_score": float(rec_score),
                      "resting_heart_rate": float(round(rhr)), "hrv_rmssd_milli": round(hrv, 4),
                      "spo2_percentage": round(clamp(rng.gauss(96.4, 0.6), 93, 99), 3),
                      "skin_temp_celsius": round(clamp(rng.gauss(33.4, 0.35), 32, 35), 3)},
        })

        # ---- workouts ----
        day_strain = clamp(rng.gauss(5.5, 1.2), 2.5, 9) if d.weekday() != 4 else clamp(rng.gauss(4.2, 0.8), 2.5, 6)   # Fridays off
        day_end = min(now, wake + timedelta(hours=16.5)) if is_today else wake + timedelta(hours=16.5)
        for sport, p in PLAN[d.weekday()]:
            if d.weekday() == 4 or rng.random() > (p + (0.1 if final_block else 0)):
                continue
            minutes, (s_lo, s_hi), inten, has_dist = SPORTS[sport]
            w_start = local_midnight + timedelta(hours=rng.choice([7, 12, 17, 18, 19]), minutes=rng.randint(0, 50))
            dur = max(15, rng.gauss(minutes, minutes * 0.18))
            w_end = w_start + timedelta(minutes=dur)
            if w_end > now:
                continue
            strain = clamp(rng.uniform(s_lo, s_hi) + (0.6 if final_block else 0), 2, 20.5)
            day_strain = clamp(day_strain + strain * 0.62, 0, 21)
            total_ms = dur * 60000
            w = [max(0.02, 0.5 - inten * 0.45), 0.25, 0.2 + inten * 0.1, 0.1 + inten * 0.2, inten * 0.25, inten * 0.08]
            zones = [int(total_ms * x / sum(w)) for x in w]
            workouts.append({
                "id": uid(), "v1_id": None, "user_id": 1,
                "created_at": iso(w_end + timedelta(minutes=5)), "updated_at": iso(w_end + timedelta(minutes=8)),
                "start": iso(w_start), "end": iso(w_end), "timezone_offset": TZ, "sport_name": sport,
                "score_state": "SCORED", "sport_id": 0,
                "score": {
                    "strain": round(strain, 6), "average_heart_rate": int(100 + inten * 55 + rng.gauss(0, 5)),
                    "max_heart_rate": int(135 + inten * 55 + rng.gauss(0, 5)),
                    "kilojoule": round(dur * (18 + inten * 45), 3), "percent_recorded": 1.0,
                    "distance_meter": round(dur * (170 if sport == "running" else 420) * rng.uniform(0.85, 1.1), 1) if has_dist else None,
                    "altitude_gain_meter": round(rng.uniform(20, 300), 1) if has_dist else None,
                    "altitude_change_meter": None,
                    "zone_durations": dict(zip(["zone_zero_milli", "zone_one_milli", "zone_two_milli",
                                                "zone_three_milli", "zone_four_milli", "zone_five_milli"], zones)),
                },
            })
        if is_today:
            day_strain = min(day_strain, 3 + 8 * clamp((now - wake).total_seconds() / 57600, 0, 1))

        cycles.append({
            "id": cycle_id, "user_id": 1,
            "created_at": iso(wake + timedelta(minutes=10)), "updated_at": iso(wake + timedelta(hours=1)),
            "start": iso(onset), "end": None if is_today else iso(onset + timedelta(days=1)),
            "timezone_offset": TZ, "score_state": "SCORED",
            "score": {"strain": round(day_strain, 6), "kilojoule": round(8000 + day_strain * 420, 3),
                      "average_heart_rate": int(62 + day_strain * 1.3), "max_heart_rate": int(120 + day_strain * 3.2)},
        })
        prev_strain = day_strain

    # most-recent first, like the API returns
    by_newest = lambda items: sorted(items, key=lambda x: x["created_at"], reverse=True)
    return {
        "profile": {"user_id": 1, "email": "alex@example.com", "first_name": "Alex", "last_name": "Demo"},
        "body": {"height_meter": 1.78, "weight_kilogram": 74.5, "max_heart_rate": 194},
        "recovery": by_newest(recoveries), "cycles": by_newest(cycles),
        "sleep": by_newest(sleeps), "workouts": by_newest(workouts),
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("out_dir", nargs="?", default="demo")
    ap.add_argument("--days", type=int, default=420)
    ap.add_argument("--seed", type=int, default=23)
    args = ap.parse_args()
    os.makedirs(args.out_dir, exist_ok=True)
    data = generate(args.days, args.seed)
    path = os.path.join(args.out_dir, "whoop_data.json")
    with open(path, "w") as f:
        json.dump(data, f)
    print(f"Wrote {path} — {len(data['cycles'])} days, {len(data['workouts'])} workouts (synthetic)")
