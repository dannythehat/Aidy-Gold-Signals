"""S001 independent, costed 2025 real-history $10k backtest.

Original: https://github.com/eamonnkennedy93-blip/GoldEA
Independently implements documented session-sweep, causal confirmed HTF
swing bias and wick stop. Tested target-2R is an explicitly specified AIDY
variant, NOT a claim of the author's unpublished MQL5/live version.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "artifacts/strategy_lab/s001_full_2025"
TABLE = "aidy-signals.aidy_analytics_test.research_candles"
SOURCE = "https://github.com/eamonnkennedy93-blip/GoldEA"
START_BALANCE = 10000.0
BYTE_CAP = 1_500_000_000
MONTHS = [f"2025-{n:02d}" for n in range(1, 13)]
PARAMS = {
    "signal_tf": "M15", "confirm_reclaim_fraction": 0.50,
    "htf_bias": "confirmed_1h_and_4h_HH_HL_or_LH_LL",
    "h1_swing_lookback": 5, "h1_swing_confirm": 3,
    "h4_swing_lookback": 3, "h4_swing_confirm": 2,
    "risk_current_equity_fraction": .01, "contract_oz_per_lot": 100,
    "lot_step": .01, "max_notional_to_equity": 10.0,
    "atr_wilder_period": 14, "atr_stop_multiplier": 1.0,
    "primary_target_r": 2.0,
    "baseline_spread_per_oz": .30,
    "slippage_each_side_per_oz": .10,
    "commission_roundtrip_per_lot": 7.0,
    "baseline_financing": 0.0,
    "base_not_author_native_volume": True,
}


def retrieve_month(client, year, month):
    from google.cloud import bigquery
    start = datetime(year, month, 1, tzinfo=UTC)
    end = datetime(year + 1, 1, 1, tzinfo=UTC) if month == 12 else datetime(year, month + 1, 1, tzinfo=UTC)
    sql = f"""
      SELECT TIMESTAMP_SECONDS(DIV(UNIX_SECONDS(open_time_utc),900)*900) open_time_utc,
        ARRAY_AGG(open ORDER BY open_time_utc ASC LIMIT 1)[OFFSET(0)] open,
        MAX(high) high, MIN(low) low,
        ARRAY_AGG(close ORDER BY open_time_utc DESC LIMIT 1)[OFFSET(0)] close,
        COUNT(*) m1_count, COUNT(DISTINCT open_time_utc) unique_m1,
        COUNTIF(NOT(
          source='histdata' AND symbol='XAUUSD' AND timeframe='M1'
          AND price_basis='bid' AND source_dataset='generic_ascii_m1'
          AND source_timezone='EST_FIXED_UTC_MINUS_05'
          AND derivation_version='aidy_histdata_source_aligned_v1'
          AND provenance_class='retrospective_history'
          AND pit_eligible=FALSE AND derived_from_timeframe IS NULL
          AND input_rows=1 AND LENGTH(source_file_sha256)=64
          AND LENGTH(source_payload_sha256)=64
        )) invalid_rows,
        ARRAY_AGG(DISTINCT source_file_sha256 IGNORE NULLS) source_shas
      FROM {chr(96)}{TABLE}{chr(96)}
      WHERE symbol='XAUUSD' AND timeframe='M1'
      AND open_time_utc>=@start AND open_time_utc<@end
      GROUP BY 1 ORDER BY 1
    """
    params = [bigquery.ScalarQueryParameter("start", "TIMESTAMP", start),
              bigquery.ScalarQueryParameter("end", "TIMESTAMP", end)]
    dry = client.query(sql, job_config=bigquery.QueryJobConfig(
        query_parameters=params, dry_run=True, use_query_cache=False))
    estimate = int(dry.total_bytes_processed or 0)
    if estimate > BYTE_CAP:
        raise ValueError("BigQuery source scan exceeds monthly 1.5GB cap")
    job = client.query(sql, job_config=bigquery.QueryJobConfig(
        query_parameters=params, use_query_cache=False,
        maximum_bytes_billed=BYTE_CAP))
    fetched = [dict(r) for r in job.result(timeout=240)]
    if not fetched:
        raise ValueError("No original M1 history for " + start.strftime("%Y-%m"))
    good, partial, bad, originals, hashes = [], 0, 0, 0, set()
    for r in fetched:
        n, unique = int(r["m1_count"]), int(r["unique_m1"])
        originals += n
        bad += int(r["invalid_rows"])
        hashes.update(r["source_shas"] or [])
        if unique != n or n > 15:
            raise ValueError("Duplicate/unqualified minute source")
        if n != 15:
            partial += 1
            continue
        data = {key:float(r[key]) for key in ("open", "high", "low", "close")}
        if not (0 < data["low"] <= data["open"] <= data["high"]
                and data["low"] <= data["close"] <= data["high"]):
            raise ValueError("Original OHLC corrupt")
        data["open_time_utc"] = r["open_time_utc"].isoformat()
        good.append(data)
    if bad or len(good) < 750 or not hashes or any(len(h) != 64 for h in hashes):
        raise ValueError("Unqualified original archive monthly contract")
    return good, {
        "month":start.strftime("%Y-%m"), "native_m1_rows":originals,
        "complete_m15":len(good), "partial_excluded":partial,
        "source_archive_shas":sorted(hashes), "query_job_id":job.job_id,
        "dry_run_bytes":estimate,
    }


def get_original_gold_history():
    from google.cloud import bigquery
    from google.oauth2 import service_account
    raw = json.loads(os.environ["AIDY_GCP_SERVICE_ACCOUNT_JSON"])
    client = bigquery.Client(project=raw["project_id"], location="EU",
        credentials=service_account.Credentials.from_service_account_info(raw))
    all_rows, receipts = [], []
    for n in range(1, 13):
        rows, receipt = retrieve_month(client, 2025, n)
        all_rows.extend(rows)
        receipts.append(receipt)
        print("S001_REAL_HISTORY", json.dumps({
            k:receipt[k] for k in ("month","native_m1_rows","complete_m15","partial_excluded","query_job_id")
        },sort_keys=True,default=_json_native),flush=True)
    raw_canon = json.dumps(all_rows,sort_keys=True,separators=(",",":"))
    source_sha = hashlib.sha256(raw_canon.encode()).hexdigest()
    return pd.DataFrame(all_rows), receipts, source_sha


def swings(df, lookback, confirm):
    """Output bias events at CONFIRMING bar close, never at pivot-time."""
    h, l = df["high"].to_numpy(), df["low"].to_numpy()
    highs, lows, events = [], [], []
    idx = df.index
    for pivot in range(lookback, len(df)-confirm):
        when = idx[pivot+confirm] + (idx[1]-idx[0])
        if h[pivot] >= max(h[pivot-lookback:pivot+confirm+1]):
            highs.append(h[pivot])
            highs = highs[-2:]
            events.append((when,0,highs.copy(),lows.copy()))
        if l[pivot] <= min(l[pivot-lookback:pivot+confirm+1]):
            lows.append(l[pivot])
            lows = lows[-2:]
            events.append((when,0,highs.copy(),lows.copy()))
    return events


def bias_projection(execution_times, htf, lookback, confirm):
    events = swings(htf,lookback,confirm)
    events.sort(key=lambda x:x[0])
    evts, vals, vwap_anchors = [], [], []
    for ts, _, highs, lows in events:
        vwap_anchors.append(ts)
        b = 0
        if len(highs)==2 and len(lows)==2:
            if highs[-1]>highs[-2] and lows[-1]>lows[-2]:
                b = 1
            elif highs[-1]<highs[-2] and lows[-1]<lows[-2]:
                b = -1
        evts.append(ts)
        vals.append(b)
    if not evts:
        return np.zeros(len(execution_times),dtype=int),[]
    order=np.argsort(np.asarray(evts,dtype="datetime64[ns]"),kind="stable")
    keys=np.asarray(evts,dtype="datetime64[ns]")[order]
    value=np.asarray(vals,dtype=int)[order]
    positions=np.searchsorted(keys,execution_times.to_numpy(dtype="datetime64[ns]"),side="right")-1
    projected=np.where(positions>=0,value[np.maximum(positions,0)],0)
    return projected,vwap_anchors


def bars_at(df, minutes, expected):
    # Uses genuine source-contiguous fixed-time windows; no missing synthetic bars.
    x = df.resample(f"{minutes}min").agg(
        {"open":"first","high":"max","low":"min","close":"last","volume_proxy":"count"})
    x=x[x["volume_proxy"]==expected].copy()
    x.drop(columns=["volume_proxy"],inplace=True)
    return x


def signal_table(raw):
    data=raw.copy()
    data["open_time_utc"]=pd.to_datetime(data["open_time_utc"],utc=True)
    data=data.sort_values("open_time_utc").set_index("open_time_utc")
    if data.index.duplicated().any():
        raise ValueError("Duplicate M15 data; cannot use")
    data.index=data.index.tz_convert("UTC").tz_localize(None)
    data["volume_proxy"]=1.0
    h1=bars_at(data,60,4)
    h4=bars_at(data,240,16)
    now=data.index+pd.Timedelta(minutes=15)
    bias1,anchors=bias_projection(now,h1,5,3)
    bias4,_=bias_projection(now,h4,3,2)
    data["bias1"]=bias1
    data["bias4"]=bias4
    data["bias"]=np.where((bias1==bias4),bias1,0)
    local=data.index.tz_localize("UTC").tz_convert("Europe/London")
    data["uk_date"]=pd.Index(local.date)
    data["uk_hour"]=local.hour+local.minute/60
    daily=data.groupby("uk_date")[["high","low"]].agg({"high":"max","low":"min"}).shift(1)
    data["prior_high"]=data["uk_date"].map(daily["high"])
    data["prior_low"]=data["uk_date"].map(daily["low"])
    a=data[(data["uk_hour"]>=0)&(data["uk_hour"]<8)].groupby("uk_date").agg(
        asia_high=("high","max"),asia_low=("low","min"))
    london=data[(data["uk_hour"]>=8)&(data["uk_hour"]<9)].groupby("uk_date").agg(
        london_high=("high","max"),london_low=("low","min"))
    for name,source,earliest in (
        ("asia_high",a,8),("asia_low",a,8),
        ("london_high",london,9),("london_low",london,9)):
        data[name]=data["uk_date"].map(source[name])
        data.loc[data["uk_hour"]<earliest,name]=np.nan
    high,low,close=data["high"].to_numpy(),data["low"].to_numpy(),data["close"].to_numpy()
    signals=np.zeros(len(data),dtype=int)
    wick=np.full(len(data),np.nan)
    which=["prior_high","asia_high","london_high"]
    lows=["prior_low","asia_low","london_low"]
    levels={k:data[k].to_numpy() for k in which+lows}
    prev_date=None
    pending_hi,pending_lo={},{}
    for i in range(len(data)):
        date=data["uk_date"].iat[i]
        if date!=prev_date:
            pending_hi,pending_lo={},{}
            prev_date=date
        span=high[i]-low[i]
        if span<=0:
            continue
        for key in which:
            val=levels[key][i]
            if np.isfinite(val) and high[i]>val:
                pending_hi[key]=max(high[i],pending_hi.get(key,-math.inf))
        for key in lows:
            val=levels[key][i]
            if np.isfinite(val) and low[i]<val:
                pending_lo[key]=min(low[i],pending_lo.get(key,math.inf))
        direction=0
        extreme=np.nan
        for key,hit in list(pending_hi.items()):
            if np.isfinite(levels[key][i]) and close[i]<levels[key][i] and high[i]-close[i]>=.5*span:
                direction=-1
                extreme=hit
                pending_hi.pop(key)
                break
        if direction==0:
            for key,hit in list(pending_lo.items()):
                if np.isfinite(levels[key][i]) and close[i]>levels[key][i] and close[i]-low[i]>=.5*span:
                    direction=1
                    extreme=hit
                    pending_lo.pop(key)
                    break
        if direction and direction==data["bias"].iat[i]:
            signals[i]=direction
            wick[i]=extreme
    tr=pd.concat([data["high"]-data["low"],
        (data["high"]-data["close"].shift()).abs(),
        (data["low"]-data["close"].shift()).abs()],axis=1).max(axis=1)
    data["atr"]=tr.ewm(alpha=1/14,adjust=False,min_periods=14).mean()
    data["signal"]=signals
    data["sweep_extreme"]=wick
    # Equal-weight typical price after causal H1 swing, deliberately NOT original tick VWAP.
    anchor_keys=np.sort(np.asarray(anchors,dtype="datetime64[ns]"))
    anchor_id=np.searchsorted(anchor_keys,now.to_numpy(dtype="datetime64[ns]"),side="right")
    typical=(data["high"]+data["low"]+data["close"])/3
    data["vwap_proxy"]=typical.groupby(anchor_id).expanding().mean().droplevel(0).to_numpy()
    return data


def simulate(df, *, scenario, spread=.30, slippage=.10, target_r=2.0,
             naive=False):
    """One $10k independent account; stop-first intrabar, next-open only.

    Quote basis is source BID. Long entry ASK=bid+spread, short exit ASK=bid+spread;
    each side also pays explicit adverse slippage; commission roundtrip.
    """
    index=df.index
    b=df
    sig=b["signal"].to_numpy()
    if naive:
        bias=b["bias"].to_numpy()
        sig=np.where((bias!=0)&(bias!=np.roll(bias,1)),bias,0)
        sig[0]=0
    op=b["open"].to_numpy()
    hi=b["high"].to_numpy()
    lo=b["low"].to_numpy()
    cl=b["close"].to_numpy()
    atr=b["atr"].to_numpy()
    wick=b["sweep_extreme"].to_numpy()
    vw=b["vwap_proxy"].to_numpy()
    uk_dates=b["uk_date"].to_numpy()
    cash=START_BALANCE
    balance_trace=[]
    trades=[]
    pending=None
    position=None
    for i in range(1,len(b)):
        can_continue=(index[i]-index[i-1]==pd.Timedelta(minutes=15))
        # No unplanned weekend carry. Exit previous last observable bar close.
        if position and (not can_continue or uk_dates[i]!=uk_dates[i-1]):
            exit_bid=cl[i-1]
            gross=(exit_bid-position["entry_bid"])*position["direction"]*position["qty"]
            charges=spread*position["qty"]+2*slippage*position["qty"]+7*position["lot"]
            pnl=gross-charges
            cash+=pnl
            trades.append({**position,"exit_time":str(index[i-1]+pd.Timedelta(minutes=15))+"Z",
                "exit_bid":round(exit_bid,4),"exit_reason":"session_close",
                "gross_pnl":round(gross,4),"costs":round(charges,4),
                "net_pnl":round(pnl,4),"balance_after":round(cash,4)})
            position=None
        # New entry uses NEXT real 15m open, never signal bar close.
        if position is None and pending and can_continue and uk_dates[i]==uk_dates[i-1]:
            direction,src_bar=pending
            if np.isfinite(atr[src_bar]) and atr[src_bar]>0 and cash>0:
                reference=wick[src_bar]
                if not np.isfinite(reference) and naive:
                    reference=(np.min(lo[max(0,src_bar-8):src_bar+1]) if direction==1
                               else np.max(hi[max(0,src_bar-8):src_bar+1]))
                if np.isfinite(reference):
                    entry_bid=op[i]
                    stop=(min(entry_bid,reference)-atr[src_bar] if direction==1
                          else max(entry_bid,reference)+atr[src_bar])
                    risk=abs(entry_bid-stop)
                    if risk>0:
                        max_lot=min((cash*.01)/(risk*100),
                                    (cash*10)/(entry_bid*100))
                        lot=math.floor(max_lot*100+1e-9)/100
                        if lot>=.01:
                            qty=lot*100
                            target=entry_bid+direction*(risk*target_r) if target_r else None
                            position={"entry_time":str(index[i])+"Z",
                                "signal_time":str(index[src_bar]+pd.Timedelta(minutes=15))+"Z",
                                "entry_bid":round(entry_bid,4),"direction":direction,
                                "lot":lot,"qty":qty,"stop_bid":round(stop,4),
                                "target_bid":round(target,4) if target is not None else None,
                                "risk_usd":round(risk*qty,4)}
        pending=None
        if position:
            d=position["direction"]
            stop=position["stop_bid"]
            target=position["target_bid"]
            exit_bid=None
            reason=""
            # If opening beyond stop, fill at adverse open, not better stop.
            if d==1 and lo[i]<=stop:
                exit_bid=min(stop,op[i])
                reason="stop"
            elif d==-1 and hi[i]>=stop:
                exit_bid=max(stop,op[i])
                reason="stop"
            elif target is not None and ((d==1 and hi[i]>=target) or (d==-1 and lo[i]<=target)):
                exit_bid=target
                reason="target_2R"
            elif target is None and i>0 and (
                (d==1 and cl[i]>=vw[i] and cl[i-1]<vw[i-1]) or
                (d==-1 and cl[i]<=vw[i] and cl[i-1]>vw[i-1])
            ):
                exit_bid=cl[i]
                reason="proxy_vwap_cross"
            if exit_bid is not None:
                gross=(exit_bid-position["entry_bid"])*d*position["qty"]
                # Spread cost counted once, slippage at two execution sides.
                charges=spread*position["qty"]+2*slippage*position["qty"]+7*position["lot"]
                pnl=gross-charges
                cash+=pnl
                trades.append({**position,
                    "exit_time":str(index[i]+pd.Timedelta(minutes=15))+"Z",
                    "exit_bid":round(exit_bid,4),"exit_reason":reason,
                    "gross_pnl":round(gross,4),"costs":round(charges,4),
                    "net_pnl":round(pnl,4),"balance_after":round(cash,4)})
                position=None
        # Mark to hypothetical liquidatable BID+spread equity on every real bar close.
        mark=cash
        if position:
            mark+=(cl[i]-position["entry_bid"])*position["direction"]*position["qty"]
            mark-=spread*position["qty"]+2*slippage*position["qty"]+7*position["lot"]
        balance_trace.append((str(index[i]+pd.Timedelta(minutes=15))+"Z",round(mark,4)))
        if position is None and sig[i]!=0 and i<len(b)-1:
            pending=(int(sig[i]),i)
    if position:
        i=len(b)-1
        exit_bid=cl[i]
        gross=(exit_bid-position["entry_bid"])*position["direction"]*position["qty"]
        charges=spread*position["qty"]+2*slippage*position["qty"]+7*position["lot"]
        pnl=gross-charges
        cash+=pnl
        trades.append({**position,
            "exit_time":str(index[i]+pd.Timedelta(minutes=15))+"Z",
            "exit_bid":round(exit_bid,4),"exit_reason":"end_of_data",
            "gross_pnl":round(gross,4),"costs":round(charges,4),
            "net_pnl":round(pnl,4),"balance_after":round(cash,4)})
    return summarize(trades,balance_trace,cash,scenario)


def summarize(trades,trace,end,scenario):
    wins=[t for t in trades if t["net_pnl"]>0]
    losses=[t for t in trades if t["net_pnl"]<0]
    profit=sum(t["net_pnl"] for t in wins)
    loss=-sum(t["net_pnl"] for t in losses)
    peak=START_BALANCE
    mdd=0.0
    for _,value in trace:
        peak=max(peak,value)
        mdd=min(mdd,(value-peak)/peak)
    monthly=[]
    for month in MONTHS:
        sub=[t for t in trades if min(t["exit_time"][:7], MONTHS[-1])==month]
        net=sum(t["net_pnl"] for t in sub)
        monthly.append({"month":month,"closed_trades":len(sub),
            "wins":sum(t["net_pnl"]>0 for t in sub),
            "losses":sum(t["net_pnl"]<0 for t in sub),
            "net_pnl_usd":round(net,2)})
    result={
        "scenario":scenario,"starting_usd":START_BALANCE,
        "closed_trades":len(trades),"wins":len(wins),"losses":len(losses),
        "breakevens":len(trades)-len(wins)-len(losses),
        "win_rate_pct":round(100*len(wins)/len(trades),3) if trades else None,
        "gross_profit_of_winners_usd":round(profit,2),
        "gross_loss_of_losers_usd":round(loss,2),
        "profit_factor":round(profit/loss,4) if loss else None,
        "net_usd":round(end-START_BALANCE,2),
        "ending_usd":round(end,2),
        "return_pct":round(100*(end/START_BALANCE-1),3),
        "max_marked_drawdown_pct":round(100*mdd,3),
        "total_cost_usd":round(sum(t["costs"] for t in trades),2),
        "monthly":monthly,"trades":trades,"equity_trace":trace,
    }
    if len(trades)!=sum(x["closed_trades"] for x in monthly):
        raise ValueError("Unreconciled S001 monthly trade ledger")
    if abs(result["net_usd"]-sum(x["net_pnl_usd"] for x in monthly))>.12:
        raise ValueError("Monthly net P&L out of tolerance")
    return result


def write_trade_csv(path,trades):
    fields=["signal_time","entry_time","exit_time","direction","entry_bid",
            "exit_bid","lot","qty","stop_bid","target_bid","risk_usd",
            "exit_reason","gross_pnl","costs","net_pnl","balance_after"]
    with path.open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore")
        w.writeheader()
        w.writerows(trades)


def _json_native(value):
    """Convert audited NumPy scalar results without rounding away evidence."""
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, (np.ndarray,)):
        return value.tolist()
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    raise TypeError("Unsupported market/result type: " + type(value).__name__)


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    raw,receipts,market_sha=get_original_gold_history()
    data=signal_table(raw)
    primary=simulate(data,scenario="S001_SWEEP_RECLAIM_FIXED_2R",target_r=2.0)
    vwap_proxy=simulate(data,scenario="S001_SWEEP_RECLAIM_EQUAL_WEIGHT_VWAP_PROXY",
                        target_r=None)
    baseline=simulate(data,scenario="NAIVE_MATCHED_HTF_BIAS_FLIP_CONTROL",
                      target_r=2.0,naive=True)
    stressed=simulate(data,scenario="S001_DOUBLE_SPREAD_AND_SLIPPAGE",
                      spread=.60,slippage=.20,target_r=2.0)
    scenarios={x["scenario"]:x for x in (primary,vwap_proxy,baseline,stressed)}
    report={
        "schema":"aidy.strategy_lab.s001.full_costed_historical.v1",
        "run_status":"FULL_REAL_2025_HISTORICAL_COSTED_MODEL__ORIGINAL_PARITY_NOT_VERIFIED",
        "system_id":"S001","system_title":"GoldEA sweep-and-reclaim",
        "original_source":SOURCE,
        "research_period":"2025-01-01 to 2025-12-31 UTC",
        "gold_data_basis":"original HistData native M1 BID -> complete M15; no synthetic candles",
        "source_sha256":market_sha,
        "source_receipts":receipts,
        "m15_bars":len(data),
        "h1_confirmed_causal_filter":True,
        "h4_confirmed_causal_filter":True,
        "independent_reimplementation":True,
        "source_original_exact_parity":False,
        "original_publisher_pf_1_30_independently_reproduced":False,
        "independently_qualified_profitable":False,
        "oos_untouched_holdout_proved":False,
        "native_mt5_tick_volume_available":False,
        "primary_variant_is_publishers_identical_live_ea":False,
        "modelled_spread_slippage_commission_not_observed_vantage":True,
        "one_percent_of_current_equity_risk_model":True,
        "parameters":PARAMS,
        "source_caveats":[
            "Published GoldEA README reports PF 1.30/183 trades but its dataset and actual MQL5 EA are absent, so our numbers cannot be compared as a source-identical replication.",
            "The publisher uses MT5 tick_volume for VWAP; no native volume is present in our authenticated M1 BID archive. Fixed 2R primary exits do not use VWAP; proxy VWAP exits are a separately labelled sensitivity, never the published author's actual version.",
            "Original public backtester.py unconditionally imports an unpublished optional entry_refinement.py, so no silent execution of untrusted author code.",
            "MT5 broker-specific fill, commission, historical observed ask and swap were not verified. Spread $0.30/oz + $0.10/oz each side slippage + $7/lot roundturn are MODEL COSTS; stressed scenario doubles spread/slippage.",
            "No MT5-native volume means anchored VWAP is NOT validated as an optional signal gate, although publisher's current pipeline describes it as diagnostic, not signal gate.",
            "Causal confirmed H1/H4 structures are projected no earlier than the confirming HTF bar closes; fills at next completed M15 opening and force-flat session end. These correctness decisions can differ from the author's implementation.",
            "All tested 2025 months were within original author's published research period, not an untouched independent OOS holdout. No source-parity claim, GREEN evidence grade or live/paper qualification.",
            "No licence is published in the original repo. Commercial reuse must be separately approved.",
        ],
        "scenarios":scenarios,
        "paper_or_live_orders":0,
    }
    report["report_sha256"]=hashlib.sha256(json.dumps(report,sort_keys=True,separators=(",",":"),allow_nan=False,default=_json_native).encode()).hexdigest()
    (OUT/"s001_2025_full_report.json").write_text(json.dumps(
        report,indent=2,sort_keys=True,allow_nan=False,default=_json_native)+"\n",encoding="utf-8")
    for name,scenario in scenarios.items():
        write_trade_csv(OUT/(name.lower()+".csv"),scenario["trades"])
    with (OUT/"source_verified_2025_m15_bid.csv").open("w",newline="",encoding="utf-8") as f:
        data[["open","high","low","close"]].to_csv(f,index_label="open_time_utc")
    print("AIDY_S001_REAL_2025_COMPLETE",json.dumps({
        "status":report["run_status"],"candles":len(data),
        "market_sha":market_sha,
        "source_job_ids":[x["query_job_id"] for x in receipts],
        "results":{k:{field:v[field] for field in (
           "closed_trades","wins","losses","net_usd","ending_usd",
           "max_marked_drawdown_pct","profit_factor")}
           for k,v in scenarios.items()}
    },sort_keys=True),flush=True)
    return 0


if __name__=="__main__":
    raise SystemExit(main())
