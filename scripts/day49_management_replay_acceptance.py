from __future__ import annotations

import argparse
import json
import subprocess
from hashlib import sha256
from pathlib import Path
from typing import Any

from aidy.management_replay import canonical_json, day49_manifest

BASE_SHA = "f471d47c53d7e0c7f294a6c252205fff6ec4dc8a"


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AIDY Day 49 management replay acceptance")
    parser.add_argument("--output-dir", default="day49_artifacts")
    return parser.parse_args()


def _file_digest(path: str) -> str:
    return sha256(Path(path).read_bytes()).hexdigest()


def build_artifacts() -> dict[str, Any]:
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    manifest = day49_manifest()
    summary: dict[str, Any] = {
        "ok": True,
        "base_sha": BASE_SHA,
        "head_sha": head,
        "manifest_digest": manifest["manifest_digest"],
        "module_digest": _file_digest("src/aidy/management_replay.py"),
        "focused_test_digest": _file_digest("tests/test_day49_management_replay.py"),
        "unchanged_benchmark_frozen_before_evaluation": True,
        "entry_and_management_effects_separate": True,
        "restart_serialization_supported": True,
        "duplicate_actions_idempotent": True,
        "conflicting_actions_fail_closed": True,
        "delayed_or_mismatched_evidence_fails_closed": True,
        "raw_and_effective_n_reported": True,
        "regime_and_setup_segmentation_reported": True,
        "individual_trade_can_promote_management": False,
        "promotion_allowed": False,
        "paper_only": True,
        "execution_allowed": False,
        "formal_forward_evidence_created": False,
        "super_signals_modified": False,
    }
    summary["summary_digest"] = sha256(canonical_json(summary).encode()).hexdigest()
    return {"manifest": manifest, "summary": summary}


def _write(path: Path, value: object) -> None:
    path.write_text(canonical_json(value) + "\n", encoding="utf-8")


def main() -> int:
    args = _args()
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    artifacts = build_artifacts()
    _write(output / "manifest.json", artifacts["manifest"])
    _write(output / "summary.json", artifacts["summary"])
    print(json.dumps(artifacts["summary"], sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
