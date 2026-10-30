"""Aggregate all original-quote TH001 42-case monthly ledgers without cherry-picking.

This is an exploratory IN-SAMPLE GRID, not a holdout or evidence of alpha.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


def aggregate(root: Path):
    files = sorted(root.rglob("grid.json"))
    bymonth = {}
    for f in files:
        payload = json.loads(f.read_text())
        month = payload["month"]
        if month in bymonth:
            raise ValueError("Duplicate monthly grid: " + month)
        if len(payload["cases"]) != 42:
            raise ValueError("Missing case in month: " + month)
        if payload["source"]["original_archive_modified"]:
            raise ValueError("Source was modified: " + month)
        bymonth[month] = payload
    expected = {"202606", "202607", "202608", "202609"}
    if set(bymonth) != expected:
        raise ValueError("Required four independent original months missing: "
                         + repr(set(bymonth) ^ expected))
    groups = defaultdict(dict)
    for month, doc in sorted(bymonth.items()):
        for c in doc["cases"]:
            key = (c["window_ms"], c["trigger_usd"])
            groups[key][month] = c
    if len(groups) != 42:
        raise ValueError("Expected precisely 42 related hypothesis variants")
    cases = []
    for (window_ms, jump), months in sorted(groups.items()):
        if len(months) != 4:
            raise ValueError("Missing variant/month")
        nets = [m["fee10_model_net_usd"] for m in months.values()]
        sample = {
            "window_ms": window_ms, "trigger_usd": jump,
            "trials_in_family": len(groups),
            "totals": {
                "filled_bundles": sum(m["filled_bundles"] for m in months.values()),
                "closed_legs": sum(m["closed_legs"] for m in months.values()),
                "tp_legs": sum(m["tp_legs"] for m in months.values()),
                "stop_legs": sum(m["stop_legs"] for m in months.values()),
                "timeout_legs": sum(m["timeout_legs"] for m in months.values()),
                "net_with_actual_quote_spread_and_10fee_usd": round(sum(nets), 3),
                "net_bidask_before_extra_fee_usd": round(sum(
                    m["model_pnl_without_extra_fees_usd"] for m in months.values()), 3),
                "long_net_before_extra_fee_usd": round(sum(
                    m["long_pnl_before_extra_fees_usd"] for m in months.values()), 3),
                "short_net_before_extra_fee_usd": round(sum(
                    m["short_pnl_before_extra_fees_usd"] for m in months.values()), 3),
                "n_positive_months_after_fee": sum(x > 0 for x in nets),
                "n_negative_months_after_fee": sum(x < 0 for x in nets),
                "all_four_positive": all(x > 0 for x in nets),
            },
            "monthly": {
                m: {
                    "filled": x["filled_bundles"],
                    "net_after_fee": x["fee10_model_net_usd"],
                    "long_gross": x["long_pnl_before_extra_fees_usd"],
                    "short_gross": x["short_pnl_before_extra_fees_usd"],
                } for m, x in sorted(months.items())
            },
        }
        cases.append(sample)
    ranked = sorted(cases, key=lambda z: (-z["totals"]["net_with_actual_quote_spread_and_10fee_usd"],
                                         -z["totals"]["filled_bundles"]))
    qualified = [c for c in ranked if c["totals"]["filled_bundles"] >= 20
                 and c["totals"]["n_positive_months_after_fee"] >= 3]
    baseline = next(c for c in cases if c["trigger_usd"] == 3 and c["window_ms"] == 1500)
    return {
        "phase": "EXPLORATORY_GRID_NO_HOLDOUT",
        "date_scope": sorted(bymonth),
        "n_related_variants": len(cases),
        "no_independent_winners_claimed": True,
        "untouched_holdout_used": False,
        "historical_broker_execution_verified": False,
        "baseline": baseline,
        "n_positive_overall": sum(c["totals"]["net_with_actual_quote_spread_and_10fee_usd"] > 0
                                  for c in cases),
        "n_positive_all_four": sum(c["totals"]["all_four_positive"] for c in cases),
        "ranked": ranked,
        "qualified_exploratory_min20_three_positive_months": qualified,
        "original_source_hashes": {k: d["source"]["original_zip_sha256"]
                                  for k, d in sorted(bymonth.items())},
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    result = aggregate(args.root)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print("TH001_AGGREGATE_GRID", json.dumps({
        "baseline": result["baseline"],
        "n_related_variants": result["n_related_variants"],
        "n_positive_overall": result["n_positive_overall"],
        "n_positive_all_four": result["n_positive_all_four"],
        "top12": result["ranked"][:12],
        "qualified_exploratory": result["qualified_exploratory_min20_three_positive_months"][:10],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
