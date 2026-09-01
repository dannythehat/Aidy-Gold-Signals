from __future__ import annotations

import copy
from collections.abc import Mapping
from datetime import datetime
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
    if trial_record.get("dataset_version") != dataset_manifest.get("dataset_version"):
        raise ReplayIntegrityError("Trial dataset version does not match replay dataset.")
    if trial_record.get("holdout_identity") != split_manifest.get("holdout_identity"):
        raise ReplayIntegrityError("Trial holdout identity does not match replay split.")
    if not isinstance(frozen_configuration, Mapping):
        raise TypeError("frozen_configuration must be a mapping.")
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
        "split_digest": split_manifest["split_digest"],
        "cpcv_digest": cpcv_manifest["cpcv_digest"],
        "holdout_identity": split_manifest["holdout_identity"],
        "frozen_version_digest": version_digest,
        "frozen_configuration": config,
        "frozen_configuration_digest": digest(config),
        "created_at": _utc(created_at, name="created_at").isoformat(),
        "holdout_access_allowed": purpose == "evaluation",
        "holdout_tuning_allowed": False,
        "configuration_mutation_after_preregistration_allowed": False,
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
        if body.get("split_digest") != split_manifest["split_digest"]:
            return False
        if body.get("cpcv_digest") != cpcv_manifest["cpcv_digest"]:
            return False
        if body.get("frozen_configuration_digest") != digest(body["frozen_configuration"]):
            return False
        if body.get("holdout_tuning_allowed") is not False:
            return False
        if body.get("configuration_mutation_after_preregistration_allowed") is not False:
            return False
        if body.get("side_effects_allowed") is not False:
            return False
        _utc(body["created_at"], name="created_at")
        canonical_json(body)
    except (KeyError, TypeError, ValueError):
        return False
    return bool(supplied) and supplied == digest(body)
