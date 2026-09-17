"""Seiler intensity zones from WHOOP heart-rate-reserve zones, Foster monotony, rest days, sleep
nights and sport cost at the same intensity."""
import unittest
from datetime import date, datetime, timedelta, timezone
from helpers import generate, build_dashboard as bd

MIN = 60000


def iso(dt):
    return dt.strftime('%Y-%m-%dT%H:%M:%S.000Z')


class IntensityTest(unittest.TestCase):
    def test_zone_five_is_all_hard(self):
        # rest 60, max 200: zone 5 = 186–200 bpm, all above 87% of max (174)
        self.assertEqual(bd.intensity_minutes({'zone_five_milli': 30 * MIN}, 200, 60), [0.0, 0.0, 30.0])

    def test_zone_is_split_in_proportion_across_the_lines(self):
        # rest 60, max 200: zone 3 = 158–172 bpm; 82% line = 164 → 6/14 easy, 8/14 moderate
        easy, mod, hard = bd.intensity_minutes({'zone_three_milli': 14 * MIN}, 200, 60)
        self.assertAlmostEqual(easy, 6.0)
        self.assertAlmostEqual(mod, 8.0)
        self.assertAlmostEqual(hard, 0.0)

    def test_missing_heart_rates_give_nothing(self):
        self.assertIsNone(bd.intensity_minutes({'zone_three_milli': MIN}, None, 60))
        self.assertIsNone(bd.intensity_minutes({}, 200, 60))

    def test_session_level_follows_most_of_the_time(self):
        self.assertEqual(bd.session_level([30, 10, 5]), 'easy')
        self.assertEqual(bd.session_level([10, 20, 5]), 'moderate')
        self.assertEqual(bd.session_level([10, 5, 20]), 'hard')
        self.assertIsNone(bd.session_level([0, 0, 0]))

    def test_zone_chart_leaves_out_strength(self):
        now = datetime(2026, 1, 10, tzinfo=timezone.utc)
        def w(sport, zd):
            t = datetime(2026, 1, 8, 17, tzinfo=timezone.utc)
            return {'created_at': iso(t), 'start': iso(t), 'end': iso(t), 'sport_name': sport, 'score': {'zone_durations': zd}}
        out = bd.build_zone_distribution([w('weightlifting', {'zone_zero_milli': 60 * MIN}),
                                          w('running', {'zone_five_milli': 60 * MIN})], now, 200, lambda d: 60)
        self.assertEqual(out['all_time']['hard_pct'], 100)


class TrimpTest(unittest.TestCase):
    def test_edwards_weights_minutes_by_percent_of_max_hr(self):
        # rest 0, max 200 makes heart-rate reserve equal % of max: zone 4 (80–90%) × 4, zone 1 (50–60%) × 1
        self.assertAlmostEqual(bd.edwards_trimp({'zone_four_milli': 10 * MIN}, 200, 0.0001), 40, places=2)
        self.assertAlmostEqual(bd.edwards_trimp({'zone_one_milli': 30 * MIN}, 200, 0.0001), 30, places=2)

    def test_time_below_50_percent_counts_nothing(self):
        self.assertAlmostEqual(bd.edwards_trimp({'zone_zero_milli': 30 * MIN}, 200, 0.0001), 0, places=2)

    def test_trimp_adds_up_unlike_strain(self):
        a = bd.edwards_trimp({'zone_three_milli': 20 * MIN}, 190, 55)
        both = bd.edwards_trimp({'zone_three_milli': 40 * MIN}, 190, 55)
        self.assertAlmostEqual(both, 2 * a)


class MonotonyTest(unittest.TestCase):
    def test_foster_uses_zero_on_days_off_and_complete_weeks_only(self):
        week = [(date(2026, 3, 2) + timedelta(days=i)).isoformat() for i in range(10)]   # Mon … next Wed
        load = {week[0]: 10.0, week[2]: 10.0, week[4]: 10.0}
        out = bd.build_monotony(load, week)
        self.assertEqual(len(out), 1)                          # the partial second week is skipped
        self.assertEqual(out[0]['start'], week[0])
        vals = [10, 0, 10, 0, 10, 0, 0]
        m = sum(vals) / 7
        sd = (sum((v - m) ** 2 for v in vals) / 7) ** 0.5
        self.assertAlmostEqual(out[0]['monotony'], round(m / sd, 2))
        self.assertFalse(out[0]['high'])

    def test_same_load_every_day_is_high(self):
        week = [(date(2026, 3, 2) + timedelta(days=i)).isoformat() for i in range(7)]
        load = {d: 10.0 + (i % 2) for i, d in enumerate(week)}
        self.assertTrue(bd.build_monotony(load, week)[0]['high'])


class DayFactsTest(unittest.TestCase):
    def setUp(self):
        self.raw = generate(90)
        self.summary = bd.build_summary(self.raw)

    def test_rest_day_is_a_finished_day_without_a_workout(self):
        rest = self.summary['rest_day_stat']
        workout_days = {bd.day(w['created_at']) for w in self.raw['workouts']}
        self.assertNotIn(rest['last_rest_date'], workout_days)
        self.assertGreaterEqual(rest['days_since'], 1)

    def test_sleep_nights_count_7_hours_asleep(self):
        s = self.summary['sleep_nights']
        self.assertLessEqual(s['nights_7h'], s['nights'])
        self.assertEqual(s['min_hours'], 7)

    def test_workout_log_carries_intensity(self):
        for w in self.summary['workout_log']:
            self.assertIn(w['intensity'], ('easy', 'moderate', 'hard', None))


class SportCostTest(unittest.TestCase):
    def test_sports_are_compared_within_one_intensity(self):
        day_sessions, rec = {}, {}
        for i in range(120):
            d = (date(2026, 1, 1) + timedelta(days=i)).isoformat()
            sport = 'Soccer' if i % 2 else 'Tennis'
            day_sessions[d] = (sport, 'easy')
            rec[(date(2026, 1, 2) + timedelta(days=i)).isoformat()] = (40 if sport == 'Soccer' else 60) + (i % 5)
        out = bd.build_sport_recovery_cost(day_sessions, rec)
        g = out['groups'][0]
        self.assertEqual(g['intensity'], 'easy')
        by = {s['sport']: s for s in g['sports']}
        self.assertTrue(by['Soccer']['significant'] and by['Soccer']['delta'] < 0)

    def test_every_sport_is_listed_but_small_samples_are_never_called_real(self):
        day_sessions = {(date(2026, 1, 1) + timedelta(days=i)).isoformat(): ('Table-Tennis' if i < 2 else 'Tennis', 'easy')
                        for i in range(60)}
        rec = {(date(2026, 1, 2) + timedelta(days=i)).isoformat(): (5 if i < 2 else 50 + i % 3) for i in range(60)}
        g = bd.build_sport_recovery_cost(day_sessions, rec)['groups'][0]
        by = {s['sport']: s for s in g['sports']}
        self.assertEqual(by['Table-Tennis']['n'], 2)
        self.assertFalse(by['Table-Tennis']['significant'])

    def test_strength_days_are_compared_with_all_other_days(self):
        day_sessions, rec = {}, {}
        for i in range(120):
            d = (date(2026, 1, 1) + timedelta(days=i)).isoformat()
            day_sessions[d] = ('Weightlifting', 'strength') if i % 2 else ('Soccer', 'easy')
            rec[(date(2026, 1, 2) + timedelta(days=i)).isoformat()] = (70 if i % 2 else 45) + i % 4
        out = bd.build_sport_recovery_cost(day_sessions, rec, {'Weightlifting', 'Soccer', 'Yoga'})
        strength = [g for g in out['groups'] if g['intensity'] == 'strength'][0]['sports'][0]
        self.assertTrue(strength['vs_all'] and strength['significant'] and strength['delta'] > 0)
        self.assertEqual(out['never_hardest'], ['Yoga'])

if __name__ == '__main__':
    unittest.main()
