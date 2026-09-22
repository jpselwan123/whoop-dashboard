"""Readiness: 7-day HRV, resting HR and sleep, each a standard score vs the 7-day averages of the
previous 4 weeks, averaged, then read as a percentile of the person's own earlier scores (50 = a median
day). 69+ Train hard, 31–68 Train as planned, 7–30 Go easy, under 7 Rest; Rest on a breathing-rate
Go easy after 2 hard days in a row."""
import math, random, unittest
from datetime import date, timedelta
from statistics import mean
from helpers import generate, build_dashboard as bd


def days(n, start=date(2026, 1, 5)):          # a Monday
    return [(start + timedelta(days=i)).isoformat() for i in range(n)]


# day-to-day pattern plus a slow drift, like real data
LN_PATTERN = (0.0, 0.05, -0.05, 0.1, -0.1, 0.03, -0.03)
HR_PATTERN = (0.0, 1.0, -1.0, 2.0, -2.0, 0.5, -0.5)


def steady(n=112, hrv=80.0, rhr=55.0, rr=15.0, flat_last=1):
    """Enough history for an answer (4 baseline weeks, then 4 weeks of scored days) and data that
    moves the way real data does: a level for each week and day-to-day noise on top. Without both,
    the score's own spread is near zero and one ordinary night reads as extreme.

    The last week sits exactly at the middle of its 4 baseline weeks and its last day carries no
    noise, so "nothing unusual happened" is the default the tests vary from."""
    ds = days(n)
    weeks, last_week = (n + 6) // 7, (n - 1) // 7
    rnd = random.Random(23)
    level = [rnd.gauss(0, 0.06) for _ in range(weeks)]
    if last_week >= 4:
        level[last_week] = mean(level[last_week - 4:last_week])
    noise = []                              # mean-zero within each week, so weekly levels stay put
    for _ in range(weeks):
        wk = [(rnd.gauss(0, 0.09), rnd.gauss(0, 1.8)) for _ in range(7)]
        mh, mr = mean(x[0] for x in wk), mean(x[1] for x in wk)
        noise += [(a - mh, b_ - mr) for a, b_ in wk]
    for i in range(n - flat_last, n):       # utterly ordinary nights at the end
        noise[i] = (0.0, 0.0)
    return ({d: hrv * math.exp(LN_PATTERN[i % 7] + level[i // 7] + noise[i][0]) for i, d in enumerate(ds)},
            {d: rhr + HR_PATTERN[i % 7] - 12 * level[i // 7] + noise[i][1] for i, d in enumerate(ds)},
            {d: rr + HR_PATTERN[i % 7] * 0.1 for i, d in enumerate(ds)}, ds)


class ProtocolTest(unittest.TestCase):
    def test_normal_week_means_train_as_planned(self):
        """Inside the normal band the trials prescribed the planned session, not a hard one."""
        h, r, b, _ = steady()
        latest, _ = bd.build_readiness(h, r, b, set())
        self.assertEqual((latest['answer'], latest['reasons']), ('moderate', []))
        self.assertEqual(latest['hrv']['state'], 'within')
        self.assertTrue(31 <= latest['score'] < 69)

    def test_hrv_drop_over_the_week_means_easy(self):
        h, r, b, ds = steady()
        for d in ds[-7:]:
            h[d] *= 0.7
        latest, _ = bd.build_readiness(h, r, b, set())
        self.assertIn(latest['answer'], ('easy', 'rest'))
        self.assertEqual(latest['reasons'], ['low'])
        self.assertLess(latest['score'], 45)
        self.assertEqual(latest['hrv']['state'], 'below')

    def test_hrv_above_the_band_is_the_same_answer_as_inside_it(self):
        """No cited trial prescribes a harder session for being above the range (Kiviniemi 2007:
        "an increase or no change" both get high intensity), so there is no fourth answer."""
        h, r, b, ds = steady()
        for d in ds[-8:-1]:
            h[d] *= 1.4
        latest, _ = bd.build_readiness(h, r, b, set())
        self.assertEqual((latest['answer'], latest['hrv']['state']), ('moderate', 'above'))

    def test_resting_hr_rise_means_easy(self):
        h, r, b, ds = steady()
        for d in ds[-7:]:
            r[d] += 8
        latest, _ = bd.build_readiness(h, r, b, set())
        self.assertEqual(latest['rhr']['state'], 'above')
        self.assertLess(latest['score'], 50, "higher resting HR must lower readiness")

    def test_a_slightly_low_night_is_diluted_by_the_7_day_average(self):
        h, r, b, ds = steady()
        h[ds[-1]] *= 0.93
        latest, _ = bd.build_readiness(h, r, b, set())
        self.assertEqual(latest['answer'], 'moderate')

    def test_normal_range_is_fixed_within_a_week(self):
        h, r, b, ds = steady(n=70)
        _, _ = bd.build_readiness(h, r, b, set())
        ranges = set()
        monday = date.fromisoformat(ds[-1]) - timedelta(days=date.fromisoformat(ds[-1]).weekday())
        for d in ds:
            if date.fromisoformat(d) >= monday:
                sub = {k: v for k, v in h.items() if k <= d}
                latest, _ = bd.build_readiness(sub, {k: v for k, v in r.items() if k <= d}, b, set())
                ranges.add(tuple(latest['hrv']['normal']))
        self.assertEqual(len(ranges), 1)

    def test_range_is_built_from_the_7_day_averages_of_the_4_weeks_before_this_week(self):
        h, r, b, ds = steady()
        for i, d in enumerate(ds):            # vary the weekly level so the 7-day averages have a spread
            h[d] *= math.exp(0.02 * (i // 7 % 3))
        d = ds[-1]
        monday = date.fromisoformat(d) - timedelta(days=date.fromisoformat(d).weekday())
        ln = {k: math.log(v) for k, v in h.items()}
        def roll(day):
            vals = [v for k, v in ln.items() if day - timedelta(days=6) <= date.fromisoformat(k) <= day]
            return sum(vals) / len(vals)
        base = [roll(monday - timedelta(days=k)) for k in range(1, 29)]
        m = sum(base) / len(base)
        sd = math.sqrt(sum((x - m) ** 2 for x in base) / (len(base) - 1))   # sample SD
        latest, _ = bd.build_readiness(h, r, b, set())
        self.assertEqual(latest['hrv']['normal'], [round(math.exp(m - 0.5 * sd)), round(math.exp(m + 0.5 * sd))])

    def test_needs_3_readings_in_the_week(self):
        h, r, b, ds = steady()
        for d in ds[-7:-2]:
            h.pop(d)
        _, series = bd.build_readiness(h, r, b, set())
        self.assertNotIn(ds[-1], [p['date'] for p in series])     # only 2 readings in the last 7 days

    def test_new_account_has_no_answer(self):
        h, r, b, _ = steady(n=28)          # starts on a Monday: 4 full weeks, answer from day 29
        self.assertEqual(bd.build_readiness(h, r, b, set()), (None, []))
        # 4 weeks to learn each measure's normal, then 4 weeks of scored days for the score's spread
        self.assertEqual(bd.readiness_progress(h), {'days': 28, 'needed': 57})
        h, r, b, _ = steady(n=56)
        self.assertEqual(bd.build_readiness(h, r, b, set())[0], None)
        h, r, b, _ = steady(n=57)
        self.assertIsNotNone(bd.build_readiness(h, r, b, set())[0])

    def test_each_baseline_week_needs_3_readings(self):
        h, r, b, ds = steady()
        monday = date.fromisoformat(ds[-1]) - timedelta(days=date.fromisoformat(ds[-1]).weekday())
        for d in list(h):
            if monday - timedelta(days=14) <= date.fromisoformat(d) < monday - timedelta(days=9):
                h.pop(d)          # leaves 2 readings in that baseline week
        latest, series = bd.build_readiness(h, r, b, set())
        self.assertNotIn(ds[-1], [p['date'] for p in series])

    def test_two_hard_days_in_a_row_means_easy(self):
        h, r, b, ds = steady()
        latest, _ = bd.build_readiness(h, r, b, {ds[-2], ds[-3]})
        self.assertEqual((latest['answer'], latest['reasons']), ('easy', ['streak']))
        latest, _ = bd.build_readiness(h, r, b, {ds[-2], ds[-4]})
        self.assertEqual(latest['answer'], 'moderate')

    def test_rest_needs_a_run_of_low_days_not_one(self):
        """Below the band the trials prescribe low intensity OR rest; Kiviniemi acted on a
        "decreasing trend for 2 days", so rest waits for the second day in a row."""
        h, r, b, ds = steady(flat_last=8)
        for d in ds[-8:]:                       # a sustained dip, mild enough to stay in the band
            h[d] *= 0.93
        _, series = bd.build_readiness(h, r, b, set())
        lines, runs = None, {}
        for p in series:
            lines = lines or p
            prev = (date.fromisoformat(p['date']) - timedelta(days=1)).isoformat()
            runs[p['date']] = (runs.get(prev, 0) + 1) if p['v'] < 31 else 0
        by_day = {p['date']: p for p in series}
        rests = [d for d, p in by_day.items() if p['answer'] == 'rest']
        self.assertTrue(rests, 'a sustained dip must produce rest days')
        for d in rests:                         # every rest is a big drop or the 3rd low day
            self.assertTrue(by_day[d]['v'] < 7 or runs[d] >= 2, (d, by_day[d]['v'], runs[d]))
        for d, p in by_day.items():             # a single low day on its own stays easy
            if 7 <= p['v'] < 31 and runs[d] < 2:
                self.assertEqual(p['answer'], 'easy', (d, p['v'], runs[d]))

    def test_never_more_than_two_rest_days_in_a_row(self):
        """A long dip must not turn into an open-ended rest block (detraining)."""
        h, r, b, ds = steady(flat_last=8)
        for d in ds[-8:]:
            h[d] *= 0.93
        _, series = bd.build_readiness(h, r, b, set())
        answers = [p['answer'] for p in series]
        self.assertIn('rest', answers[-8:])
        for i in range(2, len(answers)):
            self.assertNotEqual(answers[i - 2:i + 1], ['rest'] * 3, answers[-10:])

    def test_breathing_rate_is_reported_but_never_changes_the_plan(self):
        """Natarajan 2021 gives no numeric rise threshold, so none is applied — the rate is shown."""
        h, r, b, ds = steady()
        usual = sum(b[d] for d in ds if 30 <= (date.fromisoformat(ds[-1]) - date.fromisoformat(d)).days <= 90)
        usual /= sum(1 for d in ds if 30 <= (date.fromisoformat(ds[-1]) - date.fromisoformat(d)).days <= 90)
        calm, _ = bd.build_readiness(h, r, b, set())
        b[ds[-1]] = usual + 12                      # a rise far beyond anything real
        loud, _ = bd.build_readiness(h, r, b, set())
        self.assertEqual(loud['answer'], calm['answer'])
        self.assertEqual(loud['reasons'], calm['reasons'])
        self.assertAlmostEqual(loud['breathing']['above_usual'], 12, delta=0.2)
        self.assertNotIn('flagged', loud['breathing'])

    def test_breathing_needs_30_nights_of_history(self):
        h, r, b, _ = steady(n=58)          # only 29 nights sit 30–90 days back
        latest, _ = bd.build_readiness(h, r, b, set())
        self.assertIsNone(latest['breathing'])

    def test_values_are_reported_in_real_units(self):
        h, r, b, _ = steady()
        latest, _ = bd.build_readiness(h, r, b, set())
        lo, hi = latest['hrv']['normal']
        self.assertTrue(60 < lo < hi < 110 and 60 < latest['hrv']['value'] < 110)

    def test_summary_includes_readiness(self):
        summary = bd.build_summary(generate(120))
        for key in ('readiness', 'readiness_progress', 'plan_check', 'last_night', 'sleep_nights'):
            self.assertIn(key, summary)
        self.assertIn(summary['readiness']['answer'], ('moderate', 'easy', 'rest'))


def _raw_composites(h, r, sleep, ds):
    """Every day's average standard score, recomputed independently of build_readiness."""
    ln = {k: math.log(v) for k, v in h.items()}
    out = []
    for d in ds:
        ms = [bd.judge_marker(ln, d, 'below'), bd.judge_marker(r, d, 'above'), bd.judge_marker(sleep, d, 'below')]
        if ms[0] is None or ms[0]['z'] is None:
            continue
        ms += [bd.judge_last_night(src, d, w) for src, w in ((ln, 'below'), (r, 'above'), (sleep, 'below'))]
        zs = [m['z'] for m in ms if m and m.get('z') is not None]
        if zs:
            out.append((d, sum(zs) / len(zs)))
    return out


class ScoreTest(unittest.TestCase):
    def test_score_is_the_percentile_of_the_averaged_standard_scores(self):
        h, r, b, ds = steady()
        last_week = (len(ds) - 1) // 7
        sleep = {d: 7.5 + LN_PATTERN[i % 7] + (0 if i // 7 == last_week else (0.3 if (i // 7) % 2 else -0.3))
                 for i, d in enumerate(ds)}
        latest, _ = bd.build_readiness(h, r, b, set(), sleep)
        monday = date.fromisoformat(ds[-1]) - timedelta(days=date.fromisoformat(ds[-1]).weekday())
        def z(src, f, flip):
            def roll(day):                      # the 7 days BEFORE the day, not including it
                v = [f(x) for k, x in src.items()
                     if day - timedelta(days=7) <= date.fromisoformat(k) <= day - timedelta(days=1)]
                return sum(v) / len(v)
            base = [roll(monday - timedelta(days=k)) for k in range(1, 29)]
            m = sum(base) / len(base)
            sd = math.sqrt(sum((x - m) ** 2 for x in base) / (len(base) - 1))
            if sd == 0:
                return None
            return (roll(date.fromisoformat(ds[-1])) - m) / sd * (-1 if flip else 1)
        def z_night(src, f, flip):
            base = [f(v) for k, v in src.items() if monday - timedelta(days=28) <= date.fromisoformat(k) < monday]
            m = sum(base) / len(base)
            sd = math.sqrt(sum((x - m) ** 2 for x in base) / (len(base) - 1))
            return None if sd == 0 else (f(src[ds[-1]]) - m) / sd * (-1 if flip else 1)
        zs = [x for x in (z(h, math.log, False), z(r, lambda v: v, True), z(sleep, lambda v: v, False),
                          z_night(h, math.log, False), z_night(r, lambda v: v, True), z_night(sleep, lambda v: v, False))
              if x is not None]
        self.assertEqual(len(zs), 6)
        # the average standard score, standardised against every earlier day's average and read off
        # the normal curve — recomputed here from the series the same function returned
        raw = {p['date']: p for p in []}
        _, series = bd.build_readiness(h, r, b, set(), sleep)
        self.assertEqual(series[-1]['v'], latest['score'])
        history = [x for x in _raw_composites(h, r, sleep, ds) if x[0] < ds[-1]]
        prev = [v for _, v in history]
        m = sum(prev) / len(prev)
        sd = math.sqrt(sum((x - m) ** 2 for x in prev) / (len(prev) - 1))
        want = round(bd.normal_percentile(((sum(zs) / len(zs)) - m) / sd))
        self.assertEqual(latest['score'], max(1, min(99, want)))
        self.assertEqual(latest['last_night']['measures'], 3)

    def test_answer_lines_on_the_score(self):
        h, r, b, ds = steady()
        for factor in (1.4, 1.0, 0.93, 0.6):
            hh = dict(h)
            for d in ds[-7:]:
                hh[d] = h[d] * factor
            latest, _ = bd.build_readiness(hh, r, b, set())
            s = latest['score']
            want = 'moderate' if s >= 31 else 'easy' if s >= 7 else 'rest'
            self.assertEqual(latest['answer'], want, (factor, s))
        self.assertEqual(latest['lines'], {'train': 31, 'rest': 7})

    def test_the_bands_are_the_swc_and_rest_lines(self):
        """Band edges are the trials' SD cut-offs read as percentiles: -0.5 SD = 31, -1.5 SD = 7.
        There is no line above the band — no trial prescribes a harder session for being above it."""
        h, r, b, _ = steady()
        latest, _ = bd.build_readiness(h, r, b, set())
        L = latest['lines']
        self.assertEqual(sorted(L), ['rest', 'train'])
        self.assertEqual([L['train'], L['rest']], [31, 7])
        for z, want in ((-0.5, 31), (-1.5, 7), (0, 50)):
            self.assertEqual(round(bd.normal_percentile(z)), want)

    def test_the_score_really_is_a_percentile(self):
        """A percentile only means something if the days land where it says: over a long run the
        bands must cut off about the share of days their SD lines intend (31% / 38% / 24% / 7%)."""
        h, r, b, _ = steady(n=560)
        _, series = bd.build_readiness(h, r, b, set())
        self.assertGreater(len(series), 400)
        share = lambda f: 100 * sum(1 for p in series if f(p['v'])) / len(series)
        self.assertAlmostEqual(share(lambda v: v >= 31), 69.1, delta=8)
        self.assertAlmostEqual(share(lambda v: 7 <= v < 31), 24.2, delta=6)
        self.assertAlmostEqual(share(lambda v: v < 7), 6.7, delta=4)

    def test_shorter_sleep_lowers_the_score(self):
        h, r, b, ds = steady()
        sleep = {d: 7.5 + (0.3 if (i // 7) % 2 else -0.3) for i, d in enumerate(ds)}
        normal, _ = bd.build_readiness(h, r, b, set(), sleep)
        for d in ds[-7:]:
            sleep[d] = 5.0
        short, _ = bd.build_readiness(h, r, b, set(), sleep)
        self.assertEqual(short['sleep']['state'], 'below')
        self.assertLess(short['score'], normal['score'])

    def test_series_carries_score_and_answer(self):
        h, r, b, _ = steady()
        _, series = bd.build_readiness(h, r, b, set())
        self.assertTrue(all(0 <= p['v'] <= 100 and p['answer'] in ('moderate', 'easy', 'rest') for p in series))


class StatisticsTest(unittest.TestCase):
    def test_incomplete_beta_matches_known_value(self):
        # two-sided p for t = 2.0 with 10 degrees of freedom is 0.0734
        self.assertAlmostEqual(bd._betainc(5, 0.5, 10 / 14), 0.07339, places=4)

    def test_welch_detects_a_real_gap_and_not_noise(self):
        rng = random.Random(3)
        a = [rng.gauss(55, 15) for _ in range(200)]
        self.assertLess(bd.welch_p(a, [rng.gauss(45, 15) for _ in range(200)]), 0.05)
        self.assertGreater(bd.welch_p(a, [rng.gauss(55, 15) for _ in range(200)]), 0.05)

    def test_plan_check_needs_30_days_on_both_sides(self):
        """Few override days is the normal case — show the counts, claim nothing."""
        days = [(date(2026, 1, 1) + timedelta(days=i)).isoformat() for i in range(60)]
        series = [{'date': d, 'answer': 'easy' if i < 10 else 'moderate'} for i, d in enumerate(days)]
        rec = {(date(2026, 1, 2) + timedelta(days=i)).isoformat(): 50 for i in range(60)}
        out = bd.build_plan_check(series, rec, set(days[:5]))     # 5 override days only
        self.assertEqual(out['harder']['days'], 5)
        self.assertFalse(out['enough'])
        self.assertFalse(out['significant'])

    def test_plan_check_compares_what_you_did_not_what_the_score_said(self):
        """Overriding = a moderate/high session on a Go easy or Rest day; everything else followed."""
        days = [(date(2026, 1, 1) + timedelta(days=i)).isoformat() for i in range(200)]
        series = [{'date': d, 'answer': 'easy' if i % 2 else 'moderate'} for i, d in enumerate(days)]
        hard = {d for i, d in enumerate(days) if i % 2}           # every Go easy day was overridden
        rec = {(date(2026, 1, 2) + timedelta(days=i)).isoformat(): (40 if i % 2 else 60) + (i % 5)
               for i in range(200)}
        out = bd.build_plan_check(series, rec, hard)
        self.assertEqual(out['followed']['days'] + out['harder']['days'], out['days'])
        self.assertEqual(out['harder']['days'], 100)
        self.assertTrue(out['enough'] and out['significant'])
        self.assertGreater(out['delta'], 0)
        self.assertAlmostEqual(out['followed']['avg_next_recovery'], 62.0, delta=0.6)

    def test_plan_check_ignores_hard_days_the_plan_allowed(self):
        days = [(date(2026, 1, 1) + timedelta(days=i)).isoformat() for i in range(60)]
        series = [{'date': d, 'answer': 'moderate'} for d in days]
        rec = {(date(2026, 1, 2) + timedelta(days=i)).isoformat(): 50 for i in range(60)}
        out = bd.build_plan_check(series, rec, set(days))          # trained hard every day, as allowed
        self.assertEqual(out['harder']['days'], 0)
        self.assertEqual(out['followed']['days'], out['days'])


if __name__ == '__main__':
    unittest.main()
