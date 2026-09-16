"""Rebuild dashboard_data.json and index.html from whoop_data.json.

Run `python3 whoop.py` first to refresh whoop_data.json, then run this.
Or just run refresh.sh, which does both.

Usage: python3 build_dashboard.py [data_dir]   (default: current directory)
"""
import json, math, os
from datetime import datetime, timedelta, timezone
from statistics import mean, pstdev
from collections import Counter, defaultdict
from env_config import atomic_write, atomic_write_json

def parse(s): return datetime.fromisoformat(s.replace('Z', '+00:00'))
def day(s): return parse(s).date().isoformat()

def iso_week_monday(week_key):
    """'2026-W38' -> the actual calendar date of that ISO week's Monday, computed
    from the week number itself (not from 'first record seen'), so it's correct
    even if there's a data gap early in the week."""
    year, week = week_key.split('-W')
    return datetime.fromisocalendar(int(year), int(week), 1).date().isoformat()

def iso_week_key(dt):
    iso = dt.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"

def last_n_iso_weeks(end_date, n):
    """The n consecutive Mon-Sun ISO week keys ending with end_date's own (possibly
    partial) week, oldest first — so a week with zero events still gets a slot
    instead of being skipped, and every weekly chart shares the same Mon-Sun grid."""
    monday = datetime.fromisocalendar(*end_date.isocalendar()[:2], 1).date()
    keys = []
    for _ in range(n):
        keys.append(iso_week_key(datetime(monday.year, monday.month, monday.day)))
        monday -= timedelta(days=7)
    return list(reversed(keys))

def sport_label(name):
    m = {'weightlifting_msk': 'Weightlifting', 'weightlifting': 'Weightlifting', 'activity': 'Other activity'}
    return m.get(name, (name or 'other').replace('_', ' ').title())

def month_range(start_m, end_m):
    """All 'YYYY-MM' keys from start_m to end_m inclusive, so months with zero
    records still get a slot (a real gap) instead of being silently skipped."""
    y, mo = int(start_m[:4]), int(start_m[5:7])
    ey, emo = int(end_m[:4]), int(end_m[5:7])
    out = []
    while (y, mo) <= (ey, emo):
        out.append(f"{y:04d}-{mo:02d}")
        mo += 1
        if mo > 12:
            mo = 1
            y += 1
    return out

def series_full(items, val_fn, rnd=1):
    out = {}
    for it in items:
        v = val_fn(it)
        if v is not None:
            out[day(it['created_at'])] = round(v, rnd)
    days = sorted(out.keys())
    return [{'date': dd, 'v': out[dd]} for dd in days]


def build_acwr(strain_by_day):
    """Acute:Chronic Workload Ratio — sports-science injury-risk metric, not in the WHOOP app.
    Acute = trailing 7d avg strain, Chronic = trailing 28d avg strain."""
    days = sorted(strain_by_day.keys())
    out = []
    for i, d in enumerate(days):
        if i < 27:
            continue
        acute = mean(strain_by_day[days[j]] for j in range(i - 6, i + 1))
        chronic = mean(strain_by_day[days[j]] for j in range(i - 27, i + 1))
        if chronic == 0:
            continue
        out.append({'date': d, 'v': round(acute / chronic, 2)})
    return out


def build_monotony(strain_by_day):
    """Foster training monotony & load-strain, by ISO week. Flags weeks where the
    load x monotony combo is unusually high relative to this athlete's OWN recent
    weeks (not a fixed textbook cutoff, which doesn't discriminate well per-person)."""
    week_strain = defaultdict(list)
    week_start = {}
    for d in sorted(strain_by_day.keys()):
        dt = datetime.fromisoformat(d)
        iso = dt.isocalendar()
        key = f"{iso[0]}-W{iso[1]:02d}"
        week_strain[key].append(strain_by_day[d])
        if key not in week_start or d < week_start[key]:
            week_start[key] = d
    weeks = sorted(week_strain.keys())
    out = []
    for wk in weeks:
        vals = week_strain[wk]
        if len(vals) < 5:
            continue
        m = mean(vals)
        sd = pstdev(vals)
        monotony = round(m / sd, 2) if sd > 0 else None
        load = round(sum(vals), 1)
        load_strain = round(monotony * load, 0) if monotony else None
        out.append({'week': wk, 'start': week_start[wk], 'monotony': monotony, 'load': load, 'load_strain': load_strain})
    return out


def build_sport_recovery_cost(wo, recovery_by_day):
    """Average next-calendar-day recovery after a day whose hardest session was sport X,
    vs this athlete's overall average recovery. Not something the WHOOP app computes."""
    overall_avg = mean(recovery_by_day.values())
    day_workouts = defaultdict(list)
    for w in wo:
        day_workouts[day(w['created_at'])].append((sport_label(w['sport_name']), w['score']['strain']))
    by_sport = defaultdict(list)
    for d, sessions in day_workouts.items():
        dominant = max(sessions, key=lambda x: x[1])[0]
        next_day = (datetime.fromisoformat(d) + timedelta(days=1)).date().isoformat()
        if next_day in recovery_by_day:
            by_sport[dominant].append(recovery_by_day[next_day])
    results = []
    for sport, vals in by_sport.items():
        if len(vals) >= 8:
            results.append({'sport': sport, 'n': len(vals), 'avg_next_day_recovery': round(mean(vals), 1),
                             'delta': round(mean(vals) - overall_avg, 1)})
    results.sort(key=lambda x: x['delta'])
    return {'overall_avg_recovery': round(overall_avg, 1), 'sports': results}


def build_anomalies(hrv_by_day, rhr_by_day, rr_by_day):
    """Flag days where HRV, RHR or respiratory rate moved >1.5 SD from this athlete's
    own trailing 30-day baseline. HRV/RHR deviation is a standard overreaching signal
    in sports science; elevated overnight respiratory rate specifically has published
    evidence (wearable studies during COVID-19) as an early illness-onset signal,
    often showing up a day or two before other symptoms. None of this is a diagnosis —
    it's a same-methodology extension of the HRV/RHR check to a third vital sign
    WHOOP already measures but doesn't flag on its own."""
    days = sorted(set(hrv_by_day) & set(rhr_by_day) & set(rr_by_day))
    flags = []
    for i, d in enumerate(days):
        if i < 30:
            continue
        window = days[i - 30:i]
        hrv_hist = [hrv_by_day[w] for w in window]
        rhr_hist = [rhr_by_day[w] for w in window]
        rr_hist = [rr_by_day[w] for w in window]
        m_hrv, sd_hrv = mean(hrv_hist), pstdev(hrv_hist)
        m_rhr, sd_rhr = mean(rhr_hist), pstdev(rhr_hist)
        m_rr, sd_rr = mean(rr_hist), pstdev(rr_hist)
        if sd_hrv == 0 or sd_rhr == 0 or sd_rr == 0:
            continue
        z_hrv = (hrv_by_day[d] - m_hrv) / sd_hrv
        z_rhr = (rhr_by_day[d] - m_rhr) / sd_rhr
        z_rr = (rr_by_day[d] - m_rr) / sd_rr
        if z_hrv <= -1.5 or z_rhr >= 1.5 or z_rr >= 1.5:
            flags.append({'date': d, 'z_hrv': round(z_hrv, 2), 'z_rhr': round(z_rhr, 2), 'z_rr': round(z_rr, 2),
                          'hrv': hrv_by_day[d], 'rhr': rhr_by_day[d], 'rr': round(rr_by_day[d], 2),
                          # the edge of this person's normal range (same 1.5 SD cut, pre-converted
                          # into real units) so the page can show plain numbers instead of z-scores
                          'hrv_low': round(m_hrv - 1.5 * sd_hrv), 'rhr_high': round(m_rhr + 1.5 * sd_rhr),
                          'rr_high': round(m_rr + 1.5 * sd_rr, 2)})
    return flags


# ---- Readiness -------------------------------------------------------------------
# Method, from HRV-guided training research (Javaloyes et al. 2019; the Carrasco-Poyatos
# et al. 2020 trial protocol, which follows Plews et al. 2012 and Kiviniemi et al. 2007;
# Alfonso et al. 2025 for adding resting HR). Sources and limits are listed in the README.
#   1. Each marker is smoothed with a rolling average — 7 days for ln(RMSSD) HRV and
#      resting HR (as in the trials), 3 nights for sleep performance (a design choice).
#   2. It's compared with the person's own baseline: the rolling values over the 60 days
#      before the current 7-day window (trials used ~4 weeks). "Normal" = baseline
#      mean ± 0.5 SD, the smallest worthwhile change (SWC) used in those trials.
#   3. Markers are expressed in SD units (resting HR sign-flipped so higher = better),
#      clipped to ±3, and combined with equal (unit) weights — no study has validated
#      specific weights, and unit weighting is the robust default (Dawes 1979).
#   4. Score = 50 + 25 × mean, clamped 0–100: 50 = exactly your normal. At or above
#      +0.5 SD (63+) = Peak, below −0.5 SD (<38) = Recovery, in between = Grind —
#      the same "within / above / below SWC" rule the trials used to prescribe intensity.
READY_WINDOWS = {'hrv': 7, 'rhr': 7, 'sleep': 3}
READY_MIN_IN_WINDOW = {'hrv': 4, 'rhr': 4, 'sleep': 2}
READY_BASELINE_DAYS = 60
READY_MIN_BASELINE = 21
READY_SWC = 0.5


def _rolling_by_calendar(by_day, window, min_n, transform=lambda v: v):
    """Rolling mean over calendar days (not records), so gaps in wear don't stretch a
    '7-day' average across weeks. Returns {date: mean} where enough values exist."""
    from datetime import date as _date
    dates = sorted(by_day)
    parsed = {d: _date.fromisoformat(d) for d in dates}
    out = {}
    start = 0
    for i, d in enumerate(dates):
        while (parsed[d] - parsed[dates[start]]).days >= window:
            start += 1
        vals = [transform(by_day[x]) for x in dates[start:i + 1]]
        if len(vals) >= min_n:
            out[d] = mean(vals)
    return out


def build_readiness(hrv_by_day, rhr_by_day, sleep_perf_by_day):
    from datetime import date as _date
    rolled = {
        'hrv': _rolling_by_calendar({k: v for k, v in hrv_by_day.items() if v and v > 0},
                                    READY_WINDOWS['hrv'], READY_MIN_IN_WINDOW['hrv'], math.log),
        'rhr': _rolling_by_calendar(rhr_by_day, READY_WINDOWS['rhr'], READY_MIN_IN_WINDOW['rhr']),
        'sleep': _rolling_by_calendar(sleep_perf_by_day, READY_WINDOWS['sleep'], READY_MIN_IN_WINDOW['sleep']),
    }
    sign = {'hrv': 1, 'rhr': -1, 'sleep': 1}

    def baseline(marker, d):
        end = _date.fromisoformat(d) - timedelta(days=READY_WINDOWS['hrv'])       # exclude current 7-day window
        start = end - timedelta(days=READY_BASELINE_DAYS)
        vals = [v for k, v in rolled[marker].items() if start < _date.fromisoformat(k) <= end]
        if len(vals) < READY_MIN_BASELINE:
            return None
        m, sd = mean(vals), pstdev(vals)
        # numerical floor: if someone's rolling values barely move, a near-zero SD would turn
        # trivial wobbles into huge swings — never treat less than 1% of the mean as meaningful
        sd = max(sd, 0.01 if marker == 'hrv' else 0.01 * abs(m))   # HRV is on a ln scale: 0.01 ≈ 1%
        return (m, sd) if sd > 0 else None

    series = []
    latest = None
    for d in sorted(rolled['hrv']):
        zs, parts = {}, {}
        for marker in ('hrv', 'rhr', 'sleep'):
            if d not in rolled[marker]:
                continue
            b = baseline(marker, d)
            if not b:
                continue
            m, sd = b
            z = max(-3.0, min(3.0, sign[marker] * (rolled[marker][d] - m) / sd))
            zs[marker] = z
            lo, hi = m - READY_SWC * sd, m + READY_SWC * sd
            if marker == 'hrv':   # back from ln(ms) to ms for display
                parts[marker] = {'value': round(math.exp(rolled[marker][d])), 'normal': [round(math.exp(lo)), round(math.exp(hi))]}
            elif marker == 'rhr':
                parts[marker] = {'value': round(rolled[marker][d], 1), 'normal': [round(lo, 1), round(hi, 1)]}
            else:
                parts[marker] = {'value': round(rolled[marker][d], 1), 'normal': [round(lo, 1), round(hi, 1)]}
        if 'hrv' not in zs:        # HRV is the evidence-backed core; no score without it
            continue
        composite = mean(zs.values())
        score = max(0, min(100, math.floor(50 + 25 * composite + 0.5)))   # half-up, never banker's rounding
        state = 'peak' if composite >= READY_SWC else 'recovery' if composite < -READY_SWC else 'grind'
        series.append({'date': d, 'v': score})
        latest = {'date': d, 'score': score, 'state': state, 'z': {k: round(v, 2) for k, v in zs.items()},
                  'components': parts}
    if latest is None:
        return None, []
    latest['thresholds'] = {'peak': math.floor(50 + 25 * READY_SWC + 0.5), 'recovery': math.floor(50 - 25 * READY_SWC + 0.5)}
    return latest, series


def build_sleep_composition(sleep, now):
    """Weekly average REM/deep(SWS)/light sleep hours, last 8 weeks. Computed here
    (not client-side) so the week key is zero-padded and sorts correctly — the same
    ISO-week convention used everywhere else on this page."""
    week_rem, week_sws, week_light = defaultdict(list), defaultdict(list), defaultdict(list)
    for s in sleep:
        key = iso_week_key(parse(s['created_at']))
        stage = s['score']['stage_summary']
        week_rem[key].append(stage['total_rem_sleep_time_milli'] / 3600000)
        week_sws[key].append(stage['total_slow_wave_sleep_time_milli'] / 3600000)
        week_light[key].append(stage['total_light_sleep_time_milli'] / 3600000)
    weeks = sorted(week_rem.keys())[-8:]
    current_key = iso_week_key(now)
    return [{
        'week': wk,
        'start': iso_week_monday(wk),
        'rem_h': round(mean(week_rem[wk]), 2),
        'sws_h': round(mean(week_sws[wk]), 2),
        'light_h': round(mean(week_light[wk]), 2),
        'is_current': wk == current_key,
    } for wk in weeks]


def build_zone_distribution(wo, now):
    """Weekly time-in-heart-rate-zone breakdown from workout.score.zone_durations
    (WHOOP's own zone_zero..zone_five, each a band of % of max heart rate — WHOOP
    records this per workout but never aggregates it into a trend). Bucketed into
    easy (zone 0-1), moderate (zone 2-3) and hard (zone 4-5) for a polarized-training
    read: many endurance coaches use roughly 80% easy / 20% moderate-hard as a
    reference split, not a hard medical rule."""
    ZONE_KEYS_EASY = ['zone_zero_milli', 'zone_one_milli']
    ZONE_KEYS_MOD = ['zone_two_milli', 'zone_three_milli']
    ZONE_KEYS_HARD = ['zone_four_milli', 'zone_five_milli']

    def bucket_hours(zd):
        easy = sum((zd.get(k) or 0) for k in ZONE_KEYS_EASY) / 3600000
        mod = sum((zd.get(k) or 0) for k in ZONE_KEYS_MOD) / 3600000
        hard = sum((zd.get(k) or 0) for k in ZONE_KEYS_HARD) / 3600000
        return easy, mod, hard

    week_totals = defaultdict(lambda: [0.0, 0.0, 0.0])
    all_time = [0.0, 0.0, 0.0]
    for w in wo:
        zd = w['score'].get('zone_durations')
        if not zd:
            continue
        easy, mod, hard = bucket_hours(zd)
        key = iso_week_key(parse(w['created_at']))
        week_totals[key][0] += easy
        week_totals[key][1] += mod
        week_totals[key][2] += hard
        all_time[0] += easy
        all_time[1] += mod
        all_time[2] += hard

    weeks = sorted(week_totals.keys())
    current_key = iso_week_key(now)
    weekly = [{'week': wk, 'start': iso_week_monday(wk),
               'easy_h': round(week_totals[wk][0], 2),
               'mod_h': round(week_totals[wk][1], 2),
               'hard_h': round(week_totals[wk][2], 2),
               'is_current': wk == current_key} for wk in weeks]
    total_h = sum(all_time)
    all_time_pct = {
        'easy_pct': round(100 * all_time[0] / total_h, 1) if total_h else 0,
        'mod_pct': round(100 * all_time[1] / total_h, 1) if total_h else 0,
        'hard_pct': round(100 * all_time[2] / total_h, 1) if total_h else 0,
        'total_h': round(total_h, 1),
    }
    return {'weekly': weekly, 'all_time': all_time_pct}


def build_rest_day_stat(cyc):
    """Days since the last day with strain at or below this athlete's own 15th
    percentile — a 'true rest day' defined against their own history, not an
    arbitrary fixed number. Excludes the current in-progress cycle (no 'end' yet)
    since its strain hasn't finished accumulating."""
    completed = [c for c in cyc if c.get('end') is not None]
    if len(completed) < 20:
        return None
    strains_sorted = sorted(c['score']['strain'] for c in completed)
    threshold = strains_sorted[int(len(strains_sorted) * 0.15)]
    last_rest_idx = None
    for i in range(len(completed) - 1, -1, -1):
        if completed[i]['score']['strain'] <= threshold:
            last_rest_idx = i
            break
    if last_rest_idx is None:
        return None
    days_since = len(completed) - 1 - last_rest_idx
    return {
        'last_rest_date': day(completed[last_rest_idx]['created_at']),
        'days_since': days_since,
        'threshold': round(threshold, 1),
    }


def build_today_snapshot(cyc, wo):
    """Right-now context: today's cycle strain (still accumulating if the day isn't
    over) and full detail on every workout logged today, including the same
    easy/moderate/hard HR-zone breakdown used in the weekly zone chart, scoped to
    just that session. Not historical — this is what happened today, specifically."""
    if not cyc:
        return None
    latest_cycle = cyc[-1]
    today = day(latest_cycle['created_at'])
    in_progress = latest_cycle.get('end') is None

    ZONE_EASY = ['zone_zero_milli', 'zone_one_milli']
    ZONE_MOD = ['zone_two_milli', 'zone_three_milli']
    ZONE_HARD = ['zone_four_milli', 'zone_five_milli']

    todays_workouts = []
    for w in wo:
        if day(w['created_at']) != today:
            continue
        sc = w['score']
        zd = sc.get('zone_durations') or {}
        zone_easy = sum((zd.get(k) or 0) for k in ZONE_EASY) / 60000
        zone_mod = sum((zd.get(k) or 0) for k in ZONE_MOD) / 60000
        zone_hard = sum((zd.get(k) or 0) for k in ZONE_HARD) / 60000
        todays_workouts.append({
            'sport': sport_label(w['sport_name']),
            'start': w['start'],
            'end': w['end'],
            'dur_min': round((parse(w['end']) - parse(w['start'])).total_seconds() / 60),
            'strain': round(sc['strain'], 1),
            'avg_hr': sc.get('average_heart_rate'),
            'max_hr': sc.get('max_heart_rate'),
            'kcal': round(sc['kilojoule'] / 4.184) if sc.get('kilojoule') else None,
            'dist_km': round(sc['distance_meter'] / 1000, 2) if sc.get('distance_meter') else None,
            'zone_easy_min': round(zone_easy),
            'zone_mod_min': round(zone_mod),
            'zone_hard_min': round(zone_hard),
        })
    todays_workouts.sort(key=lambda w: w['start'])

    return {
        'date': today,
        'cycle_start': latest_cycle['start'],
        'strain_so_far': round(latest_cycle['score']['strain'], 1),
        'in_progress': in_progress,
        'workouts': todays_workouts,
    }


def build_summary(d):
    rec = sorted([r for r in d['recovery'] if r['score_state'] == 'SCORED'], key=lambda r: r['created_at'])
    cyc = sorted([c for c in d['cycles'] if c['score_state'] == 'SCORED'], key=lambda c: c['created_at'])
    sleep = sorted([s for s in d['sleep'] if s['score_state'] == 'SCORED' and not s['nap']], key=lambda s: s['created_at'])
    wo = sorted([w for w in d['workouts'] if w['score_state'] == 'SCORED' and w.get('score')], key=lambda w: w['start'])

    if not rec or not cyc or not sleep:
        raise RuntimeError(
            "No scored WHOOP data yet — you need at least one full night of sleep and a "
            "morning recovery score before this dashboard has anything to show. Wear your "
            "WHOOP overnight, let it sync, then run this again."
        )

    def day_series(items, val_fn):
        out = {}
        for it in items:
            out[day(it['created_at'])] = val_fn(it)
        days = sorted(out.keys())[-30:]
        return [{'date': dd, 'v': round(out[dd], 1)} for dd in days]

    latest_rec, latest_cyc, latest_sleep = rec[-1], cyc[-1], sleep[-1]
    sn = latest_sleep['score']['sleep_needed']
    debt_h = sn['need_from_sleep_debt_milli'] / 3600000
    last30_rec, last30_cyc, last30_sleep = rec[-30:], cyc[-30:], sleep[-30:]
    last7_cyc = cyc[-7:]

    sports = Counter(w['sport_name'] for w in wo)
    now = parse(cyc[-1]['created_at'])
    week_wo_counts = Counter()
    for w in wo:
        week_wo_counts[iso_week_key(parse(w['created_at']))] += 1
    last8_weeks = last_n_iso_weeks(now.date(), 8)
    wpw = [week_wo_counts.get(wk, 0) for wk in last8_weeks]
    wpw_starts = [iso_week_monday(wk) for wk in last8_weeks]

    full = {
        'recovery': series_full(rec, lambda r: r['score']['recovery_score'], 0),
        'strain': series_full(cyc, lambda c: c['score']['strain'], 1),
        'sleep_performance': series_full(sleep, lambda s: s['score']['sleep_performance_percentage'], 0),
        'sleep_consistency': series_full(sleep, lambda s: s['score']['sleep_consistency_percentage'], 0),
        'sleep_efficiency': series_full(sleep, lambda s: s['score']['sleep_efficiency_percentage'], 1),
        'hrv': series_full(rec, lambda r: r['score']['hrv_rmssd_milli'], 1),
        'rhr': series_full(rec, lambda r: r['score']['resting_heart_rate'], 0),
        'spo2': series_full(rec, lambda r: r['score'].get('spo2_percentage'), 1),
        'skin_temp': series_full(rec, lambda r: r['score'].get('skin_temp_celsius'), 2),
        'respiratory_rate': series_full(sleep, lambda s: s['score'].get('respiratory_rate'), 1),
        'time_in_bed_h': series_full(sleep, lambda s: s['score']['stage_summary']['total_in_bed_time_milli'] / 3600000, 2),
        'rem_h': series_full(sleep, lambda s: s['score']['stage_summary']['total_rem_sleep_time_milli'] / 3600000, 2),
        'sws_h': series_full(sleep, lambda s: s['score']['stage_summary']['total_slow_wave_sleep_time_milli'] / 3600000, 2),
        'light_h': series_full(sleep, lambda s: s['score']['stage_summary']['total_light_sleep_time_milli'] / 3600000, 2),
        'sleep_debt': series_full(sleep, lambda s: s['score']['sleep_needed']['need_from_sleep_debt_milli'] / 3600000, 2),
    }

    wlog = []
    for w in wo:
        sc = w['score']
        dur_min = (parse(w['end']) - parse(w['start'])).total_seconds() / 60
        wlog.append({
            'date': day(w['created_at']), 'sport': sport_label(w['sport_name']),
            'strain': round(sc['strain'], 1), 'dur_min': round(dur_min),
            'avg_hr': sc.get('average_heart_rate'), 'max_hr': sc.get('max_heart_rate'),
            'kcal': round(sc['kilojoule'] / 4.184) if sc.get('kilojoule') else None,
            'dist_km': round(sc['distance_meter'] / 1000, 2) if sc.get('distance_meter') else None,
        })
    workout_log = list(reversed(wlog))

    month_rec, month_strain, month_sleep, month_wo, month_days = defaultdict(list), defaultdict(list), defaultdict(list), Counter(), defaultdict(set)
    for r in rec: month_rec[day(r['created_at'])[:7]].append(r['score']['recovery_score'])
    for c in cyc:
        m = day(c['created_at'])[:7]
        month_strain[m].append(c['score']['strain'])
        month_days[m].add(day(c['created_at']))
    for s in sleep: month_sleep[day(s['created_at'])[:7]].append(s['score']['sleep_performance_percentage'])
    for w in wo: month_wo[day(w['created_at'])[:7]] += 1
    data_months = sorted(set(list(month_rec.keys()) + list(month_strain.keys())))
    MIN_DAYS_FULL = 10  # months with fewer tracked days than this render faded, as partial
    monthly = []
    for m in (month_range(data_months[0], data_months[-1]) if data_months else []):
        has_data = m in month_rec or m in month_strain
        days_n = len(month_days.get(m, ()))
        monthly.append({
            'month': m,
            'recovery': round(mean(month_rec[m]), 1) if month_rec.get(m) else None,
            'strain': round(mean(month_strain[m]), 1) if month_strain.get(m) else None,
            'sleep_performance': round(mean(month_sleep[m]), 1) if month_sleep.get(m) else None,
            'workouts': month_wo.get(m, 0),
            'days': days_n,
            'partial': has_data and days_n < MIN_DAYS_FULL,
        })
    months_with_data = sum(1 for m in monthly if m['recovery'] is not None or m['strain'] is not None)

    wd_rec, wd_strain = defaultdict(list), defaultdict(list)
    WD = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    for r in rec: wd_rec[parse(r['created_at']).weekday()].append(r['score']['recovery_score'])
    for c in cyc: wd_strain[parse(c['created_at']).weekday()].append(c['score']['strain'])
    weekday = [{
        'day': WD[i],
        'recovery': round(mean(wd_rec[i]), 1) if wd_rec.get(i) else None,
        'strain': round(mean(wd_strain[i]), 1) if wd_strain.get(i) else None,
    } for i in range(7)]

    best_rec = max(rec, key=lambda r: r['score']['recovery_score'])
    worst_rec = min(rec, key=lambda r: r['score']['recovery_score'])
    best_hrv = max(rec, key=lambda r: r['score']['hrv_rmssd_milli'])
    lowest_rhr = min(rec, key=lambda r: r['score']['resting_heart_rate'])
    biggest_strain_cyc = max(cyc, key=lambda c: c['score']['strain'])
    longest_sleep = max(sleep, key=lambda s: s['score']['stage_summary']['total_in_bed_time_milli'])
    biggest_strain_wo = max(wo, key=lambda w: w['score']['strain']) if wo else None

    streak = 0
    for r in reversed(rec):
        if r['score']['recovery_score'] >= 67: streak += 1
        else: break

    wk_counts = Counter()
    for w in wo:
        iso = parse(w['created_at']).date().isocalendar()
        wk_counts[(iso[0], iso[1])] += 1
    best_week_count = max(wk_counts.values(), default=0)

    total_kcal = sum(w['score']['kilojoule'] for w in wo if w['score'].get('kilojoule')) / 4.184
    total_dist_km = sum(w['score']['distance_meter'] for w in wo if w['score'].get('distance_meter')) / 1000
    total_training_hours = sum((parse(w['end']) - parse(w['start'])).total_seconds() for w in wo) / 3600

    strain_by_day = {day(c['created_at']): c['score']['strain'] for c in cyc}
    recovery_by_day = {day(r['created_at']): r['score']['recovery_score'] for r in rec}
    hrv_by_day = {day(r['created_at']): r['score']['hrv_rmssd_milli'] for r in rec}
    rhr_by_day = {day(r['created_at']): r['score']['resting_heart_rate'] for r in rec}
    rr_by_day = {day(s['created_at']): s['score']['respiratory_rate'] for s in sleep if s['score'].get('respiratory_rate') is not None}

    acwr = build_acwr(strain_by_day)
    monotony = build_monotony(strain_by_day)
    sport_recovery_cost = build_sport_recovery_cost(wo, recovery_by_day)
    sleep_composition = build_sleep_composition(sleep, now)
    zone_distribution = build_zone_distribution(wo, now)
    rest_day_stat = build_rest_day_stat(cyc)
    today_snapshot = build_today_snapshot(cyc, wo)
    anomalies = build_anomalies(hrv_by_day, rhr_by_day, rr_by_day)
    sleep_perf_by_day = {day(s['created_at']): s['score']['sleep_performance_percentage'] for s in sleep}
    readiness, readiness_series = build_readiness(hrv_by_day, rhr_by_day, sleep_perf_by_day)
    full['readiness'] = readiness_series
    cutoff_14d = (parse(latest_rec['created_at']) - timedelta(days=14)).date().isoformat()
    recent_anomalies = [a for a in anomalies if a['date'] >= cutoff_14d]

    records = {
        'best_recovery': {'v': best_rec['score']['recovery_score'], 'date': day(best_rec['created_at'])},
        'worst_recovery': {'v': worst_rec['score']['recovery_score'], 'date': day(worst_rec['created_at'])},
        'best_hrv': {'v': round(best_hrv['score']['hrv_rmssd_milli'], 1), 'date': day(best_hrv['created_at'])},
        'lowest_rhr': {'v': lowest_rhr['score']['resting_heart_rate'], 'date': day(lowest_rhr['created_at'])},
        'biggest_strain_day': {'v': round(biggest_strain_cyc['score']['strain'], 1), 'date': day(biggest_strain_cyc['created_at'])},
        'biggest_strain_workout': ({'v': round(biggest_strain_wo['score']['strain'], 1), 'date': day(biggest_strain_wo['created_at']), 'sport': sport_label(biggest_strain_wo['sport_name'])}
                                    if biggest_strain_wo else None),
        'longest_sleep_h': {'v': round(longest_sleep['score']['stage_summary']['total_in_bed_time_milli'] / 3600000, 1), 'date': day(longest_sleep['created_at'])},
        'current_green_streak_days': streak,
        'best_week_sessions': best_week_count,
        'total_kcal': round(total_kcal),
        'total_dist_km': round(total_dist_km, 1),
        'total_training_hours': round(total_training_hours),
    }

    now_utc = datetime.now(timezone.utc)
    return {
        'profile': {'name': d['profile']['first_name']},
        'asOf': latest_rec['created_at'],
        'generated_at': now_utc.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z',
        'latest': {
            'recovery_score': latest_rec['score']['recovery_score'],
            'hrv_rmssd_milli': latest_rec['score']['hrv_rmssd_milli'],
            'resting_heart_rate': latest_rec['score']['resting_heart_rate'],
            'spo2_percentage': latest_rec['score'].get('spo2_percentage'),
            'strain_to_date': latest_cyc['score']['strain'],
            'sleep_performance_percentage': latest_sleep['score']['sleep_performance_percentage'],
            'sleep_consistency_percentage': latest_sleep['score']['sleep_consistency_percentage'],
            'sleep_efficiency_percentage': latest_sleep['score']['sleep_efficiency_percentage'],
            'sleep_debt_hours': round(debt_h, 2),
            'respiratory_rate': latest_sleep['score'].get('respiratory_rate'),
        },
        'avg30': {
            'recovery_score': round(mean([r['score']['recovery_score'] for r in last30_rec]), 1),
            'hrv_rmssd_milli': round(mean([r['score']['hrv_rmssd_milli'] for r in last30_rec]), 1),
            'resting_heart_rate': round(mean([r['score']['resting_heart_rate'] for r in last30_rec]), 1),
            'strain': round(mean([c['score']['strain'] for c in last30_cyc]), 2),
            'sleep_performance_percentage': round(mean([s['score']['sleep_performance_percentage'] for s in last30_sleep]), 1),
            'sleep_efficiency_percentage': round(mean([s['score']['sleep_efficiency_percentage'] for s in last30_sleep]), 1),
        },
        'avg7_strain': round(mean([c['score']['strain'] for c in last7_cyc]), 2),
        'series': {
            'recovery': day_series(rec, lambda r: r['score']['recovery_score']),
            'strain': day_series(cyc, lambda c: c['score']['strain']),
            'sleep_performance': day_series(sleep, lambda s: s['score']['sleep_performance_percentage']),
            'hrv': day_series(rec, lambda r: r['score']['hrv_rmssd_milli']),
            'rhr': day_series(rec, lambda r: r['score']['resting_heart_rate']),
        },
        'sports': sports.most_common(8),
        'workouts_per_week_last8': wpw,
        'workouts_per_week_starts': wpw_starts,
        'n_days_total': len(cyc),
        'date_range': [day(cyc[0]['created_at']), day(cyc[-1]['created_at'])],
        'body': d['body'],
        'full_series': full,
        'readiness': readiness,
        'workout_log': workout_log,
        'monthly': monthly,
        'monthly_count_with_data': months_with_data,
        'weekday': weekday,
        'records': records,
        'total_workouts': len(wo),
        'acwr': acwr,
        'monotony': monotony,
        'sport_recovery_cost': sport_recovery_cost,
        'anomalies_recent': recent_anomalies,
        'anomalies_total_flagged': len(anomalies),
        'anomalies_total_scored': len(set(hrv_by_day) & set(rhr_by_day) & set(rr_by_day)),
        'sleep_composition': sleep_composition,
        'zone_distribution': zone_distribution,
        'rest_day_stat': rest_day_stat,
        'today_snapshot': today_snapshot,
    }


def main(data_dir='.'):
    here = os.path.dirname(os.path.abspath(__file__))
    raw_path = os.path.join(data_dir, 'whoop_data.json')
    if not os.path.exists(raw_path):
        raise SystemExit(f"{raw_path} not found — run `python3 whoop.py` first to pull your WHOOP data.")
    with open(raw_path) as f:
        raw = json.load(f)
    summary = build_summary(raw)
    atomic_write_json(os.path.join(data_dir, 'dashboard_data.json'), summary)

    with open(os.path.join(here, 'dashboard_template.html')) as f:
        template = f.read()
    html = template.replace('__DATA__', json.dumps(summary))
    atomic_write(os.path.join(data_dir, 'index.html'), html)

    print(f"Rebuilt {os.path.join(data_dir, 'index.html')} — {summary['n_days_total']} days, "
          f"{summary['total_workouts']} workouts, as of {summary['asOf']}")


if __name__ == '__main__':
    import sys
    main(sys.argv[1] if len(sys.argv) > 1 else '.')
