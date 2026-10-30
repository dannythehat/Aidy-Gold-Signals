"""Independent G-001 spot XAUUSD daily volatility-regime test (research only).

Primary frozen Pine source: erhungn/volatility-regime-momentum,
strategy/pine_script_strategy.pine, Git blob
f6989fb66257bd04b4915a261f89da4a3dcacd22.
Original uses Yahoo GC=F futures and daily-close stop with strategy.close;
no LICENSE file found. NOT author Pine parity / future OOS / PU Prime fills.
Two experiments: close-confirmed Pine-like stop vs hypothetical intraday
resting stop; both use original AIDY 2023-25 BID/ASK M1 and no invented bars.
2023 lacks prior 200-day warmup: only valid later 2023 signals permitted.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
import numpy as np
import pandas as pd
from scripts.gold_hunter_2023_2024_causal_research import read_month

SOURCE="https://github.com/erhungn/volatility-regime-momentum"
PIN="f6989fb66257bd04b4915a261f89da4a3dcacd22"
YEARS=(2023,2024,2025)
METHODS=("PINE_CLOSE_NEXT_OPEN","PROTECTIVE_INTRADAY_STOP")

def digest(x):
    return hashlib.sha256(json.dumps(x,sort_keys=True,allow_nan=False,separators=(",",":")).encode()).hexdigest()

def source_daily(root:Path):
    months,receipts=[],[]
    for year in YEARS:
        for month in range(1,13):
            frame,receipt=read_month(root,f"{year}{month:02d}")
            months.append(frame)
            receipts.append(receipt)
    m=pd.concat(months,ignore_index=True).sort_values("open_time_utc")
    if m["open_time_utc"].duplicated().any():
        raise ValueError("Original market tape duplicate")
    m["day"]=m["open_time_utc"].dt.normalize()
    d=m.groupby("day",sort=True).agg(
        first_utc=("open_time_utc","first"),
        bid_o=("bid_o","first"),ask_o=("ask_o","first"),
        high=("bid_h","max"),low=("bid_l","min"),
        close=("bid_c","last"),m1_count=("bid_o","size"))
    # Only original observed weekdays with >=900 source M1 observations.
    d=d.loc[(d.index.weekday<5)&(d["m1_count"]>=900)].copy()
    if len(d)<450 or set(YEARS)-set(d.index.year):
        raise ValueError("Insufficient true daily source coverage")
    prior=d["close"].shift()
    true_range=pd.concat([d["high"]-d["low"],(d["high"]-prior).abs(),
                          (d["low"]-prior).abs()],axis=1).max(axis=1).to_numpy()
    # Equivalent Wilder smoothing seed for full 14-period ATR.
    atr=np.full(len(d),np.nan)
    atr[13]=np.mean(true_range[:14])
    for i in range(14,len(d)):
        atr[i]=(13*atr[i-1]+true_range[i])/14
    d["atr14"]=atr
    d["sma200"]=d["close"].rolling(200,min_periods=200).mean()
    d["momentum"]=(d["close"]-d["close"].shift(20))/d["atr14"]
    d["setup"]=(d["momentum"]>.5)&(d["close"]>d["sma200"])&(
        d["atr14"]>d["atr14"].shift(5)*.95)
    d["risk_tier"]=np.where(d["momentum"]>=1.8,.02,
                    np.where(d["momentum"]>=1.2,.015,.01))
    return d,{"source_m1":len(m),"valid_days":len(d),
        "2023_200day_warmup_valid":int(d.loc[d.index.year==2023,"sma200"].notna().sum()),
        "monthly_source_receipts":receipts,
        "d1_sha256":hashlib.sha256(d[["bid_o","ask_o","high","low","close","m1_count"]].to_csv().encode()).hexdigest()}

def run_year(d:pd.DataFrame,year:int,mode:str,slip:float,fee:float,financing:float):
    if year not in YEARS or mode not in METHODS: raise ValueError("Unknown scenario")
    q=d.loc[d.index.year==year]
    cash=10000.
    peak=cash
    dd=0.
    active=None
    pending=False
    previous_at=None
    trades=[]
    equity=[]
    exclusions={"lot_min":0,"margin":0,"atr":0}
    entries=0
    def exit_trade(at,bid,reason):
        nonlocal cash,active
        if active is None: raise ValueError("No open trade")
        px=bid-slip
        gross=(px-active["entry"])*active["oz"]
        net=gross-fee*active["oz"]-active["funding"]
        cash+=net
        trades.append({"signal":active["signal"],
                       "entry_utc":active["at"].isoformat(),"exit_utc":at.isoformat(),
                       "reason":reason,"lots":active["lots"],"oz":active["oz"],
                       "entry_px":round(active["entry"],5),"exit_px":round(px,5),
                       "gross_usd":round(gross,6),
                       "commission_usd":round(fee*active["oz"],6),
                       "funding_usd":round(active["funding"],6),
                       "net_usd":round(net,6)})
        active=None
    for i in range(len(q)):
        day=q.index[i];row=q.iloc[i]
        at=pd.Timestamp(row["first_utc"])
        bid=float(row["bid_o"]);ask=float(row["ask_o"])
        if not 0<bid<=ask:raise ValueError("Invalid observed BID/ASK")
        if active is not None:
            n_days=(at-previous_at).total_seconds()/86400
            if n_days<0:raise ValueError("Future date moved backward")
            active["funding"]+=active["entry"]*active["oz"]*financing*n_days/365
        closed_from_prior=pending
        if pending:
            exit_trade(at,bid,"PINE_CLOSE_NEXT_OPEN")
        pending=False
        if i>0 and active is None and not closed_from_prior:
            prev=q.iloc[i-1]
            if bool(prev["setup"]):
                atr=float(prev["atr14"])
                if not math.isfinite(atr) or atr<=0:exclusions["atr"]+=1
                else:
                    lots=round(cash*float(prev["risk_tier"])/(2.5*atr*100),2)
                    if lots<.01:exclusions["lot_min"]+=1
                    elif ask*lots*100/20>cash:exclusions["margin"]+=1
                    else:
                        oz=round(lots*100,8)
                        active={"at":at,"signal":q.index[i-1].strftime("%Y-%m-%d"),
                                "entry":ask+slip,"lots":lots,"oz":oz,"funding":0.,
                                "signal_bar":i-1,"atr":atr,"stop":ask+slip-5*atr}
                        entries+=1
        if active is not None:
            if mode=="PROTECTIVE_INTRADAY_STOP" and float(row["low"])<=active["stop"]:
                # Position was entered at first quote of this day. No
                # chronological intraminute bid/ask stop tape here.
                exit_trade(at,min(bid,active["stop"]),"MODELED_RESTING_STOP")
            else:
                age=i-active["signal_bar"]
                if (age>=10 or float(row["close"])-active["entry"]>=4*active["atr"]
                        or float(row["close"])<=active["stop"]):
                    pending=True
        unrealized=0. if active is None else (
            (float(row["close"])-active["entry"])*active["oz"]-active["funding"])
        marked=cash+unrealized
        peak=max(peak,marked)
        dd=min(dd,100*(marked/peak-1))
        equity.append({"day":day.strftime("%Y-%m-%d"),
                       "marked_usd":round(marked,5),"open":bool(active)})
        previous_at=at
    unrealized=0. if active is None else (
        (float(q.iloc[-1]["close"])-active["entry"])*active["oz"]-active["funding"])
    if abs(sum(t["net_usd"] for t in trades)-(cash-10000.))>.01:
        raise ValueError("Original source-independent trade ledger failed")
    gp=sum(max(0.,t["net_usd"]) for t in trades)
    gl=-sum(min(0.,t["net_usd"]) for t in trades)
    r={"year":year,"mode":mode,"initial_usd":10000.,
       "closed":len(trades),"entries":entries,
       "realized_usd":round(cash-10000.,2),
       "open_unrealized_usd":round(unrealized,2),
       "marked_usd":round(cash+unrealized-10000.,2),
       "max_daily_marked_dd_pct":round(dd,3),
       "pf":round(gp/gl,3) if gl else None,
       "open_censored":bool(active),"exclusions":exclusions,
       "slippage_per_side":slip,"commission_roundtrip_per_oz":fee,
       "financing_annual_assumed_not_puprime":financing,
       "independent_source_interpretation":True,"native_pine_parity":False,
       "spread_bid_ask_from_original_source":True,
       "no_broker_trades":True,"trades":trades,"daily_equity":equity}
    r["sha256"]=digest(r)
    return r

def research(root:Path,out:Path):
    d,receipts=source_daily(root)
    report={"schema":"aidy.g001_goldspot_v1","external_source":SOURCE,
            "original_source_blob":PIN,"source_license_not_found":True,
            "original_published_gold_was_GC_futures":True,
            "research_is_not_native_pine_or_puprime":True,
            "retrospective_not_sealed_oos":True,"no_orders":True,
            "data_receipts":receipts,"years":{}}
    for year in YEARS:
        cases={}
        for cost,slip,fee,fund in (("base",.05,.07,.06),("stress",.25,.14,.09)):
            cases[cost]={}
            for mode in METHODS:
                case=run_year(d,year,mode,slip,fee,fund)
                path=out/str(year)/cost
                path.mkdir(parents=True,exist_ok=True)
                (path/f"{mode}.json").write_text(json.dumps(case,sort_keys=True,indent=2,allow_nan=False)+"\n")
                cases[cost][mode]={k:case[k] for k in (
                    "marked_usd","realized_usd","closed","entries",
                    "max_daily_marked_dd_pct","pf","open_censored","sha256")}
        report["years"][str(year)]=cases
    report["sha256"]=digest(report)
    out.mkdir(parents=True,exist_ok=True)
    (out/"report.json").write_text(json.dumps(report,indent=2,sort_keys=True,allow_nan=False)+"\n")
    print("AIDY_G001_SPOT_VOL_REGIME",json.dumps({
        year:{mode:{"net":case["marked_usd"],"trades":case["closed"],
                    "dd":case["max_daily_marked_dd_pct"]}
              for mode,case in costs["stress"].items()}
        for year,costs in report["years"].items()},sort_keys=True),flush=True)
    return report

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--quotes",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    a=p.parse_args()
    try:research(a.quotes,a.out)
    except Exception as e:
        a.out.mkdir(parents=True,exist_ok=True)
        (a.out/"BLOCKED.json").write_text(json.dumps({
            "status":"BLOCKED_NO_PERFORMANCE","error":type(e).__name__,
            "no_synthetic_source":True},indent=2)+"\n")
        raise
