"""README screenshots must match the page they claim to show.

They are taken from the synthetic athlete and cropped by section, so any change to the sections — a
heading, a subtitle, the order — makes them stale. The layout they were taken from is recorded next to
them; if the template has moved on, regenerate the screenshots (the readme-screenshots skill) and
record the layout again with `python3 scripts/screenshot_layout.py --write`.
"""
import os, sys, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import screenshot_layout as sl     # noqa: E402


class ScreenshotsTest(unittest.TestCase):
    def test_the_screenshots_were_taken_from_this_layout(self):
        self.assertEqual(sl.recorded(), sl.fingerprint(sl.current()),
                         'the page layout changed since the README screenshots were taken — regenerate them, '
                         'then run: python3 scripts/screenshot_layout.py --write')

    def test_every_screenshot_the_readme_shows_exists(self):
        import re
        readme = open(os.path.join(ROOT, 'README.md')).read()
        for path in re.findall(r'src="(docs/screenshots/[^"]+)"', readme):
            self.assertTrue(os.path.exists(os.path.join(ROOT, path)), path)


if __name__ == '__main__':
    unittest.main()
