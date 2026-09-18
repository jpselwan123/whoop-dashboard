"""Readiness: 7-day HRV, resting HR and sleep, each a standard score vs the 7-day averages of the
previous 4 weeks, averaged on the T scale (50 = normal). 55+ Train hard, 45–54 Train as planned,
35–44 Go easy, under 35 Rest; Rest on a breathing-rate illness sign, Go easy after 2 hard days in a row."""
import math, random, unittest
from datetime import date, timedelta
from helpers import generate, build_dashboard as bd


def days(n, start=date(2026, 1, 5)):          # a Monday
    return [(start + timedelta(days=i)).isoformat() for i in range(n)]


# day-to-day pattern plus a slow drift, like real data
LN_PATTERN = (0.0, 0.05, -0.05, 0.1, -0.1, 0.03, -0.03)
HR_PATTERN = (0.0, 1.0, -1.0, 2.0, -2.0, 0.5, -0.5)


def steady(n=70, hrv=80.0, rhr=55.0, rr=15.0):
    ds = days(n)
    last_week = (n - 1) // 7
    # weekly level alternates up/down so the baseline 7-day averages have a spread; the latest week sits
    # exactly at the middle of that spread (a normal week)
    drift = lambda i: 0.0 if i // 7 == last_week else (0.04 if (i // 7) % 2 == 0 else -0.04)
    return ({d: hrv * math.exp(LN_PATTERN[i % 7] + drift(i)) for i, d in enumerate(ds)},
            {d: rhr + HR_PATTERN[i % 7] + 12 * drift(i) for i, d in enumerate(ds)},
            {d: rr + HR_PATTERN[i % 7] * 0.1 for i, d in enumerate(ds)}, ds)


class ProtocolTest(unittest.TestCase):
    def test_normal_week_means_train_as_planned(self):
        """Inside the normal band the trials prescribed the planned session, not a hard one."""
        h, r, b, _ = steady()
        latest, _ = bd.build_readiness(h, r, b, set())
        self.assertEqual((latest['answer'], latest['reasons']), ('moderate', []))
        self.assertEqual(latest['hrv']['state'], 'within')
        self.assertTrue(45 <= latest['score'] < 55)

    def test_hrv_drop_over_the_week_means_easy(self):
        h, r, b, ds = steady()
        for d in ds[-7:]:
            h[d] *= 0.7
        latest, _ = bd.build_readiness(h, r, b, set())
        self.assertIn(latest['answer'], ('easy', 'rest'))
        self.assertEqual(latest['reasons'], ['low'])
        self.assertLess(latest['score'], 45)
        self.assertEqual(latest['hrv']['state'], 'below')

    def test_hrv_above_the_band_means_train_hard(self):
        h, r, b, ds = steady()
        for d in ds[-7:]:
            h[d] *= 1.4
        latest, _ = bd.build_readiness(h, r, b, set())
        self.assertEqual((latest['answer'], latest['hrv']['state']), ('hard', 'above'))

    def test_resting_hr_rise_means_easy(self):
        h, r, b, ds = steady()
        for d in ds[-7:]:
            r[d] += 8
        latest, _ = bd.build_readiness(h, r, b, set())
        self.assertEqual(latest['rhr']['state'], 'above')
        self.assertLess(latest['score'], 50, "higher resting HR must lower readiness")

    def test_a_slightly_low_night_is_diluted_by_the_7_day_average(self):
        h, r, b, ds = steady()
        h[ds[-1]] *= 0.93
        latest, _ = bd.build_readiness(h, r, b, set())
        self.assertEqual(latest['answer'], 'moderate')

    def test_normal_range_is_fixed_within_a_week(self):
        h, r, b, ds = steady(n=70)
        _, _ = bd.build_readiness(h, r, b, set())
        ranges = set()
        monday = date.fromisoformat(ds[-1]) - timedelta(days=date.fromisoformat(ds[-1]).weekday())
        for d in ds:
            if date.fromisoformat(d) >= monday:
                sub = {k: v for k, v in h.items() if k <= d}
                latest, _ = bd.build_readiness(sub, {k: v for k, v in r.items() if k <= d}, b, set())
                ranges.add(tuple(latest['hrv']['normal']))
        self.assertEqual(len(ranges), 1)

    def test_range_is_built_from_the_7_day_averages_of_the_4_weeks_before_this_week(self):
        h, r, b, ds = steady()
        for i, d in enumerate(ds):            # vary the weekly level so the 7-day averages have a spread
            h[d] *= math.exp(0.02 * (i // 7 % 3))
        d = ds[-1]
        monday = date.fromisoformat(d) - timedelta(days=date.fromisoformat(d).weekday())
        ln = {k: math.log(v) for k, v in h.items()}
        def roll(day):
            vals = [v for k, v in ln.items() if day - timedelta(days=6) <= date.fromisoformat(k) <= day]
            return sum(vals) / len(vals)
        base = [roll(monday - timedelta(days=k)) for k in range(1, 29)]
        m = sum(base) / len(base)
        sd = math.sqrt(sum((x - m) ** 2 for x in base) / (len(base) - 1))   # sample SD
        latest, _ = bd.build_readiness(h, r, b, set())
        self.assertEqual(latest['hrv']['normal'], [round(math.exp(m - 0.5 * sd)), round(math.exp(m + 0.5 * sd))])

    def test_needs_3_readings_in_the_week(self):
        h, r, b, ds = steady()
        for d in ds[-7:-2]:
            h.pop(d)
        _, series = bd.build_readiness(h, r, b, set())
        self.assertNotIn(ds[-1], [p['date'] for p in series])     # only 2 readings in the last 7 days

    def test_new_account_has_no_answer(self):
        h, r, b, _ = steady(n=28)          # starts on a Monday: 4 full weeks, answer from day 29
        self.assertEqual(bd.build_readiness(h, r, b, set()), (None, []))
        self.assertEqual(bd.readiness_progress(h), {'days': 28, 'needed': 29})
        h, r, b, _ = steady(n=29)
        self.assertIsNotNone(bd.build_readiness(h, r, b, set())[0])

    def test_each_baseline_week_needs_3_readings(self):
        h, r, b, ds = steady(n=70)
        monday = date.fromisoformat(ds[-1]) - timedelta(days=date.fromisoformat(ds[-1]).weekday())
        for d in list(h):
            if monday - timedelta(days=14) <= date.fromisoformat(d) < monday - timedelta(days=9):
                h.pop(d)          # leaves 2 readings in that baseline week
        latest, series = bd.build_readiness(h, r, b, set())
        self.assertNotIn(ds[-1], [p['date'] for p in series])

    def test_two_hard_days_in_a_row_means_easy(self):
        h, r, b, ds = steady()
        latest, _ = bd.build_readiness(h, r, b, {ds[-2], ds[-3]})
        self.assertEqual((latest['answer'], latest['reasons']), ('easy', ['streak']))
        latest, _ = bd.build_readiness(h, r, b, {ds[-2], ds[-4]})
        self.assertEqual(latest['answer'], 'moderate')

    def test_breathing_rate_3_above_usual_means_easy(self):
        h, r, b, ds = steady(n=100)
        usual = sum(b[d] for d in ds if 30 <= (date.fromisoformat(ds[-1]) - date.fromisoformat(d)).days <= 90)
        usual /= sum(1 for d in ds if 30 <= (date.fromisoformat(ds[-1]) - date.fromisoformat(d)).days <= 90)
        b[ds[-1]] = usual + 3.05
        latest, _ = bd.build_readiness(h, r, b, set())
        self.assertIn('breathing', latest['reasons'])
        b[ds[-1]] = usual + 2.9
        latest, _ = bd.build_readiness(h, r, b, set())
        self.assertNotIn('breathing', latest['reasons'])

    def test_breathing_needs_30_nights_of_history(self):
        h, r, b, _ = steady(n=50)
        latest, _ = bd.build_readiness(h, r, b, set())
        self.assertIsNone(latest['breathing'])

    def test_values_are_reported_in_real_units(self):
        h, r, b, _ = steady()
        latest, _ = bd.build_readiness(h, r, b, set())
        lo, hi = latest['hrv']['normal']
        self.assertTrue(60 < lo < latest['hrv']['value'] < hi < 110)

    def test_summary_includes_readiness(self):
        summary = bd.build_summary(generate(120))
        for key in ('readiness', 'readiness_progress', 'readiness_check', 'last_night', 'sleep_nights'):
            self.assertIn(key, summary)
        self.assertIn(summary['readiness']['answer'], ('hard', 'moderate', 'easy', 'rest'))


class ScoreTest(unittest.TestCase):
    def test_score_is_the_t_scale_average_of_the_standard_scores(self):
        h, r, b, ds = steady()
        last_week = (len(ds) - 1) // 7
        sleep = {d: 7.5 + LN_PATTERN[i % 7] + (0 if i // 7 == last_week else (0.3 if (i // 7) % 2 else -0.3))
                 for i, d in enumerate(ds)}
        latest, _ = bd.build_readiness(h, r, b, set(), sleep)
        monday = date.fromisoformat(ds[-1]) - timedelta(days=date.fromisoformat(ds[-1]).weekday())
        def z(src, f, flip):
            def roll(day):
                v = [f(x) for k, x in src.items() if day - timedelta(days=6) <= date.fromisoformat(k) <= day]
                return sum(v) / len(v)
            base = [roll(monday - timedelta(days=k)) for k in range(1, 29)]
            m = sum(base) / len(base)
            sd = math.sqrt(sum((x - m) ** 2 for x in base) / (len(base) - 1))
            if sd == 0:
                return None
            return (roll(date.fromisoformat(ds[-1])) - m) / sd * (-1 if flip else 1)
        def z_night(src, f, flip):
            base = [f(v) for k, v in src.items() if monday - timedelta(days=28) <= date.fromisoformat(k) < monday]
            m = sum(base) / len(base)
            sd = math.sqrt(sum((x - m) ** 2 for x in base) / (len(base) - 1))
            return None if sd == 0 else (f(src[ds[-1]]) - m) / sd * (-1 if flip else 1)
        zs = [x for x in (z(h, math.log, False), z(r, lambda v: v, True), z(sleep, lambda v: v, False),
                          z_night(h, math.log, False), z_night(r, lambda v: v, True), z_night(sleep, lambda v: v, False))
              if x is not None]
        self.assertEqual(len(zs), 6)
        self.assertEqual(latest['score'], math.floor(50 + 10 * sum(zs) / len(zs) + 0.5))
        self.assertEqual(latest['last_night']['measures'], 3)

    def test_answer_lines_on_the_score(self):
        h, r, b, ds = steady()
        for factor in (1.4, 1.0, 0.93, 0.6):
            hh = dict(h)
            for d in ds[-7:]:
                hh[d] = h[d] * factor
            latest, _ = bd.build_readiness(hh, r, b, set())
            s = latest['score']
            want = 'hard' if s >= 55 else 'moderate' if s >= 45 else 'easy' if s >= 35 else 'rest'
            self.assertEqual(latest['answer'], want, (factor, s))
        self.assertEqual(latest['lines'], {'above': 55, 'train': 45, 'rest': 35})

    def test_the_four_bands_are_the_swc_and_rest_lines(self):
        """Band edges are +0.5 SD, -0.5 SD and -1.5 SD on the T scale: 55 / 45 / 35."""
        h, r, b, _ = steady()
        latest, _ = bd.build_readiness(h, r, b, set())
        L = latest['lines']
        self.assertEqual([L['above'], L['train'], L['rest']],
                         [50 + 10 * 0.5, 50 - 10 * 0.5, 50 - 10 * 1.5])

    def test_breathing_sign_means_rest_even_with_a_normal_score(self):
        h, r, b, ds = steady(n=100)
        b[ds[-1]] = 40.0
        latest, _ = bd.build_readiness(h, r, b, set())
        self.assertGreaterEqual(latest['score'], 45)
        self.assertEqual((latest['answer'], latest['reasons']), ('rest', ['breathing']))

    def test_shorter_sleep_lowers_the_score(self):
        h, r, b, ds = steady()
        sleep = {d: 7.5 + (0.3 if (i // 7) % 2 else -0.3) for i, d in enumerate(ds)}
        normal, _ = bd.build_readiness(h, r, b, set(), sleep)
        for d in ds[-7:]:
            sleep[d] = 5.0
        short, _ = bd.build_readiness(h, r, b, set(), sleep)
        self.assertEqual(short['sleep']['state'], 'below')
        self.assertLess(short['score'], normal['score'])

    def test_series_carries_score_and_answer(self):
        h, r, b, _ = steady()
        _, series = bd.build_readiness(h, r, b, set())
        self.assertTrue(all(0 <= p['v'] <= 100 and p['answer'] in ('hard', 'moderate', 'easy', 'rest') for p in series))


class StatisticsTest(unittest.TestCase):
    def test_incomplete_beta_matches_known_value(self):
        # two-sided p for t = 2.0 with 10 degrees of freedom is 0.0734
        self.assertAlmostEqual(bd._betainc(5, 0.5, 10 / 14), 0.07339, places=4)

    def test_welch_detects_a_real_gap_and_not_noise(self):
        rng = random.Random(3)
        a = [rng.gauss(55, 15) for _ in range(200)]
        self.assertLess(bd.welch_p(a, [rng.gauss(45, 15) for _ in range(200)]), 0.05)
        self.assertGreater(bd.welch_p(a, [rng.gauss(55, 15) for _ in range(200)]), 0.05)

    def test_check_needs_30_days_of_each_answer(self):
        series = [{'date': (date(2026, 1, 1) + timedelta(days=i)).isoformat(), 'answer': 'hard' if i % 2 else 'easy'}
                  for i in range(40)]
        rec = {(date(2026, 1, 2) + timedelta(days=i)).isoformat(): 60 if i % 2 else 40 for i in range(40)}
        out = bd.build_readiness_check(series, rec)
        self.assertFalse(out['enough'])
        self.assertFalse(out['significant'])

    def test_check_uses_next_morning(self):
        series = [{'date': (date(2026, 1, 1) + timedelta(days=i)).isoformat(), 'answer': 'hard' if i % 2 else ('easy' if i % 4 else 'rest')}
                  for i in range(200)]
        rec = {(date(2026, 1, 2) + timedelta(days=i)).isoformat(): (60 if i % 2 else 40) + (i % 7) for i in range(200)}
        out = bd.build_readiness_check(series, rec)
        self.assertTrue(out['enough'] and out['significant'] and out['hard_higher'])


if __name__ == '__main__':
    unittest.main()
