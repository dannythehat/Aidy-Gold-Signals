from __future__ import annotations

import argparse
import json
import subprocess
from hashlib import sha256
from pathlib import Path
from typing import Any

from aidy.decision_ledger import decision_ledger_manifest
from aidy.end_to_end import day52_runtime_manifest
from aidy.forward_start_amendment import (
    AMENDMENT_EFFECTIVE_UTC,
    DAY54_EARLIEST_REVIEW_DATE,
    build_amended_frozen_version_manifest,
    day53_immediate_start_manifest,
    digest,
)
from aidy.gc_shadow_spine import day41_architecture_manifest
from aidy.macro_event_intelligence import EVENT_INTELLIGENCE_VERSION, SURPRISE_CAPTURE_VERSION
from aidy.openai_gateway_v2 import openai_gateway_manifest_v2
from aidy.selective_abstention import day45_manifest
from aidy.self_consistency_v2 import self_consistency_manifest_v2

BASE_SHA = "010abc653c274b14d0a64941af9ca22eb88aa658"
EXPECTED_FILES = (
    ".github/workflows/day53-immediate-start-acceptance.yml",
    "docs/day53-immediate-start-amendment.md",
    "scripts/day53_immediate_start_acceptance.py",
    "src/aidy/forward_start_amendment.py",
    "tests/test_day53_immediate_start.py",
)


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AIDY Day 53 immediate-start amendment acceptance")
    parser.add_argument("--output-dir", default="day53_immediate_start_artifacts")
    return parser.parse_args()


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True).strip()


def _file_digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _component(version: str, manifest: dict[str, Any]) -> dict[str, str]:
    manifest_digest = str(manifest.get("manifest_digest") or "")
    if not manifest_digest:
        raise RuntimeError(f"Component {version} has no manifest digest.")
    return {"version": version, "digest": manifest_digest}


def build_artifacts(head_sha: str) -> dict[str, Any]:
    runtime = day52_runtime_manifest()
    gateway = openai_gateway_manifest_v2()
    consistency = self_consistency_manifest_v2()
    ledger = decision_ledger_manifest()
    selective = day45_manifest()
    gc = day41_architecture_manifest()
    macro_identity = {
        "event_intelligence_version": EVENT_INTELLIGENCE_VERSION,
        "surprise_capture_version": SURPRISE_CAPTURE_VERSION,
        "historical_consensus_backfilled": False,
        "forward_capture_required": True,
    }
    components = {
        "day52_runtime": _component(str(runtime["runtime_version"]), runtime),
        "openai_gateway_v2": _component(str(gateway["gateway_version"]), gateway),
        "self_consistency_v2": _component(
            str(consistency["self_consistency_version"]), consistency
        ),
        "immutable_decision_ledger": _component(str(ledger["ledger_version"]), ledger),
        "selective_abstention_shadow": _component(str(selective["layer_version"]), selective),
        "gc_xau_shadow": _component(str(gc["manifest_version"]), gc),
        "macro_surprise": {
            "version": SURPRISE_CAPTURE_VERSION,
            "digest": digest(macro_identity),
        },
    }
    frozen = build_amended_frozen_version_manifest(
        accepted_code_head=head_sha,
        earliest_start_utc=AMENDMENT_EFFECTIVE_UTC,
        components=components,
    )
    architecture = day53_immediate_start_manifest()
    required_false = (
        "pre_activation_backfill_allowed",
        "formal_forward_outcomes_existed_before_amendment",
        "blocked_cycles_count_as_model_resolved_episodes",
        "performance_improvement_freeze_break_allowed",
        "super_signals_dependency_allowed",
        "broker_or_account_state_allowed",
        "follower_state_allowed",
        "live_money_execution_allowed",
    )
    for key in required_false:
        if architecture.get(key) is not False:
            raise RuntimeError(f"Immediate-start architecture boundary drift: {key}")
    if architecture.get("day54_sample_gate_episode_independent_n") != 300:
        raise RuntimeError("Day 54 decision-episode gate drifted from 300.")
    if architecture.get("day54_gate_uses_model_resolved_episodes_only") is not True:
        raise RuntimeError("Blocked cycles must not satisfy Day 54 sample gate.")
    if architecture.get("day54_earliest_review_date") != DAY54_EARLIEST_REVIEW_DATE:
        raise RuntimeError("Day 54 earliest review date drifted.")

    changed_files = sorted(
        line
        for line in _git("diff", "--name-only", f"{BASE_SHA}...{head_sha}").splitlines()
        if line
    )
    unexpected = sorted(set(changed_files) - set(EXPECTED_FILES))
    missing = sorted(set(EXPECTED_FILES) - set(changed_files))
    if unexpected:
        raise RuntimeError(f"Unexpected immediate-start files: {unexpected}")
    if missing:
        raise RuntimeError(f"Expected immediate-start files missing from candidate: {missing}")

    summary: dict[str, Any] = {
        "ok": True,
        "base_sha": BASE_SHA,
        "head_sha": head_sha,
        "changed_files": changed_files,
        "changed_file_count": len(changed_files),
        "file_digests": {filename: _file_digest(Path(filename)) for filename in EXPECTED_FILES},
        "frozen_manifest_digest": frozen["manifest_digest"],
        "amendment_architecture_manifest_digest": architecture["manifest_digest"],
        "amendment_effective_utc": AMENDMENT_EFFECTIVE_UTC,
        "former_20_sep_floor_superseded": True,
        "formal_forward_outcomes_existed_before_amendment": False,
        "pre_activation_backfill_allowed": False,
        "immediate_activation_allowed_after_merge": True,
        "actual_remote_cohort_activation_performed_by_pr_ci": False,
        "day54_earliest_review_date": DAY54_EARLIEST_REVIEW_DATE,
        "day54_minimum_model_resolved_episode_independent_n": 300,
        "blocked_cycles_can_satisfy_day54_gate": False,
        "selective_layer_shadow_only": True,
        "gc_shadow_only": True,
        "performance_improvement_freeze_break_allowed": False,
        "super_signals_modified": False,
        "broker_or_follower_state_used": False,
        "live_money_execution_enabled": False,
    }
    summary["summary_digest"] = digest(summary)
    return {
        "amended_frozen_version_manifest": frozen,
        "amendment_architecture_manifest": architecture,
        "summary": summary,
    }


def main() -> int:
    args = _args()
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    head_sha = _git("rev-parse", "HEAD")
    if _git("merge-base", BASE_SHA, head_sha) != BASE_SHA:
        raise RuntimeError("Immediate-start candidate is not descended from accepted Day 53 readiness main.")
    artifacts = build_artifacts(head_sha)
    for name, payload in artifacts.items():
        (output / f"{name}.json").write_text(canonical_json(payload) + "\n", encoding="utf-8")
    print(canonical_json(artifacts["summary"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
