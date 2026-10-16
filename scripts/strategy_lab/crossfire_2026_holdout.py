"""Nine complete months Jan-Sep 2026: unchanged S010 vs two FROZEN tweaks.

No 2026 tuning, no trade orders, no 2026 October partial archive.
Uses genuine source 10 fixed EST ZIPs (Dec2025 warmup + Jan-Sep2026).
Every raw original tick archive receives a provenance receipt.
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from aidy.strategy_lab_crossfire_2026_variants import (
    RESEARCH_CONTRACT, VARIANT_KEYS, replay,
)
from aidy.strategy_lab_crossfire_tick_2021 import FORMAT
from aidy.strategy_lab_s010_backtest import BASE, STRESS

MONTHS = ("202512",) + tuple(f"2026{n:02d}" for n in range(1, 10))
START = datetime(2026, 1, 1, tzinfo=UTC)
END = datetime(2026, 10, 1, tzinfo=UTC)
OUT = Path("artifacts/strategy_lab/crossfire_2026_holdout_result")


def collect(input_root: Path, output: Path = OUT) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    files = sorted(input_root.glob("crossfire-2026-*/receipt.json"))
    if len(files) != len(MONTHS):
        raise ValueError(f"Expected {len(MONTHS)} source months, got {len(files)}")
    all_rows = []
    receipts = []
    for month, path in zip(MONTHS, files, strict=True):
        receipt = json.loads(path.read_text(encoding="utf-8"))
        if (path.parent.name != f"crossfire-2026-{month}"
                or receipt["source_month_fixed_est"] != month
                or receipt["normalisation"] != FORMAT
                or receipt["raw_source_modified"] is not False
                or receipt["broker_ask_executable"] is not False
                or len(receipt["input_zip_sha256"]) != 64
                or receipt["source_tick_rows"] < 1000):
            raise ValueError("Wrong source month or invalid original archive")
        with (path.parent / "hourly.csv").open(
            newline="", encoding="utf-8",
        ) as stream:
            rows = list(csv.DictReader(stream))
        for row in rows:
            row["m1_count"] = int(row["m1_count"])
            for k in ("open", "high", "low", "close",
                      "observed_open_ask", "observed_open_spread",
                      "observed_max_spread"):
                row[k] = float(row[k])
            if (row["observed_open_ask"] < row["open"]
                    or row["observed_open_spread"] < 0
                    or row["observed_max_spread"] < 0):
                raise ValueError("Original market BID/ASK quote geometry invalid")
        digest = hashlib.sha256(json.dumps(
            rows, sort_keys=True, separators=(",", ":"),
        ).encode()).hexdigest()
        if digest != receipt["derived_h1_sha256"]:
            raise ValueError("Tampered derived monthly quote snapshot")
        receipts.append(receipt)
        all_rows.extend(rows)
    year = [
        row for row in all_rows
        if START <= datetime.fromisoformat(row["open_time_utc"]) < END
    ]
    if len(year) < 3000:
        raise ValueError("Insufficient real Jan-Sep2026 H1 BID source coverage")
    frame = pd.DataFrame(year)
    dates = pd.to_datetime(frame["open_time_utc"], utc=True)
    if not dates.is_monotonic_increasing or dates.duplicated().any():
        raise ValueError("Overlapping 2026 source-month seams")
    counts = dates.dt.strftime("%Y-%m").value_counts()
    if set(counts.index) != {f"2026-{n:02d}" for n in range(1, 10)}:
        raise ValueError("2026 calendar months missing, or partial October included")
    if any(n < 150 for n in counts.to_list()):
        raise ValueError("Incomplete 2026 historical month")
    scenarios = {key: replay(frame, key) for key in VARIANT_KEYS}
    # Entry-cost stress replicates the frozen 2025 B/A sensitivity scenario.
    stress = {key: replay(frame, key, costs=STRESS) for key in VARIANT_KEYS}
    for version in (scenarios, stress):
        for key, result in version.items():
            if (result["bars"] != len(year) or len(result["monthly"]) != 9
                    or result["closed_trades"] != len(result["trades"])):
                raise ValueError("Unreconciled full-year ledger: " + key)
    spread = frame["observed_open_spread"]
    source_spread = {
        "count": len(spread),
        "min_usd_per_oz": round(float(spread.min()), 4),
        "median_usd_per_oz": round(float(spread.median()), 4),
        "p95_usd_per_oz": round(float(spread.quantile(.95)), 4),
        "max_usd_per_oz": round(float(spread.max()), 4),
    }
    valid_atr_candidate = (
        scenarios["atr3_initial_stop"]["net_marked_pnl_usd"] > 0
        and scenarios["atr3_initial_stop"]["max_marked_drawdown_pct"] > -35
        and scenarios["atr3_initial_stop"]["closed_trades"] >= 30
        and stress["atr3_initial_stop"]["net_marked_pnl_usd"] > 0
    )
    payload = {
        "schema": RESEARCH_CONTRACT,
        "status": "PASS_2026_9_MONTH_HISTORICAL_SOURCE_AND_MODEL",
        "strategy_id": "S010",
        "working_brand": "CROSSFIRE",
        "source": "original HistData immutable XAUUSD BID/ASK tick source R2",
        "period_utc": "2026-01-01 to 2026-09-30",
        "source_est_months": list(MONTHS),
        "test_frozen_before_observing_2026_outcomes": True,
        "source_original_ticks": sum(x["source_tick_rows"] for x in receipts),
        "source_inversion_pairs": sum(x["source_order_inversions"] for x in receipts),
        "complete_h1_bars": len(year),
        "source_receipts": receipts,
        "historical_ask_spread": source_spread,
        "broker_specific_vantage_ask_or_swaps_proven": False,
        "broker_stopout_or_liquidation_model_proven": False,
        "broker_paper_account_connected": False,
        "paper_orders": 0,
        "original_rules_params_changed": False,
        "frozen_variants": {
            "original": "MA12/34 + RSI14 long-only with 3.28x",
            "atr3_initial_stop":
                "Unmodified entries+opposite exits plus 3x prior ATR14 initial BID stop",
            "sma200_rising_filter":
                "Only buy if previous H1 close above rising SMA200 vs 24 H1 ago",
        },
        "costs_base_assumed": vars(BASE),
        "costs_stress_assumed": vars(STRESS),
        "base": scenarios,
        "stress": stress,
        "atr_candidate_historical_screen": valid_atr_candidate,
        "paper_trial_review_eligibility": (
            "CONDITIONAL_REVIEW_ONLY" if valid_atr_candidate
            else "FAILED_PREDECLARED_2026_SCREEN"
        ),
        "no_live_trading_permission": True,
    }
    payload["full_evidence_sha256"] = hashlib.sha256(json.dumps(
        {"receipts": receipts, "base": scenarios, "stress": stress},
        sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()
    (output / "crossfire_2026_full_ledger.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8",
    )
    with (output / "verified_2026_bidask_h1.csv").open(
        "w", newline="", encoding="utf-8",
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(year[0]))
        writer.writeheader()
        writer.writerows(year)
    for key, result in scenarios.items():
        with (output / f"{key}_trades.csv").open(
            "w", newline="", encoding="utf-8",
        ) as handle:
            if result["trades"]:
                writer = csv.DictWriter(
                    handle, fieldnames=list(result["trades"][0]),
                )
                writer.writeheader()
                writer.writerows(result["trades"])
        with (output / f"{key}_monthly.csv").open(
            "w", newline="", encoding="utf-8",
        ) as handle:
            writer = csv.DictWriter(
                handle, fieldnames=list(result["monthly"][0]),
            )
            writer.writeheader()
            writer.writerows(result["monthly"])
    summary = {
        "status": payload["status"],
        "period": payload["period_utc"],
        "verified_months": 9,
        "true_source_month_archives": len(receipts),
        "native_source_ticks": payload["source_original_ticks"],
        "total_source_inversions": payload["source_inversion_pairs"],
        "H1_bars": len(year),
        "observed_spread_usd_per_oz": source_spread,
        "model_results": {
            k: {
                metric: v[metric] for metric in (
                    "net_marked_pnl_usd", "marked_return_pct",
                    "ending_marked_equity_usd", "max_marked_drawdown_pct",
                    "closed_trades", "wins", "losses", "profit_factor",
                    "sum_paid_execution_cost_usd",
                )
            } for k, v in scenarios.items()
        },
        "stressed_return_pct": {
            k: v["marked_return_pct"] for k, v in stress.items()
        },
        "atr_candidate_historical_screen": valid_atr_candidate,
        "paper_trial_review_eligibility":
            payload["paper_trial_review_eligibility"],
        "source_evidence_sha256": payload["full_evidence_sha256"],
        "broker_net_results_claimed": False,
    }
    (output / "crossfire_2026_verdict.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
        "artifacts/strategy_lab/crossfire_2026_source"
    )
    try:
        result = collect(root)
        print("CROSSFIRE_2026_HOLDOUT_RESULT", json.dumps(result,sort_keys=True), flush=True)
        return 0
    except Exception as exc:  # noqa: BLE001 - archive actual blocker; never fabricate performance
        OUT.mkdir(parents=True,exist_ok=True)
        reason = {"status":"BLOCKED_REAL_2026_DATA_OR_LEDGER",
                  "error_type": type(exc).__name__,
                  "error": str(exc)[:500],
                  "paper_trial_review_eligibility":"BLOCKED",
                  "broker_orders":0}
        (OUT / "blocked_run.json").write_text(json.dumps(reason,indent=2)+"\n")
        print("CROSSFIRE_2026_HOLDOUT_BLOCKED",json.dumps(reason),flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
