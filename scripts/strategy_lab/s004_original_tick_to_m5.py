"""S004 unmodified XAUUSD original HistData BID/ASK tick ZIP -> complete M5.

Identical original market archives used for S001/2/3, but S004 author
trades M5, so the source MUST be rebuilt at genuine M5, never scaled
from M15. Returns original-source SHA, clock, bid OHLC, observed first
ASK and exact source tick counts. No fabricated missing bars or fills.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from aidy.strategy_lab_crossfire_tick_2021 import parse_tick


def original_tick_m5(archive: Path, period: str):
    if period not in (["202412"]+[f"2025{x:02d}" for x in range(1,13)]+[f"2026{x:02d}" for x in range(1,10)]):
        raise ValueError("S004 original archive period invalid")
    sha=hashlib.sha256(archive.read_bytes()).hexdigest()
    minutes={}
    day_cache={}
    ticks=0
    inversion=0
    prev_ts=None
    with zipfile.ZipFile(archive) as z:
        files=[n for n in z.namelist() if n.lower().endswith(".csv")]
        if len(files)!=1:raise ValueError("HistData original ZIP must contain one CSV")
        with z.open(files[0]) as binary:
            for number,line in enumerate(io.TextIOWrapper(binary,encoding="utf-8-sig"),1):
                if not line.strip():continue
                epoch,micro,bid,ask=parse_tick(next(csv.reader([line])),month=period,day_cache=day_cache)
                t=epoch*1_000_000+micro
                if prev_ts is not None and t<prev_ts:inversion+=1
                prev_ts=t
                minute=epoch//60*60
                order=(t,number)
                ticks+=1
                old=minutes.get(minute)
                if old is None:
                    minutes[minute]={"first":order,"last":order,
                        "open":bid,"high":bid,"low":bid,"close":bid,
                        "volume":1,"open_ask":ask,"max_spread":ask-bid}
                else:
                    old["volume"]+=1
                    old["high"]=max(old["high"],bid)
                    old["low"]=min(old["low"],bid)
                    old["max_spread"]=max(old["max_spread"],ask-bid)
                    if order<old["first"]:
                        old["first"]=order
                        old["open"]=bid
                        old["open_ask"]=ask
                    if order>=old["last"]:
                        old["last"]=order
                        old["close"]=bid
    buckets={}
    for minute,row in minutes.items():
        buckets.setdefault(minute//300*300,[]).append((minute,row))
    qualified=[]
    partials=0
    for epoch,group in sorted(buckets.items()):
        group.sort(key=lambda q:q[0])
        if len(group)!=5 or any(k!=epoch+60*i for i,(k,_) in enumerate(group)):
            partials+=1;continue
        q=[v for _,v in group]
        qualified.append({
            "open_time_utc":datetime.fromtimestamp(epoch,UTC).isoformat(),
            "open":q[0]["open"],"high":max(y["high"] for y in q),
            "low":min(y["low"] for y in q),
            "close":q[-1]["close"],"volume":sum(y["volume"] for y in q),
            "source_m1_minutes":5,
            "observed_open_ask":q[0]["open_ask"],
            "observed_open_spread":q[0]["open_ask"]-q[0]["open"],
            "observed_max_spread":max(y["max_spread"] for y in q),
        })
    if len(qualified)<2500 or ticks<20000:
        raise ValueError("Unqualified original tick archive or insufficient full M5s")
    digest=hashlib.sha256(json.dumps(qualified,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    receipt={
      "source_period":period,"sha256_original_zip":sha,
      "original_tick_rows":ticks,"tick_time_inversions":inversion,
      "complete_real_m5_bars":len(qualified),
      "excluded_partial_m5":partials,"sha256_m5":digest,
      "time_origin":"HistData fixed EST UTC-05, converted to UTC",
      "original_zip_modified":False,"live_broker_ask_fill_parity":False,
      "publisher_native_csv_exact_match":False,
    }
    return qualified,receipt

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--archive",type=Path,required=True)
    p.add_argument("--period",required=True)
    p.add_argument("--out",type=Path,required=True)
    q=p.parse_args()
    rows,receipt=original_tick_m5(q.archive,q.period)
    q.out.mkdir(parents=True,exist_ok=True)
    with (q.out/"m5.csv").open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    (q.out/"receipt.json").write_text(json.dumps(receipt,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print("S004_REAL_SOURCE_M5",json.dumps(receipt,sort_keys=True),flush=True)

if __name__=="__main__": main()
