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


class DayKeyTest(unittest.TestCase):
    """WHOOP's day runs sleep to sleep, so the UTC day of `created_at` can put two cycles on one
    date — a night begun just after local midnight and the next begun the same evening."""

    def cycles(self):
        # +02:00: a cycle starting 00:00 local on the 28th, and the next starting 20:31 local
        a = {'id': 1, 'start': '2025-02-27T22:00:00.000Z', 'end': '2025-02-28T18:31:00.000Z',
             'created_at': '2025-02-28T10:10:00.000Z', 'timezone_offset': '+02:00', 'score_state': 'SCORED'}
        b = {'id': 2, 'start': '2025-02-28T18:31:00.000Z', 'end': '2025-03-02T00:18:00.000Z',
             'created_at': '2025-02-28T22:45:00.000Z', 'timezone_offset': '+02:00', 'score_state': 'SCORED'}
        sleeps = [
            {'id': 10, 'cycle_id': 1, 'nap': False, 'start': '2025-02-27T22:00:00.000Z',
             'end': '2025-02-28T05:30:00.000Z', 'timezone_offset': '+02:00', 'score_state': 'SCORED'},
            {'id': 11, 'cycle_id': 2, 'nap': False, 'start': '2025-02-28T18:31:00.000Z',
             'end': '2025-03-01T03:00:00.000Z', 'timezone_offset': '+02:00', 'score_state': 'SCORED'},
        ]
        return [a, b], sleeps

    def test_two_cycles_on_one_utc_day_get_different_keys(self):
        cycles, sleeps = self.cycles()
        self.assertEqual(bd.day(cycles[0]['created_at']), bd.day(cycles[1]['created_at']))   # the old bug
        key = bd.DayKey(cycles, sleeps)
        self.assertEqual(key.of(cycles[0]), '2025-02-28')      # woke on the 28th
        self.assertEqual(key.of(cycles[1]), '2025-03-01')      # woke on the 1st
        self.assertNotEqual(key.of(cycles[0]), key.of(cycles[1]))

    def test_records_follow_their_cycle(self):
        cycles, sleeps = self.cycles()
        key = bd.DayKey(cycles, sleeps)
        self.assertEqual(key.of({'cycle_id': 2, 'created_at': '2025-02-28T23:00:00.000Z'}), '2025-03-01')
        # a workout started inside the second cycle belongs to it, though its UTC day is the 28th
        workout = {'start': '2025-02-28T19:40:00.000Z', 'created_at': '2025-02-28T20:50:00.000Z',
                   'timezone_offset': '+02:00'}
        self.assertEqual(key.of(workout), '2025-03-01')

    def test_a_cycle_without_a_sleep_falls_back_to_its_local_date(self):
        cycles, _ = self.cycles()
        key = bd.DayKey(cycles, [])
        self.assertEqual(key.of(cycles[0]), '2025-02-28')      # 22:00Z = 00:00 local on the 28th

    def test_utc_offsets_written_as_Z_are_handled(self):
        c = [{'id': 3, 'start': '2025-06-01T23:30:00.000Z', 'end': None,
              'created_at': '2025-06-02T05:00:00.000Z', 'timezone_offset': 'Z', 'score_state': 'SCORED'}]
        self.assertEqual(bd.DayKey(c, []).of(c[0]), '2025-06-01')
