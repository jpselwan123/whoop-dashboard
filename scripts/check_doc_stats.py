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

Exit status is 1 if any documented figure no longer matches, 0 otherwise. Reads whoop_data.json
and the tracked docs; writes nothing.
"""
import io, contextlib, json, math, os, sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import build_dashboard as bd     # noqa: E402


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
    ]
    return ['%s no longer says %r (%s)' % (where, text, what)
            for doc, where, text, what in expected if text not in doc]


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
        y, y2, y3 = (bd._date_minus(d, k) for k in (1, 2, 3))
        if all(k in ln_hrv for k in (y, y2, y3)) and ln_hrv[y] < ln_hrv[y2] < ln_hrv[y3]:
            literal.add(d)          # HRV fell on each of the two days before today
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


def check_measured_docs(facts, root=HERE):
    """Sentences quoting a MEASURED figure — checked only when real data is present.

    These drift legitimately as days are added, so this is a report, not a CI assertion.
    """
    if not facts:
        return []
    source = open(os.path.join(root, 'build_dashboard.py')).read()
    prompt = open(os.path.join(root, 'chat_server.py')).read()
    sr, tr = facts.get('strain_ratio'), facts.get('trimp_ratio')
    br, rr_ = facts.get('breathing'), facts.get('rest_rules')
    expected = []
    if br:
        expected.append((source, 'build_dashboard.py',
                         'over the %d nights with enough baseline to judge, the largest rise was\n# +%.1f/min'
                         % (br['nights'], br['largest_rise']), 'the breathing rule that never fired'))
    if rr_:
        expected.append((prompt, 'chat_server.py',
                         'firing 0 times in %d days' % rr_['days'],
                         'how long the deleted hard-days rule sat there doing nothing'))
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
    return ['%s no longer says %r (%s)' % (where, text, what)
            for doc, where, text, what in expected if text not in doc]


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

    if problems:
        print('\nSTALE DOCUMENTATION:')
        for p in problems:
            print('  - ' + p)
        return 1
    print('\ndocumented constants match the code.')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
