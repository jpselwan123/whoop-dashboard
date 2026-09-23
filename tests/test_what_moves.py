"""What moves the next morning's readiness — and, far more often, what doesn't.

The panel exists to say "nothing here survived", so the tests that matter are the ones proving it
stays quiet: noise must not get through, and a predictor must fail if it misses any single gate.
The gates are the same three the training-cost adjustment has to pass.
"""
import random, unittest
from datetime import date, timedelta

from helpers import build_dashboard as bd


def days(n, start=date(2026, 1, 5)):
    return [(start + timedelta(days=i)).isoformat() for i in range(n)]


def series(values, ds):
    """A readiness series carrying both scales: the standardised z and the percentile shown."""
    return [{'date': d, 'z': z, 'v': max(1, min(99, round(bd.normal_percentile(z)))), 'answer': 'moderate'}
            for d, z in zip(ds, values)]


def run(feature, z_values, ds, key='strain'):
    return bd.build_what_moves(series(z_values, ds), {key: feature}, ds[-1])


class NoiseStaysQuietTest(unittest.TestCase):
    def test_pure_noise_shows_nothing(self):
        rng = random.Random(11)
        ds = days(400)
        z = [rng.gauss(0, 1) for _ in ds]
        feature = {d: rng.gauss(10, 3) for d in ds}
        out = run(feature, z, ds)
        self.assertEqual(out['shown'], [])
        self.assertEqual(out['candidates'], len(bd.WHAT_MOVES))

    def test_a_predictor_with_no_days_shows_nothing(self):
        ds = days(120)
        out = run({}, [0.0] * len(ds), ds)
        self.assertEqual(out['shown'], [])


class GatesTest(unittest.TestCase):
    """A strong, clean signal passes; break one gate at a time and it must drop out."""

    def strong(self, seed=5, n=400, noise=0.25):
        rng = random.Random(seed)
        ds = days(n)
        feature = {d: rng.uniform(0, 20) for d in ds}
        z = [0.0]
        for i in range(1, n):
            # tomorrow's score falls evenly with today's feature, plus noise
            z.append(-0.08 * (feature[ds[i - 1]] - 10) + rng.gauss(0, noise))
        return feature, z, ds

    def test_a_clean_even_signal_passes_and_is_quoted_in_points(self):
        feature, z, ds = self.strong()
        shown = run(feature, z, ds)['shown']
        self.assertEqual(len(shown), 1)
        row = shown[0]
        self.assertEqual(row['key'], 'strain')
        self.assertLess(row['points'], 0)          # more of it, worse next morning
        self.assertEqual(row['days'], len(ds) - 1)
        self.assertEqual(len(row['terciles']), 3)
        self.assertGreaterEqual(row['terciles'][0], row['terciles'][2])
        self.assertIsNotNone(row['holdout_margin'])

    def test_an_uneven_signal_fails_the_tercile_gate(self):
        """All the effect in one jump at the top — significant, but not an even relationship."""
        rng = random.Random(7)
        ds = days(400)
        feature = {d: rng.uniform(0, 20) for d in ds}
        z = [0.0]
        for i in range(1, len(ds)):
            x = feature[ds[i - 1]]
            z.append((-2.0 if x > 18 else 0.0) + rng.gauss(0, 0.25))
        self.assertEqual(run(feature, z, ds)['shown'], [])

    def test_too_few_days_shows_nothing(self):
        feature, z, ds = self.strong(n=bd.MIN_GROUP + 2)
        self.assertEqual(run(feature, z, ds)['shown'], [])

    def test_an_effect_too_small_to_be_a_whole_point_is_not_shown(self):
        """A real but sub-point effect would round to '+0 points', which says nothing."""
        rng = random.Random(3)
        ds = days(500)
        feature = {d: rng.uniform(0, 20) for d in ds}
        z = [0.0]
        for i in range(1, len(ds)):
            z.append(-0.0005 * (feature[ds[i - 1]] - 10) + rng.gauss(0, 0.2))
        for row in run(feature, z, ds)['shown']:
            self.assertNotEqual(row['points'], 0)


class FeaturesTest(unittest.TestCase):
    def test_bedtime_is_signed_hours_from_the_usual_and_wraps_past_midnight(self):
        mk = lambda d, t, off='+02:00': {'start': '%sT%s:00.000Z' % (d, t), 'end': '%sT08:00:00.000Z' % d,
                                         'timezone_offset': off, 'id': 1, 'nap': False}
        sleeps = [mk('2026-01-0%d' % i, '20:00') for i in range(1, 6)]       # 22:00 local each night
        bd.DAY = bd.DayKey([], [])
        feats = bd.build_what_moves_features(sleeps, [], [], {}, set())
        vals = sorted(feats['bedtime_offset_h'].values())
        self.assertAlmostEqual(vals[0], 0.0, places=6)                      # all the same night
        late = bd.build_what_moves_features(sleeps + [mk('2026-01-06', '22:30')], [], [], {}, set())
        # 00:30 local is a LATE night, not an early morning: it must be positive, not about -23
        self.assertGreater(max(late['bedtime_offset_h'].values()), 0)

    def test_days_since_rest_counts_calendar_days(self):
        strain = {d: 10.0 for d in days(6)}
        rest = {days(6)[0]}
        feats = bd.build_what_moves_features([], [], [], strain, rest)
        since = feats['days_since_rest']
        self.assertEqual(since[days(6)[0]], 0.0)
        self.assertEqual(since[days(6)[3]], 3.0)

    def test_nap_is_a_yes_or_no(self):
        strain = {d: 10.0 for d in days(4)}
        bd.DAY = bd.DayKey([], [])
        nap = {'start': '2026-01-05T12:00:00.000Z', 'end': '2026-01-05T13:00:00.000Z',
               'timezone_offset': '+00:00', 'id': 2, 'nap': True}
        feats = bd.build_what_moves_features([], [nap], [], strain, set())
        self.assertEqual(set(feats['nap'].values()), {0.0, 1.0})


if __name__ == '__main__':
    unittest.main()
