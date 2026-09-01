from __future__ import annotations

import argparse
import json
import subprocess
from hashlib import sha256
from pathlib import Path
from typing import Any

from aidy.end_to_end import day52_runtime_manifest
from aidy.openai_gateway_v2 import openai_gateway_manifest_v2
from aidy.self_consistency_v2 import self_consistency_manifest_v2

BASE_SHA = "0a402ab092c973db3976b46a485142b6a0a003d0"
EXPECTED_FILES = (
    "migrations/d1/0004_end_to_end_cycles.sql",
    "src/aidy/safety_gates_v2.py",
    "src/aidy/openai_gateway_v2.py",
    "src/aidy/self_consistency_v2.py",
    "src/aidy/self_consistency_ledger_v2.py",
    "src/aidy/end_to_end_store.py",
    "src/aidy/paper_management_runtime.py",
    "src/aidy/end_to_end.py",
    "tests/test_day52_end_to_end.py",
    "tests/test_day52_management_end_to_end.py",
    "scripts/day52_end_to_end_acceptance.py",
    "docs/day52-end-to-end-fidelity-restart.md",
    ".github/workflows/day52-end-to-end-acceptance.yml",
)


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value: object) -> str:
    return sha256(canonical_json(value).encode()).hexdigest()


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AIDY Day 52 deterministic acceptance evidence")
    parser.add_argument("--output-dir", default="day52_artifacts")
    return parser.parse_args()


def _file_digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: object) -> None:
    path.write_text(canonical_json(value) + "\n", encoding="utf-8")


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True).strip()


def build_artifacts(head_sha: str) -> dict[str, Any]:
    runtime = day52_runtime_manifest()
    gateway = openai_gateway_manifest_v2()
    self_consistency = self_consistency_manifest_v2()

    required_runtime_true = (
        "restart_reuses_exact_ex_ante_record",
        "restart_reuses_exact_publication_identity",
    )
    required_runtime_false = (
        "shadow_replay_can_publish",
        "no_trade_can_publish",
        "self_consistency_abstain_creates_fake_no_trade",
        "stale_resume_can_publish",
        "broker_or_account_state_allowed",
        "follower_state_allowed",
        "super_signals_dependency_allowed",
        "formal_forward_evidence_created",
        "day53_automatically_started",
    )
    for key in required_runtime_true:
        if runtime.get(key) is not True:
            raise RuntimeError(f"Day 52 runtime invariant drift: {key}")
    for key in required_runtime_false:
        if runtime.get(key) is not False:
            raise RuntimeError(f"Day 52 runtime boundary drift: {key}")
    if gateway.get("falsifiable_v2_required") is not True:
        raise RuntimeError("Day 52 gateway no longer requires falsifiable V2.")
    if gateway.get("broker_or_telegram_access") is not False:
        raise RuntimeError("Day 52 gateway crossed the provider boundary.")
    if self_consistency.get("sample_count") != 3:
        raise RuntimeError("Day 52 self-consistency is no longer k=3.")
    if self_consistency.get("no_safe_majority_action") != "abstain_without_synthetic_decision":
        raise RuntimeError("Day 52 no-majority behavior drifted.")

    file_digests: dict[str, str] = {}
    for filename in EXPECTED_FILES:
        path = Path(filename)
        if not path.is_file():
            raise RuntimeError(f"Day 52 acceptance file missing: {filename}")
        file_digests[filename] = _file_digest(path)

    changed_files = sorted(
        line for line in _git("diff", "--name-only", f"{BASE_SHA}...{head_sha}").splitlines() if line
    )
    unexpected = sorted(set(changed_files) - set(EXPECTED_FILES))
    missing_from_change = sorted(set(EXPECTED_FILES) - set(changed_files))
    if unexpected:
        raise RuntimeError(f"Unexpected Day 52 files: {unexpected}")
    if missing_from_change:
        raise RuntimeError(f"Expected Day 52 files are not in candidate diff: {missing_from_change}")

    summary: dict[str, Any] = {
        "ok": True,
        "base_sha": BASE_SHA,
        "head_sha": head_sha,
        "runtime_manifest_digest": runtime["manifest_digest"],
        "gateway_manifest_digest": gateway["manifest_digest"],
        "self_consistency_manifest_digest": self_consistency["manifest_digest"],
        "changed_file_count": len(changed_files),
        "changed_files": changed_files,
        "file_digests": file_digests,
        "market_path_test_present": True,
        "management_path_test_present": True,
        "restart_idempotency_required": True,
        "one_to_one_publication_identity_required": True,
        "stale_and_outage_fail_closed_required": True,
        "shadow_replay_private_forward_leakage_forbidden": True,
        "watcher_management_state_continuity_required": True,
        "deterministic_evidence_required": True,
        "formal_forward_evidence_created": False,
        "day53_started": False,
        "broker_or_follower_state_used": False,
        "super_signals_modified": False,
    }
    summary["summary_digest"] = digest(summary)
    return {
        "runtime_manifest": runtime,
        "gateway_manifest": gateway,
        "self_consistency_manifest": self_consistency,
        "summary": summary,
    }


def main() -> int:
    args = _args()
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    head_sha = _git("rev-parse", "HEAD")
    if _git("merge-base", BASE_SHA, head_sha) != BASE_SHA:
        raise RuntimeError("Day 52 candidate is not descended from the accepted Day 51 base.")
    artifacts = build_artifacts(head_sha)
    _write(output / "runtime_manifest.json", artifacts["runtime_manifest"])
    _write(output / "gateway_manifest.json", artifacts["gateway_manifest"])
    _write(output / "self_consistency_manifest.json", artifacts["self_consistency_manifest"])
    _write(output / "summary.json", artifacts["summary"])
    print(canonical_json(artifacts["summary"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
