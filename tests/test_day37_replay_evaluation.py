from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta

import pytest

from aidy.historical_cases import CASE_VERSION, compute_historical_case_digest
from aidy.replay_evaluation import (
    ReplayIntegrityError,
    assert_replay_evidence_known_at_t,
    build_chronological_split_manifest,
    build_cpcv_manifest,
    build_frozen_dataset_manifest,
    build_holdout_access_record,
    build_replay_score_record,
    replay_harness_manifest,
    verify_chronological_split_manifest,
    verify_cpcv_manifest,
    verify_frozen_dataset_manifest,
    verify_holdout_access_record,
    verify_replay_score_record,
)
from aidy.replay_experiment import (
    build_replay_experiment_manifest,
    verify_replay_experiment_manifest,
)
from aidy.research_integrity import preregister_trial

BASE = datetime(2025, 1, 1, tzinfo=UTC)
NOW = datetime(2026, 9, 1, 5, 0, tzinfo=UTC)
DATASET_VERSION = "day37-dataset-v1"
HOLDOUT_IDENTITY = "day37-holdout-v1"
HEAD = "d988a4ff29160e2d10a32e6c151d028001e941f2"


def _case(index: int, *, as_of: datetime, horizon_hours: int = 12) -> dict[str, object]:
    boundary = {
        "input_version": "day37-fixture-input-v1",
        "input_digest": f"{index + 1:064x}",
        "as_of_utc": as_of.isoformat(),
        "future_derived": False,
    }
    case: dict[str, object] = {
        "case_version": CASE_VERSION,
        "case_id": f"case-{index:03d}",
        "symbol": "XAUUSD",
        "as_of_utc": as_of.isoformat(),
        "provenance_class": "retrospective_history",
        "decision_input_allowed": False,
        "input_boundary": boundary,
        "future_evaluation": {
            "evaluation_only": True,
            "decision_input_allowed": False,
            "future_derived": True,
            "available_after_utc": (as_of + timedelta(hours=horizon_hours)).isoformat(),
        },
    }
    case["case_digest"] = compute_historical_case_digest(case)
    return case


def _cases() -> list[dict[str, object]]:
    result = []
    for index in range(24):
        result.append(_case(index, as_of=BASE + timedelta(days=index * 2 + 1)))
    return result


def _dataset(cases: list[dict[str, object]] | None = None) -> dict[str, object]:
    return build_frozen_dataset_manifest(
        _cases() if cases is None else cases,
        dataset_version=DATASET_VERSION,
        source_snapshot_identity="r2/day37/frozen-snapshot",
        code_head=HEAD,
    )


def _split(dataset: dict[str, object] | None = None) -> dict[str, object]:
    source = _dataset() if dataset is None else dataset
    return build_chronological_split_manifest(
        source,
        train_end=BASE + timedelta(days=12),
        dev_end=BASE + timedelta(days=24),
        calibration_end=BASE + timedelta(days=36),
        holdout_end=BASE + timedelta(days=52),
        purge_minutes=720,
        embargo_minutes=720,
        holdout_identity=HOLDOUT_IDENTITY,
    )


def _trial(*, purpose: str = "evaluation") -> dict[str, object]:
    return preregister_trial(
        [],
        trial_number=1,
        hypothesis="Frozen V2 replay improves unseen decision quality.",
        null_hypothesis="Frozen V2 replay does not improve unseen decision quality.",
        dataset_version=DATASET_VERSION,
        feature_context_version="context-v7",
        frozen_parameters={"composer": "v2", "self_consistency_k": 3},
        chronological_split={
            "train_end": (BASE + timedelta(days=12)).date().isoformat(),
            "dev_end": (BASE + timedelta(days=24)).date().isoformat(),
            "calibration_end": (BASE + timedelta(days=36)).date().isoformat(),
            "holdout_end": (BASE + timedelta(days=52)).date().isoformat(),
        },
        purge="12h",
        embargo="12h",
        evaluation_identity="day37-evaluation-v1",
        holdout_identity=HOLDOUT_IDENTITY,
        preregistered_at=NOW,
        code_head=HEAD,
        evidence_digest="e" * 64,
        purpose=purpose,  # type: ignore[arg-type]
    )


def test_harness_manifest_freezes_scientific_boundaries() -> None:
    manifest = replay_harness_manifest()
    assert manifest["chronological_train_dev_calibration_holdout_required"] is True
    assert manifest["purge_required"] is True
    assert manifest["embargo_required"] is True
    assert manifest["cpcv_pre_holdout_only"] is True
    assert manifest["day32_trial_registry_required"] is True
    assert manifest["holdout_tuning_allowed"] is False
    assert manifest["future_first_observation_allowed_at_t"] is False
    assert manifest["telegram_side_effects_allowed"] is False
    assert manifest["broker_side_effects_allowed"] is False
    assert manifest["super_signals_side_effects_allowed"] is False


def test_dataset_manifest_is_deterministic_case_sorted_and_digest_verified() -> None:
    cases = list(reversed(_cases()))
    first = _dataset(cases)
    second = _dataset(copy.deepcopy(cases))
    assert first == second
    assert verify_frozen_dataset_manifest(first)
    assert first["case_ids"] == sorted(
        first["case_ids"], key=lambda case_id: int(case_id.split("-")[-1])
    )


def test_dataset_manifest_rejects_duplicate_and_tampered_cases() -> None:
    cases = _cases()
    with pytest.raises(ReplayIntegrityError, match="duplicate"):
        _dataset(cases + [copy.deepcopy(cases[0])])
    changed = copy.deepcopy(cases)
    changed[0]["future_evaluation"]["available_after_utc"] = BASE.isoformat()
    with pytest.raises(ReplayIntegrityError, match="invalid historical case"):
        _dataset(changed)


def test_dataset_manifest_tampering_fails_verification() -> None:
    manifest = _dataset()
    changed = copy.deepcopy(manifest)
    changed["cases"][0]["input_digest"] = "0" * 64
    assert verify_frozen_dataset_manifest(changed) is False


def test_replay_rejects_evidence_first_observed_after_t() -> None:
    rows = [
        {
            "field_identity": "price:spot",
            "first_observed_timestamp": (NOW - timedelta(seconds=1)).isoformat(),
            "decision_input_eligible": True,
        },
        {
            "field_identity": "future:revision",
            "first_observed_timestamp": (NOW + timedelta(seconds=1)).isoformat(),
            "decision_input_eligible": True,
        },
    ]
    with pytest.raises(ReplayIntegrityError, match="after T"):
        assert_replay_evidence_known_at_t(rows, as_of=NOW)


def test_replay_rejects_non_decision_eligible_evidence_even_when_known() -> None:
    with pytest.raises(ReplayIntegrityError, match="not decision-input eligible"):
        assert_replay_evidence_known_at_t(
            [
                {
                    "first_observed_timestamp": (NOW - timedelta(days=1)).isoformat(),
                    "decision_input_eligible": False,
                }
            ],
            as_of=NOW,
        )


def test_chronological_split_is_deterministic_disjoint_and_holdout_frozen() -> None:
    dataset = _dataset()
    first = _split(dataset)
    second = _split(copy.deepcopy(dataset))
    assert first == second
    assert verify_chronological_split_manifest(first, dataset)
    ids = []
    for split_name in ("train", "dev", "calibration", "holdout"):
        ids.extend(first["splits"][split_name])
    assert len(ids) == len(set(ids))
    assert first["holdout_case_ids"] == first["splits"]["holdout"]
    assert first["holdout_tuning_allowed"] is False


def test_split_embargo_removes_cases_immediately_after_each_boundary() -> None:
    cases = _cases()
    cases.extend(
        [
            _case(100, as_of=BASE + timedelta(days=12, hours=6)),
            _case(101, as_of=BASE + timedelta(days=24, hours=6)),
            _case(102, as_of=BASE + timedelta(days=36, hours=6)),
        ]
    )
    split = _split(_dataset(cases))
    assert "case-100" in split["embargoed_from_split_start"]["dev"]
    assert "case-101" in split["embargoed_from_split_start"]["calibration"]
    assert "case-102" in split["embargoed_from_split_start"]["holdout"]


def test_split_purges_prior_labels_that_overlap_or_enter_purge_buffer() -> None:
    cases = _cases()
    overlap = _case(
        110,
        as_of=BASE + timedelta(days=11, hours=12),
        horizon_hours=18,
    )
    buffer_only = _case(
        111,
        as_of=BASE + timedelta(days=10, hours=18),
        horizon_hours=12,
    )
    cases.extend([overlap, buffer_only])
    split = _split(_dataset(cases))
    purged = set(split["purged_from_prior"]["train_before_dev"])
    assert "case-110" in purged
    assert "case-111" in purged
    assert "case-110" not in split["splits"]["train"]
    assert "case-111" not in split["splits"]["train"]


def test_invalid_or_non_increasing_boundaries_fail_closed() -> None:
    dataset = _dataset()
    with pytest.raises(ReplayIntegrityError, match="strictly increasing"):
        build_chronological_split_manifest(
            dataset,
            train_end=BASE + timedelta(days=12),
            dev_end=BASE + timedelta(days=12),
            calibration_end=BASE + timedelta(days=36),
            holdout_end=BASE + timedelta(days=52),
            purge_minutes=720,
            embargo_minutes=720,
            holdout_identity=HOLDOUT_IDENTITY,
        )


def test_cpcv_is_deterministic_purged_and_never_touches_holdout() -> None:
    dataset = _dataset()
    split = _split(dataset)
    first = build_cpcv_manifest(dataset, split, group_count=4, test_group_count=1)
    second = build_cpcv_manifest(copy.deepcopy(dataset), copy.deepcopy(split), group_count=4)
    assert first == second
    assert verify_cpcv_manifest(first, dataset, split)
    holdout = set(split["holdout_case_ids"])
    assert first["fold_count"] == 4
    for fold in first["folds"]:
        assert not holdout.intersection(fold["train_case_ids"])
        assert not holdout.intersection(fold["test_case_ids"])
        assert not set(fold["train_case_ids"]).intersection(fold["test_case_ids"])
        assert fold["holdout_case_ids_used"] == []


def test_cpcv_tampering_is_detected() -> None:
    dataset = _dataset()
    split = _split(dataset)
    cpcv = build_cpcv_manifest(dataset, split)
    changed = copy.deepcopy(cpcv)
    changed["folds"][0]["train_case_ids"].append(split["holdout_case_ids"][0])
    assert verify_cpcv_manifest(changed, dataset, split) is False


def test_replay_experiment_is_bound_to_day32_trial_dataset_split_cpcv_and_config() -> None:
    dataset = _dataset()
    split = _split(dataset)
    cpcv = build_cpcv_manifest(dataset, split)
    trial = _trial()
    first = build_replay_experiment_manifest(
        trial_record=trial,
        dataset_manifest=dataset,
        split_manifest=split,
        cpcv_manifest=cpcv,
        frozen_version_digest="v" * 64,
        frozen_configuration={"composer": "v2", "self_consistency_k": 3},
        created_at=NOW,
    )
    second = build_replay_experiment_manifest(
        trial_record=copy.deepcopy(trial),
        dataset_manifest=copy.deepcopy(dataset),
        split_manifest=copy.deepcopy(split),
        cpcv_manifest=copy.deepcopy(cpcv),
        frozen_version_digest="v" * 64,
        frozen_configuration={"self_consistency_k": 3, "composer": "v2"},
        created_at=NOW,
    )
    assert first == second
    assert verify_replay_experiment_manifest(
        first,
        trial_record=trial,
        dataset_manifest=dataset,
        split_manifest=split,
        cpcv_manifest=cpcv,
    )
    assert first["trial_digest"] == trial["trial_digest"]
    assert first["holdout_access_allowed"] is True
    assert first["holdout_tuning_allowed"] is False


def test_tuning_trial_experiment_cannot_gain_holdout_access() -> None:
    dataset = _dataset()
    split = _split(dataset)
    cpcv = build_cpcv_manifest(dataset, split)
    experiment = build_replay_experiment_manifest(
        trial_record=_trial(purpose="tuning"),
        dataset_manifest=dataset,
        split_manifest=split,
        cpcv_manifest=cpcv,
        frozen_version_digest="v" * 64,
        frozen_configuration={"threshold": "frozen"},
        created_at=NOW,
    )
    assert experiment["holdout_access_allowed"] is False
    assert experiment["holdout_tuning_allowed"] is False


def test_holdout_access_is_logged_only_for_evaluation_trial_and_frozen_ids() -> None:
    dataset = _dataset()
    split = _split(dataset)
    trial = _trial()
    holdout_ids = split["holdout_case_ids"][:2]
    record = build_holdout_access_record(
        trial_record=trial,
        dataset_manifest=dataset,
        split_manifest=split,
        frozen_version_digest="v" * 64,
        accessed_case_ids=holdout_ids,
        accessed_at=NOW,
        score_digest="s" * 64,
    )
    assert verify_holdout_access_record(record)
    assert record["tuning_allowed_after_access"] is False
    assert record["same_holdout_reusable_for_tuning"] is False
    assert record["silent_promotion_allowed"] is False
    assert record["new_trial_required_for_changes"] is True

    with pytest.raises(ReplayIntegrityError, match="tuning trials"):
        build_holdout_access_record(
            trial_record=_trial(purpose="tuning"),
            dataset_manifest=dataset,
            split_manifest=split,
            frozen_version_digest="v" * 64,
            accessed_case_ids=holdout_ids,
            accessed_at=NOW,
        )


def test_holdout_access_cannot_name_non_holdout_case() -> None:
    dataset = _dataset()
    split = _split(dataset)
    with pytest.raises(ReplayIntegrityError, match="only frozen holdout"):
        build_holdout_access_record(
            trial_record=_trial(),
            dataset_manifest=dataset,
            split_manifest=split,
            frozen_version_digest="v" * 64,
            accessed_case_ids=[split["splits"]["train"][0]],
            accessed_at=NOW,
        )


def test_replay_score_record_freezes_inputs_retrievals_decisions_and_scores() -> None:
    dataset = _dataset()
    split = _split(dataset)
    ids = split["splits"]["dev"][:2]
    scores = [
        {
            "case_id": ids[1],
            "input_digest": "i" * 64,
            "retrieval_digest": "r" * 64,
            "decision_digest": "d" * 64,
            "score": {"correct": False, "loss": "1"},
        },
        {
            "case_id": ids[0],
            "input_digest": "j" * 64,
            "retrieval_digest": "q" * 64,
            "decision_digest": "e" * 64,
            "score": {"correct": True, "loss": "0"},
        },
    ]
    first = build_replay_score_record(
        trial_record=_trial(),
        dataset_manifest=dataset,
        split_manifest=split,
        frozen_version_digest="v" * 64,
        evaluation_split="dev",
        case_scores=scores,
    )
    second = build_replay_score_record(
        trial_record=_trial(),
        dataset_manifest=copy.deepcopy(dataset),
        split_manifest=copy.deepcopy(split),
        frozen_version_digest="v" * 64,
        evaluation_split="dev",
        case_scores=list(reversed(copy.deepcopy(scores))),
    )
    assert first == second
    assert verify_replay_score_record(first)
    assert first["inputs_retrievals_and_scores_frozen"] is True


def test_score_record_rejects_case_from_wrong_split_and_tampering() -> None:
    dataset = _dataset()
    split = _split(dataset)
    with pytest.raises(ReplayIntegrityError, match="outside the frozen dev"):
        build_replay_score_record(
            trial_record=_trial(),
            dataset_manifest=dataset,
            split_manifest=split,
            frozen_version_digest="v" * 64,
            evaluation_split="dev",
            case_scores=[
                {
                    "case_id": split["holdout_case_ids"][0],
                    "input_digest": "i" * 64,
                    "retrieval_digest": "r" * 64,
                    "decision_digest": "d" * 64,
                    "score": {"correct": True},
                }
            ],
        )

    valid = build_replay_score_record(
        trial_record=_trial(),
        dataset_manifest=dataset,
        split_manifest=split,
        frozen_version_digest="v" * 64,
        evaluation_split="dev",
        case_scores=[
            {
                "case_id": split["splits"]["dev"][0],
                "input_digest": "i" * 64,
                "retrieval_digest": "r" * 64,
                "decision_digest": "d" * 64,
                "score": {"correct": True},
            }
        ],
    )
    changed = copy.deepcopy(valid)
    changed["case_scores"][0]["score"] = {"correct": False}
    assert verify_replay_score_record(changed) is False
