"""G-005 exact ORIGINAL author 001B zone-rejection signal/engine source research.

SOURCE (UNLICENSED FOR COMMERCIAL REDISTRIBUTION):
  https://github.com/anirudhatalmale6-alt/xauusd-strategy-backtest
  src/strategy.py blob 30f07bb307fa44a428903bc21b0d51dc441d62d5
  src/dataset.py  blob ae303bc82a36c1d5b644f436fb55f0ce03970b54
  src/engine.py   blob 7aed5ffd3fcfbd8642d5299bf342335068cf3ba6
  out/preregistered.json blob 9d4d379c3e05ee3deb49f0d0255f62e361588c67

Execute original files unmodified in isolated CI, fetched and SHA-pinned before
this script runs. This wrapper adapts the INPUT data ONLY: original independently
authenticated AIDY spot BID+ASK M1 from PR374 artifact; author's native
dataset.resample and strategy.generate_signals("B"), engine.simulate.
No made-up quotes. No portfolio edits, no broker orders, no new OOS claims.
The original 001B fixed picked-on-IS setting was 2.0R, 0.25% risk, London/
New York session gate and daily EMA50 confirmed-structure mode.

Secondary independently specified standard-lot conversion and carry overlay
is NOT source-native engine parity. Stress assumptions are *NOT* actual PU Prime
swap, margin or execution receipts. Exit mark-to-market DD not proven: author
metrics use CLOSED-trade DD.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.gold_hunter_2023_2024_causal_research import read_month

SOURCE="https://github.com/anirudhatalmale6-alt/xauusd-strategy-backtest"
BLOBS={
    "src/strategy.py":"30f07bb307fa44a428903bc21b0d51dc441d62d5",
    "src/dataset.py":"ae303bc82a36c1d5b644f436fb55f0ce03970b54",
    "src/engine.py":"7aed5ffd3fcfbd8642d5299bf342335068cf3ba6",
    "out/preregistered.json":"9d4d379c3e05ee3deb49f0d0255f62e361588c67"
}
YEARS=(2023,2024,2025)
START=10_000.0
AUTHOR_R=2.0
AUTHOR_RISK_PCT=.25
ONE_STANDARD_LOT_OZ=100.
MIN_LOT=.01
LOT_STEP=.01
LEVERAGE_ASSUMED=20.

def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),
                         allow_nan=False,default=str).encode()).hexdigest()

def original_modules(root:Path):
    if not all((root/"src"/name).is_file() for name in ("dataset.py","strategy.py","engine.py")):
        raise ValueError("Pinned ORIGINAL author executable modules absent")
    sys.path.insert(0,str(root/"src"))
    import dataset
    import strategy
    import engine
    return dataset,strategy,engine

def original_quotes(root:Path):
    chunks=[];receipts=[]
    # Original authenticated monthly 2023-25 AIDY M1 BID+ASK data.
    # The pre-2023 late-December weekend start is an explicit warm-up gap.
    for year in YEARS:
        for month in range(1,13):
            raw,receipt=read_month(root,f"{year}{month:02d}")
            chunks.append(raw)
            receipts.append(receipt)
    df=pd.concat(chunks,ignore_index=True)
    df=df.loc[(df["open_time_utc"]>=pd.Timestamp("2023-01-01",tz="UTC"))&
              (df["open_time_utc"]<pd.Timestamp("2026-01-01",tz="UTC"))].copy()
    df=df.sort_values("open_time_utc")
    if (len(df)<800_000 or df["open_time_utc"].duplicated().any()
            or not df["open_time_utc"].is_monotonic_increasing
            or set(df["open_time_utc"].dt.year)!=set(YEARS)):
        raise ValueError("Missing original chronological spot M1 quote years")
    cols=["bid_o","bid_h","bid_l","bid_c","ask_o","ask_h",
          "ask_l","ask_c","ticks","spread_mean"]
    df=df.set_index("open_time_utc")[cols]
    df.index.name="ts"
    df["o"]=(df["bid_o"]+df["ask_o"])/2
    df["h"]=(df["bid_h"]+df["ask_h"])/2
    df["l"]=(df["bid_l"]+df["ask_l"])/2
    df["c"]=(df["bid_c"]+df["ask_c"])/2
    return df,{
        "m1_rows":len(df),
        "months":len(receipts),
        "month_receipts":receipts,
        "source_m1_index_sha256":hashlib.sha256(
            df.index.astype("int64").to_numpy().tobytes()).hexdigest(),
        "no_2022_full_year_warmup":True,
        "raw_quotes_unchanged":True,
    }

def source_bars(dataset,m1):
    result={}
    for key,rule in (("m15","15min"),("h4","4h"),("d1","1D")):
        bars=dataset.resample(m1,rule)
        # Audit coverage; source-native resample ALLOWS incomplete bars
        # when original market is closed/partial. Never claim complete.
        raw_counts=m1["bid_o"].resample(rule,label="left",closed="left").count()
        needed={"m15":15,"h4":240,"d1":1440}[key]
        actual=raw_counts.reindex(bars.index).fillna(0).astype(int)
        result[key]=(bars,{"source_bars":len(bars),
                            "full_m1_coverage":int((actual==needed).sum()),
                            "partial_m1_coverage":int((actual<needed).sum()),
                            "coverage_needed":needed})
    m15=result["m15"][0].join(dataset.tag_sessions(result["m15"][0].index))
    m15.index.name="ts"
    h4=result["h4"][0]; h4.index.name="ts"
    d1=result["d1"][0]; d1.index.name="ts"
    return m15,h4,d1,{k:v[1] for k,v in result.items()}

def source_author_simulate(engine,sig,m15,m1):
    cfg=engine.Config(r_multiple=AUTHOR_R,risk_pct=AUTHOR_RISK_PCT)
    trades=engine.simulate(sig,m15,m1,cfg)
    if trades.empty:
        return {"closed_trades":0,"net_usd":0.,"win_rate_pct":None,
                "pf":None,"closed_trade_dd_pct":None,
                "no_source_orders":True},trades
    earned=float(trades["pnl"].sum())
    if abs(float(trades.iloc[-1]["equity"])-(START+earned))>.1:
        raise ValueError("Original publisher equity ledger does not reconcile")
    gain=float(trades.loc[trades.pnl>0,"pnl"].sum())
    loss=-float(trades.loc[trades.pnl<=0,"pnl"].sum())
    eq=np.r_[START,trades.equity.to_numpy()]
    dd=(eq/np.maximum.accumulate(eq)-1)*100
    return {"closed_trades":len(trades),
            "net_usd":round(earned,2),
            "win_rate_pct":round(100*(trades.pnl>0).mean(),2),
            "pf":round(gain/loss,3) if loss else None,
            "closed_trade_dd_pct":round(float(dd.min()),3),
            "longs":int((trades.direction=="BUY").sum()),
            "shorts":int((trades.direction=="SELL").sum()),
            "no_source_orders":True},trades

def broker_lot_overlay(engine,signals,m15,m1,*,slippage,roundtrip_fee_per_oz,financing_annual):
    """Same author signals, stops, targets and stop-first M1 walking.
    The author's continuous ounce size and P&L are NEVER silently changed.
    This overlay separately quantizes 0.01 standard-lot steps (100oz per lot),
    approximate 20:1 margin and financing. Not broker proof.
    """
    initial=START
    cash=initial
    rows=[]
    rejected={"no_next_open":0,"overlap":0,"stop_inversion":0,
              "min_0_01_standard_lot":0,"margin":0}
    until=None
    idx=m15.index
    for s in signals.itertuples(index=False):
        at=s.entry_ts
        if at not in idx:
            rejected["no_next_open"]+=1
            continue
        if until is not None and at<=until:
            rejected["overlap"]+=1
            continue
        bar=m15.loc[at]
        side=int(s.direction)
        entry=(float(bar.ask_o) if side==1 else float(bar.bid_o))+side*slippage
        stop=float(s.stop)
        risk=side*(entry-stop)
        if risk<=0 or not math.isfinite(risk):
            rejected["stop_inversion"]+=1
            continue
        target=entry+side*AUTHOR_R*risk
        raw_oz=cash*(AUTHOR_RISK_PCT/100)/risk
        lot_units=math.floor(raw_oz/ONE_STANDARD_LOT_OZ/LOT_STEP+1e-9)
        if lot_units<1:
            rejected["min_0_01_standard_lot"]+=1
            continue
        lots=round(lot_units*LOT_STEP,2)
        oz=lots*ONE_STANDARD_LOT_OZ
        if entry*oz/LEVERAGE_ASSUMED>cash:
            rejected["margin"]+=1
            continue
        pos=idx.get_loc(at)
        t_limit=idx[min(pos+engine.MAX_HOLD_BARS,len(idx)-1)]
        walked=engine._walk(m1,side,entry,stop,target,at,t_limit,slippage)
        if walked is None:
            exit_ts=t_limit
            exit_px=float(m15.loc[t_limit].bid_c if side==1 else m15.loc[t_limit].ask_c)
            reason="timeout"
        else:
            exit_ts,exit_px,reason=walked
        hours=max(0,(exit_ts-at).total_seconds()/3600)
        fee=roundtrip_fee_per_oz*oz
        carry=entry*oz*financing_annual*hours/(24*365)
        gross=(exit_px-entry)*side*oz
        net=gross-fee-carry
        cash+=net
        until=exit_ts
        rows.append({
            "signal_utc":s.signal_ts.isoformat(),
            "entry_utc":at.isoformat(),"exit_utc":exit_ts.isoformat(),
            "side":side,"entry_ask_or_bid":round(entry,6),
            "exit_px":round(exit_px,6),"exit_reason":reason,
            "stop":stop,"target":round(target,6),
            "lots":lots,"oz":oz,"entry_margin_20x":round(entry*oz/LEVERAGE_ASSUMED,4),
            "gross_usd":round(gross,6),"commission_usd":round(fee,6),
            "hypothetical_carry_usd":round(carry,6),"net_usd":round(net,6),
            "cash_equity_after_close":round(cash,6)})
    if abs(START+sum(r["net_usd"] for r in rows)-cash)>.02:
        raise ValueError("Broker overlay net trade ledger mismatch")
    profit=sum(max(r["net_usd"],0) for r in rows)
    loss=-sum(min(r["net_usd"],0) for r in rows)
    points=[START]+[x["cash_equity_after_close"] for x in rows]
    peaks=np.maximum.accumulate(points)
    mdd=float(np.min((np.array(points)/peaks-1)*100))
    return {"closed_trades":len(rows),"net_usd":round(cash-START,2),
            "pf":round(profit/loss,3) if loss else None,
            "closed_trade_dd_pct":round(mdd,3),
            "exclusions":rejected,
            "source_r_multiple":AUTHOR_R,"source_risk_pct":AUTHOR_RISK_PCT,
            "min_lot_standard":MIN_LOT,"lot_ounces":ONE_STANDARD_LOT_OZ,
            "actual_puprime_symbol_parity":False,"broker_order_count":0,
            "assumed_slippage_per_side":slippage,
            "assumed_roundtrip_fee_per_oz":roundtrip_fee_per_oz,
            "assumed_annual_financing_not_real_swap":financing_annual,
            "limitations":[
                "Author source intraminute stop precedes take profit if both hit",
                "Source engine does not model worse-than-stop market gaps",
                "Source author indexes incomplete H4 and D1 bars without source completeness rejection",
                "Account equity DD on closed trades only; no pathwise intratrade drawdown",
                "Financing/margin/lot levels are hypothetical, not verified PU Prime account"
            ],"trades":rows}

def research(quotes:Path,author:Path,out:Path):
    dataset,strategy,engine=original_modules(author)
    m1,proof=original_quotes(quotes)
    m15,h4,d1,coverage=source_bars(dataset,m1)
    print("G005_ORIGINAL_SOURCE_COVERAGE",json.dumps(coverage,sort_keys=True),flush=True)
    print("G005_GENERATING_ORIGINAL_AUTHOR_001B",flush=True)
    signals,rejected=strategy.generate_signals(
        m15,h4,d1,mode="B",trend_mode="ema50",session_filter=True)
    if signals.empty:
        raise ValueError("SOURCE 001B produced zero setups; requires root-cause coverage audit")
    signals=signals.sort_values("signal_ts")
    out.mkdir(parents=True,exist_ok=True)
    report={"schema":"aidy.g005.original_001B_spot_2023_2025.v1",
      "original_repo":SOURCE,"original_source_blobs":BLOBS,
      "source_license_found":False,"source_original_python_unmodified":True,
      "source_preregistered":{"mode":"B","trend_mode":"ema50","session_filter":True,
                              "r_target":AUTHOR_R,"risk_pct":AUTHOR_RISK_PCT},
      "not_original_broker_spot_or_replicated_oos":True,
      "author_in_sample_oos_claim_is_not_our_result":True,
      "data_aidy_original_M1_bidask":proof,"coverage":coverage,
      "source_raw_signals":len(signals),"source_rejections":len(rejected),
      "years":{},"no_orders":True}
    for year in YEARS:
        begin=pd.Timestamp(f"{year}-01-01",tz="UTC")
        end=pd.Timestamp(f"{year+1}-01-01",tz="UTC")
        sig=signals.loc[(signals["signal_ts"]>=begin)&(signals["entry_ts"]<end)].copy()
        y_m1=m1.loc[(m1.index>=begin)&(m1.index<end)]
        y_m15=m15.loc[(m15.index>=begin)&(m15.index<end)]
        source_summary,source_trades=source_author_simulate(engine,sig,y_m15,y_m1)
        scenarios={}
        for label,slip,fee,fin in (("base",.05,.07,.06),("stress",.25,.14,.09)):
            result=broker_lot_overlay(engine,sig,y_m15,y_m1,slippage=slip,
                roundtrip_fee_per_oz=fee,financing_annual=fin)
            folder=out/str(year)/label
            folder.mkdir(parents=True,exist_ok=True)
            (folder/"broker_overlay_full_ledger.json").write_text(
                json.dumps(result,indent=2,sort_keys=True,allow_nan=False)+"\n")
            scenarios[label]={k:v for k,v in result.items() if k!="trades"}
        folder=out/str(year)
        folder.mkdir(parents=True,exist_ok=True)
        source_trades.to_csv(folder/"original_author_trades.csv",index=False)
        sig.to_csv(folder/"original_author_signals.csv",index=False)
        report["years"][str(year)]={
            "original_source_python_engine":source_summary,
            "original_signals":len(sig),"source_signals_long":
              int((sig.direction==1).sum()),
            "source_signals_short":int((sig.direction==-1).sum()),
            "source_author_unfilled_end_year_signals":int(
                ((signals["signal_ts"]>=begin)&(signals["signal_ts"]<end)&
                 (signals["entry_ts"]>=end)).sum()),
            "independent_broker_feasibility_models":scenarios}
        print("G005_SOURCE_ONE_YEAR",json.dumps({"year":year,
            "signals":len(sig),"author":source_summary,
            "stress":scenarios["stress"]},sort_keys=True),flush=True)
    report["sha256"]=digest(report)
    (out/"report.json").write_text(json.dumps(report,indent=2,sort_keys=True,default=str,allow_nan=False)+"\n")
    return report

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--quotes",required=True,type=Path)
    p.add_argument("--author",required=True,type=Path)
    p.add_argument("--out",required=True,type=Path)
    a=p.parse_args()
    try:
        research(a.quotes,a.author,a.out)
    except Exception as ex:
        a.out.mkdir(parents=True,exist_ok=True)
        (a.out/"BLOCKED.json").write_text(json.dumps({
            "performance_not_verified":True,"exception":type(ex).__name__,
            "no_synthetic_prices_substituted":True},indent=2)+"\n")
        raise
