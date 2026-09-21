from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from aidy.gold_meta_replay import (
    build_meta_replay_dataset,
    build_meta_replay_policy,
    build_meta_replay_report,
    build_meta_replay_split,
    verify_meta_replay_dataset,
    verify_meta_replay_policy,
    verify_meta_replay_report,
    verify_meta_replay_split,
)

START = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
GATES = ["core_structure", "spurious_gate", "correlated_price"]


def _opposite(direction: str) -> str:
    return "bearish" if direction == "bullish" else "bullish"


def _rows() -> list[dict]:
    rows = []
    for i in range(120):
        as_of = START + timedelta(minutes=15 * i)
        actual = "bullish" if i % 2 == 0 else "bearish"
        return_bps = Decimal(7) if i % 3 == 0 else Decimal(3)
        if actual == "bearish":
            return_bps = -return_bps

        legacy = actual if i % 5 < 3 else _opposite(actual)
        core = actual if i % 10 < 7 else _opposite(actual)
        if i < 40:
            spurious = actual if i % 10 < 9 else _opposite(actual)
        elif i < 80:
            spurious = actual if i % 10 < 4 else _opposite(actual)
        else:
            # Deliberately looks good again on holdout. Validation must still control
            # the recommendation so holdout cannot rescue/promote it.
            spurious = actual if i % 10 < 8 else _opposite(actual)
        correlated = actual if i % 10 >= 6 else _opposite(actual)

        rows.append(
            {
                "case_id": f"case-{i:03d}",
                "input_digest": f"{i:064x}",
                "as_of_utc": as_of.isoformat(),
                "outcome_available_at_utc": (as_of + timedelta(minutes=15)).isoformat(),
                "environment_label": "trend" if i % 3 else "range",
                "decision_state": {
                    "legacy_direction": legacy,
                    "gates": {
                        "core_structure": {
                            "conclusion": core,
                            "authority_weight": "0.80",
                            "raw_authority_weight": "0.80",
                            "classification": "high_trust",
                            "gate_mode": "directional",
                        },
                        "spurious_gate": {
                            "conclusion": spurious,
                            "authority_weight": "0.35",
                            "raw_authority_weight": "0.35",
                            "classification": "reduced_trust",
                            "gate_mode": "directional",
                        },
                        "correlated_price": {
                            "conclusion": correlated,
                            "authority_weight": "0.10",
                            "raw_authority_weight": "1.00",
                            "classification": "reduced_trust",
                            "gate_mode": "directional",
                        },
                    },
                    "variant_confidences": {
                        "legacy_simple_15m": "0.60",
                        "full_system_dependency_on": "0.70",
                    },
                    "future_values_used": False,
                    "source_version": "aidy_gold_meta_direction_aggregator_v1",
                },
                "outcome": {
                    "direction": actual,
                    "return_bps": str(return_bps),
                    "evaluation_only": True,
                },
            }
        )
    return rows


def _dataset(rows: list[dict] | None = None) -> dict:
    return build_meta_replay_dataset(
        rows or _rows(),
        dataset_version="build23-acceptance-v1",
        source_snapshot_identity="synthetic_build23_acceptance_fixture_v1",
        code_head="build23-fixture-head",
    )


def _split(dataset: dict) -> dict:
    return build_meta_replay_split(
        dataset,
        development_end=START + timedelta(minutes=15 * 39),
        validation_end=START + timedelta(minutes=15 * 79),
        holdout_end=START + timedelta(minutes=15 * 119),
        purge_minutes=15,
        embargo_minutes=15,
        holdout_identity="build23-frozen-holdout-v1",
    )


def _report(rows: list[dict] | None = None) -> dict:
    dataset = _dataset(rows)
    split = _split(dataset)
    policy = build_meta_replay_policy(GATES)
    return build_meta_replay_report(
        dataset=dataset,
        split_manifest=split,
        policy=policy,
    )


def test_build23_dataset_separates_decision_state_from_later_outcome() -> None:
    dataset = _dataset()

    assert verify_meta_replay_dataset(dataset)
    assert dataset["decision_outcome_separation_enforced"] is True
    assert all(
        row["outcome_available_at_utc"] > row["as_of_utc"]
        for row in dataset["cases"]
    )


def test_build23_decision_state_rejects_outcome_injection() -> None:
    rows = _rows()
    rows[0]["decision_state"]["outcome"] = "winner"

    with pytest.raises(ValueError, match="hindsight"):
        _dataset(rows)


def test_build23_dataset_is_deterministic_under_row_reordering() -> None:
    rows = _rows()
    left = _dataset(rows)
    right = _dataset(list(reversed(rows)))

    assert left == right
    assert left["dataset_digest"] == right["dataset_digest"]


def test_build23_split_is_chronological_purged_embargoed_and_holdout_frozen() -> None:
    dataset = _dataset()
    split = _split(dataset)

    assert verify_meta_replay_split(split, dataset)
    assert split["purge_minutes"] == 15
    assert split["embargo_minutes"] == 15
    assert split["purged_from_prior"]["development_before_validation"]
    assert split["purged_from_prior"]["validation_before_holdout"]
    assert split["embargoed_from_split_start"]["validation"]
    assert split["embargoed_from_split_start"]["holdout"]
    assert split["holdout_tuning_allowed"] is False
    assert split["holdout_recommendation_updates_allowed"] is False


def test_build23_policy_freezes_required_ablation_variants_before_scoring() -> None:
    policy = build_meta_replay_policy(GATES)

    assert verify_meta_replay_policy(policy)
    assert "legacy_simple_15m" in policy["variants"]
    assert "full_system_dependency_on" in policy["variants"]
    assert "full_system_dependency_off" in policy["variants"]
    assert all(f"gate_only:{gate}" in policy["variants"] for gate in GATES)
    assert all(f"full_minus:{gate}" in policy["variants"] for gate in GATES)
    assert policy["holdout_can_tune_or_promote"] is False


def test_build23_report_contains_all_required_metrics_and_comparisons() -> None:
    report = _report()

    assert verify_meta_replay_report(report)
    assert all(report["comparisons_present"].values())
    assert all(report["metrics_present"].values())
    for split_name in ("development", "validation", "holdout"):
        assert report["split_metrics"][split_name]["full_system_dependency_on"]["sample_n"] > 0
        assert "performance_by_environment" in report["split_metrics"][split_name]["full_system_dependency_on"]
        assert "stability_accuracy_gap" in report["split_metrics"][split_name]["full_system_dependency_on"]


def test_build23_spurious_in_sample_star_is_not_promoted() -> None:
    report = _report()
    dev = report["split_metrics"]["development"]["gate_only:spurious_gate"]
    validation = report["split_metrics"]["validation"]["gate_only:spurious_gate"]
    recommendation = report["validation_recommendations"]["gate_recommendations"]["spurious_gate"]

    assert Decimal(dev["accuracy"]) > Decimal("0.80")
    assert Decimal(validation["accuracy"]) < Decimal("0.50")
    assert recommendation["recommendation"] == "prune_or_downweight"
    assert recommendation["development_metrics_used_for_recommendation"] is False
    assert recommendation["holdout_metrics_used_for_recommendation"] is False


def test_build23_large_validation_core_gate_is_retained_candidate() -> None:
    report = _report()
    recommendation = report["validation_recommendations"]["gate_recommendations"]["core_structure"]

    assert recommendation["recommendation"] == "retain_candidate"
    assert Decimal(recommendation["validation_delta_accuracy"]) > 0


def test_build23_dependency_penalty_is_ablation_tested() -> None:
    report = _report()
    validation = report["split_metrics"]["validation"]
    dep_on = validation["full_system_dependency_on"]
    dep_off = validation["full_system_dependency_off"]
    recommendation = report["validation_recommendations"]["dependency_recommendation"]

    assert Decimal(dep_on["accuracy"]) > Decimal(dep_off["accuracy"])
    assert recommendation["recommendation"] == "retain_dependency_penalty"
    assert Decimal(recommendation["validation_delta_accuracy"]) > 0


def test_build23_holdout_cannot_change_gate_recommendations() -> None:
    original = _report()
    changed_rows = copy.deepcopy(_rows())
    for i, row in enumerate(changed_rows):
        if i < 80:
            continue
        row["outcome"]["direction"] = _opposite(row["outcome"]["direction"])
        row["outcome"]["return_bps"] = str(-Decimal(row["outcome"]["return_bps"]))

    changed = _report(changed_rows)

    assert (
        original["validation_recommendations"]
        == changed["validation_recommendations"]
    )
    assert (
        original["untouched_holdout_comparison"]
        != changed["untouched_holdout_comparison"]
    )
    assert original["holdout_tuning_allowed"] is False
    assert original["holdout_recommendation_updates_allowed"] is False


def test_build23_plus2_plus1_minus1_minus2_scoring_is_present() -> None:
    report = _report()
    legacy = report["split_metrics"]["validation"]["legacy_simple_15m"]

    assert legacy["net_score"] != 0
    assert Decimal(legacy["score_mean"]) != 0


def test_build23_brier_is_only_reported_where_confidence_exists() -> None:
    report = _report()
    validation = report["split_metrics"]["validation"]

    assert validation["full_system_dependency_on"]["brier"] is not None
    assert validation["full_system_dependency_on"]["brier_sample_n"] > 0
    assert validation["gate_only:core_structure"]["brier"] is None
    assert validation["gate_only:core_structure"]["brier_sample_n"] == 0


def test_build23_coverage_and_abstention_are_explicit() -> None:
    report = _report()
    validation = report["split_metrics"]["validation"]["full_system_dependency_off"]

    assert Decimal(validation["coverage"]) <= Decimal(1)
    assert validation["covered_n"] + validation["abstain_n"] == validation["sample_n"]


def test_build23_fixture_cannot_be_mislabeled_as_real_market_edge() -> None:
    report = _report()

    assert report["source_evidence_class"] == "acceptance_fixture"
    assert report["real_market_edge_proven"] is False
    assert report["untouched_holdout_comparison"]["empirical_edge_claimed"] is False


def test_build23_report_is_reproducible_from_versioned_inputs() -> None:
    dataset = _dataset()
    split = _split(dataset)
    policy = build_meta_replay_policy(GATES)
    args = {
        "dataset": dataset,
        "split_manifest": split,
        "policy": policy,
    }

    first = build_meta_replay_report(**args)
    second = build_meta_replay_report(**args)

    assert first == second
    assert first["report_digest"] == second["report_digest"]
    assert first["results_reproducible_from_versioned_inputs"] is True
    assert first["future_values_used_for_prediction"] is False
    assert first["formal_forward_evidence_created"] is False
    assert first["live_money_execution_allowed"] is False
