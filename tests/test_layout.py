"""The tabbed layout must fail open: with no script, every view and every line of text still shows."""
import os, re, unittest
from helpers import ROOT

with open(os.path.join(ROOT, "dashboard_template.html"), encoding="utf-8") as f:
    HTML = f.read()
CSS = HTML[HTML.index("<style>"):HTML.index("</style>")]


class LayoutTest(unittest.TestCase):
    def test_every_tab_opens_a_view_and_every_view_has_a_tab(self):
        tabs = re.findall(r'<a href="#(\w+)" data-view="(\w+)">', HTML)
        self.assertTrue(tabs)
        for href, view in tabs:
            self.assertEqual(href, view)
            self.assertIn('<div class="view" id="%s" data-view="%s">' % (view, view), HTML)
        views = re.findall(r'<div class="view" id="(\w+)"', HTML)
        self.assertEqual(sorted(views), sorted(v for _, v in tabs))
        js_views = re.search(r"const VIEWS = \[([^\]]*)\]", HTML).group(1)
        self.assertEqual(sorted(re.findall(r"'(\w+)'", js_views)), sorted(views))

    def test_views_hide_only_once_the_script_has_taken_over(self):
        for rule in re.findall(r'([^{}]+)\{[^{}]*display:none', CSS):
            sel = rule.strip()
            if re.search(r'(^|\s)\.view\b', sel):
                self.assertTrue(sel.startswith('.views-on'), sel)

    def test_explanations_and_tip_details_hide_only_once_the_script_has_run(self):
        for rule in re.findall(r'([^{}]+)\{[^{}]*display:none', CSS):
            sel = rule.strip()
            if re.search(r'\.(section-sub|more|why)(?![\w-])', sel):
                self.assertTrue(sel.startswith('.compact'), sel)


if __name__ == "__main__":
    unittest.main()
