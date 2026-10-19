"""S005 original-price-source publisher 497 trade audit, no invented EA fills.

Calls AIDY's existing authenticated 22-month source reader. This study checks:
1. 100% publisher Python published trade dollar arithmetic;
2. real observed original HistData opening bid/ask spread at EACH entry;
3. source trade fixed-cohort all-in per-oz cost sensitivity;
4. signed trading performance by direction, exit reason and prior-known H1
   trend (with a rolling 24-completed-H1 bar causal slope);
5. deterministic calendar-month block resampling of original outcomes.

No substitutions of original strategy signals, stop sequencing or positions.
The same-price entry-spread-as-roundtrip quote cost PROXY is a stated
hypothesis, not the native MQL5 long/short broker roundtrip. Different
source feed/broker point, ask stop tick sequence and actual funding remain
unqualified. Fixed historic trades are not an untouched holdout.
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

from scripts.strategy_lab.s001_two_period_original_rules import read_source

PUBLISHER_SOURCE_COMMIT="3dab20e20a846edae9ac6fcf56d6b090dbba9f98"
FAMILIES=("DONCHIAN","SESSION")
PERIODS={"2025":12,"2026":9}
ORIGINAL_COST_PER_OZ=0.45
OBSERVED_QUOTE_PROXY_EXTRA_PER_OZ=0.27  # $0.20 two-sided slip + $0.07/oz commission
COST_SCENARIOS=(0.45,0.60,0.80,1.00,1.50,2.00,3.00)
BOOTSTRAP_SEED=20261019
BOOTSTRAP_DRAWS=4000


def _source_monthly_values(trades,year:str):
    by_month=defaultdict(float)
    for t in trades:
        month=t["exit_time_utc"][:7]
        if month[:4]!=year:
            raise ValueError("Original author trade escape from independent period")
        by_month[month]+=float(t["publisher_costed_usd"])
    return np.asarray([by_month[f"{year}-{i:02d}"]
                       for i in range(1,PERIODS[year]+1)],dtype=float)


def _resample_months(month_values,year,mode):
    # Explicitly exploratory, resamples only development months with replacement.
    # Not a walkforward, not a t-test or proof of statistical significance.
    mode_offset=0 if mode=="DONCHIAN" else 1_000_000
    rng=np.random.default_rng(BOOTSTRAP_SEED+int(year)+mode_offset)
    choices=rng.choice(month_values,size=(BOOTSTRAP_DRAWS,len(month_values)),
                       replace=True)
    sample=choices.sum(axis=1)
    return {
       "random_seed":BOOTSTRAP_SEED+int(year)+mode_offset,
       "draws":BOOTSTRAP_DRAWS,
       "q025_usd":round(float(np.quantile(sample,.025)),2),
       "q50_usd":round(float(np.quantile(sample,.5)),2),
       "q975_usd":round(float(np.quantile(sample,.975)),2),
       "fraction_nonpositive":round(float(np.mean(sample<=0)),6),
       "limited_months":len(month_values),
       "proof_is_independent_OOS":False,
       "month_blocks_nonindependent":True,
    }


def _signed_summary(trades,group_field):
    buckets=defaultdict(list)
    for t in trades:
        buckets[t[group_field]].append(float(t["publisher_costed_usd"]))
    return {str(k):{
        "trades":len(v),"net_usd":round(sum(v),2),
        "model_wins":sum(x>0 for x in v),
        "model_losses":sum(x<0 for x in v),
    } for k,v in sorted(buckets.items(),key=lambda x:str(x[0]))}


def _annotate_one(row,source,prior_h1_trend,year,mode,i):
    entry=pd.Timestamp(row["entry_time_utc"].replace("Z","+00:00"))
    naive=entry.tz_convert("UTC").tz_localize(None)
    if naive not in source.index:
        raise ValueError(f"Original author entry not in authentic source {mode} {year} {naive}")
    market=source.loc[naive]
    entry_spread=float(market["observed_open_spread"])
    if not np.isfinite(entry_spread) or entry_spread<0:
        raise ValueError("Bad independently sourced BID/ASK source spread")
    units=float(row["units_float_not_broker_lots"])
    model=float(row["publisher_costed_usd"])
    entry_px=float(row["entry_price_publisher_bid_proxy"])
    exit_px=float(row["exit_price_publisher_bid_proxy"])
    sign=1 if row["direction"]=="LONG" else -1
    if units<=0 or sign not in (-1,1):
        raise ValueError("Nonphysical author original position")
    check=units*((exit_px-entry_px)*sign-ORIGINAL_COST_PER_OZ)
    if abs(check-model)>0.00012:
        raise ValueError(f"Original publisher 497-trade costed P&L DOES NOT RECONCILE: {mode} {year} {i}: {check} vs {model}")
    if abs(float(market["open"])-entry_px)>0.05:
        # Source Python uses real H1 opening BID. These prices must agree.
        raise ValueError(f"Original author entry price diverges from authentic source H1 bid {mode} {year} {i}")
    # Independently verifiable ENTRY quote alone. SHORT pays executable
    # spread at EXIT, not entry. Thus this is a cost diagnostic/proxy,
    # NOT a faithful original MQL5 executable result.
    future_uncertainty="SHORT_PAY_SPREAD_AT_EXIT_NOT_ENTRY" if sign==-1 else "LONG_ENTRY_OPEN_ASK_OBSERVED"
    hypothetical_fee=entry_spread+OBSERVED_QUOTE_PROXY_EXTRA_PER_OZ
    proxy=model-(hypothetical_fee-ORIGINAL_COST_PER_OZ)*units
    trend=prior_h1_trend.get(naive,np.nan)
    if pd.isna(trend):regime="UNKNOWN_WARMUP"
    elif trend>0:regime="PREVIOUS_24_COMPLETE_H1_RISING"
    elif trend<0:regime="PREVIOUS_24_COMPLETE_H1_FALLING"
    else:regime="PREVIOUS_24_COMPLETE_H1_FLAT"
    return {
      "family":mode,"year":year,"trade_index":i,
      "entry_time_utc":row["entry_time_utc"],
      "exit_time_utc":row["exit_time_utc"],
      "direction":row["direction"],"exit_reason":row["reason"],
      "publisher_entry_bid":entry_px,"publisher_exit_bid_or_stop":exit_px,
      "publisher_continuous_oz":round(units,8),
      "publisher_net_usd":round(model,6),
      "independent_recalculated_publisher_net_usd":round(check,6),
      "real_histdata_entry_bid":float(market["open"]),
      "real_histdata_entry_ask":float(market["observed_open_ask"]),
      "real_histdata_entry_spread_per_oz":round(entry_spread,6),
      "real_entry_spread_exceeds_publishers_ENTIRE_0p45_cost":entry_spread>ORIGINAL_COST_PER_OZ,
      "observed_entry_spread_gt_60_points_if_point_0p01":entry_spread>.60,
      "observed_entry_spread_gt_60_points_if_point_0p001":entry_spread>.06,
      "market_regime_at_entry":regime,
      "source_exposure_same_original":True,
      "entry_spread_quote_proxy_total_cost_per_oz":round(hypothetical_fee,6),
      "entry_spread_quote_proxy_adjusted_net_usd":round(proxy,6),
      "quote_proxy_is_NOT_verified_MQL5_trade_fill":True,
      "short_spread_caveat":future_uncertainty,
    }


def analyse(source,evidence):
    if evidence["publisher_git_commit"]!=PUBLISHER_SOURCE_COMMIT:
        raise ValueError("Wrong original publisher source commit")
    if evidence["fully_authenticated_22_source_months"]!=22:
        raise ValueError("Original authenticated source receipts incomplete")
    actual_source_hash=hashlib.sha256(
      json.dumps(evidence["market_source_receipts"],sort_keys=True,
      separators=(",",":")).encode()).hexdigest()
    if not actual_source_hash:
        raise ValueError("Missing receipt proof")
    h=source.resample("60min").agg(
       open=("open","first"),high=("high","max"),low=("low","min"),
       close=("close","last"),quarter_count=("open","count"))
    h=h.loc[h.quarter_count==4]
    if len(h)<10000:raise ValueError("Insufficient causal fully observed H1 source bars")
    # Entry H1 opening time T may only use closes ending at or before T:
    # shift 1 previous H1 bar and shift 25 for previous 24 complete bars.
    causal_slope=h.close.shift(1)-h.close.shift(25)
    annotated=[]
    results={}
    for mode in FAMILIES:
        results[mode]={}
        for year in PERIODS:
            case=evidence["cases"][mode]["periods"][year]
            entries=case["trade_ledger"]
            if len(entries)!=case["trades"] or case["initial_usd"]!=10000:
                raise ValueError("Publisher economic source case was not reset to $10k")
            audited=[_annotate_one(t,source,causal_slope,year,mode,i)
                      for i,t in enumerate(entries)]
            expected_net=round(sum(float(t["publisher_costed_usd"]) for t in entries),2)
            if abs(expected_net-case["net_usd"])>.02:
                raise ValueError("Author original model net P&L mismatch")
            qty=sum(t["publisher_continuous_oz"] for t in audited)
            net=case["net_usd"]
            extra={f"{cost:.2f}":round(net-(cost-ORIGINAL_COST_PER_OZ)*qty,2)
                   for cost in COST_SCENARIOS}
            entry_spreads=[t["real_histdata_entry_spread_per_oz"] for t in audited]
            months=_source_monthly_values(entries,year)
            scenarios={
                "fixed_original_trade_cohort_cost_scenarios_usd":extra,
                "publisher_all_in_roundtrip_cost_per_oz":ORIGINAL_COST_PER_OZ,
                "source_entry_spread_only_exceeds_all_in_cost_count":sum(s>ORIGINAL_COST_PER_OZ for s in entry_spreads),
                "source_entry_quote_spread_usd_per_oz_median":round(float(np.median(entry_spreads)),4),
                "source_entry_quote_spread_usd_per_oz_p90":round(float(np.quantile(entry_spreads,.9)),4),
                "source_entry_quote_spread_usd_per_oz_max":round(float(max(entry_spreads)),4),
                "entry_quote_above_point_0p01_spread_gate":sum(s>.60 for s in entry_spreads),
                "entry_quote_above_point_0p001_spread_gate":sum(s>.06 for s in entry_spreads),
                "fixed_cohort_proxy_uses_ENTRY_SPREAD_FOR_SHORTS_AS_DIAGNOSTIC_ONLY":True,
                "proxy_assumed_spread_plus_0p20_slippage_plus_0p07_commission_net_usd":round(
                    sum(t["entry_spread_quote_proxy_adjusted_net_usd"] for t in audited),2),
                "fixed_original_trade_cohort_does_NOT_recreate_new_entry_rules":True,
            }
            report={
                "year":year,"family":mode,
                "original_author_model_trades":len(entries),
                "original_author_model_net_usd":net,
                "original_author_model_PF":case["profit_factor"],
                "original_author_position_volume_oz_total":round(qty,3),
                "stop_break_even_full_cost_usd_per_oz":round(
                   ORIGINAL_COST_PER_OZ+net/qty,4) if qty>0 else None,
                "independent_source_pnl_reconciliation_exact":True,
                "source_entry_quote_coverage_pct":100,
                "real_original_source_m15_bars":len(source),
                "cost":scenarios,
                "directions":_signed_summary(audited,"direction"),
                "exit_reasons":_signed_summary(audited,"exit_reason"),
                "prior_entry_market_regimes":_signed_summary(audited,"market_regime_at_entry"),
                "profitable_calendar_months":int(sum(months>0)),
                "losing_calendar_months":int(sum(months<0)),
                "bootstrap":_resample_months(months,year,mode),
                "actual_frozen_original_trades":audited,
            }
            results[mode][year]=report
            annotated+=audited
            print("S005_INDEPENDENT_COST_AND_REGIME_AUDIT",json.dumps({
                 "year":year,"mode":mode,"original_trades":len(entries),
                 "original_net_usd":net,
                 "published_cost_undershoots_observed_entry_spread_count":scenarios["source_entry_spread_only_exceeds_all_in_cost_count"],
                 "full_cost_break_even_usd_per_oz":report["stop_break_even_full_cost_usd_per_oz"],
                 "calendar_month_bootstrap_q025_usd":report["bootstrap"]["q025_usd"],
             },sort_keys=True),flush=True)
    if len(annotated)!=497 or sum(r["source_entry_spread_only_exceeds_publishers_ENTIRE_0p45_cost"]
                                  for r in annotated)!=456:
        raise ValueError("Historic 497 author original trades or original quote-cost evidence mismatch")
    return {
      "schema":"aidy.s005.author_original_497_spot_quote_cost_regime_bootstrap.v1",
      "strategy_source":PUBLISHER_SOURCE_COMMIT,
      "publisher_source_run_sha256":evidence["sha256"],
      "source_m15_history_sha256":evidence["all_original_m15_sha256"],
      "source_history_receipt_envelope_sha256":actual_source_hash,
      "author_source_position_and_entry_exit_rules_UNCHANGED":True,
      "n_original_trades_all_verified":len(annotated),
      "original_quote_source_is_authentic_histdata_spot":True,
      "all_original_entry_spreads_observed":True,
      "source_spread_exceeds_publisher_whole_cost_on_trades":456,
      "source_PY_roundtrip_0p45_not_a_verified_broker_cost":True,
      "true_native_spot_broker_exit_ASK_tick_parity":False,
      "retrospective_cost_scenarios_reselect_original_signals":False,
      "fixed_cohort_does_NOT_prove_prospective_edge":True,
      "months_bootstrap_is_not_sealed_holdout":True,
      "source_calendar_assumption":"original HISTDATA fixed EST converted UTC",
      "canonical_aidy_execution_broker_and_OOS_gaps_remain":True,
      "results":results,
    }, annotated


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--source-root",type=Path,required=True)
    ap.add_argument("--publisher-evidence",type=Path,required=True)
    ap.add_argument("--out",type=Path,required=True)
    a=ap.parse_args()
    source,receipts,marketsha=read_source(a.source_root)
    evidence=json.loads(a.publisher_evidence.read_text())
    if marketsha!=evidence["all_original_m15_sha256"] or len(receipts)!=22:
        raise ValueError("Independent source monthly price receipts are not the original 22")
    data,trade_rows=analyse(source,evidence)
    data["sha256"]=hashlib.sha256(json.dumps(
        data,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()
    a.out.mkdir(parents=True,exist_ok=True)
    (a.out/"S005_ALL_497_COST_REGIME_ROBUSTNESS.json").write_text(
        json.dumps(data,indent=2,sort_keys=True,allow_nan=False)+"\n",encoding="utf-8")
    with (a.out/"S005_ALL_497_REAL_QUOTES_AND_CONTEXT.csv").open(
         "w",newline="",encoding="utf-8") as h:
        writer=csv.DictWriter(h,fieldnames=list(trade_rows[0]))
        writer.writeheader();writer.writerows(trade_rows)
    summary=["# S005 497-trade original-source cost and causally prior-known trend audit",
        "Exact 22 authenticated original HistData source archives + the original publisher-PY trade ledger.",
        "This is NOT compiled MT5 native fills and does NOT represent unseen holdout.",
        "| Preset | Year | Trades | Original PY net | Entry source spread median $/oz | Source spread > publisher $0.45 cost | Cost-to-break-even $/oz | Positive months | Monthly bootstrap 2.5% |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for family,cases in data["results"].items():
        for year,v in cases.items():
            summary.append("| "+family+" | "+year+" | "+str(v["original_author_model_trades"])+" | "+str(v["original_author_model_net_usd"])+
                " | "+str(v["cost"]["source_entry_quote_spread_usd_per_oz_median"])+
                " | "+str(v["cost"]["source_entry_spread_only_exceeds_all_in_cost_count"])+
                " | "+str(v["stop_break_even_full_cost_usd_per_oz"])+
                " | "+str(v["profitable_calendar_months"])+
                " | "+str(v["bootstrap"]["q025_usd"])+" |")
    summary.extend(["","## Explicit methodology","- Audit original author Python model trade P&L to ±$0.00012 using source documented $0.45/oz roundtrip (not original native MQL5 fills).",
       "- The 456 cost-underestimate warning compares authentic ENTRY bid/ask quotes only. Shorts pay actual spread on EXIT, which requires native bid/ask tick evidence and is NOT proved by entry quotes.",
       "- Bootstrap independently resamples **observed monthly profit blocks** only. Month blocks may be dependent, historical data are known, this is NOT a sealed OOS CI or population alpha test.",
       "- Extra fixed-cost scenarios keep the ORIGINAL trade cohort, size and stop outcomes FIXED and vary only charged roundtrip fee; NOT a newly executable trade simulation.",
       "- 24-completed-H1 trend uses source-close SHIFTED to before the original trade's entry instant. These regime tags are explanatory and do not filter trades.",
       "- Full source-native MQL5/ASK-tick, broker point, swap, true matched baseline and independent forward validation remain mandatory engineering gaps.","",
       "Immutable audit SHA256: "+data["sha256"]])
    (a.out/"S005_ADDITIONAL_EXECUTION_COST_AND_REGIME_AUDIT.md").write_text(
        "\n".join(summary)+"\n",encoding="utf-8")
    print("S005_ECONOMIC_497_COST_REGIME_AUDIT_PASSED",json.dumps({
        "audit_sha256":data["sha256"],"original_trades":len(trade_rows),
        "source_entry_spread_exceeds_original_all_in_cost":456,
        "native_MQL5_test_complete":False,
        "genuine_OOS_complete":False,
    },sort_keys=True),flush=True)


if __name__=="__main__":
    main()
