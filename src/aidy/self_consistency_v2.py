from __future__ import annotations

import copy
from collections import Counter
from collections.abc import Awaitable, Mapping
from decimal import Decimal
from typing import Any, Protocol

from aidy.master_trader_contract_v2 import (
    master_trader_decision_digest_versioned,
    validate_master_trader_decision_versioned,
)
from aidy.openai_gateway import OPENAI_MAX_ATTEMPTS
from aidy.openai_gateway_v2 import openai_gateway_manifest_v2
from aidy.safety_gates import verify_safety_gate_digest
from aidy.safety_gates_v2 import evaluate_post_model_safety_v2
from aidy.self_consistency import (
    DISAGREEMENT_VERSION,
    SAFE_MAJORITY,
    SAMPLE_COUNT,
    _bounded_totals,
    _gateway_metadata_ok,
    canonical_json,
    digest,
)

SELF_CONSISTENCY_VERSION_V2 = "aidy_master_trader_self_consistency_v2_falsifiable"
SELF_CONSISTENCY_MANIFEST_VERSION_V2 = "aidy_self_consistency_manifest_v2_falsifiable"


class MasterTraderGatewayV2(Protocol):
    def evaluate(self, evidence_bundle: Mapping[str, Any]) -> Awaitable[dict[str, Any]]: ...


def _number_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise TypeError("Action-semantic numeric values cannot be boolean.")
    number = Decimal(str(value))
    if not number.is_finite():
        raise ValueError("Action-semantic numeric values must be finite decimals.")
    text = format(number, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def action_semantic_identity_v2(decision: Mapping[str, Any]) -> dict[str, Any]:
    """Vote on external action semantics, never confidence or prose."""

    normalized = validate_master_trader_decision_versioned(decision)
    action = str(normalized["action"])
    identity: dict[str, Any] = {"action": action}
    if action == "new_trade":
        identity.update(
            {
                "direction": normalized["direction"],
                "setup_codes": sorted(str(code) for code in normalized["setup_codes"]),
                "entry_type": normalized["entry_type"],
                "market_reference_price": _number_text(normalized["market_reference_price"]),
                "stop_loss": _number_text(normalized["stop_loss"]),
                "targets": [_number_text(value) for value in normalized["targets"]],
            }
        )
    elif action == "manage_trade":
        identity.update(
            {
                "target_decision_id": normalized["target_decision_id"],
                "management_instruction": normalized["management_instruction"],
                "new_stop_loss": _number_text(normalized["new_stop_loss"]),
                "new_targets": [_number_text(value) for value in normalized["new_targets"]],
            }
        )
    elif action == "close_trade":
        identity.update(
            {
                "target_decision_id": normalized["target_decision_id"],
                "close_scope": normalized["close_scope"],
            }
        )
    return identity


def vote_identity_digest_v2(decision: Mapping[str, Any]) -> str:
    return digest(action_semantic_identity_v2(decision))


def _sample_receipt_v2(
    *,
    sample_index: int,
    frozen_bundle_digest: str,
    frozen_config_digest: str,
    gateway_result: Mapping[str, Any],
    post_model_receipt: Mapping[str, Any],
) -> dict[str, Any]:
    gateway = copy.deepcopy(dict(gateway_result))
    post = copy.deepcopy(dict(post_model_receipt))
    metadata_ok = _gateway_metadata_ok(gateway)
    decision: dict[str, Any] | None = None
    decision_digest: str | None = None
    vote_identity: dict[str, Any] | None = None
    vote_digest: str | None = None
    contract_valid = False
    raw = gateway.get("structured_decision")
    try:
        if isinstance(raw, Mapping):
            decision = validate_master_trader_decision_versioned(raw)
            decision_digest = master_trader_decision_digest_versioned(decision)
            contract_valid = gateway.get("decision_digest") == decision_digest
            if contract_valid:
                vote_identity = action_semantic_identity_v2(decision)
                vote_digest = digest(vote_identity)
    except (TypeError, ValueError):
        decision = None

    post_digest_valid = verify_safety_gate_digest(post)
    post_passed = (
        post_digest_valid
        and post.get("stage") == "post_model"
        and post.get("status") == "passed"
        and post.get("decision_admitted") is True
    )
    action_matches = decision is not None and post.get("decision_action") == decision.get("action")
    gateway_accepted = (
        gateway.get("status") == "accepted"
        and gateway.get("publication_allowed") is True
        and gateway.get("failure_reason") is None
    )
    vote_eligible = bool(
        metadata_ok
        and gateway_accepted
        and contract_valid
        and post_passed
        and action_matches
        and vote_digest
    )
    return {
        "sample_index": sample_index,
        "frozen_bundle_digest": frozen_bundle_digest,
        "frozen_config_digest": frozen_config_digest,
        "gateway_status": gateway.get("status"),
        "gateway_failure_reason": gateway.get("failure_reason"),
        "publication_allowed": gateway.get("publication_allowed"),
        "request_digest": gateway.get("request_digest"),
        "gateway_version": gateway.get("gateway_version"),
        "prompt_version": gateway.get("prompt_version"),
        "prompt_digest": gateway.get("prompt_digest"),
        "model_id": gateway.get("model_id"),
        "reasoning_effort": gateway.get("reasoning_effort"),
        "pricing_version": gateway.get("pricing_version"),
        "attempts": gateway.get("attempts"),
        "latency_ms": gateway.get("latency_ms"),
        "usage": copy.deepcopy(gateway.get("usage")),
        "estimated_cost_usd": gateway.get("estimated_cost_usd"),
        "response_id": gateway.get("response_id"),
        "provider_status": gateway.get("provider_status"),
        "provider_model": gateway.get("provider_model"),
        "contract_valid": contract_valid,
        "post_model_digest_valid": post_digest_valid,
        "post_model_passed": post_passed,
        "vote_eligible": vote_eligible,
        "decision": decision,
        "decision_digest": decision_digest,
        "vote_identity": vote_identity,
        "vote_identity_digest": vote_digest,
        "post_model_receipt": post,
    }


def _disagreement_v2(receipts: list[Mapping[str, Any]]) -> dict[str, Any]:
    votes = [
        str(item["vote_identity_digest"])
        for item in receipts
        if item.get("vote_eligible") is True and item.get("vote_identity_digest")
    ]
    counts = Counter(votes)
    majority_count = max(counts.values(), default=0)
    eligible_count = len(votes)
    return {
        "disagreement_version": DISAGREEMENT_VERSION,
        "sample_count": SAMPLE_COUNT,
        "eligible_sample_count": eligible_count,
        "invalid_or_blocked_sample_count": SAMPLE_COUNT - eligible_count,
        "distinct_vote_count": len(counts),
        "majority_count": majority_count,
        "majority_share": f"{Decimal(majority_count) / Decimal(SAMPLE_COUNT):.6f}",
        "disagreement_score": f"{Decimal(SAMPLE_COUNT - majority_count) / Decimal(SAMPLE_COUNT):.6f}",
        "vote_counts": dict(sorted(counts.items())),
    }


def _final_consensus_v2(
    receipts: list[Mapping[str, Any]], metrics: Mapping[str, Any]
) -> dict[str, Any]:
    majority_count = int(metrics["majority_count"])
    if majority_count < SAFE_MAJORITY:
        reason = (
            "insufficient_valid_samples"
            if int(metrics["eligible_sample_count"]) < SAFE_MAJORITY
            else "no_safe_majority"
        )
        return {
            "status": "abstain",
            "final_action": "no_trade",
            "reason_code": reason,
            "winning_vote_identity_digest": None,
            "winning_sample_indices": [],
            "representative_sample_index": None,
            "representative_decision": None,
            "representative_decision_digest": None,
        }
    counts = metrics["vote_counts"]
    winning = min(
        (key for key, value in counts.items() if int(value) == majority_count),
        default=None,
    )
    if winning is None:
        raise RuntimeError("Safe majority has no winning vote identity.")
    winners = [
        row
        for row in receipts
        if row.get("vote_eligible") is True and row.get("vote_identity_digest") == winning
    ]
    winners.sort(key=lambda row: int(row["sample_index"]))
    representative = winners[0]
    decision = copy.deepcopy(representative["decision"])
    action = str(decision["action"])
    return {
        "status": "consensus",
        "final_action": action,
        "reason_code": "safe_majority_no_trade" if action == "no_trade" else "safe_majority",
        "winning_vote_identity_digest": winning,
        "winning_sample_indices": [int(row["sample_index"]) for row in winners],
        "representative_sample_index": int(representative["sample_index"]),
        "representative_decision": decision,
        "representative_decision_digest": representative["decision_digest"],
    }


async def run_master_trader_self_consistency_v2(
    *,
    gateway: MasterTraderGatewayV2,
    evidence_bundle: Mapping[str, Any],
    context: Mapping[str, Any],
    pre_model_receipt: Mapping[str, Any],
    now_utc: Any,
    setup_detection: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(evidence_bundle, Mapping) or not isinstance(context, Mapping):
        raise TypeError("evidence_bundle and context must be mappings.")
    frozen_bundle = copy.deepcopy(dict(evidence_bundle))
    frozen_bundle_digest = digest(frozen_bundle)
    config = openai_gateway_manifest_v2()
    frozen_config_digest = str(config["manifest_digest"])

    receipts: list[dict[str, Any]] = []
    for sample_index in range(1, SAMPLE_COUNT + 1):
        sample_input = copy.deepcopy(frozen_bundle)
        if digest(sample_input) != frozen_bundle_digest:
            raise RuntimeError("Frozen evidence bundle mutated before sampling.")
        gateway_result = await gateway.evaluate(sample_input)
        if not isinstance(gateway_result, Mapping):
            raise TypeError("Gateway evaluate() must return a mapping.")
        post = evaluate_post_model_safety_v2(
            context=context,
            pre_model_result=pre_model_receipt,
            gateway_result=gateway_result,
            now_utc=now_utc,
            setup_detection=setup_detection,
        )
        receipts.append(
            _sample_receipt_v2(
                sample_index=sample_index,
                frozen_bundle_digest=frozen_bundle_digest,
                frozen_config_digest=frozen_config_digest,
                gateway_result=gateway_result,
                post_model_receipt=post,
            )
        )

    request_digests = {
        str(row["request_digest"])
        for row in receipts
        if isinstance(row.get("request_digest"), str) and row.get("request_digest")
    }
    request_identity_consistent = len(request_digests) <= 1
    if not request_identity_consistent:
        for row in receipts:
            row["vote_eligible"] = False
            row["vote_identity"] = None
            row["vote_identity_digest"] = None

    metrics = _disagreement_v2(receipts)
    consensus = _final_consensus_v2(receipts, metrics)
    if not request_identity_consistent:
        consensus = {
            "status": "abstain",
            "final_action": "no_trade",
            "reason_code": "frozen_request_identity_mismatch",
            "winning_vote_identity_digest": None,
            "winning_sample_indices": [],
            "representative_sample_index": None,
            "representative_decision": None,
            "representative_decision_digest": None,
        }
    bounded = _bounded_totals(receipts)
    if int(bounded["total_provider_attempts"]) > SAMPLE_COUNT * OPENAI_MAX_ATTEMPTS:
        raise RuntimeError("Self-consistency provider-attempt bound was exceeded.")

    result: dict[str, Any] = {
        "self_consistency_version": SELF_CONSISTENCY_VERSION_V2,
        "sample_count": SAMPLE_COUNT,
        "safe_majority_required": SAFE_MAJORITY,
        "frozen_bundle_digest": frozen_bundle_digest,
        "frozen_config_digest": frozen_config_digest,
        "request_identity_consistent": request_identity_consistent,
        "sample_receipts": receipts,
        "disagreement": metrics,
        "consensus": consensus,
        "bounded_compute": bounded,
        "all_samples_receive_same_frozen_bundle": all(
            row["frozen_bundle_digest"] == frozen_bundle_digest for row in receipts
        ),
        "all_samples_receive_same_frozen_config": all(
            row["frozen_config_digest"] == frozen_config_digest for row in receipts
        ),
        "sample_outputs_shared_between_calls": False,
        "multi_agent_debate_used": False,
        "model_persuasion_loop_used": False,
        "confidence_can_override_consensus": False,
        "broker_or_follower_state_used": False,
        "formal_forward_evidence": False,
    }
    result["self_consistency_digest"] = digest(result)
    return result


def verify_self_consistency_result_v2(result: Mapping[str, Any]) -> bool:
    if not isinstance(result, Mapping):
        return False
    supplied = str(result.get("self_consistency_digest") or "")
    body = copy.deepcopy(dict(result))
    body.pop("self_consistency_digest", None)
    if body.get("self_consistency_version") != SELF_CONSISTENCY_VERSION_V2:
        return False
    receipts = body.get("sample_receipts")
    if not isinstance(receipts, list) or len(receipts) != SAMPLE_COUNT:
        return False
    if [row.get("sample_index") for row in receipts if isinstance(row, Mapping)] != [1, 2, 3]:
        return False
    if body.get("sample_outputs_shared_between_calls") is not False:
        return False
    if body.get("multi_agent_debate_used") is not False:
        return False
    if body.get("model_persuasion_loop_used") is not False:
        return False
    try:
        for row in receipts:
            if not isinstance(row, Mapping):
                return False
            decision = row.get("decision")
            if decision is not None:
                normalized = validate_master_trader_decision_versioned(decision)
                if row.get("decision_digest") != master_trader_decision_digest_versioned(normalized):
                    return False
        canonical_json(body)
    except (TypeError, ValueError):
        return False
    return bool(supplied) and supplied == digest(body)


def self_consistency_manifest_v2() -> dict[str, Any]:
    manifest: dict[str, Any] = {
        "manifest_version": SELF_CONSISTENCY_MANIFEST_VERSION_V2,
        "self_consistency_version": SELF_CONSISTENCY_VERSION_V2,
        "sample_count": SAMPLE_COUNT,
        "safe_majority_required": SAFE_MAJORITY,
        "same_frozen_bundle_required": True,
        "same_frozen_config_required": True,
        "versioned_contract_validation_required": True,
        "independent_post_model_safety_required": True,
        "invalid_or_blocked_sample_can_vote": False,
        "no_safe_majority_action": "no_external_action",
        "no_fake_no_trade_decision_on_abstain": True,
        "multi_agent_debate_used": False,
        "confidence_can_override_consensus": False,
        "max_attempts_per_sample": OPENAI_MAX_ATTEMPTS,
        "max_total_provider_attempts": SAMPLE_COUNT * OPENAI_MAX_ATTEMPTS,
        "broker_or_follower_state_used": False,
        "formal_forward_evidence": False,
    }
    manifest["manifest_digest"] = digest(manifest)
    return manifest
