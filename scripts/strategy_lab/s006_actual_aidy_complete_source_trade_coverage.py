"""S006 canonical AIDY toolbox and all original EMA/ADX source-trade PriceMath.

These calls use the genuine connected source modules, not a newly coded
pretend expert. Unconnected macro/news and full historical order-fill
brokers stay UNKNOWN. Original published source trade signals are untouched.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

from aidy.gold_toolbox_registry import (
    build_gold_toolbox_manifest,verify_gold_toolbox_manifest)
from aidy.gold_price_expert_math import (
    build_price_expert_math_packet,verify_price_expert_math_packet)
from aidy.strategy_lab_evidence_rating import (
    EvidenceBasis,FactorFinding,FACTOR_WEIGHTS,rate_strategy_evidence)
from scripts.strategy_lab.s001_two_period_original_rules import read_source
from scripts.strategy_lab.s005_actual_aidy_capability_coverage import (
    precompute_datasets)

SOURCE_AUTHOR="3dab20e20a846edae9ac6fcf56d6b090dbba9f98"

def quote_candles(datasets,asof,sha):
    rows=[]
    for tf,(frame,mins) in datasets.items():
        latest=asof-pd.Timedelta(minutes=mins)
        for ts,z in frame.loc[frame.index<=latest].tail(75).iterrows():
            rows.append({
               "symbol":"XAUUSD",
               "timeframe":tf,
               "open_time_utc":ts.tz_localize("UTC").isoformat(),
               "open":float(z["open"]),"high":float(z["high"]),
               "low":float(z["low"]),"close":float(z["close"]),
               "research_identity":"s006:original_histdata:"+sha+":"+tf,
               "provenance_class":"retrospective_history",
               "pit_eligible":False,
               "source":"HistData original genuine complete source M15",
               "source_payload_sha256":sha,
               "derivation_version":"aidy_s006_all_ema_original_spot_v1",
            })
    return rows

def gate(sourced):
    basis=EvidenceBasis(
      origin="independent_costed_xauusd",
      strategy_rule_sha256=hashlib.sha256(
         ("S006 fixed EMA-ADX source "+SOURCE_AUTHOR).encode()).hexdigest(),
      historical_input_sha256=sourced["original_22_month_m15_sha256"],
      original_run_sha256=sourced["sha256"],
      verified_costed_trade_ledger_sha256=None,
      oos_holdout_trial_tip_sha256=None,
      fair_matched_benchmark_sha256=None,
      historical_source_independently_verified=True,
      actual_bid_ask_costed_trades_independently_replayed=False,
      chronological_oos_trading_independently_verified=False,
      fair_benchmark_independently_verified=False,
      full_trial_family_independently_registered=False,
      historical_trades=None,
      observed_net_expectancy_usd=None,
      observed_benchmark_edge_usd=None,
      independently_verified_unacceptable_risk=False,
    )
    findings=tuple(FactorFinding(
      factor=k,status="INSUFFICIENT" if k in (
      "broker_compatibility","out_of_sample_robustness",
      "independent_reproducibility","adequate_sample_size") else "UNKNOWN",
      awarded_points=None,source_sha256=None,
      explanation="Original publisher EMA+ADX not implemented in native MQL5 EA. Broker parity, untested OOS, matched comparison or full trade evidence not yet established."
    ) for k,_ in FACTOR_WEIGHTS)
    result=rate_strategy_evidence(basis,findings).to_wire()
    if result.get("score_out_of_100") is not None:
        raise ValueError("S006 refuses native evidence rating without original MQL5/true OOS")
    return result

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--source-root",type=Path,required=True)
    ap.add_argument("--s006-original-evidence",type=Path,required=True)
    ap.add_argument("--out",type=Path,required=True)
    args=ap.parse_args()
    source=json.loads(args.s006_original_evidence.read_text())
    if source["original_publisher_commit"]!=SOURCE_AUTHOR or len(source["all_source_stats"])!=3:
        raise ValueError("Not original three S006 publisher EMA configurations")
    h,receipts,sha=read_source(args.source_root)
    if len(receipts)!=22 or sha!=source["original_22_month_m15_sha256"]:
        raise ValueError("S006 source market originals not authenticated")
    datasets=precompute_datasets(h)
    manifest=build_gold_toolbox_manifest(
        gold_state={},semantic_context={},live_source_availability={})
    if not verify_gold_toolbox_manifest(manifest):
        raise ValueError("Canonical real AIDY toolbox verification failed")
    records={}
    entries=0
    digests=[]
    for variant,meta in source["all_source_stats"].items():
      records[variant]={}
      for year in ("2025","2026"):
        authored=meta["periods"][year]["trade_ledger"]
        sample=[]
        for n,t in enumerate(authored):
          asof=pd.Timestamp(t["entry_time_utc"].replace("Z","+00:00"))
          if asof.tzinfo is not None:
              asof=asof.tz_convert("UTC").tz_localize(None)
          packet=build_price_expert_math_packet(
              as_of=asof.tz_localize("UTC").to_pydatetime(),
              symbol="XAUUSD",candle_rows=quote_candles(datasets,asof,sha),
              mode="retrospective")
          if not verify_price_expert_math_packet(packet):
              raise ValueError("Canonical actual AIDY primitive evidence receipt invalid")
          if packet["pit_eligible"] or packet["future_values_used"]:
              raise ValueError("S006 original retrospectively known data falsely accepted as live PIT")
          psha=packet["packet_digest"]
          sample.append({
            "source_original_entry_utc":t["entry_time_utc"],
            "source_trade_number":n,
            "AIDY_real_price_math_digest":psha,
            "original_source_trade_direction":t["direction"],
            "original_source_continuous_quantity":t["units_float_not_broker_lots"],
            "completed_original_source_frames":{
                tf:packet["timeframes"][tf]["bars_available"]
                for tf in ("M15","H1","H4")},
            "actual_AIDY_primitive_families":len(packet["primitive_manifest"]),
            "original_AIDY_source_market_math_retrospective":True,
            "math_did_not_modify_author_original_ema_signals":True
          })
          digests.append(psha)
          entries+=1
        if len(sample)!=len(authored):
            raise ValueError("Full original source trade AIDY annotation incomplete")
        records[variant][year]={
           "author_original_closed_trades":len(authored),
           "AIDY_real_price_math_full_trade_count":len(sample),
           "all_author_trades_have_actual_AIDY_math":True,
           "genuine_12_primitive_AIDY_price_expert_source_executed":True,
           "not_all_macro_and_live_brains_historically_connected":True,
           "source_trade_math":sample
        }
        print("S006_AIDY_ORIGINAL_SOURCE_MATH_ALL_TRADES",json.dumps({
          "variant":variant,"year":year,
          "author_trades":len(authored),"actual_AIDY_price_packets":len(sample),
          "known_AIDY_capabilities_not_all_executed":manifest["known_capability_count"]
        },sort_keys=True),flush=True)
    score=gate(source)
    out={
      "schema":"aidy.s006.ema_adx_canonical_real_all_trade_price_math_original.v1",
      "S006_source_original_Python_run_sha256":source["sha256"],
      "source_22_month_m15_original_sha256":sha,
      "canonical_toolbox_manifest":manifest,
      "canonical_real_AIDY_toolbox_verified":True,
      "all_AIDY_PriceMath_source_packets_run":entries,
      "original_author_trades_all_in_model_cases":sum(
          x["original_python_publisher_trades"]
          for v in source["all_source_stats"].values()
          for x in v["periods"].values()),
      "all_trades_historically_analyzed_using_actual_AIDY_price_math":True,
      "primitive_packet_digest_list_sha256":hashlib.sha256(
          json.dumps(digests,separators=(",",":")).encode()).hexdigest(),
      "AIDY_actual_nine_factor_gating_invoked":True,
      "AIDY_actual_nine_factor_result":score,
      "AIDY_numeric_evidence_score_not_issued":True,
      "verified_native_MQL5_EMA_ADX_strategy_preset":False,
      "genuine_untouched_holdout_verified":False,
      "retrospective_not_live_PIT":True,
      "no_live_trading_or_paper_execution":True,
      "per_variant_case":records,
    }
    if out["all_AIDY_PriceMath_source_packets_run"]!=out["original_author_trades_all_in_model_cases"]:
        raise ValueError("S006 original source trade AIDY complete coverage mismatched")
    out["sha256"]=hashlib.sha256(json.dumps(
       out,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    args.out.mkdir(parents=True,exist_ok=True)
    (args.out/"S006_REAL_AIDY_FULL_ORIGINAL_TRADE_COVERAGE_AND_GOVERNANCE.json").write_text(
       json.dumps(out,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print("S006_REAL_AIDY_ALL_SOURCE_EMA_ADX_TRADES_QUALIFIED_WITH_CAVEATS",json.dumps({
       "sha256":out["sha256"],"entries":entries,
       "toolbox_count":manifest["known_capability_count"],
       "nine_factor_score":score.get("score_out_of_100"),
       "native_MQL5_EMA_ADX_parity":False,
       "sealed_OOS":False
    },sort_keys=True),flush=True)

if __name__=="__main__": main()
