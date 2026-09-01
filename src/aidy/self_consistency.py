from __future__ import annotations

import copy
import json
from collections import Counter
from collections.abc import Awaitable, Mapping
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from hashlib import sha256
from typing import Any, Protocol

from aidy.master_trader_contract import (
    master_trader_decision_digest,
    validate_master_trader_decision,
)
from aidy.openai_gateway import OPENAI_MAX_ATTEMPTS, openai_gateway_manifest
from aidy.safety_gates import evaluate_post_model_safety, verify_safety_gate_digest

SELF_CONSISTENCY_VERSION = "aidy_master_trader_self_consistency_v1"
DISAGREEMENT_VERSION = "aidy_master_trader_disagreement_v1"
SELF_CONSISTENCY_MANIFEST_VERSION = "aidy_self_consistency_manifest_v1"
SAMPLE_COUNT = 3
SAFE_MAJORITY = 2
DIGEST_ALGORITHM = "sha256"


class MasterTraderGateway(Protocol):
    def evaluate(self, evidence_bundle: Mapping[str, Any]) -> Awaitable[dict[str, Any]]: ...


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value: object) -> str:
    return sha256(canonical_json(value).encode()).hexdigest()


def _number_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise TypeError("Action-semantic numeric values cannot be boolean.")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Action-semantic numeric values must be finite decimals.") from exc
    if not number.is_finite():
        raise ValueError("Action-semantic numeric values must be finite decimals.")
    text = format(number, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def action_semantic_identity(decision: Mapping[str, Any]) -> dict[str, Any]:
    """Return the deterministic action semantics used for safe majority voting."""

    normalized = validate_master_trader_decision(decision)
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


def vote_identity_digest(decision: Mapping[str, Any]) -> str:
    return digest(action_semantic_identity(decision))


def _gateway_metadata_ok(result: Mapping[str, Any]) -> bool:
    attempts = result.get("attempts")
    if isinstance(attempts, bool) or not isinstance(attempts, int):
        return False
    if not 0 <= attempts <= OPENAI_MAX_ATTEMPTS:
        return False
    latency = result.get("latency_ms")
    if isinstance(latency, bool) or not isinstance(latency, int) or latency < 0:
        return False
    usage = result.get("usage")
    if not isinstance(usage, Mapping):
        return False
    for key in (
        "input_tokens",
        "cached_input_tokens",
        "output_tokens",
        "reasoning_tokens",
        "total_tokens",
    ):
        value = usage.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return False
    try:
        cost = Decimal(str(result.get("estimated_cost_usd")))
    except (InvalidOperation, ValueError):
        return False
    return cost.is_finite() and cost >= 0


def _sample_receipt(
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
    contract_valid = False
    decision: dict[str, Any] | None = None
    decision_digest: str | None = None
    vote_identity: dict[str, Any] | None = None
    vote_digest: str | None = None
    raw = gateway.get("structured_decision")
    try:
        if isinstance(raw, Mapping):
            decision = validate_master_trader_decision(raw)
            decision_digest = master_trader_decision_digest(decision)
            contract_valid = gateway.get("decision_digest") == decision_digest
            if contract_valid:
                vote_identity = action_semantic_identity(decision)
                vote_digest = digest(vote_identity)
    except (TypeError, ValueError):
        decision = None
        decision_digest = None
        vote_identity = None
        vote_digest = None
        contract_valid = False

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
        "request_digest": gateway.get("request_digest"),
        "gateway_version": gateway.get("gateway_version"),
        "prompt_version": gateway.get("prompt_version"),
        "prompt_digest": gateway.get("prompt_digest"),
        "model_id": gateway.get("model_id"),
        "reasoning_effort": gateway.get("reasoning_effort"),
        "attempts": gateway.get("attempts"),
        "latency_ms": gateway.get("latency_ms"),
        "usage": copy.deepcopy(gateway.get("usage")),
        "estimated_cost_usd": gateway.get("estimated_cost_usd"),
        "response_id": gateway.get("response_id"),
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


def _disagreement(receipts: list[Mapping[str, Any]]) -> dict[str, Any]:
    votes = [
        str(item["vote_identity_digest"])
        for item in receipts
        if item.get("vote_eligible") is True and item.get("vote_identity_digest")
    ]
    counts = Counter(votes)
    majority_count = max(counts.values(), default=0)
    eligible_count = len(votes)
    invalid_count = SAMPLE_COUNT - eligible_count
    score = (Decimal(SAMPLE_COUNT - majority_count) / Decimal(SAMPLE_COUNT)).quantize(
        Decimal("0.000001"), rounding=ROUND_HALF_UP
    )
    return {
        "disagreement_version": DISAGREEMENT_VERSION,
        "sample_count": SAMPLE_COUNT,
        "eligible_sample_count": eligible_count,
        "invalid_or_blocked_sample_count": invalid_count,
        "distinct_vote_count": len(counts),
        "majority_count": majority_count,
        "majority_share": str(
            (Decimal(majority_count) / Decimal(SAMPLE_COUNT)).quantize(
                Decimal("0.000001"), rounding=ROUND_HALF_UP
            )
        ),
        "disagreement_score": str(score),
        "vote_counts": dict(sorted(counts.items())),
    }


def _bounded_totals(receipts: list[Mapping[str, Any]]) -> dict[str, Any]:
    total_attempts = sum(int(item.get("attempts") or 0) for item in receipts)
    latencies = [int(item.get("latency_ms") or 0) for item in receipts]
    total_cost = sum(
        (Decimal(str(item.get("estimated_cost_usd") or "0")) for item in receipts),
        start=Decimal(0),
    )
    usage_keys = (
        "input_tokens",
        "cached_input_tokens",
        "output_tokens",
        "reasoning_tokens",
        "total_tokens",
    )
    usage_totals = {
        key: sum(
            int((item.get("usage") or {}).get(key, 0))
            if isinstance(item.get("usage"), Mapping)
            else 0
            for item in receipts
        )
        for key in usage_keys
    }
    return {
        "max_samples": SAMPLE_COUNT,
        "max_attempts_per_sample": OPENAI_MAX_ATTEMPTS,
        "max_total_provider_attempts": SAMPLE_COUNT * OPENAI_MAX_ATTEMPTS,
        "total_provider_attempts": total_attempts,
        "total_latency_ms": sum(latencies),
        "max_sample_latency_ms": max(latencies, default=0),
        "total_estimated_cost_usd": str(
            total_cost.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
        ),
        "usage": usage_totals,
    }


def _final_consensus(receipts: list[Mapping[str, Any]], metrics: Mapping[str, Any]) -> dict[str, Any]:
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

    vote_counts = metrics["vote_counts"]
    winning_digest = min(
        (key for key, value in vote_counts.items() if int(value) == majority_count),
        default=None,
    )
    if winning_digest is None:
        raise RuntimeError("Safe majority count has no winning vote identity.")
    winners = [
        item
        for item in receipts
        if item.get("vote_eligible") is True
        and item.get("vote_identity_digest") == winning_digest
    ]
    winners.sort(key=lambda item: int(item["sample_index"]))
    representative = winners[0]
    decision = copy.deepcopy(representative["decision"])
    action = str(decision["action"])
    return {
        "status": "consensus",
        "final_action": action,
        "reason_code": "safe_majority_no_trade" if action == "no_trade" else "safe_majority",
        "winning_vote_identity_digest": winning_digest,
        "winning_sample_indices": [int(item["sample_index"]) for item in winners],
        "representative_sample_index": int(representative["sample_index"]),
        "representative_decision": decision,
        "representative_decision_digest": representative["decision_digest"],
    }


async def run_master_trader_self_consistency(
    *,
    gateway: MasterTraderGateway,
    evidence_bundle: Mapping[str, Any],
    context: Mapping[str, Any],
    pre_model_receipt: Mapping[str, Any],
    now_utc: Any,
    setup_detection: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Run exactly three independent Master Trader samples and vote deterministically."""

    if not isinstance(evidence_bundle, Mapping) or not isinstance(context, Mapping):
        raise TypeError("evidence_bundle and context must be mappings.")
    frozen_bundle = copy.deepcopy(dict(evidence_bundle))
    frozen_bundle_digest = digest(frozen_bundle)
    config = openai_gateway_manifest()
    frozen_config_digest = str(config["manifest_digest"])

    receipts: list[dict[str, Any]] = []
    for sample_index in range(1, SAMPLE_COUNT + 1):
        sample_input = copy.deepcopy(frozen_bundle)
        if digest(sample_input) != frozen_bundle_digest:
            raise RuntimeError("Frozen evidence bundle mutated before sampling.")
        gateway_result = await gateway.evaluate(sample_input)
        if not isinstance(gateway_result, Mapping):
            raise TypeError("Gateway evaluate() must return a mapping.")
        post = evaluate_post_model_safety(
            context=context,
            pre_model_result=pre_model_receipt,
            gateway_result=gateway_result,
            now_utc=now_utc,
            setup_detection=setup_detection,
        )
        receipts.append(
            _sample_receipt(
                sample_index=sample_index,
                frozen_bundle_digest=frozen_bundle_digest,
                frozen_config_digest=frozen_config_digest,
                gateway_result=gateway_result,
                post_model_receipt=post,
            )
        )

    request_digests = {
        str(item["request_digest"])
        for item in receipts
        if isinstance(item.get("request_digest"), str) and item.get("request_digest")
    }
    request_identity_consistent = len(request_digests) <= 1
    if not request_identity_consistent:
        for item in receipts:
            item["vote_eligible"] = False
            item["vote_identity"] = None
            item["vote_identity_digest"] = None

    metrics = _disagreement(receipts)
    consensus = _final_consensus(receipts, metrics)
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
    if int(bounded["total_provider_attempts"]) > int(bounded["max_total_provider_attempts"]):
        raise RuntimeError("Self-consistency provider-attempt bound was exceeded.")

    result: dict[str, Any] = {
        "self_consistency_version": SELF_CONSISTENCY_VERSION,
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
            item["frozen_bundle_digest"] == frozen_bundle_digest for item in receipts
        ),
        "all_samples_receive_same_frozen_config": all(
            item["frozen_config_digest"] == frozen_config_digest for item in receipts
        ),
        "sample_outputs_shared_between_calls": False,
        "multi_agent_debate_used": False,
        "model_persuasion_loop_used": False,
        "confidence_can_override_consensus": False,
        "broker_or_follower_state_used": False,
    }
    result["self_consistency_digest"] = digest(result)
    return result


def verify_self_consistency_result(result: Mapping[str, Any]) -> bool:
    if not isinstance(result, Mapping):
        return False
    supplied = str(result.get("self_consistency_digest") or "")
    body = copy.deepcopy(dict(result))
    body.pop("self_consistency_digest", None)
    if body.get("self_consistency_version") != SELF_CONSISTENCY_VERSION:
        return False
    receipts = body.get("sample_receipts")
    if not isinstance(receipts, list) or len(receipts) != SAMPLE_COUNT:
        return False
    if [item.get("sample_index") for item in receipts if isinstance(item, Mapping)] != [1, 2, 3]:
        return False
    if body.get("sample_outputs_shared_between_calls") is not False:
        return False
    if body.get("multi_agent_debate_used") is not False:
        return False
    if body.get("model_persuasion_loop_used") is not False:
        return False
    return bool(supplied) and supplied == digest(body)


def self_consistency_ledger_state(result: Mapping[str, Any]) -> dict[str, Any]:
    """Return the non-secret selective-layer payload Day 34 can persist ex ante."""

    if not verify_self_consistency_result(result):
        raise ValueError("Self-consistency result is invalid.")
    receipts = result["sample_receipts"]
    return {
        "self_consistency_version": result["self_consistency_version"],
        "self_consistency_digest": result["self_consistency_digest"],
        "sample_count": result["sample_count"],
        "safe_majority_required": result["safe_majority_required"],
        "frozen_bundle_digest": result["frozen_bundle_digest"],
        "frozen_config_digest": result["frozen_config_digest"],
        "request_identity_consistent": result["request_identity_consistent"],
        "sample_decision_digests": [item.get("decision_digest") for item in receipts],
        "sample_vote_identity_digests": [item.get("vote_identity_digest") for item in receipts],
        "sample_vote_eligible": [bool(item.get("vote_eligible")) for item in receipts],
        "sample_gateway_statuses": [item.get("gateway_status") for item in receipts],
        "sample_post_model_passed": [bool(item.get("post_model_passed")) for item in receipts],
        "disagreement": copy.deepcopy(result["disagreement"]),
        "consensus": copy.deepcopy(result["consensus"]),
        "bounded_compute": copy.deepcopy(result["bounded_compute"]),
        "multi_agent_debate_used": False,
        "model_persuasion_loop_used": False,
    }


def self_consistency_manifest() -> dict[str, Any]:
    manifest = {
        "manifest_version": SELF_CONSISTENCY_MANIFEST_VERSION,
        "self_consistency_version": SELF_CONSISTENCY_VERSION,
        "disagreement_version": DISAGREEMENT_VERSION,
        "digest_algorithm": DIGEST_ALGORITHM,
        "sample_count": SAMPLE_COUNT,
        "safe_majority_required": SAFE_MAJORITY,
        "same_frozen_bundle_required": True,
        "same_frozen_config_required": True,
        "independent_contract_validation_required": True,
        "independent_post_model_safety_required": True,
        "invalid_or_blocked_sample_can_vote": False,
        "no_safe_majority_action": "no_trade",
        "multi_agent_debate_used": False,
        "bull_bear_judge_pattern_used": False,
        "model_persuasion_loop_used": False,
        "confidence_can_override_consensus": False,
        "max_attempts_per_sample": OPENAI_MAX_ATTEMPTS,
        "max_total_provider_attempts": SAMPLE_COUNT * OPENAI_MAX_ATTEMPTS,
        "ledger_state_supported": True,
        "broker_or_follower_state_used": False,
        "super_signals_modified": False,
        "predictive_edge_claimed": False,
    }
    manifest["manifest_digest"] = digest(manifest)
    return manifest
