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


class DurationFormatTest(unittest.TestCase):
    def test_hours_minutes_not_decimal(self):
        import ai_context
        self.assertEqual(ai_context._h(2.44 * 3600000), "2:26")
        self.assertEqual(ai_context._h(0), "0:00")
        self.assertEqual(ai_context._h(None), "")

    def test_stage_minutes_match_whoop_app(self):
        import ai_context
        m = lambda x: x * 60000
        stages = {"total_light_sleep_time_milli": m(91.55167), "total_slow_wave_sleep_time_milli": m(146.64617),
                  "total_rem_sleep_time_milli": m(126.1365), "total_awake_time_milli": m(28.78383),
                  "total_no_data_time_milli": 0}
        out = ai_context._stage_minutes(stages)
        # the WHOOP app showed light 1:32, deep 2:26, REM 2:06, awake 0:29 for this night
        self.assertEqual([out[k] for k in ("total_light_sleep_time_milli", "total_slow_wave_sleep_time_milli",
                                           "total_rem_sleep_time_milli", "total_awake_time_milli")], [92, 146, 126, 29])
        self.assertEqual(sum(out.values()), 393)               # 6:33 in bed

    def test_vs_needed(self):
        import ai_context
        stage = {"total_in_bed_time_milli": 6.55 * 3600000, "total_awake_time_milli": 0.48 * 3600000}
        need = {"baseline_milli": 7.88 * 3600000, "need_from_sleep_debt_milli": 2.13 * 3600000,
                "need_from_recent_strain_milli": 0.04 * 3600000, "need_from_recent_nap_milli": 0}
        self.assertEqual(ai_context._vs_needed(stage, need), "60")

    def test_prompt_asks_for_hours_and_minutes(self):
        import chat_server
        self.assertIn("never decimal hours", chat_server.SYSTEM_PROMPT.replace("\n", " "))

    def test_prompt_forbids_blaming_the_dashboard(self):
        """It once explained a figure it had misread as a "date/time or refresh mismatch"."""
        import chat_server
        prompt = chat_server.SYSTEM_PROMPT.replace("\n", " ")
        self.assertIn("Never explain a number by guessing at a bug", prompt)
        for word in ("refresh lag", "time-zone slip", "date mismatch"):
            self.assertIn(word, prompt)

    def test_prompt_defines_the_rest_day_card(self):
        """"Last day off" is the last day with no workout — the opposite of the last day trained."""
        import chat_server
        prompt = chat_server.SYSTEM_PROMPT.replace("\n", " ")
        self.assertIn("last day off", prompt)
        self.assertIn("It is not the last day they trained", prompt)



if __name__ == "__main__":
    unittest.main()
