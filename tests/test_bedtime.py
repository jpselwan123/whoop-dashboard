"""Tonight's bedtime target: usual wake time minus WHOOP's OWN sleep need.

The need is WHOOP's figure straight from the API; the only arithmetic here is the subtraction, and the
spread of wake times is reported rather than judged against a cut-off of our own.
"""
import unittest
from datetime import date, timedelta

from helpers import build_dashboard as bd


def days(n, start=date(2026, 1, 1)):
    return [(start + timedelta(days=i)).isoformat() for i in range(n)]


class BedtimeTargetTest(unittest.TestCase):
    """Usual wake time minus WHOOP's OWN sleep need. The only arithmetic here is the subtraction."""

    def nights(self, n=30, wake_h=7, need_h=8.0, jitter=0.0):
        out = []
        for i, d in enumerate(days(n)):
            w = wake_h + (jitter if i % 2 else -jitter)
            out.append({
                'id': i, 'nap': False, 'timezone_offset': '+00:00',
                'start': '%sT22:00:00.000Z' % d,
                'end': '%sT%02d:%02d:00.000Z' % (d, int(w), round((w % 1) * 60)),
                'score': {'sleep_needed': {'baseline_milli': int(need_h * 3600000),
                                           'need_from_sleep_debt_milli': 0,
                                           'need_from_recent_strain_milli': 0,
                                           'need_from_recent_nap_milli': 0}},
            })
        return out

    def test_it_counts_back_from_the_usual_wake_time(self):
        out = bd.build_bedtime_target(self.nights(wake_h=7, need_h=8.0), days(30)[-1])
        self.assertEqual(out['wake'], '07:00')
        self.assertEqual(out['asleep_by'], '23:00')        # 07:00 minus 8h, wrapping past midnight
        self.assertAlmostEqual(out['need_h'], 8.0, places=2)

    def test_the_need_is_whoops_own_four_parts(self):
        n = self.nights()
        n[-1]['score']['sleep_needed'].update({'need_from_sleep_debt_milli': 1800000,      # +0.5 h
                                               'need_from_recent_strain_milli': 900000})   # +0.25 h
        out = bd.build_bedtime_target(n, days(30)[-1])
        self.assertAlmostEqual(out['need_h'], 8.75, places=2)
        self.assertAlmostEqual(out['parts_h']['sleep_debt'], 0.5, places=2)
        self.assertEqual(out['asleep_by'], '22:15')

    def test_a_steady_wake_time_reports_a_small_spread(self):
        out = bd.build_bedtime_target(self.nights(jitter=0.0), days(30)[-1])
        self.assertEqual(out['wake_spread_h'], 0.0)

    def test_a_variable_wake_time_is_reported_not_hidden(self):
        """No cut-off is invented — the spread is stated so the reader can judge it."""
        out = bd.build_bedtime_target(self.nights(jitter=2.0), days(30)[-1])
        self.assertGreater(out['wake_spread_h'], 1.0)
        self.assertEqual(out['nights'], 30)

    def test_too_few_nights_gives_nothing(self):
        self.assertIsNone(bd.build_bedtime_target(self.nights(n=2), days(2)[-1]))


if __name__ == '__main__':
    unittest.main()
