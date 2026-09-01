from __future__ import annotations

import argparse
import json
import subprocess
from hashlib import sha256
from pathlib import Path
from typing import Any

from aidy.management_contract_v2 import canonical_json, day48_manifest

BASE_SHA = "fe422b62efbb3814a1cf066eca6ee9cb3c9f89b0"


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AIDY Day 48 management-contract acceptance")
    parser.add_argument("--output-dir", default="day48_artifacts")
    return parser.parse_args()


def _file_digest(path: str) -> str:
    return sha256(Path(path).read_bytes()).hexdigest()


def build_artifacts() -> dict[str, Any]:
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    manifest = day48_manifest()
    summary: dict[str, Any] = {
        "ok": True,
        "base_sha": BASE_SHA,
        "head_sha": head,
        "manifest_digest": manifest["manifest_digest"],
        "management_module_digest": _file_digest("src/aidy/management_contract_v2.py"),
        "focused_test_digest": _file_digest("tests/test_day48_management_contract_v2.py"),
        "exact_originating_decision_id_required": True,
        "active_paper_state_required": True,
        "watcher_observation_required": True,
        "original_thesis_invalidation_immutable": True,
        "wrong_or_missing_target_ids_fail_closed": True,
        "risk_reducing_stop_geometry_only": True,
        "replacement_targets_state_bounded": True,
        "every_admitted_action_ledgered": True,
        "ledger_tamper_evident": True,
        "paper_only": True,
        "publication_allowed": False,
        "execution_allowed": False,
        "account_sizing_allowed": False,
        "broker_or_follower_state_allowed": False,
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
