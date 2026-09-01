from __future__ import annotations

import copy

import pytest

from aidy.context_packet import compute_context_hash
from aidy.decision_ledger import build_reproducibility_bundle, verify_reproducibility_bundle
from aidy.master_trader_contract import (
    MASTER_TRADER_CONTRACT_VERSION,
    master_trader_decision_digest,
)
from aidy.self_consistency import SELF_CONSISTENCY_VERSION, digest
from aidy.self_consistency_ledger import (
    build_self_consistency_selective_layer_state,
    verify_self_consistency_selective_layer_state,
)
from aidy.setup_detector import SETUP_TAXONOMY_VERSION


def _decision(confidence: float) -> dict[str, object]:
    return {
        "contract_version": MASTER_TRADER_CONTRACT_VERSION,
        "action": "no_trade",
        "symbol": "XAUUSD",
        "evaluated_at_utc": "2026-09-01T04:00:00+00:00",
        "valid_until_utc": "2026-09-01T04:05:00+00:00",
        "confidence": confidence,
        "setup_taxonomy_version": SETUP_TAXONOMY_VERSION,
        "setup_codes": [],
        "reason_codes": ["insufficient_evidence"],
        "decision_summary": "Evidence does not earn a trade.",
        "target_decision_id": None,
        "direction": None,
        "entry_type": None,
        "market_reference_price": None,
        "stop_loss": None,
        "targets": [],
        "management_instruction": None,
        "new_stop_loss": None,
        "new_targets": [],
        "close_scope": None,
    }


def _result() -> dict[str, object]:
    decisions = [_decision(0.1), _decision(0.5), _decision(0.9)]
    receipts = []
    for index, decision in enumerate(decisions, start=1):
        receipts.append(
            {
                "sample_index": index,
                "decision": decision,
                "decision_digest": master_trader_decision_digest(decision),
                "vote_identity_digest": "v" * 64,
                "vote_eligible": True,
                "gateway_status": "accepted",
                "post_model_passed": True,
            }
        )
    result: dict[str, object] = {
        "self_consistency_version": SELF_CONSISTENCY_VERSION,
        "sample_count": 3,
        "safe_majority_required": 2,
        "frozen_bundle_digest": "b" * 64,
        "frozen_config_digest": "c" * 64,
        "request_identity_consistent": True,
        "sample_receipts": receipts,
        "disagreement": {
            "sample_count": 3,
            "eligible_sample_count": 3,
            "majority_count": 3,
            "disagreement_score": "0.000000",
        },
        "consensus": {
            "status": "consensus",
            "final_action": "no_trade",
            "reason_code": "safe_majority_no_trade",
        },
        "bounded_compute": {
            "total_provider_attempts": 3,
            "total_latency_ms": 300,
            "total_estimated_cost_usd": "0.003000",
        },
        "all_samples_receive_same_frozen_bundle": True,
        "all_samples_receive_same_frozen_config": True,
        "sample_outputs_shared_between_calls": False,
        "multi_agent_debate_used": False,
        "model_persuasion_loop_used": False,
        "confidence_can_override_consensus": False,
        "broker_or_follower_state_used": False,
    }
    result["self_consistency_digest"] = digest(result)
    return result


def _context() -> dict[str, object]:
    context: dict[str, object] = {
        "context_packet_version": "day36_fixture_context_v1",
        "objective_only": True,
        "retrospective_history_included": False,
        "broker_follower_state_included": False,
        "source_contract_versions": {"fixture": "day36"},
    }
    context["context_hash"] = compute_context_hash(context)
    return context


def test_full_three_decisions_are_preserved_in_day34_selective_layer_state() -> None:
    result = _result()
    state = build_self_consistency_selective_layer_state(result)
    assert verify_self_consistency_selective_layer_state(state)
    assert state["all_three_sample_slots_ledgered"] is True
    assert state["sample_decision_count"] == 3
    assert len(state["sample_decisions"]) == 3
    assert [item["confidence"] for item in state["sample_decisions"]] == [0.1, 0.5, 0.9]
    assert state["disagreement"]["majority_count"] == 3

    bundle = build_reproducibility_bundle(
        context=_context(),
        prompt_version="day36_prompt_v1",
        prompt_digest="p" * 64,
        gateway_version="day36_gateway_v1",
        model_id="gpt-5.6-sol",
        strategy_version="day36-self-consistency",
        config_version="day36-k3-v1",
        sampling_metadata={
            "seed_supported": False,
            "seed": None,
            "temperature_supported": False,
            "temperature": None,
        },
        regime_state=None,
        setup_state=None,
        evidence_grade="insufficient",
        effective_n=3,
        evidence_report_digest="e" * 64,
        analogue_retrieval_version="aidy_analogue_retrieval_v2_independent_episodes",
        analogue_retrieval_digest="a" * 64,
        selective_layer_state=state,
    )
    assert verify_reproducibility_bundle(bundle)
    assert len(bundle["selective_layer_state"]["sample_decisions"]) == 3


def test_projection_revalidates_each_sample_decision_digest() -> None:
    result = _result()
    changed = copy.deepcopy(result)
    changed["sample_receipts"][0]["decision"]["confidence"] = 0.2
    changed["self_consistency_digest"] = digest(
        {key: value for key, value in changed.items() if key != "self_consistency_digest"}
    )
    with pytest.raises(ValueError, match="decision digest"):
        build_self_consistency_selective_layer_state(changed)


def test_projection_digest_detects_ledger_tampering() -> None:
    state = build_self_consistency_selective_layer_state(_result())
    changed = copy.deepcopy(state)
    changed["sample_decisions"][2]["decision_summary"] = "tampered"
    assert verify_self_consistency_selective_layer_state(changed) is False
