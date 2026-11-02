"""Slot for real Strategy Tester reports. Skipped until those files exist."""
from __future__ import annotations

import unittest
from pathlib import Path

REAL_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "goldthinker_factory" / "real_mt5_reports"
SKIP = (
    "blocked on real MT5 Strategy Tester output: place English .htm reports in "
    "tests/fixtures/goldthinker_factory/real_mt5_reports/ and remove this skip"
)


class RealReportSlotTests(unittest.TestCase):
    def test_real_report_directory_has_no_reports_yet(self):
        names = sorted(path.name for path in REAL_DIR.iterdir())
        self.assertEqual(names, ["README.md"])

    @unittest.skip(SKIP)
    def test_real_mt5_reports_extract_and_crosscheck(self):
        self.fail("real reports were added; implement admission checks before removing the skip")


if __name__ == "__main__":
    unittest.main()
