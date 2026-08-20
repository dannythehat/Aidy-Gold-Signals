from __future__ import annotations

import copy

import pytest

from aidy.context_packet import CONTEXT_PACKET_VERSION, compute_context_hash
from aidy.cross_market import ENABLED_SERIES
from aidy.feature_engine import TIMEFRAMES
from aidy.master_trader_contract import (
    MASTER_TRADER_CONTRACT_VERSION,
    master_trader_decision_digest,
)
from aidy.safety_gates import (
    DEFAULT_MAX_CONTEXT_AGE_SECONDS,
    SAFETY_GATES_VERSION,
    evaluate_post_model_safety,
    evaluate_pre_model_safety,
    safety_gate_manifest,
    verify_safety_gate_digest,
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


def _active_signal(
    *,
    signal_id: str = "signal-0001",
    decision_id: str = "decision-0001",
) -> dict:
    return {
        "aidy_signal_id": signal_id,
        "originating_decision_id": decision_id,
        "status": "active",
        "direction": "long",
        "entry_type": "market",
        "entry_price": "2500",
        "stop_loss": "2490",
        "targets": ["2510", "2520"],
        "opened_at_utc": "2026-08-20T11:55:00+00:00",
        "updated_at_utc": "2026-08-20T11:59:00+00:00",
    }


def _context(*, active_signals: list[dict] | None = None) -> dict:
    signals = [] if active_signals is None else active_signals
    lifecycle_state = "active" if signals else "none"
    packet = {
        "context_packet_version": CONTEXT_PACKET_VERSION,
        "context_hash_algorithm": "sha256",
        "as_of_utc": BASE_TIME,
        "symbol": "XAUUSD",
        "objective_only": True,
        "retrospective_history_included": False,
        "broker_follower_state_included": False,
        "gold": {
            "timeframes": {
                timeframe: {"state": "known"}
                for timeframe in TIMEFRAMES
            },
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
                series_id: {
                    "state": "known",
                    "observation_age_days": 0,
                }
                for series_id in ENABLED_SERIES
            }
        },
        "aidy_signal_lifecycle": {
            "evidence_state": "known",
            "lifecycle_state": lifecycle_state,
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
            "cross_market_observation_age_days": {
                series_id: 0 for series_id in ENABLED_SERIES
            },
            "aidy_signal_state": "known",
            "flags": [],
        },
        "provenance": {},
    }
    packet["context_hash"] = compute_context_hash(packet)
    return packet


def _rehash_context(packet: dict) -> dict:
    packet["context_hash"] = compute_context_hash(packet)
    return packet


def _decision(
    action: str = "no_trade",
    *,
    confidence: float = 0.41,
    target_decision_id: str | None = None,
) -> dict:
    value = {
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
        value.update(
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
        value.update(
            {
                "reason_codes": ["protect_trade"],
                "decision_summary": "Move stop on the active AIDY trade.",
                "target_decision_id": target_decision_id or "decision-0001",
                "management_instruction": "move_stop",
                "new_stop_loss": 2501.0,
            }
        )
    elif action == "close_trade":
        value.update(
            {
                "reason_codes": ["thesis_invalidated"],
                "decision_summary": "Close the identified AIDY trade.",
                "target_decision_id": target_decision_id or "decision-0001",
                "close_scope": "full",
            }
        )
    return value


def _gateway(decision: dict) -> dict:
    return {
        "status": "accepted",
        "publication_allowed": True,
        "failure_reason": None,
        "structured_decision": decision,
        "decision_digest": master_trader_decision_digest(decision),
    }


def _detection(context: dict, *, direction: str = "long") -> dict:
    setup_id = "trend_momentum_long" if direction == "long" else "trend_momentum_short"
    packet = {
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
        "candidate_setup_ids": [setup_id],
        "candidates": [{"setup_id": setup_id, "direction": direction}],
    }
    packet["detection_digest"] = compute_setup_detection_digest(packet)
    return packet


def _pre(
    context: dict,
    *,
    instruction_type: str = "market_evaluation",
    now: str = NOW_TIME,
    max_age: int = DEFAULT_MAX_CONTEXT_AGE_SECONDS,
) -> dict:
    return evaluate_pre_model_safety(
        context,
        now_utc=now,
        instruction_type=instruction_type,
        max_context_age_seconds=max_age,
    )


def _check_code(result: dict, gate: str) -> str:
    return next(item["reason_code"] for item in result["checks"] if item["gate"] == gate)


def test_manifest_freezes_core_safety_doctrine() -> None:
    manifest = safety_gate_manifest()
    assert manifest["gate_version"] == SAFETY_GATES_VERSION
    assert manifest["confidence_can_bypass_gate"] is False
    assert manifest["valid_no_trade_is_success"] is True
    assert manifest["no_trade_has_external_action"] is False
    assert manifest["broker_or_follower_state_allowed"] is False
    assert manifest["manifest_digest"]


def test_valid_pre_model_context_passes() -> None:
    result = _pre(_context())
    assert result["status"] == "passed"
    assert result["model_call_allowed"] is True
    assert result["reason_codes"] == ["pre_model_allowed"]
    assert verify_safety_gate_digest(result)


def test_pre_model_duplicate_context_blocks() -> None:
    context = _context()
    result = evaluate_pre_model_safety(
        context,
        now_utc=NOW_TIME,
        instruction_type="market_evaluation",
        seen_context_hashes=[context["context_hash"]],
    )
    assert "pre_context_duplicate" in result["reason_codes"]


@pytest.mark.parametrize(
    ("mutator", "expected"),
    [
        (lambda c: c.update(context_packet_version="bad"), "pre_context_version_invalid"),
        (lambda c: c.update(symbol="EURUSD"), "pre_symbol_invalid"),
        (lambda c: c.update(objective_only=False), "pre_decision_boundary_invalid"),
        (
            lambda c: c.update(retrospective_history_included=True),
            "pre_decision_boundary_invalid",
        ),
        (
            lambda c: c.update(broker_follower_state_included=True),
            "pre_decision_boundary_invalid",
        ),
    ],
)
def test_pre_model_contract_boundary_blocks(mutator, expected: str) -> None:
    context = _context()
    mutator(context)
    _rehash_context(context)
    assert expected in _pre(context)["reason_codes"]


def test_pre_model_tampered_hash_blocks() -> None:
    context = _context()
    context["symbol"] = "EURUSD"
    assert "pre_context_hash_invalid" in _pre(context)["reason_codes"]


def test_pre_model_future_context_blocks() -> None:
    context = _context()
    context["as_of_utc"] = "2026-08-20T12:02:00+00:00"
    _rehash_context(context)
    assert "pre_context_timestamp_future_or_invalid" in _pre(context)["reason_codes"]


def test_pre_model_stale_context_blocks() -> None:
    result = _pre(_context(), now="2026-08-20T12:06:00+00:00")
    assert "pre_context_stale" in result["reason_codes"]


@pytest.mark.parametrize(
    ("path", "value", "expected"),
    [
        ("missing_gold_timeframes", ["M15"], "pre_gold_timeframes_missing"),
        ("quote_freshness", "stale", "pre_quote_stale_or_unknown"),
        ("spread_state", "unknown", "pre_spread_unknown"),
        ("macro_evidence_state", "unknown", "pre_macro_evidence_unknown"),
        (
            "cross_market_missing_series",
            ["DTWEXBGS"],
            "pre_cross_market_incomplete_or_stale",
        ),
        ("aidy_signal_state", "unknown", "pre_signal_state_unknown"),
    ],
)
def test_pre_model_missing_or_stale_quality_blocks(path: str, value, expected: str) -> None:
    context = _context()
    context["data_quality"][path] = value
    _rehash_context(context)
    assert expected in _pre(context)["reason_codes"]


def test_pre_model_rehashed_quote_freshness_lie_blocks() -> None:
    context = _context()
    context["data_quality"]["quote_age_seconds"] = 999
    context["data_quality"]["quote_freshness"] = "fresh"
    context["gold"]["quote_context"]["quote_age_seconds"] = 999
    _rehash_context(context)
    assert "pre_quote_stale_or_unknown" in _pre(context)["reason_codes"]


def test_pre_model_actual_spread_missing_blocks_even_if_flag_says_known() -> None:
    context = _context()
    context["gold"]["quote_context"]["spread"] = None
    context["data_quality"]["spread_state"] = "known"
    _rehash_context(context)
    assert "pre_spread_unknown" in _pre(context)["reason_codes"]


def test_pre_model_cross_market_stale_blocks() -> None:
    context = _context()
    series_id = ENABLED_SERIES[0]
    context["data_quality"]["cross_market_observation_age_days"][series_id] = 8
    context["cross_market"]["series"][series_id]["observation_age_days"] = 8
    _rehash_context(context)
    assert "pre_cross_market_incomplete_or_stale" in _pre(context)["reason_codes"]


def test_pre_model_actual_timeframe_unknown_blocks_even_if_summary_says_complete() -> None:
    context = _context()
    context["gold"]["timeframes"]["H1"]["state"] = "unknown"
    context["data_quality"]["missing_gold_timeframes"] = []
    _rehash_context(context)
    assert "pre_gold_timeframes_missing" in _pre(context)["reason_codes"]


def test_pre_model_session_unknown_or_conflicting_blocks() -> None:
    context = _context()
    context["session"]["session_code_consistent"] = None
    _rehash_context(context)
    assert "pre_session_conflict" in _pre(context)["reason_codes"]


def test_pre_model_unknown_instruction_blocks() -> None:
    result = _pre(_context(), instruction_type="do_whatever")
    assert "pre_instruction_type_unsupported" in result["reason_codes"]


def test_pre_model_unknown_signal_state_blocks() -> None:
    context = _context()
    context["aidy_signal_lifecycle"]["evidence_state"] = "unknown"
    _rehash_context(context)
    assert "aidy_signal_lifecycle_unknown" in _pre(context)["reason_codes"]


def test_pre_model_none_state_with_active_signal_blocks() -> None:
    context = _context(active_signals=[_active_signal()])
    context["aidy_signal_lifecycle"]["lifecycle_state"] = "none"
    _rehash_context(context)
    assert "aidy_signal_lifecycle_conflict" in _pre(context)["reason_codes"]


def test_pre_model_active_state_without_signal_blocks() -> None:
    context = _context()
    context["aidy_signal_lifecycle"]["lifecycle_state"] = "active"
    _rehash_context(context)
    assert "aidy_signal_lifecycle_conflict" in _pre(context)["reason_codes"]


def test_pre_model_active_signal_requires_originating_decision_id() -> None:
    signal = _active_signal()
    signal["originating_decision_id"] = None
    result = _pre(_context(active_signals=[signal]))
    assert "aidy_signal_lifecycle_incomplete" in result["reason_codes"]


def test_pre_model_duplicate_originating_decision_id_blocks() -> None:
    signals = [
        _active_signal(signal_id="signal-0001", decision_id="decision-0001"),
        _active_signal(signal_id="signal-0002", decision_id="decision-0001"),
    ]
    assert "aidy_signal_lifecycle_conflict" in _pre(_context(active_signals=signals))["reason_codes"]


def test_valid_no_trade_is_successful_non_action() -> None:
    context = _context()
    decision = _decision("no_trade")
    result = evaluate_post_model_safety(
        context=context,
        pre_model_result=_pre(context),
        gateway_result=_gateway(decision),
        now_utc=NOW_TIME,
    )
    assert result["status"] == "passed"
    assert result["decision_admitted"] is True
    assert result["actionable"] is False
    assert result["downstream_action"] == "no_action"
    assert result["reason_codes"] == ["post_no_trade_accepted"]


def test_no_trade_with_high_confidence_still_has_no_action() -> None:
    context = _context()
    result = evaluate_post_model_safety(
        context=context,
        pre_model_result=_pre(context),
        gateway_result=_gateway(_decision("no_trade", confidence=1.0)),
        now_utc=NOW_TIME,
    )
    assert result["decision_admitted"] is True
    assert result["actionable"] is False


def test_valid_new_trade_with_current_setup_passes() -> None:
    context = _context()
    result = evaluate_post_model_safety(
        context=context,
        pre_model_result=_pre(context),
        gateway_result=_gateway(_decision("new_trade")),
        now_utc=NOW_TIME,
        setup_detection=_detection(context),
    )
    assert result["status"] == "passed"
    assert result["actionable"] is True
    assert result["downstream_action"] == "new_trade"


def test_new_trade_missing_setup_evidence_blocks_even_at_full_confidence() -> None:
    context = _context()
    result = evaluate_post_model_safety(
        context=context,
        pre_model_result=_pre(context),
        gateway_result=_gateway(_decision("new_trade", confidence=1.0)),
        now_utc=NOW_TIME,
    )
    assert "post_setup_evidence_missing" in result["reason_codes"]


def test_new_trade_setup_from_other_context_blocks() -> None:
    context = _context()
    detection = _detection(context)
    detection["source_context_hash"] = "a" * 64
    detection["detection_digest"] = compute_setup_detection_digest(detection)
    result = evaluate_post_model_safety(
        context=context,
        pre_model_result=_pre(context),
        gateway_result=_gateway(_decision("new_trade")),
        now_utc=NOW_TIME,
        setup_detection=detection,
    )
    assert "post_setup_context_mismatch" in result["reason_codes"]


def test_new_trade_tampered_setup_digest_blocks() -> None:
    context = _context()
    detection = _detection(context)
    detection["candidates"][0]["direction"] = "short"
    result = evaluate_post_model_safety(
        context=context,
        pre_model_result=_pre(context),
        gateway_result=_gateway(_decision("new_trade")),
        now_utc=NOW_TIME,
        setup_detection=detection,
    )
    assert "post_setup_evidence_digest_invalid" in result["reason_codes"]


def test_new_trade_rehashed_wrong_setup_direction_blocks() -> None:
    context = _context()
    detection = _detection(context)
    detection["candidates"][0]["direction"] = "short"
    detection["detection_digest"] = compute_setup_detection_digest(detection)
    result = evaluate_post_model_safety(
        context=context,
        pre_model_result=_pre(context),
        gateway_result=_gateway(_decision("new_trade")),
        now_utc=NOW_TIME,
        setup_detection=detection,
    )
    assert "post_setup_candidate_definition_invalid" in result["reason_codes"]


def test_new_trade_candidate_list_mismatch_blocks() -> None:
    context = _context()
    detection = _detection(context)
    detection["candidate_setup_ids"] = []
    detection["detection_digest"] = compute_setup_detection_digest(detection)
    result = evaluate_post_model_safety(
        context=context,
        pre_model_result=_pre(context),
        gateway_result=_gateway(_decision("new_trade")),
        now_utc=NOW_TIME,
        setup_detection=detection,
    )
    assert "post_setup_candidate_list_mismatch" in result["reason_codes"]


def test_new_trade_unknown_current_setup_blocks() -> None:
    context = _context()
    result = evaluate_post_model_safety(
        context=context,
        pre_model_result=_pre(context),
        gateway_result=_gateway(_decision("new_trade")),
        now_utc=NOW_TIME,
        setup_detection=_detection(context, direction="short"),
    )
    assert "post_setup_not_in_current_evidence" in result["reason_codes"]


def test_new_trade_is_not_blocked_only_because_another_signal_is_active() -> None:
    context = _context(active_signals=[_active_signal()])
    result = evaluate_post_model_safety(
        context=context,
        pre_model_result=_pre(context),
        gateway_result=_gateway(_decision("new_trade")),
        now_utc=NOW_TIME,
        setup_detection=_detection(context),
    )
    assert result["status"] == "passed"
    assert result["actionable"] is True


@pytest.mark.parametrize("action", ["manage_trade", "close_trade"])
def test_management_actions_require_exact_active_target(action: str) -> None:
    context = _context(active_signals=[_active_signal()])
    result = evaluate_post_model_safety(
        context=context,
        pre_model_result=_pre(context, instruction_type="active_signal_management"),
        gateway_result=_gateway(_decision(action)),
        now_utc=NOW_TIME,
    )
    assert result["status"] == "passed"
    assert _check_code(result, "active_target_state") == "post_target_active"


def test_management_target_missing_blocks() -> None:
    context = _context(active_signals=[_active_signal()])
    result = evaluate_post_model_safety(
        context=context,
        pre_model_result=_pre(context, instruction_type="active_signal_management"),
        gateway_result=_gateway(_decision("manage_trade", target_decision_id="decision-9999")),
        now_utc=NOW_TIME,
    )
    assert "post_target_not_active" in result["reason_codes"]


def test_management_target_ambiguous_blocks() -> None:
    signals = [
        _active_signal(signal_id="signal-0001", decision_id="decision-0001"),
        _active_signal(signal_id="signal-0002", decision_id="decision-0001"),
    ]
    context = _context(active_signals=signals)
    pre = _pre(context, instruction_type="active_signal_management")
    result = evaluate_post_model_safety(
        context=context,
        pre_model_result=pre,
        gateway_result=_gateway(_decision("manage_trade")),
        now_utc=NOW_TIME,
    )
    assert "post_pre_model_receipt_invalid" in result["reason_codes"]
    assert "post_target_ambiguous" in result["reason_codes"]


def test_market_evaluation_cannot_emit_manage_trade() -> None:
    context = _context(active_signals=[_active_signal()])
    result = evaluate_post_model_safety(
        context=context,
        pre_model_result=_pre(context, instruction_type="market_evaluation"),
        gateway_result=_gateway(_decision("manage_trade")),
        now_utc=NOW_TIME,
    )
    assert "post_action_not_allowed_for_instruction" in result["reason_codes"]


def test_management_instruction_cannot_emit_new_trade() -> None:
    context = _context(active_signals=[_active_signal()])
    result = evaluate_post_model_safety(
        context=context,
        pre_model_result=_pre(context, instruction_type="active_signal_management"),
        gateway_result=_gateway(_decision("new_trade")),
        now_utc=NOW_TIME,
        setup_detection=_detection(context),
    )
    assert "post_action_not_allowed_for_instruction" in result["reason_codes"]


def test_failed_closed_gateway_cannot_progress() -> None:
    context = _context()
    gateway = {
        "status": "failed_closed",
        "publication_allowed": False,
        "failure_reason": "model_refusal",
        "structured_decision": None,
        "decision_digest": None,
    }
    result = evaluate_post_model_safety(
        context=context,
        pre_model_result=_pre(context),
        gateway_result=gateway,
        now_utc=NOW_TIME,
    )
    assert "post_gateway_not_accepted" in result["reason_codes"]
    assert result["decision_admitted"] is False


def test_gateway_decision_digest_mismatch_blocks() -> None:
    context = _context()
    gateway = _gateway(_decision())
    gateway["decision_digest"] = "0" * 64
    result = evaluate_post_model_safety(
        context=context,
        pre_model_result=_pre(context),
        gateway_result=gateway,
        now_utc=NOW_TIME,
    )
    assert "post_decision_digest_invalid" in result["reason_codes"]


def test_invalid_day20_geometry_blocks_post_model() -> None:
    context = _context()
    decision = _decision("new_trade")
    decision["stop_loss"] = 2510.0
    gateway = {
        "status": "accepted",
        "publication_allowed": True,
        "failure_reason": None,
        "structured_decision": decision,
        "decision_digest": "0" * 64,
    }
    result = evaluate_post_model_safety(
        context=context,
        pre_model_result=_pre(context),
        gateway_result=gateway,
        now_utc=NOW_TIME,
        setup_detection=_detection(context),
    )
    assert "post_decision_contract_invalid" in result["reason_codes"]


def test_decision_context_timestamp_must_match_exactly() -> None:
    context = _context()
    decision = _decision()
    decision["evaluated_at_utc"] = "2026-08-20T12:00:30+00:00"
    decision["valid_until_utc"] = "2026-08-20T12:05:30+00:00"
    result = evaluate_post_model_safety(
        context=context,
        pre_model_result=_pre(context),
        gateway_result=_gateway(decision),
        now_utc=NOW_TIME,
    )
    assert "post_decision_context_time_mismatch" in result["reason_codes"]


def test_future_decision_timestamp_blocks() -> None:
    context = _context()
    decision = _decision()
    decision["evaluated_at_utc"] = "2026-08-20T12:02:00+00:00"
    decision["valid_until_utc"] = "2026-08-20T12:07:00+00:00"
    result = evaluate_post_model_safety(
        context=context,
        pre_model_result=_pre(context),
        gateway_result=_gateway(decision),
        now_utc=NOW_TIME,
    )
    assert "post_decision_time_future" in result["reason_codes"]


def test_expired_decision_blocks() -> None:
    context = _context()
    result = evaluate_post_model_safety(
        context=context,
        pre_model_result=_pre(context, max_age=600),
        gateway_result=_gateway(_decision()),
        now_utc="2026-08-20T12:06:00+00:00",
    )
    assert "post_decision_expired" in result["reason_codes"]


def test_context_that_becomes_stale_while_model_runs_blocks() -> None:
    context = _context()
    pre = _pre(context, now="2026-08-20T12:04:59+00:00")
    assert pre["status"] == "passed"
    result = evaluate_post_model_safety(
        context=context,
        pre_model_result=pre,
        gateway_result=_gateway(_decision()),
        now_utc="2026-08-20T12:05:01+00:00",
    )
    assert "post_context_became_stale" in result["reason_codes"]


def test_blocked_pre_model_receipt_cannot_be_bypassed_by_valid_model_output() -> None:
    context = _context()
    pre = evaluate_pre_model_safety(
        context,
        now_utc=NOW_TIME,
        instruction_type="market_evaluation",
        seen_context_hashes=[context["context_hash"]],
    )
    result = evaluate_post_model_safety(
        context=context,
        pre_model_result=pre,
        gateway_result=_gateway(_decision()),
        now_utc=NOW_TIME,
    )
    assert "post_pre_model_receipt_invalid" in result["reason_codes"]


def test_tampered_pre_model_receipt_digest_blocks() -> None:
    context = _context()
    pre = _pre(context)
    pre["model_call_allowed"] = False
    result = evaluate_post_model_safety(
        context=context,
        pre_model_result=pre,
        gateway_result=_gateway(_decision()),
        now_utc=NOW_TIME,
    )
    assert "post_pre_model_receipt_invalid" in result["reason_codes"]


def test_pre_model_receipt_from_other_context_blocks() -> None:
    context = _context()
    other = copy.deepcopy(context)
    other["as_of_utc"] = "2026-08-20T11:59:00+00:00"
    _rehash_context(other)
    pre = _pre(other)
    result = evaluate_post_model_safety(
        context=context,
        pre_model_result=pre,
        gateway_result=_gateway(_decision()),
        now_utc=NOW_TIME,
    )
    assert "post_pre_model_receipt_invalid" in result["reason_codes"]
