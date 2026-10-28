"""Pinned original S020-S031 setup/R replay; never fabricate account-level P&L.

Publisher implements an overlapping per-setup R scorecard, not lot sizing or an
account. Native R and separately labelled cost/R sensitivity are reported, with
causal-prefix/fill defects exposed. No source is silently repaired.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from scripts.oracle_gold.batch01 import blob
from scripts.oracle_gold.build_register import EXTRACTED
from scripts.oracle_gold.history import digest, load_snapshot

ROOT = Path(__file__).resolve().parents[2]
PIN = ROOT/"research/gold_oracle/batch02_source_pin.json"


def originals(root):
    pin = json.loads(PIN.read_text())
    for path, expected in pin["files"].items():
        if blob((root/path).read_bytes()) != expected:
            raise ValueError("Original sweep source changed: "+path)
    sys.path.insert(0, str(root/"src"))
    from sweepbt.models import Candle
    from sweepbt.params import Params
    from sweepbt.strategies import run_strategy
    from sweepbt.trend import apply_trend_filter
    return Candle, Params, run_strategy, apply_trend_filter


def entries(setups, before):
    return Counter((s.direction, s.entry_index, s.entry_price, s.stop_loss,
                    s.take_profit, s.trigger_index, s.resolve_index)
                   for s in setups if s.entry_index < before)


def dump_csv(path, rows, fields=None):
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields or (list(rows[0]) if rows else ["status"]))
        w.writeheader()
        if rows:
            w.writerows(rows)


def outcome_summary(rows, cost, kept_only):
    selected = [r for r in rows if (not kept_only or r["trend_filter_kept"]) and r["outcome"] != "unresolved"]
    if any(r["risk_distance"] <= 0 for r in selected):
        raise ValueError("Nonpositive source risk distance")
    net = [r["native_r"]-cost/r["risk_distance"] for r in selected]
    win = sum(v for v in net if v > 0)
    loss = -sum(v for v in net if v < 0)
    return {"closed_setups": len(selected), "unresolved": sum(r["outcome"] == "unresolved" for r in rows if not kept_only or r["trend_filter_kept"]),
        "native_total_R": sum(r["native_r"] for r in selected),
        "illustrative_cost_per_oz_round_trip": cost,
        "cost_adjusted_total_R": sum(net),
        "cost_adjusted_mean_R": sum(net)/len(net) if net else None,
        "positive_setups": sum(v > 0 for v in net), "negative_setups": sum(v < 0 for v in net),
        "profit_factor_R": win/loss if loss else None,
        "largest_costed_R": max(net) if net else None,
        "net_R_without_largest": sum(net)-max(net) if net else None,
        "account_net_usd": None, "account_drawdown": None,
        "qualification": "DIAGNOSTIC_R_SCORECARD_NOT_EXECUTABLE_ACCOUNT"}


def replay(snapshot, publisher, out):
    Candle, Params, run_strategy, apply_filter = originals(publisher)
    raw, manifest = load_snapshot(snapshot)
    year = pd.Timestamp(raw[0]["open_time_utc"]).year
    if {pd.Timestamp(r["open_time_utc"]).year for r in raw} != {year}:
        raise ValueError("Mixed research years")
    candles = [Candle(i, r["open"], r["high"], r["low"], r["close"],
                      timestamp=pd.Timestamp(r["open_time_utc"]).to_pydatetime())
               for i, r in enumerate(raw)]
    params = Params.for_timeframe("H1")
    result = {"schema": "oracle.gold.batch02.native_r.v1", "year": year,
        "source_snapshot_sha256": manifest["rows_sha256"], "data_manifest": manifest,
        "publisher_commit": json.loads(PIN.read_text())["commit"],
        "native_H1_preset": asdict(params), "models": {},
        "USD_accounts_simulated": 0, "source_originals_modified": False,
        "sealed_oos": False, "orders": 0,
        "scope": "H1 source preset chosen before results, not a uniquely selected original catalogue timeframe"}
    folder = out/str(year)
    folder.mkdir(parents=True, exist_ok=True)
    for ident, (method, _rule, known_blocker) in EXTRACTED.items():
        native = run_strategy(method, candles, params)
        # Source's own EMA trend tag. Preserve BOTH original filter-off/on views.
        apply_filter(native, candles, params)
        cuts = (len(candles)//2, 3*len(candles)//4)
        prefix = []
        for cut in cuts:
            partial = run_strategy(method, candles[:cut], params)
            # Compare entry geometry only; outcome is necessarily future-dependent.
            a, b = entries(native, cut-8), entries(partial, cut-8)
            prefix.append({"cut": cut, "geometry_equal": a == b,
                           "full_only": sum((a-b).values()), "prefix_only": sum((b-a).values())})
        rows = []
        for n, s in enumerate(native, 1):
            bar = candles[s.entry_index]
            sign = 1 if s.direction == "long" else -1
            flags = []
            if not bar.low <= s.entry_price <= bar.high:
                flags.append("SOURCE_ENTRY_OUTSIDE_ENTRY_BAR_RANGE")
            if (s.entry_price-s.stop_loss)*sign <= 0 or (s.take_profit-s.entry_price)*sign <= 0:
                flags.append("INVALID_DIRECTIONAL_STOP_OR_TARGET")
            if s.trigger_index > s.entry_index:
                flags.append("ENTRY_BEFORE_TRIGGER")
            if ident in ("S021", "S022"):
                flags.append("CONFIRM_AT_CLOSE_BUT_BOOK_PRIOR_INTRABAR_LEVEL")
            row = {"setup_id": n, "strategy_id": ident, "direction": s.direction,
                "trigger_bar_open_utc": candles[s.trigger_index].timestamp.isoformat(),
                "entry_bar_open_utc": bar.timestamp.isoformat(),
                "native_entry_price": s.entry_price, "stop": s.stop_loss, "target": s.take_profit,
                "risk_distance": s.risk, "outcome": s.verdict, "native_r": s.r_multiple,
                "exit_bar_open_utc": candles[s.exit_index].timestamp.isoformat() if s.exit_index is not None else None,
                "native_exit_price": s.exit_price, "trend_filter_kept": s.filter_kept,
                "source_execution_flags": "|".join(flags)}
            rows.append(row)
        dump_csv(folder/f"{ident}_native_setups.csv", rows)
        scenarios = {f"{filter_name}/{name}": outcome_summary(rows, cost, on)
            for filter_name, on in (("filter_off", False), ("source_EMA_filter_on", True))
            for name, cost in (("native_no_cost", 0.), ("common_base", .47), ("common_stress", 1.44))}
        model = {"source_method": method, "setup_count": len(rows), "prefix_tests": prefix,
            "prefix_geometry_stable_on_tested_cuts": all(x["geometry_equal"] for x in prefix),
            "setups_with_execution_flags": sum(bool(r["source_execution_flags"]) for r in rows),
            "known_source_blocker": known_blocker, "scenarios": scenarios,
            "status": "NATIVE_SOURCE_R_DIAGNOSTIC_ONLY_NO_ACCOUNT_PARITY",
            "execution_qualified": False, "independence_proven": False,
            "ledger_sha256": digest(rows)}
        result["models"][ident] = model
        print("B02_SOURCE", year, ident, len(rows), "prefix", model["prefix_geometry_stable_on_tested_cuts"], flush=True)
    result["sha256"] = digest(result)
    (folder/"report.json").write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False)+"\n")
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--snapshot", required=True, type=Path)
    p.add_argument("--publisher", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    args = p.parse_args()
    replay(args.snapshot, args.publisher, args.out)


if __name__ == "__main__":
    main()
