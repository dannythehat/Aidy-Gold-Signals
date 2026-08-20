from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from datetime import datetime
from hashlib import sha256
from typing import Any

from aidy.context_packet import CONTEXT_PACKET_VERSION, verify_context_hash
from aidy.cross_market import ENABLED_SERIES
from aidy.feature_engine import TIMEFRAMES
from aidy.master_trader_contract import (
    SUPPORTED_SYMBOL,
    master_trader_decision_digest,
    validate_master_trader_decision,
)
from aidy.pit_reconstruction import normalize_as_of
from aidy.setup_detector import (
    SETUP_DEFINITIONS,
    SETUP_DETECTION_VERSION,
    SETUP_DETECTOR_VERSION,
    SETUP_TAXONOMY_VERSION,
    taxonomy_manifest,
    verify_setup_detection_digest,
)

SAFETY_GATES_VERSION = "aidy_deterministic_safety_gates_v1"
SAFETY_GATE_MANIFEST_VERSION = "aidy_safety_gate_manifest_v1"
DEFAULT_MAX_CONTEXT_AGE_SECONDS = 300
DEFAULT_MAX_CROSS_MARKET_AGE_DAYS = 7
SUPPORTED_INSTRUCTION_TYPES = ("market_evaluation", "active_signal_management")

_ACTIONS_BY_INSTRUCTION = {
    "market_evaluation": {"new_trade", "no_trade"},
    "active_signal_management": {"manage_trade", "close_trade", "no_trade"},
}
_SETUP_DIRECTIONS = {
    str(item["setup_id"]): str(item["direction"]) for item in SETUP_DEFINITIONS
}


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value: object) -> str:
    return sha256(_canonical(value).encode()).hexdigest()


def compute_safety_gate_digest(packet: Mapping[str, Any]) -> str:
    body = dict(packet)
    body.pop("gate_digest", None)
    return _digest(body)


def verify_safety_gate_digest(packet: Mapping[str, Any]) -> bool:
    supplied = str(packet.get("gate_digest") or "")
    return bool(supplied) and supplied == compute_safety_gate_digest(packet)


def _gate(
    checks: list[dict[str, Any]],
    name: str,
    passed: bool,
    ok: str,
    blocked: str,
    detail: str | None = None,
) -> None:
    checks.append(
        {
            "gate": name,
            "passed": bool(passed),
            "reason_code": ok if passed else blocked,
            "detail": detail,
        }
    )


def _blockers(checks: Iterable[Mapping[str, Any]]) -> list[str]:
    return [str(x["reason_code"]) for x in checks if x.get("passed") is not True]


def _known_lifecycle(context: Mapping[str, Any]) -> tuple[bool, str]:
    lifecycle = context.get("aidy_signal_lifecycle")
    if not isinstance(lifecycle, Mapping):
        return False, "aidy_signal_lifecycle_missing"
    if lifecycle.get("evidence_state") != "known":
        return False, "aidy_signal_lifecycle_unknown"
    signals = lifecycle.get("active_signals")
    state = str(lifecycle.get("lifecycle_state") or "")
    if not isinstance(signals, list) or state not in {"none", "active"}:
        return False, "aidy_signal_lifecycle_invalid"
    if (state == "none" and signals) or (state == "active" and not signals):
        return False, "aidy_signal_lifecycle_conflict"

    signal_ids: set[str] = set()
    decision_ids: set[str] = set()
    for item in signals:
        if not isinstance(item, Mapping):
            return False, "aidy_signal_lifecycle_invalid"
        signal_id = str(item.get("aidy_signal_id") or "")
        decision_id = str(item.get("originating_decision_id") or "")
        if not signal_id or not decision_id:
            return False, "aidy_signal_lifecycle_incomplete"
        if signal_id in signal_ids or decision_id in decision_ids:
            return False, "aidy_signal_lifecycle_conflict"
        signal_ids.add(signal_id)
        decision_ids.add(decision_id)
    return True, "pre_signal_lifecycle_consistent"


def _pre_quality_checks(context: Mapping[str, Any], checks: list[dict[str, Any]]) -> None:
    quality = context.get("data_quality")
    quality = quality if isinstance(quality, Mapping) else {}
    gold = context.get("gold")
    gold = gold if isinstance(gold, Mapping) else {}
    frames = gold.get("timeframes")
    frames = frames if isinstance(frames, Mapping) else {}
    missing = quality.get("missing_gold_timeframes")
    frames_ok = (
        isinstance(missing, list)
        and not missing
        and all(
            isinstance(frames.get(tf), Mapping) and frames[tf].get("state") == "known"
            for tf in TIMEFRAMES
        )
    )
    _gate(
        checks,
        "gold_timeframe_completeness",
        frames_ok,
        "pre_gold_timeframes_complete",
        "pre_gold_timeframes_missing",
    )

    quote = gold.get("quote_context")
    quote = quote if isinstance(quote, Mapping) else {}
    age = quality.get("quote_age_seconds")
    limit = quality.get("quote_stale_after_seconds")
    quote_ok = (
        quality.get("quote_state") == "known"
        and quality.get("quote_freshness") == "fresh"
        and quote.get("quote_state") == "known"
        and isinstance(age, int)
        and not isinstance(age, bool)
        and isinstance(limit, int)
        and not isinstance(limit, bool)
        and 0 <= age <= limit
        and quote.get("quote_age_seconds") == age
    )
    _gate(
        checks,
        "quote_freshness",
        quote_ok,
        "pre_quote_fresh",
        "pre_quote_stale_or_unknown",
    )
    _gate(
        checks,
        "spread_availability",
        quality.get("spread_state") == "known" and quote.get("spread") is not None,
        "pre_spread_known",
        "pre_spread_unknown",
    )

    event = context.get("event_risk")
    event = event if isinstance(event, Mapping) else {}
    macro_ok = (
        quality.get("macro_evidence_state") == "known"
        and event.get("evidence_state") == "known"
    )
    _gate(
        checks,
        "macro_evidence",
        macro_ok,
        "pre_macro_evidence_known",
        "pre_macro_evidence_unknown",
    )

    missing_cross = quality.get("cross_market_missing_series")
    ages = quality.get("cross_market_observation_age_days")
    ages = ages if isinstance(ages, Mapping) else {}
    cross = context.get("cross_market")
    cross = cross if isinstance(cross, Mapping) else {}
    series = cross.get("series")
    series = series if isinstance(series, Mapping) else {}
    cross_ok = (
        isinstance(missing_cross, list)
        and not missing_cross
        and set(ages) == set(ENABLED_SERIES)
        and all(
            isinstance(ages.get(sid), int)
            and not isinstance(ages.get(sid), bool)
            and 0 <= ages[sid] <= DEFAULT_MAX_CROSS_MARKET_AGE_DAYS
            and isinstance(series.get(sid), Mapping)
            and series[sid].get("state") == "known"
            and series[sid].get("observation_age_days") == ages[sid]
            for sid in ENABLED_SERIES
        )
    )
    _gate(
        checks,
        "cross_market_completeness",
        cross_ok,
        "pre_cross_market_complete",
        "pre_cross_market_incomplete_or_stale",
    )
    _gate(
        checks,
        "signal_state_evidence",
        quality.get("aidy_signal_state") == "known",
        "pre_signal_state_known",
        "pre_signal_state_unknown",
    )


def evaluate_pre_model_safety(
    context: Mapping[str, Any],
    *,
    now_utc: datetime | str,
    instruction_type: str,
    seen_context_hashes: Iterable[str] = (),
    max_context_age_seconds: int = DEFAULT_MAX_CONTEXT_AGE_SECONDS,
) -> dict[str, Any]:
    if max_context_age_seconds < 0:
        raise ValueError("max_context_age_seconds must be non-negative.")
    now = normalize_as_of(now_utc)
    checks: list[dict[str, Any]] = []
    context_hash = str(context.get("context_hash") or "")

    _gate(
        checks,
        "instruction_type",
        instruction_type in SUPPORTED_INSTRUCTION_TYPES,
        "pre_instruction_type_allowed",
        "pre_instruction_type_unsupported",
        instruction_type,
    )
    _gate(
        checks,
        "context_version",
        context.get("context_packet_version") == CONTEXT_PACKET_VERSION,
        "pre_context_version_valid",
        "pre_context_version_invalid",
    )
    _gate(
        checks,
        "context_hash",
        verify_context_hash(context),
        "pre_context_hash_valid",
        "pre_context_hash_invalid",
    )
    _gate(
        checks,
        "symbol",
        context.get("symbol") == SUPPORTED_SYMBOL,
        "pre_symbol_valid",
        "pre_symbol_invalid",
    )
    boundary_ok = (
        context.get("objective_only") is True
        and context.get("retrospective_history_included") is False
        and context.get("broker_follower_state_included") is False
    )
    _gate(
        checks,
        "decision_boundary",
        boundary_ok,
        "pre_decision_boundary_valid",
        "pre_decision_boundary_invalid",
    )

    try:
        as_of = normalize_as_of(context.get("as_of_utc"))
        age = (now - as_of).total_seconds()
        timestamp_ok = age >= 0
        fresh = timestamp_ok and age <= max_context_age_seconds
    except (TypeError, ValueError):
        as_of, age, timestamp_ok, fresh = None, None, False, False
    _gate(
        checks,
        "context_timestamp",
        timestamp_ok,
        "pre_context_timestamp_valid",
        "pre_context_timestamp_future_or_invalid",
    )
    _gate(
        checks,
        "context_freshness",
        fresh,
        "pre_context_fresh",
        "pre_context_stale",
        None if age is None else str(int(age)),
    )
    seen = {str(item) for item in seen_context_hashes}
    _gate(
        checks,
        "duplicate_context",
        bool(context_hash) and context_hash not in seen,
        "pre_context_not_duplicate",
        "pre_context_duplicate",
    )

    _pre_quality_checks(context, checks)
    session = context.get("session")
    session = session if isinstance(session, Mapping) else {}
    _gate(
        checks,
        "session_consistency",
        session.get("session_code_consistent") is True,
        "pre_session_consistent",
        "pre_session_conflict",
    )
    lifecycle_ok, lifecycle_code = _known_lifecycle(context)
    _gate(
        checks,
        "aidy_signal_lifecycle",
        lifecycle_ok,
        "pre_signal_lifecycle_consistent",
        lifecycle_code,
    )

    blocked = _blockers(checks)
    result: dict[str, Any] = {
        "gate_version": SAFETY_GATES_VERSION,
        "stage": "pre_model",
        "status": "passed" if not blocked else "blocked",
        "model_call_allowed": not blocked,
        "instruction_type": instruction_type,
        "context_hash": context_hash,
        "context_as_of_utc": None if as_of is None else as_of.isoformat(),
        "checked_at_utc": now.isoformat(),
        "max_context_age_seconds": max_context_age_seconds,
        "reason_codes": ["pre_model_allowed"] if not blocked else blocked,
        "checks": checks,
    }
    result["gate_digest"] = compute_safety_gate_digest(result)
    return result


def _pre_receipt_ok(receipt: Mapping[str, Any], context_hash: str) -> bool:
    checks = receipt.get("checks")
    return (
        receipt.get("stage") == "pre_model"
        and receipt.get("gate_version") == SAFETY_GATES_VERSION
        and verify_safety_gate_digest(receipt)
        and receipt.get("status") == "passed"
        and receipt.get("model_call_allowed") is True
        and receipt.get("reason_codes") == ["pre_model_allowed"]
        and isinstance(checks, list)
        and all(isinstance(x, Mapping) and x.get("passed") is True for x in checks)
        and receipt.get("context_hash") == context_hash
    )


def _setup_ok(
    context: Mapping[str, Any],
    decision: Mapping[str, Any],
    detection: Mapping[str, Any] | None,
) -> tuple[bool, str]:
    if not isinstance(detection, Mapping):
        return False, "post_setup_evidence_missing"
    versions_ok = (
        detection.get("detection_version") == SETUP_DETECTION_VERSION
        and detection.get("detector_version") == SETUP_DETECTOR_VERSION
        and detection.get("taxonomy_version") == SETUP_TAXONOMY_VERSION
    )
    if not versions_ok:
        return False, "post_setup_evidence_version_invalid"
    if detection.get("taxonomy_digest") != taxonomy_manifest()["taxonomy_digest"]:
        return False, "post_setup_taxonomy_digest_invalid"
    if not verify_setup_detection_digest(detection):
        return False, "post_setup_evidence_digest_invalid"
    if detection.get("source_context_hash") != context.get("context_hash"):
        return False, "post_setup_context_mismatch"
    if detection.get("symbol") != SUPPORTED_SYMBOL:
        return False, "post_setup_symbol_invalid"
    try:
        if normalize_as_of(detection.get("as_of_utc")) != normalize_as_of(
            context.get("as_of_utc")
        ):
            return False, "post_setup_timestamp_mismatch"
    except (TypeError, ValueError):
        return False, "post_setup_timestamp_invalid"
    safe_flags = (
        detection.get("decision_input_allowed") is True
        and detection.get("pit_eligible") is True
        and detection.get("future_derived") is False
        and detection.get("trading_decision_made") is False
        and detection.get("trade_recommendation_made") is False
    )
    if not safe_flags:
        return False, "post_setup_evidence_not_pit_safe"

    candidates = detection.get("candidates")
    if not isinstance(candidates, list):
        return False, "post_setup_evidence_invalid"
    by_id: dict[str, str] = {}
    for item in candidates:
        if not isinstance(item, Mapping):
            return False, "post_setup_evidence_invalid"
        setup_id = str(item.get("setup_id") or "")
        direction = str(item.get("direction") or "")
        if _SETUP_DIRECTIONS.get(setup_id) != direction:
            return False, "post_setup_candidate_definition_invalid"
        by_id[setup_id] = direction

    declared = detection.get("candidate_setup_ids")
    if not isinstance(declared, list) or sorted(by_id) != sorted(map(str, declared)):
        return False, "post_setup_candidate_list_mismatch"
    setup_codes = decision.get("setup_codes")
    if not isinstance(setup_codes, list) or not setup_codes:
        return False, "post_setup_codes_missing"
    if any(str(code) not in by_id for code in setup_codes):
        return False, "post_setup_not_in_current_evidence"
    direction = str(decision.get("direction") or "")
    if any(by_id[str(code)] != direction for code in setup_codes):
        return False, "post_setup_direction_conflict"
    return True, "post_setup_evidence_confirmed"


def _target_count(context: Mapping[str, Any], decision_id: str) -> int:
    lifecycle = context.get("aidy_signal_lifecycle")
    lifecycle = lifecycle if isinstance(lifecycle, Mapping) else {}
    signals = lifecycle.get("active_signals")
    signals = signals if isinstance(signals, list) else []
    return sum(
        1
        for item in signals
        if isinstance(item, Mapping)
        and str(item.get("originating_decision_id") or "") == decision_id
    )


def evaluate_post_model_safety(
    *,
    context: Mapping[str, Any],
    pre_model_result: Mapping[str, Any],
    gateway_result: Mapping[str, Any],
    now_utc: datetime | str,
    setup_detection: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    now = normalize_as_of(now_utc)
    checks: list[dict[str, Any]] = []
    context_hash = str(context.get("context_hash") or "")

    _gate(
        checks,
        "pre_model_receipt",
        _pre_receipt_ok(pre_model_result, context_hash),
        "post_pre_model_receipt_valid",
        "post_pre_model_receipt_invalid",
    )
    _gate(
        checks,
        "context_hash",
        verify_context_hash(context),
        "post_context_hash_valid",
        "post_context_hash_invalid",
    )
    try:
        context_as_of = normalize_as_of(context.get("as_of_utc"))
        age = (now - context_as_of).total_seconds()
        max_age = int(
            pre_model_result.get(
                "max_context_age_seconds",
                DEFAULT_MAX_CONTEXT_AGE_SECONDS,
            )
        )
        still_fresh = 0 <= age <= max_age
    except (TypeError, ValueError):
        context_as_of, age, still_fresh = None, None, False
    _gate(
        checks,
        "context_still_fresh",
        still_fresh,
        "post_context_still_fresh",
        "post_context_became_stale",
        None if age is None else str(int(age)),
    )

    gateway_ok = (
        gateway_result.get("status") == "accepted"
        and gateway_result.get("publication_allowed") is True
        and gateway_result.get("failure_reason") is None
    )
    _gate(
        checks,
        "gateway_status",
        gateway_ok,
        "post_gateway_accepted",
        "post_gateway_not_accepted",
    )

    raw = gateway_result.get("structured_decision")
    decision: dict[str, Any] | None = None
    error: str | None = None
    try:
        if not isinstance(raw, Mapping):
            raise TypeError("structured_decision must be a mapping")
        decision = validate_master_trader_decision(raw)
    except (TypeError, ValueError) as exc:
        error = type(exc).__name__
    _gate(
        checks,
        "decision_contract",
        decision is not None,
        "post_decision_contract_valid",
        "post_decision_contract_invalid",
        error,
    )
    digest_ok = (
        decision is not None
        and gateway_result.get("decision_digest") == master_trader_decision_digest(decision)
    )
    _gate(
        checks,
        "decision_digest",
        digest_ok,
        "post_decision_digest_valid",
        "post_decision_digest_invalid",
    )

    if decision is None:
        action = None
        time_match = not_future = not_expired = instruction_ok = False
    else:
        action = str(decision["action"])
        evaluated = normalize_as_of(decision["evaluated_at_utc"])
        valid_until = normalize_as_of(decision["valid_until_utc"])
        time_match = context_as_of is not None and evaluated == context_as_of
        not_future = evaluated <= now
        not_expired = valid_until > now
        instruction = str(pre_model_result.get("instruction_type") or "")
        instruction_ok = action in _ACTIONS_BY_INSTRUCTION.get(instruction, set())

    _gate(
        checks,
        "decision_context_time",
        time_match,
        "post_decision_context_time_match",
        "post_decision_context_time_mismatch",
    )
    _gate(
        checks,
        "decision_not_future",
        not_future,
        "post_decision_time_not_future",
        "post_decision_time_future",
    )
    _gate(
        checks,
        "decision_validity",
        not_expired,
        "post_decision_not_expired",
        "post_decision_expired",
    )
    _gate(
        checks,
        "instruction_action_consistency",
        instruction_ok,
        "post_action_allowed_for_instruction",
        "post_action_not_allowed_for_instruction",
    )

    if decision is not None and action == "new_trade":
        setup_passed, setup_code = _setup_ok(context, decision, setup_detection)
        _gate(
            checks,
            "current_setup_evidence",
            setup_passed,
            "post_setup_evidence_confirmed",
            setup_code,
        )
    else:
        _gate(
            checks,
            "current_setup_evidence",
            True,
            "post_setup_evidence_not_required",
            "post_setup_evidence_invalid",
        )

    target_passed, target_code = True, "post_target_not_required"
    if decision is not None and action in {"manage_trade", "close_trade"}:
        count = _target_count(context, str(decision.get("target_decision_id") or ""))
        target_passed = count == 1
        target_code = (
            "post_target_active"
            if count == 1
            else "post_target_not_active"
            if count == 0
            else "post_target_ambiguous"
        )
    _gate(
        checks,
        "active_target_state",
        target_passed,
        target_code if target_passed else "post_target_active",
        target_code if not target_passed else "post_target_invalid",
    )

    blocked = _blockers(checks)
    admitted = not blocked
    downstream = "no_action" if admitted and action == "no_trade" else action if admitted else None
    result: dict[str, Any] = {
        "gate_version": SAFETY_GATES_VERSION,
        "stage": "post_model",
        "status": "passed" if admitted else "blocked",
        "decision_admitted": admitted,
        "actionable": bool(admitted and action != "no_trade"),
        "downstream_action": downstream,
        "decision_action": action,
        "context_hash": context_hash,
        "checked_at_utc": now.isoformat(),
        "reason_codes": (
            ["post_no_trade_accepted"]
            if admitted and action == "no_trade"
            else ["post_decision_admitted"]
            if admitted
            else blocked
        ),
        "checks": checks,
    }
    result["gate_digest"] = compute_safety_gate_digest(result)
    return result


def safety_gate_manifest() -> dict[str, Any]:
    manifest: dict[str, Any] = {
        "manifest_version": SAFETY_GATE_MANIFEST_VERSION,
        "gate_version": SAFETY_GATES_VERSION,
        "digest_algorithm": "sha256",
        "supported_symbol": SUPPORTED_SYMBOL,
        "supported_instruction_types": list(SUPPORTED_INSTRUCTION_TYPES),
        "max_context_age_seconds_default": DEFAULT_MAX_CONTEXT_AGE_SECONDS,
        "max_cross_market_age_days_default": DEFAULT_MAX_CROSS_MARKET_AGE_DAYS,
        "pre_model_blocks_duplicate_context": True,
        "pre_model_requires_fresh_complete_context": True,
        "post_model_revalidates_day20_contract": True,
        "post_model_requires_current_setup_for_new_trade": True,
        "post_model_requires_exact_active_target_for_management": True,
        "confidence_can_bypass_gate": False,
        "valid_no_trade_is_success": True,
        "no_trade_has_external_action": False,
        "broker_or_follower_state_allowed": False,
    }
    manifest["manifest_digest"] = _digest(manifest)
    return manifest
