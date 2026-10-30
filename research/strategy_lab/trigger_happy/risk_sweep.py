"""TH-001 controlled follow-vs-fade exit, latency and jump-size research.

Related variants, deliberately NOT independent profitable strategies.
Each test is against an immutable original source month and its separately
chronologically normalized actual BID/ASK quote stream. No broker writes.
"""
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from research.strategy_lab.trigger_happy.grid_sweep import (
    load_source,
    replay,
    verify_and_sort,
)

SPEC = "TH001_RISK_V01B_20261030_EXPLORATORY"
WINDOWS_MS = (1500, 3000, 5000)
JUMP_USD = (3., 5., 7.)
LATENCIES_MS = (50, 200, 500)
SIDES = (1, -1)
# Fixed BEFORE checking results: (targets, stop, timeout seconds)
RISK_PROFILES = (
    ((2., 4., 8.), 4., 300),
    ((2., 4., 8.), 2., 300),
    ((2., 4., 8.), 6., 300),
    ((4., 8., 12.), 3., 300),
    ((4., 8., 12.), 4., 300),
    ((4., 8., 12.), 6., 300),
    ((6., 12., 20.), 4., 300),
    ((6., 12., 20.), 6., 300),
    ((8., 16., 24.), 8., 300),
    ((4., 8., 12.), 4., 60),
)
# Status quo 2026 frozen official baseline; guard prevents accidental rewriting.
SOURCE_FROZEN_BASELINE_PNL = {
    "202606": -521.649, "202607": -260.059,
    "202608": -319.034, "202609": -424.613,
}
OZ_PER_LOT_ASSUMED = 100.
LOT_PER_TP_LEG = .01
HYPOTHETICAL_FEE_USD_PER_STANDARD_LOT = 10.


def run_sweep(ts, bid, ask):
    records = []
    for mode in SIDES:
        for w in WINDOWS_MS:
            for jump in JUMP_USD:
                for latency in LATENCIES_MS:
                    for (tps, stop, expiry) in RISK_PROFILES:
                        v = replay(
                            ts, bid, ask, w * 1000, jump, latency * 1000,
                            stop, tps[0], tps[1], tps[2],
                            expiry * 1_000_000, .8, mode,
                        )
                        closed_legs = int(v[6])
                        quote_net = float(v[7])
                        # Fee model charges every closed leg. No swap or further
                        # broker slippage included; worse gap stops ARE included.
                        fee = closed_legs * LOT_PER_TP_LEG * HYPOTHETICAL_FEE_USD_PER_STANDARD_LOT
                        friction_extra = closed_legs * LOT_PER_TP_LEG * OZ_PER_LOT_ASSUMED * .50
                        records.append({
                            "direction_rule": "FOLLOW" if mode == 1 else "FADE",
                            "window_ms": w, "jump_usd": jump,
                            "latency_ms": latency,
                            "targets": list(tps), "stop_usd": stop,
                            "time_exit_seconds": expiry, "spread_cap_usd": .8,
                            "signals": int(v[0]), "filled": int(v[1]),
                            "canceled": int(v[2]),
                            "tp_legs": int(v[3]), "stop_legs": int(v[4]),
                            "time_legs": int(v[5]), "closed_legs": closed_legs,
                            "raw_quote_net_usd": round(quote_net, 3),
                            "fee10_net_usd": round(quote_net - fee, 3),
                            "fee10_plus_extra_0_50usd_slippage_per_closed_leg": round(
                                quote_net - fee - friction_extra, 3),
                            "long_fills": int(v[10]), "short_fills": int(v[11]),
                            "long_quote_net_usd": round(float(v[8]), 3),
                            "short_quote_net_usd": round(float(v[9]), 3),
                            "long_closed_legs": int(v[12]), "short_closed_legs": int(v[13]),
                            "broker_execution_verified": False,
                            "profitable_strategy_claim": False,
                        })
    if len(records) != (len(SIDES) * len(WINDOWS_MS) * len(JUMP_USD)
                        * len(LATENCIES_MS) * len(RISK_PROFILES)):
        raise ValueError("Trial registry completeness failure")
    return records


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--archive", type=Path, required=True)
    p.add_argument("--period", required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    with tempfile.TemporaryDirectory(prefix="th001_exit_sweep_") as tmp:
        sorted_csv, prov = verify_and_sort(args.archive, args.period, Path(tmp))
        ts, bid, ask = load_source(sorted_csv, args.period, prov["original_tick_rows"])
        # Require bit-for-bit numeric parity to the older evidence register.
        baseline = replay(ts, bid, ask, 1_500_000, 3.)
        if args.period in SOURCE_FROZEN_BASELINE_PNL:
            expected = SOURCE_FROZEN_BASELINE_PNL[args.period]
            if abs(round(float(baseline[7]), 3) - expected) > 0.0001:
                raise ValueError(f"Baseline historical evidence regression {args.period}: "
                                 f"got {baseline[7]}, expected {expected}")
        records = run_sweep(ts, bid, ask)
    args.out.mkdir(parents=True, exist_ok=True)
    doc = {
        "version": SPEC, "period": args.period, "provenance": prov,
        "trial_count": len(records), "frozen_baseline_reference_net": round(float(baseline[7]), 3),
        "risk_profiles": [
            {"tps": list(tps), "stop": stop, "timeout_s": expiry}
            for tps, stop, expiry in RISK_PROFILES
        ],
        "all_results": records, "exploratory_related_variants": True,
        "no_paper_approval": True, "no_broker_trade_executed": True,
        "true_broker_latency_not_verified": True,
    }
    (args.out / "risk_grid.json").write_text(json.dumps(doc, sort_keys=True, indent=2) + "\n")
    best_by_mode = {}
    for mode in ("FOLLOW", "FADE"):
        viable = [r for r in records if r["direction_rule"] == mode and r["filled"] >= 5]
        best_by_mode[mode] = sorted(viable, key=lambda r: r["fee10_net_usd"], reverse=True)[:5]
    print("TH001_RISK_SWEEP_RESULT", json.dumps({
        "month": args.period, "original_ticks": prov["original_tick_rows"],
        "baseline_parity": round(float(baseline[7]), 3),
        "trials": len(records),
        "positive_total_with_fees": sum(x["fee10_net_usd"] > 0 for x in records),
        "positive_after_extra_slip": sum(
            x["fee10_plus_extra_0_50usd_slippage_per_closed_leg"] > 0 for x in records),
        "best_with_at_least_5_fills": best_by_mode,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
