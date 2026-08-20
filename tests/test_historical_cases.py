from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from aidy.context_packet import build_context_packet
from aidy.feature_engine import build_feature_packet
from aidy.historical_backfill import RETROSPECTIVE_PROVENANCE
from aidy.historical_cases import (
    ANALOGUE_INPUT_VIEW_VERSION,
    CASE_INPUT_VERSION,
    CASE_REPLAY_VERSION,
    CASE_VERSION,
    PIT_OBSERVED_PROVENANCE,
    RESEARCH_GOLD_CASES,
    analogue_input_view,
    build_historical_case,
    build_pit_case_input,
    build_retrospective_case,
    build_retrospective_case_input,
    compute_case_input_digest,
    historical_case_distribution,
    historical_case_storage_row,
    verify_case_input_digest,
    verify_historical_case_digest,
)
from aidy.market_sessions import session_code_at
from aidy.move_detective import build_move_bundle
from aidy.regime_classifier import classify_gold_regime
from aidy.setup_detector import RISK_TEMPLATE_VERSION, detect_candidate_setups
from aidy.trade_outcomes import build_trade_outcome_bundle

AS_OF = datetime(2025, 1, 10, 12, 0, tzinfo=UTC)
TF_MINUTES = {"M1": 1, "M5": 5, "M15": 15, "H1": 60, "H4": 240, "D1": 1440}


def _text(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.000001")), "f").rstrip("0").rstrip(".")


def _row(timeframe: str, stamp: datetime, index: int, bump: int = 0) -> dict[str, object]:
    base = Decimal(2000) + Decimal(index) * Decimal("0.40") + Decimal(bump)
    return {
        "research_identity": f"r-{timeframe}-{stamp.isoformat()}-{bump}",
        "provenance_class": RETROSPECTIVE_PROVENANCE,
        "pit_eligible": False,
        "symbol": "XAUUSD",
        "timeframe": timeframe,
        "open_time_utc": stamp.isoformat(),
        "open": _text(base),
        "high": _text(base + Decimal("0.40")),
        "low": _text(base - Decimal("0.15")),
        "close": _text(base + Decimal("0.25")),
        "source": "histdata",
        "source_file_sha256": "a" * 64,
        "source_payload_sha256": "b" * 64,
        "derivation_version": "fixture-v1",
    }


def _research_rows(future_bump: int = 0) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for timeframe, minutes in TF_MINUTES.items():
        if timeframe == "M1":
            for offset in range(-50, 241):
                stamp = AS_OF + timedelta(minutes=offset)
                bump = future_bump if stamp >= AS_OF else 0
                rows.append(_row(timeframe, stamp, offset + 1000, bump))
        else:
            for bars_back in range(40, 0, -1):
                rows.append(
                    _row(
                        timeframe,
                        AS_OF - timedelta(minutes=minutes * bars_back),
                        1000 - bars_back,
                    )
                )
            rows.append(_row(timeframe, AS_OF, 2000, future_bump))
    return rows


def _pit_stack():
    rows = []
    for timeframe, minutes in TF_MINUTES.items():
        for bars_back in range(35, 0, -1):
            stamp = AS_OF - timedelta(minutes=minutes * bars_back)
            item = _row(timeframe, stamp, 1000 - bars_back)
            item.pop("research_identity")
            item["load_identity"] = f"pit-{timeframe}-{bars_back}"
            item["provenance_class"] = "pit_observed"
            item["pit_eligible"] = True
            item["first_observed_at"] = (stamp + timedelta(minutes=minutes)).isoformat()
            rows.append(item)
    feature = build_feature_packet(
        as_of=AS_OF,
        symbol="XAUUSD",
        candle_rows=rows,
        mode="pit",
        snapshot={
            "captured_at": AS_OF.isoformat(),
            "load_identity": "snapshot-fixture",
            "provenance_class": "pit_observed",
            "capture_status": "complete",
            "quote_time": AS_OF.isoformat(),
            "quote_age_seconds": 0,
            "mid": "2050",
            "bid": None,
            "ask": None,
            "spread": None,
            "session_code": session_code_at(AS_OF),
            "data_availability": {"quote": "known"},
        },
    )
    context = build_context_packet(
        as_of=AS_OF,
        symbol="XAUUSD",
        feature_packet=feature,
        event_rows=[],
        macro_evidence_state="unknown",
        cross_market_rows=[],
    )
    regime = classify_gold_regime(context)
    detection = detect_candidate_setups(context=context, regime=regime)
    return context, regime, detection


def test_retrospective_input_contract_and_versions():
    packet = build_retrospective_case_input(as_of=AS_OF, research_rows=_research_rows())
    assert packet["input_version"] == CASE_INPUT_VERSION
    assert packet["replay_version"] == CASE_REPLAY_VERSION
    assert packet["provenance_class"] == RETROSPECTIVE_PROVENANCE
    assert packet["future_derived"] is False
    assert packet["analogue_match_allowed"] is True
    assert packet["live_decision_input_allowed"] is False
    assert packet["feature"]["feature_definition_version"] == "aidy_gold_features_v1"
    assert packet["regime"]["source_regime_definition_version"] == "aidy_gold_regime_v1"
    assert packet["setup"]["source_taxonomy_version"] == "aidy_gold_setup_taxonomy_v1"
    assert packet["setup"]["source_detector_version"] == "aidy_gold_setup_detector_v1"
    assert verify_case_input_digest(packet)


def test_replay_uses_only_closed_candles():
    packet = build_retrospective_case_input(as_of=AS_OF, research_rows=_research_rows())
    m1_latest = datetime.fromisoformat(packet["feature"]["summary"]["M1"]["latest_open_time_utc"])
    h1_latest = datetime.fromisoformat(packet["feature"]["summary"]["H1"]["latest_open_time_utc"])
    assert m1_latest == AS_OF - timedelta(minutes=1)
    assert h1_latest <= AS_OF - timedelta(hours=1)
    assert datetime.fromisoformat(packet["evaluation_anchor"]["forward_start_utc"]) == AS_OF


def test_future_prices_cannot_change_case_input():
    first = build_retrospective_case_input(as_of=AS_OF, research_rows=_research_rows())
    second = build_retrospective_case_input(as_of=AS_OF, research_rows=_research_rows(100))
    assert first["input_digest"] == second["input_digest"]
    assert first["analogue_features"] == second["analogue_features"]


def test_row_order_cannot_change_case_input():
    rows = _research_rows()
    first = build_retrospective_case_input(as_of=AS_OF, research_rows=rows)
    second = build_retrospective_case_input(as_of=AS_OF, research_rows=reversed(rows))
    assert first["input_digest"] == second["input_digest"]
    assert first["provenance"] == second["provenance"]


def test_retro_quality_marks_unavailable_non_price_evidence():
    packet = build_retrospective_case_input(as_of=AS_OF, research_rows=_research_rows())
    quality = packet["data_quality"]
    assert quality["quote_state"] == "unavailable_by_retrospective_provenance"
    assert quality["event_state"] == "unavailable_by_retrospective_provenance"
    assert quality["cross_market_state"] == "unavailable_by_retrospective_provenance"


def test_setup_replay_is_recognition_not_trading():
    packet = build_retrospective_case_input(as_of=AS_OF, research_rows=_research_rows())
    assert packet["setup"]["trading_decision_made"] is False
    assert packet["setup"]["trade_recommendation_made"] is False
    assert packet["setup"]["future_derived"] is False


def test_completed_case_has_hard_input_outcome_boundary():
    case = build_retrospective_case(as_of=AS_OF, research_rows=_research_rows())
    assert case["case_version"] == CASE_VERSION
    assert case["decision_input_allowed"] is False
    assert case["analogue_query_must_use_input_boundary_only"] is True
    assert case["input_boundary"]["future_derived"] is False
    assert case["future_evaluation"]["future_derived"] is True
    assert case["future_evaluation"]["analogue_match_allowed"] is False
    assert verify_historical_case_digest(case)


def test_future_outcome_can_change_without_changing_analogue_view():
    first = build_retrospective_case(as_of=AS_OF, research_rows=_research_rows())
    second = build_retrospective_case(as_of=AS_OF, research_rows=_research_rows(100))
    assert first["case_digest"] != second["case_digest"]
    assert first["case_id"] == second["case_id"]
    assert analogue_input_view(first) == analogue_input_view(second)


def test_analogue_projection_is_input_only():
    case = build_retrospective_case(as_of=AS_OF, research_rows=_research_rows())
    view = analogue_input_view(case)
    assert view["view_version"] == ANALOGUE_INPUT_VIEW_VERSION
    assert view["future_evaluation_included"] is False
    assert "future_evaluation" not in view
    assert "path_class" not in view


def test_future_field_in_input_is_rejected_after_digest_recomputed():
    case = build_retrospective_case(as_of=AS_OF, research_rows=_research_rows())
    modified = copy.deepcopy(case["input_boundary"])
    modified["outcome_state"] = "should_not_exist"
    modified["input_digest"] = compute_case_input_digest(modified)
    with pytest.raises(ValueError, match="Future/outcome field"):
        build_historical_case(
            input_boundary=modified,
            move_bundle=case["future_evaluation"]["move_bundle"],
        )


def test_changed_input_without_new_digest_is_rejected():
    case = build_retrospective_case(as_of=AS_OF, research_rows=_research_rows())
    modified = copy.deepcopy(case["input_boundary"])
    modified["data_quality"]["grade"] = "limited"
    with pytest.raises(ValueError, match="input digest"):
        build_historical_case(
            input_boundary=modified,
            move_bundle=case["future_evaluation"]["move_bundle"],
        )


def test_retro_case_cannot_claim_day14_counterfactual_truth():
    case = build_retrospective_case(as_of=AS_OF, research_rows=_research_rows())
    with pytest.raises(ValueError, match="genuinely observed PIT"):
        build_historical_case(
            input_boundary=case["input_boundary"],
            move_bundle=case["future_evaluation"]["move_bundle"],
            no_trade_counterfactual={"counterfactual_version": "aidy_no_trade_counterfactual_v1"},
        )


def test_completed_case_requires_later_evaluation():
    packet = build_retrospective_case_input(as_of=AS_OF, research_rows=_research_rows())
    with pytest.raises(ValueError, match="at least one future evaluation"):
        build_historical_case(input_boundary=packet, move_bundle=None)


def test_day13_canonical_trade_spec_extra_fields_do_not_break_geometry_match():
    rows = _research_rows()
    packet = build_retrospective_case_input(as_of=AS_OF, research_rows=rows)
    anchor = packet["evaluation_anchor"]
    anchor_time = datetime.fromisoformat(anchor["anchor_time_utc"])
    entry = Decimal(anchor["anchor_price"])
    stop = entry - Decimal(1)
    targets = [entry + Decimal(1), entry + Decimal(2)]
    packet["normalized_trade_spec"] = {
        "template_version": RISK_TEMPLATE_VERSION,
        "research_normalization_only": True,
        "direction": "long",
        "entry": _text(entry),
        "stop_loss": _text(stop),
        "targets": [_text(value) for value in targets],
    }
    packet["input_digest"] = compute_case_input_digest(packet)
    m1_rows = [row for row in rows if row["timeframe"] == "M1"]
    move = build_move_bundle(
        anchor_time=anchor_time,
        anchor_price=entry,
        research_rows=m1_rows,
    )
    trade = build_trade_outcome_bundle(
        anchor_time=anchor_time,
        direction="long",
        entry=entry,
        stop_loss=stop,
        targets=targets,
        research_rows=m1_rows,
    )
    assert "risk_distance" in trade["trade_spec"]
    assert "trade_spec_digest" in trade["trade_spec"]
    case = build_historical_case(
        input_boundary=packet,
        move_bundle=move,
        trade_outcome_bundle=trade,
    )
    assert case["future_evaluation"]["trade_outcome_bundle"] == trade


def test_pit_case_input_preserves_observed_hash_chain():
    context, regime, detection = _pit_stack()
    packet = build_pit_case_input(context=context, regime=regime, setup_detection=detection)
    assert packet["provenance_class"] == PIT_OBSERVED_PROVENANCE
    assert packet["pit_observed"] is True
    assert packet["retrospective_replay"] is False
    assert packet["provenance"]["context_hash"] == context["context_hash"]
    assert packet["provenance"]["regime_digest"] == regime["regime_digest"]
    assert packet["provenance"]["setup_detection_digest"] == detection["detection_digest"]
    assert verify_case_input_digest(packet)


def test_pit_case_rejects_modified_setup_detection():
    context, regime, detection = _pit_stack()
    modified = copy.deepcopy(detection)
    modified["source_context_hash"] = "0" * 64
    with pytest.raises(ValueError, match="digest does not match"):
        build_pit_case_input(context=context, regime=regime, setup_detection=modified)


def test_storage_contract_has_separate_json_boundaries():
    case = build_retrospective_case(as_of=AS_OF, research_rows=_research_rows())
    row = historical_case_storage_row(case)
    assert RESEARCH_GOLD_CASES.name == "research_gold_cases"
    assert RESEARCH_GOLD_CASES.partition_field == "as_of_utc"
    assert row["input_boundary"] == case["input_boundary"]
    assert row["future_evaluation"] == case["future_evaluation"]


def test_distribution_never_selects_cases_using_outcomes():
    first = build_retrospective_case(as_of=AS_OF, research_rows=_research_rows())
    second = build_retrospective_case(as_of=AS_OF, research_rows=_research_rows(100))
    distribution = historical_case_distribution([first, second])
    assert distribution["case_count"] == 2
    assert distribution["provenance_counts"][RETROSPECTIVE_PROVENANCE] == 2
    assert distribution["future_outcomes_used_for_case_selection"] is False
    assert distribution["analogue_matching_uses_input_boundary_only"] is True


def test_future_only_rows_cannot_create_a_retrievable_input():
    rows = [
        row
        for row in _research_rows()
        if datetime.fromisoformat(str(row["open_time_utc"])) >= AS_OF
    ]
    packet = build_retrospective_case_input(as_of=AS_OF, research_rows=rows)
    assert packet["data_quality"]["grade"] == "insufficient"
    assert packet["data_quality"]["retrieval_eligible"] is False
    assert packet["evaluation_anchor"] is None


def test_case_build_is_deterministic():
    first = build_retrospective_case(as_of=AS_OF, research_rows=_research_rows())
    second = build_retrospective_case(as_of=AS_OF, research_rows=_research_rows())
    assert first == second
