import os, unittest
from unittest import mock
from helpers import make_data_dir
import ai_context


class AiContextTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        d = make_data_dir(days=90)
        with mock.patch.object(ai_context, "RAW_FILE", os.path.join(d, "whoop_data.json")), \
             mock.patch.object(ai_context, "DASH_FILE", os.path.join(d, "dashboard_data.json")):
            cls.text = ai_context.build_context_text()

    def test_has_all_tables(self):
        for header in ("## days", "## sleeps", "## workouts", "## dashboard_summaries"):
            self.assertIn(header, self.text)

    def test_one_row_per_day(self):
        section = self.text.split("## days")[1].split("## sleeps")[0]
        rows = [l for l in section.strip().splitlines()[2:] if l]
        self.assertEqual(len(rows), 90)

    def test_never_includes_identifying_fields(self):
        for secret in ("alex@example.com", "Demo", "user_id", '"id"', "cycle_id", "sleep_id"):
            self.assertNotIn(secret, self.text)
        self.assertIn("Alex", self.text)  # first name only

    def test_stays_compact(self):
        # ~4 chars/token; must stay far below the 272K-token long-context price tier
        self.assertLess(len(self.text) / 4, 150_000)


if __name__ == "__main__":
    unittest.main()
