from __future__ import annotations

import copy
import hashlib
import json
from datetime import UTC, datetime

import pytest

from aidy.context_packet import (
    CONTEXT_HASH_ALGORITHM,
    CONTEXT_PACKET_VERSION,
    compute_context_hash,
)
from aidy.feature_engine import FEATURE_DEFINITION_VERSION, PIT_PROVENANCE
from aidy.no_trade_counterfactual import SETUP_EVIDENCE_VERSION, verify_setup_evidence_digest
from aidy.regime_classifier import classify_gold_regime
from aidy.setup_detector import (
    RESEARCH_SETUP_DETECTIONS,
    RISK_TEMPLATE_VERSION,
    SETUP_DEFINITIONS,
    SETUP_DETECTION_VERSION,
    SETUP_DETECTOR_VERSION,
    SETUP_TAXONOMY_VERSION,
    build_day14_setup_evidence_from_detection,
    detect_candidate_setups,
    setup_detection_distribution,
    setup_detection_storage_row,
    taxonomy_manifest,
    verify_setup_detection_digest,
)

AS_OF = datetime(2026, 8, 20, 9, 0, tzinfo=UTC)


def _tf(
    *,
    direction: str = "bullish",
    return_1: str | None = "2",
    body: str | None = "3",
    close_location: str | None = "0.75",
    range_position: str | None = "0.55",
    atr: str | None = "10",
    range_bps: str | None = "8",
    close: str | None = "2000",
) -> dict[str, object]:
    return {
        "state": "known",
        "return_1_bps": return_1,
        "return_5_direction": direction,
        "body_bps": body,
        "close_location": close_location,
        "range_position_20": range_position,
        "atr_14_bps": atr,
        "range_bps": range_bps,
        "latest_close": close,
    }


def _gold(
    *,
    trend: str = "bullish",
    m15_direction: str | None = None,
    m15_return_1: str | None = None,
    m15_body: str | None = None,
    m15_close_location: str | None = None,
    m15_range_position: str | None = None,
    h1_atr: str | None = "30",
    session_position: str | None = "0.50",
    m1_return_1: str | None = "1",
    known: bool = True,
) -> dict[str, object]:
    if not known:
        timeframes = {
            name: {"state": "unknown"}
            for name in ("M1", "M5", "M15", "H1", "H4", "D1")
        }
        session = {"state": "unknown", "position": None}
    else:
        bullish = trend == "bullish"
        base_direction = "bullish" if bullish else "bearish" if trend == "bearish" else "flat"
        sign = "2" if bullish else "-2" if trend == "bearish" else "0"
        body = "3" if bullish else "-3" if trend == "bearish" else "0"
        close_location = "0.75" if bullish else "0.25" if trend == "bearish" else "0.50"
        timeframes = {
            "M1": _tf(direction=base_direction, return_1=m1_return_1, body=body),
            "M5": _tf(direction=base_direction, return_1=sign, body=body),
            "M15": _tf(
                direction=m15_direction or base_direction,
                return_1=m15_return_1 if m15_return_1 is not None else sign,
                body=m15_body if m15_body is not None else body,
                close_location=m15_close_location or close_location,
                range_position=m15_range_position or "0.55",
            ),
            "H1": _tf(direction=base_direction, return_1=sign, body=body, atr=h1_atr),
            "H4": _tf(direction=base_direction, return_1=sign, body=body, atr="40"),
            "D1": _tf(direction=base_direction, return_1=sign, body=body, atr="70"),
        }
        session = {
            "state": "known",
            "position": session_position,
            "code": "london_new_york_overlap",
        }

    packet: dict[str, object] = {
        "feature_definition_version": FEATURE_DEFINITION_VERSION,
        "as_of_utc": AS_OF.isoformat(),
        "symbol": "XAUUSD",
        "mode": "pit",
        "provenance_class": PIT_PROVENANCE,
        "pit_eligible": True,
        "timeframes": timeframes,
        "range_context": {
            "utc_day": {"state": "known", "position": "0.50"},
            "session": session,
        },
        "quote_context": {"state": "known", "quote_state": "known", "mid": "2000"},
        "multi_timeframe_alignment": {"state": "mixed"},
        "source_links": {},
    }
    packet["feature_packet_digest"] = hashlib.sha256(
        json.dumps(packet, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return packet


def _context(**gold_kwargs: object) -> dict[str, object]:
    packet: dict[str, object] = {
        "context_packet_version": CONTEXT_PACKET_VERSION,
        "context_hash_algorithm": CONTEXT_HASH_ALGORITHM,
        "as_of_utc": AS_OF.isoformat(),
        "symbol": "XAUUSD",
        "objective_only": True,
        "retrospective_history_included": False,
        "broker_follower_state_included": False,
        "source_contract_versions": {},
        "gold": _gold(**gold_kwargs),
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
    packet["context_hash"] = compute_context_hash(packet)
    return packet


def _regime(context: dict[str, object]) -> dict[str, object]:
    return classify_gold_regime(context)


def _detect(**kwargs: object) -> dict[str, object]:
    context = _context(**kwargs)
    return detect_candidate_setups(context=context, regime=_regime(context))


def test_taxonomy_has_exactly_twenty_unique_human_auditable_variants() -> None:
    manifest = taxonomy_manifest()
    assert manifest["taxonomy_version"] == SETUP_TAXONOMY_VERSION
    assert manifest["setup_count"] == 20
    assert len(SETUP_DEFINITIONS) == 20
    assert len(set(manifest["setup_ids"])) == 20
    assert len(manifest["families"]) >= 8
    assert manifest["trading_decision_made"] is False
    assert manifest["threshold_basis"] == "fixed_v1_descriptive_not_future_outcome_calibrated"


def test_single_bullish_trend_momentum_setup_is_detected() -> None:
    packet = _detect(trend="bullish", m15_range_position="0.55", session_position="0.50")
    assert packet["detector_state"] == "single"
    assert packet["candidate_setup_ids"] == ["trend_momentum_long"]
    assert packet["candidate_directions"] == ["long"]


def test_single_bearish_trend_momentum_setup_is_detected() -> None:
    packet = _detect(
        trend="bearish",
        m15_range_position="0.45",
        session_position="0.50",
        m1_return_1="-1",
    )
    assert packet["detector_state"] == "single"
    assert packet["candidate_setup_ids"] == ["trend_momentum_short"]
    assert packet["candidate_directions"] == ["short"]


def test_multiple_setup_state_preserves_every_matching_candidate() -> None:
    packet = _detect(
        trend="bullish",
        m15_range_position="0.90",
        session_position="0.90",
        m1_return_1="2",
    )
    assert packet["detector_state"] == "multiple"
    assert "trend_momentum_long" in packet["candidate_setup_ids"]
    assert "recent_high_pressure_long" in packet["candidate_setup_ids"]
    assert "session_high_pressure_long" in packet["candidate_setup_ids"]


def test_none_state_is_explicit_when_every_rule_is_falsified() -> None:
    packet = _detect(
        trend="flat",
        m15_direction="flat",
        m15_return_1="0",
        m15_body="0",
        m15_close_location="0.50",
        m15_range_position="0.50",
        session_position="0.50",
        m1_return_1="0",
    )
    assert packet["detector_state"] == "none"
    assert packet["candidate_setup_ids"] == []
    assert packet["unresolved_setup_ids"] == []


def test_unknown_inputs_produce_indeterminate_not_a_fake_none() -> None:
    packet = _detect(known=False)
    assert packet["detector_state"] == "indeterminate"
    assert packet["candidate_setup_ids"] == []
    assert packet["unresolved_setup_ids"]


def test_detector_is_deterministic_and_digest_verified() -> None:
    context = _context(trend="bullish")
    regime = _regime(context)
    first = detect_candidate_setups(context=context, regime=regime)
    second = detect_candidate_setups(context=copy.deepcopy(context), regime=copy.deepcopy(regime))
    assert first == second
    assert verify_setup_detection_digest(first)


def test_tampered_detection_digest_is_rejected_by_storage() -> None:
    packet = _detect(trend="bullish")
    packet["candidate_setup_ids"] = ["forged"]
    assert not verify_setup_detection_digest(packet)
    with pytest.raises(ValueError, match="digest"):
        setup_detection_storage_row(packet)


def test_context_hash_tampering_fails_closed() -> None:
    context = _context(trend="bullish")
    regime = _regime(context)
    context["data_quality"] = {"quote_freshness": "stale"}
    with pytest.raises(ValueError, match="context hash"):
        detect_candidate_setups(context=context, regime=regime)


def test_regime_digest_tampering_fails_closed() -> None:
    context = _context(trend="bullish")
    regime = _regime(context)
    regime["labels"]["trend_structure"] = "bearish_trend"
    with pytest.raises(ValueError, match="regime digest"):
        detect_candidate_setups(context=context, regime=regime)


def test_regime_must_belong_to_exact_context() -> None:
    first = _context(trend="bullish")
    second = _context(trend="bearish", m1_return_1="-1")
    with pytest.raises(ValueError, match="originate"):
        detect_candidate_setups(context=first, regime=_regime(second))


def test_retrospective_feature_packet_cannot_enter_detector() -> None:
    context = _context(trend="bullish")
    gold = context["gold"]
    assert isinstance(gold, dict)
    gold["mode"] = "retrospective"
    gold["provenance_class"] = "retrospective_history"
    gold["pit_eligible"] = False
    context["context_hash"] = compute_context_hash(context)
    with pytest.raises(ValueError, match="PIT Gold features"):
        detect_candidate_setups(context=context, regime=_regime(context))


def test_future_outcome_field_injection_is_recursively_rejected_by_day15() -> None:
    context = _context(trend="bullish")
    regime = _regime(context)
    context["illicit"] = {"deep": {"outcome_state": "target_only"}}
    context["context_hash"] = compute_context_hash(context)
    with pytest.raises(ValueError, match="Future/outcome"):
        detect_candidate_setups(context=context, regime=regime)


def test_detection_packet_is_pit_safe_and_not_a_trade_decision() -> None:
    packet = _detect(trend="bullish")
    assert packet["detection_version"] == SETUP_DETECTION_VERSION
    assert packet["detector_version"] == SETUP_DETECTOR_VERSION
    assert packet["pit_eligible"] is True
    assert packet["future_derived"] is False
    assert packet["decision_input_allowed"] is True
    assert packet["trading_decision_made"] is False
    assert packet["trade_recommendation_made"] is False


def test_single_detection_adapts_to_day14_with_normalized_atr_geometry() -> None:
    packet = _detect(trend="bullish", h1_atr="30")
    evidence = build_day14_setup_evidence_from_detection(packet, anchor_price="2000")
    assert evidence["evidence_version"] == SETUP_EVIDENCE_VERSION
    assert evidence["setup_state"] == "present"
    assert evidence["risk_state"] == "valid"
    assert evidence["direction"] == "long"
    assert evidence["candidate_setup_ids"] == ["trend_momentum_long"]
    assert evidence["trade_spec"] == {
        "entry_type": "market",
        "entry": "2000",
        "stop_loss": "1994",
        "targets": ["2006", "2012"],
    }
    assert verify_setup_evidence_digest(evidence)


def test_single_detection_with_missing_atr_keeps_risk_unknown() -> None:
    packet = _detect(trend="bullish", h1_atr=None)
    evidence = build_day14_setup_evidence_from_detection(packet, anchor_price="2000")
    assert evidence["setup_state"] == "present"
    assert evidence["risk_state"] == "unknown"
    assert evidence["trade_spec"] is None


def test_multiple_detection_maps_to_day14_ambiguous() -> None:
    packet = _detect(
        trend="bullish",
        m15_range_position="0.90",
        session_position="0.90",
        m1_return_1="2",
    )
    evidence = build_day14_setup_evidence_from_detection(packet, anchor_price="2000")
    assert evidence["setup_state"] == "ambiguous"
    assert evidence["risk_state"] == "unknown"
    assert len(evidence["candidate_setup_ids"]) >= 2
    assert evidence["direction"] is None


def test_none_detection_maps_to_day14_absent() -> None:
    packet = _detect(
        trend="flat",
        m15_direction="flat",
        m15_return_1="0",
        m15_body="0",
        m15_close_location="0.50",
        m15_range_position="0.50",
        session_position="0.50",
        m1_return_1="0",
    )
    evidence = build_day14_setup_evidence_from_detection(packet, anchor_price="2000")
    assert evidence["setup_state"] == "absent"
    assert evidence["risk_state"] == "not_applicable"
    assert evidence["trade_spec"] is None


def test_indeterminate_detection_maps_to_day14_unknown() -> None:
    packet = _detect(known=False)
    evidence = build_day14_setup_evidence_from_detection(packet, anchor_price="2000")
    assert evidence["setup_state"] == "unknown"
    assert evidence["risk_state"] == "unknown"


def test_day14_adapter_rejects_anchor_price_not_present_in_detection_evidence() -> None:
    packet = _detect(trend="bullish")
    with pytest.raises(ValueError, match="anchor_price"):
        build_day14_setup_evidence_from_detection(packet, anchor_price="2001")


def test_risk_template_is_research_normalization_not_recommendation() -> None:
    packet = _detect(trend="bullish")
    basis = packet["risk_basis"]
    assert basis["risk_template_version"] == RISK_TEMPLATE_VERSION
    assert basis["research_normalization_only"] is True
    assert basis["trade_recommendation"] is False


def test_storage_contract_is_separate_and_contains_no_future_outcomes() -> None:
    packet = _detect(trend="bullish")
    row = setup_detection_storage_row(packet)
    assert RESEARCH_SETUP_DETECTIONS.name == "research_setup_detections"
    assert row["pit_eligible"] is True
    assert row["future_derived"] is False
    assert row["trading_decision_made"] is False
    assert "outcome" not in " ".join(row).lower()


def test_distribution_counts_only_setup_prevalence_not_outcomes() -> None:
    single = _detect(trend="bullish")
    multiple = _detect(
        trend="bullish",
        m15_range_position="0.90",
        session_position="0.90",
        m1_return_1="2",
    )
    none = _detect(
        trend="flat",
        m15_direction="flat",
        m15_return_1="0",
        m15_body="0",
        m15_close_location="0.50",
        m15_range_position="0.50",
        session_position="0.50",
        m1_return_1="0",
    )
    result = setup_detection_distribution((single, multiple, none))
    assert result["packet_count"] == 3
    assert result["detector_state_counts"] == {"multiple": 1, "none": 1, "single": 1}
    assert result["outcome_statistics_included"] is False
