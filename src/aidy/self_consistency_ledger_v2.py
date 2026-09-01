from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from aidy.master_trader_contract_v2 import (
    master_trader_decision_digest_versioned,
    validate_master_trader_decision_versioned,
)
from aidy.self_consistency import canonical_json, digest
from aidy.self_consistency_v2 import verify_self_consistency_result_v2

SELF_CONSISTENCY_LEDGER_PROJECTION_VERSION_V2 = (
    "aidy_self_consistency_ledger_projection_v2_falsifiable"
)


def build_self_consistency_selective_layer_state_v2(
    result: Mapping[str, Any],
) -> dict[str, Any]:
    if not verify_self_consistency_result_v2(result):
        raise ValueError("V2 self-consistency result is invalid.")
    receipts = result.get("sample_receipts")
    if not isinstance(receipts, list) or len(receipts) != 3:
        raise ValueError("V2 self-consistency requires exactly three sample receipts.")

    sample_decisions: list[dict[str, Any] | None] = []
    for index, receipt in enumerate(receipts, start=1):
        if not isinstance(receipt, Mapping):
            raise TypeError(f"sample_receipts[{index - 1}] must be a mapping.")
        raw = receipt.get("decision")
        if raw is None:
            sample_decisions.append(None)
            continue
        if not isinstance(raw, Mapping):
            raise TypeError(f"sample_receipts[{index - 1}].decision must be a mapping or null.")
        decision = validate_master_trader_decision_versioned(raw)
        expected = master_trader_decision_digest_versioned(decision)
        if receipt.get("decision_digest") != expected:
            raise ValueError(f"sample {index} decision digest mismatch.")
        sample_decisions.append(copy.deepcopy(decision))

    state: dict[str, Any] = {
        "ledger_projection_version": SELF_CONSISTENCY_LEDGER_PROJECTION_VERSION_V2,
        "self_consistency_version": result["self_consistency_version"],
        "self_consistency_digest": result["self_consistency_digest"],
        "sample_count": result["sample_count"],
        "safe_majority_required": result["safe_majority_required"],
        "frozen_bundle_digest": result["frozen_bundle_digest"],
        "frozen_config_digest": result["frozen_config_digest"],
        "request_identity_consistent": result["request_identity_consistent"],
        "sample_decisions": sample_decisions,
        "sample_decision_digests": [row.get("decision_digest") for row in receipts],
        "sample_vote_identity_digests": [row.get("vote_identity_digest") for row in receipts],
        "sample_vote_eligible": [bool(row.get("vote_eligible")) for row in receipts],
        "sample_gateway_statuses": [row.get("gateway_status") for row in receipts],
        "sample_post_model_passed": [bool(row.get("post_model_passed")) for row in receipts],
        "disagreement": copy.deepcopy(result["disagreement"]),
        "consensus": copy.deepcopy(result["consensus"]),
        "bounded_compute": copy.deepcopy(result["bounded_compute"]),
        "all_three_sample_slots_ledgered": len(sample_decisions) == 3,
        "sample_decision_count": sum(row is not None for row in sample_decisions),
        "multi_agent_debate_used": False,
        "model_persuasion_loop_used": False,
        "formal_forward_evidence": False,
    }
    state["ledger_projection_digest"] = digest(state)
    return state


def verify_self_consistency_selective_layer_state_v2(state: Mapping[str, Any]) -> bool:
    if not isinstance(state, Mapping):
        return False
    if state.get("ledger_projection_version") != SELF_CONSISTENCY_LEDGER_PROJECTION_VERSION_V2:
        return False
    decisions = state.get("sample_decisions")
    if not isinstance(decisions, list) or len(decisions) != 3:
        return False
    if state.get("all_three_sample_slots_ledgered") is not True:
        return False
    supplied = str(state.get("ledger_projection_digest") or "")
    body = copy.deepcopy(dict(state))
    body.pop("ledger_projection_digest", None)
    try:
        for decision in decisions:
            if decision is not None:
                validate_master_trader_decision_versioned(decision)
        canonical_json(body)
    except (TypeError, ValueError):
        return False
    return bool(supplied) and supplied == digest(body)
