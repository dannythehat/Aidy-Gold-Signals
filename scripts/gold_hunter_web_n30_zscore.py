"""External MIT Gold EA core hypothesis: closed-bar M1 Z reversion + costs.

Pinned original external code (never executed):
https://github.com/n30dyn4m1c/gold-pro-scalper
XAU_Quant_Reversion_TickRobust.mq5 git blob:
b72fa09abe789b80be6e9c7028c16409f3b35bb4
License: MIT, copyright 2026 Neo Malesa.

SOURCE-INSPIRED RESEARCH SUBSET, NOT COMPLETE MQL5 PORT:
* last closed M1 Z-score extreme >= 2.2 and momentum turn confirmed;
* M1 ATR14, cost gates SD >= 3*spread and room-to-mean >=4*spread;
* ADX14 <=22, H1 SMA50 alignment (COMPLETED hours only);
* max spread .50 USD under UNVERIFIED assumption SYMBOL_POINT=.01;
* UTC 10-20 research time; original broker-server time unknown;
* stop max($8,2.5 ATR) and fixed TP at prior M1 SMA, max 40min;
* one ounce fixed per separate hypothetical $10k annual account;
* genuine original M1 BID/ASK OHLC quotes from AIDY's authenticated cache.

DIFFERENCES: Original EA uses balance-based lots, dynamic daily loss limits,
USD red-folder economic-calendar gate, breakeven/trailing, mean-drift TP
updates, 15min loss cooldown, native Wilder ATR/ADX, its broker symbol
time/point/lot/commission, and tick-level fills. ALL unimplemented here:
never assert source-native parity, an executable real broker system, OOS or
live profitability. This is only a first-pass mechanism falsification.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.gold_hunter_2023_2024_causal_research import read_month

YEARS = (2023, 2024, 2025)
SOURCE = "https://github.com/n30dyn4m1c/gold-pro-scalper"
SOURCE_BLOB = "b72fa09abe789b80be6e9c7028c16409f3b35bb4"
START = 10_000.
MAX_SPREAD = .50  # original 50 broker points; 0.01 point is NOT verified.


def digest(v):
    return hashlib.sha256(json.dumps(v, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def year_minutes(root: Path, year: int):
    if year not in YEARS:
        raise ValueError("Unexpected source year")
    periods = ([f"{year-1}12"] if year in (2024, 2025) else []) + [
        f"{year}{month:02d}" for month in range(1, 13)
    ]
    parts, receipts = [], []
    for period in periods:
        part, proof = read_month(root, period)
        parts.append(part)
        receipts.append(proof)
    minute = pd.concat(parts, ignore_index=True)
    minute = minute[minute["open_time_utc"].dt.year == year].copy()
    if minute["open_time_utc"].duplicated().any():
        raise ValueError("Duplicate or overlapping authenticated source minutes")
    minute = minute.sort_values("open_time_utc").reset_index(drop=True)
    if len(minute) < 280_000 or set(minute["open_time_utc"].dt.month) != set(range(1, 13)):
        raise ValueError("Year lacks comprehensive original M1 source")
    return minute, {"periods": receipts, "rows": len(minute),
                    "rows_sha256": hashlib.sha256(
                        minute.to_csv(index=False).encode()).hexdigest()}


def wilder_mean(x: pd.Series, n: int):
    # EWMA alpha1/n is a research approximation, not MT5 native seed parity.
    return x.ewm(alpha=1/n, adjust=False, min_periods=n).mean()


def features(df: pd.DataFrame):
    """Time-indexed, shifted-by-one CLOSED BAR features only."""
    m = df.set_index("open_time_utc").copy()
    close = m["bid_c"]
    ma = close.rolling(20, min_periods=20).mean().shift(1)
    sd = close.rolling(20, min_periods=20).std(ddof=0).shift(1)
    previous = close.shift()
    tr = pd.concat([m["bid_h"]-m["bid_l"],
                    (m["bid_h"]-previous).abs(),
                    (m["bid_l"]-previous).abs()], axis=1).max(axis=1)
    atr = wilder_mean(tr, 14).shift(1)
    up, down = m["bid_h"].diff(), -m["bid_l"].diff()
    pos = pd.Series(np.where((up > down) & (up > 0), up, 0.), index=m.index)
    neg = pd.Series(np.where((down > up) & (down > 0), down, 0.), index=m.index)
    sm_pos = wilder_mean(pos, 14)
    sm_neg = wilder_mean(neg, 14)
    atr_w = wilder_mean(tr, 14)
    plus = 100 * sm_pos / atr_w
    minus = 100 * sm_neg / atr_w
    dx = 100 * (plus-minus).abs() / (plus+minus).replace(0, np.nan)
    adx = wilder_mean(dx, 14).shift(1)
    # 50 already COMPLETED H1 closes, not the not-yet-closed current hour.
    hourly = close.resample("1h", closed="left", label="left").last()
    hourly_count = close.resample("1h", closed="left", label="left").count()
    hourly = hourly.where(hourly_count == 60)
    hmean = hourly.rolling(50, min_periods=50).mean().shift(1)
    # An hourly row labelled HH becomes known only at HH+1. Map by
    # current hour; shifted feature intentionally excludes HH's close.
    hour_index = m.index.floor("h")
    ht = hmean.reindex(hour_index).to_numpy()
    prev_ma = ma.to_numpy()
    prev_sd = sd.to_numpy()
    prev_close = close.shift(1).to_numpy()
    prev_prev_close = close.shift(2).to_numpy()
    z = (prev_close-prev_ma)/np.where(prev_sd > 0, prev_sd, np.nan)
    return {
        "time": m.index,
        "bid_open": m["bid_o"].to_numpy(),
        "bid_hi": m["bid_h"].to_numpy(),
        "bid_lo": m["bid_l"].to_numpy(),
        "bid_close": m["bid_c"].to_numpy(),
        "ask_open": m["ask_o"].to_numpy(),
        "ask_hi": m["ask_h"].to_numpy(),
        "ask_lo": m["ask_l"].to_numpy(),
        "ask_close": m["ask_c"].to_numpy(),
        "prev_close": prev_close, "prev_prev_close": prev_prev_close,
        "ma": prev_ma, "sd": prev_sd, "z": z,
        "atr": atr.to_numpy(), "adx": adx.to_numpy(),
        "h1_sma": ht,
    }


def replay(x: dict, *, slip: float, commission: float):
    n = len(x["time"])
    cash, peak, dd = START, START, 0.
    position = None
    closed = []
    rejects = defaultdict(int)
    cooldown_until = None
    last_day = None
    for i in range(n):
        now = x["time"][i]
        day = now.date()
        if day != last_day:
            last_day = day
        bid_open = float(x["bid_open"][i])
        ask_open = float(x["ask_open"][i])
        spread = ask_open-bid_open
        if not np.isfinite(spread) or spread < 0:
            raise ValueError("Original quoted spread geometry corrupt")
        if position is not None:
            side, sl, tp = position["side"], position["stop"], position["target"]
            if side == 1:
                stop_hit, tp_hit = x["bid_lo"][i] <= sl, x["bid_hi"][i] >= tp
                quote = bid_open
            else:
                stop_hit, tp_hit = x["ask_hi"][i] >= sl, x["ask_lo"][i] <= tp
                quote = ask_open
            since = (now-position["entry_time"]).total_seconds()/60
            reason = ("STOP" if stop_hit else "TARGET" if tp_hit else
                      "TIME_EXIT" if since >= 40 else
                      "FRIDAY_EXIT" if now.weekday()==4 and now.hour >=20 else None)
            if reason:
                price = (min(sl, quote) if side==1 else max(sl, quote)) if stop_hit else (
                    tp if tp_hit else quote)
                price -= side*slip
                pnl = (price-position["entry"])*side-commission
                cash += pnl
                closed.append({
                    "entry_utc": position["entry_time"].isoformat(),
                    "exit_utc": now.isoformat(),
                    "side": side, "reason": reason,
                    "pnl_usd": round(pnl, 6),
                    "entry_price": round(position["entry"], 6),
                    "exit_price": round(price, 6),
                    "initial_stop": position["stop"],
                    "initial_mean_target": position["target"],
                    "source_signal_z": round(position["z"], 5),
                })
                if pnl < 0:
                    cooldown_until = now + pd.Timedelta(minutes=15)
                position = None
        # Intrabar H/L cannot establish actual tick ordering. Stop always first.
        if position is None and now.hour>=10 and now.hour<20 and now.weekday()<5:
            if cooldown_until is not None and now < cooldown_until:
                rejects["cooldown"] += 1
                continue
            z, zma, sd, atr, adx, hma = (
                float(x[k][i]) for k in ("z", "ma", "sd", "atr", "adx", "h1_sma"))
            if not np.isfinite([z,zma,sd,atr,adx,hma]).all() or atr <= 0:
                rejects["warmup_or_missing"] += 1
                continue
            side = 1 if z <= -2.2 else -1 if z >= 2.2 else 0
            if side == 0:
                continue
            if (side == 1 and x["prev_close"][i] < x["prev_prev_close"][i]) or (
                side == -1 and x["prev_close"][i] > x["prev_prev_close"][i]):
                rejects["not_turning"] += 1
                continue
            if adx > 22:
                rejects["ADX"] += 1
                continue
            if spread > MAX_SPREAD:
                rejects["wide_spread"] += 1
                continue
            if sd < 3*spread:
                rejects["sd_vs_cost"] += 1
                continue
            actual_price = ask_open if side == 1 else bid_open
            if (zma-actual_price)*side < 4*spread:
                rejects["mean_room_vs_cost"] += 1
                continue
            if (side == 1 and bid_open <= hma) or (
                side == -1 and bid_open >= hma):
                rejects["h1_trend"] += 1
                continue
            entry = actual_price+side*slip
            risk = max(8., 2.5*atr)  # unverified 0.01 point conversion
            position = {
                "side": side, "entry": entry, "entry_time": now,
                "stop": round(entry-side*risk, 6),
                "target": round(zma, 6), "z": z,
            }
            # Entry-minute stops/limits need intrabar chronology; the model
            # disallows same-minute resolution and labels that optimistic
            # approximation as a critical parity blocker.
        # Account drawdown from realized cash ONLY. Intratrade risk unmeasured.
        peak = max(peak, cash)
        dd = min(dd, (cash/peak-1)*100)
    if abs(sum(t["pnl_usd"] for t in closed)-(cash-START)) > .005:
        raise ValueError("Trade cash mismatch")
    wins = sum(t["pnl_usd"] > 0 for t in closed)
    gp = sum(max(t["pnl_usd"],0) for t in closed)
    gl = -sum(min(t["pnl_usd"],0) for t in closed)
    result = {
        "source": SOURCE, "source_blob": SOURCE_BLOB,
        "source_native_parity": False,
        "one_ounce_fixed_untested_native_lot": True,
        "year_start_usd": START, "end_realized_usd": round(cash,2),
        "realized_net_usd": round(cash-START,2),
        "closed": len(closed), "wins": wins,
        "win_rate": round(wins/len(closed), 4) if closed else None,
        "profit_factor": round(gp/gl,3) if gl else None,
        "realized_only_max_drawdown_pct": round(dd,3),
        "open_position_censored": bool(position),
        "intratrade_marked_drawdown_measured": False,
        "stop_first_when_ambiguous": True,
        "same_entry_minute_stop_not_modelled": True,
        "no_native_red_news_filter_or_trailing_or_broker_time": True,
        "cost": {"slippage_per_side":slip,"commission_per_oz":commission},
        "rejections": dict(rejects), "trades": closed, "no_orders": True,
    }
    result["sha256"]=digest(result)
    return result


def research(root:Path, dest:Path):
    output={"schema":"aidy.external_mit_n30_tickrobust_mechanism.v1",
            "source_repo":SOURCE, "source_blob":SOURCE_BLOB,
            "source_license":"MIT", "source_native_parity":False,
            "sealed_oos":False, "hypothesis_family":"M1 cost-gated mean reversion",
            "duplicative_with_bollinger_family_possible":True,
            "no_broker_orders":True,"years":{}}
    for year in YEARS:
        m, proof = year_minutes(root,year)
        x = features(m)
        results={}
        for name,slip,fee in (("base",.05,0.),("stress",.25,.14)):
            row=replay(x,slip=slip,commission=fee)
            folder=dest/str(year)
            folder.mkdir(parents=True,exist_ok=True)
            (folder/f"{name}.json").write_text(
                json.dumps(row,indent=2,sort_keys=True,allow_nan=False)+"\n")
            results[name]={k:row[k] for k in (
                "realized_net_usd","closed","wins","profit_factor",
                "realized_only_max_drawdown_pct","open_position_censored","rejections","sha256")}
        output["years"][str(year)]={"source":proof,"results":results}
    output["sha256"]=digest(output)
    (dest/"report.json").write_text(
        json.dumps(output,indent=2,sort_keys=True,allow_nan=False)+"\n")
    print("AIDY_EXTERNAL_N30_ZSCORE",json.dumps(
        {y:{mode:{"net":rec["realized_net_usd"],
                   "closed":rec["closed"],"rejections":rec["rejections"]}
            for mode,rec in v["results"].items()}
         for y,v in output["years"].items()},sort_keys=True),flush=True)
    return output


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--quotes",required=True,type=Path)
    p.add_argument("--out",required=True,type=Path)
    args=p.parse_args()
    try:
        research(args.quotes,args.out)
    except Exception as exc:
        args.out.mkdir(parents=True,exist_ok=True)
        (args.out/"BLOCKED.json").write_text(json.dumps({
            "status":"NO_RESULT","exception_type":type(exc).__name__,
            "no_synthetic_quotes_or_broker_orders":True},indent=2)+"\n")
        raise
