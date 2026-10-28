"""Gold Hunter forward-calendar 2026 source replay. Research only, not a sealed holdout.

Requires original AIDY R2 tick archives and CROSSFI RE's independent
2026 archive verification output. Never downloads prices opportunistically,
changes live state, sends orders, or substitutes synthetic observations.
"""
from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pandas as pd

from gold_hunter.bible_engine import (
    FAMILIES, Parameters, build_candidate_tape, research_backtest, validate_h1,
)

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "artifacts/strategy_lab/crossfire_2026_holdout_result"
OUT = ROOT / "artifacts/gold_hunter/bible_2026"
KEYS = [
    ("COMBINED", FAMILIES),
    ("TREND_ONLY", tuple(x for x in FAMILIES if x.startswith("TREND_"))),
    ("RANGE_ONLY", tuple(x for x in FAMILIES if x.startswith("RANGE_"))),
] + [(x, (x,)) for x in FAMILIES]


def run() -> dict:
    csv_path = SOURCE / "verified_2026_bidask_h1.csv"
    upstream_path = SOURCE / "crossfire_2026_full_ledger.json"
    if not csv_path.is_file() or not upstream_path.is_file():
        raise ValueError("Missing independently verified original 2026 quote source")
    upstream = json.loads(upstream_path.read_text(encoding="utf-8"))
    receipts = upstream.get("source_receipts")
    if (upstream.get("status") != "PASS_2026_9_MONTH_HISTORICAL_SOURCE_AND_MODEL"
            or not isinstance(receipts, list) or len(receipts) != 10
            or upstream.get("paper_orders") != 0
            or upstream.get("broker_stopout_or_liquidation_model_proven") is not False
            or [r.get("source_month_fixed_est") for r in receipts] !=
               ["202512"] + [f"2026{m:02d}" for m in range(1, 10)]):
        raise ValueError("Original 2026 historical-source qualification failed")
    with csv_path.open(encoding="utf-8", newline="") as stream:
        source = pd.DataFrame(csv.DictReader(stream))
    for col in ("open", "high", "low", "close",
                "observed_open_ask", "observed_open_spread", "observed_max_spread"):
        source[col] = pd.to_numeric(source[col], errors="raise")
    source["m1_count"] = pd.to_numeric(source["m1_count"], errors="raise").astype(int)
    clean = validate_h1(source)
    dates = clean["open_time_utc"]
    if (len(clean) < 3000 or dates.min() < pd.Timestamp("2026-01-01", tz="UTC")
            or dates.max() >= pd.Timestamp("2026-10-01", tz="UTC")
            or set(dates.dt.strftime("%Y-%m").unique()) !=
               {f"2026-{m:02d}" for m in range(1, 10)}):
        raise ValueError("Incomplete or out-of-period true 2026 market history")
    if (source["observed_open_ask"] < source["open"]).any():
        raise ValueError("Observed original ASK below BID")
    spread = source["observed_open_spread"]
    spread_stats = {
        "min": float(spread.min()), "median": float(spread.median()),
        "p95": float(spread.quantile(.95)), "max": float(spread.max()),
    }
    results: dict = {}
    configs = {
        "base": Parameters(),
        "stress": replace(Parameters(), spread_usd_oz=.80,
                          slip_usd_oz_each_side=.25,
                          commission_usd_oz_roundtrip=.14),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    for scenario, cfg in configs.items():
        tape = build_candidate_tape(clean, cfg)
        for name, families in KEYS:
            packet = research_backtest(clean, cfg=cfg, families=families,
                                       candidate_tape=tape)
            key = f"{name}_{scenario}"
            if (packet["closed_trades"] != len(packet["trades"])
                    or packet["price_rows"] != len(clean)):
                raise ValueError("Cannot reconcile full authentic 2026 trade ledger")
            (OUT / f"{key}.json").write_text(
                json.dumps(packet, sort_keys=True, indent=2, allow_nan=False) + "\n",
                encoding="utf-8")
            results[key] = {
                k: packet[k] for k in ("closed_trades", "win_rate_percent",
                                      "net_modelled_usd", "ending_equity_usd",
                                      "max_marked_drawdown_percent",
                                      "unrealized_open_position", "result_sha256")
            }
    report = {
        "status": "RESEARCH_2026_LATER_PERIOD_COMPLETED",
        "period": "2026-01-01_to_2026-09-30_UTC",
        "not_referee_sealed_holdout": True,
        "development_2025_not_retuned_on_2026_results": True,
        "real_native_tick_archive_receipts": 10,
        "source_h1_rows": len(clean),
        "source_csv_sha256": hashlib.sha256(csv_path.read_bytes()).hexdigest(),
        "original_archives_sha256": [r["input_zip_sha256"] for r in receipts],
        "observed_original_spread_usd_per_oz": spread_stats,
        "simulation_spread_is_fixed_not_observed": True,
        "broker_realised_returns_verified": False,
        "live_orders": 0,
        "results": results,
    }
    report["sha256"] = hashlib.sha256(json.dumps(
        report, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()).hexdigest()
    (OUT / "report.json").write_text(json.dumps(
        report, sort_keys=True, indent=2, allow_nan=False) + "\n",
        encoding="utf-8")
    print("GOLD_HUNTER_REAL_2026_REPLAY", json.dumps(results, sort_keys=True), flush=True)
    return report


if __name__ == "__main__":
    try:
        run()
    except Exception as exc:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "blocked_result.json").write_text(json.dumps({
            "status": "BLOCKED_REAL_2026_SOURCE_OR_ENGINE",
            "error_type": type(exc).__name__, "reason": str(exc)[:400],
            "no_synthetic_substitute": True, "live_orders": 0,
        }, indent=2) + "\n", encoding="utf-8")
        raise
