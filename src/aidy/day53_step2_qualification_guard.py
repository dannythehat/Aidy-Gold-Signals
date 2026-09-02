"""Pre-score guards for the frozen Day 53 Step 2 qualification.

These checks do not inspect market values or compute qualification metrics. They
only prove that the checked-out preregistration, repository manifest and
append-only D1 research-ledger records agree before an empirical scorer is
allowed to run.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from aidy.day53_step2_preregistration import (
    STEP2_QUALIFICATION_ID,
    STEP2_RESEARCH_FAMILY_ID,
    build_step2_equivalence_contract_payload,
    build_step2_research_family_payload,
    step2_contract_digest,
)
from aidy.market_data_semantics import EQUIVALENCE_CONTRACT_RECORD_TYPE
from aidy.research_trials import digest as research_digest
from aidy.research_trials import verify_chain

REPOSITORY_MANIFEST_VERSION = "aidy_day53_step2_repository_preregistration_manifest_v2"
RESEARCH_FAMILY_RECORD_TYPE = "research_family_registered"
THRESHOLD_REGION_WINDOW_BPS = Decimal(5)


def _normalize_ledger_record(value: Mapping[str, Any]) -> dict[str, Any]:
    record = dict(value)
    payload_json = record.pop("payload_json", None)
    if "payload" not in record and isinstance(payload_json, str):
        decoded = json.loads(payload_json)
        if not isinstance(decoded, Mapping):
            raise ValueError("research ledger payload_json must decode to an object")
        record["payload"] = dict(decoded)
    return record


def _payload(record: Mapping[str, Any], *, label: str) -> dict[str, Any]:
    value = record.get("payload")
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} ledger record must contain an object payload")
    return dict(value)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Step 2 H1 pairing timestamps must be timezone-aware")
    return value.astimezone(UTC)


def _decimal(value: object, *, label: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{label} must be a finite decimal") from exc
    if not parsed.is_finite():
        raise ValueError(f"{label} must be a finite decimal")
    return parsed


def assert_exact_h1_pair(
    *,
    histdata_start_utc: datetime,
    histdata_end_utc: datetime,
    twelve_start_utc: datetime,
    twelve_end_utc: datetime,
) -> dict[str, str]:
    """Require the exact same one-hour UTC interval after source-native construction."""

    hist_start = _utc(histdata_start_utc)
    hist_end = _utc(histdata_end_utc)
    twelve_start = _utc(twelve_start_utc)
    twelve_end = _utc(twelve_end_utc)
    if hist_end - hist_start != timedelta(hours=1):
        raise ValueError("HistData Step 2 pair candidate is not exactly one H1 interval")
    if twelve_end - twelve_start != timedelta(hours=1):
        raise ValueError("Twelve Data Step 2 pair candidate is not exactly one H1 interval")
    if hist_start != twelve_start or hist_end != twelve_end:
        raise ValueError("Step 2 H1 pair must have exact matching UTC start and end")
    return {
        "state": "exact_same_utc_h1_interval",
        "start_utc": hist_start.isoformat(),
        "end_utc": hist_end.isoformat(),
    }


def in_frozen_threshold_region(
    *, histdata_h1_atr_14_bps: object, twelve_data_h1_atr_14_bps: object, threshold_bps: object
) -> bool:
    """Executable form of the inclusive either-source +/-5 bps preregistered window."""

    hist = _decimal(histdata_h1_atr_14_bps, label="histdata_h1_atr_14_bps")
    twelve = _decimal(twelve_data_h1_atr_14_bps, label="twelve_data_h1_atr_14_bps")
    threshold = _decimal(threshold_bps, label="threshold_bps")
    if threshold not in {Decimal(20), Decimal(50)}:
        raise ValueError("Step 2 threshold region is defined only for 20 bps and 50 bps")
    return bool(
        abs(hist - threshold) <= THRESHOLD_REGION_WINDOW_BPS
        or abs(twelve - threshold) <= THRESHOLD_REGION_WINDOW_BPS
    )


def assert_repository_preregistration_manifest(manifest: Mapping[str, Any]) -> dict[str, str]:
    """Bind the checked-out code to the immutable repository preregistration manifest."""

    if manifest.get("manifest_version") != REPOSITORY_MANIFEST_VERSION:
        raise ValueError("Step 2 repository preregistration manifest version mismatch")
    if manifest.get("state") != "preregistered_no_result":
        raise ValueError("Step 2 repository manifest is not in preregistered_no_result state")
    if manifest.get("empirical_result_computed") is not False:
        raise ValueError("Step 2 repository manifest already claims an empirical result")
    if manifest.get("empirical_scoring_performed") is not False:
        raise ValueError("Step 2 repository manifest already claims empirical scoring")
    if manifest.get("qualification_id") != STEP2_QUALIFICATION_ID:
        raise ValueError("Step 2 repository manifest qualification_id mismatch")
    if manifest.get("research_family_id") != STEP2_RESEARCH_FAMILY_ID:
        raise ValueError("Step 2 repository manifest research_family_id mismatch")

    expected_contract_digest = step2_contract_digest()
    expected_family_digest = research_digest(build_step2_research_family_payload())
    if manifest.get("equivalence_contract_digest_sha256") != expected_contract_digest:
        raise ValueError("repository manifest contract digest does not match checked-out Step 2 code")
    if manifest.get("research_family_payload_digest_sha256") != expected_family_digest:
        raise ValueError("repository manifest family digest does not match checked-out Step 2 code")
    return {
        "state": "repository_preregistration_matches_checked_out_code",
        "contract_digest": expected_contract_digest,
        "research_family_digest": expected_family_digest,
    }


def assert_step2_scoring_prerequisites(
    *,
    manifest: Mapping[str, Any],
    research_ledger_records: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Fail closed unless repository and append-only D1 preregistration are identical."""

    repository = assert_repository_preregistration_manifest(manifest)
    records = [_normalize_ledger_record(record) for record in research_ledger_records]
    records.sort(key=lambda record: int(record.get("sequence", -1)))
    if not records or not verify_chain(records):
        raise ValueError("Step 2 scoring blocked: research ledger chain is invalid")

    family_records: list[dict[str, Any]] = []
    contract_records: list[dict[str, Any]] = []
    for record in records:
        record_type = str(record.get("record_type") or "")
        payload = record.get("payload")
        if not isinstance(payload, Mapping):
            continue
        if (
            record_type == RESEARCH_FAMILY_RECORD_TYPE
            and payload.get("research_family_id") == STEP2_RESEARCH_FAMILY_ID
        ):
            family_records.append(record)
        if (
            record_type == EQUIVALENCE_CONTRACT_RECORD_TYPE
            and payload.get("qualification_id") == STEP2_QUALIFICATION_ID
        ):
            contract_records.append(record)

    if len(family_records) != 1:
        raise ValueError("Step 2 scoring requires exactly one matching research-family ledger record")
    if len(contract_records) != 1:
        raise ValueError("Step 2 scoring requires exactly one matching equivalence-contract ledger record")

    family_record = family_records[0]
    contract_record = contract_records[0]
    if int(family_record["sequence"]) >= int(contract_record["sequence"]):
        raise ValueError("Step 2 research-family record must precede equivalence-contract record")
    if family_record.get("initiated_by") != "human":
        raise ValueError("Step 2 research-family ledger record must be human initiated")
    if contract_record.get("initiated_by") != "human":
        raise ValueError("Step 2 equivalence-contract ledger record must be human initiated")

    family_payload = _payload(family_record, label="Step 2 research-family")
    contract_payload = _payload(contract_record, label="Step 2 equivalence-contract")
    family_digest = research_digest(family_payload)
    contract_digest = research_digest(contract_payload)

    if family_digest != repository["research_family_digest"]:
        raise ValueError("D1 research-family digest does not equal repository preregistration digest")
    if contract_digest != repository["contract_digest"]:
        raise ValueError("D1 equivalence-contract digest does not equal repository preregistration digest")
    if family_payload != build_step2_research_family_payload():
        raise ValueError("D1 research-family payload is not byte-semantically identical to checked-out code")
    if contract_payload != build_step2_equivalence_contract_payload():
        raise ValueError("D1 equivalence-contract payload is not byte-semantically identical to checked-out code")

    return {
        "state": "step2_scoring_prerequisites_satisfied",
        "contract_digest": contract_digest,
        "research_family_digest": family_digest,
        "research_family_record_digest": family_record["record_digest"],
        "equivalence_contract_record_digest": contract_record["record_digest"],
        "research_family_sequence": int(family_record["sequence"]),
        "equivalence_contract_sequence": int(contract_record["sequence"]),
    }