"""Selected-year reconciliation. Mismatches block packaging. Other years are not searched."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from aidy.goldthinker_factory_contract import select_best_completed_year
from aidy.goldthinker_factory_metrics import load_thresholds
from aidy.goldthinker_factory_mt5_extract import build_annual_bundle, closed_trades_from_deals, parse_ledger_csv
from aidy.goldthinker_factory_reconcile import (
    MISSING_HOOK,
    ExplicitTradeListReplay,
    UnavailableAidyStrategyReplay,
    reconciliation_status,
    reconcile_selected_year,
)
from scripts.goldthinker_factory.reconcile_selected_year import run as reconcile_run
from tests.goldthinker_factory_synthetic_reports import synthetic_report_html
from tests.test_goldthinker_factory_extract import AS_OF_TEXT, EXTRAS, _end

ROOT = Path(__file__).resolve().parents[1]
UTC_CLOCK = {
    "schema": "goldthinker.factory.server_clock.v1",
    "gmt_offset": "UTC+00:00",
    "dst_offset": None,
    "dst_rule": "NONE",
}


def _world(root: Path):
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
    selection = select_best_completed_year(bundle)
    manifest = {
        "schema": "goldthinker.factory.data_manifest.v1",
        "system_id": "GT_TEST01",
        "years": [
            {"year": year, "dataset_id": f"synthetic-{year}", "coverage": "FIXTURE"}
            for year in range(2021, 2027)
        ],
    }
    text = (root / "ledgers" / f"GT_TEST01_{selection['aidy_year']}_deals.csv").read_text(encoding="utf-8")
    trades, residual = closed_trades_from_deals(parse_ledger_csv(text))
    assert residual == 0
    document = {
        "schema": "goldthinker.factory.aidy_trades.v1",
        "source_kind": "SYNTHETIC_FIXTURE",
        "system_id": "GT_TEST01",
        "year": selection["aidy_year"],
        "trades": [{
            "trade_id": trade.trade_id,
            "signal_time": trade.signal_time,
            "entry_time": trade.entry_time,
            "exit_time": trade.exit_time,
            "side": trade.side,
            "volume": format(trade.volume, "f"),
            "entry_price": format(trade.entry_price, "f"),
            "exit_price": format(trade.exit_price, "f"),
            "commission": format(trade.commission, "f"),
            "fee": format(trade.fee, "f"),
            "swap": format(trade.swap, "f"),
            "profit": format(trade.profit, "f"),
            "net_pnl": format(trade.net_pnl, "f"),
        } for trade in trades],
    }
    return selection, manifest, document


def _reconcile(root, selection, manifest, document, thresholds=None):
    config = thresholds if thresholds is not None else load_thresholds(
        (ROOT / "config/goldthinker_factory_thresholds.json").read_text(encoding="utf-8")
    )
    return reconcile_selected_year(
        selection=selection,
        ledger_dir=root / "ledgers",
        data_manifest=manifest,
        replay=ExplicitTradeListReplay(document),
        thresholds=config,
        server_clock=UTC_CLOCK,
    )


class ReconcileTests(unittest.TestCase):
    def test_identical_trades_stay_inconclusive_while_tolerances_are_unset(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            selection, manifest, document = _world(root)
            receipt = _reconcile(root, selection, manifest, document)
        self.assertEqual(selection["aidy_year"], 2024)
        self.assertEqual(receipt["status"], "INCONCLUSIVE")
        self.assertEqual(receipt["reasons"], ["TOLERANCES_UNSET"])
        self.assertFalse(receipt["research_packaging_allowed"])
        self.assertEqual(receipt["unexplained_residual_usd"], "0.00")
        self.assertEqual(receipt["matched_count"], 2)
        self.assertFalse(receipt["final_pnl_only"])
        self.assertFalse(receipt["orders_sent"])
        self.assertFalse(receipt["broker_credentials_used"])
        self.assertFalse(receipt["tick_data_opened"])
        self.assertFalse(receipt["public_performance_publication_authorised"])
        self.assertIn("signal_time", receipt["compared_fields"])
        self.assertIn("cash_pnl_usd", receipt["compared_fields"])

    def test_dropped_trade_shifted_price_and_changed_cost_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            selection, manifest, document = _world(root)
            dropped = copy.deepcopy(document)
            dropped["trades"] = dropped["trades"][:1]
            shifted = copy.deepcopy(document)
            shifted["trades"][0]["entry_price"] = "1900.10"
            costly = copy.deepcopy(document)
            trade = costly["trades"][0]
            trade["commission"] = format(Decimal(trade["commission"]) - Decimal("1.00"), "f")
            trade["profit"] = format(Decimal(trade["profit"]) + Decimal("1.00"), "f")
            dropped_receipt = _reconcile(root, selection, manifest, dropped)
            shifted_receipt = _reconcile(root, selection, manifest, shifted)
            cost_receipt = _reconcile(root, selection, manifest, costly)
        self.assertEqual(dropped_receipt["status"], "MISMATCH")
        self.assertIn("UNMATCHED_TRADE", dropped_receipt["reasons"])
        self.assertFalse(dropped_receipt["research_packaging_allowed"])
        self.assertTrue(dropped_receipt["unmatched_mt5"])
        self.assertEqual(shifted_receipt["status"], "MISMATCH")
        self.assertEqual(shifted_receipt["mt5_net_pnl_usd"], shifted_receipt["aidy_net_pnl_usd"])
        self.assertEqual(shifted_receipt["differences"][0]["entry_price"], "0.10")
        self.assertEqual(shifted_receipt["differences"][0]["cash_pnl_usd"], "0.00")
        self.assertFalse(shifted_receipt["research_packaging_allowed"])
        self.assertEqual(cost_receipt["status"], "MISMATCH")
        self.assertEqual(cost_receipt["differences"][0]["cost_usd"], "-1.00")
        self.assertEqual(cost_receipt["differences"][0]["cash_pnl_usd"], "0.00")
        self.assertEqual(cost_receipt["mt5_net_pnl_usd"], cost_receipt["aidy_net_pnl_usd"])

    def test_other_years_are_not_searched(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            selection, manifest, document = _world(root)
            decoy_dir = root / "decoy"
            decoy_dir.mkdir()
            (decoy_dir / "GT_TEST01_2023_deals.csv").write_text("DO_NOT_READ_OTHER_YEARS", encoding="utf-8")
            missing = reconcile_selected_year(
                selection=selection, ledger_dir=decoy_dir, data_manifest=manifest,
                replay=ExplicitTradeListReplay(document),
                thresholds=load_thresholds((ROOT / "config/goldthinker_factory_thresholds.json").read_text()),
                server_clock=UTC_CLOCK,
            )
            wrong_year = copy.deepcopy(document)
            wrong_year["year"] = 2023
            wrong = _reconcile(root, selection, manifest, wrong_year)
            manifest_other = copy.deepcopy(manifest)
            manifest_other["years"] = [row for row in manifest_other["years"] if row["year"] != selection["aidy_year"]]
            no_manifest_year = reconcile_selected_year(
                selection=selection, ledger_dir=root / "ledgers", data_manifest=manifest_other,
                replay=ExplicitTradeListReplay(document),
                thresholds=load_thresholds((ROOT / "config/goldthinker_factory_thresholds.json").read_text()),
                server_clock=UTC_CLOCK,
            )
        self.assertEqual(missing["status"], "INCONCLUSIVE")
        self.assertIn("LEDGER_MISSING", missing["reasons"])
        self.assertNotIn("DO_NOT_READ_OTHER_YEARS", json.dumps(missing))
        self.assertEqual(wrong["status"], "INCONCLUSIVE")
        self.assertIn("AIDY_REPLAY_UNAVAILABLE", wrong["reasons"])
        self.assertIn("not searched", wrong["replay_notes"])
        self.assertEqual(no_manifest_year["status"], "INCONCLUSIVE")
        self.assertIn("DATA_MANIFEST_YEAR_MISSING", no_manifest_year["reasons"])

    def test_missing_strategy_hook_is_explicit_and_approved_tolerances_can_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            selection, manifest, document = _world(root)
            unavailable = reconcile_selected_year(
                selection=selection, ledger_dir=root / "ledgers", data_manifest=manifest,
                replay=UnavailableAidyStrategyReplay(),
                thresholds=load_thresholds((ROOT / "config/goldthinker_factory_thresholds.json").read_text()),
                server_clock=UTC_CLOCK,
            )
            approved = json.loads((ROOT / "config/goldthinker_factory_thresholds.json").read_text())
            approved["approval_status"] = "APPROVED"
            approved["approved_by"] = "Danny"
            approved["tolerances"] = {
                "signal_time_seconds": "0",
                "entry_time_seconds": "0",
                "exit_time_seconds": "0",
                "price_abs": "0.01",
                "cost_usd": "0.01",
                "cash_pnl_usd": "0.01",
            }
            for key in approved["metric_thresholds"]:
                approved["metric_thresholds"][key] = "0"
            matched = _reconcile(root, selection, manifest, document, load_thresholds(json.dumps(approved)))
            shifted = copy.deepcopy(document)
            shifted["trades"][0]["entry_price"] = "1900.10"
            outside = _reconcile(root, selection, manifest, shifted, load_thresholds(json.dumps(approved)))
            selection_path = root / "selection.json"
            manifest_path = root / "manifest.json"
            output = root / "receipt.json"
            selection_path.write_text(json.dumps(selection), encoding="utf-8")
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            cli_receipt = reconcile_run(
                selection_path=selection_path,
                ledger_dir=root / "ledgers",
                manifest_path=manifest_path,
                thresholds_path=ROOT / "config/goldthinker_factory_thresholds.json",
                output_path=output,
                aidy_trades_path=None,
                server_clock_path=None,
            )
            self.assertEqual(json.loads(output.read_text(encoding="utf-8")), cli_receipt)
        self.assertEqual(unavailable["status"], "INCONCLUSIVE")
        self.assertEqual(unavailable["aidy_strategy_replay"], "NOT_AVAILABLE")
        self.assertIn(MISSING_HOOK, unavailable["replay_notes"])
        self.assertFalse(unavailable["research_packaging_allowed"])
        self.assertEqual(matched["status"], "MATCH")
        self.assertFalse(matched["research_packaging_allowed"])
        self.assertFalse(matched["historical_edge_verified"])
        self.assertFalse(matched["live_authorised"])
        self.assertFalse(matched["public_performance_publication_authorised"])
        self.assertEqual(outside["status"], "MISMATCH")
        self.assertFalse(outside["research_packaging_allowed"])
        self.assertEqual(cli_receipt["status"], "INCONCLUSIVE")

    def test_itemised_mismatch_stays_mismatch_when_residual_is_nonzero(self):
        status, reasons = reconciliation_status(
            residual=Decimal("1.00"), unmatched=False, field_difference=True, approved=False,
        )
        self.assertEqual(status, "MISMATCH")
        self.assertIn("FIELD_DIFFERENCE", reasons)
        self.assertIn("UNEXPLAINED_RESIDUAL", reasons)
        alone, alone_reasons = reconciliation_status(
            residual=Decimal("1.00"), unmatched=False, field_difference=False, approved=True,
        )
        self.assertEqual(alone, "INCONCLUSIVE")
        self.assertEqual(alone_reasons, ["UNEXPLAINED_RESIDUAL"])

    def test_missing_clock_blocks_and_dst_offset_is_applied(self):
        from datetime import datetime, timedelta
        from aidy.goldthinker_factory_reconcile import broker_server_to_utc
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            selection, manifest, document = _world(root)
            blocked = reconcile_selected_year(
                selection=selection, ledger_dir=root / "ledgers", data_manifest=manifest,
                replay=ExplicitTradeListReplay(document),
                thresholds=load_thresholds((ROOT / "config/goldthinker_factory_thresholds.json").read_text()),
                server_clock=None,
            )
            shifted = copy.deepcopy(document)
            for trade in shifted["trades"]:
                for key in ("signal_time", "entry_time", "exit_time"):
                    stamp = datetime.strptime(trade[key], "%Y-%m-%dT%H:%M:%S") - timedelta(hours=2)
                    trade[key] = stamp.strftime("%Y-%m-%dT%H:%M:%S")
            clock = {
                "schema": "goldthinker.factory.server_clock.v1",
                "gmt_offset": "UTC+02:00",
                "dst_offset": None,
                "dst_rule": "NONE",
            }
            receipt = reconcile_selected_year(
                selection=selection, ledger_dir=root / "ledgers", data_manifest=manifest,
                replay=ExplicitTradeListReplay(shifted),
                thresholds=load_thresholds((ROOT / "config/goldthinker_factory_thresholds.json").read_text()),
                server_clock=clock,
            )
        self.assertEqual(blocked["status"], "INCONCLUSIVE")
        self.assertIn("BROKER_CLOCK_MISSING", blocked["reasons"])
        self.assertNotEqual(blocked["status"], "MATCH")
        self.assertEqual(receipt["status"], "INCONCLUSIVE")
        self.assertEqual(receipt["reasons"], ["TOLERANCES_UNSET"])
        self.assertEqual(receipt["matched_count"], 2)
        summer = broker_server_to_utc(datetime(2023, 7, 15, 12, 0, 0), {
            "schema": "goldthinker.factory.server_clock.v1",
            "gmt_offset": "UTC+02:00",
            "dst_offset": "UTC+03:00",
            "dst_rule": "EU_LAST_SUNDAY_MAR_OCT",
        })
        winter = broker_server_to_utc(datetime(2023, 1, 15, 12, 0, 0), {
            "schema": "goldthinker.factory.server_clock.v1",
            "gmt_offset": "UTC+02:00",
            "dst_offset": "UTC+03:00",
            "dst_rule": "EU_LAST_SUNDAY_MAR_OCT",
        })
        self.assertEqual(summer, datetime(2023, 7, 15, 9, 0, 0))
        self.assertEqual(winter, datetime(2023, 1, 15, 10, 0, 0))
        from aidy.goldthinker_factory_reconcile import aidy_time_in_broker_year
        plus_two = {
            "schema": "goldthinker.factory.server_clock.v1",
            "gmt_offset": "UTC+02:00",
            "dst_offset": None,
            "dst_rule": "NONE",
        }
        new_year_utc = datetime(2022, 12, 31, 23, 0, 0)
        self.assertTrue(aidy_time_in_broker_year(new_year_utc, 2023, plus_two))
        self.assertFalse(aidy_time_in_broker_year(new_year_utc, 2023, UTC_CLOCK))
        self.assertFalse(aidy_time_in_broker_year(datetime(2023, 12, 31, 23, 0, 0), 2023, plus_two))

    def test_packaging_requires_real_replay_and_s040_is_unavailable(self):
        from aidy.goldthinker_factory_reconcile import research_packaging_allowed
        from aidy.goldthinker_factory_replay import S040SmokeReplay
        self.assertFalse(research_packaging_allowed(
            status="MATCH", runner_attestation_verified=True, replay_kind="EXPLICIT_INTERFACE",
        ))
        self.assertFalse(research_packaging_allowed(
            status="MATCH", runner_attestation_verified=False, replay_kind="STRATEGY_REPLAY",
        ))
        self.assertFalse(research_packaging_allowed(
            status="MATCH", runner_attestation_verified=True, replay_kind="STRATEGY_REPLAY",
        ))
        with self.assertRaises(Exception) as raised:
            S040SmokeReplay().replay(selection={"aidy_year": 2023}, data_manifest={})
        self.assertIn("AIDY_REPLAY_UNAVAILABLE", str(raised.exception))

    def test_packaging_calls_runner_verifier_and_stays_closed(self):
        from hashlib import sha256
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from aidy.goldthinker_factory_contract import canonical_json
        from aidy.goldthinker_factory_metrics import attach_v2
        from aidy.goldthinker_factory_reconcile import runner_attestation_is_verified
        from tests.test_goldthinker_factory_metrics import (
            COSTS,
            _attack_sign,
            _coherent_material,
            _load_trust,
            _runner_body,
        )
        approved = json.loads((ROOT / "config/goldthinker_factory_thresholds.json").read_text())
        approved["approval_status"] = "APPROVED"
        approved["approved_by"] = "Danny"
        approved["tolerances"] = {key: "0" for key in approved["tolerances"]}
        for key in approved["metric_thresholds"]:
            approved["metric_thresholds"][key] = "0"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            selection, manifest, document = _world(root)
            reports = {}
            for year, extra in EXTRAS.items():
                raw = synthetic_report_html(year, end=_end(year), extra_last_profit=extra).encode()
                reports[year] = (f"synthetic/synthetic_GT_TEST01_{year}_real_ticks.htm", raw)
            bundle, _receipt = build_annual_bundle(
                system_id="GT_TEST01", family_id="S016", source_kind="SYNTHETIC_FIXTURE",
                strategy_version_sha256="a" * 64, ea_sha256="d" * 64,
                broker_profile_sha256="e" * 64, test_config_sha256="f" * 64,
                data_manifest_sha256="1" * 64, tester_build="FIXTURE_NOT_MT5",
                as_of_utc=AS_OF_TEXT, reports=reports, ledger_dir=root / "ledgers-2",
            )
            ledgers = {
                row["year"]: (root / "ledgers-2" / f"GT_TEST01_{row['year']}_deals.csv").read_text(encoding="utf-8")
                for row in bundle["results"] if row["ledger_sha256"] is not None
            }
            payload = attach_v2(bundle, ledgers, COSTS, approved)
            private = Ed25519PrivateKey.generate()
            trust = _load_trust(
                private.public_key().public_bytes_raw().hex(),
                runner_id="unit-test-runner", key_id="unit-test-key",
            )
            year = selection["aidy_year"]
            row = next(item for item in payload["results"] if item["year"] == year)
            body, log, receipt_bytes, inputs, data_source, _canonical = _coherent_material(
                _runner_body(payload, row, nonce=f"reconcile-{year}", runner_id="unit-test-runner", key_id="unit-test-key")
            )
            profile = canonical_json(payload["broker_cost_profile"]).encode("utf-8")
            self.assertEqual(sha256(profile).hexdigest(), payload["broker_profile_sha256"])
            evidence = {
                "trust": trust,
                "bundle": payload,
                "attestations": {year: _attack_sign(body, private)},
                "reports": {year: reports[year][1]},
                "tester_logs": {year: log},
                "launch_receipts": {year: receipt_bytes},
                "inputs": {year: inputs},
                "data_sources": {year: data_source},
                "broker_profiles": {year: profile},
            }
            ledger = (root / "ledgers" / f"GT_TEST01_{year}_deals.csv").read_text(encoding="utf-8")
            verified = runner_attestation_is_verified(selection, ledger, evidence)
            self.assertFalse(verified)
            matched = reconcile_selected_year(
                selection=selection, ledger_dir=root / "ledgers", data_manifest=manifest,
                replay=ExplicitTradeListReplay(document), thresholds=approved,
                server_clock=UTC_CLOCK, runner_evidence=evidence,
            )
        self.assertEqual(matched["status"], "MATCH")
        self.assertFalse(matched["research_packaging_allowed"])
        self.assertFalse(verified)


if __name__ == "__main__":
    unittest.main()
