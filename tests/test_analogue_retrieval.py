from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256

import pytest

from aidy.analogue_retrieval import (
    ANALOGUE_QUERY_VERSION,
    ANALOGUE_RETRIEVAL_VERSION,
    DEFAULT_MIN_COMPONENT_COVERAGE,
    DEFAULT_MIN_SIMILARITY,
    SIMILARITY_FEATURE_VERSION,
    build_analogue_query,
    candidate_query_parameters,
    candidate_query_sql,
    reconstruct_case_from_storage_row,
    retrieve_analogues,
    score_similarity,
    similarity_manifest,
)
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
    provenance: str = RETROSPECTIVE_PROVENANCE,
    quality_grade: str = "strong",
    retrieval_eligible: bool = True,
) -> dict[str, object]:
    feature_values = _features() if features is None else features
    regime_labels = dict(feature_values["regime"])  # type: ignore[arg-type]
    candidate_ids = list(feature_values.get("candidate_setup_ids") or [])
    detector_state = str(feature_values.get("setup_detector_state") or "none")
    packet: dict[str, object] = {
        "input_version": CASE_INPUT_VERSION,
        "replay_version": "test_replay_v1" if provenance == RETROSPECTIVE_PROVENANCE else None,
        "symbol": "XAUUSD",
        "as_of_utc": as_of.astimezone(UTC).isoformat(),
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
            "detector_state": detector_state,
            "candidate_setup_ids": candidate_ids,
            "candidate_directions": ["long"] if candidate_ids else [],
            "unresolved_setup_ids": [],
        },
        "normalized_trade_spec": None,
        "data_quality": {
            "quality_version": "test_quality_v1",
            "grade": quality_grade,
            "retrieval_eligible": retrieval_eligible,
        },
        "analogue_features": feature_values,
        "evaluation_anchor": {
            "anchor_time_utc": as_of.astimezone(UTC).isoformat(),
            "anchor_price": "2000",
            "forward_start_utc": as_of.astimezone(UTC).isoformat(),
            "alignment_rule": "test",
        },
        "provenance": {"source_provenance_class": provenance},
    }
    packet["input_digest"] = compute_case_input_digest(packet)
    return packet


def _case(
    *,
    as_of: datetime,
    features: dict[str, object] | None = None,
    provenance: str = RETROSPECTIVE_PROVENANCE,
    future_available_after: datetime | None = None,
    outcome_marker: str = "baseline",
    quality_grade: str = "strong",
    retrieval_eligible: bool = True,
) -> dict[str, object]:
    boundary = _input(
        as_of=as_of,
        features=features,
        provenance=provenance,
        quality_grade=quality_grade,
        retrieval_eligible=retrieval_eligible,
    )
    case_id = _digest(
        {
            "case_version": CASE_VERSION,
            "symbol": "XAUUSD",
            "as_of_utc": boundary["as_of_utc"],
            "provenance_class": provenance,
            "input_digest": boundary["input_digest"],
        }
    )
    available = future_available_after or (as_of + timedelta(hours=4))
    future = {
        "evaluation_only": True,
        "future_derived": True,
        "pit_eligible": False,
        "decision_input_allowed": False,
        "analogue_match_allowed": False,
        "available_after_utc": available.astimezone(UTC).isoformat(),
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
        "provenance_class": provenance,
        "decision_input_allowed": False,
        "analogue_query_must_use_input_boundary_only": True,
        "input_boundary": boundary,
        "future_evaluation": future,
    }
    case["case_digest"] = compute_historical_case_digest(case)
    return case


def _query(
    *,
    as_of: datetime,
    features: dict[str, object] | None = None,
    allowed_provenance: tuple[str, ...] = (RETROSPECTIVE_PROVENANCE,),
    source_case_id: str | None = None,
    quality_grade: str = "strong",
    retrieval_eligible: bool = True,
    min_similarity: object = DEFAULT_MIN_SIMILARITY,
    min_coverage: object = DEFAULT_MIN_COMPONENT_COVERAGE,
) -> dict[str, object]:
    boundary = _input(
        as_of=as_of,
        features=features,
        provenance=PIT_OBSERVED_PROVENANCE,
        quality_grade=quality_grade,
        retrieval_eligible=retrieval_eligible,
    )
    return build_analogue_query(
        input_boundary=boundary,
        allowed_provenance=allowed_provenance,
        source_case_id=source_case_id,
        min_similarity_score=min_similarity,
        min_component_coverage=min_coverage,
    )


def test_manifest_is_versioned_and_future_free() -> None:
    manifest = similarity_manifest()
    assert manifest["similarity_feature_version"] == SIMILARITY_FEATURE_VERSION
    assert manifest["future_outcomes_used_for_similarity"] is False
    assert manifest["manifest_digest"]
    assert len(manifest["components"]) == 15


def test_query_is_deterministic_and_contains_no_outcomes() -> None:
    as_of = datetime(2025, 1, 10, 12, tzinfo=UTC)
    left = _query(as_of=as_of)
    right = _query(as_of=as_of)
    assert left == right
    assert left["query_version"] == ANALOGUE_QUERY_VERSION
    assert left["outcomes_in_query"] is False
    assert "future_evaluation" not in _canonical_json(left)


def test_query_rejects_future_injection_even_when_input_is_rehashed() -> None:
    boundary = _input(as_of=datetime(2025, 1, 10, 12, tzinfo=UTC))
    boundary["future_evaluation"] = {"outcome": "winner"}
    boundary["input_digest"] = compute_case_input_digest(boundary)
    with pytest.raises(ValueError, match="Future/outcome"):
        build_analogue_query(input_boundary=boundary)


def test_exact_known_neighbour_scores_one_with_full_component_explanation() -> None:
    features = _features()
    score = score_similarity(query_features=features, candidate_features=features)
    assert score["similarity_score"] == "1.000000"
    assert score["distance_score"] == "0.000000"
    assert score["component_coverage"] == "1.000000"
    assert all(item["state"] == "compared" for item in score["components"])


def test_ranking_is_reproducible_and_independent_of_candidate_order() -> None:
    query_time = datetime(2025, 1, 10, 12, tzinfo=UTC)
    query = _query(as_of=query_time)
    exact = _case(as_of=query_time - timedelta(days=2))
    near = _case(
        as_of=query_time - timedelta(days=3),
        features=_features(h1_atr_14_bps="39", m15_range_position_20="0.66"),
    )
    a = retrieve_analogues(query=query, candidate_cases=[near, exact])
    b = retrieve_analogues(query=query, candidate_cases=[exact, near])
    assert a["selection_digest"] == b["selection_digest"]
    assert [item["case_id"] for item in a["matches"]] == [
        item["case_id"] for item in b["matches"]
    ]
    assert a["matches"][0]["case_id"] == exact["case_id"]


def test_future_outcome_contents_cannot_change_selection_or_similarity() -> None:
    query_time = datetime(2025, 1, 10, 12, tzinfo=UTC)
    query = _query(as_of=query_time)
    base_time = query_time - timedelta(days=2)
    winner = _case(as_of=base_time, outcome_marker="winner")
    loser = _case(as_of=base_time, outcome_marker="loser")
    left = retrieve_analogues(query=query, candidate_cases=[winner])
    right = retrieve_analogues(query=query, candidate_cases=[loser])
    assert left["selection_digest"] == right["selection_digest"]
    assert left["matches"][0]["similarity"] == right["matches"][0]["similarity"]
    assert left["retrieval_digest"] != right["retrieval_digest"]
    assert left["outcomes_used_for_selection"] is False


def test_candidate_at_or_after_query_time_is_excluded() -> None:
    query_time = datetime(2025, 1, 10, 12, tzinfo=UTC)
    query = _query(as_of=query_time)
    candidate = _case(
        as_of=query_time,
        future_available_after=query_time,
    )
    result = retrieve_analogues(query=query, candidate_cases=[candidate])
    assert result["matches"] == []
    assert result["exclusion_counts"]["candidate_not_before_query"] == 1


def test_outcome_not_known_by_query_time_is_excluded() -> None:
    query_time = datetime(2025, 1, 10, 12, tzinfo=UTC)
    query = _query(as_of=query_time)
    candidate = _case(
        as_of=query_time - timedelta(days=1),
        future_available_after=query_time + timedelta(minutes=1),
    )
    result = retrieve_analogues(query=query, candidate_cases=[candidate])
    assert result["matches"] == []
    assert result["exclusion_counts"]["outcome_not_yet_available"] == 1


def test_provenance_must_be_explicitly_allowed() -> None:
    query_time = datetime(2025, 1, 10, 12, tzinfo=UTC)
    pit_case = _case(
        as_of=query_time - timedelta(days=2),
        provenance=PIT_OBSERVED_PROVENANCE,
    )
    default_query = _query(as_of=query_time)
    excluded = retrieve_analogues(query=default_query, candidate_cases=[pit_case])
    assert excluded["exclusion_counts"]["provenance_not_allowed"] == 1

    allowed_query = _query(
        as_of=query_time,
        allowed_provenance=(RETROSPECTIVE_PROVENANCE, PIT_OBSERVED_PROVENANCE),
    )
    included = retrieve_analogues(query=allowed_query, candidate_cases=[pit_case])
    assert included["returned_match_count"] == 1
    assert included["matches"][0]["provenance_class"] == PIT_OBSERVED_PROVENANCE


def test_low_component_coverage_returns_no_evidence() -> None:
    query_time = datetime(2025, 1, 10, 12, tzinfo=UTC)
    sparse = _features(
        m15_direction=None,
        h1_direction=None,
        h4_direction=None,
        h1_atr_14_bps=None,
        m15_realized_vol_20_bps=None,
        m15_range_position_20=None,
        m15_close_location=None,
        session_range_position=None,
        setup_detector_state="indeterminate",
        candidate_setup_ids=[],
        regime__volatility_band="unknown",
        regime__session="unknown",
        regime__quote_spread_condition="unknown",
        regime__event_timing="unknown",
    )
    query = _query(as_of=query_time, features=sparse)
    candidate = _case(as_of=query_time - timedelta(days=2), features=sparse)
    result = retrieve_analogues(query=query, candidate_cases=[candidate])
    assert result["evidence_state"] == "no_sufficient_similarity"
    assert result["exclusion_counts"]["coverage_below_threshold"] == 1


def test_weak_similarity_returns_no_evidence_instead_of_fake_match() -> None:
    query_time = datetime(2025, 1, 10, 12, tzinfo=UTC)
    opposite = _features(
        regime__trend_structure="bearish_trend",
        regime__volatility_band="high",
        regime__session="asia",
        regime__event_timing="inside_high_impact_window",
        m15_direction="bearish",
        h1_direction="bearish",
        h4_direction="bearish",
        h1_atr_14_bps="120",
        m15_realized_vol_20_bps="100",
        m15_range_position_20="0.05",
        m15_close_location="0.05",
        session_range_position="0.05",
        setup_detector_state="single",
        candidate_setup_ids=["trend_momentum_short"],
    )
    query = _query(as_of=query_time)
    candidate = _case(as_of=query_time - timedelta(days=2), features=opposite)
    result = retrieve_analogues(query=query, candidate_cases=[candidate])
    assert result["evidence_state"] == "no_sufficient_similarity"
    assert result["matches"] == []
    assert result["exclusion_counts"]["similarity_below_threshold"] == 1


def test_query_with_insufficient_data_quality_is_barred() -> None:
    query_time = datetime(2025, 1, 10, 12, tzinfo=UTC)
    query = _query(
        as_of=query_time,
        quality_grade="insufficient",
        retrieval_eligible=False,
    )
    candidate = _case(as_of=query_time - timedelta(days=2))
    result = retrieve_analogues(query=query, candidate_cases=[candidate])
    assert result["evidence_state"] == "query_insufficient_quality"
    assert result["matches"] == []


def test_candidate_with_insufficient_quality_is_excluded() -> None:
    query_time = datetime(2025, 1, 10, 12, tzinfo=UTC)
    query = _query(as_of=query_time)
    candidate = _case(
        as_of=query_time - timedelta(days=2),
        quality_grade="insufficient",
        retrieval_eligible=False,
    )
    result = retrieve_analogues(query=query, candidate_cases=[candidate])
    assert result["exclusion_counts"]["candidate_quality_insufficient"] == 1


def test_source_case_id_is_never_returned_as_its_own_neighbour() -> None:
    query_time = datetime(2025, 1, 10, 12, tzinfo=UTC)
    candidate = _case(as_of=query_time - timedelta(days=2))
    query = _query(as_of=query_time, source_case_id=str(candidate["case_id"]))
    result = retrieve_analogues(query=query, candidate_cases=[candidate])
    assert result["matches"] == []
    assert result["exclusion_counts"]["source_case_excluded"] == 1


def test_reconstruct_storage_row_accepts_json_strings_and_preserves_digest() -> None:
    candidate = _case(as_of=datetime(2025, 1, 8, 12, tzinfo=UTC))
    row = {
        "case_digest": candidate["case_digest"],
        "case_version": candidate["case_version"],
        "case_id": candidate["case_id"],
        "symbol": candidate["symbol"],
        "as_of_utc": datetime.fromisoformat(str(candidate["as_of_utc"])),
        "provenance_class": candidate["provenance_class"],
        "input_boundary": json.dumps(candidate["input_boundary"]),
        "future_evaluation": json.dumps(candidate["future_evaluation"]),
    }
    rebuilt = reconstruct_case_from_storage_row(row)
    assert rebuilt["case_digest"] == candidate["case_digest"]
    assert rebuilt["case_id"] == candidate["case_id"]


def test_tampered_candidate_case_digest_is_rejected() -> None:
    query_time = datetime(2025, 1, 10, 12, tzinfo=UTC)
    query = _query(as_of=query_time)
    candidate = _case(as_of=query_time - timedelta(days=2))
    candidate["future_evaluation"]["move_bundle"] = {"outcome_marker": "tampered"}  # type: ignore[index]
    with pytest.raises(ValueError, match="digest"):
        retrieve_analogues(query=query, candidate_cases=[candidate])


def test_max_results_caps_output_without_changing_sufficient_sample_count() -> None:
    query_time = datetime(2025, 1, 10, 12, tzinfo=UTC)
    boundary = _input(as_of=query_time, provenance=PIT_OBSERVED_PROVENANCE)
    query = build_analogue_query(input_boundary=boundary, max_results=2)
    candidates = [
        _case(as_of=query_time - timedelta(days=days))
        for days in (2, 3, 4, 5)
    ]
    result = retrieve_analogues(query=query, candidate_cases=candidates)
    assert result["sufficient_match_count"] == 4
    assert result["returned_match_count"] == 2


def test_bigquery_sql_has_hard_asof_outcome_provenance_and_version_guards() -> None:
    sql = candidate_query_sql(project="aidy-signals", dataset="aidy_analytics_test")
    assert "as_of_utc < @query_as_of" in sql
    assert "future_available_after_utc <= @query_as_of" in sql
    assert "provenance_class IN UNNEST(@allowed_provenance)" in sql
    assert "feature_definition_version = @feature_definition_version" in sql
    assert "setup_detector_version = @setup_detector_version" in sql
    assert "future_evaluation" in sql


def test_bigquery_parameters_are_query_bound_and_reproducible() -> None:
    query = _query(as_of=datetime(2025, 1, 10, 12, tzinfo=UTC))
    left = candidate_query_parameters(query, candidate_limit=250)
    right = candidate_query_parameters(query, candidate_limit=250)
    assert left == right
    assert left["query_as_of"] == query["as_of_utc"]
    assert left["candidate_limit"] == 250


def test_result_never_claims_probabilities_and_marks_outcome_boundary() -> None:
    query_time = datetime(2025, 1, 10, 12, tzinfo=UTC)
    query = _query(as_of=query_time)
    candidate = _case(as_of=query_time - timedelta(days=2))
    result = retrieve_analogues(query=query, candidate_cases=[candidate])
    assert result["retrieval_version"] == ANALOGUE_RETRIEVAL_VERSION
    assert result["outcomes_used_for_selection"] is False
    assert result["probability_claims_included"] is False
    assert result["matches"][0]["outcome_used_for_similarity"] is False
    assert result["matches"][0]["outcome_available_by_query_time"] is True
