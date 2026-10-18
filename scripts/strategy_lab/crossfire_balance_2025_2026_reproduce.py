"""Reproduce owner's CROSSFIRE hourly-state research with archived genuine 2025/26 BID H1.

Never ingest 2020 or 2021. Reads only two immutable prior GHA artifact CSVs.
This is historical research and creates no broker or paper orders.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd
from aidy.strategy_lab_crossfire_balanced_guard import VERSIONS, replay
from aidy.strategy_lab_s010_backtest import BASE, ORIGINAL_LEVERAGE, simulate
from aidy.strategy_lab_nursery_refinement import write_bundle
from aidy.strategy_lab_goldthinker_balanced_policy import (
    select_crossfire_platform_version, selection_markdown,
)

FROZEN={
  "2025":{"original":(15032.76,-33.671),"prior_entry_only_half_guard":(7641.47,-32.557),
     "hourly_state_half_new":(10048.65,-22.072),"gentle_three_quarter_new":(12528.68,-27.955),
     "half_new_plus_open_trim":(11306.03,-16.159)},
  "2026":{"original":(8573.74,-44.068),"prior_entry_only_half_guard":(9312.,-24.901),
     "hourly_state_half_new":(10542.25,-28.828),"gentle_three_quarter_new":(9587.42,-36.749),
     "half_new_plus_open_trim":(5790.53,-19.847)},
}
OBS_ASK_2026={
    "original":(8145.56,-44.519),"prior_entry_only_half_guard":(9021.23,-25.201),
    "hourly_state_half_new":(10244.60,-29.115),"gentle_three_quarter_new":(9219.63,-37.132),
    "half_new_plus_open_trim":(5570.33,-20.300),
}

def run(h1_2025:Path,h1_2026:Path,out:Path)->dict:
    evidence={"method":"CROSSFIRE_RISK_BALANCE_H1_SOURCED_2025_2026_v1",
              "status":"HISTORICAL_RESEARCH_NO_PAPER_ORDERS", "source_years":[2025,2026],
              "excluded_years":[2020,2021], "modelled_vantage_costs_verified":False,
              "broker_swaps_and_margin_stopout_modelled":False,"no_optimization_claimed":True,
              "years":{}}
    for year,source in [(2025,h1_2025),(2026,h1_2026)]:
        if not source.is_file():raise ValueError("Missing authenticated historical source artifact "+str(year))
        h=pd.read_csv(source)
        if len(h)<4000:raise ValueError("Insufficient source H1 rows")
        result={k:replay(h,k) for k in VERSIONS}
        assert set(result)==set(FROZEN[str(year)])
        for k,res in result.items():
            if (res["profit_usd"],res["max_dd_pct"])!=FROZEN[str(year)][k]:
                raise ValueError(f"{year} {k}: regression drift or source mismatch")
        original=simulate(h, ORIGINAL_LEVERAGE, BASE)
        if (result["original"]["end_equity_usd"]!=original["ending_marked_equity_usd"]
            or result["original"]["max_dd_pct"]!=original["max_marked_drawdown_pct"]):
            raise ValueError("Frozen original 2025/2026 trading-rule parity failed")
        scenarios={"assumed_bid_ask":result}
        if year==2026:
            observed={k:replay(h,k,"observed_histdata_ask") for k in VERSIONS}
            for k,res in observed.items():
                if (res["profit_usd"],res["max_dd_pct"])!=OBS_ASK_2026[k]:
                    raise ValueError("Historic ASK scenario mismatch: "+k)
            scenarios["observed_histdata_ask"] = observed
        evidence["years"][str(year)]={"h1_rows":len(h),"source_csv_sha256":hashlib.sha256(source.read_bytes()).hexdigest(),"scenarios":scenarios}
    out.mkdir(parents=True,exist_ok=True)
    (out/'crossfire_risk_balance_reproduced.json').write_text(json.dumps(evidence,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    # Produce actual internal report footer + standalone private System Builder handover.
    # A report cannot approve trading or publication.
    nursery = write_bundle(evidence, out)
    # Owner's platform choice is a separate read-only overlay on immutable research.
    # This does not authorize connection, account funding, demo orders or publication.
    selection = select_crossfire_platform_version(nursery)
    (out / 'goldthinker_platform_version_selection.json').write_text(
        json.dumps(selection, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    (out / 'goldthinker_platform_version_selection.md').write_text(
        selection_markdown(selection, nursery), encoding='utf-8')
    print("GOLDTHINKER_CROSSFIRE_BALANCED_VERSION_SELECTED", json.dumps({
        "version": selection["owner_selection"],
        "owner_decision": selection["owner_decision_date"],
        "research_original_preserved": True,
        "research_sha": selection["underlying_historical_packet_sha256"],
        "selection_sha": selection["selection_record_sha256"],
        "paper_execution_authorised": False,
        "customer_copy_authorised": False,
    }, sort_keys=True), flush=True)
    print("CROSSFIRE_PRIVATE_NURSERY_PACKAGE_WRITTEN", json.dumps({
        "status": "AWAITING_OWNER_VERSION_DECISION",
        "candidate": nursery["system_id"],
        "proposed_compromise": nursery["proposed_compromise"],
        "source_digest": nursery["source_packet_sha256"],
        "package_digest": nursery["draft_sha256"],
        "paper_trading_authorised": False,
    }, sort_keys=True), flush=True)
    print("CROSSFIRE_BALANCED_RISK_SOURCE_REPRODUCED",json.dumps({
        yr:{"2025_or_2026":yr, "original_profit":case["scenarios"]["assumed_bid_ask"]["original"]["profit_usd"],
            "hourly_guard_profit":case["scenarios"]["assumed_bid_ask"]["hourly_state_half_new"]["profit_usd"],
            "hourly_guard_dd":case["scenarios"]["assumed_bid_ask"]["hourly_state_half_new"]["max_dd_pct"]}
        for yr,case in evidence['years'].items()},sort_keys=True),flush=True)
    return evidence

if __name__=='__main__':
    cli=argparse.ArgumentParser()
    cli.add_argument('--h1-2025',type=Path,required=True)
    cli.add_argument('--h1-2026',type=Path,required=True)
    cli.add_argument('--out',type=Path,default=Path('artifacts/strategy_lab/crossfire_balance'))
    a=cli.parse_args()
    run(a.h1_2025,a.h1_2026,a.out)
