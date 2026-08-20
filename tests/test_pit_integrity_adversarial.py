from __future__ import annotations

import copy
import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256

import pytest

from aidy.analogue_retrieval import build_analogue_query, retrieve_analogues
from aidy.context_packet import build_context_packet, compute_context_hash
from aidy.cross_market import SERIES_US10Y
from aidy.cross_market_asof import reconstruct_cross_market_as_of
from aidy.evidence_grading import build_evidence_report
from aidy.feature_engine import FEATURE_DEFINITION_VERSION, build_feature_packet
from aidy.historical_backfill import RETROSPECTIVE_PROVENANCE
from aidy.historical_cases import (
    CASE_DIGEST_ALGORITHM,
    CASE_INPUT_VERSION,
    CASE_VERSION,
    PIT_OBSERVED_PROVENANCE,
    build_historical_case,
    compute_case_input_digest,
    compute_historical_case_digest,
)
from aidy.pit_integrity import attack_catalogue, build_integrity_report, integrity_manifest
from aidy.pit_reconstruction import (
    query_contract,
    select_latest_events_as_of,
    select_latest_revisions_as_of,
    select_snapshot_as_of,
)
from aidy.regime_classifier import (
    REGIME_DEFINITION_VERSION,
    classify_gold_regime,
    compute_regime_digest,
)
from aidy.setup_detector import (
    SETUP_DETECTOR_VERSION,
    SETUP_TAXONOMY_VERSION,
    detect_candidate_setups,
)

AS_OF = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value: object) -> str:
    return sha256(_canonical_json(value).encode()).hexdigest()


def _rehash_feature(packet: dict[str, object]) -> None:
    body = copy.deepcopy(packet)
    body.pop("feature_packet_digest", None)
    packet["feature_packet_digest"] = _digest(body)


def _candle(*, revision: int, observed_at: datetime, close: str) -> dict[str, object]:
    return {
        "load_identity": f"candle-{revision}",
        "revision_index": revision,
        "source": "fixture",
        "symbol": "XAUUSD",
        "timeframe": "M1",
        "open_time_utc": AS_OF - timedelta(minutes=1),
        "first_observed_at": observed_at,
        "open": "100",
        "high": "102",
        "low": "99",
        "close": close,
    }


def _event(*, revision: int, observed_at: datetime, headline: str) -> dict[str, object]:
    return {
        "load_identity": f"event-{revision}",
        "revision_index": revision,
        "source": "fixture",
        "external_id": "event-1",
        "first_observed_at": observed_at,
        "headline": headline,
    }


def _snapshot(*, captured_at: datetime) -> dict[str, object]:
    return {
        "load_identity": f"snapshot-{captured_at.isoformat()}",
        "captured_at": captured_at,
        "symbol": "XAUUSD",
        "capture_status": "complete",
        "mid": "2000",
        "data_availability": {"quote": "available"},
    }


def _feature() -> dict[str, object]:
    return build_feature_packet(
        as_of=AS_OF,
        symbol="XAUUSD",
        candle_rows=[],
        mode="pit",
    )


def _context(*, signal_state: dict[str, object] | None = None) -> dict[str, object]:
    return build_context_packet(
        as_of=AS_OF,
        symbol="XAUUSD",
        feature_packet=_feature(),
        event_rows=[],
        macro_evidence_state="known",
        cross_market_rows=[],
        aidy_signal_state=signal_state,
    )


def _analogue_features() -> dict[str, object]:
    return {
        "regime": {
            "trend_structure": "bullish_trend",
            "volatility_band": "normal",
            "session": "london_new_york_overlap",
            "quote_spread_condition": "fresh_quote_spread_unknown",
            "event_timing": "clear_current_window",
        },
        "m15_direction": "bullish",
        "h1_direction": "bullish",
        "h4_direction": "bullish",
        "h1_atr_14_bps": "35",
        "m15_realized_vol_20_bps": "22",
        "m15_range_position_20": "0.72",
        "m15_close_location": "0.68",
        "session_range_position": "0.66",
        "setup_detector_state": "single",
        "candidate_setup_ids": ["trend_momentum_long"],
    }


def _case_input(*, as_of: datetime, provenance: str) -> dict[str, object]:
    retrospective = provenance == RETROSPECTIVE_PROVENANCE
    packet: dict[str, object] = {
        "input_version": CASE_INPUT_VERSION,
        "replay_version": "test_replay_v1" if retrospective else None,
        "symbol": "XAUUSD",
        "as_of_utc": as_of.isoformat(),
        "provenance_class": provenance,
        "pit_observed": not retrospective,
        "retrospective_replay": retrospective,
        "future_derived": False,
        "analogue_match_allowed": True,
        "live_decision_input_allowed": not retrospective,
        "feature": {
            "feature_definition_version": FEATURE_DEFINITION_VERSION,
            "feature_packet_digest": "f" * 64,
            "mode": "retrospective" if retrospective else "pit",
            "summary": {},
        },
        "regime": {
            (
                "source_regime_definition_version"
                if retrospective
                else "regime_definition_version"
            ): REGIME_DEFINITION_VERSION,
            "labels": _analogue_features()["regime"],
            "compound_regime_key": "fixture",
        },
        "setup": {
            (
                "source_taxonomy_version" if retrospective else "taxonomy_version"
            ): SETUP_TAXONOMY_VERSION,
            (
                "source_detector_version" if retrospective else "detector_version"
            ): SETUP_DETECTOR_VERSION,
            "detector_state": "single",
            "candidate_setup_ids": ["trend_momentum_long"],
            "candidate_directions": ["long"],
            "unresolved_setup_ids": [],
        },
        "normalized_trade_spec": None,
        "data_quality": {
            "quality_version": "fixture_quality_v1",
            "grade": "strong",
            "retrieval_eligible": True,
        },
        "analogue_features": _analogue_features(),
        "evaluation_anchor": None,
        "provenance": {"source_provenance_class": provenance},
    }
    packet["input_digest"] = compute_case_input_digest(packet)
    return packet


def _case(
    *,
    as_of: datetime,
    future_available_after: datetime,
    outcome_marker: str = "baseline",
) -> dict[str, object]:
    boundary = _case_input(as_of=as_of, provenance=RETROSPECTIVE_PROVENANCE)
    case_id = _digest(
        {
            "case_version": CASE_VERSION,
            "symbol": "XAUUSD",
            "as_of_utc": boundary["as_of_utc"],
            "provenance_class": RETROSPECTIVE_PROVENANCE,
            "input_digest": boundary["input_digest"],
        }
    )
    future = {
        "evaluation_only": True,
        "future_derived": True,
        "pit_eligible": False,
        "decision_input_allowed": False,
        "analogue_match_allowed": False,
        "available_after_utc": future_available_after.isoformat(),
        "move_bundle": {"outcome_marker": outcome_marker},
        "trade_outcome_bundle": None,
        "no_trade_counterfactual": None,
        "causal_claims_included": False,
    }
    case: dict[str, object] = {
        "case_version": CASE_VERSION,
        "case_digest_algorithm": CASE_DIGEST_ALGORITHM,
        "case_id": case_id,
        "symbol": "XAUUSD",
        "as_of_utc": boundary["as_of_utc"],
        "provenance_class": RETROSPECTIVE_PROVENANCE,
        "decision_input_allowed": False,
        "analogue_query_must_use_input_boundary_only": True,
        "input_boundary": boundary,
        "future_evaluation": future,
    }
    case["case_digest"] = compute_historical_case_digest(case)
    return case


def _query(*, as_of: datetime) -> dict[str, object]:
    return build_analogue_query(
        input_boundary=_case_input(as_of=as_of, provenance=PIT_OBSERVED_PROVENANCE),
        allowed_provenance=(RETROSPECTIVE_PROVENANCE,),
        max_results=8,
    )


def _rehash_retrieval(retrieval: dict[str, object]) -> None:
    body = copy.deepcopy(retrieval)
    body.pop("retrieval_digest", None)
    retrieval["retrieval_digest"] = _digest(body)


def test_attack_catalogue_is_complete_and_versioned() -> None:
    manifest = integrity_manifest()
    attacks = attack_catalogue()
    assert manifest["attack_count"] == 18
    assert len(attacks) == 18
    assert len({item["attack_id"] for item in attacks}) == 18
    report = build_integrity_report(
        blocked_attack_ids=[item["attack_id"] for item in attacks]
    )
    assert report["all_attacks_blocked"] is True
    assert report["blocked_attack_count"] == 18
    assert report["unresolved_attack_ids"] == []


def test_future_candle_revision_is_not_visible_before_first_observed_at() -> None:
    rows = [
        _candle(revision=1, observed_at=AS_OF - timedelta(minutes=1), close="100"),
        _candle(revision=2, observed_at=AS_OF + timedelta(minutes=1), close="999"),
    ]
    selected = select_latest_revisions_as_of(
        rows,
        as_of=AS_OF,
        key_fields=("source", "symbol", "timeframe", "open_time_utc"),
    )
    assert [row["revision_index"] for row in selected] == [1]
    assert selected[0]["close"] == "100"


def test_future_macro_revision_is_not_visible_at_earlier_asof() -> None:
    rows = [
        _event(revision=1, observed_at=AS_OF - timedelta(days=1), headline="known"),
        _event(revision=2, observed_at=AS_OF + timedelta(seconds=1), headline="future"),
    ]
    selected = select_latest_events_as_of(rows, as_of=AS_OF)
    assert selected[0]["headline"] == "known"
    assert selected[0]["revision_index"] == 1


def test_future_snapshot_is_not_visible_at_earlier_asof() -> None:
    selected = select_snapshot_as_of(
        [_snapshot(captured_at=AS_OF + timedelta(seconds=1))],
        as_of=AS_OF,
        symbol="XAUUSD",
    )
    assert selected is None


def test_future_cross_market_observation_or_revision_cannot_leak() -> None:
    rows = [
        {
            "source": "us_treasury",
            "series_id": SERIES_US10Y,
            "observation_date": AS_OF.date().isoformat(),
            "value": "4.20",
            "unit": "percent",
            "first_observed_at": AS_OF - timedelta(minutes=1),
            "revision_index": 1,
            "load_identity": "old",
        },
        {
            "source": "us_treasury",
            "series_id": SERIES_US10Y,
            "observation_date": AS_OF.date().isoformat(),
            "value": "9.99",
            "unit": "percent",
            "first_observed_at": AS_OF + timedelta(minutes=1),
            "revision_index": 2,
            "load_identity": "future",
        },
    ]
    packet = reconstruct_cross_market_as_of(rows, as_of=AS_OF)
    assert packet["series"][SERIES_US10Y]["fact"]["value"] == "4.20"
    assert packet["series"][SERIES_US10Y]["fact"]["revision_index"] == 1


def test_retrospective_research_candle_cannot_enter_pit_features() -> None:
    row = {
        "symbol": "XAUUSD",
        "provenance_class": RETROSPECTIVE_PROVENANCE,
        "pit_eligible": False,
    }
    with pytest.raises(ValueError, match="Retrospective-only evidence"):
        build_feature_packet(
            as_of=AS_OF,
            symbol="XAUUSD",
            candle_rows=[row],
            mode="pit",
        )


def test_future_snapshot_cannot_enter_pit_features() -> None:
    with pytest.raises(ValueError, match="captured after"):
        build_feature_packet(
            as_of=AS_OF,
            symbol="XAUUSD",
            candle_rows=[],
            mode="pit",
            snapshot=_snapshot(captured_at=AS_OF + timedelta(seconds=1)),
        )


def test_day10_rejects_rehashed_future_field_inside_feature_packet() -> None:
    feature = _feature()
    feature["timeframes"]["M1"]["outcome_state"] = "winner"
    _rehash_feature(feature)
    with pytest.raises(ValueError, match="Future/outcome field"):
        build_context_packet(
            as_of=AS_OF,
            symbol="XAUUSD",
            feature_packet=feature,
            event_rows=[],
            macro_evidence_state="known",
            cross_market_rows=[],
        )


def test_day10_rejects_rehashed_retrospective_lineage_nested_in_pit_packet() -> None:
    feature = _feature()
    feature["source_links"]["M1"] = [
        {
            "identity": "forged-retrospective-row",
            "provenance_class": RETROSPECTIVE_PROVENANCE,
            "pit_eligible": False,
        }
    ]
    _rehash_feature(feature)
    with pytest.raises(ValueError, match="Retrospective-only evidence"):
        build_context_packet(
            as_of=AS_OF,
            symbol="XAUUSD",
            feature_packet=feature,
            event_rows=[],
            macro_evidence_state="known",
            cross_market_rows=[],
        )


def test_future_signal_lifecycle_state_is_rejected() -> None:
    with pytest.raises(ValueError, match="future state"):
        _context(
            signal_state={
                "state": "active",
                "as_of_utc": AS_OF,
                "active_signals": [
                    {
                        "aidy_signal_id": "a",
                        "updated_at_utc": (AS_OF + timedelta(seconds=1)).isoformat(),
                    }
                ],
            }
        )


def test_evaluation_record_cannot_be_smuggled_as_signal_lifecycle_state() -> None:
    with pytest.raises(ValueError, match="Unsupported AIDY signal-state fields"):
        _context(
            signal_state={
                "state": "none",
                "active_signals": [],
                "future_evaluation": {
                    "evaluation_only": True,
                    "future_derived": True,
                },
            }
        )


def test_day11_rejects_rehashed_hindsight_context() -> None:
    context = _context()
    context["gold"]["future_return"] = "123.4"
    context["context_hash"] = compute_context_hash(context)
    with pytest.raises(ValueError, match="Hindsight field"):
        classify_gold_regime(context)


def test_day15_rejects_rehashed_hindsight_even_with_matching_regime_hash() -> None:
    context = _context()
    regime = classify_gold_regime(context)
    bad_context = copy.deepcopy(context)
    bad_context["gold"]["outcome_state"] = "target_only"
    bad_context["context_hash"] = compute_context_hash(bad_context)
    bad_regime = copy.deepcopy(regime)
    bad_regime["source_context_hash"] = bad_context["context_hash"]
    bad_regime["regime_digest"] = compute_regime_digest(bad_regime)
    with pytest.raises(ValueError, match="Future/outcome field"):
        detect_candidate_setups(context=bad_context, regime=bad_regime)


def test_day15_rejects_regime_from_different_context() -> None:
    first = _context()
    second = _context(signal_state={"state": "none", "active_signals": []})
    assert first["context_hash"] != second["context_hash"]
    foreign_regime = classify_gold_regime(second)
    with pytest.raises(ValueError, match="originate from the supplied context hash"):
        detect_candidate_setups(context=first, regime=foreign_regime)


def test_day16_rejects_future_field_in_input_even_after_rehash() -> None:
    boundary = _case_input(
        as_of=AS_OF - timedelta(days=10),
        provenance=RETROSPECTIVE_PROVENANCE,
    )
    boundary["future_evaluation"] = {"outcome_state": "winner"}
    boundary["input_digest"] = compute_case_input_digest(boundary)
    with pytest.raises(ValueError, match="Future/outcome field"):
        build_historical_case(input_boundary=boundary, move_bundle=None)


def test_day17_excludes_candidate_at_or_after_query_time() -> None:
    query = _query(as_of=AS_OF)
    candidate = _case(
        as_of=AS_OF,
        future_available_after=AS_OF,
    )
    result = retrieve_analogues(query=query, candidate_cases=[candidate])
    assert result["returned_match_count"] == 0
    assert result["exclusion_counts"]["candidate_not_before_query"] == 1


def test_day17_excludes_outcome_not_available_by_query_time() -> None:
    query = _query(as_of=AS_OF)
    candidate = _case(
        as_of=AS_OF - timedelta(days=1),
        future_available_after=AS_OF + timedelta(seconds=1),
    )
    result = retrieve_analogues(query=query, candidate_cases=[candidate])
    assert result["returned_match_count"] == 0
    assert result["exclusion_counts"]["outcome_not_yet_available"] == 1


def test_day17_future_outcome_contents_cannot_change_similarity_or_selection() -> None:
    query = _query(as_of=AS_OF)
    candidate_time = AS_OF - timedelta(days=2)
    winner = _case(
        as_of=candidate_time,
        future_available_after=candidate_time + timedelta(hours=4),
        outcome_marker="winner",
    )
    loser = _case(
        as_of=candidate_time,
        future_available_after=candidate_time + timedelta(hours=4),
        outcome_marker="loser",
    )
    left = retrieve_analogues(query=query, candidate_cases=[winner])
    right = retrieve_analogues(query=query, candidate_cases=[loser])
    assert left["selection_digest"] == right["selection_digest"]
    assert left["matches"][0]["similarity"] == right["matches"][0]["similarity"]
    assert left["retrieval_digest"] != right["retrieval_digest"]


def test_day18_rejects_rehashed_selection_tamper() -> None:
    query = _query(as_of=AS_OF)
    candidate_time = AS_OF - timedelta(days=2)
    candidate = _case(
        as_of=candidate_time,
        future_available_after=candidate_time + timedelta(hours=4),
    )
    retrieval = retrieve_analogues(query=query, candidate_cases=[candidate])
    retrieval["selection_digest"] = "0" * 64
    _rehash_retrieval(retrieval)
    with pytest.raises(ValueError, match="selection digest"):
        build_evidence_report(retrieval=retrieval)


def test_day18_rejects_rehashed_match_that_claims_outcome_affected_similarity() -> None:
    query = _query(as_of=AS_OF)
    candidate_time = AS_OF - timedelta(days=2)
    candidate = _case(
        as_of=candidate_time,
        future_available_after=candidate_time + timedelta(hours=4),
    )
    retrieval = retrieve_analogues(query=query, candidate_cases=[candidate])
    retrieval["matches"][0]["outcome_used_for_similarity"] = True
    _rehash_retrieval(retrieval)
    with pytest.raises(ValueError, match="outcome affected similarity"):
        build_evidence_report(retrieval=retrieval)


def test_sql_contracts_filter_knowability_before_ranking_and_keep_outcome_tables_out() -> None:
    queries = query_contract(project="aidy-signals", dataset="aidy_analytics_test")
    combined = "\n".join(query.sql.lower() for query in queries.values())
    assert "first_observed_at <= @as_of" in combined
    assert "captured_at <= @as_of" in combined
    assert "research_candles" not in combined
    assert "research_trade_outcomes" not in combined
    assert "research_move_labels" not in combined
    assert "research_no_trade_counterfactuals" not in combined
