"""S003 Breakout Follow Trend 101: audited M15 source-default economic screening.

Source SHA pins:
  Pine  6e2155c878f90fdd1cdcedcf7b00848828d1458d
  MQL5  2d6e0eee1a2f49ff61bdc4d6edbba233b50a56dd
  README 6e673537a16731a597ba51cc2b6305ba5e25574e

CRITICAL distinctions:
* Actual Pine defaults: New York exchange time 12:00-18:00, cooldown 6.
  MQL5 defaults 19:00-01:00 broker UTC+3, cooldown 6.
* README high-win preset: 00:00-15:00 New York, cooldown 3, NOT defaults.
* MQL5/TradingView native broker tick volumes have NOT been captured.
  Source-observed HistData tick counts are authentic source volume PROXY,
  never label MT5/Pepperstone parity proven.
* Real BID/ASK tick archives are source verified and reused from S001,
  no new fabricated tick source or price history. Existing bid OHLC
  and ACTUAL opening ASK/max spread available; SHORT ask intrabar
  excursion remains a model (no full native ask path).
* This is historical AIDY reimplementation of public rules, NOT actual
  execution of author Pine/MT5 and NOT a Vantage live fills report.
* Two separate $10k model accounts: all 2025 and Jan-Sep2026.
* If a session regime is attractive, it is an examined preset, NOT sealed OOS.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.strategy_lab.s001_two_period_original_rules import read_source

OUT=Path("artifacts/strategy_lab/s003_2025_2026")
SOURCE={
    "original":"https://github.com/jzd101/breakout-follow-101",
    "pine_blob":"6e2155c878f90fdd1cdcedcf7b00848828d1458d",
    "mql5_blob":"2d6e0eee1a2f49ff61bdc4d6edbba233b50a56dd",
    "readme_blob":"6e673537a16731a597ba51cc2b6305ba5e25574e",
}
PERIODS={
 "2025":("2025-01-01","2026-01-01",12),
 "2026":("2026-01-01","2026-10-01",9),
}
DEFAULTS={
 "time_zone":"America/New_York","session_start_hour":12,"session_end_hour":18,
 "cooldown_bars":6,
 "risk_pct_current_equity":1.0,"rr_full_target":2.0,
 "atr_n":18,"atr_sl_multiplier":2.0,"ema_n":200,
 "bb_n":15,"bb_population_stdev_multiplier":1.5,
 "volume_sma_n":15,"volume_gate_enabled":True,
 "ema_gate_enabled":True,"ema_overlap_filter_enabled":False,
 "max_open_trades":1,"daily_realised_loss_limit_pct":1.0,
 "partial_exit_enabled":True,"partial_trigger_rr":1.6,
 "partial_exit_fraction":0.50,
 "weekend_force_close_enabled":False,
 "gold_ounces_per_lot":100.0,"lot_step":0.01,
 "max_notional_over_account":10.0,
 "slippage_per_side_per_oz_usd":0.10,
 "commission_round_trip_usd_per_standard_lot":7.0,
 "broker_swap_cost_verified":False,
}
README_PRESET={**DEFAULTS,"session_start_hour":0,"session_end_hour":15,"cooldown_bars":3}

def compute_indicators(raw):
    d=raw.copy()
    c=d["close"];h=d["high"];l=d["low"]
    d["ema"]=c.ewm(span=200,adjust=False,min_periods=200).mean()
    basis=c.rolling(15,min_periods=15).mean()
    deviations=c.rolling(15,min_periods=15).std(ddof=0)
    d["bbupper"]=basis+1.5*deviations
    d["bblower"]=basis-1.5*deviations
    tr=pd.concat([h-l,(h-c.shift(1)).abs(),(l-c.shift(1)).abs()],axis=1).max(axis=1)
    # True Wilder RMA: seed as arithmetic mean, alpha=1/18.
    values=tr.to_numpy(dtype=float)
    atr=np.full(len(d),np.nan,dtype=float)
    n=18
    if len(d)>=n:
        atr[n-1]=np.mean(values[:n])
        for i in range(n,len(d)):
            atr[i]=(atr[i-1]*(n-1)+values[i])/n
    d["atr"]=atr
    d["volma"]=d["volume"].rolling(15,min_periods=15).mean()
    ny=d.index.tz_localize("UTC").tz_convert("America/New_York")
    d["ny_day"]=np.asarray(ny.date)
    d["ny_hour"]=ny.hour.to_numpy()
    return d

def _sizing(equity,sl_dist,entry):
    if equity<=0 or sl_dist<=0 or entry<=0:return 0.0
    risk_lots=(equity*0.01)/(sl_dist*100)
    exposure_lots=equity*10.0/(entry*100)
    lot=math.floor(min(risk_lots,exposure_lots)*100+1e-9)/100
    return max(0.0,round(lot,2))

def _signal(row,opts):
    if not np.isfinite(row["atr"]) or not np.isfinite(row["ema"]) or not np.isfinite(row["bbupper"]) or not np.isfinite(row["volma"]):
        return 0
    hr=int(row["ny_hour"])
    start,end=opts["session_start_hour"],opts["session_end_hour"]
    allowed=(start<=hr<end) if start<end else (hr>=start or hr<end)
    if not allowed:return 0
    if opts["volume_gate_enabled"] and not float(row["volume"])>float(row["volma"]):return 0
    if opts["ema_overlap_filter_enabled"] and row["low"]<=row["ema"]<=row["high"]:
        return 0
    if row["close"]>row["bbupper"] and (not opts["ema_gate_enabled"] or row["close"]>row["ema"]):
        return 1
    if row["close"]<row["bblower"] and (not opts["ema_gate_enabled"] or row["close"]<row["ema"]):
        return -1
    return 0

def _exit_leg(p,lot,exit_quote,reason,time,friction_mult):
    # BID/ASK entry quote is observed source, but intrabar short exit ASK is
    # source BID plus max historical spread, a stress-minded model.
    oz=lot*100.
    gross=(exit_quote-p["entry_quote"])*p["side"]*oz
    fee=lot*DEFAULTS["commission_round_trip_usd_per_standard_lot"]
    slip=oz*2*DEFAULTS["slippage_per_side_per_oz_usd"]*friction_mult
    net=gross-fee-slip
    return {
       "timestamp":str(time)+"Z","exit_reason":reason,
       "quantity_lot":round(lot,2),"exit_quote":round(float(exit_quote),5),
       "price_pnl_usd":round(gross,6),"slippage_usd":round(slip,6),
       "commission_usd":round(fee,6),"net_pnl_usd":round(net,6)
    }

def simulate(df,year,opts,scenario,friction_mult=1.0):
    start,end,n_month=PERIODS[year]
    sub=df.loc[(df.index>=pd.Timestamp(start))&(df.index<pd.Timestamp(end))]
    if len(sub)<10000:raise ValueError("Insufficient source M15 complete price for "+year)
    cash=10000.0
    traces=[]
    tickets=[]
    current=None
    last_exit_bar=-999999
    daily=0.
    daily_cap=100.
    prevday=None
    last_time=None
    for i,(time,r) in enumerate(sub.iterrows()):
        date=r["ny_day"]
        if prevday!=date:
            daily=0.
            daily_cap=max(0.,cash*.01)
            prevday=date
        if current is not None:
            # Existing stop/target orders may be triggered by genuine M15 OHLC.
            p=current
            side=p["side"]
            spread=float(r["observed_max_spread"])
            open_bid=float(r["open"])
            open_ask=float(r["observed_open_ask"])
            # Short intrabar ask OHLC is NOT available; shift observed BID by
            # maximum in-bar spread to avoid falsely optimistic short fills.
            op=open_bid if side==1 else open_ask
            hi=float(r["high"]) if side==1 else float(r["high"])+spread
            lo=float(r["low"]) if side==1 else float(r["low"])+spread
            stop_hit=lo<=p["stop"] if side==1 else hi>=p["stop"]
            if stop_hit:
                exit_quote=min(op,p["stop"]) if side==1 else max(op,p["stop"])
                leg=_exit_leg(p,p["lots_left"],exit_quote,"ATR_STOP",time,friction_mult)
                p["legs"].append(leg)
                cash+=leg["net_pnl_usd"]
                daily+=leg["net_pnl_usd"]
                p["lots_left"]=0.
            elif side==1 and hi>=p["target"] or side==-1 and lo<=p["target"]:
                leg=_exit_leg(p,p["lots_left"],p["target"],"FULL_TARGET_2R",time,friction_mult)
                p["legs"].append(leg)
                cash+=leg["net_pnl_usd"]
                daily+=leg["net_pnl_usd"]
                p["lots_left"]=0.
            elif opts["partial_exit_enabled"] and not p["partial_done"]:
                hit=hi>=p["partial_target"] if side==1 else lo<=p["partial_target"]
                if hit:
                    close_lot=math.floor(p["lots_left"]*opts["partial_exit_fraction"]*100+1e-9)/100
                    # Actual minimum/step lot rule: do not create 0.00-lot partials.
                    if .01<=close_lot<=p["lots_left"]-.01:
                        leg=_exit_leg(p,close_lot,p["partial_target"],"PARTIAL_1P6R",time,friction_mult)
                        p["legs"].append(leg)
                        cash+=leg["net_pnl_usd"]
                        daily+=leg["net_pnl_usd"]
                        p["lots_left"]=round(p["lots_left"]-close_lot,2)
                        p["partial_done"]=True
            if p["lots_left"]<.009:
                pnl=sum(x["net_pnl_usd"] for x in p["legs"])
                tickets.append({
                    "year":year,"variant":scenario,"signal_time":p["signal_time"],
                    "entry_time":p["entry_time"],"exit_time":str(time)+"Z",
                    "side":"LONG" if side==1 else "SHORT",
                    "entry_quote":round(p["entry_quote"],5),
                    "entry_lot":p["lots_original"],
                    "atr_sl_dist":round(p["sl_dist"],5),
                    "stop_price":round(p["stop"],5),
                    "target_price":round(p["target"],5),
                    "partial_price":round(p["partial_target"],5),
                    "exit_reasons":"+".join(x["exit_reason"] for x in p["legs"]),
                    "net_pnl_usd":round(pnl,6),
                    "balance_usd":round(cash,6),
                    "fee_plus_slippage_usd":round(sum(x["commission_usd"]+x["slippage_usd"] for x in p["legs"]),6),
                    "partial_executed":p["partial_done"],
                    "price_legs":len(p["legs"]),
                })
                current=None
                last_exit_bar=i
        # Opening positions use completed prior candle only.
        # No new entry on the same bar an old trade exits.
        if current is None and (i-last_exit_bar)>opts["cooldown_bars"] and daily>-daily_cap and i>0 and last_exit_bar!=i:
            prev=sub.iloc[i-1]
            prev_ts=sub.index[i-1]
            if time-prev_ts==pd.Timedelta(minutes=15):
                direction=_signal(prev,opts)
                if direction:
                    sl_distance=float(prev["atr"])*2.
                    entry_quote=float(r["observed_open_ask"] if direction==1 else r["open"])
                    lot=_sizing(cash,sl_distance,entry_quote)
                    if lot>=.01:
                        current={
                            "side":direction,"entry_time":str(time)+"Z",
                            "signal_time":str(prev_ts+pd.Timedelta(minutes=15))+"Z",
                            "entry_quote":entry_quote,
                            "lots_original":lot,"lots_left":lot,
                            "sl_dist":sl_distance,
                            "stop":entry_quote-direction*sl_distance,
                            "target":entry_quote+direction*sl_distance*2,
                            "partial_target":entry_quote+direction*sl_distance*1.6,
                            "partial_done":False,"legs":[],
                        }
                        # Stop/targets are active from new bar but exact
                        # order of intrabar events on the entry M15 is unknown.
                        # Evaluate next complete candle; disclose entry-bar ambiguity.
        equity=cash
        if current is not None:
            mid=float(r["close"])
            if current["side"]==-1:mid+=float(r["observed_max_spread"])
            mark_qty=current["lots_left"]*100
            equity+=(mid-current["entry_quote"])*current["side"]*mark_qty
            equity-=2*DEFAULTS["slippage_per_side_per_oz_usd"]*friction_mult*mark_qty
            equity-=DEFAULTS["commission_round_trip_usd_per_standard_lot"]*current["lots_left"]
        traces.append((str(time+pd.Timedelta(minutes=15))+"Z",round(equity,4)))
        last_time=time
    if current is not None and last_time is not None:
        # Forced research-window close for independent period, not source signal.
        final=sub.iloc[-1]
        exit_quote=float(final["close"])
        if current["side"]==-1:exit_quote+=float(final["observed_max_spread"])
        leg=_exit_leg(current,current["lots_left"],exit_quote,"RESEARCH_PERIOD_END",last_time+pd.Timedelta(minutes=15),friction_mult)
        cash+=leg["net_pnl_usd"]
        current["legs"].append(leg)
        tickets.append({
            "year":year,"variant":scenario,"signal_time":current["signal_time"],
            "entry_time":current["entry_time"],
            "exit_time":str(last_time+pd.Timedelta(minutes=15))+"Z",
            "side":"LONG" if current["side"]==1 else "SHORT",
            "entry_quote":round(current["entry_quote"],5),
            "entry_lot":current["lots_original"],"atr_sl_dist":round(current["sl_dist"],5),
            "stop_price":round(current["stop"],5),
            "target_price":round(current["target"],5),
            "partial_price":round(current["partial_target"],5),
            "exit_reasons":"+".join(x["exit_reason"] for x in current["legs"]),
            "net_pnl_usd":round(sum(x["net_pnl_usd"] for x in current["legs"]),6),
            "balance_usd":round(cash,6),
            "fee_plus_slippage_usd":round(sum(x["commission_usd"]+x["slippage_usd"] for x in current["legs"]),6),
            "partial_executed":current["partial_done"],
            "price_legs":len(current["legs"])
        })
    wins=[x for x in tickets if x["net_pnl_usd"]>0]
    losses=[x for x in tickets if x["net_pnl_usd"]<0]
    gross_win=sum(x["net_pnl_usd"] for x in wins)
    gross_loss=-sum(x["net_pnl_usd"] for x in losses)
    profit_factor=gross_win/gross_loss if gross_loss>0 else None
    peak=10000.
    dd=0.
    for _,val in traces:
        peak=max(peak,val)
        dd=min(dd,100*(val/peak-1))
    months=[f"{year}-{n:02d}" for n in range(1,n_month+1)]
    monthly=[{
        "month":m,"trades":sum(x["entry_time"][:7]==m for x in tickets),
        "closed_tickets":sum(min(x["exit_time"][:7],months[-1])==m for x in tickets),
        "net_usd":round(sum(x["net_pnl_usd"] for x in tickets if min(x["exit_time"][:7],months[-1])==m),2),
    } for m in months]
    net=round(cash-10000,2)
    if sum(x["closed_tickets"] for x in monthly)!=len(tickets):
        raise ValueError("S003 full-year closed ticket count failed to reconcile")
    if abs(net-sum(m["net_usd"] for m in monthly))>.15:
        raise ValueError("S003 net monthly reconciliation failed")
    return {
       "period":year,"variant":scenario,"starting_usd":10000.,
       "ending_usd":round(cash,2),"net_usd":net,
       "return_pct":round(net/100,4),
       "trades":len(tickets),"wins":len(wins),"losses":len(losses),
       "win_rate_pct":round(100*len(wins)/len(tickets),3) if tickets else None,
       "profit_factor":round(profit_factor,4) if profit_factor is not None else None,
       "marked_drawdown_pct":round(dd,3),
       "total_assumed_commission_slip_usd":round(sum(x["fee_plus_slippage_usd"] for x in tickets),2),
       "partially_exited_tickets":sum(x["partial_executed"] for x in tickets),
       "months":monthly,"closed_tickets":tickets,
       "marked_equity":traces
    }

def write_csv(path,rows):
    if not rows:
        path.write_text("NO QUALIFIED OBSERVED TRADES\n",encoding="utf-8")
        return
    with path.open("w",newline="",encoding="utf-8") as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]))
        writer.writeheader();writer.writerows(rows)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--source-root",type=Path,required=True)
    ap.add_argument("--out",type=Path,default=OUT)
    a=ap.parse_args()
    raw,receipts,sha=read_source(a.source_root)
    indicators=compute_indicators(raw)
    if len(indicators)<38000 or len(receipts)!=22:
        raise ValueError("Source ZIP receipts incomplete")
    scenarios={
       "ACTUAL_PINE_MQL5_DEFAULTS":DEFAULTS,
       "README_0_TO_15_PRESET":README_PRESET,
       "NO_VOLUME_GATE_CONTROL":{**DEFAULTS,"volume_gate_enabled":False}
    }
    out={}
    for year in PERIODS:
        out[year]={}
        for name,opt in scenarios.items():
            c=simulate(indicators,year,opt,name)
            out[year][name]=c
            print("S003_ACTUAL_HISTORY",json.dumps({
                "year":year,"scenario":name,
                "trades":c["trades"],"wins":c["wins"],"losses":c["losses"],
                "net_usd":c["net_usd"],"end_usd":c["ending_usd"],
                "pf":c["profit_factor"],"dd_pct":c["marked_drawdown_pct"]
            },sort_keys=True),flush=True)
    primary=[out[y]["ACTUAL_PINE_MQL5_DEFAULTS"] for y in PERIODS]
    packet={
        "id":"S003","title":"Breakout Follow Trend 101",
        "source":SOURCE,"source_confirmed":True,
        "source_rules_tested":DEFAULTS,
        "readme_preset_rules_tested_separately":README_PRESET,
        "readme_preset_is_not_actual_code_defaults":True,
        "raw_source_months":len(receipts),
        "raw_source_market_sha256":sha,
        "source_original_m15_receipts":receipts,
        "history":"2025 FULL + JAN-SEP 2026, reset separate $10000 each",
        "source_histdata_bid_ask":True,
        "source_histdata_tick_counts_used_for_volume":True,
        "source_native_pepperstone_mt5_tick_volume_verified":False,
        "publisher_pine_mql5_parity_independently_proven":False,
        "broker_actual_execution_and_financing_verified":False,
        "short_ask_intrabar_synthesised_from_bid_plus_source_max_spread":True,
        "entry_bar_exit_intrabar_ambiguity":True,
        "strictly_sealed_untouched_out_of_sample":False,
        "model_result_invalid_for_marketing_as_author_live_profit":True,
        "owner_live_paper_approval":False,
        "unqualified_original_portability":True,
        "initial_model_economic_screen_both_profitable":all(x["net_usd"]>0 for x in primary),
        "initial_research_decision":(
            "PROMISING_MODEL_NEEDS_BROKER_VOLUME_EXECUTION_PARITY_AND_OOS"
            if all(x["net_usd"]>0 and (x["profit_factor"] or 0)>1.1 for x in primary)
            else "FAILED_OR_INCONCLUSIVE_TWO_PERIOD_SOURCE_DEFAULT_ECONOMICS"
        ),
        "independent_results":out,
        "caveats":[
            "The actual published Pine DEFAULT session is 12-18 America/New_York, cooldown=6; MQL5 default is broker 19-01, cooldown=6. README suggested preset 00-15 / cooldown 3 is NOT actual source default; separate predeclared comparison, not silent optimization.",
            "Real HistData original tick archive is authentic, but native broker MT5/Pepperstone tick-volume and TV data feed are unavailable. Historical source tick counts drive volume filter; original cross-platform 100% parity is unverified.",
            "Short-exit historical ASK H/L are not in derived M15 receipt, estimated as historical BID OHLC + original highest recorded in-bar spread, which is an explicit uncertainty.",
            "The source Pine/MQL5 has 1% initial ATR-based stop risk, 2R TP, partial 50% at 1.6R, 6 bar cooldown and 1% realized daily loss lock, and no weekend forced exit by default.",
            "Risk uses current model equity, 0.01 lot step, 100 gold ounces/lot, explicit AIDY 10x notional cap, source entry BID/ASK, $0.10/oz per-side slippage and $7/lot round trip fee. Source-native broker margin, swap and liquidation are unverified.",
            "Within entry M15, original source has stop/TP live from entry but independent bid/ask OHLC cannot prove intrabar ordering. AIDY starts stop and TP testing next bar, disclosed entry-bar ambiguity. On dual-touch later candle AIDY uses stop first.",
            "Partial exit is quantized to broker-style 0.01 lot. When remaining lot cannot split at least 0.01/0.01, partial is skipped. Costs are allocated to each closed leg without double-counting.",
            "2025 and Jan-Sep2026 sources have been inspected; 2026 is not a hermetically sealed holdout. Do NOT mark GREEN or create a demo/live account based on source-derived model.",
        ]
    }
    packet["sha256"]=hashlib.sha256(json.dumps(packet,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()
    a.out.mkdir(parents=True,exist_ok=True)
    (a.out/"S003_INITIAL_SCREEN.json").write_text(json.dumps(packet,indent=2,sort_keys=True,allow_nan=False)+"\n",encoding="utf-8")
    for year,cases in out.items():
        for name,c in cases.items():
            write_csv(a.out/(year+"_"+name+"_closed_tickets.csv"),c["closed_tickets"])
            write_csv(a.out/(year+"_"+name+"_monthly.csv"),c["months"])
    lines=[
        "# S003 Breakout Follow Trend 101 | AIDY original-source screening",
        "Actual source-code defaults (12–18 NY / cooldown 6) and README preset (00–15 NY / cooldown 3) are NOT identical.",
        "Neither real broker/Pepperstone tick volume nor source MQL5/Pine broker-parity is proven.",
        "| Year | Preset | Trades | Win % | Net model USD | Return % | End USD | PF | Max marked DD % |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|"
    ]
    for year,cases in out.items():
        for name,c in cases.items():
            lines.append(f"| {year} | {name} | {c['trades']} | {c['win_rate_pct']} | {c['net_usd']} | {c['return_pct']} | {c['ending_usd']} | {c['profit_factor']} | {c['marked_drawdown_pct']} |")
    lines.extend(["","## Gate",packet["initial_research_decision"],"","Evidence SHA256: "+packet["sha256"],
       "No full PDF for failed screen. Complete receipts, every trade and month: compact JSON/CSV artifact."])
    (a.out/"S003_INITIAL_SCREEN_SUMMARY.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    print("S003_TWO_PERIOD_RESULT",json.dumps({
        "decision":packet["initial_research_decision"],
        "market_sha256":sha,"source_months":len(receipts),
        "checksum":packet["sha256"],
        "primary":{year:{k:out[year]["ACTUAL_PINE_MQL5_DEFAULTS"][k] for k in
            ("trades","wins","losses","net_usd","ending_usd","profit_factor",
             "marked_drawdown_pct")} for year in out}
    },sort_keys=True),flush=True)

if __name__=="__main__":
    main()
