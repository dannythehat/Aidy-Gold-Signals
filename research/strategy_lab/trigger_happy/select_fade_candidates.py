"""Freeze exactly the previously declared robust TH001 fade candidates BEFORE new months.

Source: all 540 trial/4-month research artifact. Never inspect validation months
while selecting. Output includes original discovery monthly evidence and SHA.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def select(path: Path) -> dict:
    data = json.loads(path.read_text())
    if data["n_related_configs"] != 540 or data["source_months"] != [
            "202606", "202607", "202608", "202609"]:
        raise ValueError("Not the exact frozen 540/4-month discovery cohort")
    selected = [
        r for r in data["all_results"]
        if r["direction_rule"] == "FADE"
        and r["latency_ms"] >= 200 and r["filled"] >= 20
        and r["all_four_positive"]
        and r["net_fee10_plus_0_50_slip"] > 0
    ]
    if len(selected) != 2:
        raise ValueError("The predeclared gate changed unexpectedly; do not tune")
    selected.sort(key=lambda r: (r["net_fee10_plus_0_50_slip"], r["filled"]),
                  reverse=True)
    shortlist = []
    for n, r in enumerate(selected, 1):
        shortlist.append({
            "id": f"FADE_FROZEN_{n}",
            "direction_rule": r["direction_rule"],
            "window_ms": r["window_ms"], "jump_usd": r["jump_usd"],
            "latency_ms": r["latency_ms"],
            "targets": r["targets"], "stop_usd": r["stop_usd"],
            "expiry_s": r["expiry_s"], "spread_ceiling_usd": .8,
            "discovery_filled": r["filled"],
            "discovery_fee10_pnl": r["net_bidask_fee10"],
            "discovery_fee10_slippage_0_50_pnl": r["net_fee10_plus_0_50_slip"],
            "discovery_months": r["months"],
        })
    result = {
        "contract": "TH001_UNTOUCHED_MONTH_EVALUATION_FROZEN_20261030",
        "selection_source": "TH001_540_TRIALS_ALL_LOSSES_AND_GAINS.json",
        "selection_rule": "FADE, >=200ms, >=20 bundles in original four months, every month positive after $10/lot fee, total positive after additional $0.50 adverse execution per leg",
        "discovery_months": data["source_months"],
        "validation_months_not_used_in_selection": [
            "202510", "202511", "202512", "202601", "202602",
            "202603", "202604", "202605",
        ],
        "n_trials_seen_before_selection": 540,
        "selected": shortlist,
        "no_independent_prospective_or_broker_validation_claim": True,
    }
    unsigned = json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
    result["frozen_content_sha256"] = hashlib.sha256(unsigned).hexdigest()
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    result = select(args.input)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print("TH001_FROZEN_CANDIDATES", json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
