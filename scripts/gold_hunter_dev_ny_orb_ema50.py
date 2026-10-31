"""AIDY independent source-inspired DEV article ORB+EMA50+ATR 5R test.

Citation: Abdelrahman Al allaqi, "I Built a Gold Trading Bot from Scratch",
DEV 2026-04-21:
https://dev.to/alallaqi/i-built-a-gold-trading-bot-from-scratch-heres-what-actually-works-and-what-destroyed-my-account-3pij

CLAIM UNVERIFIED: author's alleged +41% CAGR 99-trade GC=F 2023-26
test cannot be source-native (no executable original published).
Published 13:00/14:00/15:00 UTC candles are defined as "opening range"
with signal at 16:00 UTC close vs that same range; mathematically impossible.
Literal hypothesis intentionally reports zero signals, NOT a losing system.

Two independently frozen research REPAIRS (NOT source parity):
 A) Fixed clock: 13/14/15 UTC 3-hour range, signal closed 16-17 UTC
    bar, entry at start 17 UTC (causal but author timing changed).
 B) Correct NY exchange-local clock: 09/10/11 America/New_York H1
    range, 12-13 local signal, entry 13 local, with US DST.
These are two clocks for ONE strategy family. H1 gold spot 2023-25 quotes
from original authenticated PR374 BID/ASK M1 derivatives, 60/60 M1 observed
per H1. Original article is GC gold futures proxy, not these spot quotes.
EMA50 on completed H1 BID close, Wilder ATR14 on completed H1 BID OHLC,
1.5 ATR stop, 5R target, original article risk 2%, one open at a time.
Additional unprovided EXIT POLICY: five trading days maximum = 120
complete H1 bars from entry; one author claim cannot be replicated with
unpublished exit. No hidden optimisation. Original absence of code and
stop/target chronology means independent research NOT exact author run.

Spread from original observed H1 open ASK/BID. H1 short adverse extrema
ASK estimated using retrospective max-M1-mean spread (NOT tick quote parity),
stop beats target if ambiguous, worst gap at next opening price. Fee and
financing independent assumptions, NOT PU Prime broker-confirmed.
Research NO live / paper orders, OOS not sealed, old 83 dedup S050 S051.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from scripts.gold_hunter_2023_2024_causal_research import source_year

START=10000.
MODES=("FIXED_UTC_REPAIRED","NEWYORK_LOCAL_DST_REPAIRED")
MAX_HOLD_COMPLETE_H1=120
R_MULTIPLE=5.
ATR_MULTIPLE=1.5
EMA_SPAN=50
RISK_FRACTION=.02
LOT_OZ=1.
LEVERAGE_ASSUMED=20.
UTC=ZoneInfo("UTC")
NEWYORK=ZoneInfo("America/New_York")
SOURCE_URL="https://dev.to/alallaqi/i-built-a-gold-trading-bot-from-scratch-heres-what-actually-works-and-what-destroyed-my-account-3pij"


def checksum(obj):
    return hashlib.sha256(json.dumps(obj,sort_keys=True,allow_nan=False,
                                     separators=(",",":")).encode()).hexdigest()


def enrich(h1):
    x=h1.sort_values("open_time_utc").reset_index(drop=True).copy()
    if x["open_time_utc"].duplicated().any():
        raise ValueError("Duplicate original quote H1")
    if not (x["m1_count"]==60).all():
        raise ValueError("Do not simulate synthetic or incomplete original H1")
    if (x["observed_open_ask"]<x["open"]).any():
        raise ValueError("Original ASK below BID")
    prev=x["close"].shift()
    tr=pd.concat([x["high"]-x["low"],(x["high"]-prev).abs(),
                  (x["low"]-prev).abs()],axis=1).max(axis=1)
    x["atr14"]=tr.ewm(alpha=1/14,adjust=False,min_periods=14).mean()
    x["ema50"]=x["close"].ewm(span=EMA_SPAN,adjust=False,
                              min_periods=EMA_SPAN).mean()
    return x


def literal_same_bar_impossible(h1):
    """Author range includes 15:00 UTC candle, close at 16:00 UTC.
    That close is <= maximum high and >= minimum low of its own range.
    True by OHLC construction, regardless of dataset/year/fees.
    """
    x=h1.copy()
    x["day"]=x["open_time_utc"].dt.strftime("%Y-%m-%d")
    x["hour"]=x["open_time_utc"].dt.hour
    checked=0
    for _,d in x.groupby("day",sort=True):
        first=d[d["hour"].isin((13,14,15))]
        if len(first)!=3 or set(first["hour"])!={13,14,15}:
            continue
        signal=float(first.loc[first["hour"]==15,"close"].iloc[0])
        high=float(first["high"].max());low=float(first["low"].min())
        if not low<=signal<=high:
            raise ValueError("Original source quote geometry inconsistent with high/low")
        checked+=1
    return {"checked_full_3h_windows":checked,"strict_literal_signals":0,
            "impossibility_is_by_definition":True}


def source_inspired_signals(h1,mode):
    if mode not in MODES:
        raise ValueError("Unknown predeclared clock mode")
    x=enrich(h1)
    dates=x["open_time_utc"]
    if mode=="FIXED_UTC_REPAIRED":
        local=dates.dt.tz_convert(UTC)
        range_hours=(13,14,15);signal_hour=16;entry_hour=17
    else:
        local=dates.dt.tz_convert(NEWYORK)
        range_hours=(9,10,11);signal_hour=12;entry_hour=13
    x["local_day"]=local.dt.strftime("%Y-%m-%d")
    x["local_hour"]=local.dt.hour
    x["local_weekday"]=local.dt.weekday
    sig=[]
    gaps=0
    for day,d in x.groupby("local_day",sort=True):
        if int(d["local_weekday"].iloc[0])>=5:
            continue
        rang=d[d["local_hour"].isin(range_hours)]
        observed=d[d["local_hour"]==signal_hour]
        after=d[d["local_hour"]==entry_hour]
        if (len(rang)!=3 or len(observed)!=1 or len(after)!=1
                or set(rang["local_hour"])!=set(range_hours)):
            gaps+=1;continue
        times=rang["open_time_utc"].to_list()
        if any(times[i+1]-times[i]!=pd.Timedelta(hours=1) for i in (0,1)):
            gaps+=1;continue
        s=observed.iloc[0];e=after.iloc[0]
        if (s["open_time_utc"]-times[-1]!=pd.Timedelta(hours=1)
            or e["open_time_utc"]-s["open_time_utc"]!=pd.Timedelta(hours=1)):
            gaps+=1;continue
        if not math.isfinite(float(s["atr14"])) or not math.isfinite(float(s["ema50"])):
            continue
        high=float(rang["high"].max());low=float(rang["low"].min())
        side=(1 if s["close"]>high and s["close"]>s["ema50"]
              else -1 if s["close"]<low and s["close"]<s["ema50"] else 0)
        if not side:
            continue
        sig.append({"signal_at_utc":(s["open_time_utc"]+pd.Timedelta(hours=1)).isoformat(),
                    "range_start_utc":times[0].isoformat(),
                    "entry_at_utc":e["open_time_utc"].isoformat(),
                    "entry_idx":int(e.name),
                    "direction":side,"range_high_bid":high,
                    "range_low_bid":low,"signal_closed_bid":float(s["close"]),
                    "ema50_bid":float(s["ema50"]),
                    "atr14_bid":float(s["atr14"]),
                    "clock_mode":mode})
    return x,sig,{"days_with_missing_or_partial_clock_windows":gaps,
                  "source_signals":len(sig)}


def account_replay(x,signals,*,slip,roundtrip_fee_per_oz,annual_carry,mode):
    if mode not in MODES:raise ValueError("Unknown mode")
    eligible={item["entry_idx"]:item for item in signals}
    cash=START;peak=START.;mdd=0.;open_trade=None
    ledger=[];max_unreal=0.;rejected={"overlap":0,"lot_min":0,"margin":0}
    count=0
    for i,row in x.iterrows():
        bid=float(row["open"]);ask=float(row["observed_open_ask"])
        low=float(row["low"]);high=float(row["high"])
        sp=max(float(row["observed_max_spread"]),ask-bid)
        at=row["open_time_utc"]
        if open_trade is not None:
            t=open_trade;side=t["direction"]
            adverse_low=(low if side==1 else high+sp)
            max_unreal=min(max_unreal,
                           (adverse_low-t["entry"])*side*t["oz"])
            stop_hit=(low<=t["stop"] if side==1 else high+sp>=t["stop"])
            tgt_hit=(high>=t["target"] if side==1 else low+sp<=t["target"])
            held=i-t["i"]
            reason=None
            if stop_hit:reason="STOP_FIRST_H1"
            elif tgt_hit:reason="TARGET_RESTING_H1"
            elif held>=MAX_HOLD_COMPLETE_H1:reason="ADAPTED_120H_TIMEOUT"
            if reason:
                if stop_hit:
                    raw=(min(t["stop"],bid) if side==1 else max(t["stop"],ask))
                    px=raw-side*slip
                elif tgt_hit:px=t["target"]
                else:px=(bid if side==1 else ask)-side*slip
                hours=max(0.,(at-t["at"]).total_seconds()/3600)
                fee=roundtrip_fee_per_oz*t["oz"]
                carry=t["entry"]*t["oz"]*annual_carry*hours/(365*24)
                gross=(px-t["entry"])*side*t["oz"]
                net=gross-fee-carry
                cash+=net
                ledger.append({"entry_utc":t["at"].isoformat(),"exit_utc":at.isoformat(),
                   "side":side,"reason":reason,"oz":t["oz"],
                   "entry":round(t["entry"],6),"exit":round(px,6),
                   "stop":round(t["stop"],6),"target":round(t["target"],6),
                   "gross_usd":round(gross,6),"fee_usd":round(fee,6),
                   "carry_usd":round(carry,6),"net_usd":round(net,6),
                   "cash_after_exit":round(cash,6)})
                open_trade=None
        # Source clock signal at preceding H1 close; use next observed BID/ASK open.
        if i in eligible:
            s=eligible[i]
            if open_trade is not None:
                rejected["overlap"]+=1
            else:
                side=s["direction"];entry=(ask if side==1 else bid)+side*slip
                risk_price=ATR_MULTIPLE*s["atr14"]
                target=entry+side*R_MULTIPLE*risk_price
                stop=entry-side*risk_price
                # Quantize risk budget DOWN to 0.01 standard lot = 1oz.
                oz=math.floor(cash*RISK_FRACTION/risk_price)
                if oz<LOT_OZ:rejected["lot_min"]+=1
                elif entry*oz/LEVERAGE_ASSUMED>cash:rejected["margin"]+=1
                else:
                    open_trade={"at":at,"i":i,"direction":side,"entry":entry,
                                "stop":stop,"target":target,"oz":float(oz)}
                    count+=1
                    # A market entry occurs at the observed first quote of this
                    # H1. Its subsequent intrabar extremes can touch SL or TP.
                    # With no tick path the STOP is charged first whenever both
                    # levels occur within the same actual complete H1 candle.
                    entry_stop=(low<=stop if side==1 else high+sp>=stop)
                    entry_target=(high>=target if side==1 else low+sp<=target)
                    if entry_stop or entry_target:
                        if entry_stop:
                            raw=min(stop,bid) if side==1 else max(stop,ask)
                            px=raw-side*slip
                            reason="ENTRY_HOUR_STOP_FIRST"
                        else:
                            px=target
                            reason="ENTRY_HOUR_TARGET"
                        fee=roundtrip_fee_per_oz*float(oz)
                        net=(px-entry)*side*float(oz)-fee
                        cash+=net
                        ledger.append({"entry_utc":at.isoformat(),
                           "exit_utc":at.isoformat(),"side":side,"reason":reason,
                           "oz":float(oz),"entry":round(entry,6),
                           "exit":round(px,6),"stop":round(stop,6),
                           "target":round(target,6),
                           "gross_usd":round((px-entry)*side*float(oz),6),
                           "fee_usd":round(fee,6),"carry_usd":0.,
                           "net_usd":round(net,6),
                           "cash_after_exit":round(cash,6)})
                        open_trade=None
        if open_trade is None:mark=cash
        else:
            t=open_trade;side=t["direction"]
            mark=cash+(float(row["close"])+(sp if side==-1 else 0)
                       -t["entry"])*side*t["oz"]
            hours=max(0,(at-t["at"]).total_seconds()/3600)
            mark-=t["entry"]*t["oz"]*annual_carry*hours/(365*24)
        peak=max(peak,mark)
        mdd=min(mdd,100*(mark/peak-1))
    open_censored=False
    marked=cash
    if open_trade:
        open_censored=True
        t=open_trade;last=x.iloc[-1]
        side=t["direction"];sp=float(last["observed_max_spread"])
        final=(float(last["close"]) if side==1 else float(last["close"])+sp)
        hours=max(0,(last["open_time_utc"]-t["at"]).total_seconds()/3600)
        carry=t["entry"]*t["oz"]*annual_carry*hours/(365*24)
        marked=cash+(final-t["entry"])*side*t["oz"]-carry
    sum_net=sum(z["net_usd"] for z in ledger)
    if abs(sum_net-(cash-START))>.02:
        raise ValueError("Original source quote closed-trade cash ledger mismatch")
    gp=sum(max(0.,z["net_usd"]) for z in ledger)
    gl=-sum(min(0.,z["net_usd"]) for z in ledger)
    return {"scenario":mode,"original_author_native_parity":False,
            "entry_bar_stop_first_if_both_extrema_hit":True,
            "slippage_per_side":slip,"fee_per_oz_roundtrip":roundtrip_fee_per_oz,
            "hypothetical_annual_financing_not_puprime":annual_carry,
            "start_usd":START,"signal_count":len(signals),
            "entries":count,"closed":len(ledger),
            "net_realized_usd":round(cash-START,2),
            "net_marked_usd":round(marked-START,2),
            "open_censored":open_censored,
            "profit_factor":round(gp/gl,3) if gl else None,
            "max_h1_marked_drawdown_pct":round(mdd,3),
            "worst_h1_approx_unrealized_excursion_usd":round(max_unreal,2),
            "nonexecuted":rejected,"ledger":ledger,
            "five_day_timeout_not_specified_in_article":True,
            "stop_first_in_ambiguous_H1":True,
            "no_broker_orders":True}


def research(root:Path,out:Path):
    report={"schema":"aidy.external_dev_ny_3h_ema50_5R_2023_25.v1",
        "source":SOURCE_URL,"published_author_results_independently_verified":False,
        "published_author_claims":{"full_pf":1.91,"oos_pf":2.71,
             "cagr_pct":41,"max_dd_pct":17.5,"trades":99,
             "original_data":"GC=F futures, not spot"},
        "is_exact_author_replication":False,
        "quote_data":"authenticated original PR374 XAUUSD spot M1 -> complete 60/60 H1",
        "not_out_of_sample":True,
        "dedup_catalogue_ids":["S049","S050","S051"],
        "no_live_or_paper_orders":True,"years":{}}
    for year in (2023,2024,2025):
        source,proof=source_year(root,year)
        literal=literal_same_bar_impossible(source)
        x=enrich(source)
        cases={}
        for mode in MODES:
            df,signals,coverage=source_inspired_signals(source,mode)
            if not df["open_time_utc"].equals(x["open_time_utc"]):
                raise ValueError("Signals consumed mismatched original H1")
            directory=out/str(year)/mode
            directory.mkdir(parents=True,exist_ok=True)
            (directory/"signals.json").write_text(json.dumps(signals,indent=2,allow_nan=False)+"\n")
            scenarios={}
            for cost,slip,fee,finance in (
                ("base",.05,.07,.06),("stress",.25,.14,.09)):
                result=account_replay(df,signals,slip=slip,
                    roundtrip_fee_per_oz=fee,annual_carry=finance,mode=mode)
                (directory/f"{cost}_ledger.json").write_text(
                    json.dumps(result,indent=2,sort_keys=True,allow_nan=False)+"\n")
                scenarios[cost]={k:v for k,v in result.items() if k!="ledger"}
            cases[mode]={"signal_coverage":coverage,"cost_cases":scenarios}
        report["years"][str(year)]={"original_quote_receipt":proof,
                    "strict_literal":literal,"repaired_clock_comparisons":cases}
        print("AIDY_DEV_ORB_YEAR",json.dumps({"year":year,"literal":literal,
           "stress":{m:{k:v for k,v in c["cost_cases"]["stress"].items()
                         if k in ("signal_count","entries","closed","net_marked_usd",
                                  "max_h1_marked_drawdown_pct","open_censored")}
                     for m,c in cases.items()}},sort_keys=True),flush=True)
    report["sha256"]=checksum(report)
    out.mkdir(parents=True,exist_ok=True)
    (out/"report.json").write_text(json.dumps(report,sort_keys=True,
                                indent=2,allow_nan=False)+"\n")
    return report


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--quotes",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    a=p.parse_args()
    try:research(a.quotes,a.out)
    except Exception as exc:
        a.out.mkdir(parents=True,exist_ok=True)
        (a.out/"BLOCKED.json").write_text(json.dumps({
            "not_tested":True,"reason":type(exc).__name__,
            "never_synthesize_original_source":True},indent=2)+"\n")
        raise
