"""The first-run page: written only when there is nothing to show, never over a working dashboard."""
import json, os, shutil, subprocess, tempfile, unittest
from helpers import ROOT, generate, build_dashboard
import setup_page

SETUP_MARK = "Let's connect your WHOOP."


def _read(path):
    with open(path) as f:
        return f.read()


def _next_step(html):
    """The title of the step marked as next."""
    start = html.index('<li class="step next">')
    h2 = html.index('<h2>', start) + 4
    return html[h2:html.index(' <span class="tag">', h2)]


class ChecklistTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="whoop-setup-")
        self.env = os.path.join(self.dir, ".env")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _touch(self, name, text="{}"):
        with open(os.path.join(self.dir, name), "w") as f:
            f.write(text)

    def test_fresh_folder_starts_at_the_developer_app(self):
        self.assertEqual(_next_step(setup_page.render(self.dir, self.env)), "Create a WHOOP developer app")

    def test_an_empty_env_file_is_not_counted_as_done(self):
        self._touch(".env", "WHOOP_CLIENT_ID=\nWHOOP_CLIENT_SECRET=\n")
        self.assertEqual(_next_step(setup_page.render(self.dir, self.env)), "Create a WHOOP developer app")

    def test_credentials_set_moves_on_to_approval(self):
        self._touch(".env", "WHOOP_CLIENT_ID=id-value-123\nWHOOP_CLIENT_SECRET='s3cret-value'\n")
        html = setup_page.render(self.dir, self.env)
        self.assertEqual(_next_step(html), "Approve access once")
        self.assertNotIn("s3cret-value", html)          # values are only checked, never shown
        self.assertNotIn("id-value-123", html)

    def test_tokens_present_moves_on_to_the_first_pull(self):
        self._touch(".env", "WHOOP_CLIENT_ID=a\nWHOOP_CLIENT_SECRET=b\n")
        self._touch("whoop_tokens.json")
        self.assertEqual(_next_step(setup_page.render(self.dir, self.env)), "Pull your history")

    def test_data_pulled_but_unscored_asks_for_a_night(self):
        self._touch(".env", "WHOOP_CLIENT_ID=a\nWHOOP_CLIENT_SECRET=b\n")
        self._touch("whoop_tokens.json")
        self._touch("whoop_data.json")
        html = setup_page.render(self.dir, self.env)
        self.assertEqual(_next_step(html), "Wear it for a night")
        self.assertNotIn("Pull your history", html)

    def test_page_always_offers_the_demo(self):
        self.assertIn("generate_demo_data.py demo", setup_page.render(self.dir, self.env))


class BuildWritesSetupPageTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="whoop-setup-")
        self.page = os.path.join(self.dir, "index.html")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_no_data_file_writes_the_setup_page_and_still_fails(self):
        with self.assertRaises(SystemExit):
            build_dashboard.main(self.dir)
        self.assertIn(SETUP_MARK, _read(self.page))

    def test_no_scored_data_writes_the_setup_page_and_still_fails(self):
        raw = generate(10)
        raw["recovery"], raw["sleep"] = [], []
        with open(os.path.join(self.dir, "whoop_data.json"), "w") as f:
            json.dump(raw, f)
        with self.assertRaises(RuntimeError):
            build_dashboard.main(self.dir)
        self.assertIn(SETUP_MARK, _read(self.page))

    def test_real_data_builds_the_dashboard_not_the_setup_page(self):
        with open(os.path.join(self.dir, "whoop_data.json"), "w") as f:
            json.dump(generate(60), f)
        build_dashboard.main(self.dir)
        html = _read(self.page)
        self.assertNotIn(SETUP_MARK, html)
        self.assertIn('id="heroCard"', html)


@unittest.skipUnless(shutil.which("bash"), "needs bash")
class RefreshScriptTest(unittest.TestCase):
    """refresh.sh with a failing pull: a first run gets the setup page; a returning user keeps their page."""
    FILES = ("refresh.sh", "whoop.py", "build_dashboard.py", "setup_page.py", "env_config.py",
             "dashboard_template.html")

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="whoop-refresh-")
        for name in self.FILES:
            shutil.copy2(os.path.join(ROOT, name), self.dir)
        self.page = os.path.join(self.dir, "index.html")
        # no .env in the copy, and none inherited: whoop.py stops before any network call
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(("WHOOP_", "PYTHON"))}

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _refresh(self):
        return subprocess.run(["bash", os.path.join(self.dir, "refresh.sh")], env=self.env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)

    def test_first_run_without_setup_shows_the_steps(self):
        result = self._refresh()
        self.assertNotEqual(result.returncode, 0)
        html = _read(self.page)
        self.assertIn(SETUP_MARK, html)
        self.assertEqual(_next_step(html), "Create a WHOOP developer app")

    def test_failed_pull_leaves_an_existing_dashboard_alone(self):
        with open(os.path.join(self.dir, "whoop_data.json"), "w") as f:
            f.write("{}")
        with open(self.page, "w") as f:
            f.write("the dashboard from the last good pull")
        result = self._refresh()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(_read(self.page), "the dashboard from the last good pull")


if __name__ == "__main__":
    unittest.main()
