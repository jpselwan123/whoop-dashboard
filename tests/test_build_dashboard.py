import json, os, unittest
from helpers import make_data_dir, generate, build_dashboard


class BuildDashboardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = make_data_dir()
        with open(os.path.join(cls.dir, "dashboard_data.json")) as f:
            cls.summary = json.load(f)

    def test_writes_all_outputs(self):
        for name in ("dashboard_data.json", "index.html"):
            self.assertTrue(os.path.getsize(os.path.join(self.dir, name)) > 0, name)

    def test_template_placeholder_replaced(self):
        with open(os.path.join(self.dir, "index.html")) as f:
            html = f.read()
        self.assertNotIn("__DATA__", html)
        self.assertIn('"asOf"', html)

    def test_core_fields_present(self):
        for key in ("latest", "avg30", "full_series", "acwr", "monotony", "readiness", "readiness_check",
                    "sport_recovery_cost", "rest_day_stat", "today_snapshot", "records"):
            self.assertIn(key, self.summary)

    def test_values_in_valid_ranges(self):
        for p in self.summary["full_series"]["recovery"]:
            self.assertTrue(0 <= p["v"] <= 100)
        for p in self.summary["full_series"]["strain"]:
            self.assertTrue(0 <= p["v"] <= 21)
        for p in self.summary["acwr"]:
            self.assertGreater(p["v"], 0)

    def test_no_workouts_does_not_crash(self):
        raw = generate(60)
        raw["workouts"] = []
        data = build_dashboard.build_summary(raw)
        self.assertEqual(data["total_workouts"], 0)

    def test_empty_account_gives_clear_error(self):
        raw = generate(10)
        raw["recovery"], raw["sleep"] = [], []
        with self.assertRaises(RuntimeError):
            build_dashboard.build_summary(raw)

    def test_missing_optional_vitals(self):
        raw = generate(60)
        for r in raw["recovery"]:
            r["score"].pop("spo2_percentage", None)
        for s in raw["sleep"]:
            s["score"].pop("respiratory_rate", None)
        build_dashboard.build_summary(raw)  # must not raise


if __name__ == "__main__":
    unittest.main()
