"""Six source-pinned models: original Apex diagnostics and causal S010 signal model.

Publisher engines run ONLY in a no-credentials evaluation job, after exact
blob checks. Apex has known lookahead: its P&L is diagnostic and never graded.
No approximate replacement of original rules, no arbitrary strategy interpreter.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from aidy.strategy_lab_s010_backtest import BASE, STRESS, derive_signals, simulate
from scripts.oracle_gold.history import digest, load_snapshot

APEX_COMMIT = "3dab20e20a846edae9ac6fcf56d6b090dbba9f98"
S010_COMMIT = "61dd6b2dd8b6550f668b828e023d7d808bfd8fbd"
PINS = {
    "engine.py": "41f1b5740314487ed6ea35b3307daf689d8abb6f",
    "strategies.py": "9abe69680df34064923e01236cbf9b77d486c682",
}
# Frozen before any new historical outcomes. S007/S008 have no unique released
# gold preset: enumerate the FIRST combination in original optimize.py, not a
# selected winner. These are explicit source-grid variants, not new bot edges.
CASES = {
    "S005": ("donchian", {"entry_n": 24, "exit_n": 12, "ema_filter": 200},
             {"sl_atr": 2.5}),
    "S006": ("ema_trend", {"fast": 9, "slow": 120, "adx_min": 20},
             {"sl_atr": 2., "trail_atr": 3.5}),
    "S007": ("bollinger_mr", {"bb_n": 20, "bb_k": 2., "rsi_n": 2, "rsi_lo": 15},
             {"sl_atr": 2., "allow_reverse": False}),
    "S008": ("rsi_pullback", {"trend_n": 100, "rsi_n": 2, "buy_below": 10,
                              "exit_above": 55},
             {"sl_atr": 1.5, "allow_reverse": False}),
    "S009": ("session_breakout", {"range_start": 0, "range_end": 6,
                                  "trade_end": 12, "close_hour": 21, "buffer_frac": 0.},
             {"sl_atr": 3., "allow_reverse": False}),
}


def blob(b):
    return hashlib.sha1(b"blob " + str(len(b)).encode() + b"\0" + b).hexdigest()


def pinned_module(name, path, expected):
    if blob(path.read_bytes()) != expected:
        raise ValueError("Publisher blob mismatch: " + path.name)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def publisher_modules(root, source10):
    engine = pinned_module("oracle_publisher_engine", root / "research/engine.py", PINS["engine.py"])
    strategy = pinned_module("oracle_publisher_strategies", root / "research/strategies.py", PINS["strategies.py"])
    original10 = pinned_module("oracle_publisher_s010", source10 / "src/strategy.py",
                              "805c0e52cce1b7d626e5809ba50a78b347f67080")
    return engine, strategy, original10


def csv_out(path, rows):
    if not rows:
        path.write_text("status\nZERO_TRADES\n")
        return
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def metrics(trades, equity, times):
    eq = np.asarray(equity, dtype=float)
    if not np.isfinite(eq).all():
        raise ValueError("Nonfinite equity")
    if abs(sum(t["net_usd"] for t in trades) - (eq[-1] - 10000)) > .05:
        raise ValueError("Closed native ledger does not reconcile")
    peaks = np.maximum.accumulate(np.r_[10000., eq])[1:]
    pnl = [t["net_usd"] for t in trades]
    won, lost = sum(v for v in pnl if v > 0), -sum(v for v in pnl if v < 0)
    monthly, prior = [], 10000.
    frame = pd.DataFrame({"time": times, "equity": eq})
    frame["month"] = pd.to_datetime(frame.time, utc=True).dt.strftime("%Y-%m")
    for month, group in frame.groupby("month", sort=True):
        end = float(group.equity.iloc[-1])
        monthly.append({"month": month, "starting_equity": prior, "ending_equity": end,
                        "net_change_usd": end-prior, "return_pct": (end/prior-1)*100})
        prior = end
    return {"closed_trades": len(trades), "long_trades": sum(t["side"] == "LONG" for t in trades),
            "short_trades": sum(t["side"] == "SHORT" for t in trades),
            "net_usd": float(eq[-1]-10000), "profit_factor": won/lost if lost else None,
            "win_rate_pct": 100*sum(v > 0 for v in pnl)/len(pnl) if pnl else None,
            "max_h1_close_marked_dd_pct": float(np.min(eq/peaks-1)*100),
            "largest_winner_usd": max([0.] + pnl),
            "net_excluding_largest_winner_usd": sum(pnl)-max([0.] + pnl),
            "monthly": monthly, "profitable_months": sum(m["net_change_usd"] > 0 for m in monthly),
            "worst_month_pct": min(m["return_pct"] for m in monthly),
            "intrabar_equity_dd_verified": False}


def run_snapshot(snapshot, out, engine, strategies, original10, *, common_costs=False, causal_probe=None):
    rows, manifest = load_snapshot(snapshot)
    bars = pd.DataFrame(rows)
    x = derive_signals(bars)
    t = x.open_time_utc
    if len(x) < 3500 or t.dt.year.nunique() != 1 or t.dt.month.nunique() != 12:
        raise ValueError("Insufficient full source-month yearly snapshot")
    year = int(t.dt.year.iloc[0])
    out = Path(out) / str(year)
    out.mkdir(parents=True, exist_ok=True)
    # Original code drops warmup before testing crossovers. Compare aligned rows.
    expected = original10.MACrossoverStrategy(12, 34, 14).calculate_indicators(bars.copy(), verbose=False)
    if not np.array_equal(expected.signal.to_numpy(), x.loc[expected.index, "signal"].to_numpy()):
        raise ValueError("S010 original signal parity FAIL")
    models, signal_traces = {}, {}
    for scenario, costs in (("base", BASE), ("stress", STRESS)):
        r = simulate(bars, 3.28, costs)
        csv_out(out / f"S010_{scenario}_trades.csv", r["trades"])
        csv_out(out / f"S010_{scenario}_monthly.csv", r["monthly"])
        csv_out(out / f"S010_{scenario}_equity.csv", r["equity"])
        # S010 original signals, independently defined accounting: NOT native engine parity.
        models[f"S010/{scenario}"] = {**{k: v for k, v in r.items() if k not in ("equity", "trades")},
            "status": "HISTORICAL_LOSS" if r["net_marked_pnl_usd"] < 0 else "HISTORICAL_PROMISING",
            "original_signal_parity": True, "original_execution_parity": False,
            "qualification": "MODELLED_ONLY_NOT_QUALIFIED", "source_commit": S010_COMMIT,
            "largest_closed_winner_usd": max([0.] + [z["net_usd"] for z in r["trades"]]),
            "intrabar_dd_financing_margin_verified": False}
    signal_traces["S010"] = x.signal.to_numpy()
    o, h, l, c = [x[k].to_numpy(float) for k in ("open", "high", "low", "close")]
    at = engine.atr(h, l, c, 14)
    hours, seconds = t.dt.hour.to_numpy(), t.array.as_unit("ns").asi8 // 10**9
    for ident, (method, signal_params, engine_params) in CASES.items():
        kw = dict(signal_params)
        if ident == "S009":
            kw["atr_arr"] = at
        sig = strategies.STRATEGIES[method](o, h, l, c, hours, **kw)
        # Causal prefix parity across several cuts; signal output cannot depend on future.
        for cut in (len(c)//3, len(c)//2, len(c)-1):
            shortkw = {k: (v[:cut] if isinstance(v, np.ndarray) else v) for k, v in kw.items()}
            partial = strategies.STRATEGIES[method](o[:cut], h[:cut], l[:cut], c[:cut], hours[:cut], **shortkw)
            if any(not np.array_equal(a[:cut], b) for a, b in zip(sig, partial)):
                raise ValueError("Publisher signal lookahead " + ident)
        signal_traces[ident] = sig[0].astype(int)-sig[1].astype(int)
        # Preserve native publisher-cost diagnostic; common-cost run is a new
        # named experiment, not a rewrite of the first run's losing outcomes.
        scenario_costs = (("base", .47), ("stress", 1.44)) if common_costs else (("base", .45), ("stress", 1.48))
        for scenario, cost in scenario_costs:
            # Original source unchanged. Admission explicitly BLOCKED by c[i] sizing.
            r = engine.simulate(o, h, l, c, seconds, at, *sig,
                engine.SymbolSpec("XAUUSD", cost=cost, max_leverage=20.),
                engine.EngineParams(**engine_params), 250, len(c))
            parity = {"status": "NOT_RUN", "native_broker_parity": False}
            if causal_probe is not None:
                causal = causal_probe.simulate(o, h, l, c, seconds, at, *sig,
                    causal_probe.SymbolSpec("XAUUSD", cost=cost, max_leverage=20.),
                    causal_probe.EngineParams(**engine_params), 250, len(c))
                same_trades = ([vars(z) for z in r.trades] == [vars(z) for z in causal.trades])
                same_equity = bool(np.array_equal(r.equity, causal.equity, equal_nan=True))
                parity = {"status": "EXACT_LEDGER_AND_EQUITY_PARITY" if same_trades and same_equity else "DIVERGENCE",
                          "same_trades": same_trades, "same_equity": same_equity,
                          "scope": "This tape and these parameters ONLY; latent original defect preserved",
                          "native_broker_parity": False}
            trades = [{"id": i+1, "side": "LONG" if z.dir == 1 else "SHORT",
                       "entry_utc": t.iloc[z.entry_i].isoformat(),
                       "exit_bar_utc": t.iloc[z.exit_i].isoformat(),
                       "entry_bid": z.entry_px, "exit_bid": z.exit_px, "units_oz": z.units,
                       "net_usd": z.pnl, "round_trip_cost_usd": z.units*cost, "exit_reason": z.reason}
                      for i, z in enumerate(r.trades)]
            equity = r.equity[250:]
            summ = metrics(trades, equity, t.iloc[250:].astype(str).tolist())
            csv_out(out / f"{ident}_{scenario}_trades.csv", trades)
            csv_out(out / f"{ident}_{scenario}_monthly.csv", summ["monthly"])
            csv_out(out / f"{ident}_{scenario}_equity.csv",
                    [{"bar_open_utc": dt, "equity_at_bar_close": float(v)}
                     for dt, v in zip(t.iloc[250:].astype(str), equity)])
            models[f"{ident}/{scenario}"] = {**summ,
                "status": "BLOCKED_PUBLISHER_LOOKAHEAD_DIAGNOSTIC_ONLY",
                "original_python_executed": True, "source_commit": APEX_COMMIT,
                "method": method, "signal_params": signal_params, "engine_params": engine_params,
                "warmup_h1_bars": 250, "rt_cost_per_oz_model": cost,
                "lookahead": "engine.open_pos uses c[i] for entry-open leverage sizing",
                "causal_sizing_probe": parity,
                "signals_causal_prefix_checked": True, "native_mql_parity": False,
                "broker_financing_margin_lot_steps_verified": False,
                "selection": "FIRST_SOURCE_GRID_COMBINATION" if ident in ("S007", "S008") else "EXISTING_FROZEN_SOURCE_RESEARCH_PRESET"}
    events = pd.DataFrame({"bar_open_utc": t.astype(str), **signal_traces})
    events.to_csv(out / "signal_events.csv", index=False)
    overlap = []
    ids = sorted(signal_traces)
    for i, a in enumerate(ids):
        for b in ids[i+1:]:
            aa, bb = signal_traces[a], signal_traces[b]
            joint = (aa != 0) & (bb != 0)
            union = (aa != 0) | (bb != 0)
            overlap.append({"a": a, "b": b, "same_hour_same_side": int(((aa == bb)&joint).sum()),
                "any_signal_union": int(union.sum()), "joint_signal_hours": int(joint.sum()),
                "side_correlation_including_zeros": float(np.corrcoef(aa, bb)[0, 1])
                if np.std(aa) and np.std(bb) else None,
                "independence_proven": False})
    report = {"schema": "oracle.gold.batch01.v1", "year": year, "manifest": manifest,
        "source_original_ids_evaluated": sorted(ids), "models": models, "signal_overlap": overlap,
        "source_month_coverage_only_not_market_calendar_certification": True,
        "trial_count_scenarios": len(models), "sealed_oos": False,
        "common_total_round_trip_costs_across_systems": common_costs,
        "cost_scope": "Common .47/1.44 per ounce RT; quote-side timing still engine-specific" if common_costs else "Original publisher .45 and diagnostic1.48 vs S010 .47/1.44; not directly cost-comparable",
        "portfolio": {"status": "BLOCKED", "reason": "Five native engines fail causal sizing; shared broker margin/hedging unverified; no sum of independent $10k accounts"},
        "gaps": ["GAP-APEX-ENTRY-SIZING-LOOKAHEAD", "GAP-SOURCE-MARKET-CALENDAR",
                 "GAP-NATIVE-BROKER-PARITY", "GAP-FINANCING-MARGIN", "GAP-INTRABAR-DD"],
        "orders": 0}
    report["sha256"] = digest(report)
    (out / "report.json").write_text(json.dumps(report, sort_keys=True, indent=2, allow_nan=False)+"\n")
    print("BATCH01_YEAR", json.dumps({"year": year, "sha256": report["sha256"],
        "models": {k: {z: v.get(z) for z in ("status", "closed_trades", "net_usd", "net_marked_pnl_usd")}
                   for k, v in models.items()}}, sort_keys=True), flush=True)
    return report


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--snapshot", type=Path, required=True)
    p.add_argument("--apex", type=Path, required=True)
    p.add_argument("--s010", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--common-costs", action="store_true")
    p.add_argument("--causal-sizing-probe", action="store_true")
    args = p.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    try:
        probe = None
        if args.causal_sizing_probe:
            from scripts.oracle_gold.causal_sizing import causal_sizing_probe
            probe = causal_sizing_probe(args.apex/"research/engine.py")
        run_snapshot(args.snapshot, args.out, *publisher_modules(args.apex, args.s010),
                     common_costs=args.common_costs, causal_probe=probe)
    except Exception as exc:
        (args.out / "BLOCKED.json").write_text(json.dumps({"status": "BLOCKED_BATCH",
            "error_type": type(exc).__name__, "detail": str(exc)[:160]}))
        raise


if __name__ == "__main__":
    main()
