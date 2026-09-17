"""Same-day context: session intensity (Stanley et al. 2013 levels) and naps counted toward sleep."""
import unittest
from datetime import datetime, timedelta, timezone
from helpers import generate, build_dashboard as bd


def iso(dt):
    return dt.strftime('%Y-%m-%dT%H:%M:%S.000Z')


def main_sleep(wake, asleep_h=6.0, need_h=8.0):
    start = wake - timedelta(hours=asleep_h + 0.5)
    return {'created_at': iso(wake + timedelta(minutes=10)), 'start': iso(start), 'end': iso(wake), 'nap': False,
            'score_state': 'SCORED',
            'score': {'stage_summary': {'total_in_bed_time_milli': int((asleep_h + 0.5) * 3.6e6),
                                        'total_awake_time_milli': int(0.5 * 3.6e6)},
                      'sleep_needed': {'baseline_milli': int(need_h * 3.6e6), 'need_from_sleep_debt_milli': 0,
                                       'need_from_recent_strain_milli': 0, 'need_from_recent_nap_milli': 0},
                      'sleep_performance_percentage': round(100 * asleep_h / need_h)}}


def nap(start, asleep_h):
    end = start + timedelta(hours=asleep_h)
    return {'created_at': iso(end + timedelta(minutes=5)), 'start': iso(start), 'end': iso(end), 'nap': True,
            'score_state': 'SCORED',
            'score': {'stage_summary': {'total_in_bed_time_milli': int(asleep_h * 3.6e6), 'total_awake_time_milli': 0}}}


WAKE = datetime(2026, 3, 10, 6, 30, tzinfo=timezone.utc)


class SessionIntensityTest(unittest.TestCase):
    def test_levels(self):
        self.assertEqual(bd.session_intensity(0, 5, 6.0), 'easy')
        self.assertEqual(bd.session_intensity(3, 25, 8.0), 'moderate')      # 20+ min in zone 3+
        self.assertEqual(bd.session_intensity(0, 0, 10.0), 'moderate')      # WHOOP moderate strain
        self.assertEqual(bd.session_intensity(12, 30, 9.0), 'hard')         # 10+ min in zones 4–5
        self.assertEqual(bd.session_intensity(0, 0, 14.0), 'hard')          # WHOOP high strain

    def test_missing_strain_is_safe(self):
        self.assertEqual(bd.session_intensity(0, 0, None), 'easy')

    def test_snapshot_workouts_carry_intensity(self):
        summary = bd.build_summary(generate(60))
        for w in summary['today_snapshot']['workouts']:
            self.assertIn(w['intensity'], ('easy', 'moderate', 'hard'))


class NapTest(unittest.TestCase):
    def test_no_nap_keeps_whoop_number(self):
        s = main_sleep(WAKE)
        perf, naps = bd.sleep_with_naps([s], [])
        self.assertEqual(perf, {'2026-03-10': 75})
        self.assertEqual(naps, {})

    def test_nap_after_waking_adds_sleep_time(self):
        perf, naps = bd.sleep_with_naps([main_sleep(WAKE)], [nap(WAKE + timedelta(hours=7), 1.0)])
        self.assertEqual(perf['2026-03-10'], 87.5)          # 75 + 1 h / 8 h
        self.assertEqual(naps['2026-03-10'], 1.0)

    def test_uses_hours_vs_needed_not_whoop_sleep_performance(self):
        s = main_sleep(WAKE, asleep_h=6.04, need_h=10.05)
        s['score']['sleep_performance_percentage'] = 73      # WHOOP's 2025 blended score
        perf, _ = bd.sleep_with_naps([s], [])
        self.assertEqual(perf['2026-03-10'], 60.1)            # 6h 04m of 10h 03m needed

    def test_capped_at_100(self):
        perf, _ = bd.sleep_with_naps([main_sleep(WAKE, asleep_h=7.5)], [nap(WAKE + timedelta(hours=6), 2.0)])
        self.assertEqual(perf['2026-03-10'], 100.0)

    def test_nap_before_the_main_sleep_or_another_day_is_ignored(self):
        before = nap(WAKE - timedelta(hours=9), 1.0)            # yesterday evening
        other_day = nap(WAKE + timedelta(days=1, hours=7), 1.0)
        perf, naps = bd.sleep_with_naps([main_sleep(WAKE)], [before, other_day])
        self.assertEqual(perf['2026-03-10'], 75)
        self.assertEqual(naps, {})

    def test_zero_need_does_not_crash(self):
        s = main_sleep(WAKE)
        s['score']['sleep_needed'] = {}
        perf, naps = bd.sleep_with_naps([s], [nap(WAKE + timedelta(hours=7), 1.0)])
        self.assertEqual(perf['2026-03-10'], 75)

    def test_nap_shows_in_readiness_last_night(self):
        raw = generate(120)
        today = bd.build_summary(raw)['readiness']['date']
        raw['sleep'] = [x for x in raw['sleep'] if not (x['nap'] and bd.day(x['created_at']) == today)]
        without = bd.build_summary(raw)['readiness']
        main = [x for x in raw['sleep'] if not x['nap'] and bd.day(x['created_at']) == today][0]
        start = datetime.fromisoformat(main['end'].replace('Z', '+00:00')) + timedelta(hours=6)
        raw['sleep'].append(nap(start, 1.0))
        self.assertEqual(bd.day(raw['sleep'][-1]['created_at']), today)
        with_nap = bd.build_summary(raw)['readiness']
        self.assertEqual(with_nap['last_night']['components']['sleep']['nap_h'], 1.0)
        self.assertNotIn('nap_h', without['last_night']['components']['sleep'])
        self.assertGreaterEqual(with_nap['score'], without['score'])
        self.assertGreater(with_nap['last_night']['components']['sleep']['value'],
                           without['last_night']['components']['sleep']['value'])

if __name__ == '__main__':
    unittest.main()
