from __future__ import annotations

import copy
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from aidy.replay_evaluation import (
    REPLAY_HARNESS_VERSION,
    ReplayIntegrityError,
    SplitName,
    build_holdout_access_record,
    build_replay_score_record,
    digest,
    verify_chronological_split_manifest,
    verify_frozen_dataset_manifest,
    verify_holdout_access_record,
    verify_replay_score_record,
)
from aidy.research_integrity import verify_trial_record

REPLAY_SCORING_GUARD_VERSION = "aidy_trial_bound_replay_scoring_v1"


def _dataset_rows(dataset_manifest: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(row["case_id"]): dict(row)
        for row in dataset_manifest["cases"]
        if isinstance(row, Mapping)
    }


def build_trial_bound_replay_score(
    *,
    trial_record: Mapping[str, Any],
    dataset_manifest: Mapping[str, Any],
    split_manifest: Mapping[str, Any],
    frozen_version_digest: str,
    evaluation_split: SplitName,
    case_scores: Iterable[Mapping[str, Any]],
    accessed_at: datetime | str | None = None,
) -> dict[str, Any]:
    """Build a replay score with frozen-input binding and mandatory holdout logging."""

    if not verify_trial_record(trial_record):
        raise ReplayIntegrityError("A valid Day-32 trial record is required.")
    if not verify_frozen_dataset_manifest(dataset_manifest):
        raise ReplayIntegrityError("A valid frozen dataset manifest is required.")
    if not verify_chronological_split_manifest(split_manifest, dataset_manifest):
        raise ReplayIntegrityError("A valid chronological split manifest is required.")
    if trial_record.get("dataset_version") != dataset_manifest.get("dataset_version"):
        raise ReplayIntegrityError("Trial dataset version does not match replay dataset.")
    if trial_record.get("holdout_identity") != split_manifest.get("holdout_identity"):
        raise ReplayIntegrityError("Trial holdout identity does not match replay split.")
    if trial_record.get("code_head") != dataset_manifest.get("code_head"):
        raise ReplayIntegrityError("Trial code head does not match replay dataset code head.")
    if evaluation_split == "holdout" and trial_record.get("purpose") != "evaluation":
        raise ReplayIntegrityError("Tuning trials cannot score the frozen holdout.")
    if evaluation_split == "holdout" and accessed_at is None:
        raise ReplayIntegrityError("Holdout scoring requires an explicit access timestamp.")

    rows_by_id = _dataset_rows(dataset_manifest)
    normalized_scores: list[dict[str, Any]] = []
    for raw in case_scores:
        if not isinstance(raw, Mapping):
            raise TypeError("case_scores entries must be mappings.")
        row = copy.deepcopy(dict(raw))
        case_id = str(row.get("case_id") or "")
        frozen = rows_by_id.get(case_id)
        if frozen is None:
            raise ReplayIntegrityError(f"Replay score references unknown frozen case: {case_id}")
        if row.get("input_digest") != frozen.get("input_digest"):
            raise ReplayIntegrityError(
                f"Replay input digest does not match frozen dataset case: {case_id}"
            )
        normalized_scores.append(row)

    score = build_replay_score_record(
        trial_record=trial_record,
        dataset_manifest=dataset_manifest,
        split_manifest=split_manifest,
        frozen_version_digest=frozen_version_digest,
        evaluation_split=evaluation_split,
        case_scores=normalized_scores,
    )
    access = None
    if evaluation_split == "holdout":
        access = build_holdout_access_record(
            trial_record=trial_record,
            dataset_manifest=dataset_manifest,
            split_manifest=split_manifest,
            frozen_version_digest=frozen_version_digest,
            accessed_case_ids=[str(row["case_id"]) for row in normalized_scores],
            accessed_at=accessed_at,  # type: ignore[arg-type]
            score_digest=str(score["score_digest"]),
        )

    result: dict[str, Any] = {
        "guard_version": REPLAY_SCORING_GUARD_VERSION,
        "harness_version": REPLAY_HARNESS_VERSION,
        "trial_identity": trial_record["trial_identity"],
        "trial_digest": trial_record["trial_digest"],
        "dataset_manifest_digest": dataset_manifest["manifest_digest"],
        "split_digest": split_manifest["split_digest"],
        "frozen_version_digest": frozen_version_digest,
        "evaluation_split": evaluation_split,
        "score_record": score,
        "holdout_access_record": access,
        "input_digest_bound_to_frozen_case": True,
        "holdout_access_mandatory_for_holdout_score": True,
        "tuning_holdout_score_allowed": False,
    }
    result["guard_digest"] = digest(result)
    return result


def verify_trial_bound_replay_score(result: Mapping[str, Any]) -> bool:
    if not isinstance(result, Mapping):
        return False
    body = copy.deepcopy(dict(result))
    supplied = str(body.pop("guard_digest", ""))
    try:
        if body.get("guard_version") != REPLAY_SCORING_GUARD_VERSION:
            return False
        if body.get("input_digest_bound_to_frozen_case") is not True:
            return False
        if body.get("holdout_access_mandatory_for_holdout_score") is not True:
            return False
        if body.get("tuning_holdout_score_allowed") is not False:
            return False
        if not verify_replay_score_record(body["score_record"]):
            return False
        access = body.get("holdout_access_record")
        if body.get("evaluation_split") == "holdout":
            if not isinstance(access, Mapping) or not verify_holdout_access_record(access):
                return False
            if access.get("score_digest") != body["score_record"].get("score_digest"):
                return False
            if access.get("frozen_version_digest") != body.get("frozen_version_digest"):
                return False
        elif access is not None:
            return False
    except (KeyError, TypeError, ValueError):
        return False
    return bool(supplied) and supplied == digest(body)
