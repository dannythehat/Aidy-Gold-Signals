from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256

import pytest

from aidy.analogue_retrieval import (
    ANALOGUE_RETRIEVAL_VERSION,
    SIMILARITY_FEATURE_VERSION,
)
from aidy.evidence_grading import (
    EVIDENCE_GRADE_VERSION,
    EVIDENCE_REPORT_VERSION,
    EVIDENCE_STATISTIC_VERSION,
    GRADE_ESTABLISHED,
    GRADE_EXPLORATORY,
    GRADE_INSUFFICIENT,
    GRADE_MODERATE,
    build_evidence_report,
    evidence_grade_manifest,
    grade_evidence,
    verify_evidence_report_digest,
)

QUERY_TIME = datetime(2026, 1, 1, 12, tzinfo=UTC)


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value: object) -> str:
    return sha256(_canonical_json(value).encode()).hexdigest()


def _score_payload(similarity: float, coverage: float) -> dict[str, object]:
    payload: dict[str, object] = {
        "similarity_feature_version": SIMILARITY_FEATURE_VERSION,
        "similarity_score": f"{similarity:.6f}",
        "distance_score": f"{1 - similarity:.6f}",
        "component_coverage": f"{coverage:.6f}",
        "covered_weight": "10.0",
        "total_weight": "10.0",
        "components": [],
        "future_outcomes_used": False,
    }
    payload["score_digest"] = _digest(payload)
    return payload


def _future(
    *,
    move_complete: bool = True,
    path_class: str = "directional_up",
    trade: bool = False,
    trade_state: str = "target_only",
) -> dict[str, object]:
    labels = []
    for horizon in (15, 60, 240):
        complete = move_complete or horizon != 240
        labels.append(
            {
                "horizon_minutes": horizon,
                "coverage_state": "complete" if complete else "incomplete",
                "path_class": path_class if complete else "unknown",
            }
        )
    trade_bundle = None
    if trade:
        trade_bundle = {
            "outcomes": [
                {
                    "horizon_minutes": horizon,
                    "coverage_state": "complete",
                    "outcome_state": trade_state,
                }
                for horizon in (15, 60, 240)
            ]
        }
    return {
        "evaluation_only": True,
        "future_derived": True,
        "pit_eligible": False,
        "decision_input_allowed": False,
        "analogue_match_allowed": False,
        "available_after_utc": QUERY_TIME.isoformat(),
        "move_bundle": {"labels": labels},
        "trade_outcome_bundle": trade_bundle,
        "no_trade_counterfactual": None,
        "causal_claims_included": False,
    }


def _match(
    index: int,
    *,
    age_days: float,
    similarity: float = 0.90,
    coverage: float = 0.90,
    quality: str = "strong",
    move_complete: bool = True,
    path_class: str = "directional_up",
    trade: bool = False,
    trade_state: str = "target_only",
) -> dict[str, object]:
    stamp = QUERY_TIME - timedelta(days=age_days)
    return {
        "rank": index + 1,
        "case_id": f"{index + 1:064x}",
        "as_of_utc": stamp.isoformat(),
        "provenance_class": "retrospective_history",
        "input_digest": "a" * 64,
        "data_quality_grade": quality,
        "regime": {},
        "setup_detector_state": "single",
        "candidate_setup_ids": ["trend_momentum_long"],
        "similarity": _score_payload(similarity, coverage),
        "future_evaluation": _future(
            move_complete=move_complete,
            path_class=path_class,
            trade=trade,
            trade_state=trade_state,
        ),
        "outcome_available_by_query_time": True,
        "outcome_used_for_similarity": False,
    }


def _matches(
    n: int,
    *,
    start_age: float = 1,
    step_days: float = 1,
    **kwargs: object,
) -> list[dict[str, object]]:
    return [
        _match(index, age_days=start_age + index * step_days, **kwargs)
        for index in range(n)
    ]


def _selection_digest(query_id: str, matches: list[dict[str, object]]) -> str:
    selection = [
        {
            "rank": item["rank"],
            "case_id": item["case_id"],
            "similarity_score": item["similarity"]["similarity_score"],
            "component_coverage": item["similarity"]["component_coverage"],
        }
        for item in matches
    ]
    return _digest({"query_id": query_id, "selection": selection})


def _retrieval(matches: list[dict[str, object]]) -> dict[str, object]:
    normalized = []
    for rank, item in enumerate(matches, start=1):
        copy = dict(item)
        copy["rank"] = rank
        normalized.append(copy)
    query_id = "q" * 64
    payload: dict[str, object] = {
        "retrieval_version": ANALOGUE_RETRIEVAL_VERSION,
        "similarity_feature_version": SIMILARITY_FEATURE_VERSION,
        "query_id": query_id,
        "query_as_of_utc": QUERY_TIME.isoformat(),
        "evidence_state": "matches_found" if normalized else "no_sufficient_similarity",
        "candidate_count": len(normalized),
        "eligible_candidate_count": len(normalized),
        "sufficient_match_count": len(normalized),
        "returned_match_count": len(normalized),
        "exclusion_counts": {},
        "matches": normalized,
        "selection_digest": _selection_digest(query_id, normalized),
        "outcomes_used_for_selection": False,
        "probability_claims_included": False,
    }
    payload["retrieval_digest"] = _digest(payload)
    return payload


def test_manifest_is_versioned_conservative_and_not_outcome_optimized() -> None:
    manifest = evidence_grade_manifest()
    assert manifest["evidence_grade_version"] == EVIDENCE_GRADE_VERSION
    assert manifest["evidence_report_version"] == EVIDENCE_REPORT_VERSION
    assert manifest["evidence_statistic_version"] == EVIDENCE_STATISTIC_VERSION
    assert manifest["threshold_basis"] == "fixed_v1_conservative_not_outcome_optimized"
    assert manifest["outcome_values_used_for_dataset_grade"] is False
    assert manifest["manifest_digest"]


def test_one_perfect_match_is_still_insufficient() -> None:
    result = grade_evidence(
        [_match(0, age_days=1, similarity=1.0, coverage=1.0)],
        query_as_of=QUERY_TIME,
    )
    assert result["grade"] == GRADE_INSUFFICIENT
    assert result["n"] == 1
    assert result["probability_like_wording_allowed"] is False
    assert result["decision_weight_allowed"] is False


def test_nine_matches_are_insufficient_even_when_perfect() -> None:
    result = grade_evidence(
        _matches(9, similarity=1.0, coverage=1.0),
        query_as_of=QUERY_TIME,
    )
    assert result["grade"] == GRADE_INSUFFICIENT


def test_ten_diverse_strong_matches_can_be_exploratory() -> None:
    result = grade_evidence(_matches(10), query_as_of=QUERY_TIME)
    assert result["grade"] == GRADE_EXPLORATORY
    assert result["probability_like_wording_allowed"] is False


def test_thirty_broad_high_quality_matches_can_be_moderate() -> None:
    result = grade_evidence(
        _matches(30, step_days=2, similarity=0.86, coverage=0.86),
        query_as_of=QUERY_TIME,
    )
    assert result["grade"] == GRADE_MODERATE
    assert result["probability_like_wording_allowed"] is True
    assert result["decision_weight_allowed"] is False


def test_one_hundred_broad_high_quality_matches_can_be_established() -> None:
    result = grade_evidence(
        _matches(100, step_days=3, similarity=0.90, coverage=0.90),
        query_as_of=QUERY_TIME,
    )
    assert result["grade"] == GRADE_ESTABLISHED
    assert result["decision_weight_allowed"] is True


def test_large_but_single_day_sample_is_not_upgraded_by_n_alone() -> None:
    result = grade_evidence(
        [_match(index, age_days=10) for index in range(100)],
        query_as_of=QUERY_TIME,
    )
    assert result["grade"] == GRADE_INSUFFICIENT
    assert any("temporal_span_days" in code for code in result["next_grade_blockers"])


def test_stale_moderate_sized_sample_is_capped_at_exploratory() -> None:
    result = grade_evidence(
        _matches(30, start_age=300, step_days=2, similarity=0.86, coverage=0.86),
        query_as_of=QUERY_TIME,
    )
    assert result["grade"] == GRADE_EXPLORATORY


def test_weak_similarity_blocks_moderate_grade() -> None:
    result = grade_evidence(
        _matches(30, step_days=2, similarity=0.73, coverage=0.90),
        query_as_of=QUERY_TIME,
    )
    assert result["grade"] == GRADE_EXPLORATORY


def test_weak_component_coverage_blocks_moderate_grade() -> None:
    result = grade_evidence(
        _matches(30, step_days=2, similarity=0.86, coverage=0.70),
        query_as_of=QUERY_TIME,
    )
    assert result["grade"] == GRADE_EXPLORATORY


def test_limited_input_quality_prevents_evidence_upgrade() -> None:
    result = grade_evidence(
        _matches(
            30,
            step_days=2,
            similarity=0.86,
            coverage=0.86,
            quality="limited",
        ),
        query_as_of=QUERY_TIME,
    )
    assert result["grade"] == GRADE_INSUFFICIENT


def test_incomplete_240m_outcomes_prevent_evidence_upgrade() -> None:
    result = grade_evidence(
        _matches(
            30,
            step_days=2,
            similarity=0.86,
            coverage=0.86,
            move_complete=False,
        ),
        query_as_of=QUERY_TIME,
    )
    assert result["grade"] == GRADE_INSUFFICIENT


def test_dataset_grade_does_not_use_outcome_categories() -> None:
    left = grade_evidence(
        _matches(30, step_days=2, path_class="directional_up"),
        query_as_of=QUERY_TIME,
    )
    right = grade_evidence(
        _matches(30, step_days=2, path_class="spike_down_reverted"),
        query_as_of=QUERY_TIME,
    )
    assert left == right
    assert left["outcome_values_used_for_grade"] is False


def test_grading_is_deterministic_under_match_reordering() -> None:
    matches = _matches(30, step_days=2)
    left = grade_evidence(matches, query_as_of=QUERY_TIME)
    right = grade_evidence(list(reversed(matches)), query_as_of=QUERY_TIME)
    assert left == right


def test_report_preserves_day17_selection_identity() -> None:
    retrieval = _retrieval(_matches(10))
    report = build_evidence_report(retrieval=retrieval)
    assert report["source_selection_digest"] == retrieval["selection_digest"]
    assert report["selection_mutated_by_grading"] is False
    assert report["grading_applied_after_analogue_selection"] is True


def test_every_report_statistic_carries_n_and_grade() -> None:
    report = build_evidence_report(retrieval=_retrieval(_matches(10)))
    assert len(report["statistics"]) == 6
    for statistic in report["statistics"]:
        assert statistic["n"] >= 0
        assert statistic["grade"] in {
            GRADE_INSUFFICIENT,
            GRADE_EXPLORATORY,
            GRADE_MODERATE,
            GRADE_ESTABLISHED,
        }
        assert statistic["statistic_digest"]


def test_low_n_trade_slice_stays_insufficient_inside_moderate_dataset() -> None:
    matches = _matches(30, step_days=2, similarity=0.86, coverage=0.86)
    for item in matches[:5]:
        item["future_evaluation"] = _future(trade=True)
    retrieval = _retrieval(matches)
    report = build_evidence_report(retrieval=retrieval)
    assert report["dataset_grade"]["grade"] == GRADE_MODERATE
    trade_240 = next(
        item for item in report["statistics"] if item["name"] == "trade_outcome_state_240m"
    )
    assert trade_240["n"] == 5
    assert trade_240["grade"] == GRADE_INSUFFICIENT
    assert trade_240["rates"] is None
    assert trade_240["probability_like_wording_allowed"] is False


def test_exploratory_statistic_does_not_emit_rates() -> None:
    report = build_evidence_report(retrieval=_retrieval(_matches(10)))
    move_240 = next(
        item for item in report["statistics"] if item["name"] == "move_path_class_240m"
    )
    assert move_240["grade"] == GRADE_EXPLORATORY
    assert move_240["rates"] is None


def test_moderate_statistic_may_emit_descriptive_rates_but_not_decision_weight() -> None:
    report = build_evidence_report(
        retrieval=_retrieval(
            _matches(30, step_days=2, similarity=0.86, coverage=0.86)
        )
    )
    move_240 = next(
        item for item in report["statistics"] if item["name"] == "move_path_class_240m"
    )
    assert move_240["grade"] == GRADE_MODERATE
    assert move_240["rates"] == {"directional_up": "1.000000"}
    assert move_240["decision_weight_allowed"] is False


def test_established_statistic_can_be_weight_eligible_but_never_standalone_decision() -> None:
    report = build_evidence_report(
        retrieval=_retrieval(
            _matches(100, step_days=3, similarity=0.90, coverage=0.90)
        )
    )
    move_240 = next(
        item for item in report["statistics"] if item["name"] == "move_path_class_240m"
    )
    assert move_240["grade"] == GRADE_ESTABLISHED
    assert move_240["decision_weight_allowed"] is True
    assert move_240["standalone_trade_decision_allowed"] is False
    assert move_240["causal_claims_allowed"] is False


def test_empty_retrieval_returns_insufficient_without_fake_statistics() -> None:
    report = build_evidence_report(retrieval=_retrieval([]))
    assert report["dataset_grade"]["grade"] == GRADE_INSUFFICIENT
    assert report["retrieved_match_count"] == 0
    assert all(item["n"] == 0 for item in report["statistics"])
    assert all(item["rates"] is None for item in report["statistics"])


def test_retrieval_tamper_is_rejected_before_grading() -> None:
    retrieval = _retrieval(_matches(10))
    retrieval["returned_match_count"] = 999
    with pytest.raises(ValueError, match="retrieval digest"):
        build_evidence_report(retrieval=retrieval)


def test_rehashed_retrieval_with_probability_claims_is_still_rejected() -> None:
    retrieval = _retrieval(_matches(10))
    retrieval["probability_claims_included"] = True
    retrieval["retrieval_digest"] = _digest(
        {key: value for key, value in retrieval.items() if key != "retrieval_digest"}
    )
    with pytest.raises(ValueError, match="probability claims"):
        build_evidence_report(retrieval=retrieval)


def test_rehashed_match_whose_outcome_affected_similarity_is_rejected() -> None:
    retrieval = _retrieval(_matches(10))
    retrieval["matches"][0]["outcome_used_for_similarity"] = True
    retrieval["selection_digest"] = _selection_digest(
        str(retrieval["query_id"]), retrieval["matches"]
    )
    retrieval["retrieval_digest"] = _digest(
        {key: value for key, value in retrieval.items() if key != "retrieval_digest"}
    )
    with pytest.raises(ValueError, match="outcome affected similarity"):
        build_evidence_report(retrieval=retrieval)


def test_report_digest_detects_tampering() -> None:
    report = build_evidence_report(retrieval=_retrieval(_matches(10)))
    assert verify_evidence_report_digest(report)
    report["decision_weight_allowed"] = True
    assert not verify_evidence_report_digest(report)
