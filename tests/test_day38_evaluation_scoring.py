from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta

import pytest

from aidy.evaluation_scoring import (
    REQUIRED_SCORE_DIMENSIONS,
    SUBJECTIVE_METHOD,
    EvaluationIntegrityError,
    build_human_calibration_record,
    build_j16_grade_validity_report,
    build_j21_setup_differentiation_report,
    build_judgement_score,
    build_risk_coverage_report,
    evaluation_manifest,
    verify_human_calibration_record,
)
from aidy.setup_detector import SETUP_DEFINITIONS, SETUP_TAXONOMY_VERSION

BASE = datetime(2025, 1, 1, tzinfo=UTC)
DIRECTIONS = {str(item["setup_id"]): str(item["direction"]) for item in SETUP_DEFINITIONS}


def _components(*, grounding: bool = True, safety: bool = True) -> dict[str, dict[str, object]]:
    result = {}
    for dimension in REQUIRED_SCORE_DIMENSIONS:
        result[dimension] = {
            "score": "1.0",
            "method": "deterministic",
            "passed": True,
            "evidence_digest": dimension,
        }
    result["grounding"]["passed"] = grounding
    result["grounding"]["score"] = "1.0" if grounding else "0.0"
    result["schema_safety"]["passed"] = safety
    result["schema_safety"]["score"] = "1.0" if safety else "0.0"
    return result


def _j16_rows(*, reverse: bool = False, n: int = 12) -> list[dict[str, object]]:
    rows = []
    for grade_index, grade in enumerate(("exploratory", "established_dataset")):
        for index in range(n):
            base_dispersion = 10 if grade == "established_dataset" else 30
            if reverse:
                base_dispersion = 30 if grade == "established_dataset" else 10
            rows.append(
                {
                    "query_id": f"{grade}-{index:02d}",
                    "as_of_utc": (
                        BASE + timedelta(days=index * 5, hours=grade_index)
                    ).isoformat(),
                    "dataset_grade": grade,
                    "effective_n": 40 if grade == "established_dataset" else 12,
                    "terminal_return_stddev_bps": str(base_dispersion + index / 100),
                    "terminal_return_iqr_bps": str(base_dispersion / 2),
                    "terminal_return_mad_bps": str(base_dispersion / 4),
                }
            )
    return rows


def _j21_rows(*, null: bool = False, n_each: int = 12) -> list[dict[str, object]]:
    setup_ids = ("trend_pullback_long", "trend_pullback_short")
    rows = []
    index = 0
    for _occurrence in range(n_each):
        for setup_id in setup_ids:
            direction = DIRECTIONS[setup_id]
            if null:
                directional = 5
            else:
                directional = 10 if setup_id.endswith("_long") else 2
            terminal_return = directional if direction == "long" else -directional
            rows.append(
                {
                    "case_id": f"case-{index:03d}",
                    "as_of_utc": (BASE + timedelta(hours=index * 5)).isoformat(),
                    "setup_id": setup_id,
                    "taxonomy_version": SETUP_TAXONOMY_VERSION,
                    "direction": direction,
                    "regime": "trend",
                    "session": "london",
                    "terminal_return_bps": str(terminal_return),
                }
            )
            index += 1
    return rows


def test_manifest_freezes_day38_boundaries() -> None:
    manifest = evaluation_manifest()
    assert manifest["safety_and_grounding_non_compensatory"] is True
    assert manifest["raw_n_and_effective_n_required"] is True
    assert manifest["subjective_grader_requires_human_calibration"] is True
    assert manifest["day23_j16_authoritative"] is False
    assert manifest["post_hardening_j16_authoritative"] is True
    assert manifest["risk_coverage_episode_deduplicated"] is True
    assert manifest["risk_coverage_evaluation_tuning_allowed"] is False
    assert manifest["j21_setup_variant_count"] == 20
    assert manifest["j21_null_accepted"] is True
    assert manifest["taxonomy_expansion_from_j21_allowed"] is False
    assert manifest["predictive_edge_claimed"] is False
    assert manifest["broker_side_effects_allowed"] is False
    assert manifest["super_signals_side_effects_allowed"] is False


def test_judgement_score_is_deterministic_and_reports_raw_and_effective_n() -> None:
    first = build_judgement_score(
        decision_id="d1",
        episode_id="e1",
        components=_components(),
        raw_n=7,
        effective_n=3,
    )
    second = build_judgement_score(
        decision_id="d1",
        episode_id="e1",
        components=copy.deepcopy(_components()),
        raw_n=7,
        effective_n=3,
    )
    assert first == second
    assert first["raw_n"] == 7
    assert first["effective_n"] == 3
    assert first["quality_claim_allowed"] is True


@pytest.mark.parametrize(
    ("grounding", "safety"), [(False, True), (True, False), (False, False)]
)
def test_safety_or_grounding_failure_cannot_be_offset_by_other_perfect_scores(
    grounding: bool, safety: bool
) -> None:
    result = build_judgement_score(
        decision_id="d1",
        episode_id="e1",
        components=_components(grounding=grounding, safety=safety),
        raw_n=1,
        effective_n=1,
    )
    assert result["mean_dimension_score"] != "0.000000"
    assert result["non_compensatory_gate_pass"] is False
    assert result["quality_claim_allowed"] is False
    assert result["good_outcome_can_offset_grounding_failure"] is False
    assert result["good_outcome_can_offset_safety_failure"] is False


def test_score_rejects_missing_or_extra_dimension() -> None:
    components = _components()
    components.pop("factual_accuracy")
    with pytest.raises(EvaluationIntegrityError, match="dimensions must be exact"):
        build_judgement_score(
            decision_id="d1",
            episode_id="e1",
            components=components,
            raw_n=1,
            effective_n=1,
        )


def test_effective_n_cannot_exceed_raw_n() -> None:
    with pytest.raises(EvaluationIntegrityError, match="no greater than raw_n"):
        build_judgement_score(
            decision_id="d1",
            episode_id="e1",
            components=_components(),
            raw_n=2,
            effective_n=3,
        )


def test_subjective_component_requires_accepted_human_calibration() -> None:
    components = _components()
    components["factual_accuracy"]["method"] = SUBJECTIVE_METHOD
    with pytest.raises(EvaluationIntegrityError, match="accepted human calibration"):
        build_judgement_score(
            decision_id="d1",
            episode_id="e1",
            components=components,
            raw_n=1,
            effective_n=1,
        )


def test_subjective_component_accepts_digest_protected_human_calibration() -> None:
    components = _components()
    components["factual_accuracy"]["method"] = SUBJECTIVE_METHOD
    calibration = build_human_calibration_record(
        dimension="factual_accuracy",
        calibration_identity="day38-human-sample-v1",
        human_reviewed_n=25,
        reviewer_protocol_digest="r" * 64,
        agreement_rate="0.88",
        accepted=True,
    )
    assert verify_human_calibration_record(calibration)
    result = build_judgement_score(
        decision_id="d1",
        episode_id="e1",
        components=components,
        raw_n=1,
        effective_n=1,
        calibration_records=[calibration],
    )
    assert result["subjective_dimensions"] == ["factual_accuracy"]
    assert (
        result["dimensions"]["factual_accuracy"]["calibration_digest"]
        == calibration["calibration_digest"]
    )


def test_tampered_human_calibration_fails_verification() -> None:
    calibration = build_human_calibration_record(
        dimension="factual_accuracy",
        calibration_identity="day38-human-sample-v1",
        human_reviewed_n=10,
        reviewer_protocol_digest="r" * 64,
        agreement_rate="0.8",
        accepted=True,
    )
    calibration["agreement_rate"] = "0.99"
    assert verify_human_calibration_record(calibration) is False


def test_j16_passes_only_when_sufficient_independent_temporal_evidence_orders_dispersion() -> None:
    report = build_j16_grade_validity_report(
        _j16_rows(),
        evaluation_set_identity="day38-j16-fixture",
    )
    assert report["status"] == "pass"
    assert report["post_hardening_j16_is_authoritative"] is True
    assert report["day23_baseline_is_authoritative"] is False
    assert report["effective_independent_query_n"] == 24
    assert report["evaluable_grade_count"] == 2
    assert report["monotonic_nonincreasing_grade_median_dispersion"] is True
    assert float(report["spearman_grade_rank_vs_terminal_return_stddev"]) < 0


def test_j16_null_is_retained_when_ordering_fails_with_sufficient_n() -> None:
    report = build_j16_grade_validity_report(
        _j16_rows(reverse=True),
        evaluation_set_identity="day38-j16-null",
    )
    assert report["status"] == "null"
    assert report["null_result_retained"] is True
    assert report["predictive_edge_claimed"] is False


def test_j16_inconclusive_is_retained_when_effective_n_is_small() -> None:
    report = build_j16_grade_validity_report(
        _j16_rows(n=3),
        evaluation_set_identity="day38-j16-small",
    )
    assert report["status"] == "inconclusive"
    assert report["inconclusive_result_retained"] is True


def test_j16_temporal_dedup_ignores_dense_burst_queries() -> None:
    rows = _j16_rows(n=12)
    burst = copy.deepcopy(rows[0])
    burst["query_id"] = "burst-duplicate"
    burst["as_of_utc"] = (BASE + timedelta(minutes=30)).isoformat()
    rows.append(burst)
    report = build_j16_grade_validity_report(rows, evaluation_set_identity="burst-test")
    assert report["raw_query_n"] == 25
    assert report["effective_independent_query_n"] == 24


def test_risk_coverage_deduplicates_exact_episode_bursts() -> None:
    rows = [
        {"episode_id": "e1", "confidence": "0.9", "adverse_outcome": False},
        {"episode_id": "e1", "confidence": "0.9", "adverse_outcome": False},
        {"episode_id": "e2", "confidence": "0.4", "adverse_outcome": True},
    ]
    report = build_risk_coverage_report(
        rows,
        evaluation_set_identity="eval-v1",
        threshold_grid=["0.0", "0.5", "0.8"],
        threshold_grid_source="preregistered_day38_v1",
    )
    assert report["raw_n"] == 3
    assert report["effective_n"] == 2
    assert report["recommended_threshold"] is None
    assert report["evaluation_set_tuning_allowed"] is False
    assert report["points"][1]["effective_selected_n"] == 1


def test_risk_coverage_rejects_conflicting_duplicate_episode() -> None:
    rows = [
        {"episode_id": "e1", "confidence": "0.9", "adverse_outcome": False},
        {"episode_id": "e1", "confidence": "0.8", "adverse_outcome": False},
    ]
    with pytest.raises(EvaluationIntegrityError, match="Conflicting duplicate"):
        build_risk_coverage_report(
            rows,
            evaluation_set_identity="eval-v1",
            threshold_grid=["0.0", "0.5"],
            threshold_grid_source="preregistered_day38_v1",
        )


def test_risk_coverage_rejects_evaluation_tuned_threshold_grid() -> None:
    with pytest.raises(EvaluationIntegrityError, match="cannot be evaluation-tuned"):
        build_risk_coverage_report(
            [{"episode_id": "e1", "confidence": "0.9", "adverse_outcome": False}],
            evaluation_set_identity="eval-v1",
            threshold_grid=["0.5"],
            threshold_grid_source="evaluation_tuned_after_results",
        )


def test_j21_requires_frozen_20_variant_taxonomy() -> None:
    report = build_j21_setup_differentiation_report(
        _j21_rows(),
        evaluation_set_identity="j21-fixture",
    )
    assert report["setup_variant_count"] == 20
    assert len(report["per_setup"]) == 20
    assert report["taxonomy_expansion_allowed"] is False


def test_j21_detects_controlled_practical_differentiation_with_sufficient_effective_n() -> None:
    report = build_j21_setup_differentiation_report(
        _j21_rows(),
        evaluation_set_identity="j21-differentiated",
    )
    assert report["status"] == "differentiated"
    assert report["sufficient_setup_count"] == 2
    assert float(report["standardized_controlled_mean_span"]) >= 0.25
    assert report["predictive_edge_claimed"] is False


def test_j21_null_is_accepted_and_does_not_expand_taxonomy() -> None:
    report = build_j21_setup_differentiation_report(
        _j21_rows(null=True),
        evaluation_set_identity="j21-null",
    )
    assert report["status"] == "null"
    assert report["null_result_retained"] is True
    assert report["null_is_evidence_for_later_consolidation_review"] is True
    assert report["taxonomy_expansion_allowed"] is False
    assert report["automatic_taxonomy_consolidation_allowed"] is False


def test_j21_insufficient_variants_are_labelled_inconclusive() -> None:
    report = build_j21_setup_differentiation_report(
        _j21_rows(n_each=3),
        evaluation_set_identity="j21-small",
    )
    assert report["status"] == "inconclusive"
    assert report["inconclusive_result_retained"] is True
    assert all(item["state"] == "inconclusive" for item in report["per_setup"].values())


def test_j21_rejects_unknown_setup_id() -> None:
    row = _j21_rows(n_each=1)[0]
    row["setup_id"] = "new_label_added_after_seeing_outcomes"
    with pytest.raises(EvaluationIntegrityError, match="Unknown or non-frozen"):
        build_j21_setup_differentiation_report([row], evaluation_set_identity="bad")


def test_j21_rejects_taxonomy_version_drift() -> None:
    row = _j21_rows(n_each=1)[0]
    row["taxonomy_version"] = "future-taxonomy"
    with pytest.raises(EvaluationIntegrityError, match="taxonomy version drifted"):
        build_j21_setup_differentiation_report([row], evaluation_set_identity="bad")


def test_j21_direction_is_frozen_by_setup_definition() -> None:
    row = _j21_rows(n_each=1)[0]
    row["direction"] = "short" if row["direction"] == "long" else "long"
    with pytest.raises(EvaluationIntegrityError, match="direction drift"):
        build_j21_setup_differentiation_report([row], evaluation_set_identity="bad")


def test_j21_episode_selection_is_outcome_blind_and_deterministic() -> None:
    first_rows = _j21_rows()
    second_rows = list(reversed(copy.deepcopy(first_rows)))
    first = build_j21_setup_differentiation_report(
        first_rows, evaluation_set_identity="same"
    )
    second = build_j21_setup_differentiation_report(
        second_rows, evaluation_set_identity="same"
    )
    assert first == second
