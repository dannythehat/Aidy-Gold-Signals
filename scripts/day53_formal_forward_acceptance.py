from __future__ import annotations

import argparse
import json
import subprocess
from hashlib import sha256
from pathlib import Path
from typing import Any

from aidy.decision_ledger import decision_ledger_manifest
from aidy.end_to_end import day52_runtime_manifest
from aidy.forward_evaluation import (
    EARLIEST_FORMAL_START_UTC,
    build_frozen_version_manifest,
    day53_manifest,
    digest,
)
from aidy.gc_shadow_spine import day41_architecture_manifest
from aidy.macro_event_intelligence import EVENT_INTELLIGENCE_VERSION, SURPRISE_CAPTURE_VERSION
from aidy.openai_gateway_v2 import openai_gateway_manifest_v2
from aidy.selective_abstention import day45_manifest
from aidy.self_consistency_v2 import self_consistency_manifest_v2

BASE_SHA = "c2282d4cd6ab3eebc311e62004167a78d5ccee15"
EXPECTED_FILES = (
    "migrations/d1/0005_formal_forward_cohorts.sql",
    "src/aidy/forward_evaluation.py",
    "tests/test_day53_formal_forward.py",
    "scripts/day53_formal_forward_acceptance.py",
    "docs/day53-formal-forward-freeze.md",
    ".github/workflows/day53-formal-forward-acceptance.yml",
)


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AIDY Day 53 readiness acceptance evidence")
    parser.add_argument("--output-dir", default="day53_artifacts")
    return parser.parse_args()


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True).strip()


def _file_digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: object) -> None:
    path.write_text(canonical_json(value) + "\n", encoding="utf-8")


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
        "selective_abstention_shadow": _component(
            str(selective["layer_version"]), selective
        ),
        "gc_xau_shadow": _component(str(gc["manifest_version"]), gc),
        "macro_surprise": {
            "version": SURPRISE_CAPTURE_VERSION,
            "digest": digest(macro_identity),
        },
    }
    frozen = build_frozen_version_manifest(
        accepted_code_head=head_sha,
        earliest_start_utc=EARLIEST_FORMAL_START_UTC,
        components=components,
    )
    architecture = day53_manifest()

    required_false = (
        "pre_day53_backfill_allowed",
        "performance_improvement_freeze_break_allowed",
        "broker_or_account_state_allowed",
        "follower_state_allowed",
        "super_signals_dependency_allowed",
        "live_money_execution_allowed",
    )
    for key in required_false:
        if architecture.get(key) is not False:
            raise RuntimeError(f"Day 53 architecture boundary drift: {key}")
    if architecture.get("day54_sample_gate_episode_independent_n") != 300:
        raise RuntimeError("Day 54 effective-N gate drifted from 300 episodes.")
    if architecture.get("earliest_formal_start_utc") != EARLIEST_FORMAL_START_UTC:
        raise RuntimeError("Day 53 earliest formal start drifted.")

    changed_files = sorted(
        line
        for line in _git("diff", "--name-only", f"{BASE_SHA}...{head_sha}").splitlines()
        if line
    )
    unexpected = sorted(set(changed_files) - set(EXPECTED_FILES))
    missing = sorted(set(EXPECTED_FILES) - set(changed_files))
    if unexpected:
        raise RuntimeError(f"Unexpected Day 53 files: {unexpected}")
    if missing:
        raise RuntimeError(f"Expected Day 53 files are not in candidate diff: {missing}")

    file_digests = {filename: _file_digest(Path(filename)) for filename in EXPECTED_FILES}
    summary: dict[str, Any] = {
        "ok": True,
        "base_sha": BASE_SHA,
        "head_sha": head_sha,
        "changed_file_count": len(changed_files),
        "changed_files": changed_files,
        "file_digests": file_digests,
        "frozen_manifest_digest": frozen["manifest_digest"],
        "day53_manifest_digest": architecture["manifest_digest"],
        "earliest_formal_start_utc": EARLIEST_FORMAL_START_UTC,
        "readiness_implementation_complete": True,
        "formal_forward_cohort_started": False,
        "formal_forward_evidence_created": False,
        "pre_day53_backfill_allowed": False,
        "all_evaluations_including_no_trade_required": True,
        "data_quality_failure_distinct_from_no_trade": True,
        "j17_disagreement_logging_required": True,
        "j20_raw_and_episode_independent_n_required": True,
        "gc_shadow_and_feed_health_logging_required": True,
        "macro_consensus_surprise_forward_logging_required": True,
        "selective_layer_shadow_only": True,
        "freeze_break_machine_reason_required": True,
        "performance_improvement_freeze_break_allowed": False,
        "closed_cohort_mutation_allowed": False,
        "day54_minimum_episode_independent_n": 300,
        "super_signals_modified": False,
        "broker_or_follower_state_used": False,
        "live_money_execution_enabled": False,
    }
    summary["summary_digest"] = digest(summary)
    return {
        "frozen_version_manifest": frozen,
        "day53_architecture_manifest": architecture,
        "summary": summary,
    }


def main() -> int:
    args = _args()
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    head_sha = _git("rev-parse", "HEAD")
    if _git("merge-base", BASE_SHA, head_sha) != BASE_SHA:
        raise RuntimeError("Day 53 candidate is not descended from accepted Day 52 main.")
    artifacts = build_artifacts(head_sha)
    _write(output / "frozen_version_manifest.json", artifacts["frozen_version_manifest"])
    _write(output / "day53_architecture_manifest.json", artifacts["day53_architecture_manifest"])
    _write(output / "summary.json", artifacts["summary"])
    print(canonical_json(artifacts["summary"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
