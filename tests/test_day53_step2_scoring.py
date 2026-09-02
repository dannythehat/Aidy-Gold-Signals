from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from aidy.day53_step2_scoring import (
    decide_outcome,
    evaluate_step2_equivalence,
    is_qualification_bucket,
    is_retrieval_bucket,
    nearest_rank,
    structural_preflight_result,
    structural_retrieval_session_capacity,
    wilson_95,
)

CANDIDATE_UNIVERSE_DIGEST = "c" * 64


def _synthetic_complete_population() -> tuple[list[dict], list[dict]]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = datetime(2026, 8, 31, 23, tzinfo=UTC)
    features: list[dict] = []
    retrievals: list[dict] = []
    selected_index = 0
    cursor = start
    while cursor <= end:
        selected = is_qualification_bucket(cursor)
        if selected:
            selected_index += 1
            slot = selected_index % 6
            if slot in {0, 1}:
                atr = "20"
            elif slot in {2, 3}:
                atr = "50"
            else:
                atr = "35"
        else:
            atr = "35"
        features.append(
            {
                "h1_bucket_end_utc": cursor.isoformat(),
                "mechanically_common_scheduled_h1": True,
                "histdata_feature_available": True,
                "twelve_feature_available": True,
                "histdata_h1_atr_14_bps": atr,
                "twelve_h1_atr_14_bps": atr,
            }
        )
        if selected and is_retrieval_bucket(cursor):
            stamp = cursor.strftime("%Y%m%d%H")
            episodes = [f"{stamp}-episode-{index}" for index in range(3)]
            retrievals.append(
                {
                    "h1_bucket_end_utc": cursor.isoformat(),
                    "query_available": True,
                    "query_id": f"synthetic-{stamp}",
                    "baseline_selected_episode_ids": episodes,
                    "comparison_selected_episode_ids": list(episodes),
                    "baseline_evidence_grade": "established_dataset",
                    "comparison_evidence_grade": "established_dataset",
                    "hard_gate_boolean_pairs": [
                        {"baseline": True, "comparison": True},
                        {"baseline": False, "comparison": False},
                        {"baseline": True, "comparison": True},
                        {"baseline": False, "comparison": False},
                    ],
                }
            )
        cursor += timedelta(hours=1)
    return features, retrievals


def test_frozen_selector_session_capacity_is_structurally_insufficient_before_values() -> None:
    capacity = structural_retrieval_session_capacity()

    assert capacity["market_values_inspected"] is False
    assert capacity["nested_selector_timestamp_count"] == 342
    assert capacity["exact_session_label_upper_bounds"]["asia"] == 84
    assert capacity["exact_session_label_upper_bounds"]["london"] == 48
    assert capacity["exact_session_label_upper_bounds"]["new_york"] == 44
    assert capacity["structural_blockers"] == {
        "london": {"maximum_possible": 48, "required": 50},
        "new_york": {"maximum_possible": 44, "required": 50},
    }


def test_structural_preflight_terminates_as_insufficient_without_loading_market_values() -> None:
    result = structural_preflight_result()

    assert result["terminal"] is True
    assert result["outcome"] == "insufficient_evidence"
    assert result["inheritance_allowed"] is False
    assert result["cross_source_retrieval_permission"] is False
    assert result["evidence"]["candidate_universe_loaded"] is False
    assert result["evidence"]["market_values_inspected"] is False
    assert result["evidence"]["empirical_scoring_performed"] is False


def test_frozen_decision_rule_has_pass_fail_and_insufficient_states_without_discretion() -> None:
    minimums = {"sample": True, "coverage": True}
    criteria = {
        "criterion_a": {"pass": True},
        "criterion_b": {"pass": True},
    }
    assert (
        decide_outcome(
            minimum_requirements=minimums,
            mandatory_criteria=criteria,
            required_statistics_available=True,
        )
        == "pass"
    )

    failed = {**criteria, "criterion_b": {"pass": False}}
    assert (
        decide_outcome(
            minimum_requirements=minimums,
            mandatory_criteria=failed,
            required_statistics_available=True,
        )
        == "fail"
    )

    insufficient = {**minimums, "coverage": False}
    assert (
        decide_outcome(
            minimum_requirements=insufficient,
            mandatory_criteria=criteria,
            required_statistics_available=True,
        )
        == "insufficient_evidence"
    )


def test_synthetic_perfect_values_still_cannot_override_structural_coverage() -> None:
    features, retrievals = _synthetic_complete_population()
    first = evaluate_step2_equivalence(
        common_h1_observations=features,
        retrieval_comparisons=retrievals,
        candidate_universe_digest=CANDIDATE_UNIVERSE_DIGEST,
    )

    rng = random.Random(5302)
    shuffled_features = list(features)
    shuffled_retrievals = list(retrievals)
    rng.shuffle(shuffled_features)
    rng.shuffle(shuffled_retrievals)
    second = evaluate_step2_equivalence(
        common_h1_observations=shuffled_features,
        retrieval_comparisons=shuffled_retrievals,
        candidate_universe_digest=CANDIDATE_UNIVERSE_DIGEST,
    )

    assert first["outcome"] == "insufficient_evidence"
    assert first["inheritance_allowed"] is False
    assert first["result_digest"] == second["result_digest"]
    assert all(
        item["pass"] is True
        for item in first["evidence"]["mandatory_criteria"].values()
    )
    assert first["evidence"]["minimum_requirements"]["retrieval_query_count"] is True
    assert first["evidence"]["minimum_requirements"]["both_retrievals_non_empty"] is True
    assert first["evidence"]["minimum_requirements"]["asia_query_count"] is True
    assert first["evidence"]["minimum_requirements"]["london_query_count"] is False
    assert first["evidence"]["minimum_requirements"]["new_york_query_count"] is False


def test_scorer_rejects_outcome_or_pnl_fields_before_any_scoring() -> None:
    features, retrievals = _synthetic_complete_population()
    features[0]["pnl"] = "100"

    with pytest.raises(ValueError, match="Outcome/P&L field is forbidden"):
        evaluate_step2_equivalence(
            common_h1_observations=features,
            retrieval_comparisons=retrievals,
            candidate_universe_digest=CANDIDATE_UNIVERSE_DIGEST,
        )


def test_wilson_and_nearest_rank_are_deterministic_and_bounded() -> None:
    lower, upper = wilson_95(600, 600)
    assert lower is not None and upper is not None
    assert Decimal("0.99") < lower <= upper <= Decimal(1)

    values = [Decimal(index) / Decimal(10) for index in range(1, 11)]
    assert nearest_rank(values, Decimal("0.10")) == Decimal("0.1")
    assert nearest_rank(values, Decimal("0.50")) == Decimal("0.5")
    assert nearest_rank(values, Decimal("0.95")) == Decimal("1")
