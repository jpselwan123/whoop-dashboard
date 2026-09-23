"""The "what the score would have been" slider: the same formula with one input replaced.

Two halves are tested. `build_what_if` assembles the numbers the page needs, and the page's own
`whatIfScore` re-evaluates the score from them — so the JavaScript is run for real with macOS's
JavaScriptCore, as the headline sentence is. CI has no jsc, so that half skips there.

The property that matters is that this is not a second model: fed the night that actually happened,
it must return the score the dashboard displays, to the point.
"""
import json, os, re, subprocess, unittest

from helpers import build_dashboard as bd, make_data_dir

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JSC = "/System/Library/Frameworks/JavaScriptCore.framework/Versions/Current/Helpers/jsc"
TEMPLATE = os.path.join(ROOT, "dashboard_template.html")


def grab(name, src):
    m = re.search(r"^function %s\(.*?^\}" % name, src, re.M | re.S)
    if not m:
        raise AssertionError("%s not found in the template" % name)
    return m.group(0)


def js_score(what_if, hours):
    """Run the page's own recompute, exactly as the slider does."""
    src = open(TEMPLATE).read()
    js = "%s\n%s\nprint(whatIfScore(%s, %r));" % (
        grab("normalPercentile", src), grab("whatIfScore", src), json.dumps(what_if), hours)
    return int(subprocess.run([JSC, "-e", js], capture_output=True, text=True, check=True).stdout.strip())


def python_score(w, hours):
    """The same arithmetic in Python — the reference the page has to match."""
    z = (hours - w['night_mean']) / w['night_sd']
    composite = (sum(w['fixed_z']) + z) / (len(w['fixed_z']) + 1)
    return max(1, min(99, round(bd.normal_percentile((composite - w['composite_mean']) / w['composite_sd']))))


def built(days=200):
    d = make_data_dir(days=days)
    with open(os.path.join(d, 'dashboard_data.json')) as fh:
        return json.load(fh)['readiness']


class WhatIfPayloadTest(unittest.TestCase):
    def setUp(self):
        self.readiness = built()
        self.w = self.readiness.get('what_if')

    def test_the_actual_night_reproduces_the_displayed_score(self):
        """If the slider disagreed with the orb at today's own value, it would be a second model."""
        self.assertIsNotNone(self.w)
        self.assertEqual(python_score(self.w, self.w['actual']), self.readiness['score'])

    def test_more_sleep_never_lowers_the_score(self):
        w = self.w
        step, prev = 0.1, None
        h = w['min']
        while h <= w['max'] + 1e-9:
            score = python_score(w, h)
            if prev is not None:
                self.assertGreaterEqual(score, prev, 'score fell at %.1f h' % h)
            prev = score
            h += step

    def test_the_range_is_this_persons_own_nights(self):
        w = self.w
        self.assertLess(w['min'], w['max'])
        self.assertLessEqual(w['min'], w['actual'])
        self.assertGreaterEqual(w['max'], w['actual'])
        self.assertEqual(w['window_days'], bd.WHAT_IF_WINDOW_DAYS)

    def test_only_last_night_moves(self):
        """The five other standard scores are fixed: the 7-day window stops before today."""
        self.assertEqual(len(self.w['fixed_z']), 5)

    def test_missing_last_night_gives_no_slider(self):
        """A night without sleep data can't be varied — the page must skip the whole block."""
        measured = ({'z': 0.1}, {'z': 0.2}, {'z': 0.3}, [{'z': 0.4}, {'z': 0.5}, None])
        self.assertIsNone(bd.build_what_if(measured, (50, 0.0, 0.0, 1.0), {'2026-01-01': 8.0}, '2026-01-01'))

    def test_a_flat_baseline_gives_no_slider(self):
        """Zero spread would divide by zero rather than mean 'no change'."""
        night = {'value': 8.0, 'z': 0.0, 'mean': 8.0, 'sd': 0.0, 'sign': 1}
        measured = ({'z': 0.1}, {'z': 0.2}, {'z': 0.3}, [{'z': 0.4}, {'z': 0.5}, night])
        self.assertIsNone(bd.build_what_if(measured, (50, 0.0, 0.0, 1.0), {'2026-01-01': 8.0}, '2026-01-01'))


@unittest.skipUnless(os.path.exists(JSC), "needs JavaScriptCore (macOS)")
class WhatIfInThePageTest(unittest.TestCase):
    def test_the_page_matches_python_across_the_whole_slider(self):
        w = built().get('what_if')
        self.assertIsNotNone(w)
        for h in (w['min'], w['actual'], (w['min'] + w['max']) / 2, w['max']):
            self.assertEqual(js_score(w, h), python_score(w, h), 'differs at %.2f h' % h)

    def test_the_pages_normal_curve_matches_pythons(self):
        src = open(TEMPLATE).read()
        js = "%s\n%s" % (grab("normalPercentile", src),
                         "print([-2.5,-1.5,-0.5,0,0.5,1.5,2.5].map(normalPercentile).join(','))")
        got = subprocess.run([JSC, "-e", js], capture_output=True, text=True, check=True).stdout.strip()
        for z, v in zip((-2.5, -1.5, -0.5, 0, 0.5, 1.5, 2.5), (float(x) for x in got.split(','))):
            self.assertAlmostEqual(v, bd.normal_percentile(z), places=4)


if __name__ == '__main__':
    unittest.main()
