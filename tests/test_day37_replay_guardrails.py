from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta

import pytest

from aidy.historical_cases import CASE_VERSION, compute_historical_case_digest
from aidy.replay_evaluation import (
    ReplayIntegrityError,
    build_chronological_split_manifest,
    build_cpcv_manifest,
    build_frozen_dataset_manifest,
)
from aidy.replay_experiment import build_replay_experiment_manifest
from aidy.replay_scoring import (
    build_trial_bound_replay_score,
    verify_trial_bound_replay_score,
)
from aidy.research_integrity import preregister_trial

BASE = datetime(2025, 2, 1, tzinfo=UTC)
NOW = datetime(2026, 9, 1, 5, 15, tzinfo=UTC)
HEAD = "d988a4ff29160e2d10a32e6c151d028001e941f2"
DATASET_VERSION = "day37-guard-dataset-v1"
HOLDOUT_IDENTITY = "day37-guard-holdout-v1"
CONFIG = {"composer": "v2", "self_consistency_k": 3}


def _case(index: int, day: int) -> dict[str, object]:
    as_of = BASE + timedelta(days=day)
    case: dict[str, object] = {
        "case_version": CASE_VERSION,
        "case_id": f"guard-case-{index:03d}",
        "symbol": "XAUUSD",
        "as_of_utc": as_of.isoformat(),
        "provenance_class": "retrospective_history",
        "decision_input_allowed": False,
        "input_boundary": {
            "input_version": "guard-fixture-v1",
            "input_digest": f"{index + 100:064x}",
            "as_of_utc": as_of.isoformat(),
            "future_derived": False,
        },
        "future_evaluation": {
            "evaluation_only": True,
            "decision_input_allowed": False,
            "future_derived": True,
            "available_after_utc": (as_of + timedelta(hours=1)).isoformat(),
        },
    }
    case["case_digest"] = compute_historical_case_digest(case)
    return case


def _dataset() -> dict[str, object]:
    return build_frozen_dataset_manifest(
        [_case(index, index + 1) for index in range(20)],
        dataset_version=DATASET_VERSION,
        source_snapshot_identity="r2/day37/guard-snapshot",
        code_head=HEAD,
    )


def _split(dataset: dict[str, object]) -> dict[str, object]:
    return build_chronological_split_manifest(
        dataset,
        train_end=BASE + timedelta(days=5),
        dev_end=BASE + timedelta(days=10),
        calibration_end=BASE + timedelta(days=15),
        holdout_end=BASE + timedelta(days=21),
        purge_minutes=60,
        embargo_minutes=60,
        holdout_identity=HOLDOUT_IDENTITY,
    )


def _trial(
    *,
    purpose: str = "evaluation",
    config: dict[str, object] | None = None,
    purge: str = "1h",
    embargo: str = "1h",
    train_end: str | None = None,
    code_head: str = HEAD,
) -> dict[str, object]:
    return preregister_trial(
        [],
        trial_number=1,
        hypothesis="Frozen replay generalizes to unseen chronology.",
        null_hypothesis="Frozen replay does not generalize to unseen chronology.",
        dataset_version=DATASET_VERSION,
        feature_context_version="context-v7",
        frozen_parameters=CONFIG if config is None else config,
        chronological_split={
            "train_end": train_end or (BASE + timedelta(days=5)).date().isoformat(),
            "dev_end": (BASE + timedelta(days=10)).date().isoformat(),
            "calibration_end": (BASE + timedelta(days=15)).date().isoformat(),
            "holdout_end": (BASE + timedelta(days=21)).date().isoformat(),
        },
        purge=purge,
        embargo=embargo,
        evaluation_identity="day37-guard-evaluation-v1",
        holdout_identity=HOLDOUT_IDENTITY,
        preregistered_at=NOW,
        code_head=code_head,
        evidence_digest="e" * 64,
        purpose=purpose,  # type: ignore[arg-type]
    )


def _experiment(
    trial: dict[str, object],
    *,
    config: dict[str, object] | None = None,
) -> dict[str, object]:
    dataset = _dataset()
    split = _split(dataset)
    cpcv = build_cpcv_manifest(dataset, split, group_count=3)
    return build_replay_experiment_manifest(
        trial_record=trial,
        dataset_manifest=dataset,
        split_manifest=split,
        cpcv_manifest=cpcv,
        frozen_version_digest="v" * 64,
        frozen_configuration=CONFIG if config is None else config,
        created_at=NOW,
    )


def _score_row(dataset: dict[str, object], case_id: str) -> dict[str, object]:
    frozen = next(row for row in dataset["cases"] if row["case_id"] == case_id)
    return {
        "case_id": case_id,
        "input_digest": frozen["input_digest"],
        "retrieval_digest": "r" * 64,
        "decision_digest": "d" * 64,
        "score": {"correct": True, "loss": "0"},
    }


def test_experiment_rejects_configuration_drift_from_preregistration() -> None:
    with pytest.raises(ReplayIntegrityError, match="configuration drifted"):
        _experiment(_trial(), config={"composer": "v2", "self_consistency_k": 5})


def test_experiment_rejects_split_purge_and_code_head_drift() -> None:
    with pytest.raises(ReplayIntegrityError, match="boundary drift"):
        _experiment(_trial(train_end=(BASE + timedelta(days=4)).date().isoformat()))
    with pytest.raises(ReplayIntegrityError, match="purge duration drifted"):
        _experiment(_trial(purge="2h"))
    with pytest.raises(ReplayIntegrityError, match="code head"):
        _experiment(_trial(code_head="f" * 40))


def test_trial_bound_score_rejects_input_digest_not_bound_to_frozen_case() -> None:
    dataset = _dataset()
    split = _split(dataset)
    case_id = split["splits"]["dev"][0]
    row = _score_row(dataset, case_id)
    row["input_digest"] = "0" * 64
    with pytest.raises(ReplayIntegrityError, match="input digest"):
        build_trial_bound_replay_score(
            trial_record=_trial(),
            dataset_manifest=dataset,
            split_manifest=split,
            frozen_version_digest="v" * 64,
            evaluation_split="dev",
            case_scores=[row],
        )


def test_tuning_trial_cannot_score_holdout_even_via_scoring_surface() -> None:
    dataset = _dataset()
    split = _split(dataset)
    case_id = split["holdout_case_ids"][0]
    with pytest.raises(ReplayIntegrityError, match="Tuning trials cannot score"):
        build_trial_bound_replay_score(
            trial_record=_trial(purpose="tuning"),
            dataset_manifest=dataset,
            split_manifest=split,
            frozen_version_digest="v" * 64,
            evaluation_split="holdout",
            case_scores=[_score_row(dataset, case_id)],
            accessed_at=NOW,
        )


def test_holdout_score_requires_and_creates_digest_linked_access_record() -> None:
    dataset = _dataset()
    split = _split(dataset)
    case_id = split["holdout_case_ids"][0]
    row = _score_row(dataset, case_id)
    with pytest.raises(ReplayIntegrityError, match="access timestamp"):
        build_trial_bound_replay_score(
            trial_record=_trial(),
            dataset_manifest=dataset,
            split_manifest=split,
            frozen_version_digest="v" * 64,
            evaluation_split="holdout",
            case_scores=[row],
        )

    result = build_trial_bound_replay_score(
        trial_record=_trial(),
        dataset_manifest=dataset,
        split_manifest=split,
        frozen_version_digest="v" * 64,
        evaluation_split="holdout",
        case_scores=[row],
        accessed_at=NOW,
    )
    assert verify_trial_bound_replay_score(result)
    assert result["holdout_access_record"]["score_digest"] == result["score_record"]["score_digest"]
    assert result["holdout_access_record"]["accessed_case_ids"] == [case_id]
    assert result["tuning_holdout_score_allowed"] is False


def test_guarded_score_digest_detects_access_or_score_tampering() -> None:
    dataset = _dataset()
    split = _split(dataset)
    case_id = split["holdout_case_ids"][0]
    result = build_trial_bound_replay_score(
        trial_record=_trial(),
        dataset_manifest=dataset,
        split_manifest=split,
        frozen_version_digest="v" * 64,
        evaluation_split="holdout",
        case_scores=[_score_row(dataset, case_id)],
        accessed_at=NOW,
    )
    changed = copy.deepcopy(result)
    changed["holdout_access_record"]["score_digest"] = "0" * 64
    assert verify_trial_bound_replay_score(changed) is False
