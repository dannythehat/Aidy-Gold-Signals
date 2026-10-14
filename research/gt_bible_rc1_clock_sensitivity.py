"""AIDY read-only GT-BIBLE RC1 clause-accurate price study, NOT a strategy backtest.

Sources: AIDY HistData XAUUSD 2024-25 M1 bid OHLC, exact source rows.
Signal geometry: pinned RC1 interpreter (already 43/43 golden decision parity).
Broker candle clocks: three explicit *HYPOTHESES*, NOT verified Vantage history.
Full GT-BIBLE 2.0 as-of structure/levels/entry/stop/target, execution costs,
no-oppose and actual ASK fills are NOT evaluated by this stage.

Never trade or update a BigQuery table. Never claim these as RC1 strategy results.
"""
from __future__ import annotations
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from fractions import Fraction as F
from pathlib import Path
from zoneinfo import ZoneInfo
import json, os

from google.cloud import bigquery
from google.oauth2 import service_account

from gt_bible_rc1_independent import load, shape, BUNDLE, GT_COMMIT

PROJECT="aidy-signals"
MAX_BILLED_BYTES=700_000_000
SQL="""
SELECT open_time_utc, open, high, low, close, research_identity
FROM `aidy-signals.aidy_analytics_test.research_candles`
WHERE open_time_utc >= TIMESTAMP('2024-01-01 00:00:00+00')
  AND open_time_utc < TIMESTAMP('2026-01-01 00:00:00+00')
  AND symbol='XAUUSD'
  AND source='histdata'
  AND timeframe='M1'
  AND pit_eligible=FALSE
  AND provenance_class='retrospective_history'
ORDER BY open_time_utc
"""

MODES={
    "ASSUMED_EU_DST_EET_EEST":"Europe/Athens",
    "SENSITIVITY_FIXED_UTC_PLUS_2":timezone(timedelta(hours=2)),
    "SENSITIVITY_FIXED_UTC_PLUS_3":timezone(timedelta(hours=3)),
}
MINS={"H1":60,"H4":240,"D1":1440}
SIDES=("BULL","BEAR")
PATS=("P03","P06","P07","P09","P22")


def minute_rows(client):
    dry=client.query(SQL,job_config=bigquery.QueryJobConfig(dry_run=True,use_query_cache=False),location="EU")
    if not dry.total_bytes_processed or dry.total_bytes_processed>MAX_BILLED_BYTES:
        raise SystemExit(f"Research read blocked by query dry run: {dry.total_bytes_processed}")
    job=client.query(SQL,job_config=bigquery.QueryJobConfig(maximum_bytes_billed=MAX_BILLED_BYTES,use_query_cache=False),location="EU",
                     job_id_prefix="goldthinker_rc1_readonly_shapes_")
    rows=[]
    prev=None
    for r in job.result(timeout=180):
        t=r.open_time_utc
        if t.tzinfo is None:
            raise SystemExit("Unexpected timezone naive BigQuery minute")
        if t.second or t.microsecond:
            raise SystemExit("Non-minute-aligned source timestamp")
        if prev is not None and t<=prev:
            raise SystemExit("Duplicate or unordered M1 candle found")
        o,h,l,c=map(Decimal,(r.open,r.high,r.low,r.close))
        if h<max(o,c) or l>min(o,c) or h<l:
            raise SystemExit("Invalid underlying M1 OHLC")
        rows.append((t,o,h,l,c))
        prev=t
    if len(rows)!=709543:
        raise SystemExit(f"Unexpected source history size {len(rows)}; investigate source revision")
    return rows,{"dry_run_bytes":dry.total_bytes_processed,"billed_bytes":job.total_bytes_billed}


def key_for(t,tf):
    # Broker wall time, with an explicit user-facing UNVERIFIED historical mapping.
    if tf=="H1":
        return (t.year,t.month,t.day,t.hour)
    if tf=="H4":
        return (t.year,t.month,t.day,t.hour//4)
    if tf=="D1":
        return (t.year,t.month,t.day)
    raise ValueError(tf)


def candle_buckets(minutes,tz):
    if isinstance(tz,str):
        tz=ZoneInfo(tz)
    # Stream UTC-ordered M1 through wall-clock bucket IDs. A DST fall-back can
    # revisit an hour bucket: use a dictionary, not sequential run segmentation.
    store={tf:{} for tf in MINS}
    for utc,o,h,l,c in minutes:
        wall=utc.astimezone(tz)
        for tf in MINS:
            k=key_for(wall,tf)
            b=store[tf].get(k)
            if b is None:
                store[tf][k]={"t":utc,"o":o,"h":h,"l":l,"c":c,"n":1,
                              "start":utc,"last":utc}
            else:
                if utc<b["start"]:
                    b["start"]=utc
                    b["o"]=o
                if utc>b["last"]:
                    b["last"]=utc
                    b["c"]=c
                b["h"]=max(h,b["h"])
                b["l"]=min(l,b["l"])
                b["n"]+=1
    output={}
    counts={}
    for tf,bs in store.items():
        bars=sorted(bs.values(),key=lambda b:b["t"])
        # Full ordinary wall-clock buckets only. Ambiguous DST transition
        # buckets (missing/repeated hour) are censored, not fabricated.
        for b in bars:
            b["full"]=b["n"]==MINS[tf]
        counts[tf]={"all_buckets":len(bars),
                    "fully_observed":sum(b["full"] for b in bars),
                    "partial_or_dst_ambiguous":sum(not b["full"] for b in bars)}
        output[tf]=bars
    return output,counts


def true_range_at(bars,i):
    b,p=bars[i],bars[i-1]
    return max(b["h"]-b["l"],abs(b["h"]-p["c"]),abs(b["l"]-p["c"]))


def atr_before(bars,i):
    if i<15 or not all(b["full"] for b in bars[i-15:i]):
        return None
    return F(sum((true_range_at(bars,k) for k in range(i-14,i)),Decimal(0))) / 14


def count_signal(store,typ,side,year,tf,prior,delta):
    k=(typ,side,str(year),tf,prior)
    g=store[k]
    g["n"]+=1
    if delta>0:g["win"]+=1
    if delta==0:g["flat"]+=1
    g["sum"]+=delta


def blank():
    return {"n":0,"win":0,"flat":0,"sum":Decimal(0)}


def census(bars_by_tf):
    matched=defaultdict(blank)
    base=defaultdict(blank)
    attr=defaultdict(lambda:{"raw_patterns":0,"forward_evaluable":0,"not_evaluable":0})
    for tf,bars in bars_by_tf.items():
        n=len(bars)
        # Candidate i is the signal bar. P22 has 2 prior bars minimum.
        for i in range(18,n-4):
            cur=bars[i]
            if not cur["full"]:
                continue
            year=cur["t"].year
            if year not in (2024,2025):
                continue
            if not all(b["full"] for b in bars[i-6:i]):
                continue
            prev_dir=("UP" if bars[i-1]["c"]>bars[i-6]["c"]
                      else "DOWN" if bars[i-1]["c"]<bars[i-6]["c"] else "FLAT")
            next4=bars[i+1:i+5]
            eligible=len(next4)==4 and all(b["full"] for b in next4)
            if eligible:
                fwd=next4[-1]["c"]-cur["c"]
                for side in SIDES:
                    signed=fwd if side=="BULL" else -fwd
                    count_signal(base,"ALL_BAR",side,year,tf,prev_dir,signed)
                    count_signal(base,"ALL_BAR",side,year,tf,"ALL_PRIOR",signed)
            # Correct canonical ATR is previous 14 TRUE RANGES from 15 prior
            # completed bars, never mean same-bar high-low.
            atr_p=atr_before(bars,i)
            if atr_p is not None:
                for side in SIDES:
                    shape3,_,_=shape("P03",side,[{k:F(v) for k,v in cur.items() if k in ("o","h","l","c")}],atr_p)
                    if shape3:
                        attr[("P03",side,str(year),tf)]["raw_patterns"]+=1
                        if eligible:
                            signed=fwd if side=="BULL" else -fwd
                            count_signal(matched,"P03",side,year,tf,prev_dir,signed)
                            count_signal(matched,"P03",side,year,tf,"ALL_PRIOR",signed)
                        else:
                            attr[("P03",side,str(year),tf)]["not_evaluable"]+=1
            prev=bars[i-1]
            atr_2=atr_before(bars,i-1)
            if not prev["full"] or atr_2 is None:
                continue
            pair=[{k:F(b[k]) for k in ("o","h","l","c")} for b in (prev,cur)]
            for side,pid in (("BULL","P06"),("BEAR","P07")):
                ok,_,_=shape(pid,side,pair,atr_2)
                if ok:
                    attr[(pid,side,str(year),tf)]["raw_patterns"]+=1
                    if eligible:
                        signed=fwd if side=="BULL" else -fwd
                        count_signal(matched,pid,side,year,tf,prev_dir,signed)
                        count_signal(matched,pid,side,year,tf,"ALL_PRIOR",signed)
                    else:
                        attr[(pid,side,str(year),tf)]["not_evaluable"]+=1
            ib,_,_=shape("P09","BULL",pair,atr_2)
            if ib:
                attr[("P09","NEUTRAL",str(year),tf)]["raw_patterns"]+=1
            # P22 completed sweep must refer to mother at i-2,i-3 or i-4,
            # inside at mother+1, and first mother-break within next 3 bars.
            # Evaluate only snapshots ending on the actual piercing bar.
            for nback in (2,3,4):
                first=i-nback
                if first<15 or not all(x["full"] for x in bars[first:i+1]):
                    continue
                mother=bars[first]
                inside=bars[first+1]
                ab=[{k:F(b[k]) for k in ("o","h","l","c")} for b in bars[first:i+1]]
                if not (inside["h"]<mother["h"] and inside["l"]>mother["l"]):
                    continue
                for side in SIDES:
                    ok,_,_=shape("P22",side,ab,atr_2)
                    if not ok:
                        continue
                    attr[("P22",side,str(year),tf)]["raw_patterns"]+=1
                    if eligible:
                        signed=fwd if side=="BULL" else -fwd
                        count_signal(matched,"P22",side,year,tf,prev_dir,signed)
                        count_signal(matched,"P22",side,year,tf,"ALL_PRIOR",signed)
                    else:
                        attr[("P22",side,str(year),tf)]["not_evaluable"]+=1
    # Express directional follow-through in percentage points over a matched,
    # same-year/same-timeframe/all-bar benchmark. NOT PnL or broker profitability.
    rows=[]
    for (pat,side,yr,tf), a in sorted(attr.items()):
        if side=="NEUTRAL":
            rows.append(dict(pattern=pat,side=side,year=int(yr),timeframe=tf,
                             occurrences=a["raw_patterns"],status="SHAPE_ONLY_NO_DIRECTIONAL_OUTCOME"))
            continue
        obs=matched.get((pat,side,yr,tf,"ALL_PRIOR"),blank())
        baseline=base.get(("ALL_BAR",side,yr,tf,"ALL_PRIOR"),blank())
        pct=lambda x:round(100*x["win"]/x["n"],2) if x["n"] else None
        lift=round(pct(obs)-pct(baseline),2) if obs["n"] and baseline["n"] else None
        rows.append(dict(pattern=pat,side=side,year=int(yr),timeframe=tf,
                         occurrences=a["raw_patterns"],evaluable=obs["n"],
                         missing_forward=a["not_evaluable"],
                         followthrough_pct=pct(obs),
                         matched_all_bar_baseline_pct=pct(baseline),
                         directional_lift_percentage_points=lift,
                         matched_baseline_n=baseline["n"]))
    return rows,{"shape_types_evaluated":len(rows),
                 "total_candidates_including_neutral_and_overlap":sum(r["occurrences"] for r in rows)}


def main():
    info=json.loads(os.environ["AIDY_GCP_SERVICE_ACCOUNT_JSON"])
    if info.get("type")!="service_account" or info.get("project_id")!=PROJECT:
        raise SystemExit("Unexpected AIDY research credential project")
    credentials=service_account.Credentials.from_service_account_info(info)
    client=bigquery.Client(credentials=credentials,project=PROJECT,location="EU")
    ms=load()  # fails if any frozen rule changed
    if ms["GT-BIBLE-COMMON"]["version"]!="2.0.0-rc1":
        raise SystemExit("Changed manifest")
    minutes,job=minute_rows(client)
    report={"classification":"EARLY_HISTORICAL_GEOMETRY_SCREEN_ONLY_NOT_GT_BIBLE_STRATEGY",
            "gt_commit":GT_COMMIT,"manifest_bundle_sha256":BUNDLE,
            "aidy_m1_rows":len(minutes),
            "source":"2024-2025 HistData M1 bid OHLC, retrospective only",
            "source_cost_bytes":job,
            "limitations":[
                "Three simulated broker time-mappings are unverified; not claimed to be historical Vantage clocks",
                "RC1 clause geometry + true-range ATR only; no confirmed as-of trend/levels/W1 agreement/RR/decision gates",
                "Conservative full-M1 bucket requirement; legitimate partial Sunday/Friday market bars excluded",
                "All-bar same-calendar-year/timeframe/side forward baseline, not proper regime matching nor untouched holdout",
                "First-pierce P22 matched only to mother+inside patterns; overlapping candidates not independent trades",
                "Forward close after four completed bars: no market orders, costs, SL/TP ordering, ASK or P&L",
                "2024-25 used for descriptive discovery: MUST use separate future/held-out material for validation"
            ],"scenarios":{}}
    for mode,tz in MODES.items():
        candles,quality=candle_buckets(minutes,tz)
        entries,summary=census(candles)
        report["scenarios"][mode]={"quality":quality,"overview":summary,"entries":entries}
        print(json.dumps({"mode":mode,"quality":quality,"overview":summary,
                          "notable":[r for r in entries if r["timeframe"] in ("H4","D1")
                                     and r.get("evaluable",0)>=15 and r.get("side")!="NEUTRAL"][:12]},default=str,sort_keys=True))
    Path("artifacts").mkdir(exist_ok=True)
    Path("artifacts/gt_bible_rc1_clock_sensitivity_shapes.json").write_text(json.dumps(report,indent=2,default=str,sort_keys=True)+"\n",encoding="utf-8")

if __name__=="__main__":
    main()
