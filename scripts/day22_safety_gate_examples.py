from __future__ import annotations

import json

from aidy.context_packet import CONTEXT_PACKET_VERSION, compute_context_hash
from aidy.cross_market import ENABLED_SERIES
from aidy.feature_engine import TIMEFRAMES
from aidy.master_trader_contract import (
    MASTER_TRADER_CONTRACT_VERSION,
    master_trader_decision_digest,
)
from aidy.safety_gates import (
    evaluate_post_model_safety,
    evaluate_pre_model_safety,
    safety_gate_manifest,
)
from aidy.setup_detector import SETUP_TAXONOMY_VERSION

AS_OF = "2026-08-20T12:00:00+00:00"
NOW = "2026-08-20T12:01:00+00:00"


def synthetic_context() -> dict:
    packet = {
        "context_packet_version": CONTEXT_PACKET_VERSION,
        "context_hash_algorithm": "sha256",
        "as_of_utc": AS_OF,
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
        "event_risk": {
            "evidence_state": "known",
            "timing_state": "clear_current_window",
        },
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
            "lifecycle_state": "none",
            "active_signals": [],
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


def no_trade_decision() -> dict:
    return {
        "contract_version": MASTER_TRADER_CONTRACT_VERSION,
        "action": "no_trade",
        "symbol": "XAUUSD",
        "evaluated_at_utc": AS_OF,
        "valid_until_utc": "2026-08-20T12:05:00+00:00",
        "confidence": 1.0,
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


def main() -> None:
    context = synthetic_context()
    pre = evaluate_pre_model_safety(
        context,
        now_utc=NOW,
        instruction_type="market_evaluation",
    )
    decision = no_trade_decision()
    gateway = {
        "status": "accepted",
        "publication_allowed": True,
        "failure_reason": None,
        "structured_decision": decision,
        "decision_digest": master_trader_decision_digest(decision),
    }
    post = evaluate_post_model_safety(
        context=context,
        pre_model_result=pre,
        gateway_result=gateway,
        now_utc=NOW,
    )
    stale = evaluate_pre_model_safety(
        context,
        now_utc="2026-08-20T12:06:00+00:00",
        instruction_type="market_evaluation",
    )
    output = {
        "manifest": safety_gate_manifest(),
        "pre_model": {
            "status": pre["status"],
            "model_call_allowed": pre["model_call_allowed"],
            "reason_codes": pre["reason_codes"],
        },
        "post_model_no_trade": {
            "status": post["status"],
            "decision_admitted": post["decision_admitted"],
            "actionable": post["actionable"],
            "downstream_action": post["downstream_action"],
            "reason_codes": post["reason_codes"],
        },
        "stale_context": {
            "status": stale["status"],
            "model_call_allowed": stale["model_call_allowed"],
            "reason_codes": stale["reason_codes"],
        },
    }
    print(json.dumps(output, sort_keys=True))


if __name__ == "__main__":
    main()
