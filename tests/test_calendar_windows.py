"""Windows are calendar days, not record counts — a gap in wear must never pull in old data."""
import unittest
from datetime import date, timedelta
from helpers import generate, build_dashboard as bd


def days(start, n):
    return [(start + timedelta(days=i)).isoformat() for i in range(n)]


class CalendarWindowTest(unittest.TestCase):
    def test_acwr_skips_the_days_right_after_a_long_gap(self):
        before = days(date(2025, 1, 1), 60)
        after = days(date(2025, 10, 1), 40)
        strain = {d: 10.0 for d in before}
        strain.update({d: 15.0 for d in after})
        out = {p['date']: p['v'] for p in bd.build_acwr(strain)}
        # 21 days of data are needed inside the 28-day window: no ratio in the first 20 days back
        self.assertNotIn(after[19], out)
        self.assertIn(after[27], out)
        self.assertEqual(out[after[27]], 1.0)       # only post-gap days in both windows

    def test_acwr_needs_28_days_of_history(self):
        strain = {d: 10.0 for d in days(date(2025, 1, 1), 40)}
        out = bd.build_acwr(strain)
        self.assertEqual(out[0]['date'], (date(2025, 1, 1) + timedelta(days=27)).isoformat())

    def setUp(self):
        self.raw = generate(120)
        self.summary = bd.build_summary(self.raw)

    def test_longest_sleep_is_time_asleep(self):
        sl = [s for s in self.raw['sleep'] if not s['nap']]
        best = max(bd.asleep_ms(s) for s in sl) / 3600000
        self.assertAlmostEqual(self.summary['records']['longest_sleep_h']['v'], best, places=2)

    def test_weekly_charts_cover_eight_consecutive_weeks(self):
        for rows in (self.summary['sleep_composition'], self.summary['zone_distribution']['weekly']):
            starts = [date.fromisoformat(r['start']) for r in rows]
            self.assertEqual(len(starts), 8)
            self.assertTrue(all((b - a).days == 7 for a, b in zip(starts, starts[1:])))


if __name__ == '__main__':
    unittest.main()
