from __future__ import annotations

import argparse
import subprocess
from hashlib import sha256
from pathlib import Path

from aidy.self_consistency import canonical_json, digest, self_consistency_manifest
from aidy.self_consistency_ledger import SELF_CONSISTENCY_LEDGER_PROJECTION_VERSION

BASE_SHA = "619923f813c3f6527f4c765174b91e272a4dd8a3"
EXPECTED_FILES = (
    "src/aidy/self_consistency.py",
    "src/aidy/self_consistency_ledger.py",
    "tests/test_day36_self_consistency.py",
    "tests/test_day36_self_consistency_ledger.py",
    "docs/day36-self-consistency-contract.md",
    "scripts/day36_self_consistency_acceptance.py",
    ".github/workflows/day36-self-consistency-acceptance.yml",
)


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="day36_artifacts")
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
    manifest = self_consistency_manifest()

    expected_true = (
        "same_frozen_bundle_required",
        "same_frozen_config_required",
        "independent_contract_validation_required",
        "independent_post_model_safety_required",
        "ledger_state_supported",
    )
    for key in expected_true:
        if manifest.get(key) is not True:
            raise RuntimeError(f"Day 36 manifest boundary drift: {key}")
    expected_false = (
        "invalid_or_blocked_sample_can_vote",
        "multi_agent_debate_used",
        "bull_bear_judge_pattern_used",
        "model_persuasion_loop_used",
        "confidence_can_override_consensus",
        "broker_or_follower_state_used",
        "super_signals_modified",
        "predictive_edge_claimed",
    )
    for key in expected_false:
        if manifest.get(key) is not False:
            raise RuntimeError(f"Day 36 manifest boundary drift: {key}")
    if manifest.get("sample_count") != 3 or manifest.get("safe_majority_required") != 2:
        raise RuntimeError("Day 36 k=3 majority contract drift")
    if manifest.get("no_safe_majority_action") != "no_trade":
        raise RuntimeError("Day 36 disagreement no longer fails to no_trade")
    if manifest.get("max_total_provider_attempts") != 6:
        raise RuntimeError("Day 36 provider-attempt bound drift")

    file_digests = {}
    for filename in EXPECTED_FILES:
        path = Path(filename)
        if not path.is_file():
            raise RuntimeError(f"Day 36 acceptance file missing: {filename}")
        file_digests[filename] = _file_digest(path)

    summary = {
        "ok": True,
        "base_sha": BASE_SHA,
        "head_sha": head_sha,
        "sample_count": 3,
        "safe_majority_required": 2,
        "no_safe_majority_action": "no_trade",
        "same_frozen_bundle_required": True,
        "same_frozen_config_required": True,
        "independent_contract_validation_required": True,
        "independent_post_model_safety_required": True,
        "all_three_sample_receipts_ledger_ready": True,
        "all_three_full_sample_decisions_ledger_ready": True,
        "ledger_projection_version": SELF_CONSISTENCY_LEDGER_PROJECTION_VERSION,
        "disagreement_metrics_ledger_ready": True,
        "max_total_provider_attempts": 6,
        "multi_agent_debate_used": False,
        "model_persuasion_loop_used": False,
        "confidence_can_override_consensus": False,
        "broker_or_follower_state_used": False,
        "super_signals_modified": False,
        "predictive_edge_claimed": False,
        "manifest_digest": manifest["manifest_digest"],
        "file_digests": file_digests,
    }
    summary["summary_digest"] = digest(summary)
    _write(output / "self_consistency_manifest.json", manifest)
    _write(output / "summary.json", summary)
    print(canonical_json(summary))


if __name__ == "__main__":
    main()
