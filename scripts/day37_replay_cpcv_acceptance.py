from __future__ import annotations

import argparse
import subprocess
from hashlib import sha256
from pathlib import Path

from aidy.replay_evaluation import canonical_json, digest, replay_harness_manifest
from aidy.replay_experiment import REPLAY_EXPERIMENT_VERSION

BASE_SHA = "d988a4ff29160e2d10a32e6c151d028001e941f2"
EXPECTED_FILES = (
    "src/aidy/replay_evaluation.py",
    "src/aidy/replay_experiment.py",
    "tests/test_day37_replay_evaluation.py",
    "docs/day37-frozen-replay-cpcv-contract.md",
    "scripts/day37_replay_cpcv_acceptance.py",
    ".github/workflows/day37-replay-cpcv-acceptance.yml",
)


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="day37_artifacts")
    return parser.parse_args()


def _file_digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: object) -> None:
    path.write_text(canonical_json(value) + "\n", encoding="utf-8")


def main() -> None:
    args = _args()
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    head_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    manifest = replay_harness_manifest()

    required_true = (
        "chronological_train_dev_calibration_holdout_required",
        "purge_required",
        "embargo_required",
        "cpcv_pre_holdout_only",
        "day32_trial_registry_required",
        "holdout_access_logging_required",
        "same_version_reproducibility_required",
    )
    for key in required_true:
        if manifest.get(key) is not True:
            raise RuntimeError(f"Day 37 manifest boundary drift: {key}")
    required_false = (
        "holdout_tuning_allowed",
        "future_first_observation_allowed_at_t",
        "telegram_side_effects_allowed",
        "broker_side_effects_allowed",
        "super_signals_side_effects_allowed",
        "predictive_edge_claimed",
    )
    for key in required_false:
        if manifest.get(key) is not False:
            raise RuntimeError(f"Day 37 manifest boundary drift: {key}")

    file_digests = {}
    for filename in EXPECTED_FILES:
        path = Path(filename)
        if not path.is_file():
            raise RuntimeError(f"Day 37 acceptance file missing: {filename}")
        file_digests[filename] = _file_digest(path)

    summary = {
        "ok": True,
        "base_sha": BASE_SHA,
        "head_sha": head_sha,
        "harness_version": manifest["harness_version"],
        "replay_experiment_version": REPLAY_EXPERIMENT_VERSION,
        "chronological_splits_required": True,
        "purge_required": True,
        "embargo_required": True,
        "cpcv_pre_holdout_only": True,
        "day32_trial_registry_required": True,
        "holdout_tuning_allowed": False,
        "holdout_access_logging_required": True,
        "future_first_observation_allowed_at_t": False,
        "same_version_reproducibility_required": True,
        "telegram_side_effects_allowed": False,
        "broker_side_effects_allowed": False,
        "super_signals_side_effects_allowed": False,
        "predictive_edge_claimed": False,
        "manifest_digest": manifest["manifest_digest"],
        "file_digests": file_digests,
    }
    summary["summary_digest"] = digest(summary)
    _write(output / "replay_harness_manifest.json", manifest)
    _write(output / "summary.json", summary)
    print(canonical_json(summary))


if __name__ == "__main__":
    main()
