from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from aidy.master_trader_contract_v2 import (
    master_trader_decision_digest_versioned,
    validate_master_trader_decision_versioned,
)
from aidy.pit_reconstruction import normalize_as_of
from aidy.safety_gates import (
    DEFAULT_MAX_CONTEXT_AGE_SECONDS,
    SAFETY_GATES_VERSION,
    _ACTIONS_BY_INSTRUCTION,
    _blockers,
    _gate,
    _pre_receipt_ok,
    _setup_ok,
    _target_count,
    compute_safety_gate_digest,
)
from aidy.context_packet import verify_context_hash

SAFETY_GATES_V2_RUNTIME_VERSION = "aidy_day52_versioned_post_model_safety_v1"


def evaluate_post_model_safety_v2(
    *,
    context: Mapping[str, Any],
    pre_model_result: Mapping[str, Any],
    gateway_result: Mapping[str, Any],
    now_utc: datetime | str,
    setup_detection: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Day-52 version-aware post-model safety validation.

    The Day-22 deterministic safety semantics remain authoritative. This
    adapter changes only the Master Trader contract reader/digest so current
    V2 falsifiable decisions can traverse the same gates while historical V1
    decisions remain readable.
    """

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
        decision = validate_master_trader_decision_versioned(raw)
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
        and gateway_result.get("decision_digest")
        == master_trader_decision_digest_versioned(decision)
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
        "max_context_age_seconds": pre_model_result.get(
            "max_context_age_seconds", DEFAULT_MAX_CONTEXT_AGE_SECONDS
        ),
        "reason_codes": (
            ["post_no_trade_accepted"]
            if admitted and action == "no_trade"
            else ["post_decision_admitted"]
            if admitted
            else blocked
        ),
        "checks": checks,
        "runtime_adapter_version": SAFETY_GATES_V2_RUNTIME_VERSION,
    }
    # Day 34 verifies Day-22 receipt digests and tolerates extra immutable
    # metadata, so the adapter identity is itself authenticated here.
    result["gate_digest"] = compute_safety_gate_digest(result)
    return result
