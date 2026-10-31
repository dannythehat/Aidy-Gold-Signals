"""AIDY original XAUUSD quote test: original open-source multi-week TSMOM and squeeze ideas.

Source: zero-was-here/tradingbot (MIT; Copyright 2025 zero-was-here)
aurum/strategies/trend.py blob b6e5d320c755befd37d7c36dee7e3ed9d2e63742
aurum/strategies/breakout.py blob 06b0d6227f5f34968d137ff857461ad4e3a70dad

Two DISTINCT trading mechanism families, frozen before historical replay:
  TSMOM: multi-horizon 120/480/1440 H1 time-series momentum, equal weighted,
         EWMA volatility half-life240, forecast magnitude >= 0.25 to hold.
  SQUEEZE: BB20 2std strictly within EMA20 +/- 1.5 * ATR20 for six
         observed complete H1 candles, trade the release direction using
         20-bar vol-normalised momentum. Exit at sign flip or 36 bars.

RESEARCH PORT DIFFERENCES: source original computes continuous Carver forecasts,
downstream volatility-targeted variable exposure, complex financing/combiner.
Here discrete +/-1 directional exposure is independently predeclared, one oz,
H1 next-open spot BID/ASK, 2.5xATR protective fixed SL, time/forecast exits,
flat when no signal, and flat end-of-year valuation separately recorded.
Strict H1 data = original verified 60/60 M1 observations; no prices synthesized.
Research financing charged at illustrative base 6% and stressed 9%/annum
on notional, NOT claimed to be actual PU Prime swap. Also no broker margin or
order parity; source original docs report its own weak walk-forward evidence.
No OOS claim (2023-25 viewed before this research), no real/paper orders.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scripts.gold_hunter_2023_2024_causal_research import source_year

SOURCE="https://github.com/zero-was-here/tradingbot"
BLOBS={"trend.py":"b6e5d320c755befd37d7c36dee7e3ed9d2e63742",
       "breakout.py":"06b0d6227f5f34968d137ff857461ad4e3a70dad"}
YEAR=(2023,2024,2025)
START=10000.
FAMILIES=("TSMOM_MULTI_HORIZON","BB_KC_SQUEEZE_RELEASE")


def digest(payload):
    return hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(",",":"),
                                     allow_nan=False).encode()).hexdigest()


def indicators(raw:pd.DataFrame):
    df=raw.sort_values("open_time_utc").reset_index(drop=True).copy()
    if df["open_time_utc"].duplicated().any() or not df["open_time_utc"].is_monotonic_increasing:
        raise ValueError("Unordered or duplicate source H1")
    close=df["close"].astype(float)
    high=df["high"].astype(float)
    low=df["low"].astype(float)
    previous=close.shift()
    true_range=pd.concat([high-low,(high-previous).abs(),(low-previous).abs()],
                         axis=1).max(axis=1)
    atr20=true_range.rolling(20,min_periods=20).mean()
    atr14=true_range.rolling(14,min_periods=14).mean()
    lc=np.log(close)
    ret=lc.diff()
    # Align with open-source bar_volatility: causal, normalised EWMA of r^2.
    sigma240=np.sqrt((ret*ret).ewm(
        halflife=240,adjust=True,min_periods=120).mean())
    sigma120=np.sqrt((ret*ret).ewm(
        halflife=120,adjust=True,min_periods=60).mean())
    scaled=[]
    horizons=(120,480,1440)
    for horizon in horizons:
        z=(lc-lc.shift(horizon))/(sigma240*math.sqrt(horizon))
        scaled.append(np.clip(.626657*z,-1,1))
    # Equal-weight Carver-style historical momentum: discrete threshold is
    # independently chosen for this research, not native source position.
    tsmom=(scaled[0]+scaled[1]+scaled[2])/3.
    direction_mom=np.where(tsmom>=.25,1,np.where(tsmom<=-.25,-1,0))
    direction_mom=np.where(np.isfinite(tsmom),direction_mom,0)
    sma20=close.rolling(20,min_periods=20).mean()
    std20=close.rolling(20,min_periods=20).std(ddof=0)
    ema20=close.ewm(span=20,adjust=False,min_periods=20).mean()
    on=((sma20+2*std20)<(ema20+1.5*atr20)) & (
        (sma20-2*std20)>(ema20-1.5*atr20))
    z20=(lc-lc.shift(20))/(sigma120*math.sqrt(20))
    squeeze=np.zeros(len(df),dtype=np.int8)
    state=0
    held=0
    run=0
    releases=0
    for i in range(len(df)):
        signal=float(z20.iloc[i])
        valid=math.isfinite(signal)
        if state:
            held+=1
            if held>=36 or not valid or signal*state<0:
                state=0
        if not bool(on.iloc[i]) and run>=6 and valid and signal!=0:
            state=1 if signal>0 else -1
            held=0
            releases+=1
        run=run+1 if bool(on.iloc[i]) else 0
        squeeze[i]=state
    df["signal_tsmom"]=direction_mom
    df["signal_squeeze"]=squeeze
    df["ATR14"]=atr14
    df["ATR20"]=atr20
    return df, {"squeeze_releases":releases,
                 "squeeze_exposure_bars":int(np.count_nonzero(squeeze)),
                 "tsmom_exposure_bars":int(np.count_nonzero(direction_mom)),
                 "momentum_complete_bars":int(tsmom.notna().sum())}


@dataclass
class Position:
    side:int
    entry:float
    at:pd.Timestamp
    stop:float
    family:str
    financing:float=0.


def replay(df:pd.DataFrame,family:str,*,slippage:float,
           commission:float,financing_rate:float):
    if family not in FAMILIES:
        raise ValueError("Unregistered external mechanism")
    sig="signal_tsmom" if family=="TSMOM_MULTI_HORIZON" else "signal_squeeze"
    current=None
    cash=START
    peak=START
    dd=0.
    closes=[]
    max_open_adverse=0.
    gap_hours=0.
    blocked_side=0  # stop-out blocks repetitive re-entry until signal resets
    skipped=0
    entries=0
    hourly_equity=[]
    for i in range(len(df)):
        row=df.iloc[i]
        now=row["open_time_utc"]
        op=float(row["open"])
        ask=float(row["observed_open_ask"])
        spread=ask-op
        high=float(row["high"]);low=float(row["low"])
        # Note max mean spread within hour is ONLY a proxy for adverse ASK,
        # NOT a contemporaneous max tick spread and not a decision input.
        proxy_spread=max(float(row["observed_max_spread"]),spread)
        if spread<0 or not all(math.isfinite(z) for z in (op,ask,high,low,proxy_spread)):
            raise ValueError("Invalid original quote geometry")
        target=int(df.iloc[i-1][sig]) if i>0 else 0
        if target!=blocked_side:
            blocked_side=0
        def close_position(price:float, reason:str):
            nonlocal cash,current,blocked_side
            if current is None:
                raise ValueError("No current trade")
            out=price-current.side*slippage
            realized=(out-current.entry)*current.side - commission - current.financing
            cash+=realized
            if reason=="PROTECTIVE_STOP":
                blocked_side=current.side
            closes.append({
                "family":family,"entry_utc":current.at.isoformat(),
                "exit_utc":now.isoformat(),"side":current.side,"reason":reason,
                "entry_price":round(current.entry,6),
                "exit_price":round(out,6),"gross_minus_spread_and_slip_usd":
                    round((out-current.entry)*current.side,6),
                "commission_usd":commission,
                "financing_usd":round(current.financing,6),
                "net_usd":round(realized,6),
            })
            current=None
        if current is not None:
            elapsed=(now-df.iloc[i-1]["open_time_utc"]).total_seconds()/3600
            if elapsed<0:
                raise ValueError("Chronology reversed")
            current.financing+=current.entry*financing_rate*elapsed/(365*24)
            if elapsed>24:
                gap_hours+=elapsed-1
        if current is not None and target!=current.side:
            close_position(op if current.side==1 else ask, "FORECAST_EXIT")
        if current is None and target and i>0 and target!=blocked_side:
            # Signal comes strictly from previous completed H1 bar.
            atr=float(df.iloc[i-1]["ATR14"])
            if not math.isfinite(atr) or atr<=0:
                skipped+=1
            else:
                side=target
                price=(ask if side==1 else op)+side*slippage
                current=Position(side,price,now,price-side*2.5*atr,family)
                entries+=1
        if current is not None:
            if current.side==1:
                stop_hit=low<=current.stop
                adverse=low
                exit_at=min(current.stop,op)
            else:
                stop_hit=high+proxy_spread>=current.stop
                adverse=high+proxy_spread
                exit_at=max(current.stop,ask)
            max_open_adverse=min(max_open_adverse,(adverse-current.entry)*current.side-
                                 current.financing)
            if stop_hit:
                close_position(exit_at,"PROTECTIVE_STOP")
        # Observed BID marks for long; estimated short ASK using observed
        # mean spread proxy. Never source parity / real tick equity.
        if current is not None:
            mark=(float(row["close"]) if current.side==1
                  else float(row["close"])+proxy_spread)
            equity=cash+(mark-current.entry)*current.side-current.financing
        else:
            equity=cash
        peak=max(peak,equity)
        dd=min(dd,100*(equity/peak-1))
        hourly_equity.append(equity)
    if abs(cash-START-sum(t["net_usd"] for t in closes))>.01:
        raise ValueError("Trade ledger mismatch")
    if current is None:
        unrealized=0.
    else:
        last=df.iloc[-1]
        final=(float(last["close"]) if current.side==1 else
               float(last["close"])+float(last["observed_max_spread"]))
        unrealized=(final-current.entry)*current.side-current.financing
    gp=sum(max(t["net_usd"],0) for t in closes)
    gl=-sum(min(t["net_usd"],0) for t in closes)
    result={
        "family":family,"source":SOURCE,"no_source_native_parity":True,
        "initial_usd":START,"closed_trades":len(closes),
        "entries":entries,"wins":sum(t["net_usd"]>0 for t in closes),
        "realized_usd":round(cash-START,2),
        "unrealized_usd_estimated":round(unrealized,2),
        "marked_net_usd":round(cash+unrealized-START,2),
        "max_marked_hourly_drawdown_pct":round(dd,3),
        "max_unrealized_adverse_excursion_usd_approx":round(max_open_adverse,2),
        "profit_factor":round(gp/gl,3) if gl else None,
        "open_censored":bool(current),"source_h1_missing_gaps_extra_hours":gap_hours,
        "rejected_signal_no_atr":skipped,
        "protective_stop_locks_same_forecast_until_reset":True,
        "slippage_per_side":slippage,
        "roundtrip_commission_per_ounce":commission,
        "illustrative_annual_financing_charge_rate":financing_rate,
        "no_actual_broker_quotes_or_swaps":True,
        "trade_ledger":closes,
    }
    result["sha256"]=digest(result)
    return result


def research(quotes:Path,out:Path):
    report={
        "schema":"aidy.gold.hunt_external_source_multihorizon_2023_2025.v1",
        "external_repo":SOURCE,"source_blobs":BLOBS,
        "original_license":"MIT",
        "source_native_execution_parity":False,
        "two_distinct_hypotheses":[*FAMILIES],
        "original_author_OOS_2016_2024_sharpe":
            {"TSMOM_MULTI_HORIZON":0.01,"BB_KC_SQUEEZE_RELEASE":0.09},
        "historical_2023_2025_are_development_not_sealed_oos":True,
        "no_live_paper_orders":True,"years":{},
    }
    for year in YEAR:
        bars,proof=source_year(quotes,year)
        feature,coverage=indicators(bars)
        year_results={}
        for scenario,slip,fee,finance in (
            ("base",.05,.07,.06),("stress",.25,.14,.09)):
            year_results[scenario]={}
            for family in FAMILIES:
                v=replay(feature,family,slippage=slip,commission=fee,
                         financing_rate=finance)
                folder=out/str(year)/scenario
                folder.mkdir(parents=True,exist_ok=True)
                (folder/f"{family}.json").write_text(
                    json.dumps(v,sort_keys=True,indent=2,allow_nan=False)+"\n")
                year_results[scenario][family]={
                    k:v[k] for k in ("marked_net_usd","realized_usd",
                                      "unrealized_usd_estimated","entries",
                                      "closed_trades","max_marked_hourly_drawdown_pct",
                                      "profit_factor","open_censored","sha256")}
        report["years"][str(year)]={"source":proof,"coverage":coverage,
                                    "results":year_results}
    report["sha256"]=digest(report)
    out.mkdir(parents=True,exist_ok=True)
    (out/"summary.json").write_text(json.dumps(
        report,sort_keys=True,indent=2,allow_nan=False)+"\n")
    print("AIDY_ORIGINAL_OUTSIDE_SLOW_GOLD",json.dumps({
        year:{family:{"marked":x["marked_net_usd"],
                      "closed":x["closed_trades"],
                      "drawdown":x["max_marked_hourly_drawdown_pct"],
                      "open":x["open_censored"]}
              for family,x in v["results"]["stress"].items()}
        for year,v in report["years"].items()},sort_keys=True),flush=True)
    return report


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--quotes",required=True,type=Path)
    p.add_argument("--out",required=True,type=Path)
    a=p.parse_args()
    try:
        research(a.quotes,a.out)
    except Exception as exc:
        a.out.mkdir(parents=True,exist_ok=True)
        (a.out/"BLOCKED.json").write_text(
            json.dumps({"not_tested":True,"exception_type":type(exc).__name__,
                        "no_unverified_market_data_substitute":True},indent=2)+"\n")
        raise
