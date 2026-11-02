"""Polarization index, WHO activity minutes, body clock and the sleep/next-morning link, each against
values worked out by hand from the papers' own formulas."""
import math, unittest
from datetime import datetime, timedelta
from helpers import build_dashboard as bd


class PolarizationIndexTest(unittest.TestCase):
    """Treff et al. 2019: log10(Z1 / Z2 x Z3 x 100), above 2.00 = polarized."""

    def test_a_polarized_mix(self):
        self.assertEqual(bd.polarization_index(80, 5, 15), round(math.log10(0.8 / 0.05 * 0.15 * 100), 2))
        self.assertGreater(bd.polarization_index(80, 5, 15), bd.POLARIZED_ABOVE)

    def test_a_pyramidal_mix_is_not_polarized(self):
        self.assertEqual(bd.polarization_index(75, 20, 5), round(math.log10(0.75 / 0.2 * 0.05 * 100), 2))
        self.assertLess(bd.polarization_index(75, 20, 5), bd.POLARIZED_ABOVE)

    def test_more_hard_than_easy_is_not_defined(self):
        self.assertIsNone(bd.polarization_index(30, 10, 60))

    def test_no_hard_time_is_zero(self):
        self.assertEqual(bd.polarization_index(90, 10, 0), 0.0)

    def test_no_moderate_time_uses_one_hundredth(self):
        self.assertEqual(bd.polarization_index(80, 0, 20), round(math.log10(0.8 / 0.01 * 0.19 * 100), 2))

    def test_no_training_at_all(self):
        self.assertIsNone(bd.polarization_index(0, 0, 0))


def _workout(when, sport='running', **zones_min):
    ms = {k: v * 60000 for k, v in zones_min.items()}
    return {'sport_name': sport, 'created_at': when.isoformat(), 'start': when.isoformat(),
            'score': {'zone_durations': ms}}


class WhoMinutesTest(unittest.TestCase):
    """WHO 2020: 150 moderate-equivalent minutes; vigorous (60%+ HRR = WHOOP zone 2 up) counts twice."""

    def setUp(self):
        bd.DAY = None
        self.now = datetime(2026, 11, 4, 12)                     # a Wednesday
        last_week = self.now - timedelta(days=7)
        self.wo = [
            _workout(last_week, zone_zero_milli=30, zone_one_milli=40, zone_two_milli=20, zone_four_milli=10),
            _workout(last_week, sport='weightlifting', zone_two_milli=60),    # strength: left out
            _workout(self.now, zone_one_milli=10),
        ]

    def test_zone_one_is_moderate_and_two_up_count_twice(self):
        W = bd.build_who_minutes(self.wo, self.now)
        lw = W['last_full_week']
        self.assertEqual((lw['moderate_min'], lw['vigorous_min'], lw['equivalent_min']), (40, 30, 100))

    def test_eight_weeks_and_only_full_weeks_are_judged(self):
        W = bd.build_who_minutes(self.wo, self.now)
        self.assertEqual(len(W['weekly']), 8)
        self.assertTrue(W['weekly'][-1]['is_current'])
        self.assertEqual(W['full_weeks'], 7)
        self.assertEqual(W['weeks_met'], 0)
        self.assertEqual(W['goal_min'], 150)

    def test_a_week_over_the_line_counts(self):
        last_week = self.now - timedelta(days=7)
        W = bd.build_who_minutes(self.wo + [_workout(last_week, zone_three_milli=25)], self.now)
        self.assertEqual(W['last_full_week']['equivalent_min'], 150)
        self.assertEqual(W['weeks_met'], 1)


def _night(onset, hours):
    end = onset + timedelta(hours=hours)
    return {'start': onset.isoformat() + '+00:00', 'end': end.isoformat() + '+00:00',
            'created_at': end.isoformat() + '+00:00', 'timezone_offset': '+00:00', 'nap': False}


class BodyClockTest(unittest.TestCase):
    """Wittmann 2006 social jetlag and Roenneberg 2012 MSFsc on four weeks of fixed nights."""

    def setUp(self):
        bd.DAY = None
        self.sleep = []
        first = datetime(2026, 10, 5)                            # a Monday
        for i in range(28):
            wake_day = first + timedelta(days=i)
            if wake_day.weekday() >= 5:                          # waking Sat/Sun: 01:00 to 10:00
                self.sleep.append(_night(wake_day.replace(hour=1), 9))
            else:                                                # waking Mon-Fri: 23:00 to 07:00
                self.sleep.append(_night(wake_day - timedelta(hours=1), 8))
        self.today = (first + timedelta(days=27)).date().isoformat()

    def test_mid_sleep_and_social_jetlag(self):
        B = bd.build_body_clock(self.sleep, self.today)
        self.assertAlmostEqual(B['mid_work_h'], 27.0, places=3)     # 03:00
        self.assertAlmostEqual(B['mid_free_h'], 29.5, places=3)     # 05:30
        self.assertAlmostEqual(B['social_jetlag_h'], 2.5, places=3)
        self.assertEqual((B['n_work'], B['n_free']), (20, 8))

    def test_chronotype_is_corrected_for_catch_up_sleep(self):
        B = bd.build_body_clock(self.sleep, self.today)
        sd_week = (5 * 8 + 2 * 9) / 7
        self.assertAlmostEqual(B['chronotype_h'], 29.5 - (9 - sd_week) / 2, places=3)
        self.assertAlmostEqual(B['catch_up_h'], 1.0, places=3)

    def test_no_correction_when_weekend_sleep_is_not_longer(self):
        short = [_night(datetime.fromisoformat(s['start'][:19]), 7.5) if datetime.fromisoformat(s['end'][:19]).weekday() >= 5 else s
                 for s in self.sleep]
        B = bd.build_body_clock(short, self.today)
        self.assertAlmostEqual(B['chronotype_h'], B['mid_free_h'], places=3)

    def test_too_few_weekend_nights_shows_nothing(self):
        weekdays_only = [s for s in self.sleep if datetime.fromisoformat(s['end'][:19]).weekday() < 5]
        self.assertIsNone(bd.build_body_clock(weekdays_only, self.today))


class SleepNextMorningTest(unittest.TestCase):
    def setUp(self):
        bd.DAY = None

    def _nights(self, n_long, n_short):
        sleep, hrv, rec = [], {}, {}
        day = datetime(2026, 1, 1, 7)
        for i in range(n_long + n_short):
            hours = 8 if i < n_long else 6
            asleep = hours * 3600000
            sleep.append({'created_at': (day + timedelta(days=i)).isoformat() + '+00:00',
                          'score': {'stage_summary': {'total_in_bed_time_milli': asleep, 'total_awake_time_milli': 0}}})
            d = (day + timedelta(days=i)).date().isoformat()
            hrv[d] = (70 if i < n_long else 60) + (i % 5)
            rec[d] = (70 if i < n_long else 50) + (i % 7)
        return sleep, hrv, rec

    def test_a_real_gap_with_enough_mornings_is_clear(self):
        L = bd.build_sleep_hrv_link(*self._nights(40, 40))
        self.assertEqual(L['hrv']['n_long'], 40)
        self.assertAlmostEqual(L['hrv']['diff'], 10.0, delta=0.5)
        self.assertTrue(L['hrv']['clear'])

    def test_fewer_than_30_a_side_is_never_clear(self):
        L = bd.build_sleep_hrv_link(*self._nights(40, 12))
        self.assertFalse(L['hrv']['clear'])
        self.assertEqual(L['hrv']['n_short'], 12)

    def test_one_side_missing_shows_nothing(self):
        L = bd.build_sleep_hrv_link(*self._nights(20, 0))
        self.assertIsNone(L['hrv'])


if __name__ == '__main__':
    unittest.main()
