"""S006 exact author EMA fast/slow signal with optional ADX filter, XAUUSD H1.

Runs PINNED ORIGINAL publisher Python functions (not guessed MQL5):
- source repository source commit 3dab20e20a846edae9ac6fcf56d6b090dbba9f98
- original engine, strategies and original grid search freeze by git blob SHA
- 9/120 ADX0 published leaderboard best EMA research benchmark
- same source-defined engine 9/120 ADX20 and ADX25 added as explicitly
  registered, finite publisher-grid ADX-filter variants
- source engine params SL2 ATR, trailing3.5 ATR, no TP, 1% equity
- historical original source 22 actual HistData raw BID/ASK monthly receipts
  and fully completed source H1 bars, warmup Dec2024.
No original MQL5 EA strategy mode exists for EMA/ADX; MT5 native
compiled/filled equivalence MUST be declared FALSE.
Never select by the new 2025 / 2026 outcomes.
Historical years are already known and cannot be called untouched OOS.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.strategy_lab.s005_publisher_engine_two_preset_parity import (
    source_h1,
)

AUTHOR="3dab20e20a846edae9ac6fcf56d6b090dbba9f98"
BLOBS={
  "engine.py":"41f1b5740314487ed6ea35b3307daf689d8abb6f",
  "strategies.py":"9abe69680df34064923e01236cbf9b77d486c682",
  "optimize.py":"41dd3dc2ca42c4ba5ec58727ddf4676e68144b96",
  "grid_all.csv":"651ecbaf2a4bf0288c37ec3216192c8d90a5f8b1",
  "ApexBreakout.mq5":"db9ee1d2589cd1625c2d9f5b224ea4f1fad14442",
}
PERIODS={"2025":("2025-01-01","2026-01-01",12),
         "2026":("2026-01-01","2026-10-01",9)}
VARIANTS={
  "EMA_9_120_ADX_0_SOURCE_LEADERBOARD":dict(fast=9,slow=120,adx_min=0),
  "EMA_9_120_ADX_20_SOURCE_GRID":dict(fast=9,slow=120,adx_min=20),
  "EMA_9_120_ADX_25_SOURCE_GRID":dict(fast=9,slow=120,adx_min=25),
}
ENGINE=dict(sl_atr=2.,tp_atr=0.,trail_atr=3.5,
            allow_reverse=True,risk_pct=1.,start_equity=10000.)
BASIS_COST=.45
WARM_BARS=250


def gitblob(b:bytes)->str:
    return hashlib.sha1(b"blob "+str(len(b)).encode()+b"\0"+b).hexdigest()


def publisher(root:Path):
    for name,sha in BLOBS.items():
        if gitblob((root/name).read_bytes())!=sha:
            raise ValueError("Original author upstream blob SHA not qualified "+name)
    sys.path.insert(0,str(root))
    import engine
    import strategies
    return engine,strategies


def original_publisher_grid(root):
    """Require ALL tested configurations to appear in pinned author's grid."""
    original=pd.read_csv(root/"grid_all.csv")
    x=original[(original.strategy=="ema_trend")&(original.symbol=="XAUUSD")]
    if not len(x):raise ValueError("No author grid source EMA XAUUSD candidates")
    preselected={}
    for name,p in VARIANTS.items():
        matched=x[(x.p_fast==p["fast"])&(x.p_slow==p["slow"])&
                  (x.p_adx_min==p["adx_min"])&
                  (x.e_sl_atr==2.)&(x.e_tp_atr==0.)&
                  (x.e_trail_atr==3.5)]
        if len(matched)!=1:
            raise ValueError("Selected EMA ADX original gold grid combo not uniquely published "+name)
        row=matched.iloc[0]
        preselected[name]={
            "original_author_grid_original_is_ret_pct":float(row.is_ret),
            "original_author_grid_original_oos_ret_pct":float(row.oos_ret),
            "original_author_grid_original_is_trades":int(row.is_trades),
            "original_author_grid_original_oos_trades":int(row.oos_trades),
            "publisher_previous_70_30_split_is_not_a_sealed_S006_holdout":True,
        }
    ranked=pd.read_csv(root/"grid_all.csv")
    published=ranked[(ranked.strategy=="ema_trend")&
                     (ranked.symbol=="XAUUSD")&
                     (ranked.p_fast==9)&(ranked.p_slow==120)&
                     (ranked.p_adx_min==0)&(ranked.e_sl_atr==2.)&
                     (ranked.e_tp_atr==0.)&(ranked.e_trail_atr==3.5)]
    if len(published)!=1:raise ValueError("Original publisher's no-ADX baseline missing")
    return preselected


def signal_independent(c,h,l,fast,slow,adx_n,adx_min):
    # independent pandas EMA crossover geometry; using original ADX with
    # direct equality check only (original indicator implementation frozen).
    f=pd.Series(c).ewm(span=fast,adjust=False).mean().to_numpy()
    s=pd.Series(c).ewm(span=slow,adjust=False).mean().to_numpy()
    ls=(f>s)&(np.roll(f,1)<=np.roll(s,1))
    ss=(f<s)&(np.roll(f,1)>=np.roll(s,1))
    if adx_min>0:
        from strategies import adx
        a=adx(h,l,c,adx_n)
        ls&=a>=adx_min
        ss&=a>=adx_min
    return ls,ss


def emit_csv(path,records):
    if not records:
        path.write_text("NO ORIGINAL SOURCE EXECUTED TRADES\n",encoding="utf-8")
        return
    with path.open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=list(records[0]))
        w.writeheader();w.writerows(records)


def run(root,market_root,out):
    eng,strategies=publisher(root)
    author_grid=original_publisher_grid(root)
    h,receipts,marketsha,hsha,times,hours,_=source_h1(market_root)
    if len(receipts)!=22 or len(h)!=10725:
        raise ValueError("Original complete HISTDATA 22 month/H1 receipt population differs from S005")
    o,hi,lo,c=(h[k].to_numpy(float) for k in ("open","high","low","close"))
    atr=eng.atr(hi,lo,c,14)
    idx=h.index
    payload={}
    for variant,params in VARIANTS.items():
        flags=strategies.ema_trend(o,hi,lo,c,hours,**params)
        indlong,indshort=signal_independent(c,hi,lo,params["fast"],params["slow"],14,params["adx_min"])
        sig_parity={
          "all_original_H1_long_signals_identical":bool(np.array_equal(flags[0],indlong)),
          "all_original_H1_short_signals_identical":bool(np.array_equal(flags[1],indshort)),
          "no_explicit_strategy_exit_flags":bool(not flags[2].any() and not flags[3].any()),
          "original_long_crossovers":int(flags[0].sum()),
          "original_short_crossovers":int(flags[1].sum()),
        }
        if not all(sig_parity[k] for k in ("all_original_H1_long_signals_identical",
               "all_original_H1_short_signals_identical","no_explicit_strategy_exit_flags")):
            raise ValueError("Author EMA/ADX signal independent verification mismatch")
        output={"strategy":"ema_trend","params":params,
                "engine_params_source_frozen":ENGINE,
                "source_author_original_grid":author_grid[variant],
                "real_original_complete_H1_signal_parity":sig_parity,
                "periods":{}}
        for year,(start,end,months) in PERIODS.items():
            a=int(idx.searchsorted(pd.Timestamp(start)))
            b=int(idx.searchsorted(pd.Timestamp(end)))
            if a<WARM_BARS:raise ValueError("History inadequate to warm original author EMA")
            model=eng.simulate(o,hi,lo,c,times,atr,*flags,
                eng.SymbolSpec("XAUUSD",cost=BASIS_COST,max_leverage=20.),
                eng.EngineParams(**ENGINE),a,b)
            trades=[]
            for t in model.trades:
                trades.append({
                    "direction":"LONG" if t.dir==1 else "SHORT",
                    "entry_time_utc":str(idx[t.entry_i])+"Z",
                    "exit_time_utc":str(idx[t.exit_i])+"Z",
                    "entry_price_publisher_bid_proxy":round(float(t.entry_px),5),
                    "exit_price_publisher_bid_proxy":round(float(t.exit_px),5),
                    "units_float_not_broker_lots":round(float(t.units),8),
                    "publisher_costed_usd":round(float(t.pnl),6),
                    "reason":t.reason,
                    "observed_real_source_H1_initial_spread":round(float(h.iloc[t.entry_i].source_open_spread),6),
                    "observed_real_source_H1_open_ask":round(float(h.iloc[t.entry_i].open_ask),6),
                    "H1_source_signal_developed_only_from_completed_bars":True
                })
            total=round(sum(t["publisher_costed_usd"] for t in trades),2)
            if abs(total-model.net_return*100)>.20:
                raise ValueError("Published original simulator accounting inconsistent")
            nums=[r["publisher_costed_usd"] for r in trades]
            profits=sum(x for x in nums if x>0)
            losses=-sum(x for x in nums if x<0)
            monthrows=[]
            for m in range(1,months+1):
                mn=f"{year}-{m:02d}"
                members=[x for x in trades if x["exit_time_utc"].startswith(mn)]
                monthrows.append({"month":mn,"trades":len(members),
                     "net_usd":round(sum(t["publisher_costed_usd"] for t in members),2)})
            overflow=[x for x in trades if not x["exit_time_utc"].startswith(year)]
            if overflow and any(t["reason"]!="eod" for t in overflow):
                raise ValueError("Original source positions escaped from reset research period")
            if overflow:
                monthrows[-1]["trades"]+=len(overflow)
                monthrows[-1]["net_usd"]=round(monthrows[-1]["net_usd"]+sum(t["publisher_costed_usd"] for t in overflow),2)
            if sum(x["trades"] for x in monthrows)!=len(trades) or abs(sum(x["net_usd"] for x in monthrows)-total)>.20:
                raise ValueError("S006 original author monthly realised ledger mismatch")
            observe_spreads=[t["observed_real_source_H1_initial_spread"] for t in trades]
            base=round(sum(t["units_float_not_broker_lots"] for t in trades),4)
            case={
               "period":year,"initial_usd":10000.,"net_usd":total,
               "ending_usd":round(10000+total,2),
               "original_python_publisher_trades":len(trades),
               "wins":sum(x>0 for x in nums),"losses":sum(x<0 for x in nums),
               "profit_factor":round(profits/losses,4) if losses else None,
               "original_author_max_drawdown_pct":round(float(-model.max_dd),4),
               "publisher_original_engine_cagr_pct":round(float(model.cagr),4),
               "author_original_engine_sharpe":round(float(model.sharpe),4),
               "source_original_all_in_cost_usd_per_oz":BASIS_COST,
               "source_observed_entry_spread_median_per_oz":round(float(np.median(observe_spreads)),4) if observe_spreads else None,
               "source_real_entry_spreads_strictly_gt_original_all_in_cost":sum(t["observed_real_source_H1_initial_spread"]>BASIS_COST+5e-7 for t in trades),
               "total_original_float_exposure_oz":base,
               "fixed_original_trade_cohort_not_executable_cost_stress":{
                  "0.45":total,
                  "0.75":round(total-(.75-BASIS_COST)*base,2),
                  "1.00":round(total-(1.-BASIS_COST)*base,2),
                  "1.50":round(total-(1.5-BASIS_COST)*base,2),
                  "2.00":round(total-(2.-BASIS_COST)*base,2)
               },
               "true_original_executed_source_Python_engine":True,
               "native_published_MQL5_EA_mode_available":False,
               "native_broker_ASK_stop_and_swap_parity_proven":False,
               "independent_untouched_holdout_proven":False,
               "positive_calendar_months":sum(x["net_usd"]>0 for x in monthrows),
               "months":monthrows if False else monthrows,
               "trade_ledger":trades
            }
            output["periods"][year]=case
            emit_csv(out/f"S006_{variant}_{year}_ORIGINAL_PY.csv",trades)
            emit_csv(out/f"S006_{variant}_{year}_MONTHS.csv",monthrows if False else monthrows)
            print("S006_ORIGINAL_AUTHOR_PYTHON_SPOT",json.dumps({
                "variant":variant,"year":year,"trades":len(trades),
                "net_usd":total,"PF":case["profit_factor"],
                "DD_pct":case["original_author_max_drawdown_pct"],
                "original_grid_OOS_ret":author_grid[variant]["original_author_grid_original_oos_ret_pct"],
                "native_mql5":False
            },sort_keys=True),flush=True)
        payload[variant]=output
    data={
      "schema":"aidy.s006.original_publisher_ema_adx_real_spot_three_source_grid_variants.v1",
      "original_publisher_commit":AUTHOR,
      "original_publisher_blobs":BLOBS,
      "market_h1_count":len(h),
      "original_22_HistData_months":len(receipts),
      "original_H1_source_sha256":hsha,"original_22_month_m15_sha256":marketsha,
      "original_month_market_receipts":receipts,
      "original_EMA_variants_preregistered_before_new_spot_replay":True,
      "author_published_EMA_9_120_best_grid_ADX_filter_disabled":True,
      "S006_2_ADX_enabled_variants_are_other_author_grid_candidates_not_MQL5_presets":True,
      "original_publisher_MQL5_EA_has_only_DONCHIAN_and_SESSION_modes":True,
      "native_MQL5_EA_execution_of_EMA_ADX_not_possible_from_current_original_EA":True,
      "source_price_replay_original_research_cost_only_not_actual_broker":True,
      "research_only_retrospective_2025_2026_no_untouched_OOS":True,
      "separate_10000_USD_initial_account_per_variant_and_year":True,
      "all_source_stats":payload,
    }
    data["sha256"]=hashlib.sha256(json.dumps(data,sort_keys=True,
          separators=(",",":"),allow_nan=False).encode()).hexdigest()
    out.joinpath("S006_ALL_VARIANTS_SOURCE_PY_REAL_SPOT_AUDIT.json").write_text(
        json.dumps(data,sort_keys=True,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    narrative=[
      "# S006 original EMA crossover / ADX author-source independent 2025 and Jan-Sep2026 real spot research",
      "",
      "**ALERT:** Original Apex MQL5 Expert Advisor only implements Donchian and Session. S006 EMA+ADX is actual source-PYTHON optimizer strategy only. There is NO original gold EMA ADX production .set or published native MT5 execution to claim parity. The best published XAUUSD EMA grid entry ADX=0 (OFF); other ADX20/25 are deliberately separately predeclared source-grid candidates.",
      "",
      "| Frozen publisher source variant | Period | Real original PY $10k net | Trades | PF | Original marked DD% | Median genuine source ENTRY spread/oz |",
      "|---|---|---:|---:|---:|---:|---:|"
    ]
    for name,v in payload.items():
      for y,p in v["periods"].items():
        narrative.append(f"| {name} | {y} | {p['net_usd']} | {p['original_python_publisher_trades']} | {p['profit_factor']} | {p['original_author_max_drawdown_pct']} | {p['source_observed_entry_spread_median_per_oz']} |")
    narrative.extend([
       "",
       "## How it trades (original source)",
       "- On closed H1 bar, 9 EMA crosses 120 EMA from below -> LONG, crosses from above -> SHORT.",
       "- ADX14 >=20/25 is optional filter only for two registered variants; the author's best historical EMA configuration has ADX=0 (OFF).",
       "- Original source research engine executes next opening BID-proxy market quote, risks 1% on 2x Wilder ATR14 initial stop and manages 3.5x ATR trailing stops, no fixed TP, stop-and-reverse enabled.",
       "- No explicit signal-channel exit. Opposite EMA crossover triggers next-bar reversal; ATR stop/trailing also exit.",
       "- Source model cost $0.45 per ounce, continuous position sizing, leverage20. Real observed spot source entry spread is included only as diagnostic, not automatically applied in original outcomes.",
       "- Authors' original 70/30 split and 2025/2026 retrospectively read data do NOT count as virgin holdout.",
       "- Full native bidask-side short stop path, broker lot margin/swaps and executable MQL5 EA implementation are NOT present, so /100 evidence rating must not be fabricated.",
       "",
       "Source qualification: author source commit "+AUTHOR,
       "Immutable output SHA: "+data["sha256"],
    ])
    out.joinpath("S006_ORIGINAL_SOURCE_PY_H1_SPOT_RESEARCH_REPORT.md").write_text(
        "\n".join(narrative)+"\n",encoding="utf-8")
    print("S006_ALL_ORIGINAL_GRID_EMA_ADX_RESEARCH_COMPLETED",json.dumps({
       "sha256":data["sha256"],"cases":len(payload)*2,
       "native_MQL5_EA_available":False,
       "independent_sealed_OOS":False
    },sort_keys=True),flush=True)
    return data


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--source-root",required=True,type=Path)
    p.add_argument("--publisher-root",required=True,type=Path)
    p.add_argument("--out",required=True,type=Path)
    o=p.parse_args();o.out.mkdir(parents=True,exist_ok=True)
    run(o.publisher_root,o.source_root,o.out)

if __name__=="__main__":
    main()
