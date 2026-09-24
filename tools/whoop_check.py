"""An independent check of every number the WHOOP dashboard shows.

This is a SECOND implementation, written to disagree. It reads the raw export
(whoop_data.json) and the built payload (dashboard_data.json) and recomputes each figure from
scratch. It deliberately does NOT import build_dashboard: if both were the same code, agreement
would mean nothing. Where the dashboard and this script agree, two independent readings of the
raw data agree.

Usage:  python3 tools/whoop_check.py [data_dir]        (default: the repo root)

It lives in the repo so it cannot be lost (the copy outside git was lost twice), and CI runs it on the
synthetic athlete on every push. What keeps it independent is not where it sits but what it imports:
the standard library only, never build_dashboard — a test enforces that.
"""
import json, math, os, sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

PASS, FAIL = [], []


def check(name, got, want, tol=0.0):
    ok = (got == want) if tol == 0 else (got is not None and want is not None and abs(got - want) <= tol)
    (PASS if ok else FAIL).append((name, got, want))


# ---- time -------------------------------------------------------------------------------------
def parse(ts):
    return datetime.fromisoformat(ts.replace('Z', '+00:00'))


def tz_of(offset):
    if not offset or offset in ('Z', 'z'):
        return timezone.utc
    sign = 1 if offset[0] == '+' else -1
    h, m = offset[1:].split(':')
    return timezone(sign * timedelta(hours=int(h), minutes=int(m)))


def local(ts, offset):
    return parse(ts).astimezone(tz_of(offset))


def local_date(ts, offset):
    return local(ts, offset).date().isoformat()


def shift(d, n):
    return (datetime.fromisoformat(d) - timedelta(days=n)).date().isoformat()


def local_hour(ts, offset):
    t = local(ts, offset)
    return t.hour + t.minute / 60 + t.second / 3600


# ---- statistics -------------------------------------------------------------------------------
def mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs)


def sd(xs, sample=True):
    xs = list(xs)
    m = mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - (1 if sample else 0)))


def median(xs):
    xs = sorted(xs)
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def phi(z):
    return 100 * 0.5 * (1 + math.erf(z / math.sqrt(2)))


def pearson(pairs):
    mx, my = mean(x for x, _ in pairs), mean(y for _, y in pairs)
    den = math.sqrt(sum((x - mx) ** 2 for x, _ in pairs) * sum((y - my) ** 2 for _, y in pairs))
    return None if not den else sum((x - mx) * (y - my) for x, y in pairs) / den


# ---- the day key ------------------------------------------------------------------------------
def build_day_key(raw):
    """A cycle is the local date its own night sleep ended; everything else follows its cycle."""
    cycles = raw['cycles']
    sleeps = [s for s in raw['sleep'] if s.get('score')]
    night_of_cycle = {}
    for s in sleeps:
        if not s['nap'] and s.get('cycle_id') is not None:
            night_of_cycle[s['cycle_id']] = s
    day_of_cycle = {}
    for c in cycles:
        n = night_of_cycle.get(c['id'])
        day_of_cycle[c['id']] = (local_date(n['end'], n.get('timezone_offset')) if n
                                 else local_date(c['start'], c.get('timezone_offset')))
    windows = sorted(((parse(c['start']), parse(c['end']) if c.get('end') else None, c['id']) for c in cycles),
                     key=lambda w: w[0])

    def for_record(r):
        cid = r.get('cycle_id')
        if cid in day_of_cycle:
            return day_of_cycle[cid]
        if r.get('id') in day_of_cycle and 'strain' in str(r.get('score', {})):
            return day_of_cycle[r['id']]
        t = parse(r['start'] if 'start' in r else r['created_at'])
        for s, e, cid2 in windows:
            if s <= t and (e is None or t < e):
                return day_of_cycle[cid2]
        return local_date(r.get('start', r['created_at']), r.get('timezone_offset'))
    return day_of_cycle, for_record


def main(data_dir):
    raw = json.load(open(os.path.join(data_dir, 'whoop_data.json')))
    D = json.load(open(os.path.join(data_dir, 'dashboard_data.json')))
    day_of_cycle, day_of = build_day_key(raw)

    cycles = sorted(raw['cycles'], key=lambda c: c['start'])
    sleeps = [s for s in raw['sleep'] if s.get('score')]
    nights = [s for s in sleeps if not s['nap']]
    naps = [s for s in sleeps if s['nap']]
    workouts = [w for w in raw['workouts'] if w.get('score')]
    recoveries = [r for r in raw['recovery'] if r.get('score')]

    # ---- the day key itself --------------------------------------------------------------
    keys = [day_of_cycle[c['id']] for c in cycles]
    check('cycles counted', D['n_days_total'], len(cycles))
    check('every cycle has a unique day', len(set(keys)), len(cycles))
    check('date range starts', D['date_range'][0], min(keys))
    check('date range ends', D['date_range'][1], max(keys))
    check('workouts counted', D['total_workouts'], len(workouts))

    strain = {day_of_cycle[c['id']]: c['score']['strain'] for c in cycles if c.get('score')}
    recovery = {}
    for r in recoveries:
        recovery[day_of_cycle.get(r['cycle_id'], None)] = r['score']['recovery_score']
    recovery.pop(None, None)
    hrv = {day_of_cycle.get(r['cycle_id']): r['score']['hrv_rmssd_milli'] for r in recoveries}
    rhr = {day_of_cycle.get(r['cycle_id']): r['score']['resting_heart_rate'] for r in recoveries}
    hrv.pop(None, None)
    rhr.pop(None, None)

    # hours asleep = time in bed minus time awake, which is what WHOOP means by it. Summing the
    # three stages instead undercounts: the stages do not always add up to the time asleep.
    def asleep_ms(s):
        st = s['score']['stage_summary']
        return max(0, st['total_in_bed_time_milli'] - st['total_awake_time_milli'])

    asleep_h = defaultdict(float)
    for s in sleeps:
        asleep_h[day_of_cycle.get(s.get('cycle_id'), day_of(s))] += asleep_ms(s) / 3600000

    check('latest recovery', D['latest']['recovery_score'], recovery[max(recovery)], 0.5)
    check('latest resting HR', D['latest']['resting_heart_rate'], rhr[max(rhr)], 0.5)

    readiness_checks(D, hrv, rhr, asleep_h)
    load_checks(D, raw, workouts, strain, day_of)
    sleep_regularity_checks(D, nights, naps)
    bedtime_checks(D, nights)
    what_moves_checks(D)
    records_checks(D, raw, workouts, strain, recovery, asleep_h, day_of)
    session_checks(D, raw, workouts, day_of)
    sport_checks(D, D['workout_log'], recovery)
    sleep_night_checks(D, nights, lambda r: day_of_cycle.get(r.get('cycle_id'), day_of(r)), strain)
    training_cost_checks(D)
    per_day_checks(D, strain, recovery)

    print('%d checks passed, %d failed' % (len(PASS), len(FAIL)))
    for name, got, want in FAIL:
        print('  FAIL %-46s got %r want %r' % (name, got, want))
    return 1 if FAIL else 0


# ---- readiness ---------------------------------------------------------------------------------
WINDOW, MIN_READINGS, BASELINE, SWC, REST_SD, MIN_HISTORY = 7, 3, 28, 0.5, 1.5, 28


def rolling(src, d):
    vals = [v for k, v in src.items() if shift(d, WINDOW) <= k <= shift(d, 1)]
    return mean(vals) if len(vals) >= MIN_READINGS else None


def trend_z(src, d, flip):
    avg = rolling(src, d)
    monday = shift(d, datetime.fromisoformat(d).weekday())
    for k in range(BASELINE // 7):
        if len([v for kk, v in src.items()
                if shift(monday, 7 * (k + 1)) <= kk <= shift(monday, 7 * k + 1)]) < MIN_READINGS:
            return None
    if avg is None:
        return None
    base = [rolling(src, shift(monday, k)) for k in range(1, BASELINE + 1)]
    base = [b for b in base if b is not None]
    if len(base) < 2:
        return None
    s = sd(base)
    return None if s == 0 else (avg - mean(base)) / s * (-1 if flip else 1)


def night_z(src, d, flip):
    if d not in src:
        return None
    monday = shift(d, datetime.fromisoformat(d).weekday())
    base = {k: v for k, v in src.items() if shift(monday, BASELINE) <= k <= shift(monday, 1)}
    if len(base) < BASELINE // 2:
        return None
    s = sd(list(base.values()))
    return None if s == 0 else (src[d] - mean(base.values())) / s * (-1 if flip else 1)


def readiness_checks(D, hrv, rhr, asleep_h):
    ln_hrv = {k: math.log(v) for k, v in hrv.items() if v > 0}
    sleep_h = {k: v for k, v in asleep_h.items() if v}
    raws = {}
    for d in sorted(ln_hrv):
        zs = [trend_z(ln_hrv, d, False), trend_z(rhr, d, True), trend_z(sleep_h, d, False),
              night_z(ln_hrv, d, False), night_z(rhr, d, True), night_z(sleep_h, d, False)]
        zs = [z for z in zs if z is not None]
        if trend_z(ln_hrv, d, False) is None:
            continue
        if zs:
            raws[d] = mean(zs)

    scores, history = {}, []
    for d in sorted(raws):
        if len(history) >= MIN_HISTORY:
            s = sd(history)
            if s:
                scores[d] = max(1, min(99, round(phi((raws[d] - mean(history)) / s))))
        history.append(raws[d])

    R = D['readiness']
    check('readiness: scored days', len(D['full_series']['readiness']), len(scores))
    check("readiness: today's score", R['score'], scores[R['date']])
    shown = {p['date']: p['v'] for p in D['full_series']['readiness']}
    check('readiness: every daily score', [d for d in scores if shown.get(d) != scores[d]][:5], [])

    lines = R['lines']
    check('readiness: the train line is -0.5 SD', lines['train'], round(phi(-SWC)))
    check('readiness: the rest line is -1.5 SD', lines['rest'], round(phi(-REST_SD)))
    check('readiness: no band above normal', 'above' in lines, False)
    C = D.get('constants') or {}
    check('constants: the page reads the same readiness lines', C.get('ready_lines'), lines)
    check('constants: load bands are Gabbett\'s', C.get('acwr_bands'), {'low': 0.8, 'caution': 1.3, 'high': 1.5})
    check("constants: monotony line is Foster's 2.0", C.get('monotony_limit'), 2.0)

    # the answers, including the sustained-fall rule and the two-rest-day cap
    answers = {}
    for d in sorted(scores):
        run, cur = 0, d
        while scores.get(cur) is not None and scores[cur] < lines['train']:
            run += 1
            cur = shift(cur, 1)
        rested_two = all(answers.get(shift(d, k)) == 'rest' for k in (1, 2))
        if scores[d] < lines['rest']:
            a = 'easy' if rested_two else 'rest'
        elif scores[d] < lines['train']:
            a = 'rest' if (run >= 2 and not rested_two) else 'easy'
        else:
            a = 'moderate'
        answers[d] = a
    got = {p['date']: p['a'] for p in D['full_series']['readiness']}
    check('readiness: every daily answer', [d for d in answers if got.get(d) != answers[d]][:5], [])
    check("readiness: today's answer", R['answer'], answers[R['date']])
    check('readiness: never 3 rest days in a row',
          max((sum(1 for k in range(3) if answers.get(shift(d, k)) == 'rest') for d in answers), default=0) < 3, True)
    check('readiness: breathing never flags', 'flagged' in (R['breathing'] or {}), False)
    check('readiness: no consecutive-hard-days rule', 'hard_days_in_a_row' in R, False)

    # the what-if slider is the same formula with one input replaced
    W = R.get('what_if')
    if W:
        z = (W['actual'] - W['night_mean']) / W['night_sd']
        comp = (sum(W['fixed_z']) + z) / (len(W['fixed_z']) + 1)
        recomputed = max(1, min(99, round(phi((comp - W['composite_mean']) / W['composite_sd']))))
        check('what-if: at the real night it equals the score shown', recomputed, R['score'])
        check('what-if: five inputs are fixed', len(W['fixed_z']), 5)
        lo = max(1, min(99, round(phi(((sum(W['fixed_z']) + (W['min'] - W['night_mean']) / W['night_sd'])
                                       / 6 - W['composite_mean']) / W['composite_sd']))))
        hi = max(1, min(99, round(phi(((sum(W['fixed_z']) + (W['max'] - W['night_mean']) / W['night_sd'])
                                       / 6 - W['composite_mean']) / W['composite_sd']))))
        check('what-if: more sleep never scores lower', lo <= hi, True)


# ---- training load ------------------------------------------------------------------------------
EDWARDS = ((0.5, 0.6, 1), (0.6, 0.7, 2), (0.7, 0.8, 3), (0.8, 0.9, 4), (0.9, 1.01, 5))
WHOOP_ZONES = (('zone_zero_milli', 0.0, 0.5), ('zone_one_milli', 0.5, 0.6), ('zone_two_milli', 0.6, 0.7),
               ('zone_three_milli', 0.7, 0.8), ('zone_four_milli', 0.8, 0.9), ('zone_five_milli', 0.9, 1.0))
STRENGTH = {'weightlifting', 'weightlifting_msk', 'powerlifting'}


def trimp(zones, max_hr, rest_hr):
    if not zones or not max_hr or not rest_hr or max_hr <= rest_hr:
        return None
    total = 0.0
    for key, lo, hi in WHOOP_ZONES:
        minutes = (zones.get(key) or 0) / 60000
        if not minutes:
            continue
        a, b = rest_hr + lo * (max_hr - rest_hr), rest_hr + hi * (max_hr - rest_hr)
        for z_lo, z_hi, w in EDWARDS:
            overlap = max(0.0, min(b, z_hi * max_hr) - max(a, z_lo * max_hr))
            total += minutes * overlap / (b - a) * w
    return total


def load_checks(D, raw, workouts, strain, day_of):
    max_hr = raw['body']['max_heart_rate']
    rhr_by_day = {}
    for r in raw['recovery']:
        if r.get('score'):
            rhr_by_day[day_of(r)] = r['score']['resting_heart_rate']
    usual = mean(rhr_by_day.values())
    load = defaultdict(float)
    for w in workouts:
        d = day_of(w)
        load[d] += trimp(w['score'].get('zone_durations'), max_hr, rhr_by_day.get(d, usual)) or 0.0
    by_day = {d: load.get(d, 0.0) for d in strain}

    days = sorted(by_day)
    series = []
    for i, d in enumerate(days):
        acute = [by_day[k] for k in days if shift(d, 6) <= k <= d]
        chronic = [by_day[k] for k in days if shift(d, 27) <= k <= d]
        if len(acute) < 4 or len(chronic) < 21 or (datetime.fromisoformat(d) - datetime.fromisoformat(days[0])).days < 27:
            continue
        c = mean(chronic)
        if c:
            series.append({'date': d, 'v': round(mean(acute) / c, 2)})
    check('load ratio: days', len(D['acwr']), len(series))
    got = {p['date']: p['v'] for p in D['acwr']}
    check('load ratio: every day', [p['date'] for p in series if abs(got.get(p['date'], -9) - p['v']) > 0.01][:5], [])
    if D.get('load_today'):
        check("load ratio: today's value", D['load_today']['ratio'], series[-1]['v'], 0.01)
        check("load ratio: today's load", D['load_today']['load'], round(by_day[max(days)]), 1)
    check('load ratio: it never changes the plan', 'load' in (D['readiness'].get('reasons') or []), False)

    # Foster monotony, complete weeks only
    weeks = defaultdict(list)
    for d in sorted(strain):
        dt = datetime.fromisoformat(d)
        weeks['%04d-W%02d' % dt.isocalendar()[:2]].append(d)
    want = {}
    for wk, ds in weeks.items():
        if len(ds) < 7:
            continue
        vals = [by_day.get(d, 0.0) for d in ds]
        s = sd(vals, sample=False)
        want[wk] = round(mean(vals) / s, 2) if s else None
    got_m = {m['week']: m['monotony'] for m in D['monotony']}
    check('monotony: weeks', len(D['monotony']), len(want))
    check('monotony: every week', [w for w in want if got_m.get(w) != want[w]][:5], [])


# ---- sleep regularity ----------------------------------------------------------------------------
def sleep_regularity_checks(D, nights, naps):
    S = D.get('sleep_regularity')
    if not S:
        return
    asleep = {}
    for s in list(nights) + list(naps):
        tz = tz_of(s.get('timezone_offset'))
        start, end = parse(s['start']).astimezone(tz), parse(s['end']).astimezone(tz)
        # whole minutes only: an episode ending 07:12:25 does not own the minute 07:12
        cur = start.replace(second=0, microsecond=0)
        while cur + timedelta(minutes=1) <= end:
            asleep.setdefault(cur.date().isoformat(), set()).add(cur.hour * 60 + cur.minute)
            cur += timedelta(minutes=1)
    dates = sorted(asleep)[1:-1]                    # boundary days are only partly observed
    complete = set(dates)
    same = {}
    for d in dates:
        nxt = shift(d, -1)
        if nxt in complete:
            a, b = asleep[d], asleep[nxt]
            same[d] = 1440 - len(a ^ b)
    last = D['sleep_regularity']['date']
    window = [k for k in same if shift(last, 29) <= k <= last]
    if window:
        want = round(200 * (sum(same[k] for k in window) / (1440 * len(window))) - 100, 1)
        check('sleep regularity: the index', S['value'], want, 0.05)
    check('sleep regularity: window is 30 days', S['window_days'], 30)
    check('sleep regularity: in range', -100 <= S['value'] <= 100, True)


def bedtime_checks(D, nights):
    B = D.get('bedtime_target')
    if not B:
        return
    recent = sorted([s for s in nights if s['score'].get('sleep_needed')], key=lambda s: s['end'])[-30:]
    wakes = sorted(local_hour(s['end'], s.get('timezone_offset')) for s in recent)
    med = median(wakes)
    need = recent[-1]['score']['sleep_needed']
    total = sum(need.get(k, 0) for k in ('baseline_milli', 'need_from_sleep_debt_milli',
                                         'need_from_recent_strain_milli', 'need_from_recent_nap_milli')) / 3600000
    check('bedtime: nights used', B['nights'], len(recent))
    check("bedtime: WHOOP's own need", B['need_h'], round(total, 2), 0.01)
    check('bedtime: usual wake', B['wake'], '%02d:%02d' % (int(med), round((med % 1) * 60) % 60))
    target = (med - total) % 24
    check('bedtime: asleep by', B['asleep_by'], '%02d:%02d' % (int(target), round((target % 1) * 60) % 60))
    check('bedtime: wake spread', B['wake_spread_h'], round(sd(wakes, sample=False), 1), 0.05)


def what_moves_checks(D):
    W = D.get('what_moves')
    if not W:
        return
    # hours asleep is excluded: it is one of the score's own inputs, so it would measure the formula
    check('what moves: five candidates tested', W['candidates'], 5)
    check('what moves: hours asleep is not a candidate',
          'sleep_hours' in {r['key'] for r in W['shown']} | {r['key'] for r in W.get('dropped_jointly', [])}, False)
    for r in W['shown']:
        j = r.get('joint')
        if j is not None:
            check('what moves: %s keeps its sign jointly' % r['key'], (j['coefficient'] > 0) == (r['coefficient'] > 0), True)
            check('what moves: %s joint significance flag' % r['key'], j['significant'], j['p'] < 0.05)
    for t in W.get('tested', []):
        st = t.get('holdout_sign_test')
        if st:
            n = st['wins'] + st['losses']
            p_sign = sum(math.comb(n, k) for k in range(st['wins'], n + 1)) / 2 ** n if n else 1.0
            check('what moves: %s tested sign test recomputed' % t['key'], round(p_sign, 4), st['p'])
        if t.get('passed'):
            check('what moves: %s passed means every gate passed' % t['key'],
                  bool(t['significant'] and t['monotone'] and st and st['passes'] and t['stable']), True)
    check('what moves: every candidate is reported', len(W.get('tested', [])), W['candidates'])
    check('what moves: shown only from those that passed',
          {r['key'] for r in W['shown']} <= {t['key'] for t in W.get('tested', []) if t.get('passed')}, True)
    for r in W.get('dropped_jointly', []):
        check('what moves: %s dropped for a stated reason' % r['key'], r['reason'] in ('flips', 'redundant'), True)
    for r in W['shown']:
        check('what moves: %s is significant' % r['key'], r['p'] < 0.05, True)
        check('what moves: %s is even across terciles' % r['key'],
              r['terciles'] == sorted(r['terciles'], reverse=r['coefficient'] < 0), True)
        st = r.get('holdout_sign_test') or {}
        n = st.get('wins', 0) + st.get('losses', 0)
        p_sign = sum(math.comb(n, k) for k in range(st.get('wins', 0), n + 1)) / 2 ** n if n else 1.0
        check('what moves: %s sign test recomputed' % r['key'], round(p_sign, 4), st.get('p'))
        check('what moves: %s wins more days than chance' % r['key'], p_sign < 0.05, True)
        halves = r.get('halves') or []
        check('what moves: %s holds in both halves' % r['key'],
              len(halves) == 2 and all(h['p'] < 0.05 and (h['coefficient'] > 0) == (r['coefficient'] > 0) for h in halves), True)
        check('what moves: %s is a whole point' % r['key'], r['points'] != 0, True)
        want = round(phi(r['coefficient']) - phi(0.0))
        check('what moves: %s in readiness points' % r['key'], r['points'], want)


def records_checks(D, raw, workouts, strain, recovery, asleep_h, day_of):
    R = D['records']
    check('record: best recovery', R['best_recovery']['v'], max(recovery.values()))
    check('record: worst recovery', R['worst_recovery']['v'], min(recovery.values()))
    check('record: biggest day strain', R['biggest_strain_day']['v'], round(max(strain.values()), 1), 0.05)
    check('record: biggest workout strain', R['biggest_strain_workout']['v'],
          round(max(w['score']['strain'] for w in workouts), 1), 0.05)
    longest = max(max(0, s['score']['stage_summary']['total_in_bed_time_milli']
                      - s['score']['stage_summary']['total_awake_time_milli']) / 3600000
                  for s in raw['sleep'] if s.get('score'))
    check('record: longest sleep', R['longest_sleep_h']['v'], round(longest, 2), 0.05)
    hrvs = [r['score']['hrv_rmssd_milli'] for r in raw['recovery'] if r.get('score')]
    check('record: peak HRV', R['best_hrv']['v'], round(max(hrvs)), 1)
    rhrs = [r['score']['resting_heart_rate'] for r in raw['recovery'] if r.get('score')]
    check('record: lowest resting HR', R['lowest_rhr']['v'], min(rhrs))
    check('record: total sessions', D['total_workouts'], len(workouts))


# ---- sessions, zones and sports -----------------------------------------------------------------
SEILER = (0.82, 0.87)


def intensity_minutes(zones, max_hr, rest_hr):
    """Minutes easy / moderate / hard, converting WHOOP's heart-rate-RESERVE zones to % of max."""
    if not zones or not max_hr or not rest_hr or max_hr <= rest_hr:
        return None
    lines = [f * max_hr for f in SEILER]
    out = [0.0, 0.0, 0.0]
    for key, lo, hi in WHOOP_ZONES:
        minutes = (zones.get(key) or 0) / 60000
        if not minutes:
            continue
        a, b = rest_hr + lo * (max_hr - rest_hr), rest_hr + hi * (max_hr - rest_hr)
        below = [min(1.0, max(0.0, (ln - a) / (b - a))) for ln in lines]
        out[0] += minutes * below[0]
        out[1] += minutes * (below[1] - below[0])
        out[2] += minutes * (1 - below[1])
    return out


def session_checks(D, raw, workouts, day_of):
    """Every session's intensity label, recomputed from its own zone minutes."""
    max_hr = raw['body']['max_heart_rate']
    rhr_by_day = {day_of(r): r['score']['resting_heart_rate'] for r in raw['recovery'] if r.get('score')}
    usual = mean(rhr_by_day.values())          # the dashboard's fallback is the mean
    by_key = {}
    for w in workouts:
        d = day_of(w)
        mins = intensity_minutes(w['score'].get('zone_durations'), max_hr, rhr_by_day.get(d, usual))
        if w['sport_name'] in STRENGTH or not mins or sum(mins) == 0:
            level = None
        else:
            # NOT a plain argmax: easy only when the two upper zones together are outweighed by
            # easy time, then hard or moderate by whichever of those two holds more
            level = ('easy' if mins[1] + mins[2] <= mins[0]
                     else 'hard' if mins[2] >= mins[1] else 'moderate')
        by_key.setdefault((d, round(w['score']['strain'], 1)), []).append(level)
    wrong = []
    for row in D['workout_log']:
        want = by_key.get((row['date'], row['strain']))
        if want and row['intensity'] not in want:
            wrong.append(row['date'])
    check('sessions: every intensity label', wrong[:5], [])
    check('sessions: logged count', len(D['workout_log']), len(workouts))
    labels = Counter(r['intensity'] for r in D['workout_log'])
    check('sessions: labels are only the three zones or strength',
          set(labels) - {'easy', 'moderate', 'hard', None}, set())

    zones = D['zone_distribution']['weekly']
    check('zones: complete weeks only', all(z['easy_h'] is not None for z in zones), True)
    check('zones: 8 weeks shown', len(zones), 8)
    check('zones: hours are never negative',
          all(z['easy_h'] >= 0 and z['mod_h'] >= 0 and z['hard_h'] >= 0 for z in zones), True)


def sport_checks(D, log, recovery):
    """Each sport row: next-morning recovery after days that sport was the hardest session."""
    S = D['sport_recovery_cost']
    hardest = {}                       # the day's hardest session is simply its highest strain
    for row in log:
        best = hardest.get(row['date'])
        if best is None or row['strain'] > best[0]:
            hardest[row['date']] = (row['strain'], row['sport'])
    by_sport = defaultdict(list)
    for d, (_strain, sport) in hardest.items():
        nxt = shift(d, -1)
        if nxt in recovery:
            by_sport[sport].append(recovery[nxt])
    for row in S['sports']:
        vals = by_sport.get(row['sport'])
        if not vals:
            continue
        check('sport: %s days' % row['sport'], row['n'], len(vals))
        check('sport: %s next-morning recovery' % row['sport'], row['avg_next_recovery'],
              round(mean(vals), 1), 0.05)
        check('sport: %s significance needs 30 a side' % row['sport'],
              bool(row['significant']) and len(vals) < 30, False)


def sleep_night_checks(D, nights, day_of, strain):
    """Individual nights in the last 7 days, not a day's total — naps are not nights."""
    N = D['sleep_nights']
    today = max(strain)
    recent = [s for s in nights
              if 0 <= (datetime.fromisoformat(today) - datetime.fromisoformat(day_of(s))).days < 7]
    hours = [max(0, s['score']['stage_summary']['total_in_bed_time_milli']
                 - s['score']['stage_summary']['total_awake_time_milli']) / 3600000 for s in recent]
    check('sleep: nights counted in the last 7 days', N['nights'], len(recent))
    check('sleep: nights of 7h+ in the last 7', N['nights_7h'], sum(1 for h in hours if h >= N['min_hours']))
    check('sleep: the bar is the AASM 7 hours', N['min_hours'], 7)
    R = D['rest_day_stat']
    check('rest day: days since', R['days_since'],
          (datetime.fromisoformat(max(strain)) - datetime.fromisoformat(R['last_rest_date'])).days)


def training_cost_checks(D):
    """The three gates, and that nothing is shown unless all three pass."""
    T = D.get('training_cost')
    if not T:
        return
    check('training cost: significant means p < 0.05 and negative',
          T['significant'], bool(T['p'] < 0.05 and T['per_strain'] < 0))
    if T['tercile_next_night']:
        t = T['tercile_next_night']
        check('training cost: monotone gate', T['linear'], t[0] >= t[1] >= t[2])
    st = T.get('holdout_sign_test')
    if st:
        n = st['wins'] + st['losses']
        p_sign = sum(math.comb(n, k) for k in range(st['wins'], n + 1)) / 2 ** n if n else 1.0
        check('training cost: sign test recomputed', round(p_sign, 4), st['p'])
        check('training cost: hold-out gate is the sign test', bool(T['holdout_better']), p_sign < 0.05)
    check('training cost: shown only if all three pass', T['usable'],
          bool(T['significant'] and T['linear'] and T['holdout_better']))
    check('training cost: not shown means no adjusted score', T['after'] is None, not T['usable'])


def per_day_checks(D, strain, recovery):
    """The last 60 days one at a time, so a failure names the day."""
    st = {p['date']: p['v'] for p in D['full_series']['strain']}
    rc = {p['date']: p['v'] for p in D['full_series']['recovery']}
    for d in sorted(strain)[-60:]:
        check('strain on %s' % d, st.get(d), round(strain[d], 1), 0.05)
    for d in sorted(recovery)[-60:]:
        check('recovery on %s' % d, rc.get(d), recovery[d], 0.5)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
