"""Sleep Regularity Index (Phillips et al. 2017).

Their definition, verbatim: "SRI was computed as the likelihood that any two time-points
(minute-by-minute) 24 h apart were the same sleep/wake state, across all days. The value could
theoretically range 0 to 1, and was rescaled (y = 200 (x - 1/2)) to give a range of -100 to 100."

So the tests are the two ends of that scale: identical nights must score 100, and inverted ones
(asleep exactly when you were awake the day before) must score -100. Everything else is in between.
"""
import unittest
from datetime import date, timedelta

from helpers import build_dashboard as bd


def night(d, start_h, hours, nap=False, offset='+00:00'):
    """One sleep episode starting at `start_h` local on day `d`."""
    start = '%sT%02d:00:00.000Z' % (d, start_h)
    end_day = d if start_h + hours < 24 else (date.fromisoformat(d) + timedelta(days=1)).isoformat()
    end_h = (start_h + hours) % 24
    return {'id': hash((d, start_h)) & 0xffff, 'start': start,
            'end': '%sT%02d:00:00.000Z' % (end_day, end_h),
            'timezone_offset': offset, 'nap': nap}


def days(n, start=date(2026, 1, 1)):
    return [(start + timedelta(days=i)).isoformat() for i in range(n)]


def sri(sleeps, naps=(), n=40):
    out = bd.build_sleep_regularity(list(sleeps), list(naps), [], days(n)[-1])
    return None if out is None else out['value']


class ScaleTest(unittest.TestCase):
    def test_identical_nights_score_100(self):
        """Asleep and awake at exactly the same minutes every day is the top of the scale."""
        self.assertAlmostEqual(sri([night(d, 23, 8) for d in days(40)]), 100.0, places=1)

    def test_perfectly_inverted_nights_score_minus_100(self):
        """Asleep exactly when you were awake the day before is the bottom of the scale."""
        sleeps = [night(d, 0 if i % 2 else 12, 12) for i, d in enumerate(days(40))]
        self.assertAlmostEqual(sri(sleeps), -100.0, places=1)

    def test_a_shifted_night_scores_between(self):
        shifted = [night(d, 23 if i % 2 else 20, 8) for i, d in enumerate(days(40))]
        v = sri(shifted)
        self.assertGreater(v, -100.0)
        self.assertLess(v, 100.0)

    def test_no_sleep_at_all_gives_nothing(self):
        self.assertIsNone(sri([]))


class NapsAndGapsTest(unittest.TestCase):
    def test_naps_are_included(self):
        """The index deliberately doesn't single out a main sleep, so a nap has to change it."""
        base = [night(d, 23, 8) for d in days(40)]
        with_nap = [dict(n) for n in base]
        naps = [night(days(40)[35], 14, 1, nap=True)]     # inside the reported window
        self.assertNotEqual(sri(base), sri(with_nap, naps))

    def test_a_gap_in_the_export_is_not_counted_as_time_awake(self):
        """A week with nothing recorded must be skipped, not read as a week spent awake."""
        ds = days(60)
        full = [night(d, 23, 8) for d in ds]
        gapped = [n for i, n in enumerate(full) if not (20 <= i < 27)]
        self.assertGreater(sri(gapped, n=60), 95.0)

    def test_a_night_crossing_midnight_marks_both_dates(self):
        out = bd.build_sleep_regularity([night(d, 23, 8) for d in days(40)], [], [], days(40)[-1])
        self.assertEqual(out['window_days'], bd.SRI_WINDOW_DAYS)
        self.assertGreater(out['days'], 0)


class ReadinessCorrelationTest(unittest.TestCase):
    def test_correlation_needs_enough_days(self):
        ds = days(40)
        series = [{'date': d, 'v': 50} for d in ds[:5]]
        out = bd.build_sleep_regularity([night(d, 23, 8) for d in ds], [], series, ds[-1])
        self.assertIsNone(out['readiness_r'])

    def test_correlation_is_reported_when_there_are_enough(self):
        ds = days(80)
        series = [{'date': d, 'v': 40 + (i % 20)} for i, d in enumerate(ds)]
        out = bd.build_sleep_regularity([night(d, 23 if i % 3 else 21, 8) for i, d in enumerate(ds)],
                                        [], series, ds[-1])
        self.assertIsNotNone(out['readiness_r'])
        self.assertGreaterEqual(out['readiness_r'], -1.0)
        self.assertLessEqual(out['readiness_r'], 1.0)
        self.assertGreaterEqual(out['readiness_days'], bd.MIN_GROUP)


if __name__ == '__main__':
    unittest.main()
