"""Additional Jan-Sep2026 original 001B Gold BID+ASK M1 replay (retrospective).

Source is exactly ten existing archived 2025Dec–2026Sep HistData XAUUSD
BID+ASK original tick ZIPs with independent per-month original source receipts
from existing CROSSFIRE 2026 run. 2023–25 original encrypted M1 receipts remain
the warmup. Author src/strategy.py and engine.py are executed UNMODIFIED.
No future Oct2026 archives invented, no source rule retuning or live orders.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import pandas as pd
from scripts.gold_hunter_g005_original_zone_rejection import (
  original_modules, original_quotes, source_bars, source_author_simulate,
  broker_lot_overlay, SOURCE, BLOBS, digest, AUTHOR_R, AUTHOR_RISK_PCT,
)

PERIODS=("202512",)+tuple(f"2026{i:02d}" for i in range(1,10))
BEGIN=pd.Timestamp("2026-01-01",tz="UTC")
END=pd.Timestamp("2026-10-01",tz="UTC")

def verified_2026_m1(source:Path):
    import csv
    blocks=[]; receipts=[]
    for period in PERIODS:
        base=source/f"g005-source-{period}"
        marker=base/"g005_m1_receipt.json"
        data=base/"bidask_m1.csv"
        if not marker.is_file() or not data.is_file():
            raise ValueError(f"Missing tick source/receipt {period}")
        proof=json.loads(marker.read_text())
        if (proof["schema"]!="aidy.g005.original_2026_m1.v1"
            or proof["period_fixed_est"]!=period
            or len(proof["original_archive_sha256"])!=64
            or len(proof["original_source_CROSSFIRE_verified_h1_sha256"])!=64
            or proof["source_modified"] is not False
            or hashlib.sha256(data.read_bytes()).hexdigest()!=proof["m1_csv_sha256"]):
            raise ValueError(f"Original tick quote provenance corrupted {period}")
        with data.open(newline="",encoding="utf-8") as stream:
            block=pd.DataFrame(csv.DictReader(stream))
        cols=["bid_o","bid_h","bid_l","bid_c","ask_o","ask_h",
              "ask_l","ask_c","ticks","spread_mean"]
        block["ts"]=pd.to_datetime(block["open_time_utc"],utc=True,errors="raise")
        for col in cols: block[col]=pd.to_numeric(block[col],errors="raise")
        if (len(block)!=proof["original_m1_rows"]
            or block["ts"].duplicated().any()
            or not block["ts"].is_monotonic_increasing
            or (block["ask_o"]<block["bid_o"]).any()
            or (block["ask_h"]<block["bid_h"]).any()
            or (block["ask_l"]<block["bid_l"]).any()
            or (block["ticks"]<1).any()):
            raise ValueError(f"Original tick-derived M1 geometry invalid {period}")
        receipts.append({k:v for k,v in proof.items() if k!="frozen_original_receipt"})
        blocks.append(block.set_index("ts")[cols])
    frame=pd.concat(blocks).sort_index()
    if frame.index.duplicated().any():
        raise ValueError("Overlapping UTC month seams on original 2026 ticks")
    frame=frame.loc[(frame.index>=BEGIN)&(frame.index<END)].copy()
    if (len(frame)<150_000 or set(frame.index.month)!=set(range(1,10))
        or not (frame.index.year==2026).all()):
        raise ValueError("Source 2026 original M1 months or coverage missing")
    frame.index.name="ts"
    frame["o"]=(frame["bid_o"]+frame["ask_o"])/2
    frame["h"]=(frame["bid_h"]+frame["ask_h"])/2
    frame["l"]=(frame["bid_l"]+frame["ask_l"])/2
    frame["c"]=(frame["bid_c"]+frame["ask_c"])/2
    return frame,{"months":len(receipts),"m1_rows_2026":len(frame),
                  "source_receipts":receipts,
                  "m1_index_sha256":hashlib.sha256(frame.index.astype("int64").to_numpy().tobytes()).hexdigest()}

def research(quotes:Path,author:Path,source_2026:Path,out:Path):
    dataset,strategy,engine=original_modules(author)
    earlier,earlier_receipts=original_quotes(quotes)
    new,new_receipts=verified_2026_m1(source_2026)
    combined=pd.concat([earlier,new]).sort_index()
    if combined.index.duplicated().any():
        raise ValueError("Historical Gold quote source overlap")
    m15,h4,d1,coverage=source_bars(dataset,combined)
    print("G005_2026_COVERAGE",json.dumps(coverage,sort_keys=True),flush=True)
    sig,rej=strategy.generate_signals(m15,h4,d1,mode="B",
                                       trend_mode="ema50",session_filter=True)
    if sig.empty:raise ValueError("No original 001B signals in full source")
    sel=sig.loc[(sig["signal_ts"]>=BEGIN)&(sig["entry_ts"]<END)].copy()
    out.mkdir(parents=True,exist_ok=True)
    sel.to_csv(out/"source_001B_2026_signals.csv",index=False)
    m15=m15.loc[(m15.index>=BEGIN)&(m15.index<END)]
    m1=combined.loc[(combined.index>=BEGIN)&(combined.index<END)]
    original,original_trades=source_author_simulate(engine,sel,m15,m1)
    original_trades.to_csv(out/"source_001B_original_author_2026_trades.csv",index=False)
    report={"schema":"aidy.g005.2026_original_tick_source_001B.v1",
      "original_author_source":SOURCE,"original_source_git_blobs":BLOBS,
      "source_original_unmodified":True,"author_selected_R":AUTHOR_R,
      "author_selected_risk_pct":AUTHOR_RISK_PCT,
      "source_2023_to_2025_warmup":earlier_receipts,
      "source_2026_original_tick_receipts":new_receipts,
      "m15_h4_d1_original_source_coverage":coverage,
      "period":"2026-01-01 through 2026-09-30",
      "retrospective_not_untouched_holdout":True,
      "g005_signals_in_2026":len(sel),"g005_source_rejections_all_years":len(rej),
      "original_unmodified_author_engine":original,
      "broker_cost_scenarios":{},"broker_orders":0,
      "scientific_no_broker_parity":True}
    for name,slip,fee,fin in (("base",.05,.07,.06),("stress",.25,.14,.09)):
        r=broker_lot_overlay(engine,sel,m15,m1,slippage=slip,
          roundtrip_fee_per_oz=fee,financing_annual=fin)
        (out/f"{name}_broker_cost_full_ledger.json").write_text(
          json.dumps(r,sort_keys=True,indent=2,allow_nan=False)+"\n")
        report["broker_cost_scenarios"][name]={
          k:v for k,v in r.items() if k!="trades"}
    report["sha256"]=digest(report)
    (out/"report.json").write_text(json.dumps(report,sort_keys=True,
      indent=2,allow_nan=False,default=str)+"\n")
    print("G005_2026_SOURCE_ORIGINAL",json.dumps({"author":original,
       "signals":len(sel),"stress":report["broker_cost_scenarios"]["stress"],
       "m1":len(m1)},sort_keys=True),flush=True)
    return report

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--quotes",required=True,type=Path)
    p.add_argument("--author",required=True,type=Path)
    p.add_argument("--source-2026",required=True,type=Path)
    p.add_argument("--out",required=True,type=Path)
    args=p.parse_args()
    try:research(args.quotes,args.author,args.source_2026,args.out)
    except Exception as ex:
        args.out.mkdir(parents=True,exist_ok=True)
        (args.out/"BLOCKED.json").write_text(json.dumps({
            "not_tested":True,"exception_type":type(ex).__name__,
            "original_market_quotes_never_synthesized":True},indent=2)+"\n")
        raise
