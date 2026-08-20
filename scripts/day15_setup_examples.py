from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from aidy.context_packet import CONTEXT_HASH_ALGORITHM, CONTEXT_PACKET_VERSION, compute_context_hash
from aidy.feature_engine import FEATURE_DEFINITION_VERSION, PIT_PROVENANCE
from aidy.regime_classifier import classify_gold_regime
from aidy.setup_detector import (
    build_day14_setup_evidence_from_detection,
    detect_candidate_setups,
    taxonomy_manifest,
)

AS_OF = datetime(2026, 8, 20, 9, 0, tzinfo=UTC)


def _tf(
    direction: str,
    *,
    return_1: str,
    body: str,
    close_location: str,
    range_position: str,
    atr: str,
) -> dict[str, Any]:
    return {
        "state": "known",
        "return_1_bps": return_1,
        "return_5_direction": direction,
        "body_bps": body,
        "close_location": close_location,
        "range_position_20": range_position,
        "atr_14_bps": atr,
        "range_bps": "8",
        "latest_close": "2000",
    }


def _context(kind: str) -> dict[str, Any]:
    if kind == "single":
        m15 = _tf(
            "bullish",
            return_1="2",
            body="3",
            close_location="0.75",
            range_position="0.55",
            atr="10",
        )
        h1 = _tf(
            "bullish",
            return_1="3",
            body="4",
            close_location="0.75",
            range_position="0.60",
            atr="30",
        )
        h4 = _tf(
            "bullish",
            return_1="5",
            body="5",
            close_location="0.75",
            range_position="0.60",
            atr="40",
        )
        m1_return = "1"
        session_position = "0.50"
    elif kind == "multiple":
        m15 = _tf(
            "bullish",
            return_1="2",
            body="3",
            close_location="0.80",
            range_position="0.90",
            atr="10",
        )
        h1 = _tf(
            "bullish",
            return_1="3",
            body="4",
            close_location="0.75",
            range_position="0.70",
            atr="30",
        )
        h4 = _tf(
            "bullish",
            return_1="5",
            body="5",
            close_location="0.75",
            range_position="0.70",
            atr="40",
        )
        m1_return = "2"
        session_position = "0.90"
    elif kind == "none":
        m15 = _tf(
            "flat",
            return_1="0",
            body="0",
            close_location="0.50",
            range_position="0.50",
            atr="10",
        )
        h1 = _tf(
            "flat",
            return_1="0",
            body="0",
            close_location="0.50",
            range_position="0.50",
            atr="30",
        )
        h4 = _tf(
            "flat",
            return_1="0",
            body="0",
            close_location="0.50",
            range_position="0.50",
            atr="40",
        )
        m1_return = "0"
        session_position = "0.50"
    else:
        raise ValueError(kind)

    m1 = _tf(
        m15["return_5_direction"],
        return_1=m1_return,
        body=str(m15["body_bps"]),
        close_location=str(m15["close_location"]),
        range_position="0.50",
        atr="5",
    )
    gold: dict[str, Any] = {
        "feature_definition_version": FEATURE_DEFINITION_VERSION,
        "as_of_utc": AS_OF.isoformat(),
        "symbol": "XAUUSD",
        "mode": "pit",
        "provenance_class": PIT_PROVENANCE,
        "pit_eligible": True,
        "timeframes": {
            "M1": m1,
            "M5": m1,
            "M15": m15,
            "H1": h1,
            "H4": h4,
            "D1": h4,
        },
        "range_context": {
            "utc_day": {"state": "known", "position": "0.50"},
            "session": {
                "state": "known",
                "position": session_position,
                "code": "london_new_york_overlap",
            },
        },
        "quote_context": {"state": "known", "quote_state": "known", "mid": "2000"},
        "multi_timeframe_alignment": {"state": "mixed"},
        "source_links": {},
    }
    gold["feature_packet_digest"] = hashlib.sha256(
        json.dumps(gold, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

    context: dict[str, Any] = {
        "context_packet_version": CONTEXT_PACKET_VERSION,
        "context_hash_algorithm": CONTEXT_HASH_ALGORITHM,
        "as_of_utc": AS_OF.isoformat(),
        "symbol": "XAUUSD",
        "objective_only": True,
        "retrospective_history_included": False,
        "broker_follower_state_included": False,
        "source_contract_versions": {},
        "gold": gold,
        "session": {"computed_session_code": "london_new_york_overlap"},
        "event_risk": {"evidence_state": "known", "timing_state": "clear_current_window"},
        "cross_market": {"series": {}},
        "aidy_signal_lifecycle": {"evidence_state": "known"},
        "data_quality": {
            "quote_state": "known",
            "quote_freshness": "fresh",
            "spread_state": "unknown",
        },
        "provenance": {},
    }
    context["context_hash"] = compute_context_hash(context)
    return context


def main() -> None:
    examples = []
    for kind in ("single", "multiple", "none"):
        context = _context(kind)
        regime = classify_gold_regime(context)
        detection = detect_candidate_setups(context=context, regime=regime)
        day14 = build_day14_setup_evidence_from_detection(detection, anchor_price="2000")
        examples.append(
            {
                "fixture": kind,
                "detector_state": detection["detector_state"],
                "candidate_setup_ids": detection["candidate_setup_ids"],
                "day14_setup_state": day14["setup_state"],
                "day14_risk_state": day14["risk_state"],
                "trading_decision_made": detection["trading_decision_made"],
            }
        )

    taxonomy = taxonomy_manifest()
    result = {
        "ok": True,
        "taxonomy_version": taxonomy["taxonomy_version"],
        "taxonomy_count": taxonomy["setup_count"],
        "future_outcomes_used": False,
        "trade_recommendations_made": False,
        "examples": examples,
    }
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
