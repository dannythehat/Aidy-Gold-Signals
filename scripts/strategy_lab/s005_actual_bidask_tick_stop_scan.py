"""S005 scan ORIGINAL monthly HistData raw BID/ASK tick ZIP chronologically.

Does not infer ASK from BID candles; uses the unmodified original ASK field
and preserves first raw quote crossing every frozen publisher-Python stop.
Sorted within the original source minute by exact microsecond timestamp;
a backward jump to a prior minute is a HARD ERROR, not silently reordered.

Actual original publisher *Python* stops only; original compiled MQL5 EA
uses different ASK entry anchoring, broker point/slippage/freeze constraints.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import zipfile
from pathlib import Path

from aidy.strategy_lab_crossfire_tick_2021 import parse_tick


def _digest_sha(obj):
    return hashlib.sha256(json.dumps(obj,sort_keys=True,
        separators=(",",":"),allow_nan=False).encode()).hexdigest()


def source_month_scan(path:Path,period:str,manifest:dict):
    if manifest["schema"]!="aidy.s005.source_pinned_497_original_stop_tick_request.v1":
        raise ValueError("Unexpected or unsigned original publisher stop manifest")
    supplied=manifest["sha256"]
    copy={k:v for k,v in manifest.items() if k!="sha256"}
    if supplied!=_digest_sha(copy):
        raise ValueError("Tampered original source stop eligibility manifest")
    receipts={r["source_period"]:r["sha256_original_zip"]
              for r in manifest["real_source_original_monthly_zip_receipts"]}
    if period not in receipts or len(receipts)!=22:
        raise ValueError("Unqualified monthly source period")
    actual=hashlib.sha256(path.read_bytes()).hexdigest()
    if actual!=receipts[period]:
        raise ValueError("Original upstream XAUUSD HISTDATA raw tick ZIP SHA mismatch")
    requests=sorted(manifest["requests"],key=lambda x:(x["start_epoch_utc"],x["id"]))
    if len(requests)!=497 or len(set(x["id"] for x in requests))!=497:
        raise ValueError("Original publisher 497 immutable positions lost or duplicated")
    states={}
    # states per ORIGINAL trade active within THIS month only. Merging months
    # uses exact source quote instant ordering and original source hash.
    open_cursor=0
    active={}
    observed_rows=0
    inversions_within_minute=0
    prior_minute=None
    pending_minute=None
    buffer=[]
    day_cache={}

    def accept(epoch,micro,bid,ask,lineno):
        nonlocal open_cursor,observed_rows
        when=epoch*1_000_000+micro
        while open_cursor<len(requests) and requests[open_cursor]["start_epoch_utc"]*1_000_000<=when:
            q=requests[open_cursor]
            if when<q["end_epoch_utc_exclusive"]*1_000_000:
                active[q["id"]]=q
            open_cursor+=1
        for rid in list(active):
            if when>=active[rid]["end_epoch_utc_exclusive"]*1_000_000:
                del active[rid]
        if not active:return
        for rid,q in active.items():
            state=states.setdefault(rid,{
                "id":rid,"entry_quote":None,
                "first_source_stop_crossing":None,
                "source_quotes_in_original_trade_window":0,
            })
            state["source_quotes_in_original_trade_window"]+=1
            if state["entry_quote"] is None:
                state["entry_quote"]={
                  "instant_epoch_us":when,"bid":bid,"ask":ask,
                  "source_zip_period_fixed_EST":period,"source_line":lineno,
                }
            crossed=(bid<=q["initial_stop_at_original_python_entry"]
                     if q["stop_test_quote_side"]=="BID" else
                     ask>=q["initial_stop_at_original_python_entry"])
            if crossed and state["first_source_stop_crossing"] is None:
                state["first_source_stop_crossing"]={
                   "instant_epoch_us":when,"bid":bid,"ask":ask,
                   "price_used":bid if q["stop_test_quote_side"]=="BID" else ask,
                   "side":q["stop_test_quote_side"],
                   "original_python_stop":q["initial_stop_at_original_python_entry"],
                   "source_zip_period_fixed_EST":period,
                   "source_line":lineno,
                }

    def flush():
        nonlocal buffer,inversions_within_minute
        if not buffer:return
        if any(buffer[k][0]<buffer[k-1][0] for k in range(1,len(buffer))):
            inversions_within_minute+=1
        for tickkey,lineno,epoch,micro,bid,ask in sorted(buffer,key=lambda v:(v[0],v[1])):
            accept(epoch,micro,bid,ask,lineno)
        buffer=[]

    with zipfile.ZipFile(path) as z:
        names=[n for n in z.namelist() if n.lower().endswith(".csv")]
        if len(names)!=1:raise ValueError("Original HISTDATA tick monthly ZIP not one CSV")
        with z.open(names[0]) as binary:
            for lineno,line in enumerate(io.TextIOWrapper(binary,encoding="utf-8-sig",newline=""),1):
                if not line.strip():continue
                epoch,micro,bid,ask=parse_tick(
                    next(csv.reader([line])),month=period,day_cache=day_cache)
                observed_rows+=1
                minute=(epoch//60)*60
                if prior_minute is not None and minute<prior_minute:
                    raise ValueError("Source HISTDATA minute chronology inverted; cannot assert event first without full sort")
                prior_minute=minute
                if pending_minute is not None and minute!=pending_minute:
                    flush()
                pending_minute=minute
                buffer.append((epoch*1_000_000+micro,lineno,epoch,micro,bid,ask))
        flush()
    if observed_rows<20000:raise ValueError("Original source tick file far too short")
    data={
      "schema":"aidy.s005.original_source_bidask_stop_events_month.v1",
      "period":period,"original_tick_zip_sha256":actual,
      "original_stop_requests_sha256":supplied,
      "original_tick_rows_processed":observed_rows,
      "source_minutes_with_out_of_order_micros":inversions_within_minute,
      "trade_ids_covered_with_quotes":len(states),
      "market_side":"original BID/ASK from authentic HistData source",
      "not_native_MT5_deal_or_equity":True,
      "states":list(states.values()),
    }
    data["sha256"]=_digest_sha(data)
    return data


def aggregate(manifest:dict,monthly:list[dict]):
    if len(monthly)!=22 or len(set(x["period"] for x in monthly))!=22:
        raise ValueError("Missing original months or repeated source archive")
    if set(x["period"] for x in monthly)!={r["source_period"]
           for r in manifest["real_source_original_monthly_zip_receipts"]}:
        raise ValueError("Different monthly quote source from source-pinned original stop manifest")
    if any(m["original_stop_requests_sha256"]!=manifest["sha256"] for m in monthly):
        raise ValueError("Different stop policy applied across original market months")
    requests={r["id"]:r for r in manifest["requests"]}
    collected={rid:[] for rid in requests}
    for m in monthly:
        for item in m["states"]:
            if item["id"] not in collected:raise ValueError("Unrecognised original publisher trade identifier")
            collected[item["id"]].append(item)
    final=[]
    missed_quote=0
    first_stops=0
    early_stops=0
    original_reported_stops=0
    original_sl_without_true_raw_cross=0
    for rid,q in requests.items():
        fragments=collected[rid]
        entry=min((frag["entry_quote"] for frag in fragments
                   if frag["entry_quote"] is not None),
                  key=lambda x:x["instant_epoch_us"],default=None)
        crossing=min((frag["first_source_stop_crossing"] for frag in fragments
                      if frag["first_source_stop_crossing"] is not None),
                     key=lambda x:x["instant_epoch_us"],default=None)
        volume=sum(x["source_quotes_in_original_trade_window"] for x in fragments)
        if entry is None:missed_quote+=1
        if entry is not None and abs(entry["bid"]-q["author_original_entry_bid"])>0.0001:
            # THE ORIGINAL SOURCE AT H1 OPEN must equal same first raw tick bid.
            raise ValueError("First true source raw tick BID != original author H1 opening BID "+rid)
        original_stop=q["original_exit_reason"] in ("sl","sl_gap")
        if original_stop:original_reported_stops+=1
        if crossing is not None:first_stops+=1
        if original_stop and crossing is None:original_sl_without_true_raw_cross+=1
        if not original_stop and crossing is not None:early_stops+=1
        final.append({
           **q,"first_original_entry_raw_tick":entry,
           "first_true_quote_side_stop_crossing":crossing,
           "observed_tick_quotes_during_original_author_trade":volume,
           "author_exit_reported_stop":original_stop,
           "any_original_market_side_quote_stop_crossing":crossing is not None,
           "evidence_is_live_broker_MT5_parity":False
        })
    if missed_quote:
        raise ValueError(f"Raw tick data missing quote at {missed_quote} original publisher trade entries")
    out={
      "schema":"aidy.s005.full_497_original_source_actual_tick_bidask_stop_parity.v1",
      "source_stop_request_sha256":manifest["sha256"],
      "month_receipts":[{"period":x["period"],"zip_sha256":x["original_tick_zip_sha256"],
         "tick_rows":x["original_tick_rows_processed"],"qualified_sha":x["sha256"],
         "minute_microorder_inversions":x["source_minutes_with_out_of_order_micros"]} for x in monthly],
      "original_publisher_model_trades":len(final),
      "source_raw_tick_coverage_original_entries":len(final)-missed_quote,
      "original_reported_model_stop_exits":original_reported_stops,
      "source_quote_side_stop_crossings_within_original_trade_windows":first_stops,
      "model_nonstop_exits_with_a_true_quote_side_crossing_before_model_exit":early_stops,
      "original_reported_stop_exits_without_matching_real_quote_crossing":original_sl_without_true_raw_cross,
      "long_stop_test_side":"BID",
      "short_stop_test_side":"ASK",
      "no_original_compiled_MT5_signal_order_parity":True,
      "positions_and_stops_are_frozen_author_python_not_native_MT5_ask_anchor":True,
      "not_a_cash_pnl_or_broker_fill_simulation":True,
      "not_an_untouched_OOS":True,
      "trades":final,
    }
    out["sha256"]=_digest_sha(out)
    return out


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--manifest",type=Path,required=True)
    ap.add_argument("--archive",type=Path)
    ap.add_argument("--period")
    ap.add_argument("--monthly-root",type=Path)
    ap.add_argument("--out",type=Path,required=True)
    a=ap.parse_args()
    manifest=json.loads(a.manifest.read_text())
    a.out.mkdir(parents=True,exist_ok=True)
    if a.archive is not None and a.period is not None and a.monthly_root is None:
        m=source_month_scan(a.archive,a.period,manifest)
        (a.out/("S005_RAW_BIDASK_STOP_EVENTS_"+a.period+".json")).write_text(
            json.dumps(m,indent=2,sort_keys=True)+"\n")
        print("S005_RAW_MONTH_REAL_TICK_STOP_EVENTS",json.dumps({
            "period":a.period,"rows":m["original_tick_rows_processed"],
            "trades_touched":m["trade_ids_covered_with_quotes"],
            "sha256":m["sha256"]},sort_keys=True),flush=True)
    elif a.archive is None and a.period is None and a.monthly_root is not None:
        monthly=[json.loads(p.read_text()) for p in
                 sorted(a.monthly_root.rglob("S005_RAW_BIDASK_STOP_EVENTS_*.json"))]
        for m in monthly:
            supplied=m["sha256"]
            candidate={k:v for k,v in m.items() if k!="sha256"}
            if supplied!=_digest_sha(candidate):
                raise ValueError("Tampered monthly real source tick event receipt")
        full=aggregate(manifest,monthly)
        (a.out/"S005_ALL497_REAL_TICK_BIDASK_STOP_EVENTS.json").write_text(
            json.dumps(full,sort_keys=True,indent=2)+"\n")
        with (a.out/"S005_ALL497_BIDASK_TICK_STOP_COMPARE.csv").open("w",newline="") as out:
            names=["id","family","year","n","direction","original_exit_reason",
                "initial_stop_at_original_python_entry","author_original_entry_bid",
                "first_entry_ask","first_raw_stop_epoch_us","first_raw_stop_side_quote",
                "any_original_market_side_quote_stop_crossing",
                "observed_tick_quotes_during_original_author_trade"]
            w=csv.DictWriter(out,fieldnames=names);w.writeheader()
            for row in full["trades"]:
                e=row["first_original_entry_raw_tick"] or {}
                h=row["first_true_quote_side_stop_crossing"] or {}
                w.writerow({**{k:row.get(k,"") for k in names},
                  "first_entry_ask":e.get("ask",""),
                  "first_raw_stop_epoch_us":h.get("instant_epoch_us",""),
                  "first_raw_stop_side_quote":h.get("price_used","")})
        print("S005_ALL497_RAW_TICK_FIRST_STOP_REPLAY_RECONCILED",json.dumps({
            "publisher_entries":full["original_publisher_model_trades"],
            "source_raw_entries":full["source_raw_tick_coverage_original_entries"],
            "model_stop_exits":full["original_reported_model_stop_exits"],
            "market_side_true_stop_events":full["source_quote_side_stop_crossings_within_original_trade_windows"],
            "nonstop_model_exit_but_true_side_stop_cross":full["model_nonstop_exits_with_a_true_quote_side_crossing_before_model_exit"],
            "sha256":full["sha256"],
            "MT5_native_parity":False
        },sort_keys=True),flush=True)
    else:raise ValueError("Choose original monthly archive+period OR 22 month-outputs root")


if __name__=="__main__":main()
