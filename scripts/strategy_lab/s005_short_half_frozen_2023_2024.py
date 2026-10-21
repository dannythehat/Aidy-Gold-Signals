"""AIDY S005 historical 2023/2024 frozen hypothesis check. RESEARCH ONLY.

Published publisher Python engine and original signal rules remain pinned.
Single preselected exploratory change: short-entry risk=0.5%, long=1%,
vs publisher original both=1%. Source-quoted 2025/2026 inspired this
hypothesis, so 2023/2024 are retrospective validation, NOT blind OOS.
No broker API, MT5 orders, Green score, or paper admission.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.strategy_lab.s005_publisher_engine_two_preset_parity import (
    PUB_COMMIT, original_modules, _git_blob_sha,
)

SOURCE_MONTHS = ["202212"] + [f"{year}{month:02d}" for year in (2023, 2024) for month in range(1,13)]
YEAR_WINDOWS = {"2023": ("2023-01-01","2024-01-01"), "2024": ("2024-01-01","2025-01-01")}
RISK_PATCH_FROM = "risk_cash = cash * riskpct / 100.0"
RISK_PATCH_TO = "risk_cash = cash * riskpct * (0.5 if direction == -1 else 1.0) / 100.0"
COSTS = (0.45, 0.90)
SOURCE_SHA_ENGINE = "41f1b5740314487ed6ea35b3307daf689d8abb6f"
SCHEMA = "aidy.s005.donchian.short_half_frozen_2023_2024.model.v1"


def load_market(root: Path):
    frames, receipts = [], []
    for month in SOURCE_MONTHS:
        folder = root / f"s005-2023-24-source-{month}"
        r = json.loads((folder/"receipt.json").read_text(encoding="utf-8"))
        if (r["fixed_est_month"] != month or r["source_clock"] != "EST_FIXED_UTC_MINUS_05"
            or r["original_zip_modified"] is not False
            or r["actual_broker_fill_verified"] is not False
            ):
            raise ValueError("Invalid original source receipt")
        if any(len(str(r[k])) != 64 for k in ("original_zip_sha256","derived_m15_sha256")):
            raise ValueError("Invalid source receipt digest")
        rows = list(csv.DictReader((folder/"m15.csv").open(newline="", encoding="utf-8")))
        clean = []
        for x in rows:
            clean.append({"open_time_utc":x["open_time_utc"],
             **{k:float(x[k]) for k in ("open","high","low","close","observed_open_ask",
                                        "observed_open_spread","observed_max_spread")},
             **{k:int(x[k]) for k in ("m1_count","volume")}})
        digest = hashlib.sha256(json.dumps(clean,sort_keys=True,separators=(",",":")).encode()).hexdigest()
        if digest != r["derived_m15_sha256"] or len(clean) != r["complete_m15"] or len(clean)<750:
            raise ValueError("Missing/mismatched authenticated M15 month: "+month)
        frame = pd.DataFrame(clean)
        ts = pd.to_datetime(frame.pop("open_time_utc"), utc=True)
        if ((ts - pd.Timedelta(hours=5)).dt.strftime("%Y%m") != month).any() or ts.duplicated().any() or not ts.is_monotonic_increasing:
            raise ValueError("Invalid month dates or source order: "+month)
        if ((frame.m1_count!=15).any() or (frame.volume<15).any()
           or (frame.observed_open_ask < frame.open).any()
           or (frame.low>frame.high).any()
           or (frame.open<frame.low).any() or (frame.open>frame.high).any()
           or (frame.close<frame.low).any() or (frame.close>frame.high).any()):
            raise ValueError("Unqualified original BID ASK M15")
        frame.index=ts.dt.tz_localize(None)
        frames.append(frame)
        receipts.append(r)
    if len(receipts)!=25:
        raise ValueError("Expected 25 real verified source archives")
    market = pd.concat(frames)
    if market.index.duplicated().any() or not market.index.is_monotonic_increasing:
        raise ValueError("Source months overlap or out of order")
    h = market.resample("60min").agg(
        open=("open","first"), high=("high","max"), low=("low","min"),
        close=("close","last"), count=("open","count"),
        observed_open_spread=("observed_open_spread","first"))
    h = h.loc[h["count"] == 4].copy()
    if len(h)<10000:
        raise ValueError("Insufficient exact complete-H1 coverage")
    digest=hashlib.sha256(h.to_csv().encode()).hexdigest()
    return h, receipts, digest


def variant_engine(original_source: Path, root: Path):
    b = original_source.read_bytes()
    if _git_blob_sha(b) != SOURCE_SHA_ENGINE:
        raise ValueError("Original author Python engine SHA mismatch")
    text = b.decode("utf-8")
    if text.count(RISK_PATCH_FROM)!=1:
        raise ValueError("Publisher position sizing implementation changed")
    adjusted = text.replace(RISK_PATCH_FROM,RISK_PATCH_TO)
    p = root/"engine_short_half_only.py"
    p.write_text(adjusted,encoding="utf-8")
    spec=importlib.util.spec_from_file_location("s005_short_half_only", p)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load tested research-only variant")
    module=importlib.util.module_from_spec(spec)
    sys.modules[spec.name]=module
    spec.loader.exec_module(module)
    return module, hashlib.sha256(adjusted.encode()).hexdigest()


def case(engine, o,h,l,c,times,atr,signals,lo,hi,cost):
    p=engine.EngineParams(sl_atr=2.5,tp_atr=0.,trail_atr=0.,
        allow_reverse=True,risk_pct=1.,start_equity=10000.)
    s=engine.SymbolSpec("XAUUSD",cost=cost,max_leverage=20.)
    res=engine.simulate(o,h,l,c,times,atr,*signals,s,p,lo,hi)
    realized=sum(float(t.pnl) for t in res.trades)
    if not np.isfinite(realized) or abs(realized-100*float(res.net_return))>0.20:
        raise ValueError("Source trade ledger does not reconcile")
    if len(res.trades)<1:
        raise ValueError("No trades in research period")
    return {
        "net_usd":round(realized,2),
        "ending_usd":round(10000+realized,2),
        "closed_trades":len(res.trades),
        "long_trades":sum(t.dir==1 for t in res.trades),
        "short_trades":sum(t.dir==-1 for t in res.trades),
        "long_net_usd":round(sum(t.pnl for t in res.trades if t.dir==1),2),
        "short_net_usd":round(sum(t.pnl for t in res.trades if t.dir==-1),2),
        "max_marked_drawdown_pct":round(-res.max_dd,4),
        "profit_factor":round(float(res.profit_factor),4) if np.isfinite(res.profit_factor) else None,
        "trade_ledger":[
          {"side":"LONG" if t.dir==1 else "SHORT","entry_utc":str(pd.to_datetime(int(times[t.entry_i]),unit="s",utc=True)),
           "exit_utc":str(pd.to_datetime(int(times[t.exit_i]),unit="s",utc=True)),
           "entry_px":round(float(t.entry_px),5),"exit_px":round(float(t.exit_px),5),
           "units_float_oz":round(float(t.units),8),"model_net_usd":round(float(t.pnl),6),
           "reason":t.reason}
          for t in res.trades
        ],
    }


def run(source_root: Path,publisher_root: Path,out: Path):
    original,strategies=original_modules(publisher_root)
    h1,receipts,price_sha=load_market(source_root)
    o,h,l,c=(h1[x].to_numpy(float) for x in ("open","high","low","close"))
    dates=h1.index.tz_localize("UTC")
    # Pandas may store timestamps as microseconds (not nanoseconds) in v3.
    # Convert explicitly to ns before dividing, otherwise exports label trades
    # in 1970 and time-based execution diagnostics become invalid.
    times=dates.as_unit("ns").asi8//1_000_000_000
    if not (pd.Timestamp("2023-01-01",tz="UTC").timestamp() <= times[1500]
            < pd.Timestamp("2025-01-01",tz="UTC").timestamp()):
        raise ValueError("SOURCE_TIME_UNITS_MISMATCH: UTC epoch seconds required")
    hours=dates.hour.to_numpy()
    signals=strategies.donchian(o,h,l,c,hours,entry_n=24,exit_n=12,ema_filter=200)
    atr=original.atr(h,l,c,14)
    out.mkdir(parents=True,exist_ok=True)
    results={}
    with tempfile.TemporaryDirectory(prefix="s005_frozen_variant_") as temp:
        adjusted,patch_sha=variant_engine(publisher_root/"engine.py",Path(temp))
        for year,(start,end) in YEAR_WINDOWS.items():
            lo=int(h1.index.searchsorted(pd.Timestamp(start)))
            hi=int(h1.index.searchsorted(pd.Timestamp(end)))
            if not (pd.Timestamp(start,tz="UTC").timestamp() <= times[lo] <
                    pd.Timestamp(end,tz="UTC").timestamp()):
                raise ValueError("BROKEN_CALENDAR_YEAR_EPOCH")
            if hi-lo<4000:
                raise ValueError("Incomplete historical year "+year)
            results[year]={}
            for cost in COSTS:
                orig=case(original,o,h,l,c,times,atr,signals,lo,hi,cost)
                half=case(adjusted,o,h,l,c,times,atr,signals,lo,hi,cost)
                if any(not (start[:4] <= trade["entry_utc"][:4] <= end[:4])
                       for trade in orig["trade_ledger"]):
                    raise ValueError("Historical trade timestamps outside study dates")
                if (orig["closed_trades"]!=half["closed_trades"]
                    or orig["long_trades"]!=half["long_trades"]
                    or orig["short_trades"]!=half["short_trades"]):
                    raise ValueError("Entry/exit population changed; investigate before comparing")
                # Identical signals and exit event order. Only sizing and ensuing
                # compounding may change.
                if any((a["side"],a["entry_utc"],a["exit_utc"],a["reason"]) !=
                       (b["side"],b["entry_utc"],b["exit_utc"],b["reason"])
                       for a,b in zip(orig["trade_ledger"],half["trade_ledger"])):
                    raise ValueError("Variant unexpectedly modified original entry or exit logic")
                results[year][f"{cost:.2f}"]={
                    "original":orig,"short_half":half,
                    "variant_minus_original_net_usd":round(half["net_usd"]-orig["net_usd"],2),
                    "variant_minus_original_dd_pp":round(half["max_marked_drawdown_pct"]-orig["max_marked_drawdown_pct"],4),
                }
                print("S005_FROZEN_SHORT_HALF_RESULT",json.dumps({
                    "year":year,"cost_per_oz":cost,"original_usd":orig["net_usd"],
                    "half_short_usd":half["net_usd"],"delta_usd":round(half["net_usd"]-orig["net_usd"],2),
                    "original_dd":orig["max_marked_drawdown_pct"],"half_dd":half["max_marked_drawdown_pct"],
                    "trades":orig["closed_trades"]},sort_keys=True),flush=True)
        report={"schema":SCHEMA,"candidate":"S005_THE_CHANNEL_HUNTER","source_publisher_commit":PUB_COMMIT,
            "tested_years":["2023","2024"],"exact_source_original_months":SOURCE_MONTHS,
            "source_price_h1_sha256":price_sha,
            "source_month_receipts":[{"month":r["fixed_est_month"],
                 "zip_sha256":r["original_zip_sha256"],"m15_sha256":r["derived_m15_sha256"],
                 "inversions":r["source_tick_inversions"]} for r in receipts],
            "source_original_engine_git_blob":SOURCE_SHA_ENGINE,"variant_python_sha256":patch_sha,
            "exact_one_line_short_risk_patch":[RISK_PATCH_FROM,RISK_PATCH_TO],
            "original_long_risk_pct":1.0,"original_short_risk_pct":1.0,
            "variant_long_risk_pct":1.0,"variant_short_risk_pct":0.5,
            "original_signal_rules_unchanged":True,
            "entry_exit_event_parity_required":True,
            "source_publisher_float_oz":True,
            "frozen_per_oz_costs_model_only":list(COSTS),
            "real_bidask_broker_fill_replay":False,"native_MT5_test":False,
            "research_only_no_orders":True,
            "retrospective_not_sealed_oos":True,
            "all_2025_2026_results_untouched":True,
            "results":results}
        report["sha256"]=hashlib.sha256(json.dumps(report,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()
        (out/"S005_2023_2024_ORIGINAL_VS_SHORT_HALF.json").write_text(json.dumps(report,sort_keys=True,indent=2,allow_nan=False)+"\n",encoding="utf-8")
        table=[]
        for year,cases in results.items():
            for cost,v in cases.items():
                table.append({"year":year,"cost_usd_per_oz_rt":cost,
                    "original_net_usd":v["original"]["net_usd"],
                    "half_short_net_usd":v["short_half"]["net_usd"],
                    "difference_usd":v["variant_minus_original_net_usd"],
                    "original_dd_pct":v["original"]["max_marked_drawdown_pct"],
                    "half_short_dd_pct":v["short_half"]["max_marked_drawdown_pct"],
                    "trades":v["original"]["closed_trades"]})
        with (out/"S005_2023_2024_COMPARE.csv").open("w",newline="",encoding="utf-8") as f:
            w=csv.DictWriter(f,fieldnames=list(table[0]));w.writeheader();w.writerows(table)
        print("S005_2023_2024_RESEARCH_PACKET",report["sha256"],flush=True)
        return report


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--source-root",required=True,type=Path)
    p.add_argument("--publisher-root",required=True,type=Path)
    p.add_argument("--out",required=True,type=Path)
    x=p.parse_args()
    run(x.source_root,x.publisher_root,x.out)


if __name__=="__main__":
    main()
