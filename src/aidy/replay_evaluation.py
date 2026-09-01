from __future__ import annotations

import copy
import itertools
import json
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any, Literal

from aidy.historical_cases import CASE_VERSION, verify_historical_case_digest
from aidy.research_integrity import TRIAL_REGISTRY_VERSION, verify_trial_record

REPLAY_HARNESS_VERSION = "aidy_frozen_replay_cpcv_v1"
DATASET_MANIFEST_VERSION = "aidy_replay_dataset_manifest_v1"
SPLIT_MANIFEST_VERSION = "aidy_chronological_split_manifest_v1"
CPCV_MANIFEST_VERSION = "aidy_purged_combinatorial_cv_manifest_v1"
HOLDOUT_ACCESS_VERSION = "aidy_holdout_access_log_v1"
REPLAY_SCORE_VERSION = "aidy_replay_score_record_v1"
DIGEST_ALGORITHM = "sha256"

SplitName = Literal["train", "dev", "calibration", "holdout"]
_SPLIT_ORDER: tuple[SplitName, ...] = ("train", "dev", "calibration", "holdout")


class ReplayIntegrityError(ValueError):
    pass


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest(value: object) -> str:
    return sha256(canonical_json(value).encode()).hexdigest()


def _utc(value: datetime | str, *, name: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip())
        except ValueError as exc:
            raise ReplayIntegrityError(f"{name} must be timezone-aware ISO-8601 text.") from exc
    else:
        raise TypeError(f"{name} must be a timezone-aware datetime or ISO-8601 string.")
    if parsed.tzinfo is None:
        raise ReplayIntegrityError(f"{name} must be timezone-aware.")
    return parsed.astimezone(UTC)


def _text(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"{name} must be non-empty text.")
    return value.strip()


def _case_row(case: Mapping[str, Any]) -> dict[str, Any]:
    if case.get("case_version") != CASE_VERSION or not verify_historical_case_digest(case):
        raise ReplayIntegrityError("Replay dataset contains an invalid historical case.")
    case_id = _text(case.get("case_id"), name="case_id")
    case_digest = _text(case.get("case_digest"), name="case_digest")
    as_of = _utc(case.get("as_of_utc"), name=f"case[{case_id}].as_of_utc")
    future = case.get("future_evaluation")
    if not isinstance(future, Mapping):
        raise ReplayIntegrityError(f"case {case_id} lacks isolated future_evaluation.")
    if future.get("evaluation_only") is not True or future.get("decision_input_allowed") is not False:
        raise ReplayIntegrityError(f"case {case_id} future evaluation is not isolated from decisions.")
    available = _utc(
        future.get("available_after_utc"), name=f"case[{case_id}].future_available_after_utc"
    )
    if available <= as_of:
        raise ReplayIntegrityError(f"case {case_id} future evaluation must become available after T.")
    boundary = case.get("input_boundary")
    if not isinstance(boundary, Mapping):
        raise ReplayIntegrityError(f"case {case_id} lacks input_boundary.")
    input_digest = _text(boundary.get("input_digest"), name="input_boundary.input_digest")
    return {
        "case_id": case_id,
        "case_digest": case_digest,
        "input_digest": input_digest,
        "as_of_utc": as_of.isoformat(),
        "future_available_after_utc": available.isoformat(),
        "provenance_class": case.get("provenance_class"),
    }


def build_frozen_dataset_manifest(
    cases: Iterable[Mapping[str, Any]],
    *,
    dataset_version: str,
    source_snapshot_identity: str,
    code_head: str,
) -> dict[str, Any]:
    rows = [_case_row(case) for case in cases]
    rows.sort(key=lambda row: (row["as_of_utc"], row["case_id"]))
    identities = [row["case_id"] for row in rows]
    if not rows:
        raise ReplayIntegrityError("Replay dataset cannot be empty.")
    if len(identities) != len(set(identities)):
        raise ReplayIntegrityError("Replay dataset contains duplicate case identities.")
    manifest: dict[str, Any] = {
        "manifest_version": DATASET_MANIFEST_VERSION,
        "harness_version": REPLAY_HARNESS_VERSION,
        "dataset_version": _text(dataset_version, name="dataset_version"),
        "source_snapshot_identity": _text(
            source_snapshot_identity, name="source_snapshot_identity"
        ),
        "code_head": _text(code_head, name="code_head"),
        "case_count": len(rows),
        "case_ids": identities,
        "cases": rows,
        "first_case_as_of_utc": rows[0]["as_of_utc"],
        "last_case_as_of_utc": rows[-1]["as_of_utc"],
        "immutable": True,
    }
    manifest["manifest_digest"] = digest(manifest)
    return manifest


def verify_frozen_dataset_manifest(manifest: Mapping[str, Any]) -> bool:
    if not isinstance(manifest, Mapping):
        return False
    body = copy.deepcopy(dict(manifest))
    supplied = str(body.pop("manifest_digest", ""))
    try:
        rows = body["cases"]
        if body.get("manifest_version") != DATASET_MANIFEST_VERSION or body.get("immutable") is not True:
            return False
        if not isinstance(rows, list) or body.get("case_count") != len(rows) or not rows:
            return False
        ids = [str(row["case_id"]) for row in rows]
        if ids != body.get("case_ids") or len(ids) != len(set(ids)):
            return False
        ordered = sorted(rows, key=lambda row: (row["as_of_utc"], row["case_id"]))
        if rows != ordered:
            return False
        for row in rows:
            if _utc(row["future_available_after_utc"], name="future_available_after_utc") <= _utc(
                row["as_of_utc"], name="as_of_utc"
            ):
                return False
    except (KeyError, TypeError, ValueError):
        return False
    return bool(supplied) and supplied == digest(body)


def assert_replay_evidence_known_at_t(
    evidence_rows: Iterable[Mapping[str, Any]], *, as_of: datetime | str
) -> list[dict[str, Any]]:
    """Fail closed if any model-facing replay evidence was first observed after T."""

    decision_time = _utc(as_of, name="as_of")
    verified: list[dict[str, Any]] = []
    for index, raw in enumerate(evidence_rows):
        if not isinstance(raw, Mapping):
            raise TypeError(f"evidence_rows[{index}] must be a mapping.")
        row = copy.deepcopy(dict(raw))
        first_observed = _utc(
            row.get("first_observed_timestamp"),
            name=f"evidence_rows[{index}].first_observed_timestamp",
        )
        if first_observed > decision_time:
            raise ReplayIntegrityError(
                f"Replay evidence first observed after T is forbidden: evidence_rows[{index}]"
            )
        if row.get("decision_input_eligible") is not True:
            raise ReplayIntegrityError(
                f"Replay evidence not decision-input eligible: evidence_rows[{index}]"
            )
        verified.append(row)
    return verified


def _duration_minutes(value: int, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ReplayIntegrityError(f"{name} must be a non-negative integer number of minutes.")
    return value


def _boundaries(
    *,
    train_end: datetime | str,
    dev_end: datetime | str,
    calibration_end: datetime | str,
    holdout_end: datetime | str,
) -> dict[str, datetime]:
    result = {
        "train_end": _utc(train_end, name="train_end"),
        "dev_end": _utc(dev_end, name="dev_end"),
        "calibration_end": _utc(calibration_end, name="calibration_end"),
        "holdout_end": _utc(holdout_end, name="holdout_end"),
    }
    ordered = list(result.values())
    if ordered != sorted(ordered) or len(set(ordered)) != len(ordered):
        raise ReplayIntegrityError("Chronological split boundaries must be strictly increasing.")
    return result


def _nominal_split(as_of: datetime, boundaries: Mapping[str, datetime]) -> SplitName | None:
    if as_of <= boundaries["train_end"]:
        return "train"
    if as_of <= boundaries["dev_end"]:
        return "dev"
    if as_of <= boundaries["calibration_end"]:
        return "calibration"
    if as_of <= boundaries["holdout_end"]:
        return "holdout"
    return None


def build_chronological_split_manifest(
    dataset_manifest: Mapping[str, Any],
    *,
    train_end: datetime | str,
    dev_end: datetime | str,
    calibration_end: datetime | str,
    holdout_end: datetime | str,
    purge_minutes: int,
    embargo_minutes: int,
    holdout_identity: str,
) -> dict[str, Any]:
    if not verify_frozen_dataset_manifest(dataset_manifest):
        raise ReplayIntegrityError("A valid frozen dataset manifest is required.")
    boundaries = _boundaries(
        train_end=train_end,
        dev_end=dev_end,
        calibration_end=calibration_end,
        holdout_end=holdout_end,
    )
    purge = _duration_minutes(purge_minutes, name="purge_minutes")
    embargo = _duration_minutes(embargo_minutes, name="embargo_minutes")
    nominal: dict[SplitName, list[dict[str, Any]]] = {name: [] for name in _SPLIT_ORDER}
    unused: list[str] = []
    for row in dataset_manifest["cases"]:
        as_of = _utc(row["as_of_utc"], name="case.as_of_utc")
        split = _nominal_split(as_of, boundaries)
        if split is None:
            unused.append(str(row["case_id"]))
        else:
            nominal[split].append(dict(row))

    starts: dict[SplitName, datetime | None] = {
        "train": None,
        "dev": boundaries["train_end"],
        "calibration": boundaries["dev_end"],
        "holdout": boundaries["calibration_end"],
    }
    retained: dict[SplitName, list[str]] = {name: [] for name in _SPLIT_ORDER}
    embargoed: dict[SplitName, list[str]] = {name: [] for name in _SPLIT_ORDER}
    for split in _SPLIT_ORDER:
        boundary = starts[split]
        for row in nominal[split]:
            as_of = _utc(row["as_of_utc"], name="case.as_of_utc")
            if boundary is not None and as_of <= boundary + timedelta(minutes=embargo):
                embargoed[split].append(str(row["case_id"]))
            else:
                retained[split].append(str(row["case_id"]))

    purged_from_prior: dict[str, list[str]] = {}
    for prior, next_split, boundary_key in (
        ("train", "dev", "train_end"),
        ("dev", "calibration", "dev_end"),
        ("calibration", "holdout", "calibration_end"),
    ):
        boundary = boundaries[boundary_key]
        overlap_cutoff = boundary + timedelta(minutes=purge)
        ids = [
            str(row["case_id"])
            for row in nominal[prior]
            if _utc(row["future_available_after_utc"], name="future_available_after_utc")
            > overlap_cutoff
        ]
        purged_from_prior[f"{prior}_before_{next_split}"] = ids
        if ids:
            retained[prior] = [case_id for case_id in retained[prior] if case_id not in set(ids)]

    manifest: dict[str, Any] = {
        "manifest_version": SPLIT_MANIFEST_VERSION,
        "harness_version": REPLAY_HARNESS_VERSION,
        "dataset_manifest_digest": dataset_manifest["manifest_digest"],
        "dataset_version": dataset_manifest["dataset_version"],
        "boundaries": {key: value.isoformat() for key, value in boundaries.items()},
        "purge_minutes": purge,
        "embargo_minutes": embargo,
        "holdout_identity": _text(holdout_identity, name="holdout_identity"),
        "splits": {name: retained[name] for name in _SPLIT_ORDER},
        "nominal_splits": {
            name: [str(row["case_id"]) for row in nominal[name]] for name in _SPLIT_ORDER
        },
        "purged_from_prior": purged_from_prior,
        "embargoed_from_split_start": embargoed,
        "unused_case_ids": unused,
        "holdout_case_ids": retained["holdout"],
        "holdout_tuning_allowed": False,
        "side_effects_allowed": False,
        "telegram_allowed": False,
        "broker_allowed": False,
        "super_signals_allowed": False,
    }
    manifest["split_digest"] = digest(manifest)
    return manifest


def verify_chronological_split_manifest(
    manifest: Mapping[str, Any], dataset_manifest: Mapping[str, Any]
) -> bool:
    if not verify_frozen_dataset_manifest(dataset_manifest) or not isinstance(manifest, Mapping):
        return False
    body = copy.deepcopy(dict(manifest))
    supplied = str(body.pop("split_digest", ""))
    try:
        if body.get("manifest_version") != SPLIT_MANIFEST_VERSION:
            return False
        if body.get("dataset_manifest_digest") != dataset_manifest["manifest_digest"]:
            return False
        if body.get("holdout_tuning_allowed") is not False or body.get("side_effects_allowed") is not False:
            return False
        all_ids: list[str] = []
        for name in _SPLIT_ORDER:
            ids = list(body["splits"][name])
            if len(ids) != len(set(ids)):
                return False
            all_ids.extend(ids)
        if len(all_ids) != len(set(all_ids)):
            return False
        dataset_ids = set(dataset_manifest["case_ids"])
        if not set(all_ids).issubset(dataset_ids):
            return False
        if body.get("holdout_case_ids") != body["splits"]["holdout"]:
            return False
    except (KeyError, TypeError, ValueError):
        return False
    return bool(supplied) and supplied == digest(body)


def _interval(row: Mapping[str, Any]) -> tuple[datetime, datetime]:
    return (
        _utc(row["as_of_utc"], name="as_of_utc"),
        _utc(row["future_available_after_utc"], name="future_available_after_utc"),
    )


def _overlaps_expanded_test(
    train_row: Mapping[str, Any],
    test_rows: Sequence[Mapping[str, Any]],
    *,
    purge_minutes: int,
    embargo_minutes: int,
) -> bool:
    train_start, train_end = _interval(train_row)
    purge = timedelta(minutes=purge_minutes)
    embargo = timedelta(minutes=embargo_minutes)
    for test_row in test_rows:
        test_start, test_end = _interval(test_row)
        expanded_start = test_start - purge
        expanded_end = test_end + embargo
        if train_start <= expanded_end and train_end >= expanded_start:
            return True
    return False


def build_cpcv_manifest(
    dataset_manifest: Mapping[str, Any],
    split_manifest: Mapping[str, Any],
    *,
    group_count: int = 4,
    test_group_count: int = 1,
) -> dict[str, Any]:
    """Build deterministic purged combinatorial folds on pre-holdout cases only."""

    if not verify_chronological_split_manifest(split_manifest, dataset_manifest):
        raise ReplayIntegrityError("Valid dataset and split manifests are required.")
    if isinstance(group_count, bool) or not isinstance(group_count, int) or group_count < 3:
        raise ReplayIntegrityError("group_count must be an integer >= 3.")
    if (
        isinstance(test_group_count, bool)
        or not isinstance(test_group_count, int)
        or test_group_count <= 0
        or test_group_count >= group_count
    ):
        raise ReplayIntegrityError("test_group_count must be between 1 and group_count - 1.")

    pre_holdout_ids = (
        list(split_manifest["splits"]["train"])
        + list(split_manifest["splits"]["dev"])
        + list(split_manifest["splits"]["calibration"])
    )
    row_by_id = {str(row["case_id"]): dict(row) for row in dataset_manifest["cases"]}
    ordered = sorted(
        (row_by_id[case_id] for case_id in pre_holdout_ids),
        key=lambda row: (row["as_of_utc"], row["case_id"]),
    )
    if len(ordered) < group_count:
        raise ReplayIntegrityError("Not enough pre-holdout cases for the requested CPCV groups.")

    groups: list[list[dict[str, Any]]] = [[] for _ in range(group_count)]
    for index, row in enumerate(ordered):
        group_index = min(index * group_count // len(ordered), group_count - 1)
        groups[group_index].append(row)
    if any(not group for group in groups):
        raise ReplayIntegrityError("CPCV grouping produced an empty group.")

    folds: list[dict[str, Any]] = []
    for fold_number, test_indexes in enumerate(
        itertools.combinations(range(group_count), test_group_count), start=1
    ):
        test_set = set(test_indexes)
        test_rows = [row for index, group in enumerate(groups) if index in test_set for row in group]
        candidate_train = [
            row for index, group in enumerate(groups) if index not in test_set for row in group
        ]
        purged = [
            row
            for row in candidate_train
            if _overlaps_expanded_test(
                row,
                test_rows,
                purge_minutes=int(split_manifest["purge_minutes"]),
                embargo_minutes=int(split_manifest["embargo_minutes"]),
            )
        ]
        purged_ids = {str(row["case_id"]) for row in purged}
        train_rows = [row for row in candidate_train if str(row["case_id"]) not in purged_ids]
        fold: dict[str, Any] = {
            "fold_number": fold_number,
            "test_group_indices": list(test_indexes),
            "train_case_ids": [str(row["case_id"]) for row in train_rows],
            "test_case_ids": [str(row["case_id"]) for row in test_rows],
            "purged_case_ids": sorted(purged_ids),
            "holdout_case_ids_used": [],
        }
        fold["fold_digest"] = digest(fold)
        folds.append(fold)

    manifest: dict[str, Any] = {
        "manifest_version": CPCV_MANIFEST_VERSION,
        "harness_version": REPLAY_HARNESS_VERSION,
        "dataset_manifest_digest": dataset_manifest["manifest_digest"],
        "split_digest": split_manifest["split_digest"],
        "group_count": group_count,
        "test_group_count": test_group_count,
        "group_case_ids": [[str(row["case_id"]) for row in group] for group in groups],
        "fold_count": len(folds),
        "folds": folds,
        "holdout_excluded_from_cpcv": True,
        "purge_minutes": split_manifest["purge_minutes"],
        "embargo_minutes": split_manifest["embargo_minutes"],
    }
    manifest["cpcv_digest"] = digest(manifest)
    return manifest


def verify_cpcv_manifest(
    manifest: Mapping[str, Any],
    dataset_manifest: Mapping[str, Any],
    split_manifest: Mapping[str, Any],
) -> bool:
    if not isinstance(manifest, Mapping):
        return False
    body = copy.deepcopy(dict(manifest))
    supplied = str(body.pop("cpcv_digest", ""))
    try:
        if body.get("manifest_version") != CPCV_MANIFEST_VERSION:
            return False
        if body.get("dataset_manifest_digest") != dataset_manifest["manifest_digest"]:
            return False
        if body.get("split_digest") != split_manifest["split_digest"]:
            return False
        if body.get("holdout_excluded_from_cpcv") is not True:
            return False
        holdout = set(split_manifest["holdout_case_ids"])
        for fold in body["folds"]:
            fold_body = dict(fold)
            fold_digest = str(fold_body.pop("fold_digest", ""))
            if fold_digest != digest(fold_body):
                return False
            if holdout & set(fold["train_case_ids"]):
                return False
            if holdout & set(fold["test_case_ids"]):
                return False
            if set(fold["train_case_ids"]) & set(fold["test_case_ids"]):
                return False
    except (KeyError, TypeError, ValueError):
        return False
    return bool(supplied) and supplied == digest(body)


def build_holdout_access_record(
    *,
    trial_record: Mapping[str, Any],
    dataset_manifest: Mapping[str, Any],
    split_manifest: Mapping[str, Any],
    frozen_version_digest: str,
    accessed_case_ids: Iterable[str],
    accessed_at: datetime | str,
    score_digest: str | None = None,
) -> dict[str, Any]:
    if not verify_trial_record(trial_record) or trial_record.get("registry_version") != TRIAL_REGISTRY_VERSION:
        raise ReplayIntegrityError("A valid Day-32 trial record is required.")
    if trial_record.get("purpose") != "evaluation":
        raise ReplayIntegrityError("Holdout access is forbidden for tuning trials.")
    if not verify_chronological_split_manifest(split_manifest, dataset_manifest):
        raise ReplayIntegrityError("Valid dataset and split manifests are required.")
    if trial_record.get("dataset_version") != dataset_manifest.get("dataset_version"):
        raise ReplayIntegrityError("Trial dataset version does not match frozen replay dataset.")
    if trial_record.get("holdout_identity") != split_manifest.get("holdout_identity"):
        raise ReplayIntegrityError("Trial holdout identity does not match the frozen split.")
    ids = [str(case_id) for case_id in accessed_case_ids]
    if len(ids) != len(set(ids)):
        raise ReplayIntegrityError("Holdout access cannot contain duplicate case IDs.")
    allowed = set(split_manifest["holdout_case_ids"])
    if not ids or not set(ids).issubset(allowed):
        raise ReplayIntegrityError("Holdout access must reference only frozen holdout case IDs.")
    record: dict[str, Any] = {
        "access_version": HOLDOUT_ACCESS_VERSION,
        "trial_identity": trial_record["trial_identity"],
        "trial_digest": trial_record["trial_digest"],
        "dataset_manifest_digest": dataset_manifest["manifest_digest"],
        "split_digest": split_manifest["split_digest"],
        "holdout_identity": split_manifest["holdout_identity"],
        "frozen_version_digest": _text(frozen_version_digest, name="frozen_version_digest"),
        "accessed_at": _utc(accessed_at, name="accessed_at").isoformat(),
        "accessed_case_ids": sorted(ids),
        "accessed_case_count": len(ids),
        "score_digest": score_digest,
        "purpose": "score_frozen_version",
        "tuning_allowed_after_access": False,
        "same_holdout_reusable_for_tuning": False,
        "silent_promotion_allowed": False,
        "new_trial_required_for_changes": True,
    }
    record["access_digest"] = digest(record)
    return record


def verify_holdout_access_record(record: Mapping[str, Any]) -> bool:
    if not isinstance(record, Mapping):
        return False
    body = copy.deepcopy(dict(record))
    supplied = str(body.pop("access_digest", ""))
    try:
        if body.get("access_version") != HOLDOUT_ACCESS_VERSION:
            return False
        if body.get("purpose") != "score_frozen_version":
            return False
        if body.get("tuning_allowed_after_access") is not False:
            return False
        if body.get("same_holdout_reusable_for_tuning") is not False:
            return False
        if body.get("silent_promotion_allowed") is not False:
            return False
        if body.get("new_trial_required_for_changes") is not True:
            return False
        _utc(body["accessed_at"], name="accessed_at")
    except (KeyError, TypeError, ValueError):
        return False
    return bool(supplied) and supplied == digest(body)


def build_replay_score_record(
    *,
    trial_record: Mapping[str, Any],
    dataset_manifest: Mapping[str, Any],
    split_manifest: Mapping[str, Any],
    frozen_version_digest: str,
    evaluation_split: SplitName,
    case_scores: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    if not verify_trial_record(trial_record):
        raise ReplayIntegrityError("A valid Day-32 trial record is required.")
    if evaluation_split not in _SPLIT_ORDER:
        raise ReplayIntegrityError("Unsupported replay evaluation split.")
    if not verify_chronological_split_manifest(split_manifest, dataset_manifest):
        raise ReplayIntegrityError("Valid dataset and split manifests are required.")
    allowed_ids = set(split_manifest["splits"][evaluation_split])
    rows: list[dict[str, Any]] = []
    for raw in case_scores:
        if not isinstance(raw, Mapping):
            raise TypeError("case_scores entries must be mappings.")
        row = copy.deepcopy(dict(raw))
        case_id = _text(row.get("case_id"), name="case_score.case_id")
        if case_id not in allowed_ids:
            raise ReplayIntegrityError(
                f"Score references a case outside the frozen {evaluation_split} split: {case_id}"
            )
        for required in ("input_digest", "retrieval_digest", "decision_digest", "score"):
            if required not in row:
                raise ReplayIntegrityError(f"Replay score row lacks {required}.")
        rows.append(row)
    rows.sort(key=lambda row: str(row["case_id"]))
    ids = [str(row["case_id"]) for row in rows]
    if not rows or len(ids) != len(set(ids)):
        raise ReplayIntegrityError("Replay score rows must be non-empty and case-unique.")
    record: dict[str, Any] = {
        "score_version": REPLAY_SCORE_VERSION,
        "harness_version": REPLAY_HARNESS_VERSION,
        "trial_identity": trial_record["trial_identity"],
        "trial_digest": trial_record["trial_digest"],
        "dataset_manifest_digest": dataset_manifest["manifest_digest"],
        "split_digest": split_manifest["split_digest"],
        "frozen_version_digest": _text(frozen_version_digest, name="frozen_version_digest"),
        "evaluation_split": evaluation_split,
        "case_count": len(rows),
        "case_scores": rows,
        "inputs_retrievals_and_scores_frozen": True,
        "side_effects_allowed": False,
    }
    record["score_digest"] = digest(record)
    return record


def verify_replay_score_record(record: Mapping[str, Any]) -> bool:
    if not isinstance(record, Mapping):
        return False
    body = copy.deepcopy(dict(record))
    supplied = str(body.pop("score_digest", ""))
    try:
        if body.get("score_version") != REPLAY_SCORE_VERSION:
            return False
        rows = body["case_scores"]
        if body.get("case_count") != len(rows) or not rows:
            return False
        if rows != sorted(rows, key=lambda row: str(row["case_id"])):
            return False
        if len({str(row["case_id"]) for row in rows}) != len(rows):
            return False
        if body.get("inputs_retrievals_and_scores_frozen") is not True:
            return False
        if body.get("side_effects_allowed") is not False:
            return False
    except (KeyError, TypeError, ValueError):
        return False
    return bool(supplied) and supplied == digest(body)


def replay_harness_manifest() -> dict[str, Any]:
    manifest = {
        "harness_version": REPLAY_HARNESS_VERSION,
        "dataset_manifest_version": DATASET_MANIFEST_VERSION,
        "split_manifest_version": SPLIT_MANIFEST_VERSION,
        "cpcv_manifest_version": CPCV_MANIFEST_VERSION,
        "holdout_access_version": HOLDOUT_ACCESS_VERSION,
        "replay_score_version": REPLAY_SCORE_VERSION,
        "digest_algorithm": DIGEST_ALGORITHM,
        "chronological_train_dev_calibration_holdout_required": True,
        "purge_required": True,
        "embargo_required": True,
        "cpcv_pre_holdout_only": True,
        "day32_trial_registry_required": True,
        "holdout_tuning_allowed": False,
        "holdout_access_logging_required": True,
        "same_version_reproducibility_required": True,
        "future_first_observation_allowed_at_t": False,
        "telegram_side_effects_allowed": False,
        "broker_side_effects_allowed": False,
        "super_signals_side_effects_allowed": False,
        "predictive_edge_claimed": False,
    }
    manifest["manifest_digest"] = digest(manifest)
    return manifest
