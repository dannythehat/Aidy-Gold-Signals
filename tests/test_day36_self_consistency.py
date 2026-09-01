from __future__ import annotations

import copy
from typing import Any

import pytest

from aidy.context_packet import CONTEXT_PACKET_VERSION, compute_context_hash
from aidy.cross_market import ENABLED_SERIES
from aidy.decision_ledger import build_reproducibility_bundle, verify_reproducibility_bundle
from aidy.feature_engine import TIMEFRAMES
from aidy.master_trader_contract import (
    MASTER_TRADER_CONTRACT_VERSION,
    master_trader_decision_digest,
)
from aidy.openai_gateway import (
    OPENAI_GATEWAY_VERSION,
    OPENAI_MODEL_ID,
    OPENAI_PRICING_VERSION,
    OPENAI_PROMPT_VERSION,
    OPENAI_REASONING_EFFORT,
)
from aidy.safety_gates import evaluate_pre_model_safety
from aidy.self_consistency import (
    SAMPLE_COUNT,
    action_semantic_identity,
    run_master_trader_self_consistency,
    self_consistency_ledger_state,
    self_consistency_manifest,
    verify_self_consistency_result,
)
from aidy.setup_detector import (
    SETUP_DETECTION_VERSION,
    SETUP_DETECTOR_VERSION,
    SETUP_TAXONOMY_VERSION,
    compute_setup_detection_digest,
    taxonomy_manifest,
)

BASE_TIME = "2026-08-20T12:00:00+00:00"
NOW_TIME = "2026-08-20T12:01:00+00:00"


def _context(*, active: bool = False) -> dict[str, Any]:
    signals = (
        [
            {
                "aidy_signal_id": "signal-0001",
                "originating_decision_id": "decision-0001",
                "status": "active",
                "direction": "long",
                "entry_type": "market",
                "entry_price": "2500",
                "stop_loss": "2490",
                "targets": ["2510", "2520"],
                "opened_at_utc": "2026-08-20T11:55:00+00:00",
                "updated_at_utc": "2026-08-20T11:59:00+00:00",
            }
        ]
        if active
        else []
    )
    packet: dict[str, Any] = {
        "context_packet_version": CONTEXT_PACKET_VERSION,
        "context_hash_algorithm": "sha256",
        "as_of_utc": BASE_TIME,
        "symbol": "XAUUSD",
        "objective_only": True,
        "retrospective_history_included": False,
        "broker_follower_state_included": False,
        "source_contract_versions": {"fixture": "day36"},
        "gold": {
            "timeframes": {timeframe: {"state": "known"} for timeframe in TIMEFRAMES},
            "quote_context": {
                "quote_state": "known",
                "quote_age_seconds": 20,
                "spread": "0.30",
            },
        },
        "session": {
            "computed_session_code": "LONDON",
            "recorded_session_code": "LONDON",
            "session_code_consistent": True,
        },
        "event_risk": {"evidence_state": "known", "timing_state": "clear_current_window"},
        "cross_market": {
            "series": {
                series_id: {"state": "known", "observation_age_days": 0}
                for series_id in ENABLED_SERIES
            }
        },
        "aidy_signal_lifecycle": {
            "evidence_state": "known",
            "lifecycle_state": "active" if signals else "none",
            "active_signals": signals,
        },
        "data_quality": {
            "quote_stale_after_seconds": 300,
            "missing_gold_timeframes": [],
            "quote_state": "known",
            "quote_age_seconds": 20,
            "quote_freshness": "fresh",
            "spread_state": "known",
            "macro_evidence_state": "known",
            "cross_market_missing_series": [],
            "cross_market_observation_age_days": {series_id: 0 for series_id in ENABLED_SERIES},
            "aidy_signal_state": "known",
            "flags": [],
        },
        "provenance": {},
    }
    packet["context_hash"] = compute_context_hash(packet)
    return packet


def _pre(context: dict[str, Any], instruction: str = "market_evaluation") -> dict[str, Any]:
    receipt = evaluate_pre_model_safety(
        context,
        now_utc=NOW_TIME,
        instruction_type=instruction,
    )
    assert receipt["status"] == "passed"
    return receipt


def _decision(action: str = "no_trade", *, confidence: float = 0.4) -> dict[str, Any]:
    decision: dict[str, Any] = {
        "contract_version": MASTER_TRADER_CONTRACT_VERSION,
        "action": action,
        "symbol": "XAUUSD",
        "evaluated_at_utc": BASE_TIME,
        "valid_until_utc": "2026-08-20T12:05:00+00:00",
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
    if action == "new_trade":
        decision.update(
            {
                "setup_codes": ["trend_momentum_long"],
                "reason_codes": ["setup_present"],
                "decision_summary": "Current setup supports a long candidate.",
                "direction": "long",
                "entry_type": "market",
                "market_reference_price": 2500.0,
                "stop_loss": 2490.0,
                "targets": [2510.0, 2520.0],
            }
        )
    elif action == "manage_trade":
        decision.update(
            {
                "reason_codes": ["protect_trade"],
                "decision_summary": "Move the stop on the active AIDY trade.",
                "target_decision_id": "decision-0001",
                "management_instruction": "move_stop",
                "new_stop_loss": 2501.0,
            }
        )
    elif action == "close_trade":
        decision.update(
            {
                "reason_codes": ["thesis_invalidated"],
                "decision_summary": "Close the identified AIDY trade.",
                "target_decision_id": "decision-0001",
                "close_scope": "full",
            }
        )
    return decision


def _gateway_result(
    decision: dict[str, Any] | None,
    *,
    request_digest: str = "r" * 64,
    attempts: int = 1,
    latency_ms: int = 100,
    cost: str = "0.001000",
    failure_reason: str | None = None,
) -> dict[str, Any]:
    accepted = decision is not None and failure_reason is None
    return {
        "gateway_version": OPENAI_GATEWAY_VERSION,
        "status": "accepted" if accepted else "failed_closed",
        "publication_allowed": accepted,
        "failure_reason": None if accepted else (failure_reason or "fixture_failure"),
        "structured_decision": copy.deepcopy(decision),
        "decision_digest": None if decision is None else master_trader_decision_digest(decision),
        "request_digest": request_digest,
        "attempts": attempts,
        "latency_ms": latency_ms,
        "response_id": f"response-{latency_ms}",
        "provider_status": "completed" if accepted else "failed",
        "provider_model": OPENAI_MODEL_ID,
        "usage": {
            "input_tokens": 100,
            "cached_input_tokens": 0,
            "output_tokens": 20,
            "reasoning_tokens": 10,
            "total_tokens": 120,
        },
        "estimated_cost_usd": cost,
        "pricing_version": OPENAI_PRICING_VERSION,
        "prompt_version": OPENAI_PROMPT_VERSION,
        "prompt_digest": "p" * 64,
        "model_id": OPENAI_MODEL_ID,
        "reasoning_effort": OPENAI_REASONING_EFFORT,
    }


class FakeGateway:
    def __init__(self, results: list[dict[str, Any]]) -> None:
        self.results = copy.deepcopy(results)
        self.inputs: list[dict[str, Any]] = []

    async def evaluate(self, evidence_bundle: dict[str, Any]) -> dict[str, Any]:
        self.inputs.append(copy.deepcopy(dict(evidence_bundle)))
        return copy.deepcopy(self.results[len(self.inputs) - 1])


def _detection(context: dict[str, Any]) -> dict[str, Any]:
    packet: dict[str, Any] = {
        "detection_version": SETUP_DETECTION_VERSION,
        "detector_version": SETUP_DETECTOR_VERSION,
        "taxonomy_version": SETUP_TAXONOMY_VERSION,
        "taxonomy_digest": taxonomy_manifest()["taxonomy_digest"],
        "pit_eligible": True,
        "future_derived": False,
        "decision_input_allowed": True,
        "trading_decision_made": False,
        "trade_recommendation_made": False,
        "symbol": "XAUUSD",
        "as_of_utc": BASE_TIME,
        "source_context_hash": context["context_hash"],
        "candidate_setup_ids": ["trend_momentum_long"],
        "candidates": [{"setup_id": "trend_momentum_long", "direction": "long"}],
    }
    packet["detection_digest"] = compute_setup_detection_digest(packet)
    return packet


def _bundle() -> dict[str, Any]:
    return {
        "dossier_version": "aidy_master_trader_context_dossier_v2",
        "dossier_digest": "d" * 64,
        "prompt_section_order": [
            "counter_evidence",
            "support_evidence",
            "uncertainty",
            "invalidation_inputs",
        ],
        "counter_evidence": {"effective_n": 3, "grade": "insufficient"},
        "support_evidence": {"effective_n": 3, "grade": "insufficient"},
    }


async def _run(
    results: list[dict[str, Any]],
    *,
    context: dict[str, Any] | None = None,
    instruction: str = "market_evaluation",
    setup_detection: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], FakeGateway]:
    current = _context(active=instruction == "active_signal_management") if context is None else context
    gateway = FakeGateway(results)
    result = await run_master_trader_self_consistency(
        gateway=gateway,
        evidence_bundle=_bundle(),
        context=current,
        pre_model_receipt=_pre(current, instruction),
        now_utc=NOW_TIME,
        setup_detection=setup_detection,
    )
    return result, gateway


def test_manifest_freezes_k3_abstention_and_no_debate() -> None:
    manifest = self_consistency_manifest()
    assert manifest["sample_count"] == SAMPLE_COUNT == 3
    assert manifest["safe_majority_required"] == 2
    assert manifest["same_frozen_bundle_required"] is True
    assert manifest["independent_contract_validation_required"] is True
    assert manifest["independent_post_model_safety_required"] is True
    assert manifest["no_safe_majority_action"] == "no_trade"
    assert manifest["multi_agent_debate_used"] is False
    assert manifest["bull_bear_judge_pattern_used"] is False
    assert manifest["model_persuasion_loop_used"] is False
    assert manifest["confidence_can_override_consensus"] is False
    assert manifest["max_total_provider_attempts"] == 6


@pytest.mark.asyncio
async def test_all_three_receive_exact_same_frozen_bundle() -> None:
    results = [_gateway_result(_decision()) for _ in range(3)]
    result, gateway = await _run(results)
    assert len(gateway.inputs) == 3
    assert gateway.inputs[0] == gateway.inputs[1] == gateway.inputs[2] == _bundle()
    assert result["all_samples_receive_same_frozen_bundle"] is True
    assert result["all_samples_receive_same_frozen_config"] is True
    assert result["request_identity_consistent"] is True
    assert verify_self_consistency_result(result)


@pytest.mark.asyncio
async def test_three_no_trade_samples_form_safe_no_trade_majority() -> None:
    result, _ = await _run([_gateway_result(_decision(confidence=x)) for x in (0.1, 0.5, 0.9)])
    assert result["consensus"]["status"] == "consensus"
    assert result["consensus"]["final_action"] == "no_trade"
    assert result["consensus"]["reason_code"] == "safe_majority_no_trade"
    assert result["disagreement"]["majority_count"] == 3
    assert result["disagreement"]["disagreement_score"] == "0.000000"


@pytest.mark.asyncio
async def test_two_identical_new_trade_semantics_form_safe_majority() -> None:
    context = _context()
    first = _decision("new_trade", confidence=0.55)
    second = _decision("new_trade", confidence=0.91)
    second["decision_summary"] = "Same actionable geometry with a different concise rationale."
    third = _decision()
    result, _ = await _run(
        [_gateway_result(first), _gateway_result(second), _gateway_result(third)],
        context=context,
        setup_detection=_detection(context),
    )
    assert result["consensus"]["status"] == "consensus"
    assert result["consensus"]["final_action"] == "new_trade"
    assert result["consensus"]["winning_sample_indices"] == [1, 2]
    assert result["disagreement"]["majority_count"] == 2
    assert result["disagreement"]["disagreement_score"] == "0.333333"


@pytest.mark.asyncio
async def test_geometry_disagreement_is_not_hidden_by_same_direction_and_setup() -> None:
    context = _context()
    first = _decision("new_trade")
    second = _decision("new_trade")
    second["stop_loss"] = 2488.0
    third = _decision()
    result, _ = await _run(
        [_gateway_result(first), _gateway_result(second), _gateway_result(third)],
        context=context,
        setup_detection=_detection(context),
    )
    assert result["consensus"]["status"] == "abstain"
    assert result["consensus"]["final_action"] == "no_trade"
    assert result["consensus"]["reason_code"] == "no_safe_majority"
    assert result["disagreement"]["distinct_vote_count"] == 3
    assert result["disagreement"]["disagreement_score"] == "0.666667"


@pytest.mark.asyncio
async def test_one_one_one_action_disagreement_abstains() -> None:
    context = _context(active=True)
    result, _ = await _run(
        [
            _gateway_result(_decision()),
            _gateway_result(_decision("manage_trade")),
            _gateway_result(_decision("close_trade")),
        ],
        context=context,
        instruction="active_signal_management",
    )
    assert result["consensus"]["status"] == "abstain"
    assert result["consensus"]["final_action"] == "no_trade"
    assert result["consensus"]["reason_code"] == "no_safe_majority"


@pytest.mark.asyncio
async def test_two_failed_samples_leave_insufficient_valid_samples() -> None:
    result, _ = await _run(
        [
            _gateway_result(_decision()),
            _gateway_result(None, failure_reason="api_transport_error"),
            _gateway_result(None, failure_reason="model_refusal"),
        ]
    )
    assert result["disagreement"]["eligible_sample_count"] == 1
    assert result["consensus"]["status"] == "abstain"
    assert result["consensus"]["reason_code"] == "insufficient_valid_samples"
    assert result["consensus"]["final_action"] == "no_trade"


@pytest.mark.asyncio
async def test_one_failed_sample_does_not_block_two_safe_matching_votes() -> None:
    result, _ = await _run(
        [
            _gateway_result(_decision(confidence=0.2)),
            _gateway_result(None, failure_reason="api_transport_error"),
            _gateway_result(_decision(confidence=0.8)),
        ]
    )
    assert result["disagreement"]["eligible_sample_count"] == 2
    assert result["disagreement"]["majority_count"] == 2
    assert result["consensus"]["final_action"] == "no_trade"
    assert result["consensus"]["status"] == "consensus"


@pytest.mark.asyncio
async def test_post_model_blocked_sample_cannot_vote() -> None:
    context = _context()
    trade = _decision("new_trade")
    result, _ = await _run(
        [_gateway_result(trade), _gateway_result(_decision()), _gateway_result(_decision())],
        context=context,
        setup_detection=None,
    )
    assert result["sample_receipts"][0]["contract_valid"] is True
    assert result["sample_receipts"][0]["post_model_passed"] is False
    assert result["sample_receipts"][0]["vote_eligible"] is False
    assert result["consensus"]["final_action"] == "no_trade"


@pytest.mark.asyncio
async def test_invalid_contract_sample_cannot_vote() -> None:
    broken = _decision()
    broken["symbol"] = "EURUSD"
    raw = _gateway_result(None, failure_reason="semantic_validator_rejection")
    raw["status"] = "accepted"
    raw["publication_allowed"] = True
    raw["failure_reason"] = None
    raw["structured_decision"] = broken
    raw["decision_digest"] = "bad"
    result, _ = await _run([raw, _gateway_result(_decision()), _gateway_result(_decision())])
    assert result["sample_receipts"][0]["contract_valid"] is False
    assert result["sample_receipts"][0]["vote_eligible"] is False
    assert result["consensus"]["final_action"] == "no_trade"


@pytest.mark.asyncio
async def test_request_identity_mismatch_forces_infrastructure_abstention() -> None:
    result, _ = await _run(
        [
            _gateway_result(_decision(), request_digest="a" * 64),
            _gateway_result(_decision(), request_digest="b" * 64),
            _gateway_result(_decision(), request_digest="a" * 64),
        ]
    )
    assert result["request_identity_consistent"] is False
    assert result["consensus"]["status"] == "abstain"
    assert result["consensus"]["reason_code"] == "frozen_request_identity_mismatch"
    assert all(item["vote_eligible"] is False for item in result["sample_receipts"])


@pytest.mark.asyncio
async def test_attempt_cost_latency_and_token_metadata_are_bounded_and_totaled() -> None:
    results = [
        _gateway_result(_decision(), attempts=2, latency_ms=100, cost="0.001000"),
        _gateway_result(_decision(), attempts=1, latency_ms=200, cost="0.002000"),
        _gateway_result(_decision(), attempts=2, latency_ms=300, cost="0.003000"),
    ]
    result, _ = await _run(results)
    bounded = result["bounded_compute"]
    assert bounded["max_total_provider_attempts"] == 6
    assert bounded["total_provider_attempts"] == 5
    assert bounded["total_latency_ms"] == 600
    assert bounded["max_sample_latency_ms"] == 300
    assert bounded["total_estimated_cost_usd"] == "0.006000"
    assert bounded["usage"]["total_tokens"] == 360


@pytest.mark.asyncio
async def test_attempts_above_gateway_bound_make_sample_ineligible() -> None:
    result, _ = await _run(
        [
            _gateway_result(_decision(), attempts=3),
            _gateway_result(_decision()),
            _gateway_result(_decision()),
        ]
    )
    assert result["sample_receipts"][0]["vote_eligible"] is False
    assert result["disagreement"]["eligible_sample_count"] == 2
    assert result["consensus"]["status"] == "consensus"


def test_action_semantic_identity_excludes_confidence_and_rationale_but_keeps_geometry() -> None:
    first = _decision("new_trade", confidence=0.1)
    second = _decision("new_trade", confidence=0.9)
    second["decision_summary"] = "Different final rationale, same actionable semantics."
    assert action_semantic_identity(first) == action_semantic_identity(second)
    second["targets"] = [2510.0, 2530.0]
    assert action_semantic_identity(first) != action_semantic_identity(second)


@pytest.mark.asyncio
async def test_ledger_state_contains_all_three_sample_decisions_and_disagreement_metrics() -> None:
    result, _ = await _run([_gateway_result(_decision()) for _ in range(3)])
    state = self_consistency_ledger_state(result)
    assert len(state["sample_decision_digests"]) == 3
    assert len(state["sample_vote_identity_digests"]) == 3
    assert state["sample_vote_eligible"] == [True, True, True]
    assert state["disagreement"]["majority_count"] == 3
    assert state["consensus"]["final_action"] == "no_trade"
    assert state["multi_agent_debate_used"] is False

    context = _context()
    repro = build_reproducibility_bundle(
        context=context,
        prompt_version=OPENAI_PROMPT_VERSION,
        prompt_digest="p" * 64,
        gateway_version=OPENAI_GATEWAY_VERSION,
        model_id=OPENAI_MODEL_ID,
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
        analogue_case_ids=("case-0001", "case-0002", "case-0003"),
        selective_layer_state=state,
    )
    assert verify_reproducibility_bundle(repro)
    assert repro["selective_layer_state"]["self_consistency_digest"] == result[
        "self_consistency_digest"
    ]


@pytest.mark.asyncio
async def test_tampered_result_digest_fails_verification_and_ledger_export() -> None:
    result, _ = await _run([_gateway_result(_decision()) for _ in range(3)])
    changed = copy.deepcopy(result)
    changed["disagreement"]["majority_count"] = 2
    assert verify_self_consistency_result(changed) is False
    with pytest.raises(ValueError, match="invalid"):
        self_consistency_ledger_state(changed)
