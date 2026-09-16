"""Warning signs lower readiness only when confirmed, and by how far past the line they are."""
import random, unittest
from datetime import date, timedelta
from helpers import build_dashboard as bd


def history(n=40, seed=3):
    rng = random.Random(seed)
    ds = [(date(2026, 1, 1) + timedelta(days=i)).isoformat() for i in range(n)]
    hrv = {d: 80 + rng.gauss(0, 6) for d in ds}
    rhr = {d: 55 + rng.gauss(0, 1.5) for d in ds}
    rr = {d: 15 + rng.gauss(0, 0.3) for d in ds}
    return ds, hrv, rhr, rr


class WarningTest(unittest.TestCase):
    def test_quiet_nights_no_warning_signals(self):
        ds, h, r, b = history()
        for d in ds[-3:]:
            b[d] = 15.0; h[d] = 80.0; r[d] = 55.0
        w = bd.build_warning(h, r, b)
        self.assertFalse(w['confirmed'])
        self.assertEqual(w['signals'], [])

    def test_single_borderline_night_is_only_watched(self):
        ds, h, r, b = history()
        for d in ds[-3:-1]:
            b[d] = 15.0
        b[ds[-1]] = 15.6                       # ~2 SD, one night only
        w = bd.build_warning(h, r, b)
        self.assertTrue(w['signals'])
        self.assertFalse(w['confirmed'])
        self.assertIsNone(w['cap'])

    def test_repeated_signal_is_confirmed_and_mild(self):
        ds, h, r, b = history()
        b[ds[-3]] = 15.0
        b[ds[-2]] = b[ds[-1]] = 15.5           # just past the line on 2 of 3 nights
        w = bd.build_warning(h, r, b)
        self.assertTrue(w['confirmed'])
        self.assertEqual(w['reason'], 'repeated')
        self.assertTrue(24 <= w['cap'] <= 37)

    def test_far_out_of_range_caps_at_rest(self):
        ds, h, r, b = history()
        b[ds[-2]] = b[ds[-1]] = 17.5            # many SD above normal
        w = bd.build_warning(h, r, b)
        self.assertEqual(w['cap'], 24)

    def test_two_signals_same_night_is_confirmed(self):
        ds, h, r, b = history()
        h[ds[-1]] = 55.0                        # HRV well below
        r[ds[-1]] = 60.0                        # resting HR well above
        w = bd.build_warning(h, r, b)
        self.assertTrue(w['confirmed'])
        self.assertEqual(w['reason'], 'multiple')

    def test_back_to_normal_stops_counting(self):
        ds, h, r, b = history()
        b[ds[-3]] = b[ds[-2]] = 17.0            # two bad nights…
        b[ds[-1]] = 15.0                        # …but last night was normal
        w = bd.build_warning(h, r, b)
        self.assertFalse(w['confirmed'])

    def test_needs_30_nights_of_history(self):
        ds, h, r, b = history(n=20)
        self.assertIsNone(bd.build_warning(h, r, b))


if __name__ == "__main__":
    unittest.main()
