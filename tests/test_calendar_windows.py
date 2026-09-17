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

    def test_anomalies_do_not_use_nights_from_before_a_gap(self):
        before = days(date(2025, 1, 1), 40)
        after = days(date(2025, 10, 1), 25)
        hrv = {d: 60.0 + (i % 5) for i, d in enumerate(before + after)}
        rhr = {d: 55.0 + (i % 3) for i, d in enumerate(before + after)}
        rr = {d: 15.0 + (i % 4) * 0.1 for i, d in enumerate(before + after)}
        flags = bd.build_anomalies(hrv, rhr, rr)
        judged_after_gap = [f for f in flags if f['date'] >= after[0] and f['date'] < after[21]]
        self.assertEqual(judged_after_gap, [])
        # and a night 22+ days after the gap is judged against post-gap nights only
        hrv[after[22]] = 20.0
        self.assertIn(after[22], [f['date'] for f in bd.build_anomalies(hrv, rhr, rr)])

    def test_monotony_weeks_start_on_monday(self):
        strain = {d: 8.0 + (i % 3) for i, d in enumerate(days(date(2026, 3, 4), 30))}   # starts on a Wednesday
        for w in bd.build_monotony(strain):
            self.assertEqual(date.fromisoformat(w['start']).weekday(), 0)


class ConsistencyTest(unittest.TestCase):
    def setUp(self):
        self.raw = generate(120)
        self.summary = bd.build_summary(self.raw)

    def test_zone_chart_uses_the_same_split_as_session_intensity(self):
        wo = [w for w in self.raw['workouts'] if w.get('score')]
        easy = sum(sum((w['score']['zone_durations'].get(k) or 0) for k in
                       ('zone_zero_milli', 'zone_one_milli', 'zone_two_milli')) for w in wo)
        total = sum(sum(v or 0 for v in w['score']['zone_durations'].values()) for w in wo)
        self.assertAlmostEqual(self.summary['zone_distribution']['all_time']['easy_pct'], round(100 * easy / total, 1))

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
