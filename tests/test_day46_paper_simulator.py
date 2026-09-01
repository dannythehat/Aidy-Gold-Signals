from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta

import pytest

from aidy.context_packet import compute_context_hash
from aidy.decision_ledger import (
    build_ex_ante_evaluation_record,
    build_reproducibility_bundle,
    verify_outcome_attachment,
)
from aidy.master_trader_contract_v2 import (
    MACHINE_CONDITION_VERSION,
    MASTER_TRADER_CONTRACT_VERSION_V2,
    master_trader_decision_digest_versioned,
)
from aidy.paper_simulator import (
    PAPER_OBSERVATION_VERSION,
    PaperSimulatorError,
    apply_paper_observation,
    build_paper_observation,
    build_paper_outcome_attachment,
    day46_manifest,
    paper_position_outcome_payload,
    reconcile_paper_state,
    replay_paper_position,
    restore_paper_state,
    serialize_paper_state,
    start_paper_position,
    verify_paper_state,
)
from aidy.safety_gates import SAFETY_GATES_VERSION, compute_safety_gate_digest
from aidy.setup_detector import SETUP_TAXONOMY_VERSION

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def _context() -> dict:
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


def _decision(*, direction: str = "long", targets: list[float] | None = None) -> dict:
    if targets is None:
        targets = [2510.0, 2520.0, 2530.0] if direction == "long" else [2490.0, 2480.0, 2470.0]
    stop = 2480.0 if direction == "long" else 2520.0
    operator = "lt" if direction == "long" else "gt"
    invalidation_value = 2490.0 if direction == "long" else 2510.0
    return {
        "contract_version": MASTER_TRADER_CONTRACT_VERSION_V2,
        "action": "new_trade",
        "symbol": "XAUUSD",
        "evaluated_at_utc": NOW.isoformat(),
        "valid_until_utc": (NOW + timedelta(minutes=15)).isoformat(),
        "confidence": 0.71,
        "setup_taxonomy_version": SETUP_TAXONOMY_VERSION,
        "setup_codes": ["trend_pullback_long" if direction == "long" else "trend_pullback_short"],
        "reason_codes": ["day46_fixture"],
        "decision_summary": "Deterministic fixture supports a bounded paper-only trade lifecycle.",
        "target_decision_id": None,
        "direction": direction,
        "entry_type": "market",
        "market_reference_price": 2500.0,
        "stop_loss": stop,
        "targets": targets,
        "management_instruction": None,
        "new_stop_loss": None,
        "new_targets": [],
        "close_scope": None,
        "thesis": "Directional continuation should persist while the reference structure remains intact.",
        "expected_horizon_minutes": 240,
        "counter_argument": "A decisive break through the invalidation level would show the claimed mechanism failed.",
        "invalidation_condition": {
            "condition_version": MACHINE_CONDITION_VERSION,
            "field_path": "$.gold.quote_context.mid",
            "operator": operator,
            "value_type": "number",
            "value": invalidation_value,
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
            "stage": stage,
            "status": "passed",
            "context_hash": context_hash,
            "checked_at_utc": NOW.isoformat(),
            "reason_codes": ["day46_fixture"],
            "checks": [{"gate": "day46_fixture", "passed": True, "reason_code": "day46_fixture"}],
            "model_call_allowed": True,
            "instruction_type": "market_evaluation",
            "max_context_age_seconds": 300,
        }
    else:
        value = {
            "gate_version": SAFETY_GATES_VERSION,
            "stage": stage,
            "status": "passed",
            "context_hash": context_hash,
            "checked_at_utc": (NOW + timedelta(seconds=1)).isoformat(),
            "reason_codes": ["day46_fixture"],
            "checks": [{"gate": "day46_fixture", "passed": True, "reason_code": "day46_fixture"}],
            "decision_admitted": True,
            "actionable": True,
            "decision_action": decision["action"],
            "downstream_action": decision["action"],
        }
    value["gate_digest"] = compute_safety_gate_digest(value)
    return value


def _record(*, direction: str = "long", targets: list[float] | None = None) -> dict:
    context = _context()
    decision = _decision(direction=direction, targets=targets)
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
        "response_id": "resp_day46",
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
        analogue_case_ids=["case_day46_fixture"],
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


def _raw_observation(minutes: int, mid: float, *, context_mid: float | None = None, extra: dict | None = None) -> dict:
    stamp = NOW + timedelta(minutes=minutes)
    context = {
        "as_of_utc": stamp.isoformat(),
        "symbol": "XAUUSD",
        "gold": {"quote_context": {} if context_mid is None else {"mid": context_mid}},
    }
    if extra:
        context.update(extra)
    return {
        "observation_version": PAPER_OBSERVATION_VERSION,
        "as_of_utc": stamp.isoformat(),
        "symbol": "XAUUSD",
        "mid": mid,
        "context": context,
    }


def test_start_requires_admitted_falsifiable_v2_new_trade() -> None:
    state = start_paper_position(_record())
    assert state["position_state"] == "open"
    assert state["paper_only"] is True
    assert state["execution_authority"] is False
    assert state["thesis_snapshot"]["invalidation_condition"]["operator"] == "lt"
    assert verify_paper_state(state)


def test_long_multi_target_lifecycle_is_deterministic() -> None:
    record = _record()
    state = start_paper_position(record)
    state = apply_paper_observation(state, _raw_observation(5, 2511.0, context_mid=2511.0))
    assert state["position_state"] == "partial"
    assert state["hit_target_indices"] == [1]
    state = apply_paper_observation(state, _raw_observation(10, 2521.0, context_mid=2521.0))
    assert state["hit_target_indices"] == [1, 2]
    state = apply_paper_observation(state, _raw_observation(15, 2531.0, context_mid=2531.0))
    assert state["position_state"] == "closed_targets"
    assert state["hit_target_indices"] == [1, 2, 3]
    assert state["realized_r"] == "1.000000"


def test_short_multi_target_lifecycle_is_symmetric() -> None:
    state = start_paper_position(_record(direction="short"))
    state = apply_paper_observation(state, _raw_observation(5, 2489.0, context_mid=2489.0))
    state = apply_paper_observation(state, _raw_observation(10, 2479.0, context_mid=2479.0))
    state = apply_paper_observation(state, _raw_observation(15, 2469.0, context_mid=2469.0))
    assert state["position_state"] == "closed_targets"
    assert state["realized_r"] == "1.000000"


def test_partial_then_stop_closes_only_remaining_slices() -> None:
    state = start_paper_position(_record())
    state = apply_paper_observation(state, _raw_observation(5, 2511.0, context_mid=2511.0))
    state = apply_paper_observation(state, _raw_observation(10, 2479.0, context_mid=2479.0))
    assert state["position_state"] == "closed_stop"
    assert state["hit_target_indices"] == [1]
    assert state["stop_hit"] is True
    assert state["realized_r"] == "-0.500000"


def test_invalidation_is_recorded_without_silently_closing_trade() -> None:
    state = start_paper_position(_record())
    state = apply_paper_observation(state, _raw_observation(5, 2495.0, context_mid=2488.0))
    assert state["invalidation"]["status"] == "triggered"
    assert state["position_state"] == "open"
    assert state["stop_hit"] is False


def test_unknown_invalidation_is_preserved_as_unknown() -> None:
    state = start_paper_position(_record())
    state = apply_paper_observation(state, _raw_observation(5, 2502.0))
    assert state["invalidation"]["status"] == "not_triggered"
    assert state["invalidation"]["unknown_count"] == 1
    assert state["invalidation"]["last_result"] == "unknown"


def test_future_timestamped_context_fails_closed() -> None:
    future = (NOW + timedelta(minutes=6)).isoformat()
    with pytest.raises(PaperSimulatorError, match="later than the observation"):
        build_paper_observation(
            as_of_utc=NOW + timedelta(minutes=5),
            mid=2501.0,
            context={
                "symbol": "XAUUSD",
                "observed_at_utc": future,
                "gold": {"quote_context": {"mid": 2501.0}},
            },
        )


def test_account_or_execution_context_is_forbidden() -> None:
    with pytest.raises(PaperSimulatorError, match="Execution/account"):
        build_paper_observation(
            as_of_utc=NOW + timedelta(minutes=5),
            mid=2501.0,
            context={"symbol": "XAUUSD", "account_balance": 1000},
        )


def test_duplicate_observation_is_idempotent_and_conflict_fails() -> None:
    state = start_paper_position(_record())
    observation = _raw_observation(5, 2501.0, context_mid=2501.0)
    first = apply_paper_observation(state, observation)
    second = apply_paper_observation(first, copy.deepcopy(observation))
    assert first == second
    conflict = _raw_observation(5, 2502.0, context_mid=2502.0)
    with pytest.raises(PaperSimulatorError, match="Conflicting paper observation"):
        apply_paper_observation(first, conflict)


def test_built_observation_can_be_applied_directly() -> None:
    state = start_paper_position(_record())
    observation = build_paper_observation(
        as_of_utc=NOW + timedelta(minutes=5),
        mid=2501.0,
        context={
            "as_of_utc": (NOW + timedelta(minutes=5)).isoformat(),
            "symbol": "XAUUSD",
            "gold": {"quote_context": {"mid": 2501.0}},
        },
    )
    updated = apply_paper_observation(state, observation)
    assert updated["observation_count"] == 1


def test_state_serialization_round_trip_is_restart_safe() -> None:
    state = start_paper_position(_record())
    state = apply_paper_observation(state, _raw_observation(5, 2511.0, context_mid=2511.0))
    restored = restore_paper_state(serialize_paper_state(state))
    assert restored == state
    continued = apply_paper_observation(restored, _raw_observation(10, 2521.0, context_mid=2521.0))
    assert continued["hit_target_indices"] == [1, 2]


def test_reconcile_allows_only_append_only_lifecycle_progression() -> None:
    opened = start_paper_position(_record())
    partial = apply_paper_observation(opened, _raw_observation(5, 2511.0, context_mid=2511.0))
    assert reconcile_paper_state(opened, partial) == partial
    forked = copy.deepcopy(partial)
    forked["lifecycle_events"][0]["mid"] = "9999.000000"
    with pytest.raises(PaperSimulatorError):
        reconcile_paper_state(partial, forked)


def test_tampered_state_is_detected() -> None:
    state = start_paper_position(_record())
    tampered = copy.deepcopy(state)
    tampered["entry_price"] = "9999.000000"
    assert verify_paper_state(tampered) is False


def test_replay_is_byte_identical_to_incremental_processing() -> None:
    record = _record()
    observations = [
        _raw_observation(5, 2511.0, context_mid=2511.0),
        _raw_observation(10, 2521.0, context_mid=2521.0),
        _raw_observation(15, 2531.0, context_mid=2531.0),
    ]
    replayed = replay_paper_position(record, observations)
    incremental = start_paper_position(record)
    for observation in observations:
        incremental = apply_paper_observation(incremental, observation)
    assert replayed == incremental


def test_profit_and_thesis_validity_are_separate_outcomes() -> None:
    state = start_paper_position(_record())
    observations = [
        _raw_observation(5, 2511.0, context_mid=2511.0),
        _raw_observation(10, 2505.0, context_mid=2488.0),
        _raw_observation(15, 2521.0, context_mid=2521.0),
        _raw_observation(20, 2531.0, context_mid=2531.0),
    ]
    for observation in observations:
        state = apply_paper_observation(state, observation)
    outcome = paper_position_outcome_payload(state)
    assert outcome["economic_outcome"]["realized_r"] == "1.000000"
    assert outcome["thesis_outcome"]["status"] == "invalidated"
    assert outcome["economic_and_thesis_outcomes_separate"] is True


def test_outcome_attaches_without_mutating_ex_ante_record() -> None:
    record = _record()
    before = copy.deepcopy(record)
    state = replay_paper_position(
        record,
        [
            _raw_observation(5, 2511.0, context_mid=2511.0),
            _raw_observation(10, 2521.0, context_mid=2521.0),
            _raw_observation(15, 2531.0, context_mid=2531.0),
        ],
    )
    attachment = build_paper_outcome_attachment(
        ex_ante_record=record,
        state=state,
        attached_at_utc=NOW + timedelta(minutes=16),
    )
    assert verify_outcome_attachment(attachment)
    assert attachment["ex_ante_digest"] == record["ex_ante_digest"]
    assert record == before
    assert attachment["outcome_payload"]["ex_ante_thesis_mutated"] is False


def test_closed_position_rejects_new_market_observations() -> None:
    state = replay_paper_position(
        _record(),
        [
            _raw_observation(5, 2511.0, context_mid=2511.0),
            _raw_observation(10, 2521.0, context_mid=2521.0),
            _raw_observation(15, 2531.0, context_mid=2531.0),
        ],
    )
    with pytest.raises(PaperSimulatorError, match="immutable"):
        apply_paper_observation(state, _raw_observation(20, 2540.0, context_mid=2540.0))


def test_day46_manifest_freezes_execution_boundaries() -> None:
    manifest = day46_manifest()
    assert manifest["paper_only"] is True
    assert manifest["pit_observations_required"] is True
    assert manifest["unknown_invalidation_is_preserved"] is True
    assert manifest["invalidation_can_mutate_trade_state"] is False
    assert manifest["economic_and_thesis_outcomes_separate"] is True
    assert manifest["broker_access_allowed"] is False
    assert manifest["account_access_allowed"] is False
    assert manifest["follower_access_allowed"] is False
    assert manifest["telegram_action_allowed"] is False
    assert manifest["mt5_action_allowed"] is False
    assert manifest["formal_forward_evidence_created"] is False
