"""MT5 config generation has zero live or tester side effects."""
import tempfile
import unittest
from pathlib import Path

from scripts.goldthinker_factory.mt5_job_generator import build_configs


def kwargs(root):
    return {
        "system_id": "GT_TEST01",
        "expert": "Factory\\DemoStrategy",
        "symbol": "XAUUSD",
        "period": "M15",
        "as_of": "2026-11-02",
        "deposit": "10000.00",
        "leverage": 100,
        "output_dir": root,
        "preset": "DemoStrategy.set",
    }


class JobGeneratorTests(unittest.TestCase):
    def test_six_calendar_configs_use_real_ticks_local_only_and_stay_unexecuted(self):
        with tempfile.TemporaryDirectory() as path:
            root = Path(path)
            receipt = build_configs(**kwargs(root))
            self.assertEqual([j["year"] for j in receipt["jobs"]], list(range(2021, 2027)))
            self.assertEqual(receipt["run_status"], "CONFIGS_ONLY")
            for job in receipt["jobs"]:
                file = (root / job["ini"]).read_text(encoding="ascii")
                self.assertIn("Model=4", file)
                self.assertIn("Optimization=0", file)
                self.assertIn("UseCloud=0", file)
                self.assertIn("UseRemote=0", file)
                self.assertIn("AllowLiveTrading=0", file)
                self.assertIn("ShutdownTerminal=1", file)
                self.assertIn("ExpertParameters=DemoStrategy.set", file)
                self.assertFalse(job["tick_coverage_verified"])
                self.assertFalse(job["tester_account_verified"])
            self.assertIn("ToDate=2026.11.02",
                          (root / receipt["jobs"][-1]["ini"]).read_text())
            self.assertEqual(receipt["jobs"][-1]["period_label"], "PARTIAL_2026_YTD")
            self.assertTrue((root / "manifest.json").is_file())

    def test_no_overwrite_or_duplicate_job(self):
        with tempfile.TemporaryDirectory() as path:
            build_configs(**kwargs(Path(path)))
            with self.assertRaisesRegex(ValueError, "refusing overwrite"):
                build_configs(**kwargs(Path(path)))

    def test_invalid_ea_path_cannot_escape_terminal(self):
        with tempfile.TemporaryDirectory() as path:
            args = kwargs(Path(path))
            args["expert"] = "..\\..\\BadEA"
            with self.assertRaisesRegex(ValueError, "unsafe"):
                build_configs(**args)

    def test_injection_cannot_be_written_to_ini(self):
        with tempfile.TemporaryDirectory() as path:
            args = kwargs(Path(path))
            args["symbol"] = "XAUUSD\\nAllowLiveTrading=1"
            with self.assertRaisesRegex(ValueError, "unsafe"):
                build_configs(**args)
            self.assertFalse((Path(path) / "manifest.json").exists())

    def test_no_unattended_account_credentials_in_job(self):
        with tempfile.TemporaryDirectory() as path:
            data = build_configs(**kwargs(Path(path)))
            self.assertFalse(data["broker_account_credentials_in_manifest"])
            text = (Path(path) / data["jobs"][0]["ini"]).read_text()
            self.assertNotIn("Password=", text)
            self.assertNotIn("Login=", text)
            self.assertNotIn("Server=", text)

    def test_2027_is_not_silently_claimed_as_pilot_end(self):
        with tempfile.TemporaryDirectory() as path:
            args = kwargs(Path(path))
            args["as_of"] = "2027-01-01"
            with self.assertRaisesRegex(ValueError, "within 2026"):
                build_configs(**args)


if __name__ == "__main__":
    unittest.main()
