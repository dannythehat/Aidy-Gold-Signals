"""S005-C original 2x$5000 real-source BID/ASK historical quote-side overlay.

Matches EACH $5000 original Python model trade to the corresponding immutable
$10000 original source raw BID+ASK first entry/first stop/actual exit quote.
Original publisher 2025 and 2026 source original unmodified rules scale exactly
when reducing capital by 50% because author model uses homogeneous position
sizing. This overlay REPLACES the quote-side flat assumption on the ORIGINAL
C parallel source trade cohort ONLY and preserves each 5k position size.

It is NOT a new broker-native C simulation, not a compounded account with
sizing updated after different real fills, not suitable for variant D.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path

STRESS_FACTORS=("1.0","2.0","3.0")
FAMILIES=("DONCHIAN","SESSION")
YEARS=("2025","2026")


def sha(obj):
    return hashlib.sha256(json.dumps(obj,sort_keys=True,separators=(",",":"),
                            allow_nan=False).encode()).hexdigest()


def match_key(family,year,entry,exit_,direction):
    return (family,year,entry,exit_,"LONG" if direction=="BUY" else "SHORT")


def derive(source,s005c):
    if source["schema"]!="aidy.s005.497_original_source_positions_real_bidask_quote_ledger.v1":
        raise ValueError("Original source actual BID ASK quote ledger type changed")
    if source["original_trades_fully_revalued"]!=497 or source["native_MQL5_EA_executed"]:
        raise ValueError("Missing original 497 authentic quote-side histories")
    if source["sha256"]!=sha({k:v for k,v in source.items() if k!="sha256"}):
        raise ValueError("Original source quote-side evidence changed")
    if not s005c["sum_allocations_equal_one_account"] or (s005c["account_total_usd"],
            s005c["donchian_capital_usd"],s005c["session_capital_usd"])!=(10000,5000,5000):
        raise ValueError("S005-C original 2x5000 account was not really funded")
    if not s005c["true_original_source_signal_rules_unchanged_in_C"]:
        raise ValueError("Do not map a new hybrid's trades to original historical cohort")
    if s005c["sha256"]!=sha({k:v for k,v in s005c.items() if k!="sha256"}):
        raise ValueError("Combined one $10k account evidence digest changed")
    if s005c["publisher_source_commit"]!=source["original_unmodified_position_signal_strategy_source"]:
        raise ValueError("S005 source author version mismatch")
    by_stress={}
    for factor in STRESS_FACTORS:
        # quote stress changes ONLY constant slippage+commission, keeps
        # original entry and first original raw stop crossing prices.
        rows=source["original_source_full_base_trade_ledger"]
        baseline={match_key(t["family"],t["year"],t["original_entry_time_utc"],
                     t["original_exit_time_label_utc"],
                     "BUY" if t["original_source_direction"]=="LONG" else "SELL"):t for t in rows}
        if len(baseline)!=497:raise ValueError("Frozen source quote row join duplicates")
        matched=[]
        totals={}
        for year in YEARS:
            original_C=s005c["two_period_results"][year]["S005_C_PARALLEL"]
            source_trades=original_C["merged_source_trade_ledger"]
            merged=[]
            unique=set()
            for item in source_trades:
                key=match_key(item["source_strategy"],year,item["entry_utc"],
                         item["exit_utc"],item["direction"])
                if key not in baseline or key in unique:
                    raise ValueError("Original $5k portfolio event has no unique authenticated source raw BID/ASK quote")
                unique.add(key)
                old=baseline[key]
                size5k=float(item["original_author_python_units_oz"])
                size10k=float(old["original_publisher_continuous_oz"])
                if size5k<=0 or abs(size5k*2-size10k)>0.000001:
                    raise ValueError("Actual original publisher 5k vs 10k units are NOT proportional, cannot port economic quote side")
                direction=1 if item["direction"]=="BUY" else -1
                price_delta=direction*(float(old["source_side_exit_price"])-float(old["source_side_entry_price"]))
                extra=.27*float(factor)
                adjusted=round(size5k*(price_delta-extra),6)
                market_original=float(item["author_source_PY_model_net_usd"])
                original10k=float(old["original_publisher_net_usd"])
                if abs(market_original*2-original10k)>0.00015:
                    raise ValueError("Not exactly source-comparable publisher original trading unit economics")
                merged.append({
                   "year":year,"mode":"S005_C_PARALLEL",
                   "source_sleeve":item["source_strategy"],
                   "entry_time_original_utc":item["entry_utc"],
                   "exit_time_original_utc":item["exit_utc"],
                   "direction":item["direction"],
                   "genuine_source_bidask_entry_price":float(old["source_side_entry_price"]),
                   "genuine_source_bidask_exit_price":float(old["source_side_exit_price"]),
                   "risk_sleeve_usd_initial":5000,
                   "original_publisher_continuous_ounces_5k":size5k,
                   "publisher_PY_original_model_net_5k":round(market_original,6),
                   "source_raw_BIDASK_adjusted_net_5k_usd":adjusted,
                   "real_stop_before_publisher_signal_exit":bool(old["raw_first_STOP_before_source_close"]),
                   "assumed_extra_slippage_and_fees_RT_per_oz":extra,
                   "true_independently_funded_BROKER_acct_profit":False,
                })
            matched.extend(merged)
            total=round(sum(t["source_raw_BIDASK_adjusted_net_5k_usd"] for t in merged),2)
            source_orig=original_C["master_realized_PY_model_net_usd"]
            original_based_on_10k=source["source_original_cohort_accounts_by_scenario"][factor]
            expected=round((original_based_on_10k["DONCHIAN_"+year]["original_source_quote_side_repriced_net_usd"]+
                            original_based_on_10k["SESSION_"+year]["original_source_quote_side_repriced_net_usd"])/2,2)
            if abs(total-expected)>.03:
                raise ValueError("2x5000 authentic original source BID ASK results do not agree with scaling of 2 original source 10k models")
            per={family:round(sum(x["source_raw_BIDASK_adjusted_net_5k_usd"]
                    for x in merged if x["source_sleeve"]==family),2)
                 for family in FAMILIES}
            if abs(sum(per.values())-total)>.02:
                raise ValueError("Source per-engine portfolio PnL does not reconcile")
            totals[year]={
               "variant":"S005_C_PARALLEL",
               "starting_master_usd":10000,
               "sleeve_allocation_each_usd":5000,
               "original_PY_2x5000_model_net_usd":source_orig,
               "real_source_BIDASK_fixed_original_5k_cohort_net_usd":total,
               "raw_quote_provisional_PnL_change_usd":round(total-source_orig,2),
               "DONCHIAN_raw_quote_source_PnL_usd":per["DONCHIAN"],
               "SESSION_raw_quote_source_PnL_usd":per["SESSION"],
               "total_frozen_original_PY_trades":len(merged),
               "native_1_account_model_run_with_updated_fills":False,
               "can_admit_to_goldthinker_paper_live":False,
            }
        if len(matched)!=497:raise ValueError("Original $5k each source market coverage not all 497 trades")
        by_stress[factor]={"periods":totals,"all_matching_original_5k_trade_quotes":matched}
    packet={
      "schema":"aidy.s005c.real_source_BIDASK_two_5000_original_combined_quote_overlay.v1",
      "source_quote_economic_receipt_sha256":source["sha256"],
      "source_original_two_5000_portfolio_sha256":s005c["sha256"],
      "genuine_original_histdata_source_bidask_quote_used":True,
      "original_author_original_gold_rule_UNMODIFIED_for_C":True,
      "all_original_source_python_position_sizes_halved_and_matched_to_raw_history":True,
      "original_source_497_event_coverage":497,
      "a_single_virtual_wallet_usd":10000,
      "donchian_initial_capital_usd":5000,
      "session_initial_capital_usd":5000,
      "hybrid_D_quote_side_ledger_qualified":False,
      "actual_native_MT5_strategy_tester_original_EA_executed":False,
      "source_true_BIDASK_cost_stress_is_not_new_compounded_portfolio":True,
      "risk_actual_broker_symbol_point_and_swap_UNVERIFIED":True,
      "original_PY_2025_and_2026_were_inspected_not_virgin_holdout":True,
      "cost_factor_scenarios":by_stress,
    }
    packet["sha256"]=sha(packet)
    return packet


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--combined-portfolio",type=Path,required=True)
    p.add_argument("--original-10k-raw-quotes",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    x=p.parse_args()
    s005c=json.loads(x.combined_portfolio.read_text())
    source=json.loads(x.original_10k_raw_quotes.read_text())
    evidence=derive(source,s005c)
    x.out.mkdir(parents=True,exist_ok=True)
    (x.out/"S005C_2x5000_REAL_BIDASK_ORIGINAL_C_STRESS.json").write_text(
          json.dumps(evidence,indent=2,sort_keys=True,allow_nan=False)+"\n")
    with (x.out/"S005C_2x5000_REAL_BIDASK_C_PUBLISHED_497_TRADES.csv").open(
         "w",newline="") as file:
        all_rows=evidence["cost_factor_scenarios"]["1.0"]["all_matching_original_5k_trade_quotes"]
        writer=csv.DictWriter(file,fieldnames=list(all_rows[0]))
        writer.writeheader();writer.writerows(all_rows)
    for factor in STRESS_FACTORS:
        for year in YEARS:
            v=evidence["cost_factor_scenarios"][factor]["periods"][year]
            print("S005C_2X5000_ACTUAL_ORIGINAL_RAW_BIDASK_STRESS",json.dumps({
               "stress":factor,"year":year,
               "combined_net":v["real_source_BIDASK_fixed_original_5k_cohort_net_usd"],
               "donchian":v["DONCHIAN_raw_quote_source_PnL_usd"],
               "session":v["SESSION_raw_quote_source_PnL_usd"],
               "model_not_MT5_compounded":True
            },sort_keys=True),flush=True)
    print("S005C_REAL_QUOTE_SIDE_ORIGINAL_SOURCE_VERIFIED",evidence["sha256"])


if __name__=="__main__":main()
