"""Readiness model: half last night, half recent trend (7-day HRV / resting HR, 3-night sleep),
each vs a 60-day personal baseline."""
import math, random, unittest
from datetime import date, timedelta
from helpers import generate, build_dashboard as bd


def days(n, start=date(2026, 1, 1)):
    return [(start + timedelta(days=i)).isoformat() for i in range(n)]


class ReadinessTest(unittest.TestCase):
    def flat(self, n=100, hrv=80.0, rhr=55.0, sleep=85.0, jitter=True):
        ds = days(n)
        rng = random.Random(1)
        wobble = (lambda i, a: a * (1 + rng.gauss(0, 0.08))) if jitter else (lambda i, a: a)
        return ({d: wobble(i, hrv) for i, d in enumerate(ds)},
                {d: wobble(i, rhr) for i, d in enumerate(ds)},
                {d: wobble(i, sleep) for i, d in enumerate(ds)}, ds)

    def test_exactly_normal_scores_50(self):
        h, r, s, _ = self.flat(jitter=False)
        latest, series = bd.build_readiness(h, r, s)
        self.assertEqual((latest['state'], latest['score']), ('normal', 50))

    def test_typical_noise_spreads_across_states(self):
        h, r, s, _ = self.flat(n=300)
        _, series = bd.build_readiness(h, r, s)
        scores = [p['v'] for p in series]
        self.assertTrue(40 <= sum(scores) / len(scores) <= 60)

    def test_thresholds_match_half_sd_rule(self):
        h, r, s, _ = self.flat(jitter=False)
        latest, _ = bd.build_readiness(h, r, s)
        self.assertEqual(latest['thresholds'], {'above': 63, 'below': 38, 'rest': 25})

    def test_suppressed_week_is_recovery(self):
        h, r, s, ds = self.flat()
        for d in ds[-7:]:
            h[d] *= 0.6      # HRV down 40%
            r[d] *= 1.15     # resting HR up 15%
            s[d] *= 0.7      # sleep down
        latest, _ = bd.build_readiness(h, r, s)
        self.assertEqual(latest['state'], 'below')
        self.assertLess(latest['score'], 38)
        self.assertLess(latest['trend']['z']['rhr'], 0, "higher resting HR must lower readiness")

    def test_strong_week_is_peak(self):
        h, r, s, ds = self.flat()
        for d in ds[-7:]:
            h[d] *= 1.4
            r[d] *= 0.9
            s[d] = min(100, s[d] * 1.15)
        latest, _ = bd.build_readiness(h, r, s)
        self.assertEqual(latest['state'], 'above')
        self.assertGreaterEqual(latest['score'], 63)

    def test_state_and_score_agree_at_boundaries(self):
        latest, series = bd.build_readiness(*generate_by_day())
        for p in series:
            self.assertTrue(0 <= p['v'] <= 100)
        s = latest['score']
        expected = 'above' if s >= 63 else 'below' if s < 38 else 'normal'
        self.assertEqual(latest['state'], expected)

    def test_needs_a_baseline(self):
        h, r, s, _ = self.flat(n=20)
        self.assertEqual(bd.build_readiness(h, r, s), (None, []))

    def test_gap_in_wear_does_not_stretch_windows(self):
        h, r, s, ds = self.flat(n=100)
        for d in ds[25:95]:          # 70-day gap: the last 5 days have no baseline in the 60 days before
            h.pop(d); r.pop(d); s.pop(d)
        latest, series = bd.build_readiness(h, r, s)
        self.assertTrue(all(p['date'] <= ds[24] or p['date'] >= ds[95] for p in series))
        self.assertTrue(latest is None or latest['date'] <= ds[24])

    def test_constant_data_does_not_explode(self):
        h, r, s, ds = self.flat(jitter=False)
        h[ds[-1]] *= 1.01             # a 1% wobble on perfectly flat history
        latest, _ = bd.build_readiness(h, r, s)
        self.assertEqual(latest['state'], 'normal')

    def test_normal_band_is_reported_in_real_units(self):
        h, r, s, _ = self.flat()
        latest, _ = bd.build_readiness(h, r, s)
        for part in ('trend', 'last_night'):
            lo, hi = latest[part]['components']['hrv']['normal']
            self.assertTrue(60 < lo < hi < 100, (part, lo, hi))    # ms, not ln(ms)

    def test_score_is_half_last_night_half_trend(self):
        for n in range(80, 100):
            h, r, s, _ = self.flat(n=n)
            latest, _ = bd.build_readiness(h, r, s)
            mean_z = lambda part: sum(latest[part]['z'].values()) / len(latest[part]['z'])
            expected = max(0, min(100, math.floor(50 + 25 * (0.5 * mean_z('trend') + 0.5 * mean_z('last_night')) + 0.5)))
            # z values are rounded to 2 decimals in the output, so allow one point
            self.assertLessEqual(abs(latest['score'] - expected), 1)
            self.assertEqual(latest['weights'], {'last_night': 0.5, 'trend': 0.5})

    def test_great_night_after_normal_week_moves_readiness(self):
        h, r, s, ds = self.flat()
        h[ds[-1]] *= 1.6      # one very strong night
        r[ds[-1]] *= 0.9
        latest, _ = bd.build_readiness(h, r, s)
        self.assertGreater(latest['last_night']['score'], latest['trend']['score'])
        self.assertGreaterEqual(latest['score'] - latest['trend']['score'], 5,
                                "last night must count for more than 1/7 of the answer")

    def test_one_bad_night_does_not_erase_a_good_week(self):
        h, r, s, ds = self.flat()
        for d in ds[-7:-1]:
            h[d] *= 1.4; r[d] *= 0.9
        h[ds[-1]] *= 0.6; r[ds[-1]] *= 1.1
        latest, _ = bd.build_readiness(h, r, s)
        self.assertLess(latest['last_night']['score'], 38)
        self.assertGreater(latest['score'], latest['last_night']['score'])

    def test_last_night_baseline_excludes_last_night(self):
        h, r, s, ds = self.flat(jitter=False)
        h[ds[-1]] *= 2      # an outlier must be judged against the nights before it, not itself
        latest, _ = bd.build_readiness(h, r, s)
        self.assertEqual(latest['last_night']['z']['hrv'], 3.0)

    def test_summary_includes_readiness(self):
        summary = bd.build_summary(generate(120))
        self.assertIn('readiness', summary)
        self.assertIn('readiness', summary['full_series'])


class ReadinessCheckTest(unittest.TestCase):
    def test_groups_by_call_and_uses_next_morning(self):
        series = [{'date': '2026-01-01', 'v': 70}, {'date': '2026-01-02', 'v': 50},
                  {'date': '2026-01-03', 'v': 30}, {'date': '2026-01-04', 'v': 10}]
        recovery = {'2026-01-02': 80, '2026-01-03': 60, '2026-01-04': 40, '2026-01-05': 20}
        out = bd.build_readiness_check(series, recovery)
        self.assertEqual([(r['call'], r['avg_next_recovery'], r['days']) for r in out['calls']],
                         [('Push', 80, 1), ('Train', 60, 1), ('Go easy', 40, 1), ('Rest', 20, 1)])
        self.assertEqual(out['overlaps'], [])
        self.assertTrue(all(r['low_confidence'] for r in out['calls']))

    def test_band_edges_match_the_answer_bands(self):
        series = [{'date': '2026-01-01', 'v': 63}, {'date': '2026-01-02', 'v': 62},
                  {'date': '2026-01-03', 'v': 38}, {'date': '2026-01-04', 'v': 37},
                  {'date': '2026-01-05', 'v': 25}, {'date': '2026-01-06', 'v': 24}]
        recovery = {'2026-01-0%d' % i: 50 for i in range(2, 8)}
        days = [r['days'] for r in bd.build_readiness_check(series, recovery)['calls']]
        self.assertEqual(days, [1, 2, 2, 1])

    def test_flags_neighbours_that_do_not_separate(self):
        series = [{'date': '2026-01-01', 'v': 30}, {'date': '2026-01-02', 'v': 10}]
        recovery = {'2026-01-02': 44.0, '2026-01-03': 44.3}
        out = bd.build_readiness_check(series, recovery)
        self.assertEqual(out['overlaps'], [['Go easy', 'Rest']])

    def test_missing_next_morning_is_skipped(self):
        out = bd.build_readiness_check([{'date': '2026-01-01', 'v': 70}], {})
        self.assertEqual(out['days'], 0)
        self.assertIsNone(out['calls'][0]['avg_next_recovery'])


def generate_by_day():
    raw = generate(200, seed=5)
    day = bd.day
    rec = [x for x in raw['recovery'] if x['score_state'] == 'SCORED']
    sl = [x for x in raw['sleep'] if not x['nap']]
    return ({day(x['created_at']): x['score']['hrv_rmssd_milli'] for x in rec},
            {day(x['created_at']): x['score']['resting_heart_rate'] for x in rec},
            {day(x['created_at']): x['score']['sleep_performance_percentage'] for x in sl})


if __name__ == "__main__":
    unittest.main()
