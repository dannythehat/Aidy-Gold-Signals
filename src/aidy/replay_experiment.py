from __future__ import annotations

import copy
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from aidy.replay_evaluation import (
    REPLAY_HARNESS_VERSION,
    ReplayIntegrityError,
    _utc,
    canonical_json,
    digest,
    verify_chronological_split_manifest,
    verify_cpcv_manifest,
    verify_frozen_dataset_manifest,
)
from aidy.research_integrity import TRIAL_REGISTRY_VERSION, verify_trial_record

REPLAY_EXPERIMENT_VERSION = "aidy_frozen_replay_experiment_v1"
_DURATION = re.compile(r"^(?P<value>\d+)(?P<unit>m|h|d)$")


def _trial_boundary(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ReplayIntegrityError(f"Trial {name} must be a date or timezone-aware timestamp.")
    text = value.strip()
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        try:
            return datetime.fromisoformat(text).replace(tzinfo=UTC)
        except ValueError as exc:
            raise ReplayIntegrityError(f"Trial {name} is invalid.") from exc
    return _utc(text, name=f"trial.{name}")


def _duration_to_minutes(value: Any, *, name: str) -> int:
    if not isinstance(value, str):
        raise ReplayIntegrityError(f"Trial {name} must use an explicit m/h/d duration.")
    match = _DURATION.fullmatch(value.strip().lower())
    if match is None:
        raise ReplayIntegrityError(f"Trial {name} must use an explicit m/h/d duration.")
    amount = int(match.group("value"))
    unit = match.group("unit")
    multiplier = {"m": 1, "h": 60, "d": 1440}[unit]
    return amount * multiplier


def assert_trial_matches_replay_design(
    *,
    trial_record: Mapping[str, Any],
    dataset_manifest: Mapping[str, Any],
    split_manifest: Mapping[str, Any],
    frozen_configuration: Mapping[str, Any],
) -> None:
    """Bind Day-37 replay design to the exact Day-32 preregistration."""

    if trial_record.get("dataset_version") != dataset_manifest.get("dataset_version"):
        raise ReplayIntegrityError("Trial dataset version does not match replay dataset.")
    if trial_record.get("code_head") != dataset_manifest.get("code_head"):
        raise ReplayIntegrityError("Trial code head does not match frozen replay dataset code head.")
    if trial_record.get("holdout_identity") != split_manifest.get("holdout_identity"):
        raise ReplayIntegrityError("Trial holdout identity does not match replay split.")

    trial_split = trial_record.get("chronological_split")
    if not isinstance(trial_split, Mapping):
        raise ReplayIntegrityError("Trial chronological split is required.")
    boundaries = split_manifest.get("boundaries")
    if not isinstance(boundaries, Mapping):
        raise ReplayIntegrityError("Replay split boundaries are required.")
    for key in ("train_end", "dev_end", "calibration_end", "holdout_end"):
        if key not in trial_split or key not in boundaries:
            raise ReplayIntegrityError(f"Missing preregistered replay boundary: {key}.")
        if _trial_boundary(trial_split[key], name=key) != _utc(
            boundaries[key], name=f"split.{key}"
        ):
            raise ReplayIntegrityError(f"Replay boundary drift from preregistration: {key}.")

    if _duration_to_minutes(trial_record.get("purge"), name="purge") != int(
        split_manifest.get("purge_minutes", -1)
    ):
        raise ReplayIntegrityError("Replay purge duration drifted from preregistration.")
    if _duration_to_minutes(trial_record.get("embargo"), name="embargo") != int(
        split_manifest.get("embargo_minutes", -1)
    ):
        raise ReplayIntegrityError("Replay embargo duration drifted from preregistration.")

    preregistered = trial_record.get("frozen_parameters")
    if not isinstance(preregistered, Mapping):
        raise ReplayIntegrityError("Trial frozen parameters are required.")
    if canonical_json(dict(preregistered)) != canonical_json(dict(frozen_configuration)):
        raise ReplayIntegrityError("Replay configuration drifted from preregistered parameters.")


def build_replay_experiment_manifest(
    *,
    trial_record: Mapping[str, Any],
    dataset_manifest: Mapping[str, Any],
    split_manifest: Mapping[str, Any],
    cpcv_manifest: Mapping[str, Any],
    frozen_version_digest: str,
    frozen_configuration: Mapping[str, Any],
    created_at: datetime | str,
) -> dict[str, Any]:
    if not verify_trial_record(trial_record) or trial_record.get("registry_version") != TRIAL_REGISTRY_VERSION:
        raise ReplayIntegrityError("A valid Day-32 trial record is required.")
    if not verify_frozen_dataset_manifest(dataset_manifest):
        raise ReplayIntegrityError("A valid frozen dataset manifest is required.")
    if not verify_chronological_split_manifest(split_manifest, dataset_manifest):
        raise ReplayIntegrityError("A valid chronological split manifest is required.")
    if not verify_cpcv_manifest(cpcv_manifest, dataset_manifest, split_manifest):
        raise ReplayIntegrityError("A valid CPCV manifest is required.")
    if not isinstance(frozen_configuration, Mapping):
        raise TypeError("frozen_configuration must be a mapping.")
    assert_trial_matches_replay_design(
        trial_record=trial_record,
        dataset_manifest=dataset_manifest,
        split_manifest=split_manifest,
        frozen_configuration=frozen_configuration,
    )
    version_digest = str(frozen_version_digest).strip()
    if not version_digest:
        raise ReplayIntegrityError("frozen_version_digest is required.")
    config = copy.deepcopy(dict(frozen_configuration))
    purpose = str(trial_record["purpose"])
    manifest: dict[str, Any] = {
        "experiment_version": REPLAY_EXPERIMENT_VERSION,
        "harness_version": REPLAY_HARNESS_VERSION,
        "trial_identity": trial_record["trial_identity"],
        "trial_digest": trial_record["trial_digest"],
        "trial_purpose": purpose,
        "dataset_version": dataset_manifest["dataset_version"],
        "dataset_manifest_digest": dataset_manifest["manifest_digest"],
        "dataset_code_head": dataset_manifest["code_head"],
        "split_digest": split_manifest["split_digest"],
        "cpcv_digest": cpcv_manifest["cpcv_digest"],
        "holdout_identity": split_manifest["holdout_identity"],
        "frozen_version_digest": version_digest,
        "frozen_configuration": config,
        "frozen_configuration_digest": digest(config),
        "preregistered_configuration_digest": digest(dict(trial_record["frozen_parameters"])),
        "created_at": _utc(created_at, name="created_at").isoformat(),
        "holdout_access_allowed": purpose == "evaluation",
        "holdout_tuning_allowed": False,
        "configuration_mutation_after_preregistration_allowed": False,
        "split_mutation_after_preregistration_allowed": False,
        "code_head_mutation_after_preregistration_allowed": False,
        "side_effects_allowed": False,
        "telegram_allowed": False,
        "broker_allowed": False,
        "super_signals_allowed": False,
    }
    manifest["experiment_digest"] = digest(manifest)
    return manifest


def verify_replay_experiment_manifest(
    manifest: Mapping[str, Any],
    *,
    trial_record: Mapping[str, Any],
    dataset_manifest: Mapping[str, Any],
    split_manifest: Mapping[str, Any],
    cpcv_manifest: Mapping[str, Any],
) -> bool:
    if not isinstance(manifest, Mapping):
        return False
    body = copy.deepcopy(dict(manifest))
    supplied = str(body.pop("experiment_digest", ""))
    try:
        if body.get("experiment_version") != REPLAY_EXPERIMENT_VERSION:
            return False
        if not verify_trial_record(trial_record):
            return False
        if body.get("trial_digest") != trial_record["trial_digest"]:
            return False
        if body.get("dataset_manifest_digest") != dataset_manifest["manifest_digest"]:
            return False
        if body.get("dataset_code_head") != dataset_manifest["code_head"]:
            return False
        if body.get("split_digest") != split_manifest["split_digest"]:
            return False
        if body.get("cpcv_digest") != cpcv_manifest["cpcv_digest"]:
            return False
        if body.get("frozen_configuration_digest") != digest(body["frozen_configuration"]):
            return False
        if body.get("preregistered_configuration_digest") != digest(
            dict(trial_record["frozen_parameters"])
        ):
            return False
        assert_trial_matches_replay_design(
            trial_record=trial_record,
            dataset_manifest=dataset_manifest,
            split_manifest=split_manifest,
            frozen_configuration=body["frozen_configuration"],
        )
        if body.get("holdout_tuning_allowed") is not False:
            return False
        if body.get("configuration_mutation_after_preregistration_allowed") is not False:
            return False
        if body.get("split_mutation_after_preregistration_allowed") is not False:
            return False
        if body.get("code_head_mutation_after_preregistration_allowed") is not False:
            return False
        if body.get("side_effects_allowed") is not False:
            return False
        _utc(body["created_at"], name="created_at")
        canonical_json(body)
    except (KeyError, TypeError, ValueError):
        return False
    return bool(supplied) and supplied == digest(body)
