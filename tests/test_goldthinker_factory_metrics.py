"""v2 metrics are recomputed from the ledger. UNSET is not a pass."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from aidy.goldthinker_factory_contract import (
    FactoryContractError,
    select_best_completed_year,
    validate_mt5_bundle,
)
from aidy.goldthinker_factory_metrics import (
    attach_v2,
    load_thresholds,
    validate_mt5_bundle_v2,
    v1_view,
)
from aidy.goldthinker_factory_mt5_extract import build_annual_bundle
from tests.goldthinker_factory_synthetic_reports import synthetic_report_html
from tests.test_goldthinker_factory_extract import AS_OF_TEXT, EXTRAS, _end

ROOT = Path(__file__).resolve().parents[1]
THRESHOLDS = ROOT / "config/goldthinker_factory_thresholds.json"
COSTS = {
    "schema": "goldthinker.factory.broker_costs.v1",
    "symbol": "XAUUSD",
    "spread_price": "0.20",
    "contract_size": "100",
    "commission_usd_per_lot_round_turn": "10.00",
    "cost_basis": "QUOTED_INPUT_NOT_BROKER_ATTESTED",
}


def _bundle_and_ledgers(root: Path):
    reports = {}
    for year, extra in EXTRAS.items():
        raw = synthetic_report_html(year, end=_end(year), extra_last_profit=extra).encode()
        reports[year] = (f"synthetic/synthetic_GT_TEST01_{year}_real_ticks.htm", raw)
    bundle, _receipt = build_annual_bundle(
        system_id="GT_TEST01", family_id="S016", source_kind="SYNTHETIC_FIXTURE",
        strategy_version_sha256="a" * 64, ea_sha256="d" * 64,
        broker_profile_sha256="e" * 64, test_config_sha256="f" * 64,
        data_manifest_sha256="1" * 64, tester_build="FIXTURE_NOT_MT5",
        as_of_utc=AS_OF_TEXT, reports=reports, ledger_dir=root / "ledgers",
    )
    ledgers = {}
    for row in bundle["results"]:
        if row["ledger_sha256"] is not None:
            ledgers[row["year"]] = (root / "ledgers" / f"GT_TEST01_{row['year']}_deals.csv").read_text(encoding="utf-8")
    return bundle, ledgers


class MetricsTests(unittest.TestCase):
    def test_repo_thresholds_are_unset_and_v2_recomputes_from_the_ledger(self):
        config = load_thresholds(THRESHOLDS.read_text(encoding="utf-8"))
        self.assertEqual(config["approval_status"], "UNSET")
        self.assertTrue(all(value is None for value in config["tolerances"].values()))
        self.assertTrue(all(value is None for value in config["metric_thresholds"].values()))
        with tempfile.TemporaryDirectory() as tmp:
            bundle, ledgers = _bundle_and_ledgers(Path(tmp))
            payload = attach_v2(bundle, ledgers, COSTS, config)
        self.assertEqual(payload["schema"], "goldthinker.factory.mt5_bundle.v2")
        validate_mt5_bundle(v1_view(payload))
        with self.assertRaises(FactoryContractError):
            validate_mt5_bundle(payload)
        metrics = payload["metrics"]
        self.assertEqual(metrics["profit_factor_scope"], "COMPLETED_2021_2025")
        self.assertEqual(metrics["profit_factor_overall"], "1.7800")
        self.assertTrue(all(check["status"] == "UNSET" for check in metrics["threshold_checks"]))
        year = next(row for row in metrics["years"] if row["year"] == 2023)
        self.assertEqual(year["profit_factor"], "2.5000")
        self.assertEqual(year["worst_trade_net_usd"], "-100.0000")
        self.assertEqual(year["worst_trade_share_of_net"], "-0.6667")
        self.assertEqual(year["average_profit_per_trade_usd"], "75.0000")
        # 0.20 spread * 100 contract * 0.10 lot + 10 commission * 0.10 lot = 3.00
        self.assertEqual(year["average_round_trip_quoted_cost_usd"], "3.0000")
        self.assertEqual(year["average_profit_vs_round_trip_cost_usd"], "72.0000")
        self.assertEqual(year["doubled_cost_stress_net_usd"], "144.0000")
        partial = next(row for row in metrics["years"] if row["year"] == 2026)
        self.assertEqual(partial["closed_trades"], 2)
        self.assertNotEqual(metrics["profit_factor_overall"], partial["profit_factor"])
        selected = select_best_completed_year(v1_view(payload))
        self.assertEqual(selected["aidy_year"], 2024)

    def test_tampered_metric_is_rejected(self):
        config = load_thresholds(THRESHOLDS.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as tmp:
            bundle, ledgers = _bundle_and_ledgers(Path(tmp))
        payload = attach_v2(bundle, ledgers, COSTS, config)
        forged = copy.deepcopy(payload)
        forged["metrics"]["years"][2]["doubled_cost_stress_net_usd"] = "999.0000"
        with self.assertRaisesRegex(FactoryContractError, "do not match recomputation"):
            validate_mt5_bundle_v2(forged, ledgers, config)

    def test_approved_numbers_can_fail_but_the_repo_file_cannot_pass(self):
        config = json.loads(THRESHOLDS.read_text(encoding="utf-8"))
        config["approval_status"] = "APPROVED"
        config["approved_by"] = "Danny"
        config["tolerances"] = {key: "0" for key in config["tolerances"]}
        config["metric_thresholds"] = {
            "profit_factor_overall_min": "99",
            "worst_trade_share_of_net_min": "0",
            "average_profit_vs_round_trip_cost_min_usd": "0",
            "doubled_cost_stress_net_min_usd": "0",
        }
        shipped = load_thresholds(THRESHOLDS.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as tmp:
            bundle, ledgers = _bundle_and_ledgers(Path(tmp))
        approved = attach_v2(bundle, ledgers, COSTS, config)
        statuses = {check["metric"]: check["status"] for check in approved["metrics"]["threshold_checks"]}
        self.assertEqual(statuses["profit_factor_overall_min"], "FAIL")
        unset = attach_v2(bundle, ledgers, COSTS, shipped)
        self.assertTrue(all(check["status"] == "UNSET" for check in unset["metrics"]["threshold_checks"]))
        self.assertNotIn("99", THRESHOLDS.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
