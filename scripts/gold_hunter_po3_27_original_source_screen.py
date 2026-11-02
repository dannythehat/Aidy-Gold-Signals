"""Source-attested PO3 27-grid M5 rejection research on authentic AIDY BID/ASK M1.

Author: Neo Malesa, n30dyn4m1c/po3-indicator, PO3_Scalper.mq5
Pinned Git blob 3fbe3656a445969bf2bc1772fc19c07afbac19a2, MIT
LICENSE blob 296949c39905a3e2499bb85938cfea3afed7cb9c.

RESEARCH SUBSET, NOT native EA or its full two-track portfolio. Implements
the frozen 27-grid M5 default candle rejection, ATR14, 27 state flip,
premium/discount, RR and cooldown. M1 BID/ASK stops/targets are conservative
stop-first if both touch within the same minute. Server time, _Point,
tick size, 0.1 XM micro lot, broker stops, commissions, financing, true
ticks, and simultaneous 9-grid interactions are NOT established. UTC
08:00-21:00, 0.01 point and 1 physical oz are explicit PROXIES.

This script NEVER connects to brokers or trades, and cannot qualify a bot.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.gold_hunter_2023_2024_causal_research import read_month

ORIGINAL_BLOB = "3fbe3656a445969bf2bc1772fc19c07afbac19a2"
LICENSE_BLOB = "296949c39905a3e2499bb85938cfea3afed7cb9c"
ORIGINAL_URL = "https://github.com/n30dyn4m1c/po3-indicator/blob/main/PO3_Scalper.mq5"
SCHEMA = "aidy.po3_27_m5_original_rule_subset.v1"
POINT = 0.01  # unverified broker point size; only a test proxy
GRID = 27.0
START_CASH = 10000.0
OZ = 1.0  # 0.1 original XM micro lots NOT equivalent to 1 oz without contract
SLIP = 0.25  # assumed USD/oz each side
COMMISSION = 0.14  # assumed USD/oz roundtrip
CARRY = 0.09  # assumed annual notional, not actual PU Prime swap
MIN_RANGE = 40 * POINT
SL_FLOOR = 30 * POINT
TOL_FLOOR = 40 * POINT
MAX_SPREAD = 40 * POINT
WARMUP = 305


def digest_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def load_year(root: Path, year: int) -> tuple[pd.DataFrame, list[dict]]:
    if year not in (2023, 2024, 2025):
        raise ValueError("Only 2023/24/25 authenticated M1 artifacts; 2026 M1 not available here")
    periods = ([f"{year-1}12"] if year > 2023 else []) + [
        f"{year}{m:02d}" for m in range(1, 13)
    ]
    chunks, receipts = [], []
    for period in periods:
        df, receipt = read_month(root, period)  # validates original ZIP + manifest and M1 CSV SHA
        chunks.append(df)
        receipts.append(receipt)
    x = pd.concat(chunks, ignore_index=True)
    x = x.loc[x.open_time_utc.dt.year == year].copy()
    x = x.sort_values("open_time_utc").reset_index(drop=True)
    if x.empty or x.open_time_utc.duplicated().any():
        raise ValueError("Missing or duplicated source chronology")
    if len(x) < 250000 or x.open_time_utc.dt.month.nunique() != 12:
        raise ValueError("Incomplete source-year coverage")
    return x, receipts


def m5_bars(m1: pd.DataFrame) -> pd.DataFrame:
    x = m1.set_index("open_time_utc")
    z = x.resample("5min").agg(
        bid_o=("bid_o", "first"), bid_h=("bid_h", "max"),
        bid_l=("bid_l", "min"), bid_c=("bid_c", "last"),
        ask_o=("ask_o", "first"), ask_h=("ask_h", "max"),
        ask_l=("ask_l", "min"), ask_c=("ask_c", "last"),
        count=("bid_o", "count"),
    )
    z = z.loc[z["count"] == 5].copy()
    prev = z.bid_c.shift()
    tr = pd.concat(
        [(z.bid_h-z.bid_l), (z.bid_h-prev).abs(), (z.bid_l-prev).abs()],
        axis=1,
    ).max(axis=1)
    # MT5 ATR seed may differ: original broker-native ATR parity is NOT asserted.
    z["atr"] = tr.ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    return z.reset_index(names="open_time_utc")


def rejects(bar: dict, atr: float, direction: int, level: float) -> bool:
    high, low, op, close = (float(bar[k]) for k in
                            ("bid_h", "bid_l", "bid_o", "bid_c"))
    size = high-low
    if size <= 0 or size < MIN_RANGE:
        return False
    tol = min(max(.25*atr, TOL_FLOOR), .25*GRID)
    buf = .05*atr
    if direction == -1:
        if high < level-tol or close >= level-buf or high > level+1.2*atr:
            return False
        wick = high-max(op,close)
    else:
        if low > level+tol or close <= level+buf or low < level-1.2*atr:
            return False
        wick = min(op,close)-low
    return size <= 9.0 and wick >= .50*size and abs(close-op) <= .45*size


def state_fights(previous: pd.DataFrame, level: float, tol: float,
                 atr: float, direction: int) -> bool:
    """Original ReadLevelState scans the preceding 300 M5 bars, never signal."""
    side = 0
    last_flip = None
    buf = max(.30*atr, POINT)
    # previous rows are in oldest-to-newest order, not including signal bar
    for j, row in enumerate(previous.itertuples(index=False)):
        new_side = 1 if row.bid_c > level+buf else -1 if row.bid_c < level-buf else 0
        if new_side:
            if side and new_side != side:
                last_flip = j
            side = new_side
    if last_flip is None or len(previous)-last_flip > 30:
        return False
    return (direction == 1 and side <= 0) or (direction == -1 and side > 0)


def cooldown_active(last_level: float | None, last_direction: int,
                    last_signal_at: pd.Timestamp | None,
                    level: float, direction: int,
                    signal_at: pd.Timestamp) -> bool:
    """Original track B rejects a repeated same-level/same-direction signal <3 M5 bars."""
    return (last_level is not None and last_signal_at is not None
            and abs(last_level-level) <= 1e-8
            and direction == last_direction
            and pd.Timedelta(0) <= signal_at-last_signal_at
            < pd.Timedelta(minutes=15))


def first_exit(future: pd.DataFrame, direction: int, stop: float,
               target: float) -> tuple[int, str, float]:
    """First observed M1 barrier. Stop wins simultaneous minute ambiguity."""
    if future.empty:
        raise ValueError("No future observed minute for a signal")
    if direction == 1:
        s = future.bid_l.to_numpy() <= stop
        t = future.bid_h.to_numpy() >= target
    else:
        s = future.ask_h.to_numpy() >= stop
        t = future.ask_l.to_numpy() <= target
    idx = np.flatnonzero(s | t)
    if len(idx):
        j = int(idx[0])
        row = future.iloc[j]
        if s[j]:
            px = (min(stop, float(row.bid_o))-SLIP if direction == 1
                  else max(stop, float(row.ask_o))+SLIP)
            return j, "STOP_FIRST_M1", px
        return j, "TARGET_M1", target
    row = future.iloc[-1]
    px = float(row.bid_c if direction == 1 else row.ask_c)
    return len(future)-1, "OPEN_MARK_YEAR_END", px


def screen_year(m1: pd.DataFrame, year: int) -> dict:
    bars = m5_bars(m1)
    if len(bars) < 20000:
        raise ValueError("Too few complete M5 bars")
    b = bars.to_dict("records")
    bt = bars.open_time_utc
    minute_time = m1.open_time_utc
    counts = Counter()
    ledger, signals = [], []
    last_exit = pd.Timestamp(f"{year}-01-01", tz="UTC")
    last_level, last_direction, last_signal_at = None, 0, None
    equity, peak, worst = START_CASH, START_CASH, 0.0
    for i in range(WARMUP, len(b)-1):
        bar, nxt = b[i], b[i+1]
        at = bt.iloc[i]
        entry_at = bt.iloc[i+1]
        if entry_at-at != pd.Timedelta(minutes=5):
            continue
        # UTC proxy for original 08-21 BROKER SERVER time, NOT clock parity.
        if not (8 <= entry_at.hour < 21) or entry_at.dayofweek == 5 or (
            entry_at.dayofweek == 4 and entry_at.hour >= 20
        ):
            continue
        atr = float(bar["atr"])
        if not math.isfinite(atr) or atr <= 0:
            continue
        spread = float(nxt["ask_o"])-float(nxt["bid_o"])
        if spread < 0 or spread > MAX_SPREAD:
            counts["spread"] += 1
            continue
        for direction in (-1, 1):  # source checks short then long
            reach = float(bar["bid_h"] if direction == -1 else bar["bid_l"])
            level = math.floor(reach/GRID+.5)*GRID
            if not rejects(bar, atr, direction, level):
                continue
            counts["rejection_shape"] += 1
            if cooldown_active(last_level, last_direction, last_signal_at,
                               level, direction, at):
                counts["cooldown"] += 1
                continue
            pos = (float(bar["bid_c"])%GRID)/GRID
            if (direction == 1 and pos > .5) or (direction == -1 and pos < .5):
                counts["premium_discount"] += 1
                continue
            tol = min(max(.25*atr, TOL_FLOOR), .25*GRID)
            if state_fights(bars.iloc[i-300:i], level, tol, atr, direction):
                counts["fresh_27_flip"] += 1
                continue
            entry = (float(nxt["ask_o"])+SLIP if direction == 1
                     else float(nxt["bid_o"])-SLIP)
            stop_buffer = max(.35*atr, SL_FLOOR)
            stop = (float(bar["bid_l"])-stop_buffer if direction == 1
                    else float(bar["bid_h"])+stop_buffer)
            # Original PushTarget extends beyond entry when the first grid
            # target is no longer on the profitable side.
            target = level+direction*GRID
            for _ in range(5):
                if direction*(target-entry) > 0:
                    break
                target += direction*GRID
            risk = direction*(entry-stop)
            reward = direction*(target-entry)
            if risk <= 0 or reward < risk:
                counts["risk_reward"] += 1
                continue
            signal = {
                "signal_utc": str(at), "entry_utc": str(entry_at),
                "direction": direction, "level": level, "atr": atr,
                "entry": entry, "stop": stop, "target": target,
            }
            signals.append(signal)
            if entry_at <= last_exit:
                counts["overlap"] += 1
                break
            minute_start = int(minute_time.searchsorted(entry_at))
            if minute_start >= len(m1) or minute_time.iloc[minute_start] != entry_at:
                counts["missing_entry_minute"] += 1
                break
            # Original EA forcibly flattens on Friday at 20 BROKER time.
            # Use 20 UTC proxy, not an asserted match to XM/PU Prime clocks.
            days_to_friday = (4-entry_at.dayofweek) % 7
            cutoff = entry_at.normalize() + pd.Timedelta(
                days=days_to_friday, hours=20)
            if cutoff <= entry_at:
                cutoff += pd.Timedelta(days=7)
            cutoff_idx = int(minute_time.searchsorted(cutoff))
            future = m1.iloc[minute_start:cutoff_idx]
            j, reason, exit_px = first_exit(future, direction, stop, target)
            exit_row = m1.iloc[minute_start+j]
            exit_at = exit_row.open_time_utc
            if reason == "OPEN_MARK_YEAR_END" and cutoff_idx < len(m1):
                exit_row = m1.iloc[cutoff_idx]
                exit_at = exit_row.open_time_utc
                exit_px = (float(exit_row.bid_o)-SLIP if direction == 1
                           else float(exit_row.ask_o)+SLIP)
                reason = "FRIDAY_FLATTEN_20UTC_PROXY"
            hours = max(0.0, (exit_at-entry_at).total_seconds()/3600)
            carry = entry*OZ*CARRY*hours/(365*24)
            net = direction*(exit_px-entry)*OZ-COMMISSION*OZ-carry
            equity += net
            peak = max(peak, equity)
            worst = min(worst, equity/peak-1)
            ledger.append({
                **signal, "exit_utc": str(exit_at), "exit": exit_px,
                "reason": reason, "carry_usd": carry, "net_usd": net,
                "equity_after_usd": equity,
            })
            last_exit = exit_at
            last_level, last_direction, last_signal_at = level, direction, at
            counts["fills_modelled"] += 1
            break
    if not ledger:
        return {"year": year, "signals": len(signals), "trades": 0,
                "net_usd": 0.0, "verdict": "ZERO_EXECUTABLE_MODEL_FILLS",
                "ledger": ledger, "signal_tape": signals, "counts": dict(counts)}
    wins = sum(max(0.0, x["net_usd"]) for x in ledger)
    losses = -sum(min(0.0, x["net_usd"]) for x in ledger)
    return {
        "year": year, "signals": len(signals), "trades": len(ledger),
        "net_usd": round(equity-START_CASH, 2),
        "profit_factor": round(wins/losses, 4) if losses else None,
        "closed_event_equity_dd_pct": round(100*worst, 3),
        "largest_winner_removed_net_usd": round(
            equity-START_CASH-max(x["net_usd"] for x in ledger), 2),
        "open_marks": sum(x["reason"]=="OPEN_MARK_YEAR_END" for x in ledger),
        "ledger": ledger, "signal_tape": signals, "counts": dict(counts),
    }


def save_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def run(root: Path, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    result = {
        "schema": SCHEMA, "source": ORIGINAL_URL, "source_git_blob": ORIGINAL_BLOB,
        "source_mit_license_blob": LICENSE_BLOB, "source_original_native_parity": False,
        "one_family": True, "track": "B_27_GRID_M5_ONLY",
        "not_run": ["A_9_GRID_M1", "both_track_interaction", "2026_M1"],
        "historical_quote_source": "AIDY authenticated original R2 BIDASK M1 derivatives",
        "research_only": True, "broker_orders": 0, "paper_or_live_approval": False,
        "point_size_proxy": POINT, "utc_server_clock_proxy": True,
        "one_oz_model_not_original_lots": True,
        "assumed_costs": {"slippage_each_side_usd_per_oz": SLIP,
                          "roundtrip_commission_usd_per_oz": COMMISSION,
                          "annual_notional_carry": CARRY},
        "unknown": ["native EA 2-track parity", "MT5 iATR seed", "server timezone",
                    "actual _Point and spread points", "broker stop levels",
                    "PU Prime lot size/margin/commission/swap", "intraminute tick ordering",
                    "real contract 0.1 XM micro lot ounces", "true untouched OOS"],
        "years": {},
    }
    for year in (2023, 2024, 2025):
        m1, receipts = load_year(root, year)
        outcome = screen_year(m1, year)
        folder = out/str(year)
        folder.mkdir(exist_ok=True)
        save_csv(folder/"trades.csv", outcome.pop("ledger"))
        save_csv(folder/"signals.csv", outcome.pop("signal_tape"))
        outcome["trade_ledger_sha256"] = digest_file(folder/"trades.csv")
        outcome["signal_tape_sha256"] = digest_file(folder/"signals.csv")
        outcome["source_receipts"] = receipts
        outcome["m1_count"] = len(m1)
        result["years"][str(year)] = outcome
        print("PO3_27_SOURCE_SCREEN", year, outcome["trades"], outcome["net_usd"], flush=True)
    (out/"summary.json").write_text(json.dumps(result, indent=2, sort_keys=True,
                                                allow_nan=False)+"\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--quotes", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    run(args.quotes, args.out)
