"""S001 GoldEA source-rule-faithful TWO-period AIDY research, real HistData ticks.

Published rules: GoldEA session_levels.py / strategy_edge.py / backtester.py,
pinned at their immutable GitHub blob SHAs in SOURCE_BLOBS.

2025 and 2026 each start with an INDEPENDENT $10,000 model account.
Both use SAME authenticated original HistData BID/ASK tick-source methodology,
M15 native source tick-count derived bars, causal H1/H4 confirmed swings,
the author's default anchored volume-weighted VWAP-cross exit, ATR stop,
UK session reference, and no 2R target or invented original-EA parameters.
Differences from unpublished LIVE EA: HistData tick counts are NOT MT5
broker tick_volume, AIDY next-open entry is causal rather than publisher's
optimistic signal-bar-close, and fills/costs are source-informed MODELS.
No broker, paper or live orders. No unlicensed author code executed.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

MONTH_IDS = ["202412"]+[f"2025{m:02d}" for m in range(1,13)]+[f"2026{m:02d}" for m in range(1,10)]
PERIODS = {
    "2025":{"start":"2025-01-01","end":"2026-01-01","months":[f"2025-{m:02d}" for m in range(1,13)]},
    "2026":{"start":"2026-01-01","end":"2026-10-01","months":[f"2026-{m:02d}" for m in range(1,10)]},
}
SOURCE_BLOBS = {
    "strategy_edge.py":"d763084900c02986d8691aad26b71cf87caa3af8",
    "session_levels.py":"4b0302001b849a5f3c2291f4fa9ca80f4a904558",
    "swing_structure.py":"19f14e8fa9b9fd6ad53ce8bc70e87b6f7e559686",
    "backtester.py":"eca177393950575015609002bc2fe06447e317ee",
    "indicators.py":"9f1c7583a76755945e22e494deb22f095ce3e736",
}
RULES = {
    "symbol":"XAUUSD","execution_frame":"M15","bias_frames":["H1","H4"],
    "reclaim_fraction":.5,"h1_pivot_left_right":[5,3],
    "h4_pivot_left_right":[3,2],"bias_n_confirmed_swings":2,
    "vwap_anchor":"last_confirmed_H1_swing",
    "vwap_price":"(high+low+close)/3",
    "vwap_weight":"source_HistData_tick_count_per_complete_M15_not_MT5_broker_volume",
    "atr_source":"publisher indicators.py _wilder_smooth 14 period, original seed semantics",
    "entry":"first_next_contiguous_M15_open_after_completed_signal",
    "stop":"sweep_wick_extreme_plus_1x_publisher_ATR",
    "primary_exit":"first_VWAP_cross_or_ATR_stop_or_UK_session_close",
    "target_r":None,"entry_mode":"sweep_reclaim",
    "require_vwap_confluence":False,"adx_min":None,"vol_ratio_min":None,
    "optional_M5_confirmation":False,
    "initial_usd":10000,"risk_fraction_of_current_model_equity":.01,
    "contract_gold_oz_per_lot":100,"lot_increment":.01,
    "maximum_notional_to_equity":10,"commission_per_lot_roundtrip_usd":7,
    "slippage_per_side_usd_per_oz":.10,
    "financing_assumed_usd":0,
}
OUT=Path("artifacts/strategy_lab/s001_full_2025_2026")

def read_source(root:Path):
    all_rows=[]
    receipts=[]
    prior_ts=None
    original_total=0
    for period in MONTH_IDS:
        folder=root/("s001-source-"+period)
        receipt=json.loads((folder/"receipt.json").read_text())
        if (receipt["fixed_est_month"]!=period or
            receipt["source_clock"]!="EST_FIXED_UTC_MINUS_05" or
            receipt["original_zip_modified"] is not False or
            receipt["actual_broker_fill_verified"] is not False or
            len(receipt["original_zip_sha256"])!=64 or
            len(receipt["derived_m15_sha256"])!=64):
            raise ValueError("Wrong original archive receipt for "+period)
        with (folder/"m15.csv").open(newline="",encoding="utf-8") as file:
            rows=list(csv.DictReader(file))
        clean=[]
        for x in rows:
            row={"open_time_utc":x["open_time_utc"],
                 **{k:float(x[k]) for k in ("open","high","low","close",
                            "observed_open_ask","observed_open_spread",
                            "observed_max_spread")},
                 **{k:int(x[k]) for k in ("m1_count","volume")}}
            timestamp=datetime.fromisoformat(row["open_time_utc"])
            if (timestamp.tzinfo is None or timestamp.utcoffset().total_seconds()!=0
                or timestamp.minute%15!=0 or timestamp.second or
                (prior_ts is not None and timestamp<=prior_ts)):
                raise ValueError("Original complete M15 clock out of order "+period)
            prior_ts=timestamp
            if (row["volume"]<15 or row["m1_count"]!=15 or
                row["observed_open_ask"]<row["open"] or
                abs(row["observed_open_spread"]-
                    (row["observed_open_ask"]-row["open"]))>1e-5 or
                not 0<row["low"]<=row["close"]<=row["high"] or
                not row["low"]<=row["open"]<=row["high"]):
                raise ValueError("Unqualified actual BID/ASK M15 source "+period)
            clean.append(row)
        digest=hashlib.sha256(json.dumps(clean,sort_keys=True,separators=(",",":")).encode()).hexdigest()
        if (digest!=receipt["derived_m15_sha256"] or
            len(rows)!=receipt["complete_m15"] or len(rows)<750):
            raise ValueError("M15 original source SHA or count mismatch: "+period)
        original_total+=receipt["source_tick_rows"]
        all_rows.extend(clean)
        receipts.append(receipt)
    if len(all_rows)<30000 or original_total<50_000_000:
        raise ValueError("Insufficient 2025/2026 genuine tick history")
    canon=hashlib.sha256(json.dumps(all_rows,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    df=pd.DataFrame(all_rows)
    df["open_time_utc"]=pd.to_datetime(df["open_time_utc"],utc=True)
    df=df.set_index("open_time_utc").sort_index()
    if df.index.duplicated().any():raise ValueError("Original M15 overlap")
    df.index=df.index.tz_convert("UTC").tz_localize(None)
    return df,receipts,canon

def resample_complete(data:pd.DataFrame,minutes:int,count:int):
    b=data.resample(str(minutes)+"min").agg(
        open=("open","first"),high=("high","max"),
        low=("low","min"),close=("close","last"),
        count=("open","count"))
    # Drop periods containing even one missing M15 source candle.
    return b.loc[b["count"]==count,["open","high","low","close"]].copy()

def swing_events(htf:pd.DataFrame,left:int,right:int):
    """A pivot only becomes visible AFTER the right confirming HTF bar closes."""
    hi,lo=htf["high"].to_numpy(),htf["low"].to_numpy()
    ix=htf.index
    events=[]
    for i in range(left,len(htf)-right):
        latest=ix[i+right]+pd.Timedelta(hours=1 if left==5 else 4)
        if hi[i]>=np.max(hi[i-left:i+right+1]):
            events.append((latest,"high",float(hi[i])))
        if lo[i]<=np.min(lo[i-left:i+right+1]):
            events.append((latest,"low",float(lo[i])))
    events.sort(key=lambda x:x[0])
    return events

def project_bias(times:pd.DatetimeIndex,events):
    hh,ll=[],[]
    ev=[]
    for when,kind,v in events:
        if kind=="high":hh=(hh+[v])[-2:]
        else:ll=(ll+[v])[-2:]
        bias=0
        if len(hh)==2 and len(ll)==2:
            if hh[1]>hh[0] and ll[1]>ll[0]:bias=1
            elif hh[1]<hh[0] and ll[1]<ll[0]:bias=-1
        ev.append((when,bias))
    if not ev:return np.zeros(len(times),dtype=int)
    # Duplicate event time: later event dominates, same as original drop_duplicates keep last.
    uniq=dict(ev)
    stamps=np.array(sorted(uniq),dtype="datetime64[ns]")
    values=np.array([uniq[pd.Timestamp(t)] for t in stamps],dtype=int)
    lookup=np.searchsorted(stamps,times.to_numpy(dtype="datetime64[ns]"),side="right")-1
    return np.where(lookup>=0,values[np.maximum(0,lookup)],0)

def wilder_atr_publisher(df,n=14):
    high=df["high"];low=df["low"];close=df["close"]
    tr=pd.concat([high-low,(high-close.shift()).abs(),
                   (low-close.shift()).abs()],axis=1).max(axis=1)
    values=tr.to_numpy(dtype=float)
    atr=np.full(len(df),np.nan)
    # Original indicators.py returns raw SUM at initial period, not /period.
    if len(values)>n:
        atr[n]=np.sum(values[1:n+1])
        for i in range(n+1,len(df)):
            atr[i]=(atr[i-1]*(n-1)+values[i])/n
    return atr

def build_signals(source:pd.DataFrame):
    df=source.copy()
    h1=resample_complete(df,60,4)
    h4=resample_complete(df,240,16)
    ev1=swing_events(h1,5,3)
    ev4=swing_events(h4,3,2)
    done=df.index+pd.Timedelta(minutes=15)
    df["bias1"]=project_bias(done,ev1)
    df["bias4"]=project_bias(done,ev4)
    df["bias"]=np.where(df["bias1"]==df["bias4"],df["bias1"],0)
    local=df.index.tz_localize("UTC").tz_convert("Europe/London")
    df["uk_date"]=np.asarray(local.date)
    df["uk_hour"]=local.hour+local.minute/60.0
    levels={
        "prior_day_high":("high",None),
        "prior_day_low":("low",None),
        "asian_high":("high",(0,8)),
        "asian_low":("low",(0,8)),
        "london_open_high":("high",(8,9)),
        "london_open_low":("low",(8,9)),
    }
    daily=df.groupby("uk_date").agg(high=("high","max"),low=("low","min")).shift(1)
    for key in ("prior_day_high","prior_day_low"):
        df[key]=df["uk_date"].map(daily["high" if key.endswith("high") else "low"])
    for key,(side,hours) in levels.items():
        if hours is None:continue
        subset=df[(df["uk_hour"]>=hours[0])&(df["uk_hour"]<hours[1])]
        extrema=subset.groupby("uk_date")[side].agg("max" if side=="high" else "min")
        df[key]=df["uk_date"].map(extrema)
        df.loc[df["uk_hour"]<hours[1],key]=np.nan
    high_lvls=["prior_day_high","asian_high","london_open_high"]
    low_lvls=["prior_day_low","asian_low","london_open_low"]
    price={k:df[k].to_numpy() for k in high_lvls+low_lvls}
    high,low,close=df["high"].to_numpy(),df["low"].to_numpy(),df["close"].to_numpy()
    dates=df["uk_date"].to_numpy()
    direction=np.zeros(len(df),dtype=int)
    wick=np.full(len(df),np.nan)
    old_date=None
    ph,pl={},{}
    # Reimplements the source's ordered, same-day pending sweep dictionary.
    for i in range(len(df)):
        date=dates[i]
        if date!=old_date:
            ph.clear();pl.clear();old_date=date
        span=high[i]-low[i]
        if span<=0:continue
        for lvl in high_lvls:
            p=price[lvl][i]
            if np.isfinite(p) and high[i]>p and (lvl not in ph or high[i]>ph[lvl]):
                ph[lvl]=high[i]
        for lvl in low_lvls:
            p=price[lvl][i]
            if np.isfinite(p) and low[i]<p and (lvl not in pl or low[i]<pl[lvl]):
                pl[lvl]=low[i]
        for lvl,extreme in list(ph.items()):
            v=price[lvl][i]
            if np.isfinite(v) and close[i]<v and high[i]-close[i]>=.5*span:
                direction[i]=-1;wick[i]=extreme;del ph[lvl];break
        if direction[i]==0:
            for lvl,extreme in list(pl.items()):
                v=price[lvl][i]
                if np.isfinite(v) and close[i]>v and close[i]-low[i]>=.5*span:
                    direction[i]=1;wick[i]=extreme;del pl[lvl];break
    df["signal"]=np.where(direction==df["bias"],direction,0)
    df["wick"]=wick
    df["atr"]=wilder_atr_publisher(df)
    # Publisher ffill stop references by latest sweep of SAME direction.
    df["long_wick_reference"]=pd.Series(
        np.where(direction==1,wick,np.nan),index=df.index).ffill()
    df["short_wick_reference"]=pd.Series(
        np.where(direction==-1,wick,np.nan),index=df.index).ffill()
    # ANCHORED TICK-COUNT-WEIGHTED VWAP, NOT equal-weight OHLC proxy.
    # Anchors are known no earlier than H1 swing confirming close.
    anchors=np.array(sorted(set(x[0] for x in ev1)),dtype="datetime64[ns]")
    group=np.searchsorted(anchors,done.to_numpy(dtype="datetime64[ns]"),side="right")
    typical=(df["high"]+df["low"]+df["close"])/3
    weighted=typical*df["volume"]
    cumulative_pv=weighted.groupby(group).cumsum()
    cumulative_vol=df["volume"].groupby(group).cumsum()
    df["vwap"]=cumulative_pv/cumulative_vol
    df["naive"]=np.where((df["bias"]!=0)&(df["bias"].shift(fill_value=0)!=df["bias"]),
                          df["bias"],0)
    return df

def model_period(df:pd.DataFrame,year:str,scenario:str,spread_multiplier=1.0,slippage=.1):
    months=PERIODS[year]["months"]
    cash=10000.0
    trade_rows=[]
    marks=[]
    pending=None
    position=None
    openp=df["open"].to_numpy();close=df["close"].to_numpy()
    high=df["high"].to_numpy();low=df["low"].to_numpy()
    atr=df["atr"].to_numpy();vwap=df["vwap"].to_numpy()
    signal=df["naive" if scenario=="naive_control" else "signal"].to_numpy()
    wick_long=df["long_wick_reference"].to_numpy()
    wick_short=df["short_wick_reference"].to_numpy()
    observed_spread=df["observed_open_spread"].to_numpy()
    dates=df["uk_date"].to_numpy()
    times=df.index
    for i in range(1,len(df)):
        contiguous=times[i]-times[i-1]==pd.Timedelta(minutes=15)
        if position is not None and (not contiguous or dates[i]!=dates[i-1]):
            # Source close of previous observed 15m, no carry across a session.
            cash,rec=_close(position,close[i-1],"session_close",
                    times[i-1]+pd.Timedelta(minutes=15),cash)
            trade_rows.append(rec)
            position=None
        if pending is not None and position is None and contiguous and dates[i]==dates[i-1]:
            d,j=pending
            ref=(wick_long[j] if d==1 else wick_short[j])
            if np.isfinite(ref) and np.isfinite(atr[j]) and atr[j]>0 and cash>0:
                entry=openp[i]
                stop=(min(entry,ref)-atr[j] if d==1
                    else max(entry,ref)+atr[j])
                distance=abs(entry-stop)
                maxlot=min(cash*.01/(distance*100),cash*10/(entry*100))
                lot=math.floor(maxlot*100+1e-9)/100
                if lot>=.01 and distance>0 and lot<1e6:
                    qty=lot*100
                    pspread=observed_spread[i]*spread_multiplier
                    position={
                        "direction":int(d),"entry_time":str(times[i])+"Z",
                        "signal_time":str(times[j]+pd.Timedelta(minutes=15))+"Z",
                        "entry_bid":float(entry),"stop":float(stop),
                        "lot":round(lot,2),"quantity_oz":round(qty,2),
                        "observed_entry_spread_usd_per_oz":round(observed_spread[i],5),
                        "assumed_roundtrip_spread_usd_per_oz":round(pspread,5),
                        "slippage_per_side_usd_per_oz":slippage,
                        "risk_nominal_usd":round(distance*qty,4),
                    }
        pending=None
        if position is not None:
            d=position["direction"];stop=position["stop"]
            price=None;reason=""
            if d==1 and low[i]<=stop:
                price=min(stop,openp[i]);reason="atr_stop"
            elif d==-1 and high[i]>=stop:
                price=max(stop,openp[i]);reason="atr_stop"
            elif d==1 and close[i]>=vwap[i] and close[i-1]<vwap[i-1]:
                price=close[i];reason="native_volume_sourced_vwap_cross"
            elif d==-1 and close[i]<=vwap[i] and close[i-1]>vwap[i-1]:
                price=close[i];reason="native_volume_sourced_vwap_cross"
            if price is not None:
                cash,rec=_close(position,price,reason,
                   times[i]+pd.Timedelta(minutes=15),cash)
                trade_rows.append(rec)
                position=None
        equity=cash
        if position is not None:
            d=position["direction"];qty=position["quantity_oz"]
            equity+=(close[i]-position["entry_bid"])*d*qty
            equity-=(position["assumed_roundtrip_spread_usd_per_oz"]+
                     2*position["slippage_per_side_usd_per_oz"])*qty
            equity-=7*position["lot"]
        marks.append((str(times[i]+pd.Timedelta(minutes=15))+"Z",round(equity,4)))
        if position is None and signal[i]!=0 and i+1<len(df):
            pending=(int(signal[i]),i)
    if position is not None:
        cash,rec=_close(position,close[-1],"end_of_period",
           times[-1]+pd.Timedelta(minutes=15),cash)
        trade_rows.append(rec)
    peak=10000.
    mdd=0.
    for _,value in marks:
        peak=max(peak,value)
        if peak>0:mdd=min(mdd,(value-peak)/peak)
    positives=[r["net_pnl"] for r in trade_rows if r["net_pnl"]>0]
    negatives=[r["net_pnl"] for r in trade_rows if r["net_pnl"]<0]
    monthly=[]
    for month in months:
        current=[r for r in trade_rows if min(r["exit_time"][:7],months[-1])==month]
        monthly.append({
            "month":month,"closed_trades":len(current),
            "wins":sum(r["net_pnl"]>0 for r in current),
            "losses":sum(r["net_pnl"]<0 for r in current),
            "net_pnl_usd":round(sum(r["net_pnl"] for r in current),2),
        })
    if sum(x["closed_trades"] for x in monthly)!=len(trade_rows):
        raise ValueError("Unreconciled two-period monthly trade totals")
    net=round(cash-10000,2)
    if abs(net-sum(r["net_pnl_usd"] for r in monthly))>.12:
        raise ValueError("Unreconciled full-period realised P&L")
    return {
        "period":year,"scenario":scenario,"start_usd":10000,
        "end_usd":round(cash,2),"net_usd":net,"return_pct":round(net/100,3),
        "closed_trades":len(trade_rows),"wins":len(positives),"losses":len(negatives),
        "breakevens":len(trade_rows)-len(positives)-len(negatives),
        "win_rate_pct":round(100*len(positives)/len(trade_rows),3) if trade_rows else None,
        "profit_factor":round(sum(positives)/abs(sum(negatives)),4) if negatives else None,
        "max_marked_drawdown_pct":round(100*mdd,3),
        "total_assumed_cost_usd":round(sum(r["execution_cost"] for r in trade_rows),2),
        "monthly":monthly,"trades":trade_rows,"equity_trace":marks,
    }

def _close(p,exit_bid,reason,when,cash):
    qty=p["quantity_oz"]
    gross=(exit_bid-p["entry_bid"])*p["direction"]*qty
    execution=(p["assumed_roundtrip_spread_usd_per_oz"]+
               2*p["slippage_per_side_usd_per_oz"])*qty+7*p["lot"]
    net=gross-execution
    cash+=net
    return cash,{**p,"exit_time":str(when)+"Z",
        "exit_bid":round(float(exit_bid),5),"exit_reason":reason,
        "gross_pnl":round(gross,4),"execution_cost":round(execution,4),
        "net_pnl":round(net,4),"balance_after":round(cash,4)}

def as_python(value):
    if isinstance(value,np.generic):return value.item()
    if isinstance(value,np.ndarray):return value.tolist()
    if isinstance(value,pd.Timestamp):return value.isoformat()
    raise TypeError(type(value).__name__)

def write_trades(path,trades):
    columns=["signal_time","entry_time","exit_time","direction","entry_bid","exit_bid",
      "stop","lot","quantity_oz","risk_nominal_usd",
      "observed_entry_spread_usd_per_oz",
      "assumed_roundtrip_spread_usd_per_oz","slippage_per_side_usd_per_oz",
      "exit_reason","gross_pnl","execution_cost","net_pnl","balance_after"]
    with path.open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=columns)
        w.writeheader()
        w.writerows(trades)

def main():
    cli=argparse.ArgumentParser()
    cli.add_argument("--source-root",type=Path,required=True)
    cli.add_argument("--out",type=Path,default=OUT)
    args=cli.parse_args()
    raw,receipts,data_sha=read_source(args.source_root)
    signals=build_signals(raw)
    result={}
    for year,cfg in PERIODS.items():
        sub=signals.loc[(signals.index>=pd.Timestamp(cfg["start"]))&
                       (signals.index<pd.Timestamp(cfg["end"]))].copy()
        if len(sub)<12000:
            raise ValueError("Insufficient real M15 in "+year)
        cases={
            "published_default_vwap_exit":model_period(sub,year,"published_default_vwap_exit"),
            "naive_htf_flip_control":model_period(sub,year,"naive_control"),
            "double_observed_spread_slippage":model_period(
                sub,year,"published_default_vwap_exit",spread_multiplier=2,slippage=.20),
        }
        result[year]={"m15_bars":len(sub),"scenarios":cases}
        print("S001_ORIGINAL_RULE_YEAR",json.dumps({
            "period":year,"actual_m15":len(sub),
            "models":{k:{x:v[x] for x in ("closed_trades","net_usd",
                 "end_usd","profit_factor","max_marked_drawdown_pct")}
                 for k,v in cases.items()}},default=as_python,sort_keys=True),flush=True)
    packet={
        "schema":"aidy.strategy_lab.s001.original_rules_two_period_real_ticks.v1",
        "status":"TWO_PERIOD_AUTHENTIC_TICK_SOURCE_MODEL_COMPLETE__MT5_PARITY_NOT_VERIFIED",
        "original":"https://github.com/eamonnkennedy93-blip/GoldEA",
        "source_blobs":SOURCE_BLOBS,"frozen_source_rules":RULES,
        "source_utc":"Fixed HistData EST converted +5h UTC; session Europe/London including BST",
        "date_bands":"Full calendar 2025 AND Jan-Sep 2026, independent $10k account per band",
        "unique_source_months":len(receipts),
        "market_source_receipts":receipts,
        "verified_combined_m15_sha256":data_sha,
        "independent_period_results":result,
        "input_native_MT5_tick_volume":False,
        "historical_HistData_source_tick_count_is_observed":True,
        "source_original_retail_MT5_EA_parity":False,
        "original_author_profit_factor_1_30_reproduced":False,
        "original_author_unavailable_target_selection_not_invented":True,
        "unseen_sealed_OOS_heldout":False,
        "competing_experiment_fixed_2R_excluded_from_primary":True,
        "source_entry_close_model_optimism_corrected_to_next_bar_open":True,
        "vendor_fills_swaps_stopout_verified":False,
        "broker_orders":0,
        "independent_profitability_qualified":False,
        "review_status":"ORANGE_RESEARCH_ONLY_PENDING_AUTHOR_PARITY_AND_OOS",
        "limitation_notes":[
            "Both periods use the SAME authenticated historical HistData original BID/ASK tick archives, deduped into full real M15 intervals. No fabricated candle or year-specific quote switch.",
            "Volume for VWAP is real source HistData tick count per M15. It is NOT the author's broker MetaTrader tick_volume nor real traded exchange size. Reproduction of original live EA therefore remains conditional.",
            "Exact ORIGINAL default exit from published Python backtester: first VWAP cross, stop, or day/session close. No invented 2R target used in primary.",
            "The original published Python ATR helper seeds Wilder smoothing with a SUM rather than average; original source implementation is preserved, not silently corrected. This affects stop width and trade sizing.",
            "Author's entry executes on completed signal candle close and does not include full transaction fees. AIDY requires NEXT-bar realistic price and a separate $10k net-of-costs account. Not an identical author backtester execution transcript.",
            "H1/H4 confirmed pivots are projected only when the confirming HTF bar closes; avoids author source's potentially optimistic pivot-confirmation timestamp.",
            "Model uses original tick recorded ASK at entry to estimate one full roundtrip spread, bid OHLC stop/VWAP exits, adverse slippage and $7/lot roundturn commission. Exit native ASK ticks, Vantage margin/slippage, financing and contract constraints have NOT been broker-qualified.",
            "Naive control is source-defined bias-flip with same timeframe, account, fees and risk. 2x spread/slippage stress tests fragility.",
            "Source date range and 2026 selection have already been inspected during research; 2026 is a separate calendar challenge, not a truly untouched registered holdout. No alpha or commercial green rating.",
            "Public repository's optional 5M refinement module and LIVE MQL5 EA are absent; licence unclear. Preserve original rights, and do not promote to demo without owner gate.",
        ],
    }
    packet["sha256"]=hashlib.sha256(json.dumps(
        packet,sort_keys=True,separators=(",",":"),allow_nan=False,
        default=as_python).encode()).hexdigest()
    args.out.mkdir(parents=True,exist_ok=True)
    (args.out/"S001_two_period_full_aidy_evidence.json").write_text(
        json.dumps(packet,sort_keys=True,indent=2,default=as_python)+"\n",encoding="utf-8")
    for yr,case in result.items():
        for name,result_item in case["scenarios"].items():
            write_trades(args.out/(yr+"_"+name+"_closed_trade_ledger.csv"),
                         result_item["trades"])
            with (args.out/(yr+"_"+name+"_monthly.csv")).open(
                 "w",newline="",encoding="utf-8") as f:
                w=csv.DictWriter(f,fieldnames=["month","closed_trades","wins","losses","net_pnl_usd"])
                w.writeheader();w.writerows(result_item["monthly"])
    (args.out/"S001_TWO_PERIOD_VERDICT.md").write_text(
        "# S001 GoldEA | Source-rule AIDY two-period $10k evaluation\n\n"+
        "Year-to-year results are independent $10k accounts, not compounded into a shared balance.\n\n"+
        "| Period | Trades | Net USD | End account USD | PF | Marked DD % | Naive net USD | 2x cost net USD |\n"+
        "|---|---:|---:|---:|---:|---:|---:|---:|\n"+
        "".join("| "+yr+" | "+str(case["scenarios"]["published_default_vwap_exit"]["closed_trades"])+
          " | "+str(case["scenarios"]["published_default_vwap_exit"]["net_usd"])+
          " | "+str(case["scenarios"]["published_default_vwap_exit"]["end_usd"])+
          " | "+str(case["scenarios"]["published_default_vwap_exit"]["profit_factor"])+
          " | "+str(case["scenarios"]["published_default_vwap_exit"]["max_marked_drawdown_pct"])+
          " | "+str(case["scenarios"]["naive_htf_flip_control"]["net_usd"])+
          " | "+str(case["scenarios"]["double_observed_spread_slippage"]["net_usd"])+
          " |\n" for yr,case in result.items())+
        "\n**Gate:** ORANGE research only. Not proven author native MT5 EA parity or broker net fills. "+
        "Source-tick-count VWAP, never claim broker native volume. "+
        "Full source and verdict evidence SHA256: "+packet["sha256"]+"\n",
        encoding="utf-8")
    print("S001_TWO_PERIOD_FINISHED",json.dumps({
      "status":packet["status"],"source_months":len(receipts),
      "sha256":packet["sha256"],"periods":{
        year:{k:c["scenarios"]["published_default_vwap_exit"][k]
           for k in ("closed_trades","wins","losses","net_usd",
              "end_usd","profit_factor","max_marked_drawdown_pct")}
        for year,c in result.items()}},default=as_python),flush=True)

if __name__=="__main__":
    main()
