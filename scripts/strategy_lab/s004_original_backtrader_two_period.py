"""S004: run PINNED original SunriseOgle Backtrader engine on real M5 history.

Research uses the THIRD PARTY CLASS UNMODIFIED for signals/stops/exits.
Wrapper only restricts pre-period warmup, records orders, and supplies
two independent $10k model accounts with declared historical quote-cost
slippage. Never infer author's source 100k result proves 10k feasibility.
No paper/live orders, no fake publisher parity.

Source original Git blob sha1: 8f3289f5e25107e0bf73f1d4f355908b9b96cc82
Original upstream 2026-10-09 git commit: 4ab0213c5e6dd3ffb486a67f9b07bef788cdbd02
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import hashlib
import importlib.util
import json
import math
from pathlib import Path

import backtrader as bt
import pandas as pd

MONTHS=["202412"]+[f"2025{x:02}" for x in range(1,13)]+[f"2026{x:02}" for x in range(1,10)]
DATE_BANDS={
    "2025":{"warmup":"2024-12-01","from":"2025-01-01","to":"2026-01-01","month_count":12},
    "2026":{"warmup":"2025-12-01","from":"2026-01-01","to":"2026-10-01","month_count":9},
}
SOURCE_GIT_BLOB="8f3289f5e25107e0bf73f1d4f355908b9b96cc82"
SOURCE_COMMIT="4ab0213c5e6dd3ffb486a67f9b07bef788cdbd02"
OUT=Path("artifacts/strategy_lab/s004_two_period_source")

def load_original(path):
    data=path.read_bytes()
    blob=hashlib.sha1(b"blob "+str(len(data)).encode()+b"\0"+data).hexdigest()
    if blob!=SOURCE_GIT_BLOB:
        raise ValueError("Upstream author code changed; original source blob fail")
    spec=importlib.util.spec_from_file_location("s004_external_pinned_source",path)
    mod=importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    with contextlib.redirect_stdout(open("/dev/null","w")):
        spec.loader.exec_module(mod)
    p=mod.SunriseOgle.params
    frozen={
        "enable_long_trades":bool(p.enable_long_trades),
        "enable_short_trades":bool(p.enable_short_trades),
        "long_atr_sl_multiplier":float(p.long_atr_sl_multiplier),
        "long_atr_tp_multiplier":float(p.long_atr_tp_multiplier),
        "long_atr_max_threshold":float(p.long_atr_max_threshold),
        "long_entry_window_periods":int(p.long_entry_window_periods),
        "long_pullback_max_candles":int(p.long_pullback_max_candles),
        "risk_fraction":float(p.risk_percent),
        "atr_period":int(p.atr_length),
        "time_filter_enabled":bool(p.use_time_range_filter),
        "contract_size_default":int(p.contract_size),
        "forex_sizing_mode":bool(p.use_forex_position_calc),
        "long_atr_increment_filter":bool(p.long_use_atr_increment_filter),
    }
    expect={"enable_long_trades":True,"enable_short_trades":False,
        "long_atr_sl_multiplier":4.5,"long_atr_tp_multiplier":6.5,
        "long_atr_max_threshold":2.0,
        "long_entry_window_periods":1,"long_pullback_max_candles":3,
        "risk_fraction":.01,"atr_period":10,"time_filter_enabled":False,
        "contract_size_default":100000,"forex_sizing_mode":True,
        "long_atr_increment_filter":True}
    if frozen!=expect:
        raise ValueError("CRITICAL: S004 actual publisher source parameters unexpectedly changed: "+str(frozen))
    # Publisher's verbose reports/plots are NOT execution rules, shut off
    # without changing the original signal, lot-sizing, or exit methods.
    mod.EXPORT_TRADE_REPORTS=False
    mod.TRADE_REPORT_ENABLED=False
    return mod,frozen,blob

def load_m5(root):
    rec=[]
    allrows=[]
    prior=None
    for month in MONTHS:
        folder=root/("s004-source-"+month)
        r=json.loads((folder/"receipt.json").read_text())
        if r["source_period"]!=month or r["time_origin"]!="HistData fixed EST UTC-05, converted to UTC":
            raise ValueError("Noncanonical S004 source month or historical clock")
        with (folder/"m5.csv").open(newline="",encoding="utf-8") as f:
            rows=list(csv.DictReader(f))
        clean=[]
        for x in rows:
            o={"open_time_utc":x["open_time_utc"],
               **{k:float(x[k]) for k in ("open","high","low","close",
                        "observed_open_ask","observed_open_spread","observed_max_spread")},
               **{k:int(x[k]) for k in ("volume","source_m1_minutes")}}
            when=pd.Timestamp(o["open_time_utc"])
            if when.tz is None or when.utcoffset().total_seconds()!=0 or (
                prior is not None and when<=prior):
                raise ValueError("Noncausal original M5 timestamps")
            prior=when
            if (o["source_m1_minutes"]!=5 or o["volume"]<5 or
                o["low"]>min(o["open"],o["close"]) or
                o["high"]<max(o["open"],o["close"]) or
                o["observed_open_ask"]<o["open"]):
                raise ValueError("Bad original BID/ASK complete M5 bar")
            clean.append(o)
        sha=hashlib.sha256(json.dumps(clean,sort_keys=True,separators=(",",":")).encode()).hexdigest()
        if sha!=r["sha256_m5"] or len(clean)!=r["complete_real_m5_bars"]:
            raise ValueError("Market source M5 digest mismatch "+month)
        rec.append(r)
        allrows.extend(clean)
    if len(rec)!=22 or len(allrows)<125000:
        raise ValueError("Original market source year data incomplete")
    d=pd.DataFrame(allrows)
    d["open_time_utc"]=pd.to_datetime(d["open_time_utc"],utc=True)
    d=d.set_index("open_time_utc").sort_index()
    d.index=d.index.tz_localize(None)
    if d.index.has_duplicates:raise ValueError("Market source overlaps")
    market_sha=hashlib.sha256(json.dumps(allrows,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    return d,rec,market_sha

def run_account(year,source,market,scale=1):
    cfg=DATE_BANDS[year]
    sub=market.loc[(market.index>=cfg["warmup"])&(market.index<cfg["to"])].copy()
    if len(sub)<35000:raise ValueError("Insufficient author-native 5min source "+year)
    spread=float(sub["observed_open_spread"].median())
    if not math.isfinite(spread) or spread<=0 or spread>10:
        raise ValueError("Unqualified original source observed spread")
    slippage=(spread/2+0.10)*scale
    # The author's original source assumes self.data._dataname is a filename
    # string and explicitly invokes .upper(). A PandasData feed will CRASH
    # in unmodified _apply_forex_config. Use the identical GenericCSVData
    # adapter configured in the PUBLISHER's own __main__ block. No source
    # trading calculations are patched or disabled.
    csv_path=OUT/("S004_AUTHENTIC_REAL_M5_"+year+".csv")
    with csv_path.open("w",newline="",encoding="utf-8") as h:
        w=csv.writer(h)
        w.writerow(["Date","Time","Open","High","Low","Close","Volume"])
        for ts,x in sub.iterrows():
            w.writerow([ts.strftime("%Y%m%d"),ts.strftime("%H:%M:%S"),
                 x["open"],x["high"],x["low"],x["close"],int(x["volume"])])
    c=bt.Cerebro(stdstats=False,preload=True,runonce=True)
    c.adddata(bt.feeds.GenericCSVData(dataname=str(csv_path),
        dtformat="%Y%m%d",tmformat="%H:%M:%S",
        datetime=0,time=1,open=2,high=3,low=4,close=5,volume=6,
        openinterest=-1,timeframe=bt.TimeFrame.Minutes,compression=5))
    broker=c.broker
    broker.setcash(10000.)
    # One GOLD oz per one Backtrader stocklike unit, 100 oz per standard lot.
    # 7 USD / standard lot roundturn = $0.035 per oz per side.
    broker.setcommission(commission=.035,commtype=bt.CommInfoBase.COMM_FIXED,
                       stocklike=True,leverage=30.)
    broker.set_slippage_fixed(slippage,slip_open=True,slip_match=True)
    from_ts=pd.Timestamp(cfg["from"])
    class SourceFaithfulAudit(source.SunriseOgle):
        def __init__(self):
            super().__init__()
            self.audit_closed=[]
            self.audit_rejected=[]
            self.audit_orders_filled=[]
            self.audit_equity=[]
        def next(self):
            stamp=pd.Timestamp(bt.num2date(self.data.datetime[0]))
            if stamp<from_ts:
                return  # indicator warmup only; NO December 2024/25 account trade.
            super().next()
            self.audit_equity.append((stamp.isoformat(),float(self.broker.getvalue())))
        def notify_order(self,order):
            if order.status in (order.Margin,order.Rejected):
                self.audit_rejected.append({
                    "date":str(bt.num2date(self.data.datetime[0])),
                    "status":order.getstatusname(),"units":float(order.size),
                    "requested_gross_notional_usd":float(abs(order.size)*self.data.open[0]),
                })
            if order.status==order.Completed:
                self.audit_orders_filled.append({
                    "date":str(bt.num2date(self.data.datetime[0])),
                    "side":"BUY" if order.isbuy() else "SELL",
                    "units":float(order.executed.size),
                    "fill":float(order.executed.price),
                    "fee":float(order.executed.comm),
                })
            super().notify_order(order)
        def notify_trade(self,trade):
            if trade.isclosed:
                self.audit_closed.append({
                    "close_time":str(bt.num2date(self.data.datetime[0])),
                    "price_pnl_usd":round(float(trade.pnl),6),
                    "net_pnl_usd":round(float(trade.pnlcomm),6),
                    "total_commission_usd":round(float(trade.commission),6),
                    "trade_bar_length":int(trade.barlen),
                })
            super().notify_trade(trade)
    c.addstrategy(SourceFaithfulAudit,verbose_debug=False,print_signals=False,
                 plot_result=False)
    with open(OUT/(year+f"_source_stdout_stress{scale}.txt"),"w",encoding="utf-8") as output:
        with contextlib.redirect_stdout(output):
            records=c.run()
    a=records[0]
    cash=float(a.broker.getcash())
    eq=float(a.broker.getvalue())
    pnl=eq-10000.
    closed=a.audit_closed
    gains=[x["net_pnl_usd"] for x in closed if x["net_pnl_usd"]>0]
    losses=[x["net_pnl_usd"] for x in closed if x["net_pnl_usd"]<0]
    peak=10000.
    dd=0.
    for _,value in a.audit_equity:
        peak=max(peak,value)
        dd=min(dd,100.*(value-peak)/peak)
    monthly=[]
    for n in range(1,cfg["month_count"]+1):
        label=f"{year}-{n:02d}"
        t=[x for x in closed if x["close_time"][:7]==label]
        monthly.append({
            "month":label,"closed_trades":len(t),
            "closed_net_pnl_usd":round(sum(x["net_pnl_usd"] for x in t),2),
            "win_count":sum(x["net_pnl_usd"]>0 for x in t),
        })
    if sum(x["closed_trades"] for x in monthly)!=len(closed):
        raise ValueError("S004 original Backtrader closed monthly book inconsistent")
    margin_rejects=sum(x["status"]=="Margin" for x in a.audit_rejected)
    result={
        "year":year,"broker_model_30x_leverage":True,
        "author_source_SunriseOgle_subclass_only_for_logging_and_warmup":True,
        "slippage_scale":scale,
        "source_observed_median_spread_usd_per_oz":round(spread,5),
        "model_slippage_each_side_including_half_spread":round(slippage,5),
        "native_source_date_band":cfg,
        "starting_usd":10000.,"end_equity_usd":round(eq,2),
        "end_cash_usd":round(cash,2),
        "net_model_equity_usd":round(pnl,2),
        "return_pct":round(pnl/100,4),
        "closed_trades":len(closed),
        "wins":len(gains),"losses":len(losses),
        "profit_factor":round(sum(gains)/-sum(losses),4) if losses else None,
        "max_marked_drawdown_pct":round(dd,4),
        "long_entries_filled":sum(x["side"]=="BUY" for x in a.audit_orders_filled),
        "orders_with_margin_rejections":margin_rejects,
        "orders_rejected_or_margin":len(a.audit_rejected),
        "closed_trades_ledger":closed,
        "filled_orders":a.audit_orders_filled,
        "margin_rejections":a.audit_rejected,
        "monthly":monthly,
        "net_account_less_sum_closed_dollars":round(pnl-sum(x["net_pnl_usd"] for x in closed),2),
        "open_position_units":float(a.position.size),
    }
    print("S004_ORIGINAL_BACKTRADER_ACTUAL",json.dumps({
        "year":year,"cost_factor":scale,
        "trades":result["closed_trades"],"profit_factor":result["profit_factor"],
        "ending_usd":result["end_equity_usd"],"net_usd":result["net_model_equity_usd"],
        "margin_rejections":margin_rejects,
        "open_position_units":result["open_position_units"]},sort_keys=True),flush=True)
    return result

def rows_csv(path,rows):
    if not rows:
        path.write_text("NO RECORDS\n",encoding="utf-8")
        return
    with path.open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

def main():
    global OUT
    cli=argparse.ArgumentParser()
    cli.add_argument("--original-source",required=True,type=Path)
    cli.add_argument("--source-root",required=True,type=Path)
    cli.add_argument("--output",type=Path,default=OUT)
    a=cli.parse_args()
    OUT=a.output
    OUT.mkdir(parents=True,exist_ok=True)
    source,params,sha=load_original(a.original_source)
    market,receipts,market_sha=load_m5(a.source_root)
    accounts={}
    for year in DATE_BANDS:
        accounts[year]={
            "native_source_30x_model":run_account(year,source,market,1),
            "double_source_spread_plus_slippage":run_account(year,source,market,2),
        }
    raw={
        "schema":"aidy.s004.source_exact_native_backtrader.two_period.v1",
        "source_repo":"https://github.com/ilahuerta-IA/backtrader-pullback-window-xauusd",
        "original_git_commit":SOURCE_COMMIT,
        "original_blob_sha":sha,
        "actual_frozen_code_defaults":params,
        "readme_default_parameters_matched":False,
        "source_history_timeframe":"M5 real original HistData ticks, not M15",
        "original_22_month_source_receipts":receipts,
        "derived_m5_combined_sha256":market_sha,
        "starting_capital_each":10000,
        "source_size_minimum_one_contract":True,
        "source_contract_100_gold_ounces_per_contract":True,
        "original_author_100k_account_comparison_not_identical":True,
        "unmodified_source_strategy_signal_stop_entry_logic":True,
        "source_author_input_data_same_as_histdata":False,
        "MT5_broker_fill_parity":False,
        "costs_modelled_not_broker_receipts":True,
        "paper_trading_approved":False,
        "accounts":accounts,
    }
    possible=all(accounts[y]["native_source_30x_model"]["closed_trades"]>0
                 and accounts[y]["native_source_30x_model"]["net_model_equity_usd"]>0
                 for y in accounts)
    stressed=all(accounts[y]["double_source_spread_plus_slippage"]["net_model_equity_usd"]>0
                 for y in accounts)
    raw["economic_first_screen"] = "PASS_INITIAL_ONLY_FURTHER_VERIFICATION_REQUIRED" if possible and stressed else "FAILED_OR_INCONCLUSIVE"
    OUT.mkdir(parents=True,exist_ok=True)
    data=json.dumps(raw,allow_nan=False,indent=2,sort_keys=True)
    (OUT/"S004_2025_2026_NATIVE_SOURCE_RESEARCH.json").write_text(data+"\n",encoding="utf-8")
    for year,v in accounts.items():
        for key,case in v.items():
            rows_csv(OUT/(year+"_"+key+"_trade_ledger.csv"),case["closed_trades_ledger"])
            rows_csv(OUT/(year+"_"+key+"_monthly.csv"),case["monthly"])
    (OUT/"S004_INITIAL_SCREEN.md").write_text(
      "# S004 | PINNED native Backtrader first screen\n\n"+
      "Readme + source discrepancy: executable LONG-only, ATR max 2, long stop 4.5x ATR, TP 6.5x ATR, one-bar long window. Original backtest uses $100k, our independent model requires $10k. Source position sizing floors contracts at ONE × 100 gold ounces, potentially violating 1% desired nominal risk and creating margin rejections. No source parameter tuning.\n\n"+
      "| Period | Case | Closed | Rejected margin | Net model USD | End equity | PF | Marked DD % |\n"+
      "|---|---|---:|---:|---:|---:|---:|---:|\n"+
      "".join(f"| {year} | {name} | {v['closed_trades']} | {v['orders_with_margin_rejections']} | {v['net_model_equity_usd']} | {v['end_equity_usd']} | {v['profit_factor']} | {v['max_marked_drawdown_pct']} |\n"
        for year,cs in accounts.items() for name,v in cs.items())+
      "\n**Decision:** "+raw["economic_first_screen"]+
      "\n\nReal original source M5, observed source spread median, cost model, no MT5/Vantage order equivalence. No PDF if screen fails.\n",encoding="utf-8")
    print("S004_FINAL_SOURCE_FIRST_SCREEN",json.dumps({
        "verdict":raw["economic_first_screen"],"models":{
          year:{case:{k:c[k] for k in ("closed_trades","net_model_equity_usd",
            "profit_factor","max_marked_drawdown_pct","orders_with_margin_rejections")}
           for case,c in cs.items()} for year,cs in accounts.items()}
    },sort_keys=True),flush=True)

if __name__=="__main__":main()
