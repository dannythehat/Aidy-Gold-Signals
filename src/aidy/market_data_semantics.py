from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from hashlib import sha256
from typing import Any

from aidy.historical_backfill import (
    DERIVATION_VERSION,
    HISTDATA_DATASET,
    HISTDATA_PRICE_BASIS,
    HISTDATA_SOURCE,
    HISTDATA_SOURCE_TIMEZONE,
)
from aidy.research_trials import digest as research_digest
from aidy.research_trials import verify_chain
from aidy.twelve_data_market import (
    ADAPTER_VERSION,
    AGGREGATE_SOURCE,
    AIDY_SYMBOL,
    RAW_M1_SOURCE,
    SESSION_CALENDAR_VERSION,
    TWELVE_DATA_SOURCE,
    TWELVE_DATA_SYMBOL,
)

SEMANTIC_IDENTITY_VERSION = "aidy_market_data_semantic_identity_v1"
COMPATIBILITY_VERSION = "aidy_market_data_semantic_compatibility_v1"
EQUIVALENCE_CONTRACT_RECORD_TYPE = "market_data_equivalence_contract_registered"
QUALIFICATION_RESULT_RECORD_TYPE = "qualification_result"


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest(value: object) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _finish(body: dict[str, Any]) -> dict[str, Any]:
    body = dict(body)
    body["semantic_identity_version"] = SEMANTIC_IDENTITY_VERSION
    body["semantic_identity_digest"] = digest(body)
    return body


def _hex64(value: object) -> bool:
    text = str(value or "").lower()
    return len(text) == 64 and all(ch in "0123456789abcdef" for ch in text)


def histdata_semantic_identity() -> dict[str, Any]:
    return _finish(
        {
            "provider_source_family": HISTDATA_SOURCE,
            "vendor_symbol_mapping": f"{AIDY_SYMBOL}->{AIDY_SYMBOL}",
            "price_basis": HISTDATA_PRICE_BASIS,
            "raw_timeframe_source": HISTDATA_DATASET,
            "session_calendar_version": "histdata_source_time_fixed_est_v1",
            "timezone_dst_policy": HISTDATA_SOURCE_TIMEZONE,
            "maintenance_gap_policy": "source_observed_no_aidy_ny_session_filter_v1",
            "candle_aggregation_construction_version": DERIVATION_VERSION,
            "current_bucket_completeness_rule_version": "retrospective_timeframe_closed_by_nominal_end_v1",
        }
    )


def twelve_data_semantic_identity() -> dict[str, Any]:
    return _finish(
        {
            "provider_source_family": TWELVE_DATA_SOURCE,
            "vendor_symbol_mapping": f"{TWELVE_DATA_SYMBOL}->{AIDY_SYMBOL}",
            "price_basis": "vendor_ohlc_price_basis_not_contractually_identified",
            "raw_timeframe_source": RAW_M1_SOURCE,
            "session_calendar_version": SESSION_CALENDAR_VERSION,
            "timezone_dst_policy": "America/New_York_IANA_DST_aware",
            "maintenance_gap_policy": "sun_1800_to_fri_1700_ny_with_daily_1700_1800_break_v1",
            "candle_aggregation_construction_version": f"{ADAPTER_VERSION}+{AGGREGATE_SOURCE}",
            "current_bucket_completeness_rule_version": "all_expected_market_minutes_closed_before_bucket_ready_v1",
        }
    )


def verify_semantic_identity(identity: Mapping[str, Any]) -> bool:
    body = dict(identity)
    supplied = str(body.pop("semantic_identity_digest", ""))
    if body.get("semantic_identity_version") != SEMANTIC_IDENTITY_VERSION:
        return False
    required = {
        "provider_source_family",
        "vendor_symbol_mapping",
        "price_basis",
        "raw_timeframe_source",
        "session_calendar_version",
        "timezone_dst_policy",
        "maintenance_gap_policy",
        "candle_aggregation_construction_version",
        "current_bucket_completeness_rule_version",
    }
    if not required.issubset(body):
        return False
    if any(body.get(key) in (None, "") for key in required):
        return False
    return supplied == digest(body)


def identity_from_source_links(source_links: Mapping[str, Any]) -> dict[str, Any]:
    sources: set[str] = set()
    derivations: set[str] = set()
    for links in source_links.values():
        if not isinstance(links, list):
            continue
        for item in links:
            if not isinstance(item, Mapping):
                continue
            source = str(item.get("source") or "").strip()
            if source:
                sources.add(source)
            derivation = str(item.get("derivation_version") or "").strip()
            if derivation:
                derivations.add(derivation)

    histdata_markers = {HISTDATA_SOURCE}
    twelve_markers = {TWELVE_DATA_SOURCE, RAW_M1_SOURCE, AGGREGATE_SOURCE}
    is_histdata = bool(sources & histdata_markers) or DERIVATION_VERSION in derivations
    is_twelve = bool(sources & twelve_markers)
    if is_histdata and is_twelve:
        raise ValueError("mixed market-data semantic families are forbidden")
    if is_histdata:
        return histdata_semantic_identity()
    if is_twelve:
        return twelve_data_semantic_identity()
    raise ValueError("market-data semantic identity cannot be established from source links")


def identity_from_feature_packet(feature_packet: Mapping[str, Any]) -> dict[str, Any]:
    source_links = feature_packet.get("source_links")
    if not isinstance(source_links, Mapping):
        raise ValueError("feature packet lacks source_links required for semantic identity")
    return identity_from_source_links(source_links)


def _normalize_ledger_record(value: Mapping[str, Any]) -> dict[str, Any]:
    record = dict(value)
    if "payload" not in record:
        payload_json = record.pop("payload_json", None)
        if isinstance(payload_json, str):
            decoded = json.loads(payload_json)
            if not isinstance(decoded, Mapping):
                raise ValueError("research ledger payload_json must decode to an object")
            record["payload"] = dict(decoded)
    return record


def accepted_market_data_equivalences(
    research_ledger_records: Iterable[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Resolve only PASS equivalence results from a valid append-only research ledger chain."""

    records = [_normalize_ledger_record(value) for value in research_ledger_records]
    records.sort(key=lambda item: int(item.get("sequence", -1)))
    if not records:
        return {}
    if not verify_chain(records):
        raise ValueError("research ledger chain is invalid; equivalence cannot be accepted")

    contracts: dict[str, tuple[dict[str, Any], str]] = {}
    for record in records:
        if record.get("record_type") != EQUIVALENCE_CONTRACT_RECORD_TYPE:
            continue
        payload = record.get("payload")
        if not isinstance(payload, Mapping):
            raise ValueError("equivalence contract ledger record requires an object payload")
        qualification_id = str(payload.get("qualification_id") or "").strip()
        left = str(payload.get("source_identity_a_digest") or "")
        right = str(payload.get("source_identity_b_digest") or "")
        if not qualification_id or not _hex64(left) or not _hex64(right):
            raise ValueError("equivalence contract ledger record is missing semantic identity binding")
        contract_payload = dict(payload)
        contract_digest = research_digest(contract_payload)
        contracts[qualification_id] = (contract_payload, contract_digest)

    accepted: dict[str, dict[str, Any]] = {}
    for record in records:
        if record.get("record_type") != QUALIFICATION_RESULT_RECORD_TYPE:
            continue
        payload = record.get("payload")
        if not isinstance(payload, Mapping):
            continue
        if payload.get("outcome") != "pass" or payload.get("inheritance_allowed") is not True:
            continue
        qualification_id = str(payload.get("qualification_id") or "")
        contract = contracts.get(qualification_id)
        if contract is None:
            continue
        contract_payload, expected_contract_digest = contract
        if str(payload.get("contract_digest") or "") != expected_contract_digest:
            continue
        evidence_digest = str(payload.get("evidence_digest") or "")
        if not _hex64(evidence_digest):
            continue
        left = str(contract_payload["source_identity_a_digest"])
        right = str(contract_payload["source_identity_b_digest"])
        acceptance = {
            "qualification_id": qualification_id,
            "contract_digest": expected_contract_digest,
            "evidence_digest": evidence_digest,
            "qualification_result_record_digest": record["record_digest"],
            "outcome": "pass",
            "inheritance_allowed": True,
        }
        accepted[f"{left}:{right}"] = acceptance
        accepted[f"{right}:{left}"] = acceptance
    return accepted


def assert_semantic_compatible(
    query_identity: Mapping[str, Any],
    candidate_identity: Mapping[str, Any],
    *,
    accepted_equivalence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if not verify_semantic_identity(query_identity):
        raise ValueError("query market-data semantic identity is invalid")
    if not verify_semantic_identity(candidate_identity):
        raise ValueError("candidate market-data semantic identity is invalid")
    query_digest = str(query_identity["semantic_identity_digest"])
    candidate_digest = str(candidate_identity["semantic_identity_digest"])
    if query_digest == candidate_digest:
        return {
            "compatibility_version": COMPATIBILITY_VERSION,
            "state": "same_semantic_identity",
            "query_identity_digest": query_digest,
            "candidate_identity_digest": candidate_digest,
            "equivalence_contract_digest": None,
            "qualification_result_record_digest": None,
        }
    if accepted_equivalence is not None:
        contract_digest = str(accepted_equivalence.get("contract_digest") or "")
        result_record_digest = str(
            accepted_equivalence.get("qualification_result_record_digest") or ""
        )
        if (
            accepted_equivalence.get("outcome") != "pass"
            or accepted_equivalence.get("inheritance_allowed") is not True
            or not _hex64(contract_digest)
            or not _hex64(result_record_digest)
        ):
            raise ValueError("market-data equivalence acceptance record is invalid")
        return {
            "compatibility_version": COMPATIBILITY_VERSION,
            "state": "qualified_equivalence_contract",
            "query_identity_digest": query_digest,
            "candidate_identity_digest": candidate_digest,
            "equivalence_contract_digest": contract_digest,
            "qualification_result_record_digest": result_record_digest,
        }
    raise ValueError("cross-source analogue comparison blocked: market-data semantic identities differ")
