"""Immutable source-ledger tests for the independent PR370/371 comparison."""
import os
import tempfile
import unittest
from pathlib import Path

from gold_hunter_independent_cross_period_audit import audit, read_pinned


class EvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(os.environ.get("AIDY_EVIDENCE_DIR", "/mnt/data"))
        cls.paths = {}
        for pr in (370, 371):
            for year in (2025, 2026):
                zip_path = root / f"gold_hunter_pr{pr}_{year}_source_replay.zip"
                cls.paths[(pr, year)] = zip_path if zip_path.exists() else root / f"pr{pr}_{year}"
        if not all(p.exists() for p in cls.paths.values()):
            raise unittest.SkipTest("Original four AIDY artifacts not mounted; run via CLI with explicit files")
        cls.report = audit(cls.paths)

    def test_source_pins_and_original_five_unchanged(self):
        self.assertEqual(len(self.report["source_integrity"]), 4)
        self.assertTrue(all(v["exact_match"] for v in self.report["frozen_original_five_parity"].values()))
        self.assertTrue(all(v["matching_stress_case_ledgers"] == 9 for v in self.report["frozen_original_five_parity"].values()))

    def test_duplicate_alias_is_not_a_new_bot(self):
        self.assertEqual(len(self.report["verified_duplicate_aliases"]), 4)
        self.assertEqual(len(self.report["unique_hypothesis_ids"]), 10)
        self.assertNotIn("MEAN_REVERSION", self.report["unique_hypothesis_ids"])

    def test_cost_stress_negative_2026_is_preserved(self):
        m = self.report["candidate_results"]["ALL_TEN"]["stress"]
        self.assertEqual(m["2025"]["stress_net_usd"], 2164.93)
        self.assertEqual(m["2026"]["stress_net_usd"], -239.09)
        self.assertEqual(m["2026"]["months_observed"], 9)
        self.assertEqual(m["2026"]["months_over_10pct"], 0)

    def test_only_two_original_hypotheses_positive_in_both_periods(self):
        self.assertEqual(self.report["conclusions"]["positive_stress_both_observed_periods_individual_ids"], ["DONCHIAN_TREND", "PREV_DAY_BREAKOUT"])
        self.assertEqual(self.report["conclusions"]["historically_qualified"], 0)
        self.assertEqual(self.report["conclusions"]["new_order_count"], 0)

    def test_correlated_trend_methods_are_not_assumed_independent(self):
        for year in ("2025", "2026"):
            c = self.report["dependence"][year]["DONCHIAN_TREND__PREV_DAY_BREAKOUT"]
            self.assertGreater(c["monthly_realized_pnl_correlation"], .79)
            self.assertGreater(c["same_hour_same_side_signal_count"], 0)

    def test_tampered_report_fails_before_analysis(self):
        with tempfile.TemporaryDirectory() as root:
            p = Path(root) / "gold_hunter/open_lab_2025/report.json"
            p.parent.mkdir(parents=True)
            p.write_text('{"tampered": true}')
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                read_pinned(Path(root), 370, 2025)


if __name__ == "__main__":
    unittest.main()
