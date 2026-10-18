"""S005 uses REAL AIDY toolbox, shared price-mathematics and nine-factor gate.

These are genuine runtime calls to existing AIDY modules on source-authenticated
price windows; individual expert / macro signals not callable without archived
PIT inputs are explicitly NOT faked. Strategy trade parameters NEVER modified.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, timedelta
from pathlib import Path

import pandas as pd

from aidy.gold_toolbox_registry import (
    build_gold_toolbox_manifest,
    verify_gold_toolbox_manifest,
)
from aidy.gold_price_expert_math import (
    build_price_expert_math_packet,
    verify_price_expert_math_packet,
)
from aidy.strategy_lab_evidence_rating import (
    EvidenceBasis,
    FactorFinding,
    FACTOR_WEIGHTS,
    rate_strategy_evidence,
)
from scripts.strategy_lab.s005_publisher_engine_two_preset_parity import (
    PUB_COMMIT,
    source_h1,
)

def candle_rows(h:pd.DataFrame,as_of:pd.Timestamp,market_sha:str):
    # Each emitted candle has CLOSED before as_of. No future candles or
    # outcome-based inclusion, and NO retrospective -> PIT promotion.
    datasets={
       "M15":(h,15),
       "H1":(h.resample("60min").agg(
         open=("open","first"),high=("high","max"),low=("low","min"),
         close=("close","last"),bars=("open","count")).loc[lambda v:v.bars==4],60),
    }
    m15=h
    h4=m15.resample("240min").agg(
       open=("open","first"),high=("high","max"),low=("low","min"),
       close=("close","last"),bars=("open","count"))
    datasets["H4"]=(h4.loc[h4.bars==16],240)
    all_rows=[]
    for tf,(frame,minutes) in datasets.items():
        cutoff=as_of-pd.Timedelta(minutes=minutes)
        limited=frame.loc[frame.index<=cutoff].tail(75)
        for ts,row in limited.iterrows():
            all_rows.append({
              "symbol":"XAUUSD","timeframe":tf,
              "open_time_utc":ts.tz_localize("UTC").isoformat(),
              "open":float(row["open"]),"high":float(row["high"]),
              "low":float(row["low"]),"close":float(row["close"]),
              "research_identity":"s005:histdata:"+market_sha+":"+tf,
              "provenance_class":"retrospective_history",
              "pit_eligible":False,
              "source":"HistData genuine original complete BID/ASK source M15",
              "source_payload_sha256":market_sha,
              "derivation_version":"aidy_s005_h1_source_complete_only_v1"
            })
    return all_rows

def nine_factor_gate(publisher_sha:str,source_sha:str):
    basis=EvidenceBasis(
      origin="independent_costed_xauusd",
      strategy_rule_sha256=hashlib.sha256(
        ("S005 both source presets pinned "+PUB_COMMIT).encode()).hexdigest(),
      historical_input_sha256=source_sha,
      original_run_sha256=publisher_sha,
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
        factor=f,status="INSUFFICIENT" if f in (
           "out_of_sample_robustness","broker_compatibility",
           "independent_reproducibility","adequate_sample_size") else "UNKNOWN",
        awarded_points=None,source_sha256=None,
        explanation="Full trusted source-specific execution, benchmark or OOS receipts not established."
      ) for f,_ in FACTOR_WEIGHTS)
    gate=rate_strategy_evidence(basis,findings).to_wire()
    if gate.get("score_out_of_100") is not None:
        raise ValueError("S005 MUST NOT score without native execution/OOS")
    return gate

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--source-root",type=Path,required=True)
    ap.add_argument("--publisher-evidence",type=Path,required=True)
    ap.add_argument("--out",type=Path,required=True)
    o=ap.parse_args()
    original=json.loads(o.publisher_evidence.read_text())
    assert original["publisher_git_commit"]==PUB_COMMIT
    m15,receipts,market_sha,hsha,times,hours,weekdays=source_h1(o.source_root)
    assert len(receipts)==22 and market_sha==original["all_original_m15_sha256"]
    full_m15=m15 # name inherited from source_h1, this is source-derived H1.
    # We need the original M15 source for M15 / H4, not H1 approximation.
    from scripts.strategy_lab.s001_two_period_original_rules import read_source
    real_m15,_,originalsha=read_source(o.source_root)
    assert originalsha==market_sha
    manifest=build_gold_toolbox_manifest(
      gold_state={},semantic_context={},live_source_availability={})
    if not verify_gold_toolbox_manifest(manifest):
        raise ValueError("AIDY canonical toolbox manifest verification failed")
    reports={}
    for family in ("DONCHIAN","SESSION"):
        reports[family]={}
        for yr in ("2025","2026"):
            evidence=original["cases"][family]["periods"][yr]
            trades=evidence["trade_ledger"]
            # Representative PREDECLARED set: chronological first, 25%, 50%,
            # 75%, last. No post-outcome optimisation or chart-picking.
            indices=sorted(set(round((len(trades)-1)*fraction)
                               for fraction in (0,.25,.5,.75,1))) if trades else []
            snapshots=[]
            for k in indices:
                trade=trades[k]
                asof=pd.Timestamp(trade["entry_time_utc"].replace("Z","+00:00"))
                if asof.tzinfo is not None:
                    asof=asof.tz_convert("UTC").tz_localize(None)
                candle_inputs=candle_rows(real_m15,asof,market_sha)
                packet=build_price_expert_math_packet(
                    as_of=asof.tz_localize("UTC").to_pydatetime(),
                    symbol="XAUUSD",candle_rows=candle_inputs,mode="retrospective")
                if not verify_price_expert_math_packet(packet):
                    raise ValueError("AIDY real price-math original-source parity packet failed")
                if packet["pit_eligible"] or packet["future_values_used"]:
                    raise ValueError("Retrospective price expert falsely promoted to PIT")
                snapshots.append({
                    "entry_time_utc":trade["entry_time_utc"],
                    "original_publisher_trade_index":k,
                    "AIDY_price_math_packet_sha256":packet["packet_digest"],
                    "frames_completed":{
                      tf:packet["timeframes"][tf].get("observed_candles",
                            packet["timeframes"][tf].get("completed_candle_count"))
                      for tf in ("M15","H1","H4")},
                    "primitive_manifest_count":len(packet["primitive_manifest"]),
                    "research_not_pit":True,
                    "did_not_change_original_signal":True})
            reports[family][yr]={
                "actual_AIDY_source_math_execution":len(snapshots),
                "original_publisher_trades":len(trades),
                "sample_method":"chronological fixed-index 0/25/50/75/100pct, not chosen by P&L",
                "price_math_samples":snapshots,
                "not_all_trades_PIT_gold_experts_executed":True,
                "macro_asof_and_news_intelligence_not_qualified":True,
                "source_backtest_trades_unmodified":True,
            }
            print("S005_AIDY_INTELLIGENCE_COVERAGE",json.dumps({
                "family":family,"year":yr,
                "source_trades":len(trades),"AIDY_math_packets":len(snapshots),
                "toolbox_catalogue":manifest["known_capability_count"]
            },sort_keys=True),flush=True)
    gate=nine_factor_gate(original["sha256"],market_sha)
    packet={
      "schema":"aidy.s005.actual_full_toolbox_inventory_original_evidence.v1",
      "original_market_sha256":market_sha,
      "original_publisher_run_sha256":original["sha256"],
      "frozen_publisher_git_commit":PUB_COMMIT,
      "aidy_toolbox_source_component":"aidy.gold_toolbox_registry",
      "AIDY_toolbox_manifest_valid":True,
      "canonical_toolbox_manifest":manifest,
      "aidy_source_real_price_math_executed":True,
      "AIDY_price_math_mode":"retrospective",
      "representative_not_all_trades":True,
      "real_AIDY_nine_factor_governance_invoked":True,
      "qualified_numeric_score_prohibited":True,
      "nine_factor_AIDY_real_result":gate,
      "source_native_MT5_trade_parity":False,
      "original_backtest_and_gold_intelligence_deliberately_separate":True,
      "run_was_research_only":True,
      "no_live_broker_orders":True,
      "coverage_by_preset_period":reports,
      "hard_gaps":[
        "Original native MQL5 EA Strategy Tester real tick/stop/order receipts not available in this runner. Original Python differs on bar-close exits.",
        "Canonical toolbox lists many relevant experts as runtime-resolved/research-only, not presently wired to this original strategy audit. Sampling price-math snapshots is NOT the entire toolbox per trade.",
        "Historical source R2 M15 retains first ASK but NOT bid-and-ask full tick path needed for exact original EA ASK short-stop chronology and broker margins.",
        "Real publisher data are GC=F futures proxy; actual broker XAUUSD specification, symbol point, leverage, swaps, commissions and permissions need source-qualified receipts.",
        "AIDY Day26 sealed holdout proof is narrow example, not independent frozen S005 strategy validation. Source years already inspected and must not be renamed untouched OOS.",
        "Nine-factor score cannot be populated because actual native spot execution, matched trade benchmark, sealed OOS and independent finance-risk qualification are unproven.",
      ]
    }
    packet["sha256"]=hashlib.sha256(json.dumps(packet,sort_keys=True,
        separators=(",",":"),allow_nan=False).encode()).hexdigest()
    o.out.mkdir(parents=True,exist_ok=True)
    (o.out/"S005_CANONICAL_AIDY_CAPABILITY_COVERAGE.json").write_text(
        json.dumps(packet,indent=2,sort_keys=True,allow_nan=False)+"\n")
    print("S005_CANONICAL_AIDY_CAPABILITY_AUDIT_PASS",json.dumps({
        "sha256":packet["sha256"],"known_toolbox":manifest["known_capability_count"],
        "factor_score":gate.get("score_out_of_100"),
        "state":"INCOMPLETE_NATIVE_EA_PARITY_AND_SEALED_OOS"
    },sort_keys=True))

if __name__=="__main__":
    main()
