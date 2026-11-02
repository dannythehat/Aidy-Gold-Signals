"""Runner attestation stays self-reported until an observed runner exists."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from aidy.goldthinker_factory_attestation import (
    NonceReplayRegistry,
    independent_runner_observed,
    verify_runner_attestation,
)
from aidy.goldthinker_factory_contract import canonical_json
from aidy.goldthinker_factory_metrics import attach_v2, select_best_completed_year_v2
from aidy.goldthinker_factory_mt5_extract import build_annual_bundle
from tests.goldthinker_factory_synthetic_reports import synthetic_report_html
from tests.test_goldthinker_factory_extract import AS_OF_TEXT, EXTRAS, _end
from tests.test_goldthinker_factory_metrics import (
    COSTS,
    THRESHOLDS,
    _attack_sign,
    _coherent_material,
    _load_trust,
    _runner_body,
)


def _approved():
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
    return approved


class AttestationCeilingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        cls.private = Ed25519PrivateKey.generate()
        cls.public = cls.private.public_key().public_bytes_raw().hex()
        cls.trust = _load_trust(cls.public, runner_id="unit-test-runner", key_id="unit-test-key")
        cls.approved = _approved()
        cls._tmp = tempfile.TemporaryDirectory()
        root = Path(cls._tmp.name)
        reports = {}
        for year, extra in EXTRAS.items():
            html = synthetic_report_html(year, end=_end(year), extra_last_profit=extra)
            reports[year] = (
                f"GT_TEST01_{year}_real_ticks.htm",
                html.replace("SYNTHETIC_FIXTURE", "AUTHORED_NOT_A_TERMINAL").encode("utf-8"),
            )
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
        payload = attach_v2(bundle, ledgers, COSTS, cls.approved)
        cls.bundle = bundle
        cls.receipt = receipt
        cls.payload = payload
        cls.ledgers = ledgers
        cls.reports = {year: raw for year, (_name, raw) in reports.items()}
        cls.profile = canonical_json(payload["broker_cost_profile"]).encode("utf-8")
        cls.year = 2024
        row = next(item for item in payload["results"] if item["year"] == cls.year)
        body, log, launch, inputs, data_source, _canonical = _coherent_material(
            _runner_body(
                payload, row, nonce="nonce-equity-2024",
                runner_id="unit-test-runner", key_id="unit-test-key",
            )
        )
        cls.body = body
        cls.log = log
        cls.launch = launch
        cls.inputs = inputs
        cls.data_source = data_source
        cls.signed = _attack_sign(body, cls.private)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def _verify(self, document, *, log=None, launch=None, registry=None, observations=None):
        return verify_runner_attestation(
            document,
            trust=self.trust,
            report=self.reports[self.year],
            ledger=self.ledgers[self.year],
            bundle=self.payload,
            year=self.year,
            tester_log=self.log if log is None else log,
            inputs=self.inputs,
            broker_profile=self.profile,
            data_source=self.data_source,
            launch_receipt=self.launch if launch is None else launch,
            nonce_registry=registry if registry is not None else NonceReplayRegistry(
                Path(tempfile.mkdtemp()) / "used.json"
            ),
            equity_observations=observations,
        )

    def _signed_with(self, *, log=None, launch=None, nonce="nonce-variant"):
        from hashlib import sha256
        body = dict(self.body)
        body["nonce"] = nonce
        if log is not None:
            body["tester_log_sha256"] = sha256(log).hexdigest()
        if launch is not None:
            body["launch_receipt_sha256"] = sha256(launch).hexdigest()
        return _attack_sign(body, self.private)

    def test_signed_report_equity_drawdown_stays_unverified(self):
        self.assertFalse(independent_runner_observed())
        checked = self._verify(self.signed)
        self.assertNotEqual(checked["equity_dd_status"], "TESTER_ATTESTED")
        self.assertEqual(checked["equity_dd_status"], "RUNNER_SIGNED_SELF_REPORTED")
        self.assertFalse(checked["verified"])
        self.assertEqual(checked["reason"], "RUNNER_SIGNED_SELF_REPORTED_PENDING_VERIFICATION")
        registry = NonceReplayRegistry(Path(tempfile.mkdtemp()) / "used.json")
        selected = select_best_completed_year_v2(
            self.payload, self.ledgers, self.approved,
            evidence=self._evidence(registry),
        )
        self.assertIsNone(selected["aidy_year"])
        self.assertNotEqual(selected["selection_status"], "SELECTED_PENDING_INDEPENDENT_EVIDENCE")
        self.assertIn(
            selected["selection_status"],
            ("RUNNER_SIGNED_SELF_REPORTED_PENDING_VERIFICATION", "BLOCKED_REAL_MT5_PROVENANCE"),
        )

    def test_nonce_replay_is_rejected_across_verifier_instances(self):
        path = Path(tempfile.mkdtemp()) / "used.json"
        first = self._verify(self._signed_with(nonce="nonce-replay-once"), registry=NonceReplayRegistry(path))
        self.assertEqual(first["reason"], "RUNNER_SIGNED_SELF_REPORTED_PENDING_VERIFICATION")
        second = self._verify(
            self._signed_with(nonce="nonce-replay-once"),
            registry=NonceReplayRegistry(path),
        )
        self.assertEqual(second["reason"], "BLOCKED_ATTESTATION_NONCE_REPLAY")
        self.assertFalse(second["verified"])

    def test_journal_near_miss_fields_are_not_coherent(self):
        build = self.body["terminal_build"]
        cases = {
            "prefix": self._rewrite(self.log, "terminal_build", build[:-1]),
            "suffix": self._rewrite(self.log, "terminal_build", build[1:]),
            "embedded": (
                "comment=ea_sha256={ea} ini_sha256={ini} report_sha256={report} "
                "year={year} terminal_build={build}\n"
            ).format(
                ea=self.body["ea_sha256"],
                ini=self.body["ini_sha256"],
                report=self.body["report_sha256"],
                year=self.body["year"],
                build=build,
            ).encode(),
        }
        for name, log in cases.items():
            checked = self._verify(self._signed_with(log=log, nonce=f"near-{name}"), log=log)
            self.assertEqual(checked["reason"], "BLOCKED_REAL_MT5_PROVENANCE", name)
            self.assertFalse(checked["verified"], name)

    def test_launch_receipt_fields_must_match_exactly(self):
        text = self.launch.decode("utf-8")
        fields = {
            "started_utc": "2026-11-02T00:00:01Z",
            "exited_utc": "2026-11-02T00:09:00Z",
            "exit_code": "1",
            "year": "2023",
            "terminal_build": self.body["terminal_build"] + "X",
        }
        for field, wrong in fields.items():
            missing = self._drop_line(text, field).encode()
            mismatched = self._rewrite(self.launch, field, wrong)
            for label, receipt in (("missing", missing), ("mismatched", mismatched)):
                checked = self._verify(
                    self._signed_with(launch=receipt, nonce=f"receipt-{field}-{label}"),
                    launch=receipt,
                )
                self.assertEqual(
                    checked["reason"], "BLOCKED_REAL_MT5_PROVENANCE", f"{field} {label}",
                )

    def test_attestation_system_id_mismatch_is_blocked(self):
        body = dict(self.body)
        body["system_id"] = "GT_OTHER01"
        body["nonce"] = "nonce-other-system"
        checked = self._verify(_attack_sign(body, self.private))
        self.assertEqual(checked["reason"], "BLOCKED_ATTESTATION_SYSTEM_ID")

    def _evidence(self, registry):
        attestations = {}
        logs, launches, inputs_map, sources, profiles = {}, {}, {}, {}, {}
        for row in self.payload["results"]:
            if row["test_status"] != "COMPLETED":
                continue
            year_body, year_log, year_launch, year_inputs, year_source, _canonical = _coherent_material(
                _runner_body(
                    self.payload, row, nonce=f"select-{row['year']}",
                    runner_id="unit-test-runner", key_id="unit-test-key",
                )
            )
            attestations[row["year"]] = _attack_sign(year_body, self.private)
            logs[row["year"]] = year_log
            launches[row["year"]] = year_launch
            inputs_map[row["year"]] = year_inputs
            sources[row["year"]] = year_source
            profiles[row["year"]] = self.profile
        return {
            "trust": self.trust,
            "bundle_v1": self.bundle,
            "receipt": self.receipt,
            "reports": self.reports,
            "attestations": attestations,
            "tester_logs": logs,
            "launch_receipts": launches,
            "inputs": inputs_map,
            "data_sources": sources,
            "broker_profiles": profiles,
            "nonce_registry": registry,
        }

    @staticmethod
    def _rewrite(raw: bytes, key: str, value: str) -> bytes:
        lines = []
        for line in raw.decode("utf-8").splitlines():
            if line.startswith(key + "="):
                lines.append(f"{key}={value}")
            else:
                lines.append(line)
        return ("\n".join(lines) + "\n").encode()

    @staticmethod
    def _drop_line(text: str, key: str) -> str:
        kept = [line for line in text.splitlines() if not line.startswith(key + "=")]
        return "\n".join(kept) + "\n"


if __name__ == "__main__":
    unittest.main()
