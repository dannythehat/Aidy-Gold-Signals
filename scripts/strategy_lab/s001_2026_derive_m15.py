"""S001: derive causal M15 original BID/ASK from unmodified R2 tick ZIP.

One month per invocation, verified against source SHA and UTC row geometry.
Source clocks are fixed EST UTC-05, identical to AIDY CROSSFIRE parser.
No trades or uploaded source archives are modified.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import zipfile
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from aidy.strategy_lab_crossfire_tick_2021 import parse_tick


def derive(archive: Path, period: str) -> tuple[list[dict], dict]:
    if len(period)!=6 or not period.isdigit() or not 2020<=int(period[:4])<=2030 or not 1<=int(period[4:])<=12:
        raise ValueError("Source archive period must be YYYYMM")
    sha=hashlib.sha256(archive.read_bytes()).hexdigest()
    minutes={}
    day_cache={}
    previous=None
    count=0
    inversions=0
    payload_digest=hashlib.sha256()
    with zipfile.ZipFile(archive) as z:
        files=[x for x in z.namelist() if x.lower().endswith(".csv")]
        if len(files)!=1:
            raise ValueError("Original HistData archive must have one CSV")
        with z.open(files[0]) as binary:
            for block in iter(lambda: binary.read(1024*1024),b""):
                payload_digest.update(block)
        with z.open(files[0]) as binary:
            for line_no,line in enumerate(io.TextIOWrapper(binary,encoding="utf-8-sig"),1):
                if not line.strip():
                    continue
                epoch,micro,bid,ask=parse_tick(
                    next(csv.reader([line])),month=period,day_cache=day_cache)
                tick=epoch*1000000+micro
                if previous is not None and tick<previous:
                    inversions+=1
                previous=tick
                count+=1
                minute=(epoch//60)*60
                item=minutes.get(minute)
                order=(tick,line_no)
                if item is None:
                    minutes[minute]={
                        "first":order,"last":order,"open_bid":bid,
                        "close_bid":bid,"high_bid":bid,"low_bid":bid,
                        "open_ask":ask,"max_spread":ask-bid,"source_ticks":1,
                    }
                else:
                    item["source_ticks"]+=1
                    item["high_bid"]=max(item["high_bid"],bid)
                    item["low_bid"]=min(item["low_bid"],bid)
                    item["max_spread"]=max(item["max_spread"],ask-bid)
                    if order<item["first"]:
                        item["first"]=order
                        item["open_bid"]=bid
                        item["open_ask"]=ask
                    if order>=item["last"]:
                        item["last"]=order
                        item["close_bid"]=bid
    if count<1000 or not minutes:
        raise ValueError("Insufficient original market source")
    grouped=defaultdict(list)
    for k,item in minutes.items():
        grouped[(k//900)*900].append((k,item))
    m15=[]
    excluded=0
    for epoch,parts in sorted(grouped.items()):
        parts.sort(key=lambda x:x[0])
        if len(parts)!=15 or any(key!=epoch+i*60 for i,(key,_) in enumerate(parts)):
            excluded+=1
            continue
        first=parts[0][1]
        last=parts[-1][1]
        m15.append({
            "open_time_utc":datetime.fromtimestamp(epoch,UTC).isoformat(),
            "open":first["open_bid"],
            "high":max(v["high_bid"] for _,v in parts),
            "low":min(v["low_bid"] for _,v in parts),
            "close":last["close_bid"],
            "m1_count":15,
            "volume":sum(v["source_ticks"] for _,v in parts),
            "observed_open_ask":first["open_ask"],
            "observed_open_spread":first["open_ask"]-first["open_bid"],
            "observed_max_spread":max(v["max_spread"] for _,v in parts),
        })
    if len(m15)<750:
        raise ValueError("Insufficient source-derived complete M15 bars")
    digest=hashlib.sha256(json.dumps(m15,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    receipt={
        "fixed_est_month":period,"original_zip_sha256":sha,
        "payload_sha256":payload_digest.hexdigest(),
        "source_tick_rows":count,"source_tick_inversions":inversions,
        "unique_minutes":len(minutes),"complete_m15":len(m15),
        "excluded_partial_m15":excluded,"derived_m15_sha256":digest,
        "source_clock":"EST_FIXED_UTC_MINUS_05",
        "original_zip_modified":False,"native_mt5_volume_available":False,
        "actual_broker_fill_verified":False,
    }
    return m15,receipt


def main():
    cli=argparse.ArgumentParser()
    cli.add_argument("--period",required=True)
    cli.add_argument("--archive",type=Path,required=True)
    cli.add_argument("--output",type=Path,required=True)
    args=cli.parse_args()
    bars,receipt=derive(args.archive,args.period)
    args.output.mkdir(parents=True,exist_ok=True)
    with (args.output/"m15.csv").open("w",newline="",encoding="utf-8") as f:
        writer=csv.DictWriter(f,fieldnames=list(bars[0]))
        writer.writeheader()
        writer.writerows(bars)
    (args.output/"receipt.json").write_text(
        json.dumps(receipt,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print("S001_2026_ORIGINAL_M15",json.dumps(receipt,sort_keys=True),flush=True)


if __name__=="__main__":
    main()
