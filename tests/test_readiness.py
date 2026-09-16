"""Readiness model: 7-day HRV / resting HR and 3-night sleep vs a 60-day personal baseline."""
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
        self.assertEqual(latest['thresholds'], {'above': 63, 'below': 38})

    def test_suppressed_week_is_recovery(self):
        h, r, s, ds = self.flat()
        for d in ds[-7:]:
            h[d] *= 0.6      # HRV down 40%
            r[d] *= 1.15     # resting HR up 15%
            s[d] *= 0.7      # sleep down
        latest, _ = bd.build_readiness(h, r, s)
        self.assertEqual(latest['state'], 'below')
        self.assertLess(latest['score'], 38)
        self.assertLess(latest['z']['rhr'], 0, "higher resting HR must lower readiness")

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
        lo, hi = latest['components']['hrv']['normal']
        self.assertTrue(60 < lo < hi < 100, (lo, hi))    # ms, not ln(ms)

    def test_summary_includes_readiness(self):
        summary = bd.build_summary(generate(120))
        self.assertIn('readiness', summary)
        self.assertIn('readiness', summary['full_series'])


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
