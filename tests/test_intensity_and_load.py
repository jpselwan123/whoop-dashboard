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
        """The ratio runs on Edwards TRIMP, not day strain: the bands were built on linear load."""
        s = bd.build_summary(self.raw)
        L = s['load_today']
        self.assertEqual(L['date'], s['today_snapshot']['date'])
        self.assertEqual(L['ratio'], s['acwr'][-1]['v'])
        self.assertIn('load', L)
        self.assertNotIn('strain', L)

    def test_load_lines_put_the_ratio_exactly_on_each_band(self):
        """The 'passes 1.3 if today's load goes over X' number is pure algebra on the band."""
        s = bd.build_summary(self.raw)
        today = s['load_today']['date']
        load = {p['date']: p['v'] for p in s['full_series']['strain']}       # any per-day load works
        for band, r in bd.ACWR_BANDS.items():
            x = bd.build_load_today(load, today)['load_at'][band]
            if not x:                                    # 0 means the line is already passed
                continue
            got = bd.build_load_today(dict(load, **{today: x}), today)['ratio']
            self.assertAlmostEqual(got, r, delta=0.02, msg=band)

    def test_more_strain_today_raises_the_ratio(self):
        s = bd.build_summary(self.raw)
        today = s['load_today']['date']
        strain = {p['date']: p['v'] for p in s['full_series']['strain']}
        low = bd.build_load_today(dict(strain, **{today: 4.0}), today)['ratio']
        high = bd.build_load_today(dict(strain, **{today: 180.0}), today)['ratio']
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


class TrainingCostTest(unittest.TestCase):
    """What today's strain costs the next night, and the three gates before it is ever shown."""

    def history(self, effect, n=260, seed=5, noise=0.35):
        """Synthetic days where today's strain lowers the next night's composite by `effect`."""
        import random
        rnd = random.Random(seed)
        start = date(2026, 1, 1)
        days = [(start + timedelta(days=i)).isoformat() for i in range(n)]
        workout_days = {d for i, d in enumerate(days) if i % 3 != 0}
        strain = {d: (rnd.uniform(11, 18) if d in workout_days else rnd.uniform(3, 7)) for d in days}
        # the effect lands on the NEXT day's standardised composite — the scale the coefficient is
        # fitted on and later added to
        series, base = [], 0.0
        for i, d in enumerate(days):
            base = 0.5 * base + rnd.gauss(0, 0.6)
            z = base + (effect * (strain[days[i - 1]] - 5) if i else 0.0) + rnd.gauss(0, noise)
            series.append({'date': d, 'v': max(1, min(99, round(bd.normal_percentile(z)))),
                           'answer': 'moderate', 'z': z, 'night_z': z})
        return series, strain, workout_days, days

    def test_measures_the_effect_on_the_next_night(self):
        series, strain, wd, days = self.history(effect=-0.08)
        out = bd.build_training_cost(series, strain, wd, days[-1])
        self.assertTrue(out['significant'])
        self.assertAlmostEqual(out['per_strain'], -0.08, delta=0.03)
        self.assertEqual(out['pairs'], len(days) - 1)
        self.assertIn('residual_autocorr', out)

    def test_no_effect_in_the_history_is_not_significant(self):
        series, strain, wd, days = self.history(effect=0.0, seed=9)
        out = bd.build_training_cost(series, strain, wd, days[-1])
        self.assertFalse(out['significant'])
        self.assertFalse(out['usable'])
        self.assertIsNone(out['after'])

    def test_nothing_is_shown_unless_all_three_gates_pass(self):
        """Significant, monotone across strain terciles, and better than nothing out of sample."""
        series, strain, wd, days = self.history(effect=-0.08)
        out = bd.build_training_cost(series, strain, wd, days[-1])
        self.assertEqual(out['usable'], bool(out['significant'] and out['linear'] and out['holdout_better']))
        if not out['usable']:
            self.assertIsNone(out['after'])
        self.assertEqual(len(out['tercile_next_night']), 3)

    def test_a_quiet_day_is_never_a_bonus(self):
        series, strain, wd, days = self.history(effect=-0.08)
        strain[days[-1]] = 1.0                                  # far below a typical rest day
        out = bd.build_training_cost(series, strain, wd, days[-1])
        self.assertIn(out['cost'], (None, 0))

    def test_real_summary_carries_it(self):
        s = bd.build_summary(generate(120, 23))
        self.assertIn('training_cost', s)


class TrainingCostSignTestTest(unittest.TestCase):
    """The training cost's hold-out gate is the same sign test as the panel's — not a comparison of means."""

    def test_the_hold_out_gate_is_the_sign_test(self):
        series, strain, wd, days = TrainingCostTest().history(effect=-0.08)
        out = bd.build_training_cost(series, strain, wd, days[-1])
        st = out['holdout_sign_test']
        self.assertIsNotNone(st)
        self.assertEqual(out['holdout_better'], st['passes'])
        self.assertEqual(st['passes'], st['p'] < bd.SIGNIFICANCE)


class PlanEffectScriptTest(unittest.TestCase):
    """The offline analysis in scripts/analyse_plan_effect.py, on synthetic data only."""

    def setUp(self):
        import importlib.util, os
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            'scripts', 'analyse_plan_effect.py')
        spec = importlib.util.spec_from_file_location('analyse_plan_effect', path)
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)

    def test_recovers_a_known_effect(self):
        import random
        rnd = random.Random(7)
        X, y = [], []
        for _ in range(400):
            score_z, lvl = rnd.gauss(0, 1), float(rnd.randint(0, 3))
            X.append([1.0, score_z, lvl, score_z * lvl])
            y.append(0.3 * score_z - 0.2 * lvl + rnd.gauss(0, 0.5))      # no interaction
        # the script now uses the pipeline's estimator, so that is what is checked
        beta, se, r1 = bd._ols_newey_west(X, y, lag=self.mod.LAG)
        self.assertAlmostEqual(beta[1], 0.3, delta=0.08)
        self.assertAlmostEqual(beta[2], -0.2, delta=0.08)
        self.assertLess(abs(beta[3] / se[3]), 2.0, 'no interaction was simulated')
        self.assertGreater(abs(beta[2] / se[2]), 2.0, 'the intensity effect should be detected')

    def test_newey_west_widens_the_error_when_days_run_together(self):
        """Dependent days carry less information; the correction must not shrink the error."""
        import random
        rnd = random.Random(11)
        X, y, e = [], [], 0.0
        for i in range(300):
            e = 0.8 * e + rnd.gauss(0, 0.5)                              # autocorrelated noise
            x = rnd.gauss(0, 1)
            X.append([1.0, x])
            y.append(0.2 * x + e)
        _, se_nw, r1 = bd._ols_newey_west(X, y, lag=7)
        _, se_plain, _ = bd._ols_newey_west(X, y, lag=0)
        self.assertGreater(se_nw[1], se_plain[1] * 0.99)
        self.assertGreater(r1, 0.3, 'the fixture should leave autocorrelated residuals')
