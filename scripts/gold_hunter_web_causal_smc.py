"""Independently corrected causal H1 sweep + FVG gold hypothesis, research only.

External source audited (MIT): frankabingale1111/smc-backtest,
smc_backtest/smc_backtest.py git blob 04328b6232950022cf71f5cf02a257c63a73a7ec.
Original source mixes H4 current candle with incomplete hours (resample/ffill),
uses backward filling for early ATR, and FVG test low_i>low_i-2 where
a true bullish three-candle imbalance requires low_i>HIGH_i-2.
DO NOT reproduce or advertise the upstream source's published returns.

This implementation uses fully completed H4 candles and previous trading-day
levels only, real source BID/ASK H1 snapshots, next H1 opening execution, stop
first and conservative costs. Two variants are the SAME mechanism family:
8-point bias + EITHER sweep OR FVG (author's score-style screen);
12-point bias + BOTH sweep and FVG (confluence).
The original author's source-native execution parity remains UNPROVEN.
All three calendar years are retrospective development, no sealed OOS.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

from gold_hunter.bible_engine import validate_h1
from gold_hunter.open_strategy_lab import Settings, replay_causal_v2
from scripts.gold_hunter_2023_2024_causal_research import source_year

SOURCE = "https://github.com/frankabingale1111/smc-backtest"
BLOB = "04328b6232950022cf71f5cf02a257c63a73a7ec"
YEARS = (2023, 2024, 2025)
SCORE8 = "CAUSAL_SMC_SCORE8"
STRICT12 = "CAUSAL_SMC_CONFLUENCE12"
GROUPS = {
    SCORE8: (SCORE8,),
    STRICT12: (STRICT12,),
}


def digest(x):
    return hashlib.sha256(json.dumps(x, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def make_tape(raw):
    """No current unfinished higher timeframe nor future-filled series."""
    df = validate_h1(raw).copy()
    df = df.sort_values("open_time_utc").reset_index(drop=True)
    times = df["open_time_utc"]
    closes = times + pd.Timedelta(hours=1)
    c,h,l = df["close"], df["high"], df["low"]
    tr = pd.concat([h-l, (h-c.shift()).abs(), (l-c.shift()).abs()],
                   axis=1).max(axis=1)
    atr = tr.rolling(14, min_periods=14).mean()
    # Completed H4 data; each source H4 group must have all four H1 candles.
    h4 = (df.set_index("open_time_utc")
          .resample("4h", label="left", closed="left")
          .agg(close=("close","last"), n=("close","count")))
    h4["sma20"] = h4["close"].where(h4["n"]==4).rolling(
        20, min_periods=20).mean()
    h4["bias"] = np.where(
        h4["n"].eq(4) & h4["sma20"].notna(),
        np.where(h4["close"]>h4["sma20"], 1,-1), 0)
    historical_h4 = pd.DataFrame({
        "complete_utc": h4.index + pd.Timedelta(hours=4),
        "bias": h4["bias"].to_numpy(dtype=int)
    }).sort_values("complete_utc")
    usable = pd.merge_asof(
        pd.DataFrame({"complete_utc": closes}).sort_values("complete_utc"),
        historical_h4, on="complete_utc", direction="backward",
    ).sort_index()
    # No accidental matching of same time H4 partial; missing bias zero.
    bias = usable["bias"].fillna(0).to_numpy(dtype=int)
    dates = df["open_time_utc"].dt.strftime("%Y-%m-%d")
    d = df.groupby(dates, sort=True).agg(
        high=("high","max"), low=("low","min"),
        full=("high","count"))
    prior = d[["high","low"]].shift(1).rename(
        columns={"high":"previous_day_hi","low":"previous_day_lo"})
    daily = df.join(prior, on=dates)
    pdh = daily["previous_day_hi"]
    pdl = daily["previous_day_lo"]
    # Original source score weights = 4+4+4, but upstream direction of
    # sweep is counterintuitive. Preserve named bull/bear mapping and disclose.
    bull_sweep = (h > pdh + .25*atr) & (c < pdh)
    bear_sweep = (l < pdl - .25*atr) & (c > pdl)
    bull_fvg = l > h.shift(2)  # true completed three-candle imbalance
    bear_fvg = h < l.shift(2)
    events = {name: [] for name in GROUPS}
    coverage = {"closed_h4_nonzero": int((bias!=0).sum()),
                "sweep_bull": int(bull_sweep.sum()),
                "sweep_bear": int(bear_sweep.sum()),
                "fvg_bull": int(bull_fvg.sum()),
                "fvg_bear": int(bear_fvg.sum())}
    for i in range(len(df)):
        one = []
        close = float(c.iloc[i])
        if i >= 240 and np.isfinite(atr.iloc[i]) and atr.iloc[i] > 0:
            for side, sweep, fvg in [
                (1, bool(bull_sweep.iloc[i]),bool(bull_fvg.iloc[i])),
                (-1,bool(bear_sweep.iloc[i]),bool(bear_fvg.iloc[i])),
            ]:
                if bias[i] != side:
                    continue
                for name, take in (
                    (SCORE8,sweep or fvg), (STRICT12,sweep and fvg),
                ):
                    if not take:
                        continue
                    # Same 2R ATR stop/target as shared AIDY conservative model.
                    stop = close - side * 2 * float(atr.iloc[i])
                    target = close + side * 4 * float(atr.iloc[i])
                    events[name].append((i, {
                        "system":name,"side":side,
                        "signal_utc":closes.iloc[i].isoformat(),
                        "signal_bar_index":i,
                        "stop":round(stop,6),"target":round(target,6),
                        "source":SOURCE,
                    }))
    tapes={}
    for name, entries in events.items():
        rows=[tuple() for _ in range(len(df))]
        for i,item in entries:
            rows[i]=(item,)
        tapes[name]=tuple(rows)
    coverage["signals_by_family"]={
        n:len(x) for n,x in events.items()}
    return df, tapes, coverage


def research(quotes:Path,out:Path):
    report={"schema":"aidy.independent_external_smc_corrected_v1",
            "external_source":SOURCE,"source_blob_sha":BLOB,
            "upstream_license":"MIT",
            "original_source_h4_lookahead":True,
            "original_source_backward_fill_lookahead":True,
            "original_source_fvg_definition_nonstandard":True,
            "source_native_strategy_reproduction":False,
            "original_source_claims_not_reproduced":True,
            "sealed_oos":False,"historical_research_only":True,
            "broker_orders":0,"years":{}}
    for year in YEARS:
        raw,trace=source_year(quotes,year)
        df,tapes,signals=make_tape(raw)
        yearly={}
        for cost_name,settings in {
            "base":Settings(observed_quote_mode=True),
            "stress":replace(Settings(observed_quote_mode=True),
                             spread_floor=.80,slippage_per_side=.25,
                             roundtrip_commission_per_oz=.14),
        }.items():
            yearly[cost_name]={}
            for name,arms in GROUPS.items():
                r=replay_causal_v2(df,tapes[name],arms,settings)
                if (r["closed_trades"] != len(r["trades"]) or
                    abs(sum(t["pnl_usd"] for t in r["trades"])
                        -r["realized_net_usd"])>.05):
                    raise ValueError("Original trade ledger mismatch")
                target=out/str(year)/cost_name
                target.mkdir(parents=True,exist_ok=True)
                (target/f"{name}.json").write_text(
                    json.dumps(r,sort_keys=True,indent=2,allow_nan=False)+"\n")
                yearly[cost_name][name]={
                    k:r[k] for k in ("closed_trades","realized_net_usd",
                                     "net_marked_usd","max_marked_drawdown_pct",
                                     "profit_factor","sha256")}
        report["years"][str(year)]={"source":trace,
                                     "source_signals":signals,
                                     "results":yearly}
    report["sha256"]=digest(report)
    out.mkdir(parents=True,exist_ok=True)
    (out/"report.json").write_text(
        json.dumps(report,sort_keys=True,indent=2,allow_nan=False)+"\n")
    print("AIDY_CAUSAL_SMC_WEB_RESEARCH",json.dumps({
        year:{"candidate_signals":v["source_signals"]["signals_by_family"],
              "stress":{name:{"net":case["net_marked_usd"],
                              "trades":case["closed_trades"],
                              "drawdown":case["max_marked_drawdown_pct"]}
                  for name,case in v["results"]["stress"].items()}}
        for year,v in report["years"].items()},sort_keys=True),flush=True)
    return report


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--quotes",type=Path,required=True)
    parser.add_argument("--out",type=Path,required=True)
    args=parser.parse_args()
    try:
        research(args.quotes,args.out)
    except Exception as exc:
        args.out.mkdir(parents=True,exist_ok=True)
        (args.out/"BLOCKED.json").write_text(json.dumps({
            "status":"NOT_TESTED","error_type":type(exc).__name__,
            "did_not_substitute_market_data":True,
            "broker_orders":0},indent=2)+"\n")
        raise
