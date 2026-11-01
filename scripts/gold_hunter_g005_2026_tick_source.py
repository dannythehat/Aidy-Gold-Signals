"""G005 2026 genuine tick ZIP -> BID+ASK M1, with exact prior 2026 receipts.

Fetch no market prices. Input = original already stored 2025Dec/2026Jan-Sep
HistData tick ZIP, read-only remote, with matching frozen CROSSFIRE receipts from
GitHub Actions run 38851611865. The independent original AIDY crossfire parser
is executed again and its entire historical receipt is checked against the
frozen prior CI artifact before deriving 2-sided minute bars.

No quote fabrication, future-data filling, broker order or new OOS claim.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import io
import json
import math
from datetime import UTC,datetime
from pathlib import Path
import zipfile

from aidy.strategy_lab_crossfire_tick_2021 import derive_month_zip,parse_tick

MONTHS=("202512",)+tuple(f"2026{i:02d}" for i in range(1,10))

def validate_original_source(path:Path,month:str,receipt:dict):
    if month not in MONTHS:
        raise ValueError("Unexpected source fixed-EST period")
    hourly,computed=derive_month_zip(path,month)
    fields=("source_month_fixed_est","input_zip_sha256",
            "original_csv_payload_sha256","source_tick_rows",
            "source_order_inversions","occupied_source_minutes",
            "derived_h1_sha256","normalisation","raw_source_modified")
    for key in fields:
        if receipt.get(key)!=computed.get(key):
            raise ValueError(f"Original 2026 source receipt mismatch: {key}")
    if len(hourly)<200 or receipt.get("raw_source_modified") is not False:
        raise ValueError("Invalid original 2026 source provenance")
    return computed

def minutes_from_zip(path:Path,period:str):
    rows=0
    days={}
    minute={}
    with zipfile.ZipFile(path) as zf:
        names=[name for name in zf.namelist() if name.lower().endswith(".csv")]
        if len(names)!=1: raise ValueError("More than one original source CSV")
        with zf.open(names[0]) as stream:
            for line_number,line in enumerate(
                io.TextIOWrapper(stream,encoding="utf-8-sig",newline=""),1):
                if not line.strip():continue
                epoch,micro,bid,ask=parse_tick(
                    next(csv.reader([line])),month=period,day_cache=days)
                rows+=1
                key=epoch//60*60
                order=(epoch*1_000_000+micro,line_number)
                spread=ask-bid
                item=minute.get(key)
                if item is None:
                    minute[key]={
                       "first":order,"last":order,
                       "bid_o":bid,"bid_c":bid,"bid_h":bid,"bid_l":bid,
                       "ask_o":ask,"ask_c":ask,"ask_h":ask,"ask_l":ask,
                       "ticks":1,"spread_sum":spread}
                else:
                    item["bid_h"]=max(bid,item["bid_h"])
                    item["bid_l"]=min(bid,item["bid_l"])
                    item["ask_h"]=max(ask,item["ask_h"])
                    item["ask_l"]=min(ask,item["ask_l"])
                    item["ticks"]+=1
                    item["spread_sum"]+=spread
                    if order<item["first"]:
                        item.update(first=order,bid_o=bid,ask_o=ask)
                    if order>=item["last"]:
                        item.update(last=order,bid_c=bid,ask_c=ask)
    result=[]
    for epoch,item in sorted(minute.items()):
        result.append({
          "open_time_utc":datetime.fromtimestamp(epoch,UTC).isoformat(),
          "bid_o":item["bid_o"],"bid_h":item["bid_h"],
          "bid_l":item["bid_l"],"bid_c":item["bid_c"],
          "ask_o":item["ask_o"],"ask_h":item["ask_h"],
          "ask_l":item["ask_l"],"ask_c":item["ask_c"],
          "ticks":item["ticks"],
          "spread_mean":round(item["spread_sum"]/item["ticks"],8)
        })
    if not result or sum(x["ticks"] for x in result)!=rows:
        raise ValueError("Real tick to minute reconciliation failed")
    return result,rows

def research(archive:Path,original_receipt:Path,period:str,out:Path):
    receipt=json.loads(original_receipt.read_text())
    check=validate_original_source(archive,period,receipt)
    rows,count=minutes_from_zip(archive,period)
    if count!=check["source_tick_rows"] or len(rows)!=check["occupied_source_minutes"]:
        raise ValueError("Derived M1 vs frozen original month mismatch")
    out.mkdir(parents=True,exist_ok=True)
    csvpath=out/"bidask_m1.csv"
    with csvpath.open("w",newline="",encoding="utf-8") as handle:
        writer=csv.DictWriter(handle,fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    proof={"schema":"aidy.g005.original_2026_m1.v1",
           "period_fixed_est":period,"original_archive_sha256":check["input_zip_sha256"],
           "original_source_CROSSFIRE_verified_h1_sha256":check["derived_h1_sha256"],
           "original_source_CSV_sha256":check["original_csv_payload_sha256"],
           "source_ticks":count,"original_m1_rows":len(rows),
           "m1_csv_sha256":hashlib.sha256(csvpath.read_bytes()).hexdigest(),
           "frozen_original_receipt":receipt,
           "source_modified":False,"no_broker_trades":True}
    (out/"g005_m1_receipt.json").write_text(
        json.dumps(proof,indent=2,sort_keys=True,allow_nan=False)+"\n")
    print("G005_VERIFIED_TICK_MONTH",json.dumps({
        "period":period,"ticks":count,"minutes":len(rows),
        "zip_source_sha":proof["original_archive_sha256"]},sort_keys=True),flush=True)
    return proof

if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--archive",type=Path,required=True)
    ap.add_argument("--original-receipt",type=Path,required=True)
    ap.add_argument("--period",required=True)
    ap.add_argument("--out",type=Path,required=True)
    opts=ap.parse_args()
    research(opts.archive,opts.original_receipt,opts.period,opts.out)
