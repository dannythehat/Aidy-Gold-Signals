from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256

from aidy.analogue_retrieval import build_analogue_query
from aidy.analogue_retrieval_v3 import retrieve_analogues_v3, verify_retrieval_digest_v3
from aidy.feature_engine import FEATURE_DEFINITION_VERSION
from aidy.historical_backfill import RETROSPECTIVE_PROVENANCE
from aidy.historical_case_context_v2 import (
    enrich_historical_case_with_market_structure,
    market_structure_epoch_from_case,
)
from aidy.historical_cases import (
    CASE_DIGEST_ALGORITHM,
    CASE_INPUT_VERSION,
    CASE_VERSION,
    PIT_OBSERVED_PROVENANCE,
    compute_case_input_digest,
    compute_historical_case_digest,
)
from aidy.j5_epoch_effect import run_j5_epoch_effect, verify_j5_digest
from aidy.market_structure_context import (
    ONE_OZ_24X7_BOUNDARY_UTC,
    SCHEDULE_RECORD_VERSION,
    build_market_structure_context,
    market_structure_epoch_at,
    one_oz_weekend_state_at,
    verify_market_structure_context,
)
from aidy.regime_classifier import REGIME_DEFINITION_VERSION
from aidy.setup_detector import SETUP_DETECTOR_VERSION, SETUP_TAXONOMY_VERSION


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value: object) -> str:
    return sha256(_canonical_json(value).encode()).hexdigest()


def _features() -> dict[str, object]:
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


def _input(*, as_of: datetime, provenance: str) -> dict[str, object]:
    features = _features()
    regime_labels = dict(features["regime"])  # type: ignore[arg-type]
    packet: dict[str, object] = {
        "input_version": CASE_INPUT_VERSION,
        "replay_version": "test_replay_v1" if provenance == RETROSPECTIVE_PROVENANCE else None,
        "symbol": "XAUUSD",
        "as_of_utc": as_of.isoformat(),
        "provenance_class": provenance,
        "pit_observed": provenance == PIT_OBSERVED_PROVENANCE,
        "retrospective_replay": provenance == RETROSPECTIVE_PROVENANCE,
        "future_derived": False,
        "analogue_match_allowed": True,
        "live_decision_input_allowed": provenance == PIT_OBSERVED_PROVENANCE,
        "feature": {
            "feature_definition_version": FEATURE_DEFINITION_VERSION,
            "feature_packet_digest": "f" * 64,
            "mode": "pit" if provenance == PIT_OBSERVED_PROVENANCE else "retrospective",
            "summary": {},
        },
        "regime": {
            (
                "regime_definition_version"
                if provenance == PIT_OBSERVED_PROVENANCE
                else "source_regime_definition_version"
            ): REGIME_DEFINITION_VERSION,
            "labels": regime_labels,
            "compound_regime_key": "|".join(
                f"{key}={value}" for key, value in regime_labels.items()
            ),
        },
        "setup": {
            (
                "taxonomy_version"
                if provenance == PIT_OBSERVED_PROVENANCE
                else "source_taxonomy_version"
            ): SETUP_TAXONOMY_VERSION,
            (
                "detector_version"
                if provenance == PIT_OBSERVED_PROVENANCE
                else "source_detector_version"
            ): SETUP_DETECTOR_VERSION,
            "detector_state": "single",
            "candidate_setup_ids": ["trend_momentum_long"],
            "candidate_directions": ["long"],
            "unresolved_setup_ids": [],
        },
        "normalized_trade_spec": None,
        "data_quality": {
            "quality_version": "test_quality_v1",
            "grade": "strong",
            "retrieval_eligible": True,
        },
        "analogue_features": features,
        "evaluation_anchor": {
            "anchor_time_utc": as_of.isoformat(),
            "anchor_price": "2000",
            "forward_start_utc": as_of.isoformat(),
            "alignment_rule": "test",
        },
        "provenance": {"source_provenance_class": provenance},
    }
    packet["input_digest"] = compute_case_input_digest(packet)
    return packet


def _case(*, as_of: datetime, outcome: str = "10") -> dict[str, object]:
    boundary = _input(as_of=as_of, provenance=RETROSPECTIVE_PROVENANCE)
    case_id = _digest(
        {
            "case_version": CASE_VERSION,
            "symbol": "XAUUSD",
            "as_of_utc": boundary["as_of_utc"],
            "provenance_class": RETROSPECTIVE_PROVENANCE,
            "input_digest": boundary["input_digest"],
        }
    )
    end = as_of + timedelta(minutes=240)
    future = {
        "evaluation_only": True,
        "future_derived": True,
        "pit_eligible": False,
        "decision_input_allowed": False,
        "analogue_match_allowed": False,
        "available_after_utc": end.isoformat(),
        "move_bundle": {
            "labels": [
                {
                    "horizon_minutes": 240,
                    "coverage_state": "complete",
                    "anchor_time_utc": as_of.isoformat(),
                    "horizon_end_utc": end.isoformat(),
                    "path_class": "test",
                    "path_stats": {"terminal_return_bps": outcome},
                }
            ]
        },
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


def _query(as_of: datetime) -> dict[str, object]:
    boundary = _input(as_of=as_of, provenance=PIT_OBSERVED_PROVENANCE)
    return build_analogue_query(
        input_boundary=boundary,
        allowed_provenance=(RETROSPECTIVE_PROVENANCE,),
        max_results=200,
    )


def _named(context: dict[str, object], name: str) -> dict[str, object]:
    windows = context["named_market_windows"]
    assert isinstance(windows, list)
    return next(item for item in windows if item["name"] == name)


def test_epoch_boundary_is_exact_versioned_and_deterministic() -> None:
    before = market_structure_epoch_at(ONE_OZ_24X7_BOUNDARY_UTC - timedelta(seconds=1))
    after = market_structure_epoch_at(ONE_OZ_24X7_BOUNDARY_UTC)
    repeated = market_structure_epoch_at(ONE_OZ_24X7_BOUNDARY_UTC)
    assert before["market_structure_epoch"] == "post_2022_pre_1oz_24x7"
    assert after["market_structure_epoch"] == "post_1oz_24x7"
    assert after == repeated
    assert after["epoch_digest"] == repeated["epoch_digest"]


def test_named_windows_follow_london_and_new_york_dst() -> None:
    winter = build_market_structure_context(as_of=datetime(2026, 1, 15, 10, 30, tzinfo=UTC))
    summer = build_market_structure_context(as_of=datetime(2026, 7, 15, 9, 30, tzinfo=UTC))
    assert _named(winter, "lbma_gold_price_am")["start_utc"].endswith("10:30:00+00:00")
    assert _named(summer, "lbma_gold_price_am")["start_utc"].endswith("09:30:00+00:00")

    ny_winter = build_market_structure_context(
        as_of=datetime(2026, 1, 15, 18, 29, tzinfo=UTC)
    )
    ny_summer = build_market_structure_context(
        as_of=datetime(2026, 7, 15, 17, 29, tzinfo=UTC)
    )
    assert _named(ny_winter, "cme_gold_settlement_observation")["active"] is True
    assert _named(ny_summer, "cme_gold_settlement_observation")["active"] is True


def test_post_boundary_weekend_1oz_state_and_maintenance_are_explicit() -> None:
    active = datetime(2026, 7, 25, 12, tzinfo=UTC)
    maintenance = datetime(2026, 7, 25, 8, tzinfo=UTC)
    assert one_oz_weekend_state_at(active) == "weekend_24x7_active"
    assert one_oz_weekend_state_at(maintenance) == "weekend_maintenance"
    context = build_market_structure_context(as_of=maintenance)
    assert "one_oz_saturday_maintenance" in context["active_named_market_windows"]


def test_future_known_official_schedule_record_cannot_enter_context() -> None:
    as_of = datetime(2026, 11, 26, 15, tzinfo=UTC)
    future_known = {
        "record_version": SCHEDULE_RECORD_VERSION,
        "event_id": "thanksgiving-special-hours",
        "event_kind": "exchange_holiday",
        "known_at_utc": "2026-11-27T00:00:00+00:00",
        "start_utc": "2026-11-26T00:00:00+00:00",
        "end_utc": "2026-11-27T00:00:00+00:00",
        "source": "CME",
    }
    context = build_market_structure_context(
        as_of=as_of,
        official_schedule_records=[future_known],
    )
    assert context["calendar"]["known_official_schedule_records"] == []
    assert context["calendar"]["liquidity_calendar_state"] == (
        "holiday_date_known_hours_unconfirmed"
    )
    assert context["calendar"]["special_hours_state"] == "unknown"


def test_known_official_half_day_and_options_expiry_are_reproducible() -> None:
    as_of = datetime(2026, 12, 24, 17, tzinfo=UTC)
    records = [
        {
            "record_version": SCHEDULE_RECORD_VERSION,
            "event_id": "gold-half-day",
            "event_kind": "exchange_half_day",
            "known_at_utc": "2026-12-10T00:00:00+00:00",
            "start_utc": "2026-12-24T00:00:00+00:00",
            "end_utc": "2026-12-25T00:00:00+00:00",
            "source": "CME",
        },
        {
            "record_version": SCHEDULE_RECORD_VERSION,
            "event_id": "gold-options-expiry",
            "event_kind": "cme_gold_options_expiry",
            "known_at_utc": "2026-12-01T00:00:00+00:00",
            "start_utc": "2026-12-24T16:30:00+00:00",
            "end_utc": "2026-12-24T17:30:00+00:00",
            "source": "CME",
        },
    ]
    context = build_market_structure_context(as_of=as_of, official_schedule_records=records)
    assert context["calendar"]["liquidity_calendar_state"] == "official_exchange_half_day"
    assert context["options_expiry_state"] == "inside_known_official_window"
    assert verify_market_structure_context(context)


def test_historical_case_enrichment_is_outcome_neutral_and_versioned() -> None:
    source = _case(as_of=datetime(2025, 1, 2, 12, tzinfo=UTC), outcome="100")
    enriched = enrich_historical_case_with_market_structure(case=source)
    assert enriched["case_id"] != source["case_id"]
    assert enriched["future_evaluation"] == source["future_evaluation"]
    assert market_structure_epoch_from_case(enriched) == "post_2022_pre_1oz_24x7"
    features = enriched["input_boundary"]["analogue_features"]
    assert features["market_structure_epoch"] == "post_2022_pre_1oz_24x7"


def test_day25_retrieval_hard_gates_epoch_without_pre_day25_relaxation() -> None:
    query_time = datetime(2025, 1, 20, 12, tzinfo=UTC)
    candidate = _case(as_of=datetime(2025, 1, 2, 12, tzinfo=UTC))
    result = retrieve_analogues_v3(query=_query(query_time), candidate_cases=[candidate])
    delegated = result["retrieval"]
    assert verify_retrieval_digest_v3(result)
    assert delegated["returned_match_count"] == 1
    assert result["query_market_structure_epoch"] == "post_2022_pre_1oz_24x7"
    names = {item["name"] for item in delegated["gate_relaxations"]}
    assert "market_structure_epoch_unavailable_pre_day25" not in names
    assert result["day24_thresholds_unchanged"]["min_similarity_score"] == "0.72"
    assert result["day24_thresholds_unchanged"]["min_component_coverage"] == "0.65"


def test_day25_retrieval_excludes_cross_epoch_candidate_before_similarity() -> None:
    query_time = datetime(2026, 8, 20, 12, tzinfo=UTC)
    old_candidate = _case(as_of=datetime(2026, 7, 1, 12, tzinfo=UTC))
    result = retrieve_analogues_v3(query=_query(query_time), candidate_cases=[old_candidate])
    delegated = result["retrieval"]
    assert delegated["returned_match_count"] == 0
    assert delegated["exclusion_counts"]["hard_gate_market_structure_epoch_mismatch"] == 1
    assert delegated["hard_gate_pass_count"] == 0


def test_j5_uses_episode_independent_pairs_and_frozen_conclusion_rule() -> None:
    cases = []
    pre_start = datetime(2025, 1, 1, 0, tzinfo=UTC)
    post_start = datetime(2026, 8, 1, 0, tzinfo=UTC)
    for index in range(5):
        cases.append(_case(as_of=pre_start + timedelta(days=index), outcome=str(index)))
        cases.append(
            _case(as_of=post_start + timedelta(days=index), outcome=str(100 + index))
        )
    result = run_j5_epoch_effect(cases)
    assert verify_j5_digest(result)
    assert result["same_epoch_abs_terminal_return_difference_bps"]["n"] == 20
    assert result["cross_epoch_abs_terminal_return_difference_bps"]["n"] == 25
    assert result["j5_conclusion"] == "SUPPORTS_LOWER_SAME_EPOCH_DISPERSION"
    assert result["new_24x7_epoch_independent_case_count"] == 5
    assert result["new_24x7_epoch_conclusion"] == "INSUFFICIENT"


def test_j5_result_is_deterministic_under_case_reordering() -> None:
    start = datetime(2025, 1, 1, 0, tzinfo=UTC)
    cases = [
        _case(as_of=start, outcome="1"),
        _case(as_of=start + timedelta(hours=1), outcome="999"),
        _case(as_of=start + timedelta(days=1), outcome="2"),
    ]
    left = run_j5_epoch_effect(cases)
    right = run_j5_epoch_effect(list(reversed(cases)))
    assert left["j5_digest"] == right["j5_digest"]
    assert left["matching_strata"][0]["raw_complete_case_count"] == 3
    assert left["matching_strata"][0]["independent_episode_count"] == 2
