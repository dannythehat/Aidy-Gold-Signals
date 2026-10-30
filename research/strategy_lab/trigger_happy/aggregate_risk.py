"""Reconcile all 540 related TH001 entry/exit trials against four raw tick months.

No optimistic cherry-picking: every tested configuration and monthly loss remains.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


def trial_key(r):
    return (r["direction_rule"], r["window_ms"], r["jump_usd"],
            r["latency_ms"], tuple(r["targets"]), r["stop_usd"],
            r["time_exit_seconds"])


def assemble(root: Path):
    docs = {}
    for p in sorted(root.rglob("risk_grid.json")):
        d = json.loads(p.read_text())
        if d["period"] in docs:
            raise ValueError("Duplicate source month")
        if d["trial_count"] != 540 or len(d["all_results"]) != 540:
            raise ValueError("Incomplete source month: " + d["period"])
        docs[d["period"]] = d
    if set(docs) != {"202606", "202607", "202608", "202609"}:
        raise ValueError("Required four historical months not present: " + str(sorted(docs)))
    groups = defaultdict(dict)
    for month, d in sorted(docs.items()):
        for r in d["all_results"]:
            key = trial_key(r)
            if month in groups[key]:
                raise ValueError("Duplicate config in month: " + month)
            groups[key][month] = r
    if len(groups) != 540:
        raise ValueError("Missing or duplicated complete family of 540 trials")
    ranked = []
    for key, m in groups.items():
        if len(m) != 4:
            raise ValueError("Incomplete monthly cohort")
        mode, window, jump, latency, targets, stop, expiry = key
        values = list(m.values())
        n = sum(x["filled"] for x in values)
        net = round(sum(x["fee10_net_usd"] for x in values), 3)
        stress = round(sum(x["fee10_plus_extra_0_50usd_slippage_per_closed_leg"]
                           for x in values), 3)
        long_price = sum(x["long_quote_net_usd"] for x in values)
        short_price = sum(x["short_quote_net_usd"] for x in values)
        long_legs = sum(x["long_closed_legs"] for x in values)
        short_legs = sum(x["short_closed_legs"] for x in values)
        month_net = {k: v["fee10_net_usd"] for k, v in sorted(m.items())}
        ranked.append({
            "direction_rule": mode, "window_ms": window,
            "jump_usd": jump, "latency_ms": latency,
            "targets": list(targets), "stop_usd": stop, "expiry_s": expiry,
            "filled": n, "closed_legs": sum(x["closed_legs"] for x in values),
            "tp_legs": sum(x["tp_legs"] for x in values),
            "stop_legs": sum(x["stop_legs"] for x in values),
            "net_bidask_fee10": net, "net_fee10_plus_0_50_slip": stress,
            "long_net_fee10": round(long_price - long_legs * .1, 3),
            "short_net_fee10": round(short_price - short_legs * .1, 3),
            "pos_months": sum(v > 0 for v in month_net.values()),
            "all_four_positive": all(v > 0 for v in month_net.values()),
            "months": {
                mth: {"filled": r["filled"], "net_fee10": r["fee10_net_usd"],
                      "net_stress": r["fee10_plus_extra_0_50usd_slippage_per_closed_leg"],
                      "long_net_fee10": round(
                          r["long_quote_net_usd"] - r["long_closed_legs"] * .1, 3),
                      "short_net_fee10": round(
                          r["short_quote_net_usd"] - r["short_closed_legs"] * .1, 3)}
                for mth, r in sorted(m.items())
            },
        })
    ranked.sort(key=lambda r: (r["net_bidask_fee10"], r["filled"]), reverse=True)
    active = [r for r in ranked if r["filled"] >= 20]
    # Distinguish 50ms optimistic scenario from more conservative delays.
    conservative = [r for r in active if r["latency_ms"] >= 200]
    return {
        "label": "TH001_540_RELATED_EXPLORATORY_TRIALS_NO_LIVE_EXECUTION",
        "source_months": sorted(docs),
        "original_source_hashes": {k: d["provenance"]["original_zip_sha256"]
                                  for k, d in sorted(docs.items())},
        "n_related_configs": len(ranked),
        "n_positive_with_fee": sum(r["net_bidask_fee10"] > 0 for r in ranked),
        "n_positive_after_extra_slip": sum(
            r["net_fee10_plus_0_50_slip"] > 0 for r in ranked),
        "n_all_four_positive": sum(r["all_four_positive"] for r in ranked),
        "n_positive_with_min20": sum(r["net_bidask_fee10"] > 0 for r in active),
        "n_positive_all4_with_min20_conservative": sum(
            r["all_four_positive"] and r["net_fee10_plus_0_50_slip"] > 0
            for r in conservative),
        "top_by_pnl_all_trials": ranked[:15],
        "top_with_min20_filled": active[:15],
        "top_with_min20_and_latency_at_least_200ms": conservative[:15],
        "top_follow_min20": [r for r in active if r["direction_rule"] == "FOLLOW"][:10],
        "top_fade_min20": [r for r in active if r["direction_rule"] == "FADE"][:10],
        "top_by_long_net_after_fee_min20": sorted(
            active, key=lambda r: r["long_net_fee10"], reverse=True)[:10],
        "top_by_short_net_after_fee_min20": sorted(
            active, key=lambda r: r["short_net_fee10"], reverse=True)[:10],
        "all_results": ranked,
        "data_snooping_warning": "540 related configurations reviewed on the same four historical months: NO independent winner or OOS conclusion",
        "paper_ready": False,
        "broker_fill_verified": False,
    }


def main():
    a = argparse.ArgumentParser()
    a.add_argument("--root", type=Path, required=True)
    a.add_argument("--out", type=Path, required=True)
    args = a.parse_args()
    result = assemble(args.root)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print("TH001_RISK_AGGREGATE", json.dumps({
        k: v for k, v in result.items()
        if k not in {"all_results", "original_source_hashes"}
    }, sort_keys=True))


if __name__ == "__main__":
    main()
