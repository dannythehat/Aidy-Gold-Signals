from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta

import pytest

from aidy.context_packet import compute_context_hash
from aidy.decision_ledger import build_ex_ante_evaluation_record, build_reproducibility_bundle
from aidy.management_contract_v2 import (
    ManagementContractError,
    build_management_action_record,
    day48_manifest,
    digest,
    reconcile_management_action_record,
    verify_management_action_record,
)
from aidy.master_trader_contract_v2 import (
    MACHINE_CONDITION_VERSION,
    MASTER_TRADER_CONTRACT_VERSION_V2,
    master_trader_decision_digest_versioned,
)
from aidy.master_watcher import (
    WATCHER_OBSERVATION_VERSION,
    WATCHER_RECEIPT_VERSION,
    WATCHER_VERSION,
    watcher_observation_digest,
)
from aidy.master_watcher import digest as watcher_digest
from aidy.paper_simulator import (
    PAPER_OBSERVATION_VERSION,
    apply_paper_observation,
    start_paper_position,
)
from aidy.safety_gates import SAFETY_GATES_VERSION, compute_safety_gate_digest
from aidy.setup_detector import SETUP_TAXONOMY_VERSION

NOW = datetime(2026, 9, 1, 14, 0, tzinfo=UTC)
WATCH = NOW + timedelta(minutes=10)


def _origin_context() -> dict:
    value = {
        "context_packet_version": "aidy_market_context_v7_volatility_state",
        "as_of_utc": NOW.isoformat(),
        "symbol": "XAUUSD",
        "objective_only": True,
        "retrospective_history_included": False,
        "broker_follower_state_included": False,
        "source_contract_versions": {"gold_features": "aidy_gold_features_v1"},
        "data_quality": {"state": "known", "quote_freshness": "fresh"},
        "gold": {"quote_context": {"mid": "2500.0"}},
    }
    value["context_hash"] = compute_context_hash(value)
    return value


def _origin_decision() -> dict:
    return {
        "contract_version": MASTER_TRADER_CONTRACT_VERSION_V2,
        "action": "new_trade",
        "symbol": "XAUUSD",
        "evaluated_at_utc": NOW.isoformat(),
        "valid_until_utc": (NOW + timedelta(minutes=15)).isoformat(),
        "confidence": 0.72,
        "setup_taxonomy_version": SETUP_TAXONOMY_VERSION,
        "setup_codes": ["trend_pullback_long"],
        "reason_codes": ["day48_origin"],
        "decision_summary": "The bounded setup supports a paper-only long position for management testing.",
        "target_decision_id": None,
        "direction": "long",
        "entry_type": "market",
        "market_reference_price": 2500.0,
        "stop_loss": 2480.0,
        "targets": [2510.0, 2520.0, 2530.0],
        "management_instruction": None,
        "new_stop_loss": None,
        "new_targets": [],
        "close_scope": None,
        "thesis": "Gold should continue higher while the reference structure remains above invalidation.",
        "expected_horizon_minutes": 240,
        "counter_argument": "A decisive loss of the invalidation level would contradict the continuation mechanism.",
        "invalidation_condition": {
            "condition_version": MACHINE_CONDITION_VERSION,
            "field_path": "$.gold.quote_context.mid",
            "operator": "lt",
            "value_type": "number",
            "value": 2490.0,
        },
        "abstention_basis": None,
        "shadow_thesis": None,
        "shadow_direction": None,
        "shadow_horizon_minutes": None,
        "shadow_evaluation_condition": None,
    }


def _gate(stage: str, context_hash: str, decision: dict) -> dict:
    if stage == "pre_model":
        value = {
            "gate_version": SAFETY_GATES_VERSION,
            "stage": "pre_model",
            "status": "passed",
            "context_hash": context_hash,
            "checked_at_utc": NOW.isoformat(),
            "reason_codes": ["day48_fixture"],
            "checks": [{"gate": "day48_fixture", "passed": True, "reason_code": "day48_fixture"}],
            "model_call_allowed": True,
            "instruction_type": "market_evaluation",
            "max_context_age_seconds": 300,
        }
    else:
        value = {
            "gate_version": SAFETY_GATES_VERSION,
            "stage": "post_model",
            "status": "passed",
            "context_hash": context_hash,
            "checked_at_utc": (NOW + timedelta(seconds=1)).isoformat(),
            "reason_codes": ["day48_fixture"],
            "checks": [{"gate": "day48_fixture", "passed": True, "reason_code": "day48_fixture"}],
            "decision_admitted": True,
            "actionable": True,
            "decision_action": decision["action"],
            "downstream_action": decision["action"],
        }
    value["gate_digest"] = compute_safety_gate_digest(value)
    return value


def _record() -> dict:
    context = _origin_context()
    decision = _origin_decision()
    decision_digest = master_trader_decision_digest_versioned(decision)
    gateway = {
        "gateway_version": "aidy_openai_reasoning_gateway_v1",
        "status": "accepted",
        "publication_allowed": True,
        "failure_reason": None,
        "decision_digest": decision_digest,
        "request_digest": "d" * 64,
        "attempts": 1,
        "latency_ms": 1,
        "response_id": "resp_day48",
        "provider_status": "completed",
        "provider_model": "gpt-5.6-sol",
        "usage": {"input_tokens": 10, "output_tokens": 10},
        "estimated_cost_usd": "0.000100",
        "pricing_version": "pricing_v1",
        "prompt_version": "aidy_master_trader_prompt_v1",
        "prompt_digest": "a" * 64,
        "model_id": "gpt-5.6-sol",
        "reasoning_effort": "medium",
    }
    repro = build_reproducibility_bundle(
        context=context,
        prompt_version="aidy_master_trader_prompt_v1",
        prompt_digest="a" * 64,
        gateway_version="aidy_openai_reasoning_gateway_v1",
        model_id="gpt-5.6-sol",
        strategy_version="aidy_strategy_config_v1",
        config_version="aidy_runtime_config_v1",
        sampling_metadata={
            "seed_supported": False,
            "seed": None,
            "temperature_supported": False,
            "temperature": None,
        },
        regime_state={"trend_structure": "uptrend", "volatility_band": "normal"},
        setup_state={"candidate_setup_ids": decision["setup_codes"]},
        evidence_grade="exploratory",
        effective_n=4,
        evidence_report_digest="b" * 64,
        analogue_retrieval_version="aidy_analogue_retrieval_v2",
        analogue_retrieval_digest="c" * 64,
        analogue_case_ids=["case_day48_fixture"],
        selective_layer_state=None,
    )
    return build_ex_ante_evaluation_record(
        context=context,
        instruction_type="market_evaluation",
        cycle_disposition="decision_admitted",
        pre_model_receipt=_gate("pre_model", context["context_hash"], decision),
        gateway_result=gateway,
        post_model_receipt=_gate("post_model", context["context_hash"], decision),
        decision=decision,
        reproducibility_bundle=repro,
        data_quality_flags=context["data_quality"],
    )


def _context(mid: float = 2505.0) -> dict:
    value = {
        "context_packet_version": "aidy_market_context_v7_volatility_state",
        "as_of_utc": WATCH.isoformat(),
        "symbol": "XAUUSD",
        "objective_only": True,
        "retrospective_history_included": False,
        "broker_follower_state_included": False,
        "source_contract_versions": {"gold_features": "aidy_gold_features_v1"},
        "data_quality": {"state": "known", "quote_freshness": "fresh"},
        "gold": {"quote_context": {"mid": mid}},
    }
    value["context_hash"] = compute_context_hash(value)
    return value


def _watcher_receipt(
    record: dict,
    state: dict,
    context: dict,
    *,
    assessment: str = "management_review",
    thesis_assessment: str = "weakened",
    watcher_reason: str = "momentum_weakened",
) -> dict:
    observation = {
        "observation_version": WATCHER_OBSERVATION_VERSION,
        "position_id": state["position_id"],
        "originating_decision_id": record["decision_id"],
        "observed_at_utc": context["as_of_utc"],
        "context_hash": context["context_hash"],
        "paper_state_digest": state["state_digest"],
        "original_thesis_digest": digest(state["thesis_snapshot"]),
        "assessment": assessment,
        "thesis_assessment": thesis_assessment,
        "reason_codes": [watcher_reason],
        "observation_summary": "Fresh evidence warrants a bounded management review of the active paper trade.",
        "evidence_change_summary": "Current evidence has weakened relative to the original entry context without rewriting it.",
        "confidence": 0.61,
        "management_action_emitted": False,
        "publication_requested": False,
        "execution_requested": False,
    }
    identity = {
        "position_id": state["position_id"],
        "cycle_index": 0,
        "checked_at_utc": context["as_of_utc"],
        "watch_input_digest": "1" * 64,
        "status": "observed",
    }
    receipt = {
        "receipt_version": WATCHER_RECEIPT_VERSION,
        "watcher_version": WATCHER_VERSION,
        "receipt_id": f"watch:{watcher_digest(identity)[:32]}",
        "cycle_index": 0,
        "checked_at_utc": context["as_of_utc"],
        "position_id": state["position_id"],
        "context_hash": context["context_hash"],
        "paper_state_digest": state["state_digest"],
        "original_thesis_digest": observation["original_thesis_digest"],
        "watch_input_digest": "1" * 64,
        "status": "observed",
        "reason_codes": ["watch_observation_recorded"],
        "call_attempted": True,
        "model_call_count": 1,
        "provider_attempts": 1,
        "gateway_version": "aidy_openai_master_watcher_gateway_v1",
        "request_digest": "2" * 64,
        "prompt_version": "aidy_master_watcher_prompt_v1",
        "prompt_digest": "3" * 64,
        "model_id": "gpt-5.6-sol",
        "usage": {"input_tokens": 100, "output_tokens": 50},
        "estimated_cost_usd": "0.002000",
        "observation": observation,
        "observation_digest": watcher_observation_digest(observation),
        "publication_allowed": False,
        "execution_allowed": False,
        "management_action_contract_emitted": False,
        "formal_forward_evidence": False,
        "super_signals_modified": False,
    }
    receipt["receipt_digest"] = watcher_digest(receipt)
    return receipt


def _manage(record: dict, *, stop: float = 2495.0, watcher_reason: str = "momentum_weakened") -> dict:
    origin = record["decision"]
    return {
        "contract_version": MASTER_TRADER_CONTRACT_VERSION_V2,
        "action": "manage_trade",
        "symbol": "XAUUSD",
        "evaluated_at_utc": WATCH.isoformat(),
        "valid_until_utc": (WATCH + timedelta(minutes=5)).isoformat(),
        "confidence": 0.64,
        "setup_taxonomy_version": SETUP_TAXONOMY_VERSION,
        "setup_codes": [],
        "reason_codes": [watcher_reason, "thesis_weakened"],
        "decision_summary": "Current evidence supports reducing risk while preserving the original thesis record.",
        "target_decision_id": record["decision_id"],
        "direction": None,
        "entry_type": None,
        "market_reference_price": None,
        "stop_loss": None,
        "targets": [],
        "management_instruction": "move_stop",
        "new_stop_loss": stop,
        "new_targets": [],
        "close_scope": None,
        "thesis": origin["thesis"],
        "expected_horizon_minutes": origin["expected_horizon_minutes"],
        "counter_argument": origin["counter_argument"],
        "invalidation_condition": copy.deepcopy(origin["invalidation_condition"]),
        "abstention_basis": None,
        "shadow_thesis": None,
        "shadow_direction": None,
        "shadow_horizon_minutes": None,
        "shadow_evaluation_condition": None,
    }


def _close(record: dict, *, watcher_reason: str = "thesis_broken") -> dict:
    origin = record["decision"]
    return {
        "contract_version": MASTER_TRADER_CONTRACT_VERSION_V2,
        "action": "close_trade",
        "symbol": "XAUUSD",
        "evaluated_at_utc": WATCH.isoformat(),
        "valid_until_utc": (WATCH + timedelta(minutes=5)).isoformat(),
        "confidence": 0.78,
        "setup_taxonomy_version": SETUP_TAXONOMY_VERSION,
        "setup_codes": [],
        "reason_codes": [watcher_reason, "thesis_invalidated"],
        "decision_summary": "Fresh evidence now contradicts the original thesis and supports a full paper close.",
        "target_decision_id": record["decision_id"],
        "direction": None,
        "entry_type": None,
        "market_reference_price": None,
        "stop_loss": None,
        "targets": [],
        "management_instruction": None,
        "new_stop_loss": None,
        "new_targets": [],
        "close_scope": "full",
        "thesis": origin["thesis"],
        "expected_horizon_minutes": origin["expected_horizon_minutes"],
        "counter_argument": origin["counter_argument"],
        "invalidation_condition": copy.deepcopy(origin["invalidation_condition"]),
        "abstention_basis": None,
        "shadow_thesis": None,
        "shadow_direction": None,
        "shadow_horizon_minutes": None,
        "shadow_evaluation_condition": None,
    }


def _inputs():
    record = _record()
    state = start_paper_position(record)
    context = _context()
    receipt = _watcher_receipt(record, state, context)
    return record, state, context, receipt


def test_valid_move_stop_is_ledgered_and_reduces_risk() -> None:
    record, state, context, receipt = _inputs()
    action = build_management_action_record(
        decision=_manage(record),
        watcher_receipt=receipt,
        ex_ante_record=record,
        paper_state=state,
        current_context=context,
    )
    assert action["projected_transition"]["stop_loss"] == "2495.0"
    assert action["originating_decision_id"] == record["decision_id"]
    assert action["execution_allowed"] is False
    assert verify_management_action_record(action)


def test_valid_close_requires_close_review_and_preserves_thesis() -> None:
    record, state, context, _ = _inputs()
    receipt = _watcher_receipt(
        record,
        state,
        context,
        assessment="close_review",
        thesis_assessment="invalidated",
        watcher_reason="thesis_broken",
    )
    action = build_management_action_record(
        decision=_close(record),
        watcher_receipt=receipt,
        ex_ante_record=record,
        paper_state=state,
        current_context=context,
    )
    assert action["projected_transition"]["after_state"] == "closed_management"
    assert action["decision"]["thesis"] == record["decision"]["thesis"]
    assert verify_management_action_record(action)


def test_wrong_target_decision_id_is_rejected() -> None:
    record, state, context, receipt = _inputs()
    decision = _manage(record)
    decision["target_decision_id"] = "aidy_dec_deadbeef"
    with pytest.raises(ManagementContractError, match="exact origin"):
        build_management_action_record(
            decision=decision,
            watcher_receipt=receipt,
            ex_ante_record=record,
            paper_state=state,
            current_context=context,
        )


def test_watcher_for_different_origin_is_rejected() -> None:
    record, state, context, receipt = _inputs()
    receipt = copy.deepcopy(receipt)
    receipt["observation"]["originating_decision_id"] = "aidy_dec_deadbeef"
    receipt["observation_digest"] = watcher_observation_digest(receipt["observation"])
    receipt.pop("receipt_digest")
    receipt["receipt_digest"] = watcher_digest(receipt)
    with pytest.raises(ManagementContractError, match="different originating"):
        build_management_action_record(
            decision=_manage(record),
            watcher_receipt=receipt,
            ex_ante_record=record,
            paper_state=state,
            current_context=context,
        )


def test_original_thesis_cannot_be_rewritten() -> None:
    record, state, context, receipt = _inputs()
    decision = _manage(record)
    decision["thesis"] = "Gold should now rise for an entirely different hindsight-derived reason."
    with pytest.raises(ManagementContractError, match="rewrite original thesis"):
        build_management_action_record(
            decision=decision,
            watcher_receipt=receipt,
            ex_ante_record=record,
            paper_state=state,
            current_context=context,
        )


def test_thesis_relationship_reason_code_is_mandatory() -> None:
    record, state, context, receipt = _inputs()
    decision = _manage(record)
    decision["reason_codes"] = ["momentum_weakened"]
    with pytest.raises(ManagementContractError, match="thesis_weakened"):
        build_management_action_record(
            decision=decision,
            watcher_receipt=receipt,
            ex_ante_record=record,
            paper_state=state,
            current_context=context,
        )


def test_current_watcher_reason_must_be_cited() -> None:
    record, state, context, receipt = _inputs()
    decision = _manage(record, watcher_reason="different_reason")
    with pytest.raises(ManagementContractError, match="watcher reason"):
        build_management_action_record(
            decision=decision,
            watcher_receipt=receipt,
            ex_ante_record=record,
            paper_state=state,
            current_context=context,
        )


@pytest.mark.parametrize("stop", [2475.0, 2505.0, 2510.0])
def test_invalid_stop_geometry_fails_closed(stop: float) -> None:
    record, state, context, receipt = _inputs()
    with pytest.raises(ManagementContractError, match="Stop management"):
        build_management_action_record(
            decision=_manage(record, stop=stop),
            watcher_receipt=receipt,
            ex_ante_record=record,
            paper_state=state,
            current_context=context,
        )


def test_replace_targets_cannot_create_extra_legs() -> None:
    record, state, context, receipt = _inputs()
    decision = _manage(record)
    decision["management_instruction"] = "replace_targets"
    decision["new_stop_loss"] = None
    decision["new_targets"] = [2515.0, 2525.0, 2535.0]
    action = build_management_action_record(
        decision=decision,
        watcher_receipt=receipt,
        ex_ante_record=record,
        paper_state=state,
        current_context=context,
    )
    assert action["projected_transition"]["replacement_targets"] == decision["new_targets"]

    partial_obs = {
        "observation_version": PAPER_OBSERVATION_VERSION,
        "as_of_utc": (NOW + timedelta(minutes=5)).isoformat(),
        "symbol": "XAUUSD",
        "mid": 2511.0,
        "context": {
            "as_of_utc": (NOW + timedelta(minutes=5)).isoformat(),
            "symbol": "XAUUSD",
            "gold": {"quote_context": {"mid": 2511.0}},
        },
    }
    partial = apply_paper_observation(state, partial_obs)
    context2 = _context(2512.0)
    receipt2 = _watcher_receipt(record, partial, context2)
    with pytest.raises(ManagementContractError, match="more remaining legs"):
        build_management_action_record(
            decision=decision,
            watcher_receipt=receipt2,
            ex_ante_record=record,
            paper_state=partial,
            current_context=context2,
        )


def test_closed_position_cannot_be_managed() -> None:
    record, state, context, receipt = _inputs()
    obs = {
        "observation_version": PAPER_OBSERVATION_VERSION,
        "as_of_utc": (NOW + timedelta(minutes=5)).isoformat(),
        "symbol": "XAUUSD",
        "mid": 2479.0,
        "context": {
            "as_of_utc": (NOW + timedelta(minutes=5)).isoformat(),
            "symbol": "XAUUSD",
            "gold": {"quote_context": {"mid": 2479.0}},
        },
    }
    closed = apply_paper_observation(state, obs)
    with pytest.raises(ManagementContractError, match="active paper states"):
        build_management_action_record(
            decision=_manage(record),
            watcher_receipt=receipt,
            ex_ante_record=record,
            paper_state=closed,
            current_context=context,
        )


def test_context_hash_mismatch_fails_closed() -> None:
    record, state, context, receipt = _inputs()
    changed = copy.deepcopy(context)
    changed["gold"]["quote_context"]["mid"] = 2506.0
    changed["context_hash"] = compute_context_hash(changed)
    with pytest.raises(ManagementContractError, match="context hashes differ"):
        build_management_action_record(
            decision=_manage(record),
            watcher_receipt=receipt,
            ex_ante_record=record,
            paper_state=state,
            current_context=changed,
        )


def test_ledger_is_idempotent_and_tamper_evident() -> None:
    record, state, context, receipt = _inputs()
    first = build_management_action_record(
        decision=_manage(record),
        watcher_receipt=receipt,
        ex_ante_record=record,
        paper_state=state,
        current_context=context,
    )
    second = build_management_action_record(
        decision=_manage(record),
        watcher_receipt=receipt,
        ex_ante_record=record,
        paper_state=state,
        current_context=context,
    )
    assert first == second
    assert reconcile_management_action_record(first, second) == first
    tampered = copy.deepcopy(first)
    tampered["projected_transition"]["stop_loss"] = "2499"
    assert not verify_management_action_record(tampered)


def test_manifest_preserves_aidy_boundaries() -> None:
    manifest = day48_manifest()
    assert manifest["exact_originating_decision_id_required"] is True
    assert manifest["original_thesis_invalidation_immutable"] is True
    assert manifest["execution_allowed"] is False
    assert manifest["broker_or_follower_state_allowed"] is False
    assert manifest["super_signals_modified"] is False
