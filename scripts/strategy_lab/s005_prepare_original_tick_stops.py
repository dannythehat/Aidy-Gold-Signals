"""S005 original-source 497 frozen trades -> exact point-in-time stop requests.

No original publisher trading rule changes, no invented executed order.
Author-Python's initial STOP anchored to its own BUY/SELL entry BID,
computed from pinned original engine's Wilder ATR14 at bar before entry.
Actual LONG stop should be tested against BID, SHORT stop against ASK.
Native MQL5 market entry ASK and SL anchor DIFFER: this is original-Python
fixed-stop challenge, not a compiled MT5 EA run or new native-equity model.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.strategy_lab.s005_publisher_engine_two_preset_parity import (
    PUB_COMMIT, original_modules, source_h1,
)

PARAMS={"DONCHIAN":2.5,"SESSION":3.0}
PERIODS={"2025":121+183,"2026":80+113}


def utc_epoch(value):
    t=pd.Timestamp(str(value).replace("Z","+00:00"))
    if t.tzinfo is None or t.utcoffset().total_seconds()!=0:
        raise ValueError("S005 frozen original trade instant MUST be real UTC")
    return int(t.timestamp())


def prepare(m15_root,publisher_root,original_evidence):
    if original_evidence["publisher_git_commit"]!=PUB_COMMIT:
        raise ValueError("Original publisher source SHA was changed")
    if original_evidence["fully_authenticated_22_source_months"]!=22:
        raise ValueError("S005 22 archived HistData quote months incomplete")
    if not original_evidence["publisher_python_original_executed_on_REAL_SPOT_HISTORY"]:
        raise ValueError("No completed original publisher Python source experiment")
    publisher_engine,_=original_modules(publisher_root)
    h1,receipts,historysha,h1sha,*_=source_h1(m15_root)
    if historysha!=original_evidence["all_original_m15_sha256"]:
        raise ValueError("Original full tick-derived HISTDATA historical source SHA mismatch")
    for receipt in receipts:
        if receipt.get("fixed_est_month") is None or not receipt.get("original_zip_sha256"):
            raise ValueError("Monthly original source archive ZIP SHA missing")
    atr=publisher_engine.atr(
        h1.high.to_numpy(float),h1.low.to_numpy(float),
        h1.close.to_numpy(float),14)
    requests=[]
    for fam,multiple in PARAMS.items():
        for year in PERIODS:
            old=original_evidence["cases"][fam]["periods"][year]
            if old["initial_usd"]!=10000 or old["trades"]!=len(old["trade_ledger"]):
                raise ValueError("S005 original separate 10k publisher case invalid")
            for n,t in enumerate(old["trade_ledger"]):
                start=utc_epoch(t["entry_time_utc"])
                end=utc_epoch(t["exit_time_utc"])
                loc=int(h1.index.searchsorted(pd.Timestamp(t["entry_time_utc"]).tz_convert("UTC").tz_localize(None)))
                if loc<=0 or loc>=len(h1) or h1.index[loc].timestamp()!=start:
                    raise ValueError("Original trade hour not present at complete authentic H1 opening")
                prioratr=float(atr[loc-1])
                if not np.isfinite(prioratr) or prioratr<=0:
                    raise ValueError("Publisher Wilder ATR14 missing at original entry")
                source_bid=float(t["entry_price_publisher_bid_proxy"])
                if abs(source_bid-float(h1.iloc[loc].open))>0.0001:
                    raise ValueError("Frozen original publisher entry != authentic historical H1 opening BID")
                direction=t["direction"]
                if direction not in ("LONG","SHORT"):raise ValueError("Unqualified trade direction")
                signed=1 if direction=="LONG" else -1
                stop=source_bid-signed*multiple*prioratr
                # Author engine sources initial stop from entry BID (not native
                # MT5 BUY entry ASK). For existing STOP exit tick may occur
                # anywhere within exit bar; close-of-bar signal/eod too.
                # REVERSE occurs at bar OPEN, no tick past it is eligible.
                reason=t["reason"]
                if reason not in ("signal","sl","sl_gap","eod","reverse","margin","tp","tp_gap","time","equity_stop"):
                    raise ValueError("Original source exit reason not understood")
                end_exclusive=end+(0 if reason=="reverse" else 3600)
                if end_exclusive<=start:
                    raise ValueError("Original historical period invalid for raw tick stop qualification")
                requests.append({
                   "id":f"S005-{fam}-{year}-{n:04d}",
                   "family":fam,"year":year,"n":n,
                   "start_epoch_utc":start,
                   "end_epoch_utc_exclusive":end_exclusive,
                   "original_exit_reason":reason,
                   "author_original_entry_bid":source_bid,
                   "initial_stop_at_original_python_entry":round(stop,9),
                   "original_engine_ATR14_prev_completed_H1":round(prioratr,9),
                   "original_stop_is_entry_bid_anchored_not_MT5_buy_ask":True,
                   "stop_test_quote_side":"BID" if direction=="LONG" else "ASK",
                   "direction":direction,
                   "publisher_original_net_pnl_usd":t["publisher_costed_usd"],
                 })
    expected=sum(PERIODS.values())
    if len(requests)!=expected:
        raise ValueError(f"Expected all {expected} original publisher trade windows")
    payload={
      "schema":"aidy.s005.source_pinned_497_original_stop_tick_request.v1",
      "original_python_engine_commit":PUB_COMMIT,
      "publisher_history_evidence_sha256":original_evidence["sha256"],
      "qualified_m15_histdata_source_sha256":historysha,
      "completed_history_h1_sha256":h1sha,
      "real_source_original_monthly_zip_receipts":[{
         "source_period":r["fixed_est_month"],
         "sha256_original_zip":r["original_zip_sha256"]
       } for r in receipts],
      "publisher_model_vs_compiled_MT5_must_NOT_be_equated":True,
      "initial_stops_from_unmodified_author_engine":True,
      "requests":requests,
    }
    payload["sha256"]=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(",",":"),
        allow_nan=False).encode()).hexdigest()
    return payload


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--source-root",required=True,type=Path)
    ap.add_argument("--publisher-root",required=True,type=Path)
    ap.add_argument("--original-evidence",required=True,type=Path)
    ap.add_argument("--out",required=True,type=Path)
    a=ap.parse_args()
    data=prepare(a.source_root,a.publisher_root,json.loads(a.original_evidence.read_text()))
    a.out.mkdir(parents=True,exist_ok=True)
    (a.out/"S005_497_SOURCE_FROZEN_ORIGINAL_TICK_STOP_REQUESTS.json").write_text(
       json.dumps(data,sort_keys=True,indent=2)+"\n")
    print("S005_ORIGINAL_497_STOP_REQUESTS_VERIFIED",json.dumps({
       "count":len(data["requests"]), "sha256":data["sha256"],
       "original_source_months":len(data["real_source_original_monthly_zip_receipts"]),
       "computed_stops_from_author_original_atr":True,
       "MT5_native_verified":False},sort_keys=True),flush=True)

if __name__=="__main__":main()
