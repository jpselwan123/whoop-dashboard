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
