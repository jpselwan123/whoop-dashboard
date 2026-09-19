"""Rebuild dashboard_data.json and index.html from whoop_data.json.

Run `python3 whoop.py` first to refresh whoop_data.json, then run this.
Or just run refresh.sh, which does both.

Usage: python3 build_dashboard.py [data_dir]   (default: current directory)
"""
import json, math, os
from datetime import datetime, timedelta, timezone
from statistics import mean, pstdev, stdev, variance
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


def _calendar_window(days, i, span):
    """Indexes of the days (sorted ISO strings) within `span` calendar days before days[i]
    (exclusive) — calendar days, not records, so a gap in wear never pulls in data from
    months earlier."""
    from datetime import date as _date
    end = _date.fromisoformat(days[i])
    j = i
    while j > 0 and (end - _date.fromisoformat(days[j - 1])).days <= span:
        j -= 1
    return range(j, i)


ACWR_MIN_DAYS = {'acute': 4, 'chronic': 21}   # days with data needed inside the 7 / 28-day windows


def build_acwr(strain_by_day):
    """Acute:Chronic Workload Ratio — sports-science injury-risk metric, not in the WHOOP app.
    Acute = average strain over the last 7 calendar days, Chronic = last 28 calendar days
    (both including the day itself); skipped when too few days have data."""
    from datetime import date as _date
    days = sorted(strain_by_day.keys())
    out = []
    for i, d in enumerate(days):
        acute_idx = list(_calendar_window(days, i, 6)) + [i]
        chronic_idx = list(_calendar_window(days, i, 27)) + [i]
        if len(acute_idx) < ACWR_MIN_DAYS['acute'] or len(chronic_idx) < ACWR_MIN_DAYS['chronic']:
            continue
        if (_date.fromisoformat(d) - _date.fromisoformat(days[0])).days < 27:   # a full 28 days of history first
            continue
        chronic = mean(strain_by_day[days[j]] for j in chronic_idx)
        if chronic == 0:
            continue
        acute = mean(strain_by_day[days[j]] for j in acute_idx)
        out.append({'date': d, 'v': round(acute / chronic, 2)})
    return out


# Load-ratio bands as used on the page: sweet spot 0.8–1.3, caution to 1.5, high risk above
# (Gabbett 2016; disputed as an injury predictor — Impellizzeri et al. 2020 — and labelled so).
ACWR_BANDS = {'low': 0.8, 'caution': 1.3, 'high': 1.5}


def build_load_today(strain_by_day, today):
    """Today's load ratio from the strain so far, and the day strain at which it would cross each
    band line — so the plan can say how much room is left as the day's strain climbs.

    The ratio includes today in both windows (as `build_acwr` does), so with A / C the strain summed
    over the other days in the 7 / 28-day windows and a / c the day counts including today, the day
    strain S that puts the ratio exactly at r solves (A + S) / a = r (C + S) / c:
        S = (r C / c − A / a) / (1 / a − r / c)
    Pure algebra on the band lines above — no new threshold. Strain is WHOOP's day strain (0–21),
    averaged across days, never summed across sessions."""
    days = sorted(strain_by_day)
    if not days or days[-1] != today:
        return None
    i = len(days) - 1
    acute = [strain_by_day[days[j]] for j in _calendar_window(days, i, 6)]
    chronic = [strain_by_day[days[j]] for j in _calendar_window(days, i, 27)]
    a, c = len(acute) + 1, len(chronic) + 1
    if a < ACWR_MIN_DAYS['acute'] or c < ACWR_MIN_DAYS['chronic']:
        return None
    A, C, S = sum(acute), sum(chronic), strain_by_day[today]
    if C + S == 0:
        return None

    def strain_at(r):
        den = 1 / a - r / c
        if den <= 0:
            return None
        return round(max(0.0, min(21.0, (r * C / c - A / a) / den)), 1)

    return {'date': today, 'strain': round(S, 1), 'ratio': round(((A + S) / a) / ((C + S) / c), 2),
            'bands': dict(ACWR_BANDS),
            'strain_at': {k: strain_at(v) for k, v in ACWR_BANDS.items()}}


# ---- Statistics helpers ----------------------------------------------------------------
# A difference is only called real when it passes a two-sided Welch's t-test at p < 0.05, the
# standard convention in sport-science and medical research. Groups need at least 30 values
# before being compared (the usual central-limit rule of thumb for comparing averages).
SIGNIFICANCE = 0.05
MIN_GROUP = 30


def _betacf(a, b, x):
    """Continued fraction for the incomplete beta function (Numerical Recipes)."""
    fpmin = 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > fpmin else fpmin)
    h = d
    for m in range(1, 300):
        m2 = 2 * m
        for aa in (m * (b - m) * x / ((qam + m2) * (a + m2)),
                   -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))):
            d = 1.0 + aa * d
            d = 1.0 / (d if abs(d) > fpmin else fpmin)
            c = 1.0 + aa / c
            c = c if abs(c) > fpmin else fpmin
            h *= d * c
        if abs(d * c - 1.0) < 3e-14:
            break
    return h


def _betainc(a, b, x):
    """Regularized incomplete beta I_x(a, b)."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    front = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1 - x))
    if x < (a + 1) / (a + b + 2):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1 - x) / b


def welch_p(a, b):
    """Two-sided p-value of Welch's t-test (unequal variances); None if a group has < 2 values."""
    n1, n2 = len(a), len(b)
    if n1 < 2 or n2 < 2:
        return None
    v1, v2 = variance(a), variance(b)
    se2 = v1 / n1 + v2 / n2
    if se2 == 0:
        return 1.0 if mean(a) == mean(b) else 0.0
    t = (mean(a) - mean(b)) / math.sqrt(se2)
    df = se2 ** 2 / ((v1 / n1) ** 2 / (n1 - 1) + (v2 / n2) ** 2 / (n2 - 1))
    return _betainc(df / 2, 0.5, df / (df + t * t))


def _date_minus(d, n):
    return (datetime.fromisoformat(d) - timedelta(days=n)).date().isoformat()


# ---- Exercise intensity (Seiler's three zones) --------------------------------------------
# Low intensity is below the first ventilatory threshold, moderate between the two thresholds,
# high above the second; on the Norwegian Olympic scale these sit at ~82% and ~87% of maximum
# heart rate (Seiler 2010; Seiler & Kjerland 2006). WHOOP's zones are percentages of heart-rate
# *reserve* (resting → max), so each zone is converted to beats per minute with the person's
# resting and max heart rate and its minutes are split across the 82% / 87% lines in proportion
# (time assumed evenly spread inside a zone — WHOOP reports only minutes per zone).
SEILER_LINES = (0.82, 0.87)
WHOOP_ZONES_HRR = (('zone_zero_milli', 0.0, 0.5), ('zone_one_milli', 0.5, 0.6), ('zone_two_milli', 0.6, 0.7),
                   ('zone_three_milli', 0.7, 0.8), ('zone_four_milli', 0.8, 0.9), ('zone_five_milli', 0.9, 1.0))
STRENGTH_SPORTS = {'weightlifting', 'weightlifting_msk', 'powerlifting'}   # rest between sets reads as "easy"


def intensity_minutes(zone_durations, max_hr, rest_hr):
    """[easy, moderate, hard] minutes for one workout, or None without the heart rates needed."""
    if not zone_durations or not max_hr or not rest_hr or max_hr <= rest_hr:
        return None
    lines = [f * max_hr for f in SEILER_LINES]
    out = [0.0, 0.0, 0.0]
    for key, lo, hi in WHOOP_ZONES_HRR:
        minutes = (zone_durations.get(key) or 0) / 60000
        if not minutes:
            continue
        a, b = rest_hr + lo * (max_hr - rest_hr), rest_hr + hi * (max_hr - rest_hr)
        below = [min(1.0, max(0.0, (line - a) / (b - a))) for line in lines]
        out[0] += minutes * below[0]
        out[1] += minutes * (below[1] - below[0])
        out[2] += minutes * (1 - below[1])
    return out


def session_level(split):
    """A session's intensity from where most of its time was (time-in-zone method, Seiler &
    Kjerland 2006): 'easy' when most time is below the first threshold, otherwise 'hard' or
    'moderate' by whichever of the two upper zones holds more time."""
    if not split or sum(split) == 0:
        return None
    if split[1] + split[2] <= split[0]:
        return 'easy'
    return 'hard' if split[2] >= split[1] else 'moderate'


# ---- Training monotony (Foster) -----------------------------------------------------------
# Foster's monotony = a week's mean daily training load ÷ its standard deviation, with 0 on days
# without training (Foster 1998; Foster et al. 2001); above 2.0 is the commonly used risk line.
# Training load is Edwards' TRIMP (Edwards 1993): minutes at 50–60 / 60–70 / 70–80 / 80–90 /
# 90–100% of max HR × 1 / 2 / 3 / 4 / 5. Foster's session RPE isn't recorded by WHOOP, and WHOOP
# strain can't be added across sessions (it's a logarithmic 0–21 scale), while TRIMP minutes can.
EDWARDS_ZONES = ((0.5, 0.6, 1), (0.6, 0.7, 2), (0.7, 0.8, 3), (0.8, 0.9, 4), (0.9, 1.01, 5))


def edwards_trimp(zone_durations, max_hr, rest_hr):
    """Edwards TRIMP for one workout from WHOOP's heart-rate-reserve zones, each zone's minutes
    split across the %-of-max-HR bands in proportion (time assumed even inside a zone)."""
    if not zone_durations or not max_hr or not rest_hr or max_hr <= rest_hr:
        return None
    total = 0.0
    for key, lo, hi in WHOOP_ZONES_HRR:
        minutes = (zone_durations.get(key) or 0) / 60000
        if not minutes:
            continue
        a, b = rest_hr + lo * (max_hr - rest_hr), rest_hr + hi * (max_hr - rest_hr)
        for z_lo, z_hi, weight in EDWARDS_ZONES:
            overlap = max(0.0, min(b, z_hi * max_hr) - max(a, z_lo * max_hr))
            total += minutes * overlap / (b - a) * weight
    return total
FOSTER_MONOTONY_LIMIT = 2.0


def build_monotony(load_by_day, tracked_days):
    """Complete ISO weeks (all 7 days tracked) only — a partial week has no fair mean/SD."""
    weeks = defaultdict(list)
    for d in sorted(tracked_days):
        weeks[iso_week_key(datetime.fromisoformat(d))].append(d)
    out = []
    for wk in sorted(weeks):
        if len(weeks[wk]) < 7:
            continue
        vals = [load_by_day.get(d, 0.0) for d in weeks[wk]]
        sd = pstdev(vals)
        monotony = round(mean(vals) / sd, 2) if sd > 0 else None
        out.append({'week': wk, 'start': iso_week_monday(wk), 'monotony': monotony, 'load': round(sum(vals)),
                    'high': bool(monotony is not None and monotony > FOSTER_MONOTONY_LIMIT)})
    return out


# ---- Sport recovery cost ---------------------------------------------------------------------
def build_sport_recovery_cost(day_sessions, recovery_by_day, all_sports=()):
    """One row per sport: next-morning recovery after days whose hardest session was that sport,
    against all your other training days. The gap counts as real only with 30+ days on both sides
    and Welch's t-test p < 0.05. Each row also carries the intensity most of those days were."""
    rows = []
    for d, (sport, level) in day_sessions.items():
        nxt = (datetime.fromisoformat(d) + timedelta(days=1)).date().isoformat()
        if level and nxt in recovery_by_day:
            rows.append((sport, level, recovery_by_day[nxt]))
    out = {'sports': [], 'days': len(rows),
           'avg_next_recovery': round(mean([r for _, _, r in rows]), 1) if rows else None,
           'never_hardest': sorted(set(all_sports) - {s for s, _, _ in rows})}
    for sport in {s for s, _, _ in rows}:
        mine = [r for s, _, r in rows if s == sport]
        others = [r for s, _, r in rows if s != sport]
        levels = Counter(l for s, l, _ in rows if s == sport)
        p = welch_p(mine, others) if len(mine) >= MIN_GROUP and len(others) >= MIN_GROUP else None
        out['sports'].append({
            'sport': sport, 'n': len(mine), 'avg_next_recovery': round(mean(mine), 1),
            'delta': round(mean(mine) - mean(others), 1) if others else None,
            'significant': p is not None and p < SIGNIFICANCE,
            'intensity': levels.most_common(1)[0][0],
        })
    out['sports'].sort(key=lambda x: (-x['n'], x['sport']))
    return out


# ---- Readiness: one score from the HRV-guided training protocol ------------------------------
# Inputs and ranges follow the HRV-guided training trials; the score combines them the way athlete
# monitoring combines several measures (Thornton et al. 2019):
#   - 7-day average of ln(RMSSD) HRV (Plews et al. 2012; Javaloyes et al. 2019), valid with at
#     least 3 readings in the 7 days (Plews et al. 2014).
#   - Normal range = mean ± 0.5 SD of the 7-day averages over the 4 weeks before the current week
#     (28 baseline values of the same 7-day average: Vesterinen et al. 2016; Javaloyes et al. 2019;
#     tabulated in Manresa-Rocamora et al. 2021), updated weekly (Carrasco-Poyatos et al. 2020).
#   - Measures: HRV, resting HR and hours asleep, each over the last 7 days (the trials' unit:
#     Javaloyes et al. 2019; Alfonso et al. 2025 for resting HR; Craven et al. 2022 for sleep) and
#     for last night alone (single days keep the response to yesterday visible: Schneider et al.
#     2019; Kiviniemi et al. 2007; Nuuttila et al. 2024). Each becomes a standard score vs its own
#     baseline (resting HR flipped, so higher = better); the score is their average with equal
#     weights (no study gives validated weights: Dawes 1979), then standardised against the spread
#     of the person's own earlier composites and shown as a percentile of them (`percentile_series`)
#     — 50 = your median day; the SD lines above become 69 / 31 / 7.
#   - Answer, the way the trials prescribed the day's session (Kiviniemi et al. 2007; Vesterinen
#     et al. 2016; Javaloyes et al. 2019): above the normal band (69+, i.e. more than +0.5 SD, the
#     smallest worthwhile change) → Train hard; inside the band → Train as planned, the trials'
#     moderate/prescribed session; below it → Go easy or Rest ("low intensity exercise (or passive
#     rest) is prescribed when values are suppressed" — Manresa-Rocamora et al. 2021). Rest when the
#     fall is large (1.5 SD below, the line Thornton et al. 2019 give as worth acting on) or
#     sustained — the third day in a row below the band, since the method papers act on a sustained
#     fall rather than one low night (Plews et al. 2013; Buchheit 2014) — but never more than two
#     rest days in a row (Kiviniemi et al. 2007 cap consecutive rest days; detraining).
#     One prescription per day: the trials read HRV each morning and set that day's session.
#   - No more than 2 hard (moderate/high-intensity) days in a row (Carrasco-Poyatos et al. 2020).
#   - Breathing rate 3+ breaths/min above the person's usual rate (average of the nights 30–90
#     days before, at least 30 nights) — an illness sign (Natarajan et al. 2021) → Rest.
READY_WINDOW_DAYS = 7
READY_MIN_READINGS = 3
READY_BASELINE_DAYS = 28
READY_SWC = 0.5
READY_REST_SD = 1.5


def normal_percentile(z):
    """Where a standard score sits among normally distributed days, 0–100 (Φ, the normal CDF)."""
    return 100 * 0.5 * (1 + math.erf(z / math.sqrt(2)))


# The score is that percentile: 50 = your median day, and the decision lines are the trials' own
# SD cut-offs expressed in the same unit — +0.5 SD = 69, −0.5 SD = 31, −1.5 SD = 7.
READY_LINES = {'above': round(normal_percentile(READY_SWC)),
               'train': round(normal_percentile(-READY_SWC)),
               'rest': round(normal_percentile(-READY_REST_SD))}
MAX_HARD_DAYS_IN_A_ROW = 2
# Below the normal band the trials prescribe "low intensity exercise (or passive rest)"
# (Manresa-Rocamora et al. 2021). Which of the two is decided the way the method papers say to read
# HRV — by a sustained fall, not one low night (Plews et al. 2013; Buchheit 2014): the third day in
# a row below your normal is a rest day. Never more than two rest days in a row, the same limit
# HRV-guided protocols put on consecutive rest days to avoid detraining (Kiviniemi et al. 2007).
DAYS_LOW_TO_REST = 3
MAX_REST_DAYS_IN_A_ROW = 2
BREATHING_RISE = 3.0
BREATHING_BASELINE = (30, 90)
BREATHING_MIN_NIGHTS = 30


def asleep_ms(s):
    st = s['score']['stage_summary']
    return max(0, st['total_in_bed_time_milli'] - st['total_awake_time_milli'])


def _in_range(src, first, last):
    return [v for k, v in src.items() if first <= k <= last]


def rolling_7(src, d):
    """7-day average ending on d, valid with 3+ readings (Plews et al. 2014)."""
    window = _in_range(src, _date_minus(d, READY_WINDOW_DAYS - 1), d)
    return mean(window) if len(window) >= READY_MIN_READINGS else None


def judge_marker(src, d, worse):
    """Today's 7-day average vs the 7-day averages of the 4 weeks before this week: mean ± 0.5 SD
    (sample SD). The trials built the range from 28 baseline values of the same 7-day average
    they compared (Vesterinen 2016; Javaloyes 2019, 2020 — Manresa-Rocamora et al. 2021, table 2)."""
    avg = rolling_7(src, d)
    monday = _date_minus(d, datetime.fromisoformat(d).weekday())
    weeks_ok = all(len(_in_range(src, _date_minus(monday, 7 * (k + 1)), _date_minus(monday, 7 * k + 1))) >= READY_MIN_READINGS
                   for k in range(READY_BASELINE_DAYS // 7))   # each of the 4 baseline weeks needs 3+ readings
    if avg is None or not weeks_ok:
        return None
    base_by_day = {_date_minus(monday, k): rolling_7(src, _date_minus(monday, k)) for k in range(1, READY_BASELINE_DAYS + 1)}
    base = [v for v in base_by_day.values() if v is not None]
    if len(base) < 2:
        return None
    m, sd = mean(base), stdev(base)
    lo, hi = m - READY_SWC * sd, m + READY_SWC * sd
    state = 'below' if avg < lo else 'above' if avg > hi else 'within'
    sign = -1 if worse == 'above' else 1
    z = None if sd == 0 else (avg - m) / sd * sign   # + = better
    # the same standard score for each baseline day, so the composite can be measured against
    # the spread of its own baseline instead of an assumed one
    base_z = {} if sd == 0 else {k: (v - m) / sd * sign for k, v in base_by_day.items() if v is not None}
    return {'avg': avg, 'lo': lo, 'hi': hi, 'state': state, 'worse': state == worse, 'z': z, 'base_z': base_z}


def breathing_check(rr_by_day, d):
    if d not in rr_by_day:
        return None
    base = _in_range(rr_by_day, _date_minus(d, BREATHING_BASELINE[1]), _date_minus(d, BREATHING_BASELINE[0]))
    if len(base) < BREATHING_MIN_NIGHTS:
        return None
    usual = mean(base)
    return {'value': round(rr_by_day[d], 1), 'usual': round(usual, 1), 'limit': round(usual + BREATHING_RISE, 1),
            'flagged': rr_by_day[d] >= usual + BREATHING_RISE}


def hard_days_in_a_row(hard_days, d):
    """Consecutive calendar days with a moderate/high-intensity session, ending the day before d."""
    n, cur = 0, _date_minus(d, 1)
    while cur in hard_days:
        n += 1
        cur = _date_minus(cur, 1)
    return n


def judge_last_night(src, d, worse):
    """Last night's single value vs the daily values of the 4 weeks before this week."""
    if d not in src:
        return None
    monday = _date_minus(d, datetime.fromisoformat(d).weekday())
    first, last = _date_minus(monday, READY_BASELINE_DAYS), _date_minus(monday, 1)
    base_by_day = {k: v for k, v in src.items() if first <= k <= last}
    if len(base_by_day) < READY_BASELINE_DAYS // 2:
        return None
    m, sd = mean(base_by_day.values()), stdev(list(base_by_day.values()))
    if sd == 0:
        return None
    sign = -1 if worse == 'above' else 1
    return {'value': src[d], 'z': (src[d] - m) / sd * sign,
            'base_z': {k: (v - m) / sd * sign for k, v in base_by_day.items()}}


def composite_raw(measures):
    """The day's measures as one average standard score, or None if none could be scored."""
    zs = [m['z'] for m in measures if m and m.get('z') is not None]
    return mean(zs) if zs else None


def percentile_series(raw_by_day):
    """Each day's composite read as a percentile of the person's own earlier days.

    Averaging standard scores shrinks their spread — the measures move together, but not exactly —
    so the average is not itself on a 1-SD-per-unit scale: here its spread was 0.88 SD, which made
    a genuinely above-normal day read as barely above average. It is therefore standardised against
    the spread of the person's own earlier composites (all days before it, 28+ needed, so nothing is
    scored with days it has not lived through yet) and shown as a percentile: 50 = a median day for
    you, and the trials' decision lines keep their meaning — +0.5 SD = 69, −0.5 SD = 31, −1.5 SD = 7.
    Checked on 553 days here: 6.5% of days landed under 7 and 31.2% at or above 69, against the
    6.7% and 30.9% those SD lines are meant to cut off."""
    out, history = {}, []
    for d in sorted(raw_by_day):
        if len(history) >= READY_BASELINE_DAYS:
            m, sd = mean(history), stdev(history)
            if sd > 0:
                z = (raw_by_day[d] - m) / sd
                out[d] = (max(1, min(99, round(normal_percentile(z)))), z)
        history.append(raw_by_day[d])
    return out


def build_readiness(hrv_by_day, rhr_by_day, rr_by_day, hard_days, sleep_h_by_day=None):
    ln_hrv = {k: math.log(v) for k, v in hrv_by_day.items() if v and v > 0}
    rhr = {k: v for k, v in rhr_by_day.items() if v}
    sleep_h = {k: v for k, v in (sleep_h_by_day or {}).items() if v}
    # pass 1: each day's measures and its average standard score
    measured, raw_all, raw_night = {}, {}, {}
    for d in sorted(ln_hrv):
        hrv = judge_marker(ln_hrv, d, 'below')
        if hrv is None or hrv['z'] is None:
            continue
        rest = judge_marker(rhr, d, 'above')
        sleep = judge_marker(sleep_h, d, 'below')
        night = [judge_last_night(src, d, worse) for src, worse in
                 ((ln_hrv, 'below'), (rhr, 'above'), (sleep_h, 'below'))]
        measured[d] = (hrv, rest, sleep, night)
        raw_all[d] = composite_raw([hrv, rest, sleep] + night)
        night_raw = composite_raw(night)
        if night_raw is not None:
            raw_night[d] = night_raw

    # pass 2: the same composites on the scale they are shown in
    pct_all, pct_night = percentile_series(raw_all), percentile_series(raw_night)

    series, latest = [], None
    scores, answers = {}, {}           # by day, for the sustained-suppression rule below
    for d in sorted(pct_all):
        hrv, rest, sleep, night = measured[d]
        score = pct_all[d][0]
        scores[d] = score
        night_score, night_z = pct_night.get(d, (None, None))   # information only, same scale
        breathing = breathing_check(rr_by_day, d)
        streak = hard_days_in_a_row(hard_days, d)
        days_below = 0                 # consecutive calendar days below the normal band, today included
        cur = d
        while scores.get(cur) is not None and scores[cur] < READY_LINES['train']:
            days_below += 1
            cur = _date_minus(cur, 1)
        if breathing and breathing['flagged']:
            answer, reasons = 'rest', ['breathing']
        elif score < READY_LINES['rest']:
            answer, reasons = 'rest', ['low']
        elif score < READY_LINES['train']:
            # below the normal band the trials prescribe low intensity OR rest; a sustained fall is
            # what the method papers act on, and two rest days in a row is the limit
            rested = [answers.get(_date_minus(d, k)) == 'rest' for k in (1, 2)]
            if days_below >= DAYS_LOW_TO_REST and not all(rested):
                answer, reasons = 'rest', ['days_low']
            else:
                answer, reasons = 'easy', ['low']
        elif streak >= MAX_HARD_DAYS_IN_A_ROW:
            answer, reasons = 'easy', ['streak']
        elif score < READY_LINES['above']:
            answer, reasons = 'moderate', []
        else:
            answer, reasons = 'hard', []
        answers[d] = answer
        series.append({'date': d, 'v': score, 'answer': answer})
        marker = lambda m, unit_fn: None if m is None else {'value': unit_fn(m['avg']), 'normal': [unit_fn(m['lo']), unit_fn(m['hi'])],
                                                            'state': m['state']}
        latest = {
            'date': d, 'score': score, 'answer': answer, 'reasons': reasons, 'lines': dict(READY_LINES),
            'hrv': marker(hrv, lambda v: round(math.exp(v))),
            'rhr': marker(rest, lambda v: round(v, 1)),
            'sleep': marker(sleep, lambda v: round(v, 2)),
            'last_night': None if night_score is None else {
                'score': night_score,
                'state': ('above' if night_z > READY_SWC else 'below' if night_z < -READY_SWC else 'within'),
                'measures': sum(1 for m in night if m)},
            'breathing': breathing, 'hard_days_in_a_row': streak, 'max_hard_days': MAX_HARD_DAYS_IN_A_ROW,
            'days_below_normal': days_below, 'days_low_to_rest': DAYS_LOW_TO_REST,
        }
    return latest, series


def readiness_progress(hrv_by_day):
    """Days of HRV so far vs days until the first answer: 4 full weeks before the first Monday that
    can be scored (learning each measure's normal), then 4 more weeks of scored days to learn how
    much your score itself moves (`percentile_series`)."""
    days = sorted(k for k, v in hrv_by_day.items() if v)
    if not days:
        return {'days': 0, 'needed': 2 * READY_BASELINE_DAYS + 1}
    first = datetime.fromisoformat(days[0])
    ready = first + timedelta(days=READY_BASELINE_DAYS)
    ready += timedelta(days=(7 - ready.weekday()) % 7)
    ready += timedelta(days=READY_BASELINE_DAYS)
    elapsed = (datetime.fromisoformat(days[-1]) - first).days + 1
    return {'days': elapsed, 'needed': (ready - first).days + 1}


# "Does this work?": next-morning recovery after 'hard training OK' days vs 'easy or rest' days,
# tested with Welch's t-test. A consistency check, not independent proof — recovery shares HRV and
# resting HR with the answer.
def build_readiness_check(series, recovery_by_day):
    """Next-morning recovery after days with each answer; the green/blue answers vs the yellow/red
    ones tested with Welch's t-test. A consistency check, not independent proof (recovery shares
    HRV and resting HR)."""
    groups = {'hard': [], 'moderate': [], 'easy': [], 'rest': []}
    for p in series:
        nxt = (datetime.fromisoformat(p['date']) + timedelta(days=1)).date().isoformat()
        if nxt in recovery_by_day:
            groups[p['answer']].append(recovery_by_day[nxt])
    upper = groups['hard'] + groups['moderate']
    lower = groups['easy'] + groups['rest']
    p = welch_p(upper, lower)
    enough = len(upper) >= MIN_GROUP and len(lower) >= MIN_GROUP
    return {
        'answers': [{'answer': k, 'avg_next_recovery': round(mean(v), 1) if v else None, 'days': len(v)}
                    for k, v in groups.items()],
        'days': sum(len(v) for v in groups.values()),
        'enough': enough,
        'significant': bool(enough and p is not None and p < SIGNIFICANCE),
        'hard_higher': bool(upper and lower and mean(upper) > mean(lower)),
    }


def _ols(X, y):
    """Least squares with standard errors (stdlib): returns (coefficients, standard errors, df)."""
    n, k = len(y), len(X[0])
    M = [[sum(X[i][a] * X[i][b] for i in range(n)) for b in range(k)] + [1.0 if a == j else 0.0 for j in range(k)]
         for a in range(k)]
    for c in range(k):                                   # Gauss-Jordan inverse of X'X
        piv = max(range(c, k), key=lambda r: abs(M[r][c]))
        M[c], M[piv] = M[piv], M[c]
        if abs(M[c][c]) < 1e-12:
            return None
        f = M[c][c]
        M[c] = [v / f for v in M[c]]
        for r in range(k):
            if r != c:
                g = M[r][c]
                M[r] = [a - g * b for a, b in zip(M[r], M[c])]
    inv = [row[k:] for row in M]
    xty = [sum(X[i][a] * y[i] for i in range(n)) for a in range(k)]
    beta = [sum(inv[a][b] * xty[b] for b in range(k)) for a in range(k)]
    df = n - k
    s2 = sum((y[i] - sum(beta[a] * X[i][a] for a in range(k))) ** 2 for i in range(n)) / df
    return beta, [math.sqrt(s2 * inv[a][a]) for a in range(k)], df


# What today's training costs in readiness, measured on the person's own history rather than assumed.
# Readiness is an overnight measurement, so a session can't change this morning's number - but it does
# lower the next one. Each past day's day strain is regressed against the next morning's readiness,
# holding that day's own readiness constant (ordinary least squares; t-test on the coefficient,
# p < 0.05, 30+ pairs - the same conventions as every other comparison here). Today's cost is that
# effect applied to the strain above a typical rest day (median day strain on days with no workout),
# never a bonus for doing less; the page shows it once a session is logged.
def build_training_cost(readiness_series, strain_by_day, workout_days, today):
    scores = {p['date']: p['v'] for p in readiness_series}
    rows = [(1.0, scores[d], strain_by_day[d], scores[_date_minus(d, -1)])
            for d in scores if d < today and d in strain_by_day and _date_minus(d, -1) in scores]
    rest = [v for d, v in strain_by_day.items() if d < today and d not in workout_days]
    if len(rows) < MIN_GROUP or len(rest) < MIN_GROUP or today not in scores or today not in strain_by_day:
        return None
    fit = _ols([r[:3] for r in rows], [r[3] for r in rows])
    if fit is None:
        return None
    beta, se, df = fit
    per_strain = beta[2]
    t = per_strain / se[2] if se[2] else 0.0
    p = _betainc(df / 2, 0.5, df / (df + t * t))
    significant = p < SIGNIFICANCE and per_strain < 0
    rest_strain = sorted(rest)[len(rest) // 2] if len(rest) % 2 else sum(sorted(rest)[len(rest) // 2 - 1:len(rest) // 2 + 1]) / 2
    strain = strain_by_day[today]
    cost = round(min(0.0, per_strain * (strain - rest_strain))) if significant else None
    morning = scores[today]
    return {'date': today, 'morning': morning, 'strain': round(strain, 1), 'rest_day_strain': round(rest_strain, 1),
            'per_strain': round(per_strain, 2), 'p': round(p, 4), 'pairs': len(rows), 'significant': significant,
            'cost': cost, 'after': None if cost is None else max(1, min(99, morning + cost))}


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
    weeks = last_n_iso_weeks(now.date(), 8)          # a week with no sleep recorded stays as a gap
    current_key = iso_week_key(now)
    return [{
        'week': wk,
        'start': iso_week_monday(wk),
        'rem_h': round(mean(week_rem[wk]), 2) if week_rem.get(wk) else None,
        'sws_h': round(mean(week_sws[wk]), 2) if week_sws.get(wk) else None,
        'light_h': round(mean(week_light[wk]), 2) if week_light.get(wk) else None,
        'is_current': wk == current_key,
    } for wk in weeks]


def build_zone_distribution(wo, now, max_hr, rest_hr_for):
    """Weekly easy / moderate / hard hours (Seiler's three zones, see intensity_minutes), all
    workouts except strength sessions, whose rest between sets would read as easy time."""
    week_totals = defaultdict(lambda: [0.0, 0.0, 0.0])
    all_time = [0.0, 0.0, 0.0]
    for w in wo:
        if w['sport_name'] in STRENGTH_SPORTS:
            continue
        split = intensity_minutes(w['score'].get('zone_durations'), max_hr, rest_hr_for(day(w['created_at'])))
        if not split:
            continue
        key = iso_week_key(parse(w['created_at']))
        for i in range(3):
            week_totals[key][i] += split[i] / 60
            all_time[i] += split[i] / 60
    current_key = iso_week_key(now)
    weeks = last_n_iso_weeks(now.date(), 8)          # every week, including ones without workouts
    weekly = [{'week': wk, 'start': iso_week_monday(wk),
               'easy_h': round(week_totals[wk][0], 2), 'mod_h': round(week_totals[wk][1], 2),
               'hard_h': round(week_totals[wk][2], 2), 'is_current': wk == current_key} for wk in weeks]
    total_h = sum(all_time)
    pct = lambda i: round(100 * all_time[i] / total_h, 1) if total_h else 0
    return {'weekly': weekly, 'all_time': {'easy_pct': pct(0), 'mod_pct': pct(1), 'hard_pct': pct(2),
                                           'total_h': round(total_h, 1)}}


def build_rest_day_stat(cyc, workout_days):
    """The most recent finished day with no logged workout — a plain fact, no threshold."""
    today = day(cyc[-1]['created_at'])
    for c in reversed(cyc):
        d = day(c['created_at'])
        if d != today and d not in workout_days:
            return {'last_rest_date': d,
                    'days_since': (datetime.fromisoformat(today) - datetime.fromisoformat(d)).days}
    return None


SLEEP_MIN_HOURS = 7   # adults: 7+ hours a night (AASM & Sleep Research Society, Watson et al. 2015)


def build_sleep_nights(sleep, today):
    """Nights in the last 7 days with 7+ hours asleep."""
    recent = [s for s in sleep if 0 <= (datetime.fromisoformat(today) - datetime.fromisoformat(day(s['created_at']))).days < 7]
    return {'nights_7h': sum(1 for s in recent if asleep_ms(s) >= SLEEP_MIN_HOURS * 3600000),
            'nights': len(recent), 'min_hours': SLEEP_MIN_HOURS}


def build_today_snapshot(cyc, wo, max_hr, rest_hr_for):
    """Right-now context: today's cycle strain (still accumulating if the day isn't over) and
    every workout logged today with its easy / moderate / hard minutes and intensity."""
    if not cyc:
        return None
    latest_cycle = cyc[-1]
    today = day(latest_cycle['created_at'])
    todays_workouts = []
    for w in wo:
        if day(w['created_at']) != today:
            continue
        sc = w['score']
        split = intensity_minutes(sc.get('zone_durations'), max_hr, rest_hr_for(today)) or [0.0, 0.0, 0.0]
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
            'zone_easy_min': round(split[0]),
            'zone_mod_min': round(split[1]),
            'zone_hard_min': round(split[2]),
            'intensity': session_level(split) if w['sport_name'] not in STRENGTH_SPORTS else None,
        })
    todays_workouts.sort(key=lambda w: w['start'])
    return {
        'date': today,
        'cycle_start': latest_cycle['start'],
        'strain_so_far': round(latest_cycle['score']['strain'], 1),
        'in_progress': latest_cycle.get('end') is None,
        'workouts': todays_workouts,
    }


def build_summary(d):
    rec = sorted([r for r in d['recovery'] if r['score_state'] == 'SCORED'], key=lambda r: r['created_at'])
    cyc = sorted([c for c in d['cycles'] if c['score_state'] == 'SCORED'], key=lambda c: c['created_at'])
    sleep = sorted([s for s in d['sleep'] if s['score_state'] == 'SCORED' and not s['nap']], key=lambda s: s['created_at'])
    naps = [s for s in d['sleep'] if s['score_state'] == 'SCORED' and s['nap'] and s.get('score')]
    wo = sorted([w for w in d['workouts'] if w['score_state'] == 'SCORED' and w.get('score')], key=lambda w: w['start'])

    if not rec or not cyc or not sleep:
        raise RuntimeError(
            "No scored WHOOP data yet — you need at least one full night of sleep and a "
            "morning recovery score before this dashboard has anything to show. Wear your "
            "WHOOP overnight, let it sync, then run this again."
        )

    latest_rec, latest_cyc, latest_sleep = rec[-1], cyc[-1], sleep[-1]
    sn = latest_sleep['score']['sleep_needed']
    debt_h = sn['need_from_sleep_debt_milli'] / 3600000
    last30_rec, last30_cyc, last30_sleep = rec[-30:], cyc[-30:], sleep[-30:]
    last7_cyc = cyc[-7:]

    sports = Counter(sport_label(w['sport_name']) for w in wo)
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
    longest_sleep = max(sleep, key=asleep_ms)   # time asleep, like the WHOOP app's "Hours of Sleep"
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

    max_hr = (d.get('body') or {}).get('max_heart_rate')
    usual_rhr = mean(rhr_by_day.values()) if rhr_by_day else None
    rest_hr_for = lambda dd: rhr_by_day.get(dd) or usual_rhr

    # each day's hardest session and its intensity; strength sessions have no zone-based intensity
    day_sessions, hard_days, load_by_day = {}, set(), defaultdict(float)
    by_day_wo = defaultdict(list)
    for w in wo:
        by_day_wo[day(w['created_at'])].append(w)
        load_by_day[day(w['created_at'])] += edwards_trimp(w['score'].get('zone_durations'), max_hr, rest_hr_for(day(w['created_at']))) or 0.0
    for dd, ws in by_day_wo.items():
        levels = [session_level(intensity_minutes(w['score'].get('zone_durations'), max_hr, rest_hr_for(dd)))
                  for w in ws if w['sport_name'] not in STRENGTH_SPORTS]
        if any(l in ('moderate', 'hard') for l in levels):
            hard_days.add(dd)
        top = max(ws, key=lambda w: w['score']['strain'])
        day_sessions[dd] = (sport_label(top['sport_name']), 'strength' if top['sport_name'] in STRENGTH_SPORTS else
                            session_level(intensity_minutes(top['score'].get('zone_durations'), max_hr, rest_hr_for(dd))))

    acwr = build_acwr(strain_by_day)
    load_today = build_load_today(strain_by_day, day(cyc[-1]['created_at']))
    monotony = build_monotony(load_by_day, strain_by_day.keys())
    sport_recovery_cost = build_sport_recovery_cost(day_sessions, recovery_by_day, {sport_label(w['sport_name']) for w in wo})
    sleep_composition = build_sleep_composition(sleep, now)
    zone_distribution = build_zone_distribution(wo, now, max_hr, rest_hr_for)
    today = day(cyc[-1]['created_at'])
    rest_day_stat = build_rest_day_stat(cyc, set(by_day_wo))
    today_snapshot = build_today_snapshot(cyc, wo, max_hr, rest_hr_for)
    sleep_h_by_day = defaultdict(float)   # hours asleep per day, naps included
    for sl in list(sleep) + list(naps):
        sleep_h_by_day[day(sl['created_at'])] += asleep_ms(sl) / 3600000
    readiness, readiness_series = build_readiness(hrv_by_day, rhr_by_day, rr_by_day, hard_days, sleep_h_by_day)
    # 'a' = the answer that day, so the page can show how often each one actually comes up
    full['readiness'] = [{'date': p['date'], 'v': p['v'], 'a': p['answer']} for p in readiness_series]
    readiness_check = build_readiness_check(readiness_series, recovery_by_day)
    training_cost = build_training_cost(readiness_series, strain_by_day, set(by_day_wo), day(cyc[-1]['created_at']))
    for entry, w in zip(wlog, wo):   # wlog was built in the same order as wo
        entry['intensity'] = None if w['sport_name'] in STRENGTH_SPORTS else session_level(
            intensity_minutes(w['score'].get('zone_durations'), max_hr, rest_hr_for(entry['date'])))
    # last night, shown as information next to the answer (not part of the decision)
    last_sleep = sleep[-1]
    naps_after = [n for n in naps if day(n['created_at']) == day(last_sleep['created_at']) and n['start'] >= last_sleep['end']]
    last_night = {'hrv': round(latest_rec['score']['hrv_rmssd_milli']), 'rhr': latest_rec['score']['resting_heart_rate'],
                  'recovery': latest_rec['score']['recovery_score'], 'asleep_h': round(asleep_ms(last_sleep) / 3600000, 2),
                  'nap_h': round(sum(asleep_ms(n) for n in naps_after) / 3600000, 2)}

    records = {
        'best_recovery': {'v': best_rec['score']['recovery_score'], 'date': day(best_rec['created_at'])},
        'worst_recovery': {'v': worst_rec['score']['recovery_score'], 'date': day(worst_rec['created_at'])},
        'best_hrv': {'v': round(best_hrv['score']['hrv_rmssd_milli'], 1), 'date': day(best_hrv['created_at'])},
        'lowest_rhr': {'v': lowest_rhr['score']['resting_heart_rate'], 'date': day(lowest_rhr['created_at'])},
        'biggest_strain_day': {'v': round(biggest_strain_cyc['score']['strain'], 1), 'date': day(biggest_strain_cyc['created_at'])},
        'biggest_strain_workout': ({'v': round(biggest_strain_wo['score']['strain'], 1), 'date': day(biggest_strain_wo['created_at']), 'sport': sport_label(biggest_strain_wo['sport_name'])}
                                    if biggest_strain_wo else None),
        'longest_sleep_h': {'v': round(asleep_ms(longest_sleep) / 3600000, 3), 'date': day(longest_sleep['created_at'])},
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
        'sports': sports.most_common(),
        'workouts_per_week_last8': wpw,
        'workouts_per_week_starts': wpw_starts,
        'n_days_total': len(cyc),
        'date_range': [day(cyc[0]['created_at']), day(cyc[-1]['created_at'])],
        'body': d['body'],
        'full_series': full,
        'readiness': readiness,
        'readiness_progress': readiness_progress(hrv_by_day),
        'readiness_check': readiness_check,
        'last_night': last_night,
        'sleep_nights': build_sleep_nights(sleep, today),
        'workout_log': workout_log,
        'monthly': monthly,
        'monthly_count_with_data': months_with_data,
        'weekday': weekday,
        'records': records,
        'total_workouts': len(wo),
        'acwr': acwr,
        'load_today': load_today,
        'training_cost': training_cost,
        'monotony': monotony,
        'sport_recovery_cost': sport_recovery_cost,
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
