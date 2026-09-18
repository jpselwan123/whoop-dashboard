"""Seiler intensity zones from WHOOP heart-rate-reserve zones, Foster monotony, rest days, sleep
nights and sport cost at the same intensity."""
import json, unittest
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

    def test_todays_session_and_load_ratio_include_today(self):
        # a session logged today must show up in the snapshot (so the page can act on it) and the
        # load ratio must cover today, so both change when the refresh button pulls new data
        snap = self.summary['today_snapshot']
        today_workouts = [w for w in self.raw['workouts'] if bd.day(w['created_at']) == snap['date']]
        self.assertEqual(len(snap['workouts']), len(today_workouts))
        self.assertEqual(self.summary['acwr'][-1]['date'], snap['date'])
        strain_today = [p['v'] for p in self.summary['full_series']['strain'] if p['date'] == snap['date']]
        self.assertEqual(strain_today, [round(snap['strain_so_far'], 1)])

    def test_workout_log_carries_intensity(self):
        for w in self.summary['workout_log']:
            self.assertIn(w['intensity'], ('easy', 'moderate', 'hard', None))


class SportCostTest(unittest.TestCase):
    """One row per sport: its days vs all other training days."""

    def build(self, n=120):
        day_sessions, rec = {}, {}
        for i in range(n):
            d = (date(2026, 1, 1) + timedelta(days=i)).isoformat()
            sport = 'Soccer' if i % 2 else 'Tennis'
            day_sessions[d] = (sport, 'hard' if sport == 'Soccer' else 'easy')
            rec[(date(2026, 1, 2) + timedelta(days=i)).isoformat()] = (40 if sport == 'Soccer' else 60) + (i % 5)
        return day_sessions, rec

    def test_one_row_per_sport_with_its_usual_intensity(self):
        out = bd.build_sport_recovery_cost(*self.build())
        rows = {s['sport']: s for s in out['sports']}
        self.assertEqual(sorted(rows), ['Soccer', 'Tennis'])
        self.assertEqual(rows['Soccer']['intensity'], 'hard')
        self.assertEqual(rows['Tennis']['intensity'], 'easy')
        self.assertTrue(rows['Soccer']['significant'] and rows['Soccer']['delta'] < 0)
        self.assertEqual(rows['Soccer']['n'] + rows['Tennis']['n'], out['days'])

    def test_sorted_by_days_and_small_samples_are_never_called_real(self):
        day_sessions, rec = self.build()
        for i in range(2):
            d = (date(2026, 6, 1) + timedelta(days=i)).isoformat()
            day_sessions[d] = ('Table-Tennis', 'easy')
            rec[(date(2026, 6, 2) + timedelta(days=i)).isoformat()] = 5
        out = bd.build_sport_recovery_cost(day_sessions, rec)
        self.assertEqual([s['n'] for s in out['sports']], sorted([s['n'] for s in out['sports']], reverse=True))
        tt = [s for s in out['sports'] if s['sport'] == 'Table-Tennis'][0]
        self.assertEqual(tt['n'], 2)
        self.assertFalse(tt['significant'])

    def test_sports_never_the_hardest_session_are_named(self):
        out = bd.build_sport_recovery_cost(*self.build(), all_sports={'Soccer', 'Tennis', 'Yoga'})
        self.assertEqual(out['never_hardest'], ['Yoga'])

if __name__ == '__main__':
    unittest.main()


class DayAdaptsTest(unittest.TestCase):
    """What changes when the refresh button pulls new activity mid-day."""

    def setUp(self):
        self.raw = generate(120, 23)

    def test_load_ratio_today_matches_the_card(self):
        s = bd.build_summary(self.raw)
        L = s['load_today']
        self.assertEqual(L['date'], s['today_snapshot']['date'])
        self.assertEqual(L['ratio'], s['acwr'][-1]['v'])
        self.assertEqual(L['strain'], s['today_snapshot']['strain_so_far'])

    def test_strain_lines_put_the_ratio_exactly_on_each_band(self):
        """The 'passes 1.3 if today's strain goes over X' number is pure algebra on the band."""
        s = bd.build_summary(self.raw)
        today = s['load_today']['date']
        strain = {p['date']: p['v'] for p in s['full_series']['strain']}
        for band, r in bd.ACWR_BANDS.items():
            x = s['load_today']['strain_at'][band]
            if x is None or x in (0.0, 21.0):          # clamped: the line can't be reached today
                continue
            probe = dict(strain, **{today: x})
            got = bd.build_load_today(probe, today)['ratio']
            self.assertAlmostEqual(got, r, delta=0.011, msg=band)

    def test_more_strain_today_raises_the_ratio(self):
        s = bd.build_summary(self.raw)
        today = s['load_today']['date']
        strain = {p['date']: p['v'] for p in s['full_series']['strain']}
        low = bd.build_load_today(dict(strain, **{today: 4.0}), today)['ratio']
        high = bd.build_load_today(dict(strain, **{today: 18.0}), today)['ratio']
        self.assertGreater(high, low)

    def test_a_nap_today_moves_readiness(self):
        """Readiness is measured overnight, but hours asleep count naps — a nap logged later in the
        day changes today's score on the next refresh."""
        before = bd.build_summary(self.raw)
        today = before['readiness']['date']
        night = [x for x in self.raw['sleep'] if not x['nap'] and bd.day(x['created_at']) == today][0]
        end = bd.parse(night['end']) + timedelta(hours=7)
        nap = json.loads(json.dumps(night))
        nap.update({'id': 'nap-test', 'nap': True, 'start': (end - timedelta(hours=2)).isoformat(),
                    'end': end.isoformat(), 'created_at': (end + timedelta(minutes=8)).isoformat()})
        raw = dict(self.raw, sleep=self.raw['sleep'] + [nap])
        after = bd.build_summary(raw)
        self.assertEqual(after['readiness']['date'], today)
        self.assertNotEqual(after['readiness']['score'], before['readiness']['score'])
        self.assertGreater(after['last_night']['nap_h'], before['last_night']['nap_h'])
