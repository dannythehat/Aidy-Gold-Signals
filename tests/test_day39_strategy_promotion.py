from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from aidy.replay_evaluation import HOLDOUT_ACCESS_VERSION
from aidy.replay_evaluation import digest as replay_digest
from aidy.research_integrity import (
    IntegrityError,
    digest as trial_digest,
    finalize_trial,
    preregister_trial,
    verify_trial_registry,
)
from aidy.strategy_promotion import (
    REQUIRED_COMPONENTS,
    PromotionIntegrityError,
    apply_registry_event,
    build_multiple_testing_control,
    build_promotion_event,
    build_promotion_policy,
    build_registry_snapshot,
    build_rollback_event,
    build_rollback_record,
    build_strategy_version,
    deflated_sharpe_ratio,
    digest as promotion_digest,
    evaluate_promotion,
    promotion_manifest,
    verify_multiple_testing_control,
    verify_promotion_decision,
    verify_promotion_policy,
    verify_registry_event,
    verify_registry_snapshot,
    verify_rollback_record,
    verify_strategy_version,
)

NOW = datetime(2026, 9, 1, 6, 0, tzinfo=UTC)
CODE_HEAD = "a" * 40
DATASET_VERSION = "day39-frozen-dataset-v1"
EVALUATION_IDENTITY = "day39-chronological-holdout-v1"
FINAL_HOLDOUT = "day39-holdout-final"


def _components(prefix: str) -> dict[str, str]:
    return {key: f"{prefix}-{key}-v1" for key in REQUIRED_COMPONENTS}


def _version(
    version_id: str,
    *,
    registered_offset: int,
    parent: str | None = None,
) -> dict[str, object]:
    return build_strategy_version(
        version_id=version_id,
        registered_at=NOW + timedelta(minutes=registered_offset),
        code_head=CODE_HEAD,
        components=_components(version_id),
        config={"threshold": version_id, "risk_authority": False},
        change_hypothesis=f"{version_id} should improve broad judgement metrics.",
        parent_version_digest=parent,
    )


def _policy() -> dict[str, object]:
    return build_promotion_policy(
        metric_criteria=[
            {
                "metric": "judgement_score",
                "direction": "higher",
                "minimum_delta": "0.02",
            },
            {
                "metric": "risk_coverage_quality",
                "direction": "higher",
                "minimum_delta": "0.02",
            },
            {
                "metric": "decision_stability",
                "direction": "higher",
                "minimum_delta": "0.01",
            },
        ],
        safety_criteria=[
            {
                "metric": "safety_violation_rate",
                "direction": "lower",
                "minimum_delta": 0,
            },
            {
                "metric": "grounding_failure_rate",
                "direction": "lower",
                "minimum_delta": 0,
            },
        ],
        minimum_improved_metrics=2,
        dsr_min_probability="0.95",
    )


def _trial_registry(
    champion: dict[str, object],
    challenger: dict[str, object],
    policy: dict[str, object],
    *,
    candidate_state: str = "passed",
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    states = ("null", "insufficient", "failed", candidate_state)
    for number, state in enumerate(states, start=1):
        final = number == len(states)
        holdout = FINAL_HOLDOUT if final else f"day39-holdout-{number}"
        frozen: dict[str, object] = {"attempt": number}
        if final:
            frozen = {
                "champion_version_digest": champion["version_digest"],
                "challenger_version_digest": challenger["version_digest"],
                "promotion_policy_digest": policy["policy_digest"],
                "declared_trial_count": len(states),
            }
        registered = preregister_trial(
            rows,
            trial_number=number,
            hypothesis=f"challenger attempt {number} improves pre-specified metrics",
            null_hypothesis=f"challenger attempt {number} does not improve them",
            dataset_version=DATASET_VERSION,
            feature_context_version="aidy_market_context_v7_volatility_state",
            frozen_parameters=frozen,
            chronological_split={
                "train": "chronological_pre_holdout",
                "holdout": holdout,
            },
            purge="240m",
            embargo="240m",
            evaluation_identity=(
                EVALUATION_IDENTITY if final else f"day39-evaluation-{number}"
            ),
            holdout_identity=holdout,
            preregistered_at=NOW + timedelta(minutes=number),
            code_head=CODE_HEAD,
            evidence_digest="e" * 64,
            purpose="evaluation",
        )
        rows.append(
            finalize_trial(
                registered,
                executed_at=NOW + timedelta(minutes=number, seconds=30),
                result_state=state,
                result={"attempt": number, "state": state},
            )
        )
    assert verify_trial_registry(rows)
    return rows


def _holdout_access(
    trial: dict[str, object],
    challenger: dict[str, object],
) -> dict[str, object]:
    record: dict[str, object] = {
        "access_version": HOLDOUT_ACCESS_VERSION,
        "trial_identity": trial["trial_identity"],
        "trial_digest": trial["trial_digest"],
        "dataset_manifest_digest": "d" * 64,
        "split_digest": "s" * 64,
        "holdout_identity": FINAL_HOLDOUT,
        "frozen_version_digest": challenger["version_digest"],
        "accessed_at": (NOW + timedelta(hours=1)).isoformat(),
        "accessed_case_ids": ["holdout-case-001", "holdout-case-002"],
        "accessed_case_count": 2,
        "score_digest": "c" * 64,
        "purpose": "score_frozen_version",
        "tuning_allowed_after_access": False,
        "same_holdout_reusable_for_tuning": False,
        "silent_promotion_allowed": False,
        "new_trial_required_for_changes": True,
    }
    record["access_digest"] = replay_digest(record)
    return record


def _multiple_testing(
    registry: list[dict[str, object]],
    *,
    strong: bool = True,
) -> dict[str, object]:
    return build_multiple_testing_control(
        registry,
        sharpe_statistics={
            "observed_sharpe": "2.0" if strong else "0.05",
            "observation_count": 300,
            "variance_across_trials": "0.01" if strong else "1.0",
            "skewness": "0",
            "kurtosis": "3",
        },
    )


def _decision(
    *,
    candidate_state: str = "passed",
    strong_dsr: bool = True,
    challenger_metrics: dict[str, str] | None = None,
    challenger_safety: dict[str, str] | None = None,
) -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, object],
    list[dict[str, object]],
    dict[str, object],
]:
    champion = _version("champion-v1", registered_offset=0)
    challenger = _version(
        "challenger-v2",
        registered_offset=1,
        parent=str(champion["version_digest"]),
    )
    policy = _policy()
    registry = _trial_registry(
        champion, challenger, policy, candidate_state=candidate_state
    )
    decision = evaluate_promotion(
        champion_version=champion,
        challenger_version=challenger,
        policy=policy,
        trial_registry=registry,
        challenger_trial_identity=str(registry[-1]["trial_identity"]),
        champion_metrics={
            "judgement_score": "0.70",
            "risk_coverage_quality": "0.60",
            "decision_stability": "0.80",
        },
        challenger_metrics=challenger_metrics
        or {
            "judgement_score": "0.75",
            "risk_coverage_quality": "0.64",
            "decision_stability": "0.81",
        },
        champion_safety={
            "safety_violation_rate": "0.01",
            "grounding_failure_rate": "0.02",
        },
        challenger_safety=challenger_safety
        or {
            "safety_violation_rate": "0.01",
            "grounding_failure_rate": "0.01",
        },
        multiple_testing_control=_multiple_testing(registry, strong=strong_dsr),
        holdout_access_record=_holdout_access(registry[-1], challenger),
        evaluation_identity=EVALUATION_IDENTITY,
        holdout_identity=FINAL_HOLDOUT,
        evaluated_at=NOW + timedelta(hours=2),
    )
    return champion, challenger, policy, registry, decision


def test_strategy_version_is_immutable_and_digest_bound() -> None:
    version = _version("champion-v1", registered_offset=0)
    assert verify_strategy_version(version)
    mutated = copy.deepcopy(version)
    mutated["components"]["model_version"] = "secretly-swapped"
    assert not verify_strategy_version(mutated)


def test_strategy_version_requires_all_six_component_identities() -> None:
    components = _components("bad")
    components.pop("safety_version")
    with pytest.raises(PromotionIntegrityError):
        build_strategy_version(
            version_id="bad",
            registered_at=NOW,
            code_head=CODE_HEAD,
            components=components,
            config={},
            change_hypothesis="bad",
        )


def test_strategy_version_never_contains_execution_authority() -> None:
    version = _version("champion-v1", registered_offset=0)
    assert version["autonomous_mutation_allowed"] is False
    assert version["broker_side_effects_allowed"] is False
    assert version["telegram_side_effects_allowed"] is False
    assert version["super_signals_side_effects_allowed"] is False


def test_policy_requires_broad_metrics_and_non_compensatory_safety() -> None:
    policy = _policy()
    assert verify_promotion_policy(policy)
    assert policy["minimum_improved_metrics"] == 2
    assert policy["require_all_primary_metrics_non_degrading"] is True
    assert policy["require_all_safety_metrics_non_degrading"] is True


def test_policy_rejects_single_metric_promotion_rules() -> None:
    with pytest.raises(PromotionIntegrityError):
        build_promotion_policy(
            metric_criteria=[
                {"metric": "profit", "direction": "higher", "minimum_delta": 0}
            ],
            safety_criteria=[
                {
                    "metric": "safety_violation_rate",
                    "direction": "lower",
                    "minimum_delta": 0,
                }
            ],
            minimum_improved_metrics=1,
        )


def test_trial_registry_retains_failed_null_and_insufficient_attempts() -> None:
    champion = _version("champion-v1", registered_offset=0)
    challenger = _version(
        "challenger-v2",
        registered_offset=1,
        parent=str(champion["version_digest"]),
    )
    registry = _trial_registry(champion, challenger, _policy())
    assert [row["result_state"] for row in registry] == [
        "null",
        "insufficient",
        "failed",
        "passed",
    ]


def test_day32_contract_forbids_holdout_reuse_for_tuning() -> None:
    champion = _version("champion-v1", registered_offset=0)
    challenger = _version(
        "challenger-v2",
        registered_offset=1,
        parent=str(champion["version_digest"]),
    )
    registry = _trial_registry(champion, challenger, _policy())
    with pytest.raises(IntegrityError):
        preregister_trial(
            registry,
            trial_number=5,
            hypothesis="reuse",
            null_hypothesis="no reuse",
            dataset_version=DATASET_VERSION,
            feature_context_version="aidy_market_context_v7_volatility_state",
            frozen_parameters={},
            chronological_split={},
            purge="240m",
            embargo="240m",
            evaluation_identity="bad-tuning",
            holdout_identity=FINAL_HOLDOUT,
            preregistered_at=NOW + timedelta(hours=3),
            code_head=CODE_HEAD,
            evidence_digest="e" * 64,
            purpose="tuning",
        )


def test_multiple_testing_control_uses_complete_registry_count() -> None:
    champion = _version("champion-v1", registered_offset=0)
    challenger = _version(
        "challenger-v2",
        registered_offset=1,
        parent=str(champion["version_digest"]),
    )
    registry = _trial_registry(champion, challenger, _policy())
    report = _multiple_testing(registry)
    assert verify_multiple_testing_control(report)
    assert report["trial_count"] == 4
    assert report["terminal_result_counts"] == {
        "failed": 1,
        "insufficient": 1,
        "null": 1,
        "passed": 1,
    }


def test_no_sharpe_claim_does_not_invent_dsr() -> None:
    champion = _version("champion-v1", registered_offset=0)
    challenger = _version(
        "challenger-v2",
        registered_offset=1,
        parent=str(champion["version_digest"]),
    )
    registry = _trial_registry(champion, challenger, _policy())
    report = build_multiple_testing_control(registry)
    assert report["method"] == "trial_count_only"
    assert report["sharpe_claimed"] is False
    assert report["deflated_sharpe"] is None


def test_deflated_sharpe_penalizes_more_trials() -> None:
    one = deflated_sharpe_ratio(
        observed_sharpe="0.8",
        trial_count=1,
        observation_count=200,
        variance_across_trials="0.04",
    )
    many = deflated_sharpe_ratio(
        observed_sharpe="0.8",
        trial_count=50,
        observation_count=200,
        variance_across_trials="0.04",
    )
    assert Decimal(one["deflated_sharpe_probability"]) > Decimal(
        many["deflated_sharpe_probability"]
    )


def test_deflated_sharpe_rejects_impossible_sampling_geometry() -> None:
    with pytest.raises(PromotionIntegrityError):
        deflated_sharpe_ratio(
            observed_sharpe="10",
            trial_count=4,
            observation_count=100,
            variance_across_trials="0.1",
            skewness="100",
            kurtosis="1",
        )


def test_clean_broad_improvement_can_recommend_promotion() -> None:
    *_, decision = _decision()
    assert verify_promotion_decision(decision)
    assert decision["status"] == "promote"
    assert decision["broad_improvement_passed"] is True
    assert decision["safety_parity_passed"] is True
    assert decision["deflated_sharpe_passed"] is True
    assert decision["owner_approval_still_required"] is True


def test_single_great_metric_cannot_compensate_for_degradation() -> None:
    *_, decision = _decision(
        challenger_metrics={
            "judgement_score": "0.99",
            "risk_coverage_quality": "0.59",
            "decision_stability": "0.90",
        }
    )
    assert decision["status"] == "retain_champion"
    assert "primary_metric_degradation" in decision["reasons"]


def test_safety_regression_is_non_compensatory() -> None:
    *_, decision = _decision(
        challenger_safety={
            "safety_violation_rate": "0.02",
            "grounding_failure_rate": "0.00",
        }
    )
    assert decision["status"] == "retain_champion"
    assert decision["safety_parity_passed"] is False
    assert "safety_parity_failed" in decision["reasons"]


def test_dsr_failure_blocks_sharpe_based_promotion() -> None:
    *_, decision = _decision(strong_dsr=False)
    assert decision["status"] == "retain_champion"
    assert decision["deflated_sharpe_passed"] is False
    assert "deflated_sharpe_threshold_failed" in decision["reasons"]


@pytest.mark.parametrize("state", ["null", "insufficient", "failed"])
def test_nonpassing_trials_are_auditable_and_inconclusive(state: str) -> None:
    *_, decision = _decision(candidate_state=state)
    assert decision["status"] == "inconclusive"
    assert decision["trial_result_state"] == state
    assert decision["reasons"] == [f"challenger_trial_{state}"]


def test_incomplete_declared_trial_count_is_rejected() -> None:
    champion = _version("champion-v1", registered_offset=0)
    challenger = _version(
        "challenger-v2",
        registered_offset=1,
        parent=str(champion["version_digest"]),
    )
    policy = _policy()
    registry = _trial_registry(champion, challenger, policy)
    last = copy.deepcopy(registry[-1])
    last["frozen_parameters"]["declared_trial_count"] = 3
    body = dict(last)
    body.pop("trial_digest")
    last["trial_digest"] = trial_digest(body)
    broken = [*registry[:-1], last]
    assert verify_trial_registry(broken)

    with pytest.raises(PromotionIntegrityError, match="declared_trial_count"):
        evaluate_promotion(
            champion_version=champion,
            challenger_version=challenger,
            policy=policy,
            trial_registry=broken,
            challenger_trial_identity=str(last["trial_identity"]),
            champion_metrics={
                "judgement_score": "0.7",
                "risk_coverage_quality": "0.6",
                "decision_stability": "0.8",
            },
            challenger_metrics={
                "judgement_score": "0.8",
                "risk_coverage_quality": "0.7",
                "decision_stability": "0.9",
            },
            champion_safety={
                "safety_violation_rate": "0.01",
                "grounding_failure_rate": "0.01",
            },
            challenger_safety={
                "safety_violation_rate": "0.01",
                "grounding_failure_rate": "0.01",
            },
            multiple_testing_control=_multiple_testing(broken),
            holdout_access_record=_holdout_access(last, challenger),
            evaluation_identity=EVALUATION_IDENTITY,
            holdout_identity=FINAL_HOLDOUT,
            evaluated_at=NOW,
        )


def test_mutated_holdout_access_is_rejected() -> None:
    champion = _version("champion-v1", registered_offset=0)
    challenger = _version(
        "challenger-v2",
        registered_offset=1,
        parent=str(champion["version_digest"]),
    )
    policy = _policy()
    registry = _trial_registry(champion, challenger, policy)
    access = _holdout_access(registry[-1], challenger)
    access["silent_promotion_allowed"] = True

    with pytest.raises(PromotionIntegrityError, match="holdout access"):
        evaluate_promotion(
            champion_version=champion,
            challenger_version=challenger,
            policy=policy,
            trial_registry=registry,
            challenger_trial_identity=str(registry[-1]["trial_identity"]),
            champion_metrics={
                "judgement_score": "0.7",
                "risk_coverage_quality": "0.6",
                "decision_stability": "0.8",
            },
            challenger_metrics={
                "judgement_score": "0.8",
                "risk_coverage_quality": "0.7",
                "decision_stability": "0.9",
            },
            champion_safety={
                "safety_violation_rate": "0.01",
                "grounding_failure_rate": "0.01",
            },
            challenger_safety={
                "safety_violation_rate": "0.01",
                "grounding_failure_rate": "0.01",
            },
            multiple_testing_control=_multiple_testing(registry),
            holdout_access_record=access,
            evaluation_identity=EVALUATION_IDENTITY,
            holdout_identity=FINAL_HOLDOUT,
            evaluated_at=NOW,
        )


def _promoted_registry() -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, object],
]:
    champion, challenger, _, _, decision = _decision()
    registry = build_registry_snapshot(
        versions=[champion, challenger],
        active_champion_digest=str(champion["version_digest"]),
    )
    event = build_promotion_event(
        registry=registry,
        decision=decision,
        approved_by="owner",
        approved_at=NOW + timedelta(hours=3),
    )
    assert verify_registry_event(event)
    promoted = apply_registry_event(registry, event)
    assert verify_registry_snapshot(promoted)
    return champion, challenger, promoted


def test_registry_promotion_is_append_only_and_manual() -> None:
    champion, challenger, promoted = _promoted_registry()
    assert promoted["registered_version_count"] == 2
    assert promoted["active_champion_digest"] == challenger["version_digest"]
    assert promoted["versions"][0]["version_digest"] == champion["version_digest"]
    assert promoted["events"][0]["autonomous_execution_allowed"] is False


def test_registry_rejects_unregistered_target() -> None:
    champion, challenger, _, _, decision = _decision()
    registry = build_registry_snapshot(
        versions=[champion, challenger],
        active_champion_digest=str(champion["version_digest"]),
    )
    event = build_promotion_event(
        registry=registry,
        decision=decision,
        approved_by="owner",
        approved_at=NOW,
    )
    bad = copy.deepcopy(event)
    bad["to_version_digest"] = "not-registered"
    body = dict(bad)
    body.pop("event_digest")
    bad["event_digest"] = promotion_digest(body)
    with pytest.raises(PromotionIntegrityError, match="not registered"):
        apply_registry_event(registry, bad)


def test_rollback_returns_to_prior_version_without_deleting_versions() -> None:
    champion, _, promoted = _promoted_registry()
    rollback = build_rollback_record(
        registry=promoted,
        rollback_to_version_digest=str(champion["version_digest"]),
        trigger="safety_regression",
        evidence_digest="r" * 64,
        approved_by="owner",
        approved_at=NOW + timedelta(hours=4),
    )
    assert verify_rollback_record(rollback)
    rolled_back = apply_registry_event(
        promoted,
        build_rollback_event(registry=promoted, rollback_record=rollback),
    )
    assert rolled_back["active_champion_digest"] == champion["version_digest"]
    assert rolled_back["event_count"] == 2
    assert rolled_back["registered_version_count"] == 2


def test_performance_only_rollback_trigger_is_rejected() -> None:
    champion, _, promoted = _promoted_registry()
    with pytest.raises(PromotionIntegrityError):
        build_rollback_record(
            registry=promoted,
            rollback_to_version_digest=str(champion["version_digest"]),
            trigger="performance_worse_than_expected",
            evidence_digest="r" * 64,
            approved_by="owner",
            approved_at=NOW,
        )


def test_promotion_decision_never_claims_edge_or_execution_authority() -> None:
    *_, decision = _decision()
    assert decision["predictive_edge_claimed"] is False
    assert decision["autonomous_registry_change_allowed"] is False
    assert decision["broker_side_effects_allowed"] is False
    assert decision["telegram_side_effects_allowed"] is False
    assert decision["super_signals_side_effects_allowed"] is False


def test_manifest_freezes_day39_boundaries() -> None:
    manifest = promotion_manifest()
    assert manifest["day32_preregistered_trial_required"] is True
    assert manifest["day37_holdout_access_record_required"] is True
    assert manifest["complete_trial_count_required"] is True
    assert manifest["deflated_sharpe_required_when_sharpe_claimed"] is True
    assert manifest["safety_parity_non_compensatory"] is True
    assert manifest["champion_overwrite_allowed"] is False
    assert manifest["version_deletion_allowed"] is False
    assert manifest["autonomous_self_modification_allowed"] is False
    assert manifest["predictive_edge_claimed"] is False
