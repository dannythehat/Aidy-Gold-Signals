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
from aidy.goldthinker_factory_mt5_extract import build_annual_bundle
from aidy.goldthinker_factory_metrics import (
    _gate,
    attach_v2,
    load_thresholds,
    metrics_from_deals,
    select_best_completed_year_v2,
    validate_mt5_bundle_v2,
    v1_view,
    year_passes_metric_gates,
)
from aidy.goldthinker_factory_mt5_extract import build_annual_bundle
from tests.goldthinker_factory_synthetic_reports import synthetic_report_html
from tests.test_goldthinker_factory_extract import AS_OF_TEXT, EXTRAS, _end

ROOT = Path(__file__).resolve().parents[1]
THRESHOLDS = ROOT / "config/goldthinker_factory_thresholds.json"


def _load_trust(public_hex, *, runner_id, key_id, revoked=()):
    from aidy.goldthinker_factory_attestation import load_runner_trust
    return load_runner_trust({
        "schema": "goldthinker.factory.runner_trust.v1",
        "trusted_runners": [{
            "runner_id": runner_id,
            "key_id": key_id,
            "ed25519_public_key_hex": public_hex,
        }],
        "revoked_key_ids": list(revoked),
    })


def _attack_sign(body, private):
    """Simulate an attacker signature. This is not a factory mint path."""
    from aidy.goldthinker_factory_contract import canonical_json
    signed = {key: body[key] for key in body}
    signed["signature_hex"] = private.sign(canonical_json(signed).encode("utf-8")).hex()
    return signed


def _runner_body(bundle, row, *, nonce, runner_id, key_id):
    from hashlib import sha256
    return {
        "schema": "goldthinker.factory.mt5_runner_attestation.v1",
        "provenance_class": "RUNNER",
        "runner_id": runner_id,
        "key_id": key_id,
        "system_id": bundle["system_id"],
        "nonce": nonce,
        "issued_at": "2026-11-02T00:00:00Z",
        "year": row["year"],
        "report_sha256": row["report_sha256"],
        "ledger_sha256": row["ledger_sha256"],
        "ea_sha256": bundle["ea_sha256"],
        "ini_sha256": bundle["test_config_sha256"],
        "inputs_sha256": sha256(b"inputs-not-a-terminal").hexdigest(),
        "broker_profile_sha256": bundle["broker_profile_sha256"],
        "data_source_sha256": sha256(b"data-source-not-a-terminal").hexdigest(),
        "strategy_source_sha256": bundle["strategy_version_sha256"],
        "data_manifest_sha256": bundle["data_manifest_sha256"],
        "terminal_build": bundle["tester_build"],
        "tester_log_sha256": "ab" * 32,
        "launch_receipt_sha256": "cd" * 32,
        "process_started_utc": "2026-11-02T00:00:00Z",
        "process_exited_utc": "2026-11-02T00:10:00Z",
        "process_exit_code": 0,
        "attested_equity_drawdown_pct": row["max_equity_drawdown_pct"],
        "equity_observations_sha256": None,
    }


def _coherent_material(body):
    from hashlib import sha256
    from aidy.goldthinker_factory_contract import canonical_json
    updated = dict(body)
    log = (
        f"ea_sha256={updated['ea_sha256']}\n"
        f"ini_sha256={updated['ini_sha256']}\n"
        f"report_sha256={updated['report_sha256']}\n"
        f"year={updated['year']}\n"
        f"terminal_build={updated['terminal_build']}\n"
    ).encode()
    receipt = (
        f"started_utc={updated['process_started_utc']}\n"
        f"exited_utc={updated['process_exited_utc']}\n"
        f"exit_code={updated['process_exit_code']}\n"
        f"year={updated['year']}\n"
        f"terminal_build={updated['terminal_build']}\n"
    ).encode()
    inputs = b"inputs-not-a-terminal"
    data_source = b"data-source-not-a-terminal"
    updated["tester_log_sha256"] = sha256(log).hexdigest()
    updated["launch_receipt_sha256"] = sha256(receipt).hexdigest()
    updated["inputs_sha256"] = sha256(inputs).hexdigest()
    updated["data_source_sha256"] = sha256(data_source).hexdigest()
    return updated, log, receipt, inputs, data_source, canonical_json
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

    def test_losing_year_share_cannot_pass_and_unset_blocks_v2_selection(self):
        from aidy.goldthinker_factory_mt5_extract import closed_trades_from_deals
        running = Decimal("0")
        deals = []

        def add(**kwargs):
            nonlocal running
            running += kwargs["profit"] + kwargs["commission"] + kwargs["fee"] + kwargs["swap"]
            deals.append({**kwargs, "balance": running, "comment": "SYNTHETIC_FIXTURE"})

        add(time="2023-01-02T00:00:00", deal=1, order=None, symbol="", type="balance",
            direction="", volume=None, price=None, commission=Decimal("0"), fee=Decimal("0"),
            swap=Decimal("0"), profit=Decimal("10000"))
        add(time="2023-02-01T10:00:00", deal=2, order=10, symbol="XAUUSD", type="buy",
            direction="in", volume=Decimal("0.10"), price=Decimal("1900"), commission=Decimal("0"),
            fee=Decimal("0"), swap=Decimal("0"), profit=Decimal("0"))
        add(time="2023-02-01T14:00:00", deal=3, order=11, symbol="XAUUSD", type="sell",
            direction="out", volume=Decimal("0.10"), price=Decimal("1890"), commission=Decimal("0"),
            fee=Decimal("0"), swap=Decimal("0"), profit=Decimal("-100"))
        add(time="2023-03-01T10:00:00", deal=4, order=12, symbol="XAUUSD", type="buy",
            direction="in", volume=Decimal("0.10"), price=Decimal("1900"), commission=Decimal("0"),
            fee=Decimal("0"), swap=Decimal("0"), profit=Decimal("0"))
        add(time="2023-03-01T16:00:00", deal=5, order=13, symbol="XAUUSD", type="sell",
            direction="out", volume=Decimal("0.10"), price=Decimal("1905"), commission=Decimal("0"),
            fee=Decimal("0"), swap=Decimal("0"), profit=Decimal("50"))
        detail = metrics_from_deals(deals, COSTS)
        self.assertEqual(detail["year_net"], Decimal("-50"))
        self.assertFalse(detail["worst_trade_share_defined"])
        self.assertIsNone(detail["worst_trade_share_of_net"])
        self.assertEqual(_gate(None, "-1", "APPROVED", signed=True), "FAIL")
        self.assertNotEqual(_gate(None, "-100", "UNSET", signed=True), "PASS")
        row = {
            "profit_factor": "0.5000",
            "worst_trade_share_defined": False,
            "worst_trade_share_of_net": None,
            "average_profit_vs_round_trip_cost_usd": "-25.0000",
            "doubled_cost_stress_net_usd": "-56.0000",
        }
        self.assertFalse(year_passes_metric_gates(row, {
            "profit_factor_overall_min": "0",
            "worst_trade_share_of_net_min": "-100",
            "average_profit_vs_round_trip_cost_min_usd": "-1000",
            "doubled_cost_stress_net_min_usd": "-1000",
        }))
        trades, _residual = closed_trades_from_deals(deals)
        self.assertEqual(trades[0].net_pnl, Decimal("-100"))
        config = load_thresholds(THRESHOLDS.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as tmp:
            bundle, ledgers = _bundle_and_ledgers(Path(tmp))
            payload = attach_v2(bundle, ledgers, COSTS, config)
            selected = select_best_completed_year_v2(payload, ledgers, config)
        self.assertEqual(selected["selection_status"], "BLOCKED_THRESHOLDS_UNSET")
        self.assertIsNone(selected["aidy_year"])
        self.assertNotEqual(selected["selection_status"], "SELECTED_PENDING_INDEPENDENT_EVIDENCE")
        year = next(item for item in payload["metrics"]["years"] if item["year"] == 2023)
        self.assertEqual(year["equity_drawdown_relative_pct"], "1.0500")
        self.assertEqual(year["balance_drawdown_relative_pct"], "1.0500")
        self.assertEqual(year["equity_dd_status"], "EQUITY_DD_UNVERIFIED")
        self.assertEqual(year["conservative_drawdown_pct"], "1.0500")
        approved = json.loads(THRESHOLDS.read_text(encoding="utf-8"))
        approved["approval_status"] = "APPROVED"
        approved["approved_by"] = "Danny"
        approved["tolerances"] = {key: "0" for key in approved["tolerances"]}
        approved["metric_thresholds"] = {
            "profit_factor_overall_min": "1",
            "worst_trade_share_of_net_min": "-10",
            "average_profit_vs_round_trip_cost_min_usd": "0",
            "doubled_cost_stress_net_min_usd": "0",
        }
        gated = attach_v2(bundle, ledgers, COSTS, approved)
        chosen = select_best_completed_year_v2(gated, ledgers, approved)
        self.assertEqual(chosen["selection_status"], "RESEARCH_FIXTURE_ONLY")
        self.assertEqual(chosen["aidy_year"], 2024)
        relabelled = copy.deepcopy(gated)
        relabelled["source_kind"] = "REAL_MT5_TESTER"
        refused = select_best_completed_year_v2(relabelled, ledgers, approved)
        self.assertEqual(refused["selection_status"], "BLOCKED_SYNTHETIC_MARKER")
        self.assertIsNone(refused["aidy_year"])
        self.assertNotEqual(refused["selection_status"], "SELECTED_PENDING_INDEPENDENT_EVIDENCE")
        self.assertFalse(refused["real_mt5_evidence_authenticated"])
        approved["metric_thresholds"]["worst_trade_share_of_net_min"] = "0"
        blocked_bundle = attach_v2(bundle, ledgers, COSTS, approved)
        blocked = select_best_completed_year_v2(blocked_bundle, ledgers, approved)
        self.assertEqual(blocked["selection_status"], "BLOCKED_METRIC_CHECKS")
        self.assertIsNone(blocked["aidy_year"])
        self.assertNotEqual(blocked["selection_status"], "SELECTED_PENDING_INDEPENDENT_EVIDENCE")

    def test_signed_synthetic_relabel_is_blocked(self):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        approved = json.loads(THRESHOLDS.read_text(encoding="utf-8"))
        approved["approval_status"] = "APPROVED"
        approved["approved_by"] = "Danny"
        approved["tolerances"] = {key: "0" for key in approved["tolerances"]}
        approved["metric_thresholds"] = {
            "profit_factor_overall_min": "1",
            "worst_trade_share_of_net_min": "-10",
            "average_profit_vs_round_trip_cost_min_usd": "0",
            "doubled_cost_stress_net_min_usd": "0",
        }
        raw_reports = {}
        named = {}
        for year, extra in EXTRAS.items():
            html = synthetic_report_html(year, end=_end(year), extra_last_profit=extra)
            self.assertIn("SYNTHETIC_FIXTURE", html)
            raw = html.encode("utf-8")
            raw_reports[year] = raw
            named[year] = (f"synthetic/synthetic_GT_TEST01_{year}_real_ticks.htm", raw)
        with tempfile.TemporaryDirectory() as tmp:
            bundle, _receipt = build_annual_bundle(
                system_id="GT_TEST01", family_id="S016", source_kind="SYNTHETIC_FIXTURE",
                strategy_version_sha256="a" * 64, ea_sha256="d" * 64,
                broker_profile_sha256="e" * 64, test_config_sha256="f" * 64,
                data_manifest_sha256="1" * 64, tester_build="FIXTURE_NOT_MT5",
                as_of_utc=AS_OF_TEXT, reports=named, ledger_dir=Path(tmp) / "ledgers",
            )
            ledgers = {
                row["year"]: (Path(tmp) / "ledgers" / f"GT_TEST01_{row['year']}_deals.csv").read_text(encoding="utf-8")
                for row in bundle["results"] if row["ledger_sha256"] is not None
            }
        bundle["source_kind"] = "REAL_MT5_TESTER"
        payload = attach_v2(bundle, ledgers, COSTS, approved)
        private = Ed25519PrivateKey.generate()
        public = private.public_key().public_bytes_raw().hex()
        trust = _load_trust(public, runner_id="reviewer-runner", key_id="reviewer-key")
        attestations = {}
        for row in payload["results"]:
            if row["test_status"] != "COMPLETED":
                continue
            attestations[row["year"]] = _attack_sign(
                _runner_body(
                    payload, row, nonce=f"attack-{row['year']}",
                    runner_id="reviewer-runner", key_id="reviewer-key",
                ),
                private,
            )
        attacked = select_best_completed_year_v2(
            payload, ledgers, approved,
            evidence={"trust": trust, "attestations": attestations, "reports": raw_reports},
        )
        self.assertEqual(attacked["selection_status"], "BLOCKED_SYNTHETIC_MARKER")
        self.assertIsNone(attacked["aidy_year"])
        self.assertNotEqual(attacked["selection_status"], "SELECTED_PENDING_INDEPENDENT_EVIDENCE")

    def test_real_selection_requires_a_matching_extractor_receipt(self):
        approved = json.loads(THRESHOLDS.read_text(encoding="utf-8"))
        approved["approval_status"] = "APPROVED"
        approved["approved_by"] = "Danny"
        approved["tolerances"] = {key: "0" for key in approved["tolerances"]}
        approved["metric_thresholds"] = {
            "profit_factor_overall_min": "1",
            "worst_trade_share_of_net_min": "-10",
            "average_profit_vs_round_trip_cost_min_usd": "0",
            "doubled_cost_stress_net_min_usd": "0",
        }
        reports = {}
        for year, extra in EXTRAS.items():
            html = synthetic_report_html(year, end=_end(year), extra_last_profit=extra)
            self.assertIn("SYNTHETIC_FIXTURE", html)
            reports[year] = (
                f"GT_TEST01_{year}_real_ticks.htm",
                html.replace("SYNTHETIC_FIXTURE", "AUTHORED_NOT_A_TERMINAL").encode("utf-8"),
            )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle, receipt = build_annual_bundle(
                system_id="GT_TEST01", family_id="S016", source_kind="REAL_MT5_TESTER",
                strategy_version_sha256="a" * 64, ea_sha256="d" * 64,
                broker_profile_sha256="e" * 64, test_config_sha256="f" * 64,
                data_manifest_sha256="1" * 64, tester_build="AUTHORED_NOT_A_TERMINAL",
                as_of_utc=AS_OF_TEXT, reports=reports, ledger_dir=root / "ledgers",
            )
            ledgers = {
                row["year"]: (root / "ledgers" / f"GT_TEST01_{row['year']}_deals.csv").read_text(encoding="utf-8")
                for row in bundle["results"] if row["ledger_sha256"] is not None
            }
        payload = attach_v2(bundle, ledgers, COSTS, approved)
        evidence = {
            "bundle_v1": bundle,
            "receipt": receipt,
            "reports": {year: raw for year, (_name, raw) in reports.items()},
        }
        unsigned = select_best_completed_year_v2(payload, ledgers, approved, evidence=evidence)
        self.assertEqual(unsigned["selection_status"], "BLOCKED_RUNNER_TRUST_UNCONFIGURED")
        self.assertNotEqual(unsigned["selection_status"], "SELECTED_PENDING_INDEPENDENT_EVIDENCE")
        self.assertFalse(unsigned["real_mt5_evidence_authenticated"])
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from aidy.goldthinker_factory_attestation import sign_attestation
        from aidy.goldthinker_factory_contract import canonical_json
        private = Ed25519PrivateKey.generate()
        public = private.public_key().public_bytes_raw().hex()
        trust = _load_trust(public, runner_id="unit-test-runner", key_id="unit-test-key")
        with self.assertRaises(FactoryContractError) as minted:
            sign_attestation({"provenance_class": "RUNNER"}, private)
        self.assertIn("not minted", str(minted.exception))
        attestations = {}
        for year, row in ((item["year"], item) for item in payload["results"] if item["test_status"] == "COMPLETED"):
            body = _runner_body(
                payload, row, nonce=f"nonce-{year}",
                runner_id="unit-test-runner", key_id="unit-test-key",
            )
            attestations[year] = _attack_sign(body, private)
        from aidy.goldthinker_factory_attestation import NonceReplayRegistry
        nonce_dir = Path(tempfile.mkdtemp())
        nonce_registry = NonceReplayRegistry(nonce_dir / "used.json")
        bound = {
            "bundle_v1": bundle,
            "receipt": receipt,
            "reports": evidence["reports"],
            "nonce_registry": nonce_registry,
        }
        missing_receipt = select_best_completed_year_v2(
            payload, ledgers, approved,
            evidence={"trust": trust, "reports": evidence["reports"], "nonce_registry": nonce_registry},
        )
        self.assertEqual(missing_receipt["selection_status"], "BLOCKED_EVIDENCE_RECEIPT_MISSING")
        self.assertIsNone(missing_receipt["aidy_year"])
        tampered_receipt = copy.deepcopy(receipt)
        tampered_receipt["system_id"] = "GT_TAMPER"
        tampered = select_best_completed_year_v2(
            payload, ledgers, approved,
            evidence={**bound, "receipt": tampered_receipt},
        )
        self.assertEqual(tampered["selection_status"], "BLOCKED_EVIDENCE_HASH_MISMATCH")
        self.assertIsNone(tampered["aidy_year"])
        signed = select_best_completed_year_v2(
            payload, ledgers, approved,
            evidence={**bound, "trust": trust, "attestations": attestations},
        )
        self.assertEqual(signed["selection_status"], "BLOCKED_REAL_MT5_PROVENANCE")
        self.assertIsNone(signed["aidy_year"])
        self.assertNotEqual(signed["selection_status"], "SELECTED_PENDING_INDEPENDENT_EVIDENCE")
        self.assertFalse(signed["real_mt5_evidence_authenticated"])
        profile_bytes = canonical_json(payload["broker_cost_profile"]).encode("utf-8")
        coherent = {}
        logs, receipts, inputs, sources, profiles = {}, {}, {}, {}, {}
        for year, row in ((item["year"], item) for item in payload["results"] if item["test_status"] == "COMPLETED"):
            body, log, receipt, raw_inputs, data_source, _canonical = _coherent_material(
                _runner_body(
                    payload, row, nonce=f"coherent-{year}",
                    runner_id="unit-test-runner", key_id="unit-test-key",
                )
            )
            coherent[year] = _attack_sign(body, private)
            logs[year] = log
            receipts[year] = receipt
            inputs[year] = raw_inputs
            sources[year] = data_source
            profiles[year] = profile_bytes
        self_reported = select_best_completed_year_v2(
            payload, ledgers, approved,
            evidence={
                **bound,
                "trust": trust,
                "attestations": coherent,
                "tester_logs": logs,
                "launch_receipts": receipts,
                "inputs": inputs,
                "data_sources": sources,
                "broker_profiles": profiles,
            },
        )
        self.assertEqual(
            self_reported["selection_status"],
            "RUNNER_SIGNED_SELF_REPORTED_PENDING_VERIFICATION",
        )
        self.assertIsNone(self_reported["aidy_year"])
        self.assertNotEqual(self_reported["selection_status"], "SELECTED_PENDING_INDEPENDENT_EVIDENCE")
        self.assertFalse(self_reported["real_mt5_evidence_authenticated"])
        revoked_trust = _load_trust(
            public, runner_id="unit-test-runner", key_id="unit-test-key", revoked=["unit-test-key"],
        )
        revoked = select_best_completed_year_v2(
            payload, ledgers, approved,
            evidence={**bound, "trust": revoked_trust, "attestations": coherent},
        )
        self.assertEqual(revoked["selection_status"], "BLOCKED_ATTESTATION_KEY_REVOKED")
        self.assertIsNone(revoked["aidy_year"])
        self.assertNotEqual(revoked["selection_status"], "SELECTED_PENDING_INDEPENDENT_EVIDENCE")
        fixture = dict(attestations[2021])
        fixture["provenance_class"] = "FIXTURE"
        fixture = sign_attestation({k: fixture[k] for k in fixture if k != "signature_hex"}, private)
        refused_fixture = select_best_completed_year_v2(
            payload, ledgers, approved,
            evidence={**bound, "trust": trust, "attestations": {**attestations, 2021: fixture}},
        )
        self.assertEqual(refused_fixture["selection_status"], "BLOCKED_FIXTURE_PROVENANCE")
        self.assertNotEqual(refused_fixture["selection_status"], "SELECTED_PENDING_INDEPENDENT_EVIDENCE")
        reused = dict(attestations[2022])
        reused["nonce"] = attestations[2021]["nonce"]
        reused = _attack_sign({k: reused[k] for k in reused if k != "signature_hex"}, private)
        collided = select_best_completed_year_v2(
            payload, ledgers, approved,
            evidence={**bound, "trust": trust, "attestations": {**attestations, 2022: reused}},
        )
        self.assertEqual(collided["selection_status"], "BLOCKED_ATTESTATION_NONCE_REUSED")
        other = copy.deepcopy(payload)
        other["system_id"] = "GT_OTHER01"
        foreign = select_best_completed_year_v2(
            other, ledgers, approved,
            evidence={**bound, "trust": trust, "attestations": attestations},
        )
        self.assertEqual(foreign["selection_status"], "BLOCKED_EVIDENCE_HASH_MISMATCH")
        self.assertIsNone(foreign["aidy_year"])


if __name__ == "__main__":
    unittest.main()
