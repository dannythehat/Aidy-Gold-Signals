"""External-paper-inspired XAUUSD abnormal-day reversal, AIDY original quotes.

Research source: Caporale & Plastun (2021), Gold and oil prices: abnormal
returns, momentum and contrarian effects, DOI 10.1007/s11408-021-00380-w.
They describe a next-day contrarian gold effect after an abnormal return day.

INDEPENDENT PREDECLARED ADAPTATION, NOT verbatim publisher execution rules:
  * full UTC days only, at least 20 verified full M1-derived H1 bars/day;
  * define daily open-to-close return, abnormal if > 2 population standard
    deviations from the trailing 60 PREVIOUS complete trading days (min 50);
  * after event day is completely closed, open next available trading day
    at its first H1 original BID/ASK opening quote in opposite direction;
  * exit at >=06:00 UTC or >=20:00 UTC of entry day, first available H1 open;
  * isolate same-direction 6h momentum control, for falsification;
  * 1 XAUUSD ounce, annual $10k reset; two fixed cost scenarios;
  * no tuning, no broker orders, no synthetic prices.

Cannot claim source-native trading parity: 2021 paper's GMT+3 intraday timing,
dynamic sample length and original research timings differ from fixed UTC
independent hypotheses. Paper 2009-2020 history vs AIDY 2023-2025 history;
years are retrospective DEVELOPMENT, not unseen OOS. No financing or margin.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.gold_hunter_web_gaussmacd_research import YEARS, prices

PAPER = "https://doi.org/10.1007/s11408-021-00380-w"
ROLL = 60
MIN_ROLL = 50
SIGMA = 2.0
START = 10_000.0
OUNCES = 1.0
MODES = {
    "NEXT_DAY_REVERSAL_06UTC": (-1, 6),
    "NEXT_DAY_REVERSAL_20UTC": (-1, 20),
    "NEXT_DAY_MOMENTUM_06UTC_CONTROL": (+1, 6),
}


def digest(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def qualified_days(h: pd.DataFrame) -> pd.DataFrame:
    """No future days enter historical mean/std threshold."""
    if not h.index.is_monotonic_increasing or h.index.has_duplicates:
        raise ValueError("Non-monotone or duplicated source H1")
    daily = h.groupby(h.index.date).agg(
        first_utc=("open", lambda z: z.index[0]),
        last_utc=("close", lambda z: z.index[-1]),
        open_bid=("open", "first"),
        close_bid=("close", "last"),
        bar_count=("close", "size"),
    )
    daily.index = pd.to_datetime(daily.index, utc=True)
    daily = daily[daily["bar_count"] >= 20].copy()
    if daily.empty:
        raise ValueError("No complete enough trading days")
    daily["daily_return"] = daily["close_bid"] / daily["open_bid"] - 1
    past = daily["daily_return"].shift(1)
    daily["past_mean"] = past.rolling(ROLL, min_periods=MIN_ROLL).mean()
    daily["past_sigma"] = past.rolling(ROLL, min_periods=MIN_ROLL).std(ddof=0)
    daily["event_side"] = np.where(
        daily["past_sigma"].gt(0)
        & (daily["daily_return"] > daily["past_mean"] + SIGMA * daily["past_sigma"]), 1,
        np.where(
            daily["past_sigma"].gt(0)
            & (daily["daily_return"] < daily["past_mean"] - SIGMA * daily["past_sigma"]), -1, 0))
    return daily


def run_mode(h: pd.DataFrame, daily: pd.DataFrame, name: str, slip: float,
             commission: float) -> dict:
    direction, expiry_utc_hour = MODES[name]
    cash = START
    peak = cash
    worst = 0.
    trades = []
    monthly = defaultdict(float)
    skipped = defaultdict(int)
    days = list(daily.index)
    for i in range(len(days)-1):
        event_day, follow_day = days[i], days[i+1]
        event = daily.loc[event_day]
        if not event["event_side"]:
            continue
        # Weekend can be three days; no inference of unseen calendar quote gaps.
        if (follow_day-event_day).days > 4:
            skipped["large_calendar_gap"] += 1
            continue
        today = h.loc[(h.index.normalize() == follow_day)]
        if today.empty:
            skipped["no_follow_day"] += 1
            continue
        entry_row, entry_at = today.iloc[0], today.index[0]
        if entry_at.hour > 2:
            skipped["late_entry"] += 1
            continue
        later = today.loc[today.index.hour >= expiry_utc_hour]
        if later.empty:
            skipped["missing_exit_quote"] += 1
            continue
        exit_row, exit_at = later.iloc[0], later.index[0]
        side = int(-event["event_side"] if direction == -1
                   else event["event_side"])
        entry_px = float(entry_row["ask_o"] if side == 1 else entry_row["open"])
        entry_px += side*slip
        exit_px = float(exit_row["open"] if side == 1 else exit_row["ask_o"])
        exit_px -= side*slip
        pnl = (exit_px-entry_px)*side*OUNCES-commission*OUNCES
        cash += pnl
        # Drawdown is based on closed trade equity; mark-to-market intra-trade
        # drawdown is NOT observable from these entry/exit-only accounting marks.
        peak = max(peak, cash)
        worst = min(worst, 100*(cash/peak-1))
        month = exit_at.strftime("%Y-%m")
        monthly[month] += pnl
        trades.append({
            "event_day": event_day.strftime("%Y-%m-%d"),
            "event_direction": int(event["event_side"]),
            "threshold_mean": round(float(event["past_mean"]), 8),
            "threshold_stdev": round(float(event["past_sigma"]), 8),
            "event_return": round(float(event["daily_return"]), 8),
            "side": side, "entry_utc": entry_at.isoformat(),
            "exit_utc": exit_at.isoformat(), "entry_price": round(entry_px, 6),
            "exit_price": round(exit_px, 6), "pnl_usd": round(pnl, 6),
        })
    if abs(sum(t["pnl_usd"] for t in trades)-(cash-START)) > .002:
        raise ValueError("Realized cash ledger failed to reconcile")
    months = [{"month": f"{h.index[0].year}-{m:02d}",
               "realized_net_usd": round(monthly.get(
                   f"{h.index[0].year}-{m:02d}", 0.), 4)} for m in range(1, 13)]
    gp = sum(max(t["pnl_usd"], 0) for t in trades)
    gl = -sum(min(t["pnl_usd"], 0) for t in trades)
    result = {
        "model": name, "source": PAPER, "source_native_parity": False,
        "initial_usd": START, "end_usd": round(cash, 2),
        "realized_net_usd": round(cash-START, 2),
        "closed_trades": len(trades),
        "wins": sum(t["pnl_usd"] > 0 for t in trades),
        "profit_factor": round(gp/gl, 3) if gl else None,
        "max_closed_equity_drawdown_pct": round(worst, 3),
        "intratrade_drawdown_not_measured": True,
        "event_days": int((daily["event_side"] != 0).sum()),
        "skipped": dict(skipped), "slippage_per_side": slip,
        "commission_roundtrip_per_oz": commission,
        "monthly": months, "trades": trades,
        "no_broker_orders": True,
    }
    result["sha256"] = digest(result)
    return result


def research(root: Path, out: Path) -> dict:
    report = {"schema": "aidy.outside_academic.gold_nextday_abnormal.v1",
              "paper": PAPER, "sourced_mechanism": "abnormal day followed by gold reversal",
              "independently_set_UTC_hours_not_author_rules": [6, 20],
              "threshold": {"previous_trading_days": ROLL,
                            "minimum_available": MIN_ROLL, "standard_deviations": SIGMA},
              "research_only": True, "sealed_oos": False, "broker_orders": 0,
              "data_original": "authenticated XAUUSD spot BID/ASK M1 from PR374",
              "years": {}}
    for year in YEARS:
        h, provenance = prices(root, year)
        days = qualified_days(h)
        results = {}
        for cost_name, slip, commission in (
            ("base", .05, 0.), ("stress", .25, .14)
        ):
            results[cost_name] = {}
            for name in MODES:
                item = run_mode(h, days, name, slip, commission)
                p = out/str(year)/cost_name
                p.mkdir(parents=True, exist_ok=True)
                (p/f"{name}.json").write_text(
                    json.dumps(item, sort_keys=True, indent=2, allow_nan=False)+"\n")
                results[cost_name][name] = {
                    k: item[k] for k in ("realized_net_usd", "closed_trades",
                                         "wins", "profit_factor",
                                         "max_closed_equity_drawdown_pct",
                                         "event_days", "sha256")
                }
        report["years"][str(year)] = {
            "source_receipts": provenance, "day_count": len(days),
            "results": results}
    report["sha256"] = digest(report)
    out.mkdir(parents=True, exist_ok=True)
    (out/"report.json").write_text(json.dumps(report, sort_keys=True,
                                              indent=2, allow_nan=False)+"\n")
    print("AIDY_ABNORMAL_DAY_RESEARCH", json.dumps(
        {year: {name: vals["realized_net_usd"]
                for name, vals in item["results"]["stress"].items()}
         for year, item in report["years"].items()}, sort_keys=True))
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--quotes", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    args = p.parse_args()
    try:
        research(args.quotes, args.out)
    except Exception as exc:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out/"BLOCKED.json").write_text(json.dumps({
            "status": "NO_RESULT", "exception_type": type(exc).__name__,
            "market_data_substitution": False, "broker_orders": 0},
            indent=2)+"\n")
        raise
