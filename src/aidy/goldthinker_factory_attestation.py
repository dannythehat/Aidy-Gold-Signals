"""Runner-signed MT5 report attestation.

The committed trust store lists no runners and no keys. Verification then
fails closed. A fixture provenance class is rejected even if the bundle's
source_kind says REAL_MT5_TESTER. A valid signature binds bytes the runner
claims to have produced. It is not an independent authentication that a
terminal session occurred.
"""
from __future__ import annotations

import hmac
import json
from decimal import Decimal, ROUND_HALF_UP
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping

from aidy.goldthinker_factory_contract import FactoryContractError, canonical_json

ATTESTATION_SCHEMA = "goldthinker.factory.mt5_runner_attestation.v1"
TRUST_SCHEMA = "goldthinker.factory.runner_trust.v1"
BODY_KEYS = (
    "schema", "provenance_class", "runner_id", "year",
    "report_sha256", "ledger_sha256", "ea_sha256", "ini_sha256",
    "strategy_source_sha256", "data_manifest_sha256", "terminal_build",
    "tester_log_sha256", "process_started_utc", "process_exited_utc",
    "process_exit_code", "attested_equity_drawdown_pct",
    "equity_observations_sha256",
)
HEX64 = set("0123456789abcdef")
TRUST_PATH = Path(__file__).resolve().parents[2] / "config" / "goldthinker_factory_runner_trust.json"


def load_runner_trust(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) != {"schema", "trusted_runners"}:
        raise FactoryContractError("runner trust: missing or unexpected keys")
    if payload["schema"] != TRUST_SCHEMA or not isinstance(payload["trusted_runners"], list):
        raise FactoryContractError("runner trust schema is invalid")
    runners = {}
    for row in payload["trusted_runners"]:
        if not isinstance(row, dict) or set(row) != {"runner_id", "hmac_sha256_key_hex"}:
            raise FactoryContractError("runner trust entry is invalid")
        key_hex = row["hmac_sha256_key_hex"]
        if (
            not isinstance(row["runner_id"], str) or not row["runner_id"]
            or not isinstance(key_hex, str) or len(key_hex) != 64
            or any(ch not in HEX64 for ch in key_hex)
        ):
            raise FactoryContractError("runner key must be 32 bytes of hex and is not stored in git")
        runners[row["runner_id"]] = bytes.fromhex(key_hex)
    return {"schema": TRUST_SCHEMA, "runners": runners}


def committed_runner_trust() -> dict[str, Any]:
    return load_runner_trust(json.loads(TRUST_PATH.read_text(encoding="utf-8")))


def attestation_body(document: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(document, Mapping) or set(document) != set(BODY_KEYS) | {"signature_hex"}:
        raise FactoryContractError("ATTESTATION_MALFORMED")
    if document["schema"] != ATTESTATION_SCHEMA:
        raise FactoryContractError("ATTESTATION_MALFORMED")
    if document["provenance_class"] not in ("RUNNER", "FIXTURE"):
        raise FactoryContractError("ATTESTATION_MALFORMED")
    return {key: document[key] for key in BODY_KEYS}


def sign_attestation(body: Mapping[str, Any], key: bytes) -> dict[str, Any]:
    """Test and runner helper. The repository does not call this with a real key."""
    if not isinstance(key, bytes) or len(key) != 32:
        raise FactoryContractError("runner key must be 32 bytes")
    clean = {key_name: body[key_name] for key_name in BODY_KEYS}
    signature = hmac.new(key, canonical_json(clean).encode("utf-8"), sha256).hexdigest()
    signed = dict(clean)
    signed["signature_hex"] = signature
    return signed


def equity_drawdown_from_observations(equities: list[str]) -> str:
    """Max peak-to-trough percent of an equity series. Not a balance series."""
    if len(equities) < 2:
        raise FactoryContractError("equity observations are insufficient")
    values = [Decimal(item) for item in equities]
    if any(item <= 0 for item in values):
        raise FactoryContractError("equity observations must stay positive")
    peak = values[0]
    worst = Decimal(0)
    for item in values:
        if item > peak:
            peak = item
        drawdown = (peak - item) / peak * Decimal(100)
        if drawdown > worst:
            worst = drawdown
    return format(worst.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP), "f")


def verify_runner_attestation(
    document: Mapping[str, Any] | None,
    *,
    trust: Mapping[str, Any] | None,
    report: bytes | None,
    ledger: str | None,
    bundle: Mapping[str, Any],
    year: int,
    equity_observations: list[str] | None = None,
) -> dict[str, Any]:
    """Fail closed. An empty trust store never verifies."""
    if trust is None:
        trust = committed_runner_trust()
    runners = trust.get("runners") if isinstance(trust, Mapping) else None
    if not runners:
        return _result(False, "BLOCKED_RUNNER_TRUST_UNCONFIGURED", "EQUITY_DD_UNVERIFIED")
    if document is None:
        return _result(False, "BLOCKED_ATTESTATION_MISSING", "EQUITY_DD_UNVERIFIED")
    try:
        body = attestation_body(document)
    except FactoryContractError:
        return _result(False, "BLOCKED_ATTESTATION_MALFORMED", "EQUITY_DD_UNVERIFIED")
    if body["provenance_class"] != "RUNNER":
        return _result(False, "BLOCKED_FIXTURE_PROVENANCE", "EQUITY_DD_UNVERIFIED")
    key = runners.get(body["runner_id"])
    if key is None:
        return _result(False, "BLOCKED_RUNNER_TRUST_UNCONFIGURED", "EQUITY_DD_UNVERIFIED")
    expected = hmac.new(key, canonical_json(body).encode("utf-8"), sha256).hexdigest()
    supplied = document.get("signature_hex")
    if not isinstance(supplied, str) or not hmac.compare_digest(expected, supplied):
        return _result(False, "BLOCKED_ATTESTATION_SIGNATURE", "EQUITY_DD_UNVERIFIED")
    if body["year"] != year or not isinstance(report, (bytes, bytearray)) or not isinstance(ledger, str):
        return _result(False, "BLOCKED_ATTESTATION_HASH_MISMATCH", "EQUITY_DD_UNVERIFIED")
    if sha256(bytes(report)).hexdigest() != body["report_sha256"]:
        return _result(False, "BLOCKED_ATTESTATION_HASH_MISMATCH", "EQUITY_DD_UNVERIFIED")
    if sha256(ledger.encode("utf-8")).hexdigest() != body["ledger_sha256"]:
        return _result(False, "BLOCKED_ATTESTATION_HASH_MISMATCH", "EQUITY_DD_UNVERIFIED")
    row = next(item for item in bundle["results"] if item["year"] == year)
    if (
        body["report_sha256"] != row["report_sha256"]
        or body["ledger_sha256"] != row["ledger_sha256"]
        or body["ea_sha256"] != bundle["ea_sha256"]
        or body["ini_sha256"] != bundle["test_config_sha256"]
        or body["strategy_source_sha256"] != bundle["strategy_version_sha256"]
        or body["data_manifest_sha256"] != bundle["data_manifest_sha256"]
        or body["terminal_build"] != bundle["tester_build"]
        or body["process_exit_code"] != 0
        or not _sha(body["tester_log_sha256"])
    ):
        return _result(False, "BLOCKED_ATTESTATION_HASH_MISMATCH", "EQUITY_DD_UNVERIFIED")
    equity_status = _equity_status(body, row, equity_observations)
    return _result(True, "RUNNER_ATTESTATION_VERIFIED", equity_status)


def _sha(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(ch in HEX64 for ch in value)


def _equity_status(body: Mapping[str, Any], row: Mapping[str, Any], observations: list[str] | None) -> str:
    attested = body.get("attested_equity_drawdown_pct")
    if isinstance(attested, str) and attested == row.get("max_equity_drawdown_pct"):
        return "TESTER_ATTESTED"
    if observations is not None and body.get("equity_observations_sha256"):
        digest = sha256(canonical_json(observations).encode("utf-8")).hexdigest()
        if digest == body["equity_observations_sha256"]:
            derived = equity_drawdown_from_observations(observations)
            if derived == row.get("max_equity_drawdown_pct"):
                return "EQUITY_OBSERVATIONS_CHECKED"
    return "EQUITY_DD_UNVERIFIED"


def _result(verified: bool, reason: str, equity_status: str) -> dict[str, Any]:
    return {
        "verified": verified,
        "reason": reason,
        "equity_dd_status": equity_status,
        "real_mt5_evidence_authenticated": False,
    }
