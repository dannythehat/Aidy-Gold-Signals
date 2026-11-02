"""Offline contract acceptance: no brokers, live accounts or performance assertions."""
from __future__ import annotations

import copy
import unittest

from aidy.goldthinker_factory_contract import (
    FactoryContractError,
    digest,
    select_best_completed_year,
    validate_mt5_bundle,
)


def bundle() -> dict:
    rows = []
    for year, net in zip(range(2021, 2026), ("4.00", "-12.00", "42.00", "42.00", "3.00")):
        rows.append({
            "year": year, "coverage": "VERIFIED", "test_status": "COMPLETED",
            "net_profit_usd": net, "closed_trades": 20,
            "max_equity_drawdown_pct": "6.2",
            "report_sha256": "b" * 64, "ledger_sha256": "c" * 64,
        })
    rows.append({
        "year": 2026, "coverage": "INCOMPLETE", "test_status": "PARTIAL",
        "net_profit_usd": None, "closed_trades": None,
        "max_equity_drawdown_pct": None,
        "report_sha256": None, "ledger_sha256": None,
    })
    return {
        "schema": "goldthinker.factory.mt5_bundle.v1",
        "source_kind": "SYNTHETIC_FIXTURE",
        "system_id": "GT_TEST01", "family_id": "S016",
        "strategy_version_sha256": "a" * 64, "ea_sha256": "d" * 64,
        "broker_profile_sha256": "e" * 64, "test_config_sha256": "f" * 64,
        "data_manifest_sha256": "1" * 64, "tester_build": "FIXTURE_NOT_MT5",
        "as_of_utc": "2026-11-02T06:00:00Z", "account_currency": "USD",
        "results": rows,
    }


class FactoryContractTests(unittest.TestCase):
    def test_select_best_completed_profitable_year_only(self):
        p = bundle()
        r = select_best_completed_year(p)
        self.assertEqual(r["aidy_year"], 2023)  # first earlier year on tie
        self.assertEqual(r["aidy_expected_net_usd"], "42.00")
        self.assertEqual(r["selection_status"], "RESEARCH_FIXTURE_ONLY")
        self.assertEqual(r["mt5_bundle_sha256"], digest(p))
        for field in (
            "historical_edge_verified", "real_mt5_evidence_authenticated",
            "paper_authorised", "cent_authorised", "live_authorised",
            "public_performance_publication_authorised",
        ):
            self.assertFalse(r[field])

    def test_stable_output_and_not_mutating_source(self):
        p = bundle()
        original = copy.deepcopy(p)
        self.assertEqual(select_best_completed_year(p), select_best_completed_year(p))
        self.assertEqual(p, original)

    def test_all_completed_years_are_required(self):
        p = bundle()
        p["results"][2] = {
            "year": 2023, "coverage": "MISSING", "test_status": "BLOCKED",
            "net_profit_usd": None, "closed_trades": None,
            "max_equity_drawdown_pct": None, "report_sha256": None,
            "ledger_sha256": None,
        }
        result = select_best_completed_year(p)
        self.assertEqual(result["selection_status"], "RESEARCH_FIXTURE_ONLY")
        self.assertIsNone(result["aidy_year"])

    def test_no_positive_completed_year(self):
        p = bundle()
        for row in p["results"][:5]:
            row["net_profit_usd"] = "-5.00"
        self.assertIsNone(select_best_completed_year(p)["aidy_year"])

    def test_real_kind_does_not_authenticate_itself(self):
        p = bundle()
        p["source_kind"] = "REAL_MT5_TESTER"
        result = select_best_completed_year(p)
        self.assertEqual(result["selection_status"], "SELECTED_PENDING_INDEPENDENT_EVIDENCE")
        self.assertFalse(result["real_mt5_evidence_authenticated"])

    def test_missing_2021_to_2026_row(self):
        p = bundle()
        p["results"].pop()
        with self.assertRaises(FactoryContractError):
            validate_mt5_bundle(p)

    def test_duplicate_year(self):
        p = bundle()
        p["results"][1]["year"] = 2021
        with self.assertRaises(FactoryContractError):
            validate_mt5_bundle(p)

    def test_partial_2026_must_not_pretend_completed(self):
        p = bundle()
        p["results"][-1]["coverage"] = "VERIFIED"
        p["results"][-1]["test_status"] = "COMPLETED"
        p["results"][-1]["net_profit_usd"] = "999999.00"
        p["results"][-1]["closed_trades"] = 1
        p["results"][-1]["max_equity_drawdown_pct"] = "1.00"
        p["results"][-1]["report_sha256"] = "2" * 64
        p["results"][-1]["ledger_sha256"] = "3" * 64
        with self.assertRaises(FactoryContractError):
            validate_mt5_bundle(p)

    def test_blocked_year_never_claims_profit(self):
        p = bundle()
        p["results"][1]["coverage"] = "MISSING"
        p["results"][1]["test_status"] = "BLOCKED"
        with self.assertRaises(FactoryContractError):
            validate_mt5_bundle(p)

    def test_malformed_sha(self):
        p = bundle()
        p["ea_sha256"] = "not-a-digest"
        with self.assertRaises(FactoryContractError):
            validate_mt5_bundle(p)

    def test_unknown_field_is_rejected(self):
        p = bundle()
        p["strategy_is_profitable"] = True
        with self.assertRaises(FactoryContractError):
            validate_mt5_bundle(p)

    def test_no_floating_point_finance(self):
        p = bundle()
        p["results"][0]["net_profit_usd"] = 99.4
        with self.assertRaises(FactoryContractError):
            validate_mt5_bundle(p)

    def test_invalid_utc(self):
        p = bundle()
        p["as_of_utc"] = "2026-11-02T06:00:00+02:00"
        with self.assertRaises(FactoryContractError):
            validate_mt5_bundle(p)

    def test_drawdown_outside_range(self):
        p = bundle()
        p["results"][0]["max_equity_drawdown_pct"] = "101.00"
        with self.assertRaises(FactoryContractError):
            validate_mt5_bundle(p)


if __name__ == "__main__":
    unittest.main()
