"""S005 FROZEN ORIGINAL-PY cohort, source ACTUAL raw BID/ASK event-revalued economics.

This is a verified raw SOURCE QUOTE / STOP OVERLAY, not a resimulation of
native MQL5 EA source. Entry and size are held exactly as immutable
publisher original Python 497 trades; later trade policy/risk are NOT
re-computed after earlier stop variations. Signal exit receives last
genuine raw tick BEFORE source H1 close (not an invented M15 ASK high);
stop exit receives the FIRST original raw correct quote-side touch.

The original published Python author's $0.45/oz all-in FIXED charge is
REPLACED with ORIGINAL source quote spread (BID/ASK) and declared
separate $0.10/oz adverse slippage per side + $0.07/oz roundtrip commission.
Financing absent from broker-confirmed source => NOT CALLED VERIFIED P&L.
Actual Vantage/MetaQuotes native tester parity is FALSE.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from datetime import datetime, UTC
from pathlib import Path

import numpy as np

ROOT_HASH="b0907976cba60714f1bb69715d553c2bf458d8ac442824efe6393bc1179ac884"
PINNED_PUBLISHER="3dab20e20a846edae9ac6fcf56d6b090dbba9f98"
FAMILIES=("DONCHIAN","SESSION")
YEARS=("2025","2026")
BASIS_SLIPPAGE_SIDE=.10
BASIS_COMMISSION_ROUNDTRIP_PER_OZ=.07
STRESS_FACTORS=(1.0,2.0,3.0)
START_EACH=10000.
DECLARED_NATIVE_MT5_CERTIFICATION=False

def _digest(d):
    return hashlib.sha256(json.dumps(d,sort_keys=True,
        separators=(",",":"),allow_nan=False).encode()).hexdigest()


def verify_original(raw,original):
    if raw.get("sha256")!=_digest({
         k:v for k,v in raw.items() if k!="sha256"}):
        raise ValueError("Full original BID ASK 497-trade stop/raw source receipt tampered")
    if len(raw["month_receipts"])!=22 or raw["original_publisher_model_trades"]!=497:
        raise ValueError("Not the full 22 original source archive 497 trade population")
    if raw["source_stop_request_sha256"]!="10bed13771dc77fa9ece75ec26a6429848c83100d3690dd73f2d9a0f63b0cfea":
        raise ValueError("The frozen original 497 publisher stop request policy was replaced")
    if (raw["original_reported_model_stop_exits"]!=129 or
        raw["source_quote_side_stop_crossings_within_original_trade_windows"]!=130 or
        raw["model_nonstop_exits_with_a_true_quote_side_crossing_before_model_exit"]!=1):
        raise ValueError("Prior original true-source raw tick regression mismatch")
    if raw["source_raw_tick_coverage_original_entries"]!=497:
        raise ValueError("Raw original BID and ASK first quote missing")
    if original.get("publisher_git_commit")!=PINNED_PUBLISHER:
        raise ValueError("Author original source SHA changed")
    if original.get("publisher_python_original_executed_on_REAL_SPOT_HISTORY") is not True:
        raise ValueError("No verified original author program execution")
    if original.get("fully_authenticated_22_source_months")!=22:
        raise ValueError("Original 22 authentic market month source SHA chain not proven")
    if original.get("native_MQL5_EA_run") is not False:
        raise ValueError("Publisher original evidence changed MT5 execution claim")
    for m in raw["month_receipts"]:
        if len(m["zip_sha256"])!=64 or len(m["qualified_sha"])!=64:
            raise ValueError("Original true tick source monthly archive SHA absent")
    ids={t["id"] for t in raw["trades"]}
    if len(ids)!=497:
        raise ValueError("Duplicate or missing original trade raw tick identifier")


def annotate_trade(raw,source,cost_factor):
    if cost_factor<=0:raise ValueError("Nonphysical trading cost factor")
    entry=raw["first_original_entry_raw_tick"]
    last=raw["last_original_window_raw_tick"]
    stop=raw["first_true_quote_side_stop_crossing"]
    if not entry or not last:
        raise ValueError("Missing true original source tick at original entry/exit")
    quantity=float(source["units_float_not_broker_lots"])
    if quantity<=0:raise ValueError("Original source has nonpositive ounce amount")
    direction=source["direction"]
    if direction!=raw["direction"] or direction not in ("LONG","SHORT"):
        raise ValueError("Original source trade direction mismatch with original raw tape")
    if source["reason"]!=raw["original_exit_reason"]:
        raise ValueError("Source original exit reason does not agree with stop scan")
    if abs(float(source["entry_price_publisher_bid_proxy"])-float(entry["bid"]))>.00001:
        raise ValueError("Original entry BID not source raw HISTDATA actual first quote")
    start=entry["instant_epoch_us"]
    exit_quote=stop if stop is not None else last
    exit_us=exit_quote["instant_epoch_us"]
    if exit_us<start:
        raise ValueError("Causality violated: exit before source entry")
    if exit_us>last["instant_epoch_us"]:
        raise ValueError("Stop quote after source original trade window last event")
    sign=+1 if direction=="LONG" else -1
    original_exit_bid=source["exit_price_publisher_bid_proxy"]
    entry_fill=float(entry["ask"]) if sign>0 else float(entry["bid"])
    exit_fill=float(exit_quote["bid"]) if sign>0 else float(exit_quote["ask"])
    original_delta=quantity*((original_exit_bid-float(entry["bid"]))*sign-.45)
    if abs(original_delta-float(source["publisher_costed_usd"]))>.00015:
        raise ValueError("Frozen author-PY trade dollar arithmetic mismatch")
    gap_mid=(stop is not None and exit_us<last["instant_epoch_us"])
    cost=cost_factor*(2*BASIS_SLIPPAGE_SIDE+BASIS_COMMISSION_ROUNDTRIP_PER_OZ)
    pnl=quantity*((exit_fill-entry_fill)*sign-cost)
    if not np.isfinite(pnl):
        raise ValueError("Nonfinite adjusted source quote economics")
    return {
      "id":raw["id"],"family":raw["family"],"year":raw["year"],
      "original_entry_time_utc":source["entry_time_utc"],
      "original_exit_time_label_utc":source["exit_time_utc"],
      "true_quote_entry_at_utc":datetime.fromtimestamp(start/1_000_000,UTC).isoformat(),
      "true_quote_exit_at_utc":datetime.fromtimestamp(exit_us/1_000_000,UTC).isoformat(),
      "original_source_direction":direction,
      "original_publisher_exit_reason":source["reason"],
      "raw_first_STOP_before_source_close":bool(gap_mid),
      "exit_path":"FIRST_TRUE_SOURCE_STOP_QUOTE" if stop is not None else "LAST_TRUE_SOURCE_QUOTE_IN_ORIGINAL_H1_EXIT_WINDOW",
      "original_publisher_continuous_oz":quantity,
      "original_publisher_net_usd":round(float(source["publisher_costed_usd"]),6),
      "entry_genuine_source_bid":float(entry["bid"]),
      "entry_genuine_source_ask":float(entry["ask"]),
      "exit_genuine_source_bid":float(exit_quote["bid"]),
      "exit_genuine_source_ask":float(exit_quote["ask"]),
      "source_side_entry_price":entry_fill,
      "source_side_exit_price":exit_fill,
      "source_genuine_BID_ASK_spread_entry":float(entry["ask"])-float(entry["bid"]),
      "source_genuine_BID_ASK_spread_exit":float(exit_quote["ask"])-float(exit_quote["bid"]),
      "cost_factor_slippage_and_fees":cost_factor,
      "slippage_and_fees_usd_per_oz_RT":round(cost,5),
      "source_original_frozen_cohort_repriced_usd":round(pnl,6),
      "native_broker_MT5_fill_certified":False,
      "no_original_signals_resimulated":True,
    }


def analyse(full,source):
    verify_original(full,source)
    original_source={(fam,yr,index):trade
        for fam in FAMILIES for yr in YEARS
        for index,trade in enumerate(source["cases"][fam]["periods"][yr]["trade_ledger"])}
    outcome={}
    allbase=[]
    for factor in STRESS_FACTORS:
        groups=defaultdict(list)
        for row in full["trades"]:
            original=original_source[(row["family"],row["year"],row["n"])]
            enriched=annotate_trade(row,original,factor)
            groups[(row["family"],row["year"])].append(enriched)
        block={}
        for (fam,year),items in sorted(groups.items()):
            items.sort(key=lambda r:r["original_entry_time_utc"])
            if len(items)!=source["cases"][fam]["periods"][year]["trades"]:
                raise ValueError("Original source trade population removed")
            net=sum(q["source_original_frozen_cohort_repriced_usd"] for q in items)
            wins=sum(q["source_original_frozen_cohort_repriced_usd"]>0 for q in items)
            losses=sum(q["source_original_frozen_cohort_repriced_usd"]<0 for q in items)
            grossgain=sum(max(0,q["source_original_frozen_cohort_repriced_usd"]) for q in items)
            grossloss=sum(-min(0,q["source_original_frozen_cohort_repriced_usd"]) for q in items)
            months=defaultdict(float)
            for x in items:
                m=x["true_quote_exit_at_utc"][:7]
                if not m.startswith(year):
                    # Trades close in their original independent period,
                    # including special 2026 September EOD.
                    raise ValueError("Source original quote exit escaped its study year")
                months[m]+=x["source_original_frozen_cohort_repriced_usd"]
            account=source["cases"][fam]["periods"][year]
            block[f"{fam}_{year}"]={
                "period":year,"original_preset":fam,
                "starting_usd":START_EACH,
                "original_author_trades":len(items),
                "original_publisher_python_net_usd":account["net_usd"],
                "original_source_quote_side_repriced_net_usd":round(net,2),
                "source_quote_side_repriced_end_if_original_positions_held_fixed":round(START_EACH+net,2),
                "frozen_original_cohort_source_quote_dollar_change":round(net-account["net_usd"],2),
                "wins_after_raw_quote_repricing":wins,
                "losses_after_raw_quote_repricing":losses,
                "trade_net_profit_factor_fixed_cohort":round(grossgain/grossloss,4) if grossloss else None,
                "changed_to_first_actual_stop_before_original_close":sum(
                    x["raw_first_STOP_before_source_close"] for x in items
                    if x["original_publisher_exit_reason"] not in ("sl","sl_gap")),
                "source_actual_bidask_quote_side_entry_and_exit":True,
                "modelled_slippage_commission_rt_usd_per_oz":round(factor*.27,5),
                "original_1percent_risk_recomputed_after_repriced_trades":False,
                "full_original_MT5_EA_run":False,
                "monthly_close_original_cohort":{k:round(v,2) for k,v in sorted(months.items())},
            }
            if factor==1:
                allbase.extend(items)
        outcome[str(factor)]=block
    assert len(allbase)==497
    # The issue raised by actual XAUUSD quote tape must remain explicitly.
    target=next(x for x in allbase if x["id"]=="S005-DONCHIAN-2025-0112")
    if target["exit_path"]!="FIRST_TRUE_SOURCE_STOP_QUOTE":
        raise ValueError("S005 known raw Sunday gap / omitted stop regression missing")
    out={
      "schema":"aidy.s005.497_original_source_positions_real_bidask_quote_ledger.v1",
      "actual_original_historical_BID_ASK_ticks":True,
      "original_unmodified_position_signal_strategy_source":PINNED_PUBLISHER,
      "raw_original_source_quote_first_stop_artifact_SHA256":full["sha256"],
      "prior_readonly_497_stop_probe_SHA256":ROOT_HASH,
      "original_publisher_PY_model_evidence_sha256":source["sha256"],
      "source_original_author_unchanged_frozen_positions":True,
      "original_author_shares_account_compounding_replayed":False,
      "native_MQL5_EA_executed":False,
      "broker_profit_certified":False,
      "broker_fill_slippage_and_financing_verified":False,
      "H1_decision_signal_and_order_timing_may_differ_from_MQL5":True,
      "actual_quote_side_bidask_used_at_original_trade_entry_and_exit":True,
      "source_first_real_quote_side_stop_touch_used_over_original_signal_exit":True,
      "original_source_share_of_22_original_tick_months":22,
      "original_trades_fully_revalued":len(allbase),
      "cost_model":"real original BID/ASK quotes plus 0.10 USD/oz/slippage each side, plus 0.07 USD/oz RT commission",
      "slippage_commission_factors":list(STRESS_FACTORS),
      "source_original_cohort_accounts_by_scenario":outcome,
      "original_sunday_first_stop_trade_case":target,
      "original_source_full_base_trade_ledger":allbase,
      "research_opinion":"ORANGE_NOT_QUALIFIED_NATIVE_EA_OR_SEALED_HOLDOUT",
      "high_frequency_raw_tick_quote_source_parity":True,
      "more_work_required_to_claim_native_broker_edge":True,
    }
    out["sha256"]=_digest(out)
    return out


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--actual-raw-tick-audit",type=Path,required=True)
    p.add_argument("--original-publisher",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    q=p.parse_args()
    original=json.loads(q.original_publisher.read_text())
    raw=json.loads(q.actual_raw_tick_audit.read_text())
    data=analyse(raw,original)
    q.out.mkdir(parents=True,exist_ok=True)
    (q.out/"S005_497_FIXED_COHORT_REAL_SOURCE_BIDASK_ECONOMICS.json").write_text(
        json.dumps(data,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    trade_rows=data["original_source_full_base_trade_ledger"]
    with (q.out/"S005_497_REAL_BIDASK_BROKER_SENSITIVITY_ONLY.csv").open(
         "w",newline="",encoding="utf-8") as file:
        writer=csv.DictWriter(file,fieldnames=list(trade_rows[0]))
        writer.writeheader();writer.writerows(trade_rows)
    summary=[
        "# S005 original publisher model 497 trades revalued at authentic historical raw BID/ASK quotes",
        "",
        "**Note:** This is a fixed-cohort scientific sensitivity analysis, NOT native-MT5 EA broker results, true corrected model equity or independent OOS. Original authored signals, positions, quantities and windows are frozen. First real stop quote replaces ignored bar-only exit. Full author position sizing after changes is NOT replayed.",
        "",
        "| Published source preset | Historical band | Author Python fixed-cost $ | Original positions with TRUE real quote and exit side, $0.27/oz modelled slip+fees | Further 2x slippage/fees net | 3x slippage/fees net |",
        "|---|---|---:|---:|---:|---:|"]
    for family in FAMILIES:
      for year in YEARS:
        key=f"{family}_{year}"
        a=data["source_original_cohort_accounts_by_scenario"]["1.0"][key]
        x2=data["source_original_cohort_accounts_by_scenario"]["2.0"][key]
        x3=data["source_original_cohort_accounts_by_scenario"]["3.0"][key]
        summary.append(f"| {family} | {year} | {a['original_publisher_python_net_usd']} | {a['original_source_quote_side_repriced_net_usd']} | {x2['original_source_quote_side_repriced_net_usd']} | {x3['original_source_quote_side_repriced_net_usd']} |")
    summary.extend([
      "",
      "All 497 original positions were checked against actual source raw BID/ASK at entry and exit. Short closes use observed ASK. Long opens use observed ASK. One ignored stop from Sunday 2025 December is now recognized at its actual first BID touch. Each source original archive hash and exact quote timestamp were proved by prior green workflow.",
      "No full original author-native equity, stop reentry/signals or lot-cap effects are re-propagated after the altered execution prices. The ending balance shown for frozen historical quantities is NOT a truly executable strategy account.",
      "Original MQL5 compiled EA uses bar-next-tick execution, broker point/lot/stop policies and a different session close than original author's Python research, so this is NOT official original EA parity.",
      "Financing/swaps/real Vantage commissions/real slippage/market impact and an independent sealed holdout are not verified. Owner must not promote to paper or live on this ledger.",
      "",
      "Source current real raw bidask quote-audit SHA: "+data["raw_original_source_quote_first_stop_artifact_SHA256"],
      "This model evidence SHA: "+data["sha256"],
    ])
    (q.out/"S005_REAL_QUOTE_FULL_REVALUATION_AUDIT.md").write_text(
        "\n".join(summary)+"\n",encoding="utf-8")
    print("S005_FULL_REAL_RAW_BIDASK_497_TRADE_REVALUATION",json.dumps({
        "sha256":data["sha256"],
        "trades":data["original_trades_fully_revalued"],
        "scenario_stats":data["source_original_cohort_accounts_by_scenario"],
        "native_ea_broker_certified":False,
    },sort_keys=True),flush=True)

if __name__=="__main__":main()
