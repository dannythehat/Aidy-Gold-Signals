from __future__ import annotations

import copy
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from aidy.context_composer_v2 import (
    CONTEXT_COMPOSER_VERSION_V2,
    CONTEXT_DOSSIER_VERSION_V2,
    MANDATORY_PROMPT_SECTION_ORDER,
    verify_context_dossier_v2,
)
from aidy.context_composer_v2 import digest as composer_digest
from aidy.context_packet import compute_context_hash
from aidy.decision_ledger import build_ex_ante_evaluation_record, build_reproducibility_bundle
from aidy.master_trader_contract_v2 import (
    MACHINE_CONDITION_VERSION,
    MASTER_TRADER_CONTRACT_VERSION_V2,
    master_trader_decision_digest_versioned,
)
from aidy.master_watcher import (
    WATCHER_API_URL,
    WATCHER_CADENCE_SECONDS,
    WATCHER_GATEWAY_VERSION,
    WATCHER_MAX_CONTEXT_AGE_SECONDS,
    WATCHER_MODEL_ID,
    WATCHER_OBSERVATION_VERSION,
    WATCHER_VERSION,
    OpenAIMasterWatcherGateway,
    WatcherError,
    build_watcher_evidence_bundle,
    build_watcher_request,
    digest,
    master_watcher_manifest,
    prepare_watch_cycle,
    reconcile_watcher_receipt,
    run_watch_cycle,
    validate_watcher_observation,
    verify_watcher_evidence_bundle,
    verify_watcher_receipt,
    watcher_history_summary,
    watcher_observation_digest,
)
from aidy.paper_simulator import (
    PAPER_OBSERVATION_VERSION,
    apply_paper_observation,
    start_paper_position,
    verify_paper_state,
)
from aidy.paper_simulator import digest as paper_digest
from aidy.safety_gates import SAFETY_GATES_VERSION, compute_safety_gate_digest
from aidy.setup_detector import SETUP_TAXONOMY_VERSION

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
WATCH_TIME = NOW + timedelta(minutes=10)


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


def _decision() -> dict:
    return {
        "contract_version": MASTER_TRADER_CONTRACT_VERSION_V2,
        "action": "new_trade",
        "symbol": "XAUUSD",
        "evaluated_at_utc": NOW.isoformat(),
        "valid_until_utc": (NOW + timedelta(minutes=15)).isoformat(),
        "confidence": 0.71,
        "setup_taxonomy_version": SETUP_TAXONOMY_VERSION,
        "setup_codes": ["trend_pullback_long"],
        "reason_codes": ["day47_fixture"],
        "decision_summary": "Deterministic fixture opens an AIDY paper signal for watcher testing.",
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
        "thesis": "Directional continuation should persist while the reference structure remains intact.",
        "expected_horizon_minutes": 240,
        "counter_argument": (
            "A decisive break through the invalidation level would show the claimed mechanism failed."
        ),
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
            "stage": stage,
            "status": "passed",
            "context_hash": context_hash,
            "checked_at_utc": NOW.isoformat(),
            "reason_codes": ["day47_fixture"],
            "checks": [
                {"gate": "day47_fixture", "passed": True, "reason_code": "day47_fixture"}
            ],
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
            "reason_codes": ["day47_fixture"],
            "checks": [
                {"gate": "day47_fixture", "passed": True, "reason_code": "day47_fixture"}
            ],
            "decision_admitted": True,
            "actionable": True,
            "decision_action": decision["action"],
            "downstream_action": decision["action"],
        }
    value["gate_digest"] = compute_safety_gate_digest(value)
    return value


def _record() -> dict:
    context = _origin_context()
    decision = _decision()
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
        "response_id": "resp_day47_origin",
        "provider_status": "completed",
        "provider_model": WATCHER_MODEL_ID,
        "usage": {"input_tokens": 10, "output_tokens": 10},
        "estimated_cost_usd": "0.000100",
        "pricing_version": "pricing_v1",
        "prompt_version": "aidy_master_trader_prompt_v1",
        "prompt_digest": "a" * 64,
        "model_id": WATCHER_MODEL_ID,
        "reasoning_effort": "medium",
    }
    repro = build_reproducibility_bundle(
        context=context,
        prompt_version="aidy_master_trader_prompt_v1",
        prompt_digest="a" * 64,
        gateway_version="aidy_openai_reasoning_gateway_v1",
        model_id=WATCHER_MODEL_ID,
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
        analogue_case_ids=["case_day47_fixture"],
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


def _current_context(*, stamp: datetime = WATCH_TIME, mid: float = 2505.0) -> dict:
    value = {
        "context_packet_version": "aidy_market_context_v7_volatility_state",
        "as_of_utc": stamp.isoformat(),
        "symbol": "XAUUSD",
        "objective_only": True,
        "retrospective_history_included": False,
        "broker_follower_state_included": False,
        "source_contract_versions": {
            "gold_features": "aidy_gold_features_v1",
            "volatility_intelligence": "aidy_volatility_intelligence_v1",
        },
        "data_quality": {"state": "known", "quote_freshness": "fresh"},
        "gold": {"quote_context": {"mid": str(mid)}},
        "event_risk": {
            "evidence_state": "known",
            "timing_state": "clear_current_window",
        },
    }
    value["context_hash"] = compute_context_hash(value)
    return value


def _evidence_section(side: str) -> dict:
    return {
        "side": side,
        "selection_digest": "1" * 64,
        "retrieval_digest": "2" * 64,
        "report_digest": "3" * 64,
        "effective_n": 4,
        "raw_n": 6,
        "grade": "exploratory",
        "grade_label": "Exploratory",
        "format_version": "aidy_symmetric_evidence_section_v1",
        "statistics": [],
    }


def _dossier(state: dict, context: dict) -> dict:
    counter = _evidence_section("counter")
    support = _evidence_section("support")
    uncertainty = {
        "retrieval_evidence_state": "matches_found",
        "no_comparable_reason": None,
        "effective_n": 4,
        "raw_n": 6,
        "effective_n_over_raw_n": "0.666667",
        "grade": "exploratory",
        "grade_label": "Exploratory",
        "next_grade": None,
        "next_grade_blockers": [],
        "probability_like_wording_allowed": False,
        "decision_weight_allowed": False,
        "temporal_dispersion": {},
        "unclassified_aggregate_counts": [],
    }
    mid = context.get("gold", {}).get("quote_context", {}).get("mid")
    invalidation_inputs = {"gold": {"quote_context": {"mid": mid}}}
    value = {
        "dossier_version": CONTEXT_DOSSIER_VERSION_V2,
        "composer_version": CONTEXT_COMPOSER_VERSION_V2,
        "symbol": "XAUUSD",
        "as_of_utc": context["as_of_utc"],
        "hypothesis": {"direction": "long", "setup_family": "trend_pullback"},
        "current_context_identity": {
            "context_packet_version": context["context_packet_version"],
            "context_hash": context["context_hash"],
        },
        "current_aidy_state": {
            "paper_position_id": state["position_id"],
            "paper_state_digest": state["state_digest"],
            "position_state": state["position_state"],
        },
        "history_state": {
            "state": "matches_found",
            "comparable_history_available": True,
            "no_comparable_case": False,
            "no_comparable_reason": None,
            "historical_signal_invented": False,
        },
        "counter_evidence": counter,
        "support_evidence": support,
        "setup_family_failure_profile": {
            "setup_family": "trend_pullback",
            "source_statistic": "trade_outcome_state_240m",
            "source_statistic_digest": None,
            "effective_n": 4,
            "failure_or_nonresolution_counts": {},
        },
        "uncertainty": uncertainty,
        "gate_relaxations": [],
        "invalidation_inputs": invalidation_inputs,
        "provenance": {
            "context_packet_version": context["context_packet_version"],
            "context_hash": context["context_hash"],
            "source_contract_versions": context["source_contract_versions"],
            "retrieval_version": "aidy_analogue_retrieval_v2",
            "retrieval_digest": "2" * 64,
            "selection_digest": "1" * 64,
            "evidence_report_version": "aidy_evidence_report_v2",
            "report_digest": "3" * 64,
            "provenance_counts": {},
            "quality_counts": {},
            "outcome_values_used_for_analogue_selection": False,
            "raw_future_evaluation_included": False,
        },
        "prompt_section_order": list(MANDATORY_PROMPT_SECTION_ORDER),
        "prompt_sections": [
            {"name": "counter_evidence", "payload": counter},
            {"name": "support_evidence", "payload": support},
            {"name": "uncertainty", "payload": uncertainty},
            {"name": "invalidation_inputs", "payload": invalidation_inputs},
        ],
        "mandatory_fields_preserved": True,
        "raw_future_evaluation_included": False,
        "standalone_trade_decision_allowed": False,
        "trimmed_optional_sections": [],
        "token_pressure_applied": False,
    }
    value["dossier_digest"] = composer_digest(value)
    assert verify_context_dossier_v2(value)
    return value


def _observation_from_bundle(bundle: dict, *, assessment: str = "hold") -> dict:
    position = bundle["current_paper_position"]
    original = bundle["original_decision"]
    context = bundle["fresh_pit_context"]
    return {
        "observation_version": WATCHER_OBSERVATION_VERSION,
        "position_id": position["position_id"],
        "originating_decision_id": original["originating_decision_id"],
        "observed_at_utc": context["as_of_utc"],
        "context_hash": context["context_hash"],
        "paper_state_digest": position["paper_state_digest"],
        "original_thesis_digest": original["original_thesis_digest"],
        "assessment": assessment,
        "thesis_assessment": "intact" if assessment == "hold" else "weakened",
        "reason_codes": ["fresh_context_reviewed", "original_thesis_preserved"],
        "observation_summary": (
            "Fresh evidence does not yet justify converting this observation into an action."
        ),
        "evidence_change_summary": (
            "Counter and support evidence remain bounded and the original thesis is unchanged."
        ),
        "confidence": 0.62,
        "management_action_emitted": False,
        "publication_requested": False,
        "execution_requested": False,
    }


class StubGateway:
    def __init__(
        self,
        *,
        fail: bool = False,
        boundary_violation: bool = False,
        mismatch: bool = False,
    ) -> None:
        self.calls = 0
        self.fail = fail
        self.boundary_violation = boundary_violation
        self.mismatch = mismatch

    async def evaluate(self, bundle: dict) -> dict:
        self.calls += 1
        if self.fail:
            return {
                "gateway_version": WATCHER_GATEWAY_VERSION,
                "status": "failed_closed",
                "publication_allowed": False,
                "execution_allowed": False,
                "failure_reason": "fixture_failure",
                "structured_observation": None,
                "observation_digest": None,
                "request_digest": "4" * 64,
                "attempts": 2,
                "latency_ms": 5,
                "usage": {
                    "input_tokens": 20,
                    "cached_input_tokens": 0,
                    "output_tokens": 0,
                },
                "estimated_cost_usd": "0.000100",
                "pricing_version": "fixture_pricing",
                "prompt_version": "fixture_prompt",
                "prompt_digest": "5" * 64,
                "model_id": WATCHER_MODEL_ID,
                "reasoning_effort": "medium",
            }
        observation = _observation_from_bundle(bundle)
        if self.mismatch:
            observation["context_hash"] = "f" * 64
        return {
            "gateway_version": WATCHER_GATEWAY_VERSION,
            "status": "accepted",
            "publication_allowed": self.boundary_violation,
            "execution_allowed": False,
            "failure_reason": None,
            "structured_observation": observation,
            "observation_digest": watcher_observation_digest(observation),
            "request_digest": "4" * 64,
            "attempts": 1,
            "latency_ms": 5,
            "usage": {
                "input_tokens": 100,
                "cached_input_tokens": 0,
                "output_tokens": 50,
            },
            "estimated_cost_usd": "0.002000",
            "pricing_version": "fixture_pricing",
            "prompt_version": "fixture_prompt",
            "prompt_digest": "5" * 64,
            "model_id": WATCHER_MODEL_ID,
            "reasoning_effort": "medium",
        }


def _inputs(
    *, stamp: datetime = WATCH_TIME, mid: float = 2505.0
) -> tuple[dict, dict, dict, dict]:
    record = _record()
    state = start_paper_position(record)
    context = _current_context(stamp=stamp, mid=mid)
    dossier = _dossier(state, context)
    return record, state, context, dossier


def test_manifest_freezes_day47_boundary_and_cadence() -> None:
    manifest = master_watcher_manifest()
    assert manifest["watcher_version"] == WATCHER_VERSION
    assert manifest["cadence_seconds"] == WATCHER_CADENCE_SECONDS == 300
    assert manifest["max_context_age_seconds"] == WATCHER_MAX_CONTEXT_AGE_SECONDS == 300
    assert manifest["management_action_contract_allowed"] is False
    assert manifest["day48_action_conversion_required"] is True
    assert manifest["publication_allowed"] is False
    assert manifest["execution_allowed"] is False
    assert manifest["confidence_is_safety_gate"] is False


def test_bundle_binds_fresh_context_state_thesis_and_history() -> None:
    record, state, context, dossier = _inputs()
    bundle = build_watcher_evidence_bundle(
        ex_ante_record=record,
        paper_state=state,
        current_context=context,
        historical_dossier=dossier,
        now_utc=WATCH_TIME,
    )
    assert verify_watcher_evidence_bundle(bundle)
    assert bundle["fresh_pit_context"]["context_hash"] == context["context_hash"]
    assert bundle["current_paper_position"]["paper_state_digest"] == state["state_digest"]
    assert bundle["historical_evidence"]["dossier_digest"] == dossier["dossier_digest"]
    assert bundle["original_decision"]["thesis"] == record["decision"]["thesis"]
    assert bundle["boundaries"]["management_action_contract_allowed"] is False


@pytest.mark.asyncio
async def test_closed_position_is_not_watched_and_does_not_call_model() -> None:
    record, state, context, _ = _inputs()
    stamp = NOW + timedelta(minutes=5)
    observation = {
        "observation_version": PAPER_OBSERVATION_VERSION,
        "as_of_utc": stamp.isoformat(),
        "symbol": "XAUUSD",
        "mid": 2479.0,
        "context": {
            "as_of_utc": stamp.isoformat(),
            "symbol": "XAUUSD",
            "gold": {"quote_context": {"mid": 2479.0}},
        },
    }
    state = apply_paper_observation(state, observation)
    assert state["position_state"] == "closed_stop"
    dossier = _dossier(state, context)
    gateway = StubGateway()
    receipt = await run_watch_cycle(
        ex_ante_record=record,
        paper_state=state,
        current_context=context,
        historical_dossier=dossier,
        now_utc=WATCH_TIME,
        gateway=gateway,
    )
    assert receipt["status"] == "blocked"
    assert receipt["reason_codes"] == ["watch_position_inactive"]
    assert receipt["model_call_count"] == 0
    assert gateway.calls == 0


@pytest.mark.asyncio
async def test_stale_context_fails_closed_without_model_call() -> None:
    record, state, context, dossier = _inputs(stamp=NOW)
    gateway = StubGateway()
    receipt = await run_watch_cycle(
        ex_ante_record=record,
        paper_state=state,
        current_context=context,
        historical_dossier=dossier,
        now_utc=NOW + timedelta(seconds=WATCHER_MAX_CONTEXT_AGE_SECONDS + 1),
        gateway=gateway,
    )
    assert receipt["status"] == "blocked"
    assert receipt["reason_codes"] == ["watch_context_stale"]
    assert gateway.calls == 0


@pytest.mark.asyncio
async def test_missing_quality_fails_closed() -> None:
    record, state, context, _ = _inputs()
    context = copy.deepcopy(context)
    context.pop("data_quality")
    context["context_hash"] = compute_context_hash(context)
    dossier = _dossier(state, context)
    gateway = StubGateway()
    receipt = await run_watch_cycle(
        ex_ante_record=record,
        paper_state=state,
        current_context=context,
        historical_dossier=dossier,
        now_utc=WATCH_TIME,
        gateway=gateway,
    )
    assert receipt["status"] == "blocked"
    assert receipt["reason_codes"] == ["watch_context_quality_missing"]
    assert gateway.calls == 0


@pytest.mark.asyncio
async def test_missing_quote_fails_closed() -> None:
    record, state, context, _ = _inputs()
    context = copy.deepcopy(context)
    context["gold"]["quote_context"].pop("mid")
    context["context_hash"] = compute_context_hash(context)
    dossier = _dossier(state, context)
    gateway = StubGateway()
    receipt = await run_watch_cycle(
        ex_ante_record=record,
        paper_state=state,
        current_context=context,
        historical_dossier=dossier,
        now_utc=WATCH_TIME,
        gateway=gateway,
    )
    assert receipt["status"] == "blocked"
    assert receipt["reason_codes"] == ["watch_quote_missing"]
    assert gateway.calls == 0


@pytest.mark.asyncio
async def test_tampered_context_hash_fails_closed() -> None:
    record, state, context, dossier = _inputs()
    context = copy.deepcopy(context)
    context["gold"]["quote_context"]["mid"] = "2600"
    gateway = StubGateway()
    receipt = await run_watch_cycle(
        ex_ante_record=record,
        paper_state=state,
        current_context=context,
        historical_dossier=dossier,
        now_utc=WATCH_TIME,
        gateway=gateway,
    )
    assert receipt["status"] == "blocked"
    assert receipt["reason_codes"] == ["watch_context_hash_invalid"]
    assert gateway.calls == 0


@pytest.mark.asyncio
async def test_invalid_historical_dossier_fails_closed() -> None:
    record, state, context, dossier = _inputs()
    dossier = copy.deepcopy(dossier)
    dossier["counter_evidence"]["effective_n"] = 999
    gateway = StubGateway()
    receipt = await run_watch_cycle(
        ex_ante_record=record,
        paper_state=state,
        current_context=context,
        historical_dossier=dossier,
        now_utc=WATCH_TIME,
        gateway=gateway,
    )
    assert receipt["status"] == "blocked"
    assert receipt["reason_codes"] == ["watch_historical_dossier_invalid"]
    assert gateway.calls == 0


@pytest.mark.asyncio
async def test_dossier_must_bind_exact_context_hash() -> None:
    record, state, context, dossier = _inputs()
    dossier = copy.deepcopy(dossier)
    dossier["current_context_identity"]["context_hash"] = "a" * 64
    body = {key: value for key, value in dossier.items() if key != "dossier_digest"}
    dossier["dossier_digest"] = composer_digest(body)
    assert verify_context_dossier_v2(dossier)
    gateway = StubGateway()
    receipt = await run_watch_cycle(
        ex_ante_record=record,
        paper_state=state,
        current_context=context,
        historical_dossier=dossier,
        now_utc=WATCH_TIME,
        gateway=gateway,
    )
    assert receipt["status"] == "blocked"
    assert receipt["reason_codes"] == ["watch_dossier_context_hash_mismatch"]
    assert gateway.calls == 0


@pytest.mark.asyncio
async def test_original_thesis_snapshot_is_immutable() -> None:
    record, state, context, _ = _inputs()
    state = copy.deepcopy(state)
    state["thesis_snapshot"]["thesis"] = (
        "This text was rewritten after observing the path and must be rejected."
    )
    body = copy.deepcopy(state)
    body.pop("state_digest")
    state["state_digest"] = paper_digest(body)
    assert verify_paper_state(state)
    dossier = _dossier(state, context)
    gateway = StubGateway()
    receipt = await run_watch_cycle(
        ex_ante_record=record,
        paper_state=state,
        current_context=context,
        historical_dossier=dossier,
        now_utc=WATCH_TIME,
        gateway=gateway,
    )
    assert receipt["status"] == "blocked"
    assert receipt["reason_codes"] == ["watch_original_thesis_mutated"]
    assert gateway.calls == 0


@pytest.mark.asyncio
async def test_successful_watch_records_one_call_cost_and_no_side_effects() -> None:
    record, state, context, dossier = _inputs()
    gateway = StubGateway()
    receipt = await run_watch_cycle(
        ex_ante_record=record,
        paper_state=state,
        current_context=context,
        historical_dossier=dossier,
        now_utc=WATCH_TIME,
        gateway=gateway,
    )
    assert receipt["status"] == "observed"
    assert receipt["model_call_count"] == 1
    assert receipt["provider_attempts"] == 1
    assert receipt["estimated_cost_usd"] == "0.002000"
    assert receipt["publication_allowed"] is False
    assert receipt["execution_allowed"] is False
    assert receipt["management_action_contract_emitted"] is False
    assert receipt["observation"]["assessment"] == "hold"
    assert verify_watcher_receipt(receipt)
    assert gateway.calls == 1


@pytest.mark.asyncio
async def test_duplicate_identical_input_is_suppressed_at_freshness_boundary() -> None:
    record, state, context, dossier = _inputs()
    first = await run_watch_cycle(
        ex_ante_record=record,
        paper_state=state,
        current_context=context,
        historical_dossier=dossier,
        now_utc=WATCH_TIME,
        gateway=StubGateway(),
    )
    gateway = StubGateway()
    second = await run_watch_cycle(
        ex_ante_record=record,
        paper_state=state,
        current_context=context,
        historical_dossier=dossier,
        now_utc=WATCH_TIME + timedelta(seconds=WATCHER_CADENCE_SECONDS),
        gateway=gateway,
        previous_receipts=[first],
    )
    assert second["status"] == "suppressed"
    assert second["reason_codes"] == ["watch_duplicate_input"]
    assert second["model_call_count"] == 0
    assert gateway.calls == 0


@pytest.mark.asyncio
async def test_identical_input_after_freshness_boundary_is_blocked_stale() -> None:
    record, state, context, dossier = _inputs()
    first = await run_watch_cycle(
        ex_ante_record=record,
        paper_state=state,
        current_context=context,
        historical_dossier=dossier,
        now_utc=WATCH_TIME,
        gateway=StubGateway(),
    )
    gateway = StubGateway()
    second = await run_watch_cycle(
        ex_ante_record=record,
        paper_state=state,
        current_context=context,
        historical_dossier=dossier,
        now_utc=WATCH_TIME + timedelta(seconds=WATCHER_CADENCE_SECONDS + 1),
        gateway=gateway,
        previous_receipts=[first],
    )
    assert second["status"] == "blocked"
    assert second["reason_codes"] == ["watch_context_stale"]
    assert gateway.calls == 0


@pytest.mark.asyncio
async def test_changed_context_before_cadence_is_suppressed() -> None:
    record, state, context, dossier = _inputs()
    first = await run_watch_cycle(
        ex_ante_record=record,
        paper_state=state,
        current_context=context,
        historical_dossier=dossier,
        now_utc=WATCH_TIME,
        gateway=StubGateway(),
    )
    next_time = WATCH_TIME + timedelta(seconds=60)
    changed_context = _current_context(stamp=next_time, mid=2507.0)
    changed_dossier = _dossier(state, changed_context)
    gateway = StubGateway()
    second = await run_watch_cycle(
        ex_ante_record=record,
        paper_state=state,
        current_context=changed_context,
        historical_dossier=changed_dossier,
        now_utc=next_time,
        gateway=gateway,
        previous_receipts=[first],
    )
    assert second["status"] == "suppressed"
    assert second["reason_codes"] == ["watch_cadence_not_due"]
    assert gateway.calls == 0


@pytest.mark.asyncio
async def test_changed_context_after_cadence_allows_new_call() -> None:
    record, state, context, dossier = _inputs()
    first = await run_watch_cycle(
        ex_ante_record=record,
        paper_state=state,
        current_context=context,
        historical_dossier=dossier,
        now_utc=WATCH_TIME,
        gateway=StubGateway(),
    )
    next_time = WATCH_TIME + timedelta(seconds=WATCHER_CADENCE_SECONDS)
    changed_context = _current_context(stamp=next_time, mid=2508.0)
    changed_dossier = _dossier(state, changed_context)
    gateway = StubGateway()
    second = await run_watch_cycle(
        ex_ante_record=record,
        paper_state=state,
        current_context=changed_context,
        historical_dossier=changed_dossier,
        now_utc=next_time,
        gateway=gateway,
        previous_receipts=[first],
    )
    assert second["status"] == "observed"
    assert second["model_call_count"] == 1
    assert gateway.calls == 1


@pytest.mark.asyncio
async def test_failed_model_call_logs_attempts_and_cost() -> None:
    record, state, context, dossier = _inputs()
    receipt = await run_watch_cycle(
        ex_ante_record=record,
        paper_state=state,
        current_context=context,
        historical_dossier=dossier,
        now_utc=WATCH_TIME,
        gateway=StubGateway(fail=True),
    )
    assert receipt["status"] == "model_failed"
    assert receipt["model_call_count"] == 1
    assert receipt["provider_attempts"] == 2
    assert receipt["estimated_cost_usd"] == "0.000100"
    assert receipt["observation"] is None
    assert verify_watcher_receipt(receipt)


@pytest.mark.asyncio
async def test_gateway_cannot_request_publication_or_execution() -> None:
    record, state, context, dossier = _inputs()
    receipt = await run_watch_cycle(
        ex_ante_record=record,
        paper_state=state,
        current_context=context,
        historical_dossier=dossier,
        now_utc=WATCH_TIME,
        gateway=StubGateway(boundary_violation=True),
    )
    assert receipt["status"] == "model_failed"
    assert receipt["reason_codes"] == ["watch_gateway_boundary_violation"]
    assert receipt["publication_allowed"] is False
    assert receipt["execution_allowed"] is False


@pytest.mark.asyncio
async def test_gateway_identity_mismatch_fails_closed() -> None:
    record, state, context, dossier = _inputs()
    receipt = await run_watch_cycle(
        ex_ante_record=record,
        paper_state=state,
        current_context=context,
        historical_dossier=dossier,
        now_utc=WATCH_TIME,
        gateway=StubGateway(mismatch=True),
    )
    assert receipt["status"] == "model_failed"
    assert receipt["reason_codes"] == ["watch_observation_semantic_rejection"]
    assert receipt["observation"] is None


@pytest.mark.asyncio
async def test_invalid_history_fails_closed_without_call() -> None:
    record, state, context, dossier = _inputs()
    bad = {"receipt_version": "bad", "receipt_digest": "0" * 64}
    gateway = StubGateway()
    receipt = await run_watch_cycle(
        ex_ante_record=record,
        paper_state=state,
        current_context=context,
        historical_dossier=dossier,
        now_utc=WATCH_TIME,
        gateway=gateway,
        previous_receipts=[bad],
    )
    assert receipt["status"] == "blocked"
    assert receipt["reason_codes"] == ["watch_history_invalid"]
    assert gateway.calls == 0


def test_observation_contract_cannot_smuggle_day48_action_geometry() -> None:
    record, state, context, dossier = _inputs()
    bundle = build_watcher_evidence_bundle(
        ex_ante_record=record,
        paper_state=state,
        current_context=context,
        historical_dossier=dossier,
        now_utc=WATCH_TIME,
    )
    observation = _observation_from_bundle(bundle)
    observation["new_stop_loss"] = 2500.0
    with pytest.raises(WatcherError, match="fields mismatch"):
        validate_watcher_observation(observation, expected_bundle=bundle)


def test_request_is_strict_non_stored_and_non_action() -> None:
    record, state, context, dossier = _inputs()
    bundle = build_watcher_evidence_bundle(
        ex_ante_record=record,
        paper_state=state,
        current_context=context,
        historical_dossier=dossier,
        now_utc=WATCH_TIME,
    )
    request = build_watcher_request(bundle)
    assert request["model"] == WATCHER_MODEL_ID
    assert request["store"] is False
    schema = request["text"]["format"]["schema"]
    assert schema["additionalProperties"] is False
    assert "new_stop_loss" not in schema["properties"]
    assert "new_targets" not in schema["properties"]
    assert "close_scope" not in schema["properties"]


@pytest.mark.asyncio
async def test_real_gateway_adapter_accepts_strict_mock_response() -> None:
    record, state, context, dossier = _inputs()
    bundle = build_watcher_evidence_bundle(
        ex_ante_record=record,
        paper_state=state,
        current_context=context,
        historical_dossier=dossier,
        now_utc=WATCH_TIME,
    )
    observation = _observation_from_bundle(bundle)

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == WATCHER_API_URL
        assert request.headers["Authorization"] == "Bearer test-key"
        payload = json.loads(request.content)
        assert payload["store"] is False
        return httpx.Response(
            200,
            json={
                "id": "resp_day47_mock",
                "status": "completed",
                "model": WATCHER_MODEL_ID,
                "error": None,
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {"type": "output_text", "text": json.dumps(observation)}
                        ],
                    }
                ],
                "usage": {
                    "input_tokens": 100,
                    "input_tokens_details": {"cached_tokens": 20},
                    "output_tokens": 50,
                    "output_tokens_details": {"reasoning_tokens": 10},
                    "total_tokens": 150,
                },
            },
        )

    gateway = OpenAIMasterWatcherGateway(
        "test-key",
        transport=httpx.MockTransport(handler),
    )
    result = await gateway.evaluate(bundle)
    assert result["status"] == "accepted"
    assert result["publication_allowed"] is False
    assert result["execution_allowed"] is False
    assert result["observation_digest"] == watcher_observation_digest(observation)
    assert result["estimated_cost_usd"] == "0.001910"


@pytest.mark.asyncio
async def test_real_gateway_adapter_fails_closed_on_refusal() -> None:
    record, state, context, dossier = _inputs()
    bundle = build_watcher_evidence_bundle(
        ex_ante_record=record,
        paper_state=state,
        current_context=context,
        historical_dossier=dossier,
        now_utc=WATCH_TIME,
    )

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "resp_refusal",
                "status": "completed",
                "model": WATCHER_MODEL_ID,
                "error": None,
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "refusal", "refusal": "no"}],
                    }
                ],
                "usage": {"input_tokens": 20, "output_tokens": 0, "total_tokens": 20},
            },
        )

    gateway = OpenAIMasterWatcherGateway(
        "test-key",
        transport=httpx.MockTransport(handler),
    )
    result = await gateway.evaluate(bundle)
    assert result["status"] == "failed_closed"
    assert result["failure_reason"] == "model_refusal"
    assert result["publication_allowed"] is False
    assert result["execution_allowed"] is False


@pytest.mark.asyncio
async def test_history_summary_counts_calls_attempts_costs_and_suppression() -> None:
    record, state, context, dossier = _inputs()
    first = await run_watch_cycle(
        ex_ante_record=record,
        paper_state=state,
        current_context=context,
        historical_dossier=dossier,
        now_utc=WATCH_TIME,
        gateway=StubGateway(),
    )
    second = await run_watch_cycle(
        ex_ante_record=record,
        paper_state=state,
        current_context=context,
        historical_dossier=dossier,
        now_utc=WATCH_TIME + timedelta(seconds=WATCHER_CADENCE_SECONDS),
        gateway=StubGateway(),
        previous_receipts=[first],
    )
    summary = watcher_history_summary([first, second])
    assert summary["receipt_count"] == 2
    assert summary["model_call_count"] == 1
    assert summary["provider_attempt_count"] == 1
    assert summary["observed_count"] == 1
    assert summary["suppressed_count"] == 1
    assert summary["estimated_cost_usd"] == "0.002000"
    assert summary["publication_count"] == 0
    assert summary["execution_count"] == 0


@pytest.mark.asyncio
async def test_receipt_reconciliation_is_idempotent_and_conflicts_fail() -> None:
    record, state, context, dossier = _inputs()
    receipt = await run_watch_cycle(
        ex_ante_record=record,
        paper_state=state,
        current_context=context,
        historical_dossier=dossier,
        now_utc=WATCH_TIME,
        gateway=StubGateway(),
    )
    assert reconcile_watcher_receipt(receipt, copy.deepcopy(receipt)) == receipt
    changed = copy.deepcopy(receipt)
    changed["estimated_cost_usd"] = "9.000000"
    changed.pop("receipt_digest")
    changed["receipt_digest"] = digest(changed)
    assert verify_watcher_receipt(changed)
    with pytest.raises(WatcherError, match="conflicting payloads"):
        reconcile_watcher_receipt(receipt, changed)


def test_prepare_is_deterministic_for_same_inputs() -> None:
    record, state, context, dossier = _inputs()
    first = prepare_watch_cycle(
        ex_ante_record=record,
        paper_state=state,
        current_context=context,
        historical_dossier=dossier,
        now_utc=WATCH_TIME,
    )
    second = prepare_watch_cycle(
        ex_ante_record=record,
        paper_state=state,
        current_context=context,
        historical_dossier=dossier,
        now_utc=WATCH_TIME,
    )
    assert first == second
    assert first["status"] == "ready"
    assert first["call_allowed"] is True
    assert first["watch_input_digest"] == first["evidence_bundle"]["watch_input_digest"]
