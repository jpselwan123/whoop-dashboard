"""The documentation must quote the numbers the code actually produces.

Twice now a figure pasted into the README or a docstring has outlived the code it described: a
"+0.5 SD = 69" band that had been deleted, and band shares from a four-state plan that no longer
existed. Prose cannot be trusted to age well, so the figures that follow from the code's own
constants are checked here on every test run.

Only constant-derived figures are asserted. The band lines and the share of days a normal curve
puts either side of them depend on READY_SWC / READY_REST_SD alone, so they need no data of any
kind and a mismatch is always a documentation bug. Figures measured on a real history (observed
band shares, day counts, spreads) move as days are added — `scripts/check_doc_stats.py` recomputes
those on demand, and this file only checks that the script itself still runs.
"""
import io, contextlib, os, sys, unittest
from datetime import date, timedelta

from helpers import build_dashboard as bd, make_data_dir

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scripts'))
import check_doc_stats as cds     # noqa: E402


class DocumentedConstantsTest(unittest.TestCase):
    def test_docs_quote_the_current_band_lines_and_target_shares(self):
        """The README and the source must say what READY_LINES currently is."""
        self.assertEqual(cds.check_constant_docs(), [])

    def test_the_check_notices_when_a_line_moves(self):
        """Guard against a check that passes because it is looking for nothing."""
        original = dict(bd.READY_LINES)
        bd.READY_LINES['train'] = original['train'] + 1
        try:
            problems = cds.check_constant_docs()
        finally:
            bd.READY_LINES.update(original)
        self.assertTrue(problems, 'moving a band line should make the documentation stale')

    def test_target_shares_follow_from_the_sd_lines(self):
        f = cds.constant_facts()
        self.assertEqual(f['train_line'], round(bd.normal_percentile(-bd.READY_SWC)))
        self.assertEqual(f['rest_line'], round(bd.normal_percentile(-bd.READY_REST_SD)))
        self.assertAlmostEqual(f['target_plan'] + f['target_easy'] + f['target_rest'], 100.0, places=6)


class FixTest(unittest.TestCase):
    """--fix rewrites a stale figure in place, and never guesses."""

    def root(self, text):
        import tempfile
        d = tempfile.mkdtemp()
        with open(os.path.join(d, 'README.md'), 'w') as f:
            f.write(text)
        return d

    def read(self, d):
        return open(os.path.join(d, 'README.md')).read()

    def test_a_stale_figure_is_replaced_in_place(self):
        d = self.root('Intro.\nOver 530 days the bands caught 66.6% / 27.2% / 6.2% of days, as measured.\n')
        fresh = 'Over 531 days the bands caught 66.7% / 27.1% / 6.2% of days'
        left = cds.fix([cds.Stale('README.md', fresh, 'band shares')], d)
        self.assertEqual(left, [])
        self.assertEqual(self.read(d), 'Intro.\n%s, as measured.\n' % fresh)

    def test_signs_and_number_words_are_figures_too(self):
        d = self.root('On this history **one of five** survives; a cost of \u22120.041 per point.\n')
        cds.fix([cds.Stale('README.md', 'On this history **none of five** survives', 'survivors'),
                 cds.Stale('README.md', 'a cost of +0.012 per point', 'cost')], d)
        self.assertEqual(self.read(d), 'On this history **none of five** survives; a cost of +0.012 per point.\n')

    def test_a_reworded_sentence_is_left_for_a_person(self):
        d = self.root('Over 530 days the bands landed on 66.6% / 27.2% / 6.2% of days.\n')
        before = self.read(d)
        left = cds.fix([cds.Stale('README.md', 'Over 531 days the bands caught 66.7% / 27.1% / 6.2% of days', 'x')], d)
        self.assertEqual(len(left), 1)
        self.assertEqual(self.read(d), before)

    def test_an_ambiguous_match_is_never_guessed(self):
        d = self.root('rest on **21** days.\nrest on **22** days.\n')
        before = self.read(d)
        self.assertEqual(len(cds.fix([cds.Stale('README.md', 'rest on **23** days', 'x')], d)), 1)
        self.assertEqual(self.read(d), before)

    def test_a_finding_still_reads_as_one_line(self):
        st = cds.Stale('README.md', 'some text', 'what it is')
        self.assertEqual(st, "README.md no longer says 'some text' (what it is)")

class MeasuredFiguresTest(unittest.TestCase):
    def test_the_measuring_script_runs_on_synthetic_data(self):
        """The script is how a real history is re-measured — it must survive a full run."""
        d = make_data_dir(days=200)
        with contextlib.redirect_stdout(io.StringIO()):
            facts = cds.measured_facts(d)
        self.assertEqual(facts['cycles'], facts['distinct_days'] + facts['key_collisions'])
        self.assertAlmostEqual(sum(facts['band_shares'].values()), 100.0, delta=0.3)
        self.assertAlmostEqual(sum(facts['answer_shares'].values()), 100.0, delta=0.3)
        self.assertGreater(facts['scored_days'], 0)
        self.assertLessEqual(facts['effective_n'], facts['scored_days'])

    def test_both_rest_rules_are_judged_on_the_same_day(self):
        """The comparison is meaningless if one rule looks at today and the other at yesterday.

        Today's HRV is known each morning, so Kiviniemi's two drops end today, exactly as the
        implemented run of low days includes today. An earlier version compared a run ending today
        against drops ending yesterday, which inflated the disagreement.
        """
        series = [{'date': (date(2026, 1, 1) + timedelta(days=i)).isoformat(), 'v': 50}
                  for i in range(40)]
        falling = {p['date']: 4.0 - i * 0.01 for i, p in enumerate(series)}   # HRV drops every day
        out = cds._rest_rules(series, falling)
        # every day with two prior readings qualifies under the literal rule, today included
        self.assertEqual(out['kiviniemi_literal_fires'], len(series) - 2)
        self.assertEqual(out['days'], len(series))
        # and with no day below the band, the implemented rule fires on none of them
        self.assertEqual(out['implemented_fires'], 0)
        self.assertEqual(out['disagree_days'], out['kiviniemi_literal_fires'])

    def test_variance_shares_account_for_the_whole_score(self):
        """Equal weights are not equal shares — but the six shares still have to add up."""
        d = make_data_dir(days=200)
        with contextlib.redirect_stdout(io.StringIO()):
            shares = cds.measured_facts(d)['variance_shares']
        if shares is None:
            self.skipTest('not enough days with all six inputs')
        self.assertAlmostEqual(shares['trend_total'] + shares['night_total'], 100.0, delta=0.3)


if __name__ == '__main__':
    unittest.main()
