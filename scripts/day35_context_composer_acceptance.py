from __future__ import annotations

import argparse
import json
import subprocess
from hashlib import sha256
from pathlib import Path

from aidy.context_composer_v2 import (
    CONTEXT_COMPOSER_VERSION_V2,
    CONTEXT_DOSSIER_VERSION_V2,
    MANDATORY_PROMPT_SECTION_ORDER,
    canonical_json,
    context_composer_manifest_v2,
    digest,
)

BASE_SHA = "e182084fa4484836a0e971892fde2890a7ee4890"
EXPECTED_FILES = (
    "src/aidy/context_composer_v2.py",
    "tests/test_day35_context_composer_v2.py",
    "docs/day35-context-composer-v2-contract.md",
    "scripts/day35_context_composer_acceptance.py",
    ".github/workflows/day35-context-composer-v2-acceptance.yml",
)


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="day35_artifacts")
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
    manifest = context_composer_manifest_v2()

    required_true = (
        "counter_evidence_first",
        "same_selection_identity_for_support_and_counter",
        "same_format_schema_for_support_and_counter",
        "effective_n_mandatory",
        "evidence_grade_mandatory",
        "no_comparable_case_first_class",
        "validated_aggregate_statistics_only",
    )
    for key in required_true:
        if manifest.get(key) is not True:
            raise RuntimeError(f"Day 35 manifest boundary drift: {key}")

    required_false = (
        "raw_future_evaluation_allowed_in_dossier",
        "mandatory_fields_trimmable",
        "secrets_allowed",
        "runtime_account_state_allowed",
        "hidden_reasoning_allowed",
        "gateway_promoted_by_day35",
        "trading_gate_created_by_day35",
        "predictive_edge_claimed",
        "super_signals_modified",
    )
    for key in required_false:
        if manifest.get(key) is not False:
            raise RuntimeError(f"Day 35 manifest boundary drift: {key}")

    if manifest.get("composer_version") != CONTEXT_COMPOSER_VERSION_V2:
        raise RuntimeError("Day 35 composer version drift")
    if manifest.get("dossier_version") != CONTEXT_DOSSIER_VERSION_V2:
        raise RuntimeError("Day 35 dossier version drift")

    file_digests = {}
    for filename in EXPECTED_FILES:
        path = Path(filename)
        if not path.is_file():
            raise RuntimeError(f"Day 35 acceptance file missing: {filename}")
        file_digests[filename] = _file_digest(path)

    summary = {
        "ok": True,
        "base_sha": BASE_SHA,
        "head_sha": head_sha,
        "composer_version": CONTEXT_COMPOSER_VERSION_V2,
        "dossier_version": CONTEXT_DOSSIER_VERSION_V2,
        "mandatory_prompt_section_order": list(MANDATORY_PROMPT_SECTION_ORDER),
        "counter_evidence_first": True,
        "same_selection_identity_for_support_and_counter": True,
        "same_format_schema_for_support_and_counter": True,
        "effective_n_mandatory": True,
        "evidence_grade_mandatory": True,
        "no_comparable_case_first_class": True,
        "raw_future_evaluation_allowed": False,
        "mandatory_fields_trimmable": False,
        "gateway_promoted_by_day35": False,
        "trading_gate_created_by_day35": False,
        "predictive_edge_claimed": False,
        "super_signals_modified": False,
        "manifest_digest": manifest["manifest_digest"],
        "file_digests": file_digests,
    }
    summary["summary_digest"] = digest(summary)

    _write(output / "composer_manifest.json", manifest)
    _write(output / "summary.json", summary)
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
