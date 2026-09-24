"""Recompute every statistic the documentation quotes, and check the docs still match.

Numbers pasted into a README or a docstring go stale silently: the data grows, the model changes,
and the prose keeps claiming what was true months ago. This script is the antidote. It recomputes
each quoted figure from a fresh run and compares it with the sentence that quotes it.

Two kinds of figure are handled differently:

* **Derived from code constants** (the band lines and the share of days a normal curve puts either
  side of them). These cannot drift with the data, so a mismatch is always a documentation bug —
  and they are checked by the test suite on every run, with no data of any kind.
* **Measured on real history** (band shares actually observed, day counts, spreads, correlations).
  These move as days are added, so drift is expected rather than wrong. Run this script after a
  refresh, and update the sentences it reports.

Usage:  python3 scripts/check_doc_stats.py [data_dir]     (default: the repo root)
        python3 scripts/check_doc_stats.py --constants-only     (no data needed)
        python3 scripts/check_doc_stats.py --fix                (rewrite stale figures in place)

Exit status is 1 if any documented figure no longer matches, 0 otherwise. Reads whoop_data.json
and the tracked docs; writes nothing.
"""
import io, contextlib, json, math, os, re, sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import build_dashboard as bd     # noqa: E402


class Stale(str):
    """One out-of-date sentence: prints as a one-line complaint, and carries what --fix needs."""

    def __new__(cls, where, text, what):
        obj = str.__new__(cls, '%s no longer says %r (%s)' % (where, text, what))
        obj.where, obj.text, obj.what = where, text, what
        return obj


# ---- figures that follow from the constants alone ------------------------------------------
def constant_facts():
    """The band lines and their target shares — fixed by READY_SWC / READY_REST_SD, not by data."""
    train, rest = bd.READY_LINES['train'], bd.READY_LINES['rest']
    above = 100 - bd.normal_percentile(-bd.READY_SWC)
    below = bd.normal_percentile(-bd.READY_REST_SD)
    return {
        'train_line': train,
        'rest_line': rest,
        'target_plan': round(above, 1),
        'target_easy': round(100 - above - below, 1),
        'target_rest': round(below, 1),
    }


def check_constant_docs(root=HERE):
    """Sentences in the docs that quote a constant-derived figure must quote the current one.

    Returns a list of complaints; empty means the documentation is in step with the code.
    """
    f = constant_facts()
    readme = open(os.path.join(root, 'README.md')).read()
    source = open(os.path.join(root, 'build_dashboard.py')).read()
    expected = [
        (readme, 'README.md', '**%d+**' % f['train_line'], 'the Train-as-planned line'),
        (readme, 'README.md', 'under **%d**' % f['rest_line'], 'the Rest line'),
        (readme, 'README.md',
         'against the %.1f / %.1f / %.1f%% the SD lines correspond to'
         % (f['target_plan'], f['target_easy'], f['target_rest']), 'the target band shares'),
        (source, 'build_dashboard.py', "−0.5 SD = %d" % f['train_line'], 'the lower line'),
        (source, 'build_dashboard.py', "−1.5 SD = %d" % f['rest_line'], 'the rest line'),
        # the "choices that are ours" table must quote the constants the code actually uses
        (readme, 'README.md', 'at least **%d** single nights' % (bd.READY_BASELINE_DAYS // 2), 'the last-night baseline minimum'),
        (readme, 'README.md', '**%d** days of data in the 7-day window, **%d** in the 28'
         % (bd.ACWR_MIN_DAYS['acute'], bd.ACWR_MIN_DAYS['chronic']), 'the load-ratio data minimums'),
        (readme, 'README.md', 'fit on the first **%d%%**, test on the last **%d%%**'
         % (round(100 * (1 - bd.HOLDOUT)), round(100 * bd.HOLDOUT)), 'the hold-out split'),
        (readme, 'README.md', '| Newey-West lag | **%d** days' % bd.NEWEY_WEST_LAG, 'the Newey-West lag'),
        (readme, 'README.md', 'at least **%d** days in each third' % (bd.MIN_GROUP // 3), 'the tercile minimum'),
        (readme, 'README.md', 'at least **%d** of the %d days observed' % (bd.SRI_WINDOW_DAYS // 2, bd.SRI_WINDOW_DAYS),
         'the regularity minimum'),
        (readme, 'README.md', 'median of the last **%d** nights' % bd.BEDTIME_WAKE_WINDOW_DAYS, 'the wake-time window'),
        (readme, 'README.md', 'in the last **%d** days' % bd.WHAT_IF_WINDOW_DAYS, 'the what-if range'),
        (readme, 'README.md', 'nights **%d–%d** days back, **%d**+ of them'
         % (bd.BREATHING_BASELINE[0], bd.BREATHING_BASELINE[1], bd.BREATHING_MIN_NIGHTS), 'the breathing baseline'),
        (readme, 'README.md', '| Rest on a sustained fall | **%s** day in a row' % {2: '2nd', 3: '3rd'}.get(bd.DAYS_LOW_TO_REST, bd.DAYS_LOW_TO_REST),
         'the sustained-fall count'),
    ]
    return [Stale(where, text, what) for doc, where, text, what in expected if text not in doc]


# ---- figures measured on real history --------------------------------------------------------
def measured_facts(data_dir):
    """Rebuild the dashboard and measure everything the prose quotes about this person's history."""
    raw = json.load(open(os.path.join(data_dir, 'whoop_data.json')))
    series, composites, inputs = _rebuild(raw)
    scored = [p['date'] for p in series]
    comp = [composites[d] for d in scored]
    n = len(comp)
    mean_c = sum(comp) / n
    sd_c = math.sqrt(sum((v - mean_c) ** 2 for v in comp) / (n - 1))
    z = [(v - mean_c) / sd_c for v in comp]

    lines = bd.READY_LINES
    vals = [p['v'] for p in series]
    bands = {
        'plan': sum(1 for v in vals if v >= lines['train']),
        'easy': sum(1 for v in vals if lines['rest'] <= v < lines['train']),
        'rest': sum(1 for v in vals if v < lines['rest']),
    }
    answers = {}
    for p in series:
        answers[p['answer']] = answers.get(p['answer'], 0) + 1

    r, pairs = _autocorrelation(series)
    n_eff = n * (1 - r * r) / (1 + r * r)
    cycles = raw['cycles']
    keys = [bd.record_day(c) for c in cycles]          # after the rebuild, so the day map is built
    utc_keys = [c['created_at'][:10] for c in cycles]
    start_keys = [bd.local_day(c['start'], c.get('timezone_offset')) for c in cycles]

    return {
        'as_of': max(keys) if keys else None,
        'cycles': len(cycles),
        'distinct_days': len(set(keys)),
        'key_collisions': len(cycles) - len(set(keys)),
        'collisions_if_utc_day': len(cycles) - len(set(utc_keys)),
        'collisions_if_cycle_start': len(cycles) - len(set(start_keys)),
        'scored_days': n,
        'band_shares': {k: round(100 * v / n, 1) for k, v in bands.items()},
        'answer_shares': {k: round(100 * v / n, 1) for k, v in answers.items()},
        'composite_sd': round(sd_c, 2),
        'composite_skew': round(sum(x ** 3 for x in z) / n, 2),
        'composite_kurtosis': round(sum(x ** 4 for x in z) / n - 3, 2),
        'autocorrelation': round(r, 2),
        'autocorrelation_pairs': pairs,
        'effective_n': round(n_eff),
        'sd_error_pct': round(100 / math.sqrt(2 * n_eff), 1),
        'sd_error_90d_pct': round(100 / math.sqrt(2 * (90 * (1 - r * r) / (1 + r * r))), 1),
        'variance_shares': _variance_shares(series, inputs),
        'breathing': _breathing(inputs['rr']),
        'strain_ratio': _strain_ratio(raw),
        'training_cost': _training_cost(data_dir),
        'plan_effect': _plan_effect(data_dir),
        'trimp_ratio': _trimp_ratio(data_dir),
        'rest_rules': _rest_rules(series, inputs['hrv']),
        'what_moves': _what_moves(data_dir),
        'sleep_regularity': _sleep_regularity(data_dir),
        'bedtime': _bedtime(data_dir),
        'window_90d': _window_experiment(series, composites),
        'plan_adherence': _plan_adherence(data_dir, series),
        'rule_firings': _rule_firings(series),
    }


def _rebuild(raw):
    """Run the real pipeline, keeping the readiness series, the composites and the raw inputs."""
    grabbed = {}
    orig_readiness, orig_percentile = bd.build_readiness, bd.percentile_series

    def spy_readiness(*a, **k):
        grabbed['inputs'] = a
        latest, series = orig_readiness(*a, **k)
        grabbed['series'] = series
        return latest, series

    def spy_percentile(raw_by_day):
        grabbed.setdefault('composites', dict(raw_by_day))
        return orig_percentile(raw_by_day)

    bd.build_readiness, bd.percentile_series = spy_readiness, spy_percentile
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            bd.build_summary(raw)
    finally:
        bd.build_readiness, bd.percentile_series = orig_readiness, orig_percentile

    hrv, rhr, rr, sleep = grabbed['inputs']
    inputs = {
        'hrv': {k: math.log(v) for k, v in hrv.items() if v and v > 0},
        'rhr': {k: v for k, v in rhr.items() if v},
        'sleep': {k: v for k, v in (sleep or {}).items() if v},
        'rr': rr,
    }
    return grabbed['series'], grabbed['composites'], inputs


def _autocorrelation(series):
    """Correlation between a day's score and the *calendar* next day's, skipping gaps in the data."""
    by_day = {p['date']: p['v'] for p in series}
    pairs = [(by_day[d], by_day[bd._date_minus(d, -1)])
             for d in sorted(by_day) if bd._date_minus(d, -1) in by_day]
    a = [x for x, _ in pairs]
    b = [y for _, y in pairs]
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    den = math.sqrt(sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b))
    return (num / den if den else 0.0), len(pairs)


def _variance_shares(series, inputs):
    """How much of the score's variance each of the six inputs actually carries.

    Equal weights on six standard scores are not equal shares of the result: the inputs that move
    more, and that move with the others, count for more. Share = cov(input/6, composite) / var.
    """
    order = [('trend_hrv', 'hrv', 'below', bd.judge_marker), ('trend_rhr', 'rhr', 'above', bd.judge_marker),
             ('trend_sleep', 'sleep', 'below', bd.judge_marker), ('night_hrv', 'hrv', 'below', bd.judge_last_night),
             ('night_rhr', 'rhr', 'above', bd.judge_last_night), ('night_sleep', 'sleep', 'below', bd.judge_last_night)]
    cols = {name: {} for name, _, _, _ in order}
    for p in series:
        for name, key, worse, fn in order:
            m = fn(inputs[key], p['date'], worse)
            if m and m.get('z') is not None:
                cols[name][p['date']] = m['z']
    days = [p['date'] for p in series if all(p['date'] in cols[name] for name, _, _, _ in order)]
    if len(days) < bd.MIN_GROUP:
        return None
    comp = {d: sum(cols[name][d] for name, _, _, _ in order) / len(order) for d in days}
    mc = sum(comp.values()) / len(days)
    var = sum((comp[d] - mc) ** 2 for d in days) / (len(days) - 1)
    out = {}
    for name, _, _, _ in order:
        mu = sum(cols[name][d] for d in days) / len(days)
        cov = sum((cols[name][d] - mu) * (comp[d] - mc) for d in days) / (len(days) - 1)
        out[name] = round(100 * (cov / len(order)) / var, 1)
    out['trend_total'] = round(sum(out[n] for n in ('trend_hrv', 'trend_rhr', 'trend_sleep')), 1)
    out['night_total'] = round(sum(out[n] for n in ('night_hrv', 'night_rhr', 'night_sleep')), 1)
    out['sleep_total'] = round(out['trend_sleep'] + out['night_sleep'], 1)
    return out


def _breathing(rr_by_day):
    """The rule we removed claimed +3 breaths/min was worth resting on — how close did it ever get?"""
    nights, largest = 0, 0.0
    for d in sorted(rr_by_day):
        b = bd.breathing_check(rr_by_day, d)
        if b:
            nights += 1
            largest = max(largest, b['above_usual'])
    return {'nights': nights, 'largest_rise': round(largest, 1)}


def _strain_ratio(raw):
    """The load ratio as it was before it moved to TRIMP: did the top band ever come within reach?"""
    strain = {}
    for c in raw['cycles']:
        v = (c.get('score') or {}).get('strain')
        if v is not None:
            strain[bd.record_day(c)] = v
    series = bd.build_acwr(strain)
    if not series:
        return None
    vals = [p['v'] if isinstance(p, dict) else p[1] for p in series]
    m = sum(vals) / len(vals)
    return {'days': len(vals), 'highest': round(max(vals), 2),
            'sd': round(math.sqrt(sum((v - m) ** 2 for v in vals) / (len(vals) - 1)), 2)}


def _training_cost(data_dir):
    """What the README quotes about today's strain and the next night, straight from the build.

    The figures are produced by `build_training_cost` and carried in the dashboard payload, so this
    reads them rather than reimplementing the regression — the independent check script is what
    verifies the maths.
    """
    path = os.path.join(data_dir, 'dashboard_data.json')
    if not os.path.exists(path):
        return None
    tc = json.load(open(path)).get('training_cost')
    if not tc:
        return None
    mae = tc.get('holdout_mae') or [None, None]
    return {
        'sign_test': tc.get('holdout_sign_test'),
        'per_strain': tc.get('per_strain'),
        'p': tc.get('p'),
        'pairs': tc.get('pairs'),
        'terciles': tc.get('tercile_next_night'),
        'holdout_mae_null': mae[0],
        'holdout_mae_adjusted': mae[1],
        'significant': tc.get('significant'),
        'monotone': tc.get('linear'),
        'beats_doing_nothing': tc.get('holdout_better'),
        'displayed': tc.get('usable'),
    }


def _plan_effect(data_dir):
    """The offline question: what does a session cost the next night, and does readiness change it?

    Same regression as `scripts/analyse_plan_effect.py`, imported rather than copied so the two can
    never disagree.
    """
    try:
        import analyse_plan_effect as ape
    except ImportError:
        return None
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        ape.main(data_dir)
    rows = {}
    for line in buf.getvalue().splitlines():
        parts = line.strip().split()
        if 't' not in parts or 'se' not in parts:
            continue
        i_se, i_t = parts.index('se'), parts.index('t')
        rows[' '.join(parts[:i_se - 1])] = {'coefficient': float(parts[i_se - 1]),
                                            't': float(parts[i_t + 1])}
    intensity = rows.get('session intensity')
    interaction = next((v for k, v in rows.items() if k.startswith('score') and 'intensity' in k), None)
    if not intensity:
        return None
    return {
        'per_intensity_step': round(intensity['coefficient'], 3),
        'intensity_t': round(intensity['t'], 2),
        'interaction_t': round(interaction['t'], 2) if interaction else None,
    }


def _trimp_ratio(data_dir):
    """The load ratio as it is actually shown — on Edwards TRIMP."""
    path = os.path.join(data_dir, 'dashboard_data.json')
    if not os.path.exists(path):
        return None
    vals = [p['v'] for p in (json.load(open(path)).get('acwr') or [])]
    if not vals:
        return None
    ordered = sorted(vals)
    return {'days': len(vals), 'median': round(ordered[len(vals) // 2], 2), 'highest': round(max(vals), 2),
            'over_high_pct': round(100 * sum(1 for v in vals if v > bd.ACWR_BANDS['high']) / len(vals), 1)}


def _rest_rules(series, ln_hrv):
    """The implemented sustained-fall rule against Kiviniemi's literal one — measured, not applied.

    The dashboard rests on the 2nd consecutive day BELOW the normal band. Kiviniemi 2007's "decreasing
    trend for 2 days" is something else: two successive DROPS in HRV, whatever level it is at. Neither
    is obviously right, so both are measured here and the numbers are quoted in the README; only the
    first is implemented.

    Both rules must be evaluated for the SAME day: today's HRV is known each morning, so Kiviniemi's
    two drops end today, exactly as the implemented run of low days includes today. An earlier version
    compared a run ending today against drops ending yesterday, which made the two look far more
    different than they are.
    """
    days = [p['date'] for p in series]
    score = {p['date']: p['v'] for p in series}
    train = bd.READY_LINES['train']

    def below_run(d):
        n, cur = 0, d
        while score.get(cur) is not None and score[cur] < train:
            n += 1
            cur = bd._date_minus(cur, 1)
        return n

    implemented, literal = set(), set()
    for d in days:
        if below_run(d) >= bd.DAYS_LOW_TO_REST:
            implemented.add(d)
        y, y2 = (bd._date_minus(d, k) for k in (1, 2))
        if all(k in ln_hrv for k in (d, y, y2)) and ln_hrv[d] < ln_hrv[y] < ln_hrv[y2]:
            literal.add(d)          # HRV fell on today and on the day before
    n = len(days)
    return {
        'days': n,
        'implemented_fires': len(implemented),
        'implemented_pct': round(100 * len(implemented) / n, 1),
        'kiviniemi_literal_fires': len(literal),
        'kiviniemi_literal_pct': round(100 * len(literal) / n, 1),
        'disagree_days': len(implemented ^ literal),
        'disagree_pct': round(100 * len(implemented ^ literal) / n, 1),
        'both_fire': len(implemented & literal),
    }


def _what_moves(data_dir):
    """Which of the candidates survive the gates, and by how much."""
    path = os.path.join(data_dir, 'dashboard_data.json')
    if not os.path.exists(path):
        return None
    with open(path) as fh:
        wm = json.load(fh).get('what_moves')
    if not wm:
        return None
    return {'candidates': wm['candidates'], 'shown': len(wm['shown']),
            'dropped_jointly': wm.get('dropped_jointly', []),
            'tested': wm.get('tested', []),
            'rows': [{'key': r['key'], 'points': r['points'], 'days': r['days'],
                      'holdout_margin': r['holdout_margin']} for r in wm['shown']]}


def _sleep_regularity(data_dir):
    """The index, its 30-day move, and how it relates to readiness on this history."""
    path = os.path.join(data_dir, 'dashboard_data.json')
    if not os.path.exists(path):
        return None
    with open(path) as fh:
        sr = json.load(fh).get('sleep_regularity')
    if not sr:
        return None
    return {k: sr[k] for k in ('value', 'change_30d', 'days', 'readiness_r', 'readiness_days')}


def _bedtime(data_dir):
    path = os.path.join(data_dir, 'dashboard_data.json')
    if not os.path.exists(path):
        return None
    with open(path) as fh:
        b = json.load(fh).get('bedtime_target')
    if not b:
        return None
    total_min = round(b['wake_spread_h'] * 60)
    return {'spread_h': b['wake_spread_h'],
            'spread_hm': '%dh %02dm' % divmod(total_min, 60) if total_min >= 60 else '%dm' % total_min}


def _window_experiment(series, composites):
    """How much a 90-day rolling ruler would change the band, against the expanding one used."""
    ordered = sorted(composites)
    lines = bd.READY_LINES
    band = lambda v: 'plan' if v >= lines['train'] else 'easy' if v >= lines['rest'] else 'rest'
    shown = {p['date']: p['v'] for p in series}
    changed = total = 0
    for i, d in enumerate(ordered):
        if d not in shown:
            continue
        hist = [composites[k] for k in ordered[:i] if k >= bd._date_minus(d, 90)]
        if len(hist) < bd.READY_BASELINE_DAYS:
            continue
        m = sum(hist) / len(hist)
        sd = math.sqrt(sum((v - m) ** 2 for v in hist) / (len(hist) - 1))
        if not sd:
            continue
        v90 = max(1, min(99, round(bd.normal_percentile((composites[d] - m) / sd))))
        total += 1
        changed += band(v90) != band(shown[d])
    return {'days': total, 'band_changes_pct': round(100 * changed / total) if total else None}


def _plan_adherence(data_dir, series):
    """Next-morning recovery after days the plan was followed vs overridden (the card that was removed)."""
    path = os.path.join(data_dir, 'dashboard_data.json')
    if not os.path.exists(path):
        return None
    with open(path) as fh:
        D = json.load(fh)
    rec = {p['date']: p['v'] for p in D['full_series'].get('recovery', [])}
    hard = {w['date'] for w in D['workout_log'] if w.get('intensity') in ('moderate', 'hard')}
    followed, overrode = [], []
    for p in series:
        nxt = bd._date_minus(p['date'], -1)
        if nxt not in rec:
            continue
        (overrode if (p['date'] in hard and p['answer'] in ('easy', 'rest')) else followed).append(rec[nxt])
    if not followed or not overrode:
        return None
    return {'followed_days': len(followed), 'followed_mean': round(sum(followed) / len(followed), 1),
            'overrode_days': len(overrode), 'overrode_mean': round(sum(overrode) / len(overrode), 1)}


def _rule_firings(series):
    """How often each rest rule decided the answer — the counts the settled-decisions note quotes."""
    L = bd.READY_LINES
    scores = {p['date']: p['v'] for p in series}
    answers, out = {}, {'large_fall': 0, 'sustained': 0, 'cap': 0}
    for p in sorted(series, key=lambda q: q['date']):
        d, v = p['date'], p['v']
        run, cur = 0, d
        while scores.get(cur) is not None and scores[cur] < L['train']:
            run += 1
            cur = bd._date_minus(cur, 1)
        rested_two = all(answers.get(bd._date_minus(d, k)) == 'rest' for k in (1, 2))
        if v < L['rest']:
            out['cap' if rested_two else 'large_fall'] += 1
        elif v < L['train'] and run >= bd.DAYS_LOW_TO_REST:
            out['cap' if rested_two else 'sustained'] += 1
        answers[d] = p['answer']
    return out


def check_measured_docs(facts, root=HERE):
    """Sentences quoting a MEASURED figure — checked only when real data is present.

    These drift legitimately as days are added, so this is a report, not a CI assertion.
    """
    if not facts:
        return []
    words = {0: 'none', 1: 'one', 2: 'two', 3: 'three', 4: 'four', 5: 'five', 6: 'six'}
    source = open(os.path.join(root, 'build_dashboard.py')).read()
    prompt = open(os.path.join(root, 'chat_server.py')).read()
    readme = open(os.path.join(root, 'README.md')).read()
    sr, tr = facts.get('strain_ratio'), facts.get('trimp_ratio')
    br, rr_ = facts.get('breathing'), facts.get('rest_rules')
    vs = facts.get('variance_shares')
    wm = facts.get('what_moves')
    expected = []
    if br:
        expected.append((source, 'build_dashboard.py',
                         'over the %d nights with enough baseline to judge, the largest rise was\n# +%.1f/min'
                         % (br['nights'], br['largest_rise']), 'the breathing rule that never fired'))
    if rr_:
        expected.append((prompt, 'chat_server.py',
                         'firing 0 times in %d days' % rr_['days'],
                         'how long the deleted hard-days rule sat there doing nothing'))
        expected.append((readme, 'README.md',
                         'triggers on **%d of %d days (%.1f%%)**' % (rr_['implemented_fires'], rr_['days'], rr_['implemented_pct']),
                         'how often the implemented rest rule fires'))
        expected.append((readme, 'README.md',
                         'on **%d (%.1f%%)**, and they **disagree on %d days (%.1f%%)**, agreeing on only %d'
                         % (rr_['kiviniemi_literal_fires'], rr_['kiviniemi_literal_pct'],
                            rr_['disagree_days'], rr_['disagree_pct'], rr_['both_fire']),
                         "Kiviniemi's literal rule and how far the two disagree"))
    if wm:
        expected.append((readme, 'README.md', 'On this history **%s of %s** survive%s' % (
            words.get(wm['shown'], wm['shown']), words.get(wm['candidates'], wm['candidates']),
            's' if wm['shown'] == 1 else ''), 'how many candidates survive'))
    closest = next((t for t in (wm or {}).get('tested', []) if t['key'] == 'strain'), None)
    if closest and closest.get('holdout_sign_test') and not closest.get('passed'):
        st = closest['holdout_sign_test']
        expected.append((readme, 'README.md', 'its adjustment won **%d** and lost **%d** (sign test p = %.2f)'
                         % (st['wins'], st['losses'], st['p']), "day strain's out-of-sample result"))
    if wm and wm['shown'] == 1 and wm['rows'][0]['key'] == 'strain':
        r = wm['rows'][0]
        # the prose uses a typographic minus, so the guard has to look for the same character
        signed = ('\u2212%d' % abs(r['points'])) if r['points'] < 0 else ('+%d' % r['points'])
        expected.append((readme, 'README.md',
                         'is worth **%s point** on the next morning, over %d days' % (signed, r['days']),
                         'the one candidate that passes all three gates'))

    sr_idx = facts.get('sleep_regularity')
    if sr_idx and sr_idx.get('readiness_r') is not None:
        expected.append((readme, 'README.md',
                         'r = %.2f over %d days here' % (sr_idx['readiness_r'], sr_idx['readiness_days']),
                         'sleep regularity against readiness'))
    bt = facts.get('bedtime')
    if bt:
        expected.append((readme, 'README.md', '**always stated** (\u00b1%s here)' % bt['spread_hm'],
                         'the wake-time spread under the bedtime target'))
    claude = open(os.path.join(root, 'CLAUDE.md')).read()
    minus = lambda v: ('−' if v < 0 else '+') + '%s'
    n, bs = facts.get('scored_days'), facts.get('band_shares')
    if n and bs:
        expected += [
            (readme, 'README.md', 'Over %d days the bands caught %.1f%% / %.1f%% / %.1f%% of days'
             % (n, bs['plan'], bs['easy'], bs['rest']), 'the observed band shares'),
            (readme, 'README.md', '%.1f%% above the lower line' % bs['plan'], 'the band share restated under Limitations'),
            (readme, 'README.md', '%.1f%% below the rest line' % bs['rest'], 'the rest share restated under Limitations'),
            (readme, 'README.md', 'Measured over %d days, the trend inputs carry' % n, 'the day count behind the weights'),
            (claude, 'CLAUDE.md', 'in %d days only 2 days ever carried a streak of 2' % n, 'the deleted hard-days rule'),
            (source, 'build_dashboard.py', '#     %d days here only 2 days ever carried a streak of 2' % n,
             'the deleted hard-days rule, in the source'),
            (prompt, 'chat_server.py', 'firing 0 times in %d days' % n, 'the deleted hard-days rule, in the AI prompt'),
        ]
    if n and facts.get('effective_n'):
        expected.append((readme, 'README.md',
                         'so %d days behave like an effective **n ≈ %d** and the spread estimate is good to about '
                         '**±%d%%**; a 90-day window would be ±%d%%'
                         % (n, facts['effective_n'], round(facts['sd_error_pct']), round(facts['sd_error_90d_pct'])),
                         'the effective sample size and the spread error'))
    if facts.get('collisions_if_utc_day') in words and facts.get('collisions_if_cycle_start') in words:
        expected.append((source, 'build_dashboard.py', 'collides\n    on %s and the local date of the cycle start on %s'
                         % (words[facts['collisions_if_utc_day']], words[facts['collisions_if_cycle_start']]),
                         'the day-key collision counts in the DayKey docstring'))
    if facts.get('composite_sd') is not None:
        expected.append((source, 'build_dashboard.py', 'here its spread was %.2f SD' % facts['composite_sd'],
                         "the composite's spread, in the percentile_series docstring"))
    if n and facts.get('composite_sd') is not None:
        expected.append((readme, 'README.md', '(measured here: %.2f SD over %d days' % (facts['composite_sd'], n),
                         "the composite's own spread"))
    if facts.get('composite_skew') is not None:
        expected.append((readme, 'README.md', 'skewness %s, excess kurtosis %s' % (
            ('−%.2f' if facts['composite_skew'] < 0 else '+%.2f') % abs(facts['composite_skew']),
            ('−%.2f' if facts['composite_kurtosis'] < 0 else '+%.2f') % abs(facts['composite_kurtosis'])),
            'how far the days are from normal'))
    w90 = facts.get('window_90d')
    if w90 and w90.get('band_changes_pct') is not None:
        expected.append((readme, 'README.md', 'would put %d%% of days in a different band' % w90['band_changes_pct'],
                         'the rolling-window experiment'))
    pa = facts.get('plan_adherence')
    if pa:
        expected.append((readme, 'README.md', 'followed (%d days → %.1f)' % (pa['followed_days'], pa['followed_mean']),
                         'the plan-adherence split'))
        expected.append((readme, 'README.md', '(**%d days** → %.1f)' % (pa['overrode_days'], pa['overrode_mean']),
                         'the override group'))
    pe = facts.get('plan_effect')
    if pe:
        expected.append((readme, 'README.md', '**−%.3f SD per intensity step** (t = −%.2f)'
                         % (abs(pe['per_intensity_step']), abs(pe['intensity_t'])), 'the offline plan effect'))
        expected.append((readme, 'README.md', '(interaction t = %s%.2f)'
                         % ('+' if pe['interaction_t'] >= 0 else '−', abs(pe['interaction_t'])), 'its interaction'))
    if br:
        expected.append((readme, 'README.md', 'over the %d nights with enough baseline to judge' % br['nights'],
                         'the breathing night count in the README'))
    if sr:
        expected.append((readme, 'README.md', 'over %d days the strain ratio never once reached 1.5 (highest %.2f, SD %.2f)'
                         % (sr['days'], sr['highest'], sr['sd']), 'the strain-ratio comparison in the README'))
        expected.append((claude, 'CLAUDE.md', 'the\n  strain ratio never passed 1.5 in %d days' % sr['days'], 'the same in CLAUDE.md'))
    if tr:
        expected.append((readme, 'README.md', 'above 1.5 on **%.1f%%** of days (median %.2f, highest %.2f)'
                         % (tr['over_high_pct'], tr['median'], tr['highest']), 'the TRIMP ratio in the README'))
        expected.append((claude, 'CLAUDE.md', 'above 1.5 on %.1f%% of days here' % tr['over_high_pct'], 'the same in CLAUDE.md'))
    if facts.get('as_of'):
        expected.append((readme, 'README.md', 'measured on the owner\'s history **as of %s**' % facts['as_of'],
                         'the date the quoted figures refer to'))
    rf, vsh = facts.get('rule_firings'), facts.get('variance_shares')
    if rf and n:
        expected.append((readme, 'README.md', 'Over %d days: rest after a large fall **%d** days, after a\n   sustained fall **%d**, the two-rest-day cap turned a rest into Go easy **%d** times'
                         % (n, rf['large_fall'], rf['sustained'], rf['cap']), 'the settled rest-rule firing counts'))
        expected.append((claude, 'CLAUDE.md', 'Fired over %d days: large\n  fall %d, sustained fall %d, cap %d' % (n, rf['large_fall'], rf['sustained'], rf['cap']),
                         'the same counts in CLAUDE.md'))
    if vsh:
        expected.append((readme, 'README.md', 'trend **%.1f%%**, last\n   night **%.1f%%**' % (vsh['trend_total'], vsh['night_total']),
                         'the settled variance shares'))
        expected.append((claude, 'CLAUDE.md', 'trend %.1f%% / last night %.1f%%' % (vsh['trend_total'], vsh['night_total']),
                         'the same in CLAUDE.md'))
    tcs = (facts.get('training_cost') or {}).get('sign_test')
    if tcs:
        expected.append((readme, 'README.md', 'beat doing nothing on only **%d** of the held-out days and lost on **%d** (%d ties; sign test p = %.2f)'
                         % (tcs['wins'], tcs['losses'], tcs['ties'], tcs['p']), "the training cost's sign test"))
        expected.append((claude, 'CLAUDE.md', 'sign test (%d wins / %d losses,\n  p = %.2f)' % (tcs['wins'], tcs['losses'], tcs['p']),
                         'the same in CLAUDE.md'))
    tc = facts.get('training_cost')
    if tc and tc.get('per_strain') is not None:
        expected.append((readme, 'README.md',
                         '**\u2212%.3f per strain point, p < 0.001, %d day pairs**' % (abs(tc['per_strain']), tc['pairs']),
                         "the training cost's own figures"))
        if tc.get('tercile_next_night'):
            t3 = tc['tercile_next_night']
            fmt = lambda v: ('+' if v >= 0 else '\u2212') + '%.3f' % abs(v)
            expected.append((readme, 'README.md', '%s / %s / %s' % tuple(fmt(v) for v in t3),
                             "the training cost's terciles"))
        if tc.get('holdout_mae'):
            expected.append((readme, 'README.md',
                             'doing nothing (mean error %.1f vs %.1f)' % (tc['holdout_mae'][1], tc['holdout_mae'][0]),
                             'its hold-out errors'))
    if vs:
        # the same measurement is quoted twice — in the weights paragraph and again in Limitations
        share = 'HRV %d%% / resting heart rate %d%% / sleep %d%% on the trend side, %d%% / %d%% / %d%% for last' % (
            round(vs['trend_hrv']), round(vs['trend_rhr']), round(vs['trend_sleep']),
            round(vs['night_hrv']), round(vs['night_rhr']), round(vs['night_sleep']))
        expected.append((readme, 'README.md', share, 'the variance shares in the weights paragraph'))
        limits = 'measured: HRV %d%%, resting HR %d%%, sleep %d%% on the trend side; %d%% / %d%% / %d%% for last night' % (
            round(vs['trend_hrv']), round(vs['trend_rhr']), round(vs['trend_sleep']),
            round(vs['night_hrv']), round(vs['night_rhr']), round(vs['night_sleep']))
        expected.append((readme, 'README.md', limits, 'the same shares restated under Limitations'))
    if sr:
        expected.append((source, 'build_dashboard.py',
                         'over %d days here the strain ratio never once passed 1.5 (highest %.2f, SD %.2f)'
                         % (sr['days'], sr['highest'], sr['sd']), 'the strain-ratio comparison'))
    if tr:
        expected.append((source, 'build_dashboard.py',
                         'it sits above 1.5 on %.1f%% of days' % tr['over_high_pct'],
                         'how often the TRIMP ratio is above the high line'))
        expected.append((prompt, 'chat_server.py',
                         'above 1.5 on %.1f%% of days here' % tr['over_high_pct'],
                         'the same figure in the AI prompt'))
    return [Stale(where, text, what) for doc, where, text, what in expected if text not in doc]


_NUMBER = r'[+−-]?\d+(?:\.\d+)?'
_WORD = r'\b(?:none|one|two|three|four|five|six)\b'


def _pattern(text):
    """The sentence with every number (and number word) left open, so the stale version matches."""
    parts, pos = [], 0
    for m in re.finditer('(%s)|(%s)' % (_NUMBER, _WORD), text):
        parts.append(re.escape(text[pos:m.start()]))
        parts.append(_NUMBER if m.group(1) else _WORD)
        pos = m.end()
    parts.append(re.escape(text[pos:]))
    return re.compile(''.join(parts))


def fix(problems, root=HERE):
    """Replace each stale sentence with the fresh one. Returns the ones it could not place.

    Only a sentence that matches exactly once, with only its numbers different, is rewritten; a
    sentence whose wording changed, or that matches in two places, is left for a person — this never
    guesses. Nothing calls it automatically: run it after a refresh, then read the diff and commit.
    """
    left = []
    for prob in problems:
        path = os.path.join(root, prob.where)
        text = open(path).read()
        hits = list(_pattern(prob.text).finditer(text))
        if len(hits) != 1:
            left.append(prob)
            continue
        m = hits[0]
        with open(path, 'w') as fh:
            fh.write(text[:m.start()] + prob.text + text[m.end():])
    return left


def main(argv):
    problems = check_constant_docs()
    facts = constant_facts()
    print('from the constants (no data needed):')
    print('  lines %d / %d, target shares %.1f / %.1f / %.1f%%'
          % (facts['train_line'], facts['rest_line'],
             facts['target_plan'], facts['target_easy'], facts['target_rest']))

    if '--constants-only' not in argv:
        data_dir = next((a for a in argv[1:] if not a.startswith('-')), HERE)
        if not os.path.exists(os.path.join(data_dir, 'whoop_data.json')):
            print('\nno whoop_data.json in %s — skipping the measured figures' % data_dir)
        else:
            m = measured_facts(data_dir)
            print('\nmeasured on %s:' % data_dir)
            for k in sorted(m):
                print('  %-22s %s' % (k, m[k]))
            if m['key_collisions']:
                print('\n  NOTE: %d cycle(s) share a day key — one day\'s totals overwrite another\'s.'
                      % m['key_collisions'])
            problems += check_measured_docs(m)

    if problems and '--fix' in argv:
        left = fix(problems)
        print('\nfixed %d stale figure(s) in place — read the diff before committing'
              % (len(problems) - len(left)))
        problems = left
    if problems:
        print('\nSTALE DOCUMENTATION:' + (' (these need a person — wording changed or ambiguous)'
                                            if '--fix' in argv else ''))
        for p in problems:
            print('  - ' + p)
        return 1
    print('\ndocumented constants match the code.')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
