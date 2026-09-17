"""Sport cost at similar intensity, strength sessions out of the zone split, rest-day calendar count."""
import unittest
from datetime import datetime, timedelta, timezone
from helpers import generate, build_dashboard as bd


def iso(dt):
    return dt.strftime('%Y-%m-%dT%H:%M:%S.000Z')


def workout(day, sport, hr, strain=10.0, zones=None):
    start = datetime(2026, 1, 1, 17, tzinfo=timezone.utc) + timedelta(days=day)
    return {'created_at': iso(start + timedelta(hours=1)), 'start': iso(start), 'end': iso(start + timedelta(hours=1)),
            'sport_name': sport, 'score_state': 'SCORED',
            'score': {'strain': strain, 'average_heart_rate': hr, 'zone_durations': zones or {}}}


class SportCostTest(unittest.TestCase):
    def build(self):
        wo, rec = [], {}
        for i in range(90):
            sport, hr, r = [('weightlifting', 95, 65), ('tennis', 125, 50), ('soccer', 150, 40)][i % 3]
            wo.append(workout(i, sport, hr + (i % 5)))
            rec[(datetime(2026, 1, 2) + timedelta(days=i)).date().isoformat()] = r + (i % 7)
        return bd.build_sport_recovery_cost(wo, rec)

    def test_groups_by_own_heart_rate_thirds(self):
        out = self.build()
        self.assertEqual([g['intensity'] for g in out['groups']], ['lower', 'moderate', 'higher'])
        self.assertEqual([[s['sport'] for s in g['sports']] for g in out['groups']],
                         [['Weightlifting'], ['Tennis'], ['Soccer']])
        self.assertGreater(out['groups'][0]['avg_next_recovery'], out['groups'][2]['avg_next_recovery'])

    def test_sport_compared_within_its_group(self):
        for g in self.build()['groups']:
            for s in g['sports']:
                self.assertAlmostEqual(s['delta'], round(s['avg_next_recovery'] - g['avg_next_recovery'], 1), places=1)

    def test_too_little_history_gives_no_groups(self):
        out = bd.build_sport_recovery_cost([workout(0, 'tennis', 130)], {'2026-01-02': 50})
        self.assertEqual(out['groups'], [])

    def test_sparse_sport_in_a_group_is_hidden(self):
        for g in self.build()['groups']:
            self.assertTrue(all(s['n'] >= bd.SPORT_COST_MIN_SESSIONS for s in g['sports']))


class ZoneSplitTest(unittest.TestCase):
    def test_strength_sessions_are_left_out(self):
        z = {'zone_zero_milli': 3600000}
        hard = {'zone_five_milli': 3600000}
        now = datetime(2026, 1, 10, tzinfo=timezone.utc)
        out = bd.build_zone_distribution([workout(0, 'weightlifting', 95, zones=z), workout(1, 'soccer', 150, zones=hard)], now)
        self.assertEqual(out['all_time']['hard_pct'], 100)


class RestDayTest(unittest.TestCase):
    def test_days_since_counts_calendar_days_and_never_today(self):
        summary = bd.build_summary(generate(60))
        rest = summary['rest_day_stat']
        today = datetime.fromisoformat(summary['today_snapshot']['date']).date()
        self.assertEqual(rest['days_since'], (today - datetime.fromisoformat(rest['last_rest_date']).date()).days)
        self.assertGreaterEqual(rest['days_since'], 1)

    def test_training_mix_merges_weightlifting_labels(self):
        summary = bd.build_summary(generate(60))
        names = [n for n, _ in summary['sports']]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(sum(n for _, n in summary['sports']), summary['total_workouts'])


if __name__ == '__main__':
    unittest.main()
