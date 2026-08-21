from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256

from aidy.analogue_retrieval import build_analogue_query
from aidy.analogue_retrieval_v2 import (
    ANALOGUE_RETRIEVAL_VERSION_V2,
    EMBARGO_MINUTES,
    SIMILARITY_FEATURE_VERSION_V2,
    retrieve_analogues_v2,
    similarity_manifest_v2,
)
from aidy.evidence_grading_v2 import build_evidence_report_v2
from aidy.feature_engine import FEATURE_DEFINITION_VERSION
from aidy.historical_backfill import RETROSPECTIVE_PROVENANCE
from aidy.historical_cases import (
    CASE_DIGEST_ALGORITHM,
    CASE_INPUT_VERSION,
    CASE_VERSION,
    PIT_OBSERVED_PROVENANCE,
    compute_case_input_digest,
    compute_historical_case_digest,
)
from aidy.regime_classifier import REGIME_DEFINITION_VERSION
from aidy.setup_detector import SETUP_DETECTOR_VERSION, SETUP_TAXONOMY_VERSION


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value: object) -> str:
    return sha256(_canonical_json(value).encode()).hexdigest()


def _features(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
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
    for key, value in overrides.items():
        if key.startswith("regime__"):
            payload["regime"][key.removeprefix("regime__")] = value  # type: ignore[index]
        else:
            payload[key] = value
    return payload


def _input(
    *,
    as_of: datetime,
    features: dict[str, object] | None = None,
    provenance: str,
) -> dict[str, object]:
    feature_values = _features() if features is None else features
    regime_labels = dict(feature_values["regime"])  # type: ignore[arg-type]
    candidate_ids = list(feature_values.get("candidate_setup_ids") or [])
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
            "compound_regime_key": "|".join(f"{key}={value}" for key, value in regime_labels.items()),
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
            "candidate_setup_ids": candidate_ids,
            "candidate_directions": ["long"] if candidate_ids else [],
            "unresolved_setup_ids": [],
        },
        "normalized_trade_spec": None,
        "data_quality": {
            "quality_version": "test_quality_v1",
            "grade": "strong",
            "retrieval_eligible": True,
        },
        "analogue_features": feature_values,
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


def _case(
    *,
    as_of: datetime,
    episode_start: datetime | None = None,
    features: dict[str, object] | None = None,
    outcome_return: str = "10",
) -> dict[str, object]:
    boundary = _input(as_of=as_of, features=features, provenance=RETROSPECTIVE_PROVENANCE)
    case_id = _digest(
        {
            "case_version": CASE_VERSION,
            "symbol": "XAUUSD",
            "as_of_utc": boundary["as_of_utc"],
            "provenance_class": RETROSPECTIVE_PROVENANCE,
            "input_digest": boundary["input_digest"],
        }
    )
    anchor = episode_start or as_of
    end = anchor + timedelta(minutes=240)
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
                    "anchor_time_utc": anchor.isoformat(),
                    "horizon_end_utc": end.isoformat(),
                    "path_class": "up",
                    "path_stats": {"terminal_return_bps": outcome_return},
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


def _query(
    *, as_of: datetime, features: dict[str, object] | None = None, max_results: int = 200
) -> dict[str, object]:
    boundary = _input(as_of=as_of, features=features, provenance=PIT_OBSERVED_PROVENANCE)
    return build_analogue_query(
        input_boundary=boundary,
        allowed_provenance=(RETROSPECTIVE_PROVENANCE,),
        max_results=max_results,
    )


def test_manifest_is_low_dimensional_and_bars_learned_similarity() -> None:
    manifest = similarity_manifest_v2()
    assert manifest["similarity_feature_version"] == SIMILARITY_FEATURE_VERSION_V2
    assert len(manifest["components"]) == 5
    assert manifest["learned_embeddings"] is False
    assert manifest["metric_learning"] is False
    assert manifest["dynamic_time_warping"] is False
    assert "h1_direction" in manifest["deliberately_excluded_redundant_soft_votes"]


def test_hard_regime_mismatch_is_excluded_before_similarity() -> None:
    query_time = datetime(2025, 1, 10, 12, tzinfo=UTC)
    candidate = _case(
        as_of=query_time - timedelta(days=2),
        features=_features(regime__trend_structure="bearish_trend"),
    )
    result = retrieve_analogues_v2(query=_query(as_of=query_time), candidate_cases=[candidate])
    assert result["evidence_state"] == "no_comparable_case"
    assert result["exclusion_counts"]["hard_gate_trend_structure_mismatch"] == 1
    assert result["hard_gate_pass_count"] == 0


def test_pre_day25_epoch_gap_is_explicitly_surfaced_not_hidden() -> None:
    query_time = datetime(2025, 1, 10, 12, tzinfo=UTC)
    result = retrieve_analogues_v2(
        query=_query(as_of=query_time),
        candidate_cases=[_case(as_of=query_time - timedelta(days=2))],
    )
    names = {item["name"] for item in result["gate_relaxations"]}
    assert "market_structure_epoch_unavailable_pre_day25" in names
    assert result["returned_match_count"] == 1


def test_known_market_structure_epoch_mismatch_is_hard_exclusion() -> None:
    query_time = datetime(2025, 1, 10, 12, tzinfo=UTC)
    query = _query(as_of=query_time, features=_features(market_structure_epoch="epoch_a"))
    candidate = _case(
        as_of=query_time - timedelta(days=2),
        features=_features(market_structure_epoch="epoch_b"),
    )
    result = retrieve_analogues_v2(query=query, candidate_cases=[candidate])
    assert result["returned_match_count"] == 0
    assert result["exclusion_counts"]["hard_gate_market_structure_epoch_mismatch"] == 1


def test_query_embargo_purges_recent_completed_outcome_window() -> None:
    query_time = datetime(2025, 1, 10, 12, tzinfo=UTC)
    episode_end = query_time - timedelta(minutes=60)
    candidate = _case(
        as_of=episode_end - timedelta(minutes=240),
        episode_start=episode_end - timedelta(minutes=240),
    )
    result = retrieve_analogues_v2(query=_query(as_of=query_time), candidate_cases=[candidate])
    assert EMBARGO_MINUTES == 240
    assert result["returned_match_count"] == 0
    assert result["exclusion_counts"]["query_embargo_overlap"] == 1


def test_overlapping_outcome_windows_are_deduplicated_to_one_episode() -> None:
    query_time = datetime(2025, 1, 20, 12, tzinfo=UTC)
    start = datetime(2025, 1, 2, 0, tzinfo=UTC)
    first = _case(as_of=start, episode_start=start)
    second = _case(as_of=start + timedelta(hours=1), episode_start=start + timedelta(hours=1))
    result = retrieve_analogues_v2(query=_query(as_of=query_time), candidate_cases=[second, first])
    independence = result["independence"]
    assert independence["pre_dedup_raw_n"] == 2
    assert independence["pre_dedup_kish_effective_n"] == "1.000000"
    assert independence["pre_dedup_effective_n_over_raw_n"] == "0.500000"
    assert independence["distinct_independent_episodes"] == 1
    assert independence["grading_effective_n"] == 1
    assert result["returned_match_count"] == 1
    assert result["matches"][0]["episode_member_count"] == 2


def test_non_overlapping_windows_remain_separate_independent_episodes() -> None:
    query_time = datetime(2025, 1, 20, 12, tzinfo=UTC)
    first_start = datetime(2025, 1, 2, 0, tzinfo=UTC)
    second_start = first_start + timedelta(hours=4)
    result = retrieve_analogues_v2(
        query=_query(as_of=query_time),
        candidate_cases=[
            _case(as_of=first_start, episode_start=first_start),
            _case(as_of=second_start, episode_start=second_start),
        ],
    )
    independence = result["independence"]
    assert independence["pre_dedup_raw_n"] == 2
    assert independence["pre_dedup_kish_effective_n"] == "2.000000"
    assert independence["pre_dedup_effective_n_over_raw_n"] == "1.000000"
    assert independence["distinct_independent_episodes"] == 2
    assert result["returned_match_count"] == 2
    assert len({item["episode_id"] for item in result["matches"]}) == 2


def test_selection_is_deterministic_under_candidate_reordering() -> None:
    query_time = datetime(2025, 1, 20, 12, tzinfo=UTC)
    first_start = datetime(2025, 1, 2, 0, tzinfo=UTC)
    second_start = datetime(2025, 1, 3, 0, tzinfo=UTC)
    first = _case(as_of=first_start, episode_start=first_start)
    second = _case(as_of=second_start, episode_start=second_start)
    query = _query(as_of=query_time)
    left = retrieve_analogues_v2(query=query, candidate_cases=[first, second])
    right = retrieve_analogues_v2(query=query, candidate_cases=[second, first])
    assert left["selection_digest"] == right["selection_digest"]
    assert left["retrieval_digest"] == right["retrieval_digest"]


def test_realized_outcome_value_cannot_change_selection() -> None:
    query_time = datetime(2025, 1, 20, 12, tzinfo=UTC)
    start = datetime(2025, 1, 2, 0, tzinfo=UTC)
    winner = _case(as_of=start, episode_start=start, outcome_return="100")
    loser = _case(as_of=start, episode_start=start, outcome_return="-100")
    query = _query(as_of=query_time)
    left = retrieve_analogues_v2(query=query, candidate_cases=[winner])
    right = retrieve_analogues_v2(query=query, candidate_cases=[loser])
    assert left["selection_digest"] == right["selection_digest"]
    assert left["matches"][0]["similarity"] == right["matches"][0]["similarity"]
    assert left["outcome_values_used_for_selection"] is False
    assert right["outcome_values_used_for_selection"] is False


def test_evidence_grade_uses_effective_independent_n_not_raw_n() -> None:
    query_time = datetime(2025, 1, 20, 12, tzinfo=UTC)
    start = datetime(2025, 1, 2, 0, tzinfo=UTC)
    candidates = [
        _case(
            as_of=start + timedelta(minutes=30 * index),
            episode_start=start + timedelta(minutes=30 * index),
        )
        for index in range(12)
    ]
    retrieval = retrieve_analogues_v2(query=_query(as_of=query_time), candidate_cases=candidates)
    report = build_evidence_report_v2(retrieval=retrieval)
    grade = report["dataset_grade"]
    assert report["pre_dedup_raw_n"] == 12
    assert report["effective_independent_n"] < 10
    assert grade["sample_size_basis"] == "effective_independent_episode_n"
    assert grade["grade"] == "insufficient"
    assert any(blocker.startswith("min_effective_n:") for blocker in grade["next_grade_blockers"])


def test_explicit_no_comparable_case_is_valid_output() -> None:
    query_time = datetime(2025, 1, 10, 12, tzinfo=UTC)
    result = retrieve_analogues_v2(query=_query(as_of=query_time), candidate_cases=[])
    assert result["retrieval_version"] == ANALOGUE_RETRIEVAL_VERSION_V2
    assert result["evidence_state"] == "no_comparable_case"
    assert result["no_comparable_reason"] == "no_eligible_candidate"
    assert result["returned_match_count"] == 0
