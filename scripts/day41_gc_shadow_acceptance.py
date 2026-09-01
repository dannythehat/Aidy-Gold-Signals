from __future__ import annotations

import argparse
import json
import subprocess
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from aidy.gc_shadow_spine import (
    GcObservation,
    XauObservation,
    canonical_json,
    day41_architecture_manifest,
    pair_shadow_observations,
)

BASE_SHA = "abe751749a20f9951b2456db9c7a048a8f60554f"


def _write(path: Path, value: object) -> None:
    path.write_text(canonical_json(value) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="day41_artifacts")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    output = root / args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    head_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()

    observed = datetime(2026, 9, 1, 7, 0, tzinfo=UTC)
    gc = GcObservation(
        observed_at=observed,
        price=Decimal("4521.50"),
        contract_symbol="GCZ6",
        source_digest="a" * 64,
    )
    xau = XauObservation(
        observed_at=observed + timedelta(seconds=15),
        price=Decimal("4500.25"),
        source_digest="b" * 64,
    )
    pair = pair_shadow_observations(gc, xau, max_skew_seconds=60)
    architecture = day41_architecture_manifest()

    summary = {
        "ok": bool(
            pair["paired"]
            and architecture["gc_shadow_only"]
            and architecture["xau_reference_retained"]
            and architecture["outage_substitution_allowed"] is False
            and architecture["broker_market_data_dependency"] is False
            and architecture["paid_subscription_activated"] is False
            and architecture["live_gc_promoted"] is False
            and architecture["promotion_policy"]["frozen_before_shadow_results"]
            and architecture["promotion_policy"]["automatic_promotion_allowed"] is False
        ),
        "base_sha": BASE_SHA,
        "head_sha": head_sha,
        "provider": architecture["provider"],
        "dataset": architecture["dataset"],
        "continuous_symbol": architecture["continuous_symbol"],
        "xau_reference_source": architecture["xau_reference_source"],
        "vendor_separable_adapter": architecture["vendor_separable_adapter"],
        "gc_shadow_only": architecture["gc_shadow_only"],
        "xau_reference_retained": architecture["xau_reference_retained"],
        "outage_substitution_allowed": architecture["outage_substitution_allowed"],
        "broker_market_data_dependency": architecture["broker_market_data_dependency"],
        "paid_subscription_activated": architecture["paid_subscription_activated"],
        "live_gc_promoted": architecture["live_gc_promoted"],
        "promotion_policy_digest": architecture["promotion_policy"]["policy_digest"],
        "architecture_manifest_digest": architecture["manifest_digest"],
        "fixture_pair_digest": pair["pair_digest"],
        "genuine_databento_evidence_required_separately": True,
    }
    _write(output / "architecture_manifest.json", architecture)
    _write(output / "fixture_pair.json", pair)
    _write(output / "summary.json", summary)
    print(json.dumps(summary, sort_keys=True))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
