from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from aidy.day40_gate import build_day40_manifest, canonical_json, failing_items, verify_manifest


def _write(path: Path, value: object) -> None:
    path.write_text(canonical_json(value) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="day40_artifacts")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    output = root / args.output_dir
    output.mkdir(parents=True, exist_ok=True)

    manifest = build_day40_manifest(root)
    head_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()

    summary = {
        "ok": bool(
            verify_manifest(manifest)
            and manifest["architecture_p0_passed"]
            and manifest["adversarial_gate_passed"]
        ),
        "head_sha": head_sha,
        "base_sha": manifest["base_sha"],
        "p0_requirement_count": manifest["checklist"]["requirement_count"],
        "p0_passed_count": manifest["checklist"]["passed_count"],
        "p0_failed_items": list(failing_items(manifest["checklist"])),
        "effective_n_is_authoritative_for_grading": manifest["checklist"][
            "effective_n_is_authoritative_for_grading"
        ],
        "j16_interpretation": manifest["checklist"]["j16_interpretation"],
        "j16_predictive_ordering_claimed": manifest["checklist"][
            "j16_predictive_ordering_claimed"
        ],
        "all_adversarial_fail_closed": manifest["adversarial"]["all_failed_closed"],
        "paid_market_data_activated": manifest["paid_market_data_activated"],
        "live_gc_subscription_activated": manifest["live_gc_subscription_activated"],
        "databento_adapter_built": True,
        "databento_free_first_decision": manifest["procurement"]["decision"],
        "databento_free_credit_usd": manifest["procurement"]["free_credit_usd"],
        "databento_day40_spend_cap_usd": manifest["procurement"][
            "day40_credit_spend_cap_usd"
        ],
        "databento_reserved_credit_usd": manifest["procurement"]["reserved_credit_usd"],
        "owner_approval_required_before_paid_activation": manifest["procurement"][
            "owner_approval_required_before_paid_activation"
        ],
        "formal_forward_paper_evaluation_started": manifest[
            "formal_forward_paper_evaluation_started"
        ],
        "broker_side_effects_allowed": manifest["broker_side_effects_allowed"],
        "telegram_side_effects_allowed": manifest["telegram_side_effects_allowed"],
        "super_signals_side_effects_allowed": manifest[
            "super_signals_side_effects_allowed"
        ],
        "manifest_digest": manifest["manifest_digest"],
        "checklist_digest": manifest["checklist"]["checklist_digest"],
        "adversarial_digest": manifest["adversarial"]["matrix_digest"],
        "procurement_digest": manifest["procurement"]["decision_digest"],
    }

    _write(output / "manifest.json", manifest)
    _write(output / "p0_checklist.json", manifest["checklist"])
    _write(output / "adversarial_matrix.json", manifest["adversarial"])
    _write(output / "procurement.json", manifest["procurement"])
    _write(output / "summary.json", summary)

    print(json.dumps(summary, sort_keys=True))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
