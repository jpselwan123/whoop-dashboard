"""The one sentence on the daily card, evaluated for real.

The sentence lives in the template's JavaScript, so it is run here with macOS's JavaScriptCore
(`jsc`) on synthetic inputs. CI has no jsc, so the test skips there and runs locally.
"""
import json, os, re, subprocess, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JSC = "/System/Library/Frameworks/JavaScriptCore.framework/Versions/Current/Helpers/jsc"
TEMPLATE = os.path.join(ROOT, "dashboard_template.html")


def grab(name, src):
    """The named function's source, from `function name(` to its closing brace at column 0."""
    m = re.search(r"^function %s\(.*?^\}" % name, src, re.M | re.S)
    if not m:
        raise AssertionError("%s not found in the template" % name)
    return m.group(0)


def marker(state):
    return {"value": 1, "normal": [0, 2], "state": state}


def sentence(score, night_state, hrv="within", rhr="within", sleep="within"):
    src = open(TEMPLATE).read()
    helpers = """
      const MARKER_NAME = {hrv:'HRV', rhr:'resting HR', sleep:'sleep'};
      const listAnd = arr => arr.length > 1 ? arr.slice(0,-1).join(', ') + ' and ' + arr[arr.length-1] : (arr[0] || '');
      const markerWorse = (key, m) => m && m.state === (key === 'rhr' ? 'above' : 'below');
    """
    calc = {"R": {"score": score, "lines": {"above": 69, "train": 31, "rest": 7},
                  "hrv": marker(hrv), "rhr": marker(rhr), "sleep": marker(sleep),
                  "last_night": None if night_state is None else {"state": night_state}}}
    js = "%s\n%s\nprint(scoreText(%s));" % (helpers, grab("scoreText", src), json.dumps(calc))
    return subprocess.run([JSC, "-e", js], capture_output=True, text=True, check=True).stdout.strip()


@unittest.skipUnless(os.path.exists(JSC), "needs JavaScriptCore (macOS)")
class HeadlineTest(unittest.TestCase):
    def test_good_night_with_a_low_score_names_both_halves(self):
        """The confusing case: last night was fine, the week is what is holding the score down."""
        out = sentence(24, "above")
        self.assertIn("last night was above your normal", out)
        self.assertIn("last 7 days pull it down", out)

    def test_low_night_with_a_normal_week_still_says_so(self):
        out = sentence(33, "below")
        self.assertIn("last 7 days are all within your normal", out)
        self.assertIn("last night was below your normal", out)

    def test_a_good_night_inside_the_band_is_not_called_a_drag(self):
        out = sentence(55, "above")
        self.assertNotIn("pull it down", out)

    def test_everything_normal_says_nothing_else(self):
        self.assertEqual(sentence(50, "within"), "readiness 50, everything within your normal range")

    def test_measures_above_normal_are_named(self):
        out = sentence(75, "above", hrv="above")
        self.assertIn("7-day HRV", out)
        self.assertIn("last night", out)


if __name__ == "__main__":
    unittest.main()
