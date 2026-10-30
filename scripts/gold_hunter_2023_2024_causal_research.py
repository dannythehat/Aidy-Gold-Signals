"""AIDY Gold Hunter 2023/24 authentic quote-cache extension; RESEARCH ONLY.

Consumes PR374's separately authenticated original BID+ASK M1 derivatives.
No BigQuery/R2 fetches, broker network, arbitrary external source or production
writes. Frozen v0 ledgers from 2025/26 are untouched. This is a new V2 causal
entry-admission replay (not source-native broker parity or sealed OOS).
"""
from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

from gold_hunter.open_strategy_lab import (
    Settings, SYSTEMS, signal_tape, replay_causal_v2,
)

ROOT = Path(__file__).resolve().parents[1]
YEARS = (2023, 2024)
FAMILIES = {name: (name,) for name in SYSTEMS}
FAMILIES["DONCHIAN_PREVDAY_COMPOSITE"] = (
    "DONCHIAN_TREND", "PREV_DAY_BREAKOUT",
)


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def digest(value: dict) -> str:
    return sha(json.dumps(value, sort_keys=True, separators=(",", ":"),
                          allow_nan=False).encode())


def read_month(root: Path, period: str) -> tuple[pd.DataFrame, dict]:
    folder = root / period
    marker = folder / "manifest.json"
    file = folder / "bidask.csv"
    if not marker.is_file() or not file.is_file():
        raise ValueError(f"Missing independently authenticated month {period}")
    m = json.loads(marker.read_text(encoding="utf-8"))
    original_sha = m.pop("sha256", None)
    if (m.get("schema") != "oracle.gold.bidask_m1.v1"
            or digest(m) != original_sha
            or m.get("csv_sha256") != sha(file.read_bytes())
            or m.get("receipt", {}).get("period_fixed_est") != period
            or m.get("receipt", {}).get("raw_modified") is not False):
        raise ValueError(f"Source BID/ASK manifest integrity mismatch {period}")
    if period.startswith("2023") and not m["receipt"].get("prior2023_identity_verified"):
        raise ValueError(f"2023 immutable original archive identity unavailable: {period}")
    with file.open(newline="", encoding="utf-8") as handle:
        df = pd.DataFrame(csv.DictReader(handle))
    if len(df) != m["rows"] or len(df) < 1000:
        raise ValueError(f"Source row count mismatch {period}")
    df["open_time_utc"] = pd.to_datetime(df["open_time_utc"], utc=True, errors="raise")
    fields = ("bid_o", "bid_h", "bid_l", "bid_c", "ask_o", "ask_h",
              "ask_l", "ask_c", "spread_mean", "ticks")
    for key in fields:
        df[key] = pd.to_numeric(df[key], errors="raise")
    if (df["open_time_utc"].isna().any()
            or df["open_time_utc"].duplicated().any()
            or not df["open_time_utc"].is_monotonic_increasing
            or not np.isfinite(df[list(fields)].to_numpy()).all()
            or (df["ticks"] < 1).any()
            or (df["spread_mean"] < 0).any()
            or (df["ask_o"] < df["bid_o"]).any()
            or (df["ask_h"] < df["bid_h"]).any()
            or (df["ask_l"] < df["bid_l"]).any()
            or (df["open_time_utc"].dt.second != 0).any()):
        raise ValueError(f"Noncausal, duplicated or corrupt M1 quotes {period}")
    m["sha256"] = original_sha
    return df, {"period": period, "manifest_sha256": original_sha,
                "m1_sha256": m["csv_sha256"], "rows": len(df),
                "source_zip_sha256": m["receipt"]["archive_sha256"]}


def build_h1(minutes: pd.DataFrame) -> pd.DataFrame:
    """Admit only UTC hours with 60 complete, non-duplicated M1 observations."""
    if minutes.empty:
        raise ValueError("Empty market history")
    x = minutes.sort_values("open_time_utc").set_index("open_time_utc")
    if (x.index.has_duplicates or not x.index.is_monotonic_increasing
            or (x.index.minute != x.index.floor("min").minute).any()):
        raise ValueError("Bad M1 chronology")
    res = x.resample("1h").agg(
        open=("bid_o", "first"), high=("bid_h", "max"),
        low=("bid_l", "min"), close=("bid_c", "last"),
        observed_open_ask=("ask_o", "first"),
        opening_bid=("bid_o", "first"),
        minute_max_mean_spread=("spread_mean", "max"),
        m1_count=("bid_o", "count"),
    )
    # Strict 60-minute completeness: every minute exactly once with no gaps.
    res = res.loc[res["m1_count"] == 60].copy()
    res["observed_open_spread"] = res["observed_open_ask"] - res["opening_bid"]
    res["observed_max_spread"] = res[
        ["minute_max_mean_spread", "observed_open_spread"]].max(axis=1)
    res = res.drop(columns=["opening_bid", "minute_max_mean_spread"])
    if res.empty or (res["observed_open_spread"] < 0).any():
        raise ValueError("No admissible full H1 source bars")
    return res.reset_index(names="open_time_utc")


def source_year(root: Path, year: int) -> tuple[pd.DataFrame, dict]:
    if year not in YEARS:
        raise ValueError("Only frozen years 2023/2024 allowed")
    # 2024-01 00-04 UTC belongs to fixed-EST 202312 archive.
    periods = ([f"{year - 1}12"] if year == 2024 else []) + [
        f"{year}{m:02d}" for m in range(1, 13)
    ]
    blocks, provenance = [], []
    for period in periods:
        chunk, receipt = read_month(root, period)
        blocks.append(chunk)
        provenance.append(receipt)
    df = pd.concat(blocks, ignore_index=True)
    df = df.loc[df["open_time_utc"].dt.year == year].copy()
    if df.empty or df["open_time_utc"].duplicated().any():
        raise ValueError("Incomplete or overlapping chronological research archive")
    df = df.sort_values("open_time_utc")
    h1 = build_h1(df)
    if (len(h1) < 4500 or set(h1["open_time_utc"].dt.month) != set(range(1, 13))):
        raise ValueError("Year missing required source months or complete H1 coverage")
    return h1, {
        "source": "PR374 original authenticated R2 spot XAUUSD BID+ASK tick derivatives",
        "source_periods": provenance,
        "market_m1_observations": len(df),
        "complete_h1_rows": len(h1),
        "hourly_data_sha256": sha(h1.to_csv(index=False).encode()),
        "broker_source_parity": False,
        "source_has_2022_december_warmup": False if year == 2023 else True,
        "missing_2022_december_2023_initial_hours_disclosed": year == 2023,
        "quote_warning": "Observed first-minute ASK/open spread; max per-minute MEAN spread is an intrahour retrospective proxy, NOT the true contemporaneous tick maximum or price-extreme-aligned ASK.",
        "not_sealed_holdout": True,
    }


def run_year(h1: pd.DataFrame, year: int, out: Path) -> dict:
    df, tape = signal_tape(h1)
    results = {}
    for scenario, settings in {
        "base": Settings(observed_quote_mode=True),
        "stress": replace(Settings(observed_quote_mode=True),
                          spread_floor=.80, slippage_per_side=.25,
                          roundtrip_commission_per_oz=.14),
    }.items():
        results[scenario] = {}
        for name, component_ids in FAMILIES.items():
            r = replay_causal_v2(df, tape, component_ids, settings)
            if (r["closed_trades"] != len(r["trades"])
                    or abs(sum(t["pnl_usd"] for t in r["trades"])
                           - r["realized_net_usd"]) > .06
                    or abs(sum(m["realized_net_usd"] for m in r["monthly"])
                           - r["realized_net_usd"]) > .15
                    or len(r["monthly"]) != 12):
                raise ValueError(f"Trade/annual monthly ledger mismatch: {year}/{scenario}/{name}")
            output = out / str(year) / scenario
            output.mkdir(parents=True, exist_ok=True)
            (output / f"{name}.json").write_text(
                json.dumps(r, indent=2, sort_keys=True, allow_nan=False) + "\n",
                encoding="utf-8",
            )
            results[scenario][name] = {
                key: r[key] for key in (
                    "closed_trades", "net_marked_usd", "realized_net_usd",
                    "max_marked_drawdown_pct", "profit_factor", "sha256",
                    "months_above_10_pct", "net_ex_largest_winner_usd",
                )
            }
    return results


def main(root: Path, dest: Path) -> dict:
    report = {"schema": "gold_hunter.2023_2024_original_source_causal_v2",
              "research_only": True, "paper_or_live_orders": 0,
              "untouched_oos": False, "source_or_rules_reoptimized": False,
              "legacy_2025_2026_ledgers_changed": False,
              "model": "v2_causal_open_spread_at_entry",
              "unverified": ["financing", "margin", "lot size",
                             "native broker execution", "stop/target order within H1"],
              "years": {}}
    for year in YEARS:
        source, trace = source_year(root, year)
        report["years"][str(year)] = {
            "trace": trace, "results": run_year(source, year, dest)}
    report["sha256"] = digest(report)
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8")
    print("GOLD_HUNTER_2023_2024_CAUSAL_V2", json.dumps(
        {year: {name: v["net_marked_usd"]
                for name, v in item["results"]["stress"].items()}
         for year, item in report["years"].items()}, sort_keys=True))
    return report


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--quotes", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        main(args.quotes, args.out)
    except Exception as exc:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "BLOCKED.json").write_text(json.dumps({
            "status": "NOT_TESTED", "error_type": type(exc).__name__,
            "research_only": True, "broker_orders": 0,
            "no_synthetic_substitute": True,
        }, indent=2) + "\n", encoding="utf-8")
        raise
