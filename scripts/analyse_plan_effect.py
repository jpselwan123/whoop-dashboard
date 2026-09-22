"""Offline: does training against the plan cost you anything the next night?

Not part of the dashboard. The page used to carry a card comparing next-morning WHOOP recovery after
days the plan was followed against days it was overridden, but the groups are far too uneven to test
(7 override days here), and WHOOP recovery shares its inputs with the score, so the two agree by
construction.

This runs the comparison properly, offline, on a cleaner outcome: the **next night's own composite**
(the three single-night standard scores that go into readiness — HRV, resting heart rate and hours
asleep), regressed on today's score, the session intensity done today, and their interaction:

    next_night_z = a + b·today_score_z + c·intensity + d·(today_score_z × intensity)

`c` answers "what does a session of this intensity cost the next night", and `d` answers "does that
cost depend on how ready you were" — which is the question the card could not answer. Standard errors
are Newey-West (lag 7) because consecutive days are dependent; the residual lag-1 autocorrelation is
printed so the correction can be judged.

Usage:  python3 scripts/analyse_plan_effect.py [data_dir]      (default: the repo root)
Reads whoop_data.json; writes nothing.
"""
import io, contextlib, math, os, sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import build_dashboard as bd     # noqa: E402

LAG = 7          # Newey-West bandwidth: a week, the longest window the score itself uses
LEVELS = {'easy': 1.0, 'moderate': 2.0, 'hard': 3.0, 'strength': 1.0}


def ols_newey_west(X, y, lag=LAG):
    """Coefficients with Newey-West standard errors, plus residual lag-1 autocorrelation."""
    n, k = len(y), len(X[0])
    xtx = [[sum(X[i][a] * X[i][b] for i in range(n)) for b in range(k)] for a in range(k)]
    inv = _inverse(xtx)
    if inv is None:
        return None
    xty = [sum(X[i][a] * y[i] for i in range(n)) for a in range(k)]
    beta = [sum(inv[a][b] * xty[b] for b in range(k)) for a in range(k)]
    resid = [y[i] - sum(beta[a] * X[i][a] for a in range(k)) for i in range(n)]
    # meat of the sandwich: S = sum u_t^2 x_t x_t' + weighted cross-products up to `lag`
    S = [[0.0] * k for _ in range(k)]
    for i in range(n):
        for a in range(k):
            for b in range(k):
                S[a][b] += resid[i] * resid[i] * X[i][a] * X[i][b]
    for L in range(1, lag + 1):
        w = 1 - L / (lag + 1)
        for i in range(L, n):
            for a in range(k):
                for b in range(k):
                    S[a][b] += w * resid[i] * resid[i - L] * (X[i][a] * X[i - L][b] + X[i - L][a] * X[i][b])
    var = [[sum(inv[a][p] * S[p][q] * inv[q][b] for p in range(k) for q in range(k)) for b in range(k)]
           for a in range(k)]
    se = [math.sqrt(max(var[a][a], 0.0)) for a in range(k)]
    mr = sum(resid) / n
    r1 = (sum((resid[i] - mr) * (resid[i - 1] - mr) for i in range(1, n))
          / sum((r - mr) ** 2 for r in resid))
    return beta, se, r1, n


def _inverse(m):
    k = len(m)
    a = [row[:] + [1.0 if i == j else 0.0 for j in range(k)] for i, row in enumerate(m)]
    for c in range(k):
        piv = max(range(c, k), key=lambda r: abs(a[r][c]))
        a[c], a[piv] = a[piv], a[c]
        if abs(a[c][c]) < 1e-12:
            return None
        f = a[c][c]
        a[c] = [v / f for v in a[c]]
        for r in range(k):
            if r != c:
                g = a[r][c]
                a[r] = [x - g * y for x, y in zip(a[r], a[c])]
    return [row[k:] for row in a]


def main(data_dir):
    raw = bd.load_raw(data_dir) if hasattr(bd, 'load_raw') else __import__('json').load(
        open(os.path.join(data_dir, 'whoop_data.json')))
    captured = {}
    orig = bd.build_readiness

    def spy(*a, **k):
        captured['args'] = a
        return orig(*a, **k)

    bd.build_readiness = spy
    with contextlib.redirect_stdout(io.StringIO()):
        summary = bd.build_summary(raw)
    bd.build_readiness = orig
    hrv_by_day, rhr_by_day, _rr, sleep_by_day = captured['args']
    ln_hrv = {k: math.log(v) for k, v in hrv_by_day.items() if v and v > 0}
    rhr = {k: v for k, v in rhr_by_day.items() if v}
    sleep_h = {k: v for k, v in sleep_by_day.items() if v}

    night_z = {}
    for d in sorted(ln_hrv):
        ms = [bd.judge_last_night(src, d, worse) for src, worse in
              ((ln_hrv, 'below'), (rhr, 'above'), (sleep_h, 'below'))]
        zs = [m['z'] for m in ms if m]
        if zs:
            night_z[d] = sum(zs) / len(zs)

    score = {p['date']: p['v'] for p in summary['full_series']['readiness']}
    intensity = {w['date']: w.get('intensity') or 'strength' for w in summary['workout_log']}

    rows = []
    for d, s in score.items():
        nxt = bd._date_minus(d, -1)
        if nxt not in night_z:
            continue
        lvl = LEVELS.get(intensity.get(d), 0.0)          # 0 = no session that day
        z_today = (s - 50) / 25.0                        # roughly standardised, for readable slopes
        rows.append(([1.0, z_today, lvl, z_today * lvl], night_z[nxt]))
    if len(rows) < bd.MIN_GROUP:
        print('not enough days')
        return
    fit = ols_newey_west([r[0] for r in rows], [r[1] for r in rows])
    if fit is None:
        print('could not fit')
        return
    beta, se, r1, n = fit
    names = ['intercept', "today's score", 'session intensity', 'score × intensity']
    print(f'next night\'s composite on {n} day pairs (Newey-West, lag {LAG})')
    for nm, b, e in zip(names, beta, se):
        t = b / e if e else 0.0
        print(f'  {nm:<18}{b:+.3f}   se {e:.3f}   t {t:+5.2f}   {"significant" if abs(t) > 1.96 else "not significant"}')
    print(f'  residual lag-1 autocorrelation {r1:+.2f}')
    print('  intensity is coded easy/strength 1, moderate 2, hard 3; 0 on days with no session.')


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else HERE)
