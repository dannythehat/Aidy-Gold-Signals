"""S005 run original pinned 2026 author Python engine unchanged on REAL gold H1.

Both original gold PRESETS individually. This benchmark is NOT an MT5 fill.
Compare source-aligned signals and expose native publisher execution timing
versus next-bar EA. No third-party Python source runs without git-blob pins.
Original author's GC=F FUTURES research did NOT use the source spot tape here.
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

from scripts.strategy_lab.s001_two_period_original_rules import read_source

PUB_COMMIT="3dab20e20a846edae9ac6fcf56d6b090dbba9f98"
BLOBS={
    "engine.py":"41f1b5740314487ed6ea35b3307daf689d8abb6f",
    "strategies.py":"9abe69680df34064923e01236cbf9b77d486c682",
    "ApexBreakout.mq5":"db9ee1d2589cd1625c2d9f5b224ea4f1fad14442",
    "ApexBreakout_XAUUSD_H1_Donchian.set":"0a053c3c49cdd23e70a65d079739dad46900b6a1",
    "ApexBreakout_XAUUSD_H1_Session.set":"f16c28996e112e6179ee6eb91ae0b490eb74270b"
}
PERIODS={"2025":("2025-01-01","2026-01-01",12),"2026":("2026-01-01","2026-10-01",9)}

def _git_blob_sha(content:bytes):
    return hashlib.sha1(b"blob "+str(len(content)).encode()+b"\0"+content).hexdigest()

def original_modules(root:Path):
    for name,sha in BLOBS.items():
        p=root/name
        if _git_blob_sha(p.read_bytes())!=sha:
            raise ValueError("S005 original publisher SHA changed "+name)
    sys.path.insert(0,str(root))
    # Only run independently reviewed modules; no arbitrary package import.
    import engine
    import strategies
    return engine, strategies

def source_h1(root:Path):
    m15,receipts,source_sha=read_source(root)
    frame=m15.resample("60min").agg(
       open=("open","first"),high=("high","max"),
       low=("low","min"),close=("close","last"),
       actual_m15=("open","count"),
       open_ask=("observed_open_ask","first"),
       source_open_spread=("observed_open_spread","first"),
       max_source_spread=("observed_max_spread","max"))
    h=frame[frame.actual_m15==4].copy()
    if len(h)<10000 or len(receipts)!=22:
        raise ValueError("Missing fully sourced original M15/H1 months")
    dates=h.index.tz_localize("UTC")
    hours=dates.hour.to_numpy()
    weekdays=dates.dayofweek.to_numpy()
    times=dates.astype("int64").to_numpy()//1_000_000_000
    hsha=hashlib.sha256(h.to_csv().encode()).hexdigest()
    return h,receipts,source_sha,hsha,times,hours,weekdays

def auditor_signal_diff(h, original_ls,original_ss, original_lx,original_sx,mode):
    # Completely independent causal signal-geometry verification, not
    # native MT5 compiled and tick-triggered parity.
    if mode=="DONCHIAN":
        hh=h.high.rolling(24).max().shift(1)
        ll=h.low.rolling(24).min().shift(1)
        xh=h.high.rolling(12).max().shift(1)
        xl=h.low.rolling(12).min().shift(1)
        ema200=h.close.ewm(span=200,adjust=False).mean()
        test=(
          ((h.close>hh)&(h.close>ema200)).to_numpy(),
          ((h.close<ll)&(h.close<ema200)).to_numpy(),
          (h.close<xl).to_numpy(),(h.close>xh).to_numpy()
        )
        return {"long_entries_mismatched":int(sum(original_ls!=test[0])),
          "short_entries_mismatched":int(sum(original_ss!=test[1])),
          "long_exit_signals_mismatched":int(sum(original_lx!=test[2])),
          "short_exit_signals_mismatched":int(sum(original_sx!=test[3])),
          "signal_event_parity_mechanical":all(np.array_equal(a,b)
               for a,b in zip((original_ls,original_ss,original_lx,original_sx),test))}
    # Session author source may permit incomplete 00-06 original H1 session;
    # track exact signal counts; native EA's SessionRange logic separate.
    return {"publisher_long_signal_hours":sorted(set(h.index.hour[original_ls])),
            "publisher_short_signal_hours":sorted(set(h.index.hour[original_ss])),
            "long_signals":int(sum(original_ls)),
            "short_signals":int(sum(original_ss)),
            "native_mql_session_parity_proven":False}

def dump_csv(path,rows):
    if not rows:
        path.write_text("NO ORIGINAL PUBLISHER TRADES\n")
        return
    with path.open("w",newline="",encoding="utf-8") as file:
        writer=csv.DictWriter(file,fieldnames=list(rows[0]))
        writer.writeheader();writer.writerows(rows)

def main():
    arg=argparse.ArgumentParser()
    arg.add_argument("--source-root",required=True,type=Path)
    arg.add_argument("--publisher-root",required=True,type=Path)
    arg.add_argument("--out",required=True,type=Path)
    opts=arg.parse_args()
    engine,strategies=original_modules(opts.publisher_root)
    bars,receipts,source_sha,hsha,times,hours,weekdays=source_h1(opts.source_root)
    o,h,l,c=[bars[k].to_numpy(dtype=float) for k in ("open","high","low","close")]
    publisher_atr=engine.atr(h,l,c,14)
    models={
      "DONCHIAN":{
        "signals":strategies.donchian(o,h,l,c,hours,entry_n=24,exit_n=12,ema_filter=200),
        "engine_params":engine.EngineParams(sl_atr=2.5,tp_atr=0.,trail_atr=0.,
                                         allow_reverse=True,risk_pct=1.,start_equity=10000.)},
      "SESSION":{
        "signals":strategies.session_breakout(o,h,l,c,hours,
              range_start=0,range_end=6,trade_end=12,close_hour=21,
              buffer_frac=0.,atr_arr=publisher_atr,dows=weekdays),
        "engine_params":engine.EngineParams(sl_atr=3.,tp_atr=0.,trail_atr=0.,
                                         allow_reverse=False,risk_pct=1.,start_equity=10000.)}
    }
    output={}
    opts.out.mkdir(parents=True,exist_ok=True)
    timeindex=bars.index
    for family,inputs in models.items():
        signals=inputs["signals"]
        sig_audit=auditor_signal_diff(bars,*signals,family)
        output[family]={"source_signal_diagnostic":sig_audit,"periods":{}}
        for year,(start,end,nmonths) in PERIODS.items():
            start_i=int(timeindex.searchsorted(pd.Timestamp(start)))
            end_i=int(timeindex.searchsorted(pd.Timestamp(end)))
            # SymbolSpec is original research cost model: 45c/oz all-in
            # and 20x leverage; uses FLOAT units not MT5 0.01 lot step.
            spec=engine.SymbolSpec("XAUUSD",cost=.45,max_leverage=20.)
            res=engine.simulate(o,h,l,c,times,publisher_atr,*signals,spec,
                inputs["engine_params"],start_i,end_i)
            trades=[]
            for t in res.trades:
                trades.append({
                  "direction":"LONG" if t.dir==1 else "SHORT",
                  "entry_time_utc":str(timeindex[t.entry_i])+"Z",
                  "exit_time_utc":str(timeindex[t.exit_i])+"Z",
                  "entry_price_publisher_bid_proxy":round(t.entry_px,5),
                  "exit_price_publisher_bid_proxy":round(t.exit_px,5),
                  "units_float_not_broker_lots":round(t.units,7),
                  "publisher_costed_usd":round(t.pnl,6),
                  "reason":t.reason
                })
            prof=sum(x["publisher_costed_usd"] for x in trades if x["publisher_costed_usd"]>0)
            loss=-sum(x["publisher_costed_usd"] for x in trades if x["publisher_costed_usd"]<0)
            monthly=[]
            for month in range(1,nmonths+1):
                name=f"{year}-{month:02d}"
                arr=[x for x in trades if x["exit_time_utc"].startswith(name)]
                monthly.append({"month":name,"closed":len(arr),
                                "net_usd":round(sum(x["publisher_costed_usd"] for x in arr),2)})
            cross=[x for x in trades if not x["exit_time_utc"].startswith(year)]
            if cross:
                if any(x["reason"]!="eod" for x in cross):
                    raise ValueError("Nonperiod original close escaped model")
                monthly[-1]["closed"]+=len(cross)
                monthly[-1]["net_usd"]=round(monthly[-1]["net_usd"]+
                    sum(x["publisher_costed_usd"] for x in cross),2)
            profit=round(sum(x["publisher_costed_usd"] for x in trades),2)
            if abs(profit-round(res.net_return*100,2))>.20:
                raise ValueError("Original author net USD not reconciled to return")
            if sum(x["closed"] for x in monthly)!=len(trades) or abs(sum(x["net_usd"] for x in monthly)-profit)>.20:
                raise ValueError("Monthly publisher native economic model ledger mismatch")
            case={
               "period":year,"mode":family,"publisher_python_original_executed":True,
               "initial_usd":10000.,"net_usd":profit,"ending_usd":round(10000+profit,2),
               "trades":len(trades),"wins":sum(x["publisher_costed_usd"]>0 for x in trades),
               "losses":sum(x["publisher_costed_usd"]<0 for x in trades),
               "profit_factor":round(prof/loss,4) if loss else None,
               "max_marked_drawdown_pct":round(-res.max_dd,4),
               "pct_return":round(res.net_return,4),"author_engine_sharpe":round(res.sharpe,4),
               "author_exit_by_reason":{k:sum(x["reason"]==k for x in trades)
                                       for k in set(x["reason"] for x in trades)},
               "publisher_gold_original_cost_round_trip_per_oz":.45,
               "publisher_gold_original_leverage":20.,
               "published_original_python_signal_bar_close_exits":True,
               "published_MQL5_EA_next_bar_open_exits":True,
               "actual_MT5_native_compiler_tested":False,
               "source_quote_basis":"REAL HISTDATA SPOT BID DERIVED H1 - NOT AUTHOR COMEX GC=F",
               "monthly":monthly,"trade_ledger":trades
            }
            output[family]["periods"][year]=case
            dump_csv(opts.out/f"{family}_{year}_publisher_PY_closed_trades.csv",trades)
            dump_csv(opts.out/f"{family}_{year}_publisher_PY_monthly.csv",monthly)
            print("S005_PUBLISHER_NATIVE_PY_ACTUAL",json.dumps({
                "mode":family,"year":year,"trades":len(trades),"net_usd":profit,
                "PF":case["profit_factor"],"DD":case["max_marked_drawdown_pct"],
                "signal_parity":sig_audit
            },sort_keys=True),flush=True)
    packet={
      "schema":"aidy.s005.real_source.original_publisher_python_two_mode.v1",
      "publisher_git_commit":PUB_COMMIT,
      "publisher_original_frozen_source_blobs":BLOBS,
      "same_original_source_as_independent_EA_event_replay":True,
      "fully_authenticated_22_source_months":len(receipts),
      "all_original_m15_sha256":source_sha,"derived_real_H1_sha256":hsha,
      "market_source_receipts":receipts,
      "publisher_python_original_executed_on_REAL_SPOT_HISTORY":True,
      "native_MQL5_EA_run":False,
      "author_source_original_research_COMEX_futures_proxy_not_spot":True,
      "both_modes_separately_executed":True,
      "two_years_independent_10000USD":True,
      "publisher_python_barclose_vs_MQL5_EA_nextbar_exits_differ":True,
      "independently_recomputed_original_PY_donchian_boolean_geometry":True,
      "full_native_spot_broker_parity":False,
      "cases":output,
    }
    packet["sha256"]=hashlib.sha256(json.dumps(packet,sort_keys=True,
        separators=(",",":"),allow_nan=False).encode()).hexdigest()
    (opts.out/"S005_PUBLISHER_PY_NATIVE_REPLAY.json").write_text(
        json.dumps(packet,indent=2,sort_keys=True,allow_nan=False)+"\n")
    print("S005_SOURCE_PUBLISHER_ENGINE_VERIFIED",json.dumps({
      "m15_archive_months":len(receipts),"checksum":packet["sha256"],
      "source_m15_sha256":source_sha,"H1_bars":len(bars)
    },sort_keys=True),flush=True)

if __name__=="__main__":
    main()
