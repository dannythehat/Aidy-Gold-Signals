"""S005-C research: ONE $10k account model, TWO isolated $5k signal sleeves.

Original Donchian and original Session author Python engines execute unchanged
with exactly $5000 starting per sleeve, 1% nominal sleeve risk at each entry.
Combined account is SUM of the contemporaneous marked-to-market sleeve equities
on one original-source H1 time grid. 2x $10k runs or sum of 2x $10k accounts
IS PROHIBITED.

Four frozen experiments each period:
  DON_ONLY: $5k Donchian / $5k idle.
  SESSION_ONLY: $5k session / $5k idle.
  S005_C_PARALLEL: $5k each original unfiltered source rules.
  S005_D_EMA_CONFIRM: $5k original Donchian and $5k Session, with
    Session entry allowed only in direction of a causally CLOSED bar's EMA200.
The D hybrid is retrospective exploratory and NOT a virgin holdout; no
parameter optimisations, no selection by performance or future candles.
Original source Python simplified $0.45/oz RT and 20x sleeve leverage,
NOT actual bid/ask or a compiled MetaTrader Strategy Tester deal ledger.
C/D require a HEDGING-capable broker if overlapping opposite gold positions;
using two accounting sleeves on one virtual account does not magically enable
hedging on netting MT5 accounts.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.strategy_lab.s005_publisher_engine_two_preset_parity import (
    PUB_COMMIT, PERIODS, original_modules, source_h1,
)

ACCOUNT=10000.
SLEEVE=5000.
SOURCE_RISK_PCT=1.0
COST_PER_OUNCE=.45
LEVERAGE_CAP=20.
MODE_NAMES=("DON_ONLY","SESSION_ONLY","S005_C_PARALLEL","S005_D_EMA_CONFIRM")

def digest(obj):
    return hashlib.sha256(json.dumps(obj,sort_keys=True,
               separators=(",",":"),allow_nan=False).encode()).hexdigest()

def closed_signal_ema_mask(close,span=200):
    """Decide once at completed H1 bar, never using a future close."""
    s=pd.Series(close,dtype=float)
    avg=s.ewm(span=span,adjust=False).mean().to_numpy()
    return close>avg,close<avg

def gate_session_signals(original_signals,close):
    long_allowed,short_allowed=closed_signal_ema_mask(close)
    long_s,short_s,exit_l,exit_s=original_signals
    gate_long=np.asarray(long_s,dtype=bool)&long_allowed
    gate_short=np.asarray(short_s,dtype=bool)&short_allowed
    return (gate_long,gate_short,np.array(exit_l,copy=True),np.array(exit_s,copy=True)),{
        "original_source_long_signals":int(np.sum(long_s)),
        "original_source_short_signals":int(np.sum(short_s)),
        "source_long_signals_blocked":int(np.sum(long_s&~long_allowed)),
        "source_short_signals_blocked":int(np.sum(short_s&~short_allowed)),
        "selected_long_signals":int(np.sum(gate_long)),
        "selected_short_signals":int(np.sum(gate_short)),
        "exits_unchanged":bool(np.array_equal(exit_l,original_signals[2])
                                and np.array_equal(exit_s,original_signals[3])),
        "same_bar_close_EMA200_only":True,
    }

def merge_portfolio(result_d,result_s,lo,hi,h1_closes,case_name,year):
    """One 10k master, two separate original 5k sleeve MTM states."""
    d=(np.asarray(result_d.equity[lo:hi],float) if result_d is not None
       else np.full(hi-lo,SLEEVE))
    s=(np.asarray(result_s.equity[lo:hi],float) if result_s is not None
       else np.full(hi-lo,SLEEVE))
    if not len(d) or not len(s):
        raise ValueError("Empty trading year in shared $10k model")
    if not np.isfinite(d).all() or not np.isfinite(s).all():
        raise ValueError("Missing original trade equity time state")
    combined=d+s
    if abs((d[0]+s[0])-ACCOUNT)>1000:
        # original first historical bar might carry an open P&L if first
        # entry at first bar: not an independent funding event.
        raise ValueError("First combined portfolio mark too far from 10k")
    peak=np.maximum.accumulate(np.r_[ACCOUNT,combined])
    dd=(peak[1:]-combined)/peak[1:]
    monthly=defaultdict(lambda:{"DONCHIAN":0.0,"SESSION":0.0})
    merged_trades=[]
    for tag,res in (("DONCHIAN",result_d),("SESSION",result_s)):
        if res is None:continue
        for k,t in enumerate(res.trades):
            if not (lo<=t.entry_i<hi and lo<=t.exit_i<hi):
                raise ValueError("Source original trade escaped $5k sleeve period")
            ts=pd.Timestamp(h1_closes.index[t.exit_i])
            month=ts.strftime("%Y-%m")
            if not month.startswith(year):
                raise ValueError("Out-of-calendar trade end")
            monthly[month][tag]+=float(t.pnl)
            merged_trades.append({
                "source_strategy":tag,
                "source_trade_no":k,
                "entry_utc":str(pd.Timestamp(h1_closes.index[t.entry_i]))+"Z",
                "exit_utc":str(ts)+"Z",
                "direction":"BUY" if t.dir>0 else "SELL",
                "entry_bid_proxy":float(t.entry_px),
                "exit_bid_proxy":float(t.exit_px),
                "original_author_python_units_oz":float(t.units),
                "author_source_PY_model_net_usd":float(t.pnl),
                "original_source_exit_reason":t.reason,
                "source_entry_i":int(t.entry_i),
                "source_exit_i":int(t.exit_i),
                "source_publisher_python_only":True,
            })
    merged_trades.sort(key=lambda x:(x["exit_utc"],x["source_strategy"],x["source_trade_no"]))
    realized=float(sum(x["author_source_PY_model_net_usd"] for x in merged_trades))
    if abs(combined[-1]-(ACCOUNT+realized))>.05:
        raise ValueError("Source master $10k cash/equity does not reconcile to sleeves + closed trade PnL")
    # Track side-by-side concurrent exposure on each original bar, including
    # opposing positions for the hedging/netting feasibility disclosure.
    inventory=np.zeros((2,hi-lo),dtype=np.float64)
    gross_notional=np.zeros(hi-lo,dtype=float)
    for j,res in enumerate((result_d,result_s)):
        if res is None:continue
        for t in res.trades:
            loc0=t.entry_i-lo
            loc1=t.exit_i-lo
            inventory[j,loc0:loc1+1]+=t.dir
            gross_notional[loc0:loc1+1]+=float(t.units)*h1_closes["close"].iloc[t.entry_i:t.exit_i+1].to_numpy()
    both=(inventory[0]!=0)&(inventory[1]!=0)
    opposite=both&(inventory[0]*inventory[1]<0)
    double=(inventory[0]*inventory[1]>0)
    # MAX gross notional / master same-H1 mark, meaningful contingent
    # margin exposure rather than 2 independent full $10k leverage caps.
    leverage_ratio=np.divide(gross_notional,combined,
                             out=np.full_like(combined,np.inf),
                             where=combined>0)
    max_ratio=float(np.max(leverage_ratio))
    margin_20x_exceed=int(np.sum(leverage_ratio>LEVERAGE_CAP+1e-8))
    return {
      "name":case_name,"year":year,
      "master_initial_cash_usd":ACCOUNT,
      "donchian_allocated_initial_usd":SLEEVE,
      "session_allocated_initial_usd":SLEEVE,
      "master_ending_marked_equity_PY_model_usd":round(float(combined[-1]),2),
      "master_realized_PY_model_net_usd":round(realized,2),
      "donchian_source_net_usd":round(float(np.sum([t.pnl for t in result_d.trades])) if result_d else 0,2),
      "session_source_net_usd":round(float(np.sum([t.pnl for t in result_s.trades])) if result_s else 0,2),
      "total_trades":len(merged_trades),
      "donchian_trades":len(result_d.trades) if result_d else 0,
      "session_trades":len(result_s.trades) if result_s else 0,
      "max_combined_mark_to_market_drawdown_pct":round(float(np.max(dd)*100),4),
      "concurrent_source_H1_bars":int(np.sum(both)),
      "opposing_gold_positions_H1_bars":int(np.sum(opposite)),
      "same_direction_gold_positions_H1_bars":int(np.sum(double)),
      "requires_hedging_ability_if_opposite_exposure":bool(np.any(opposite)),
      "max_gross_original_model_notional_over_combined_equity":round(max_ratio,5),
      "H1_bars_above_shared_20x_gross_margin_notional":margin_20x_exceed,
      "native_account_margin_stopouts_applied":False,
      "source_python_original_20x_sleeve_individual_cap_applied":True,
      "monthly_realized_usd":[{
        "month":f"{year}-{month:02d}",
        "donchian_usd":round(monthly[f"{year}-{month:02d}"]["DONCHIAN"],2),
        "session_usd":round(monthly[f"{year}-{month:02d}"]["SESSION"],2),
        "total_usd":round(sum(monthly[f"{year}-{month:02d}"].values()),2)
      } for month in range(1,13 if year=="2025" else 10)],
      "merged_source_trade_ledger":merged_trades,
      "mtm_equity_points_raw_original_h1":int(len(combined)),
      "independent_blind_holdout":False,
      "native_original_EA_combined_account_parity":False,
    }

def _result(engine,signals,params,arrays,spec,lo,hi):
    return engine.simulate(*arrays, *signals,spec,params,lo,hi)

def run(input_source,publisher_root,output):
    engine,strategies=original_modules(publisher_root)
    h1,receipts,source_sha,h1sha,times,hours,weekdays=source_h1(input_source)
    o,h,l,c=[h1[x].to_numpy(float) for x in ("open","high","low","close")]
    atr=engine.atr(h,l,c,14)
    donchian_signals=strategies.donchian(o,h,l,c,hours,entry_n=24,exit_n=12,ema_filter=200)
    session_signals=strategies.session_breakout(o,h,l,c,hours,
       range_start=0,range_end=6,trade_end=12,close_hour=21,
       buffer_frac=0.,atr_arr=atr,dows=weekdays)
    hybrid_signals,filter_count=gate_session_signals(session_signals,c)
    params={
       "DONCHIAN":engine.EngineParams(sl_atr=2.5,tp_atr=0.,trail_atr=0.,
                          allow_reverse=True,risk_pct=SOURCE_RISK_PCT,
                          start_equity=SLEEVE),
       "SESSION":engine.EngineParams(sl_atr=3.,tp_atr=0.,trail_atr=0.,
                          allow_reverse=False,risk_pct=SOURCE_RISK_PCT,
                          start_equity=SLEEVE),
    }
    spec=engine.SymbolSpec("XAUUSD",cost=COST_PER_OUNCE,max_leverage=LEVERAGE_CAP)
    price=(o,h,l,c,times,atr)
    portfolio={}
    output.mkdir(parents=True,exist_ok=True)
    for year,(start,end,nmon) in PERIODS.items():
        lo=int(h1.index.searchsorted(pd.Timestamp(start)))
        hi=int(h1.index.searchsorted(pd.Timestamp(end)))
        don=_result(engine,donchian_signals,params["DONCHIAN"],price,spec,lo,hi)
        sess=_result(engine,session_signals,params["SESSION"],price,spec,lo,hi)
        hybrid=_result(engine,hybrid_signals,params["SESSION"],price,spec,lo,hi)
        # Exact C sleeve return attribution = genuine original engine
        # $5k, NOT original preexisting $10k run divided by assumption.
        cases={
           "DON_ONLY":merge_portfolio(don,None,lo,hi,h1,"DON_ONLY",year),
           "SESSION_ONLY":merge_portfolio(None,sess,lo,hi,h1,"SESSION_ONLY",year),
           "S005_C_PARALLEL":merge_portfolio(don,sess,lo,hi,h1,"S005_C_PARALLEL",year),
           "S005_D_EMA_CONFIRM":merge_portfolio(don,hybrid,lo,hi,h1,"S005_D_EMA_CONFIRM",year)
        }
        for mode,v in cases.items():
            if len(v["monthly_realized_usd"])!=nmon:raise ValueError("Month coverage missing")
            if abs(sum(m["total_usd"] for m in v["monthly_realized_usd"])-v["master_realized_PY_model_net_usd"])>.08:
                raise ValueError("Monthly+portfolio PnL source conflict")
            v["source_frozen_sleeve_risk_pct_each"]=SOURCE_RISK_PCT
            v["initial_risk_pct_of_FULL_10k_PER_position"]=.5
            v["maximum_two_initial_sleeve_risks_pct_of_10k"]=1.0
            v["publisher_python_original_cost_per_oz_rt"]=COST_PER_OUNCE
            v["frozen_combo_spec"]={
                "one_master_usd":10000,"donchian_sleeve_usd":5000,
                "session_sleeve_usd":5000,"cross_sleeve_capital_transfer":False,
                "external_deposits":0,"reinvest_both_as_separate_5000_sleeves":True,
                "hedging_feasibility_must_be_verified":True,
            }
            full=output/f"{mode}_{year}_SOURCE_PY_ORIGINAL_2X5000_TRADES.csv"
            with full.open("w",newline="",encoding="utf-8") as file:
                rows=v["merged_source_trade_ledger"]
                if not rows:continue
                wr=csv.DictWriter(file,fieldnames=list(rows[0]))
                wr.writeheader();wr.writerows(rows)
            print("S005_C_SINGLE_10K_TWO_5K_COMBINED_RESULT",json.dumps({
                 "year":year,"mode":mode,"net":v["master_realized_PY_model_net_usd"],
                 "ending":v["master_ending_marked_equity_PY_model_usd"],
                 "dd_pct":v["max_combined_mark_to_market_drawdown_pct"],
                 "trades":v["total_trades"],
                 "opposite_H1":v["opposing_gold_positions_H1_bars"],
                 "gross_ratio":v["max_gross_original_model_notional_over_combined_equity"]},sort_keys=True),flush=True)
        portfolio[year]=cases
    original_source_sig_digest=digest({
       "donchian":{f"{i}":np.flatnonzero(np.asarray(a,dtype=bool)).tolist()
                   for i,a in enumerate(donchian_signals)},
       "session":{f"{i}":np.flatnonzero(np.asarray(a,dtype=bool)).tolist()
                   for i,a in enumerate(session_signals)}})
    record={
      "schema":"aidy.s005_unified_parallel_and_hybrid_2x5000_original_gold_source.v1",
      "publisher_source_commit":PUB_COMMIT,
      "authentic_HistData_22_original_months":len(receipts),
      "original_source_H1_digest":h1sha,
      "original_source_m15_archive_digest":source_sha,
      "original_source_rule_boolean_digest":original_source_sig_digest,
      "original_publisher_python_engine_actually_called":True,
      "account_total_usd":ACCOUNT,
      "donchian_capital_usd":SLEEVE,
      "session_capital_usd":SLEEVE,
      "sum_allocations_equal_one_account":ACCOUNT==SLEEVE*2,
      "true_original_source_signal_rules_unchanged_in_C":True,
      "D_ema_session_gate_retrospective_exploratory_not_OOS":True,
      "D_session_gating_method":"Only keep author-original session BUY if signal-bar CLOSED close>EMA200, SELL if close<EMA200. Both filters causal, original Don unchanged, source session exits unchanged. Owner did not pre-register before source historical outcome review.",
      "D_total_original_source_signal_reduction":filter_count,
      "cost_model_note":"Unmodified publisher-PY float-ounce fills, simplified $0.45/oz all-in roundtrip, 20x each sleeve not actual broker quote-side MT5; actual source BIDASK alternative stress from original S005 quote cost audit is NOT automatically substitutable for hybrid.",
      "MT5_netted_one_account_gross_order_parity":False,
      "exact_original_bidask_quote_level_fill_parity":False,
      "one_combined_broker_account_with_independently_risk_limited_5k_sleeves":True,
      "read_only_no_broker_orders":True,
      "2025_and_2026_both_known_dev_not_blind_holdout":True,
      "study_periods":{"2025":"2025-01-01 to 2025-12-31","2026":"2026-01-01 to 2026-09-30"},
      "two_period_results":portfolio
    }
    record["sha256"]=digest(record)
    (output/"S005_UNIFIED_2X5000_MASTER_PORTFOLIO.json").write_text(
        json.dumps(record,sort_keys=True,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    with (output/"S005_UNIFIED_2X5000_RESULTS.csv").open("w",newline="") as file:
        rows=[{
          "period":year,"variant":mode,"total_start_usd":v["master_initial_cash_usd"],
          "don_sleeve_start_usd":v["donchian_allocated_initial_usd"],
          "session_sleeve_start_usd":v["session_allocated_initial_usd"],
          "net_py_model_usd":v["master_realized_PY_model_net_usd"],
          "end_py_marked_model_usd":v["master_ending_marked_equity_PY_model_usd"],
          "portfolio_max_marked_dd_pct":v["max_combined_mark_to_market_drawdown_pct"],
          "trades_total":v["total_trades"],"don_trades":v["donchian_trades"],
          "session_trades":v["session_trades"],
          "opposite_hedge_H1_bars":v["opposing_gold_positions_H1_bars"],
          "max_gross_leverage":v["max_gross_original_model_notional_over_combined_equity"],
          "gross_20x_overage_H1_bars":v["H1_bars_above_shared_20x_gross_margin_notional"],
          "source_python_not_live_native_MT5":True
        } for year,modes in record["two_period_results"].items() for mode,v in modes.items()]
        wr=csv.DictWriter(file,fieldnames=list(rows[0]));wr.writeheader();wr.writerows(rows)
    text=["# S005-C unified Gold Breakout | ONE master $10,000, two $5,000 sleeves",
      "**Model:** unmodified author Python strategy rules (except explicitly NEW D session EMA200 filter), source HISTDATA original source H1 gold, original publisher historical $0.45/oz friction. Native MT5 and source true BID/ASK combined broker execution NOT proven.",
      "",
      "| Period | Variant | Total start | Don sleeve | Session sleeve | Combined model net | Ending model $ | Max MTM DD % | Trades | Opposing positions H1 bars | Gross 20x overages |",
      "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for x in rows:
        text.append(f"| {x['period']} | {x['variant']} | 10000 | 5000 | 5000 | {x['net_py_model_usd']:+.2f} | {x['end_py_marked_model_usd']:.2f} | {x['portfolio_max_marked_dd_pct']:.2f} | {x['trades_total']} | {x['opposite_hedge_H1_bars']} | {x['gross_20x_overage_H1_bars']} |")
    text.extend(["","**D is explicitly a NEW source-derived hypothesis**, not a publisher preset and not an AIDY machine-trained selected rule. The historical source bands have been viewed repeatedly so superior D results would be in-sample and cannot be promoted without truly new data.",
      "**C is a capital-allocation portfolio, not literally one BUY/SELL EA with a broker-netted position.** Opposing positions require hedging-capable accounts and the broker may reject due its own gross exposure, contract sizes and stop/fill rules. Each 5k sleeve sets own nominal 1% sizing and cap at author-20x, while the master must enforce a separate shared portfolio margin cap in future broker-native testing.",
      "Combining two separate original historical $10,000 outputs would DOUBLE-COUNT capital. This script genuinely reruns both author engines at $5,000 each and proves master cash/equity math. No promised returns or paper/live admission.",
      "Source verifier SHA: "+record["sha256"]])
    (output/"S005_UNIFIED_2X5000_OWNER_SUMMARY.md").write_text("\n".join(text)+"\n",encoding="utf-8")
    return record


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--source-root",type=Path,required=True)
    p.add_argument("--publisher-root",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    args=p.parse_args()
    run(args.source_root,args.publisher_root,args.out)


if __name__=="__main__":main()
