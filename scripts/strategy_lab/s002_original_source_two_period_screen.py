"""AIDY S002 source-literal previous-day high/low sweep economic screen.

READ the publisher's two original 2026 Python files rather than the claimed
71.17% "win rate" and do not import or run untrusted remote author code.

Source rules pinned:
  ExtractTrades.py 27f6d366569eb1f2f4f384f2bc187c49086967ea
  TradeSimulation.py d38f4bfdd54fbe742ef2bc9c3de357243201d01e
  README.md 381541d4648c43b1ab8f3c7997998e7c17019c06

Original source is an OPEN-PRICE-ONLY daily state machine:
daily bias = sum(round(open - close, 2)) >= 0 on PREVIOUS date,
LONG sweep when bar open <= prior low, or SHORT >= prior high;
remember source bar-open extreme; enter when bar open retreats past it;
after entry, close once the NEXT observed open again meets the stored
extreme, otherwise source takes an immediate loss. If still open at end
of day, exit last observed bar open. This is source-faithful in SIGNAL
and open price trigger sequence, but fixes fabricated WIN labels by
calculating actual USD mark-to-model liquidation P&L.

NO protective stop price is defined in the original code! Use fixed
0.01 standard gold lot per trade to avoid inventing an ATR/1% stop.
The separate USD $10,000 accounts are MODEL accounts, no trades submitted.

Original candles are precisely those SHA-checked authentic S001 source-
derived M15 BID/ASK receipts, reused instead of redownloading ticks.
Clock used is the AIDY HistData source fixed EST, not unknown author's
Kaggle CSV broker clock. No source OHLC fabrication.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import timedelta, timezone
from pathlib import Path

import pandas as pd

from scripts.strategy_lab.s001_two_period_original_rules import read_source

REFERENCE_USD=10000.0
LOT=0.01
OZ=LOT*100.0
COMMISSION_PER_LOT_USD=7.0
SLIPPAGE_EACH_SIDE_USD_PER_OZ=0.10
FIRST_YEAR="2025"
PERIODS={
    "2025":("2025-01-01","2026-01-01",12),
    "2026":("2026-01-01","2026-10-01",9),
}
SOURCE={
    "repository":"https://github.com/ikeawesom/xauusd-backtest",
    "readme_blob":"381541d4648c43b1ab8f3c7997998e7c17019c06",
    "extract_trades_blob":"27f6d366569eb1f2f4f384f2bc187c49086967ea",
    "trade_simulation_blob":"d38f4bfdd54fbe742ef2bc9c3de357243201d01e",
    "license":"MIT 2026 Ike Lim",
    "original_author_claimed_15m_win_rate_pct":71.17,
    "original_author_claimed_15m_trades":4547,
}
RULES={
    "execution_tf":"M15 source-authenticated full BID/ASK",
    "daily_calendar":"HistData original EST fixed UTC-05 (author CSV timezone not specified)",
    "daily_bias":"AUTHOR CODE sum(round(M15 open - close,2))>=0 for LONG",
    "readme_bias_inconsistent_with_code":True,
    "entry":"original source successive M15 opening-prices past running swept open",
    "source_take_profit":"next M15 open meets sweep open again (not an economic return check)",
    "end_of_session":"last source M15 OPEN each fixed EST calendar day",
    "protective_stop_price_in_author_code":None,
    "sizing":"one constant 0.01 lot per trade, forced by lack of source defined stop",
    "leverage_and_margin":"not broker verified",
    "gold_oz_per_standard_lot":100,
    "slippage_per_side_per_oz":SLIPPAGE_EACH_SIDE_USD_PER_OZ,
    "commission_per_standard_lot_round_trip":COMMISSION_PER_LOT_USD,
    "source_readme_returns_vs_actual_labels_may_disagree":True,
}
DEFAULT_OUT=Path("artifacts/strategy_lab/s002_2025_2026")


def author_daily_bias_and_levels(history):
    """Completed and causally known previous day only; no intraday peeking."""
    local=history.index.tz_localize("UTC").tz_convert(timezone(timedelta(hours=-5)))
    d=history.copy()
    d["source_day"]=pd.Index(local.date)
    # Source uses open minus close, rounded EACH candle to cents before sum.
    d["author_open_minus_close"]=[
        round(float(op-cl),2) for op,cl in zip(d["open"],d["close"])]
    summary=d.groupby("source_day",sort=True).agg(
        pdh=("high","max"),pdl=("low","min"),
        code_bias_sum=("author_open_minus_close","sum"),
        day_rows=("open","count"))
    summary["author_bullish"]=(summary["code_bias_sum"]>=0)
    summary["prev_pdh"]=summary["pdh"].shift(1)
    summary["prev_pdl"]=summary["pdl"].shift(1)
    summary["prev_bullish"]=summary["author_bullish"].shift(1)
    summary["prev_source_day"]=pd.Series(summary.index,index=summary.index).shift(1)
    return d,summary


def true_price_and_costs(entry,exit_row,direction,slippage_mult=1.0,
                         spread_mult=1.0):
    """Observe real BID/ASK at both OPEN ticks, never assert broker fills."""
    entry_bid=float(entry["open"])
    entry_ask=float(entry["observed_open_ask"])
    exit_bid=float(exit_row["open"])
    exit_ask=float(exit_row["observed_open_ask"])
    spread_entry=max(0.,entry_ask-entry_bid)
    spread_exit=max(0.,exit_ask-exit_bid)
    # One spread per full roundtrip, side chosen correctly.
    natural_spread=spread_entry if direction==1 else spread_exit
    gross=(exit_bid-entry_bid)*direction*OZ
    spread_cost=natural_spread*OZ*spread_mult
    slippage_cost=2*SLIPPAGE_EACH_SIDE_USD_PER_OZ*OZ*slippage_mult
    commission=COMMISSION_PER_LOT_USD*LOT
    net=gross-spread_cost-slippage_cost-commission
    return dict(
        gross_usd=round(gross,6),
        observed_spread_cost_usd=round(spread_cost,6),
        two_sided_slippage_usd=round(slippage_cost,6),
        commission_usd=round(commission,6),
        net_usd=round(net,6),
        entry_bid=entry_bid,entry_ask=entry_ask,
        exit_bid=exit_bid,exit_ask=exit_ask,
    )


def simulate(d,summary,year,variant,spread_mult=1.0,slip_mult=1.0):
    start,end,n_months=PERIODS[year]
    cash=REFERENCE_USD
    ledger=[]
    trace=[]
    source_labels={"WIN":0,"LOSE":0,"BE":0}
    # Source's actual scan iterates each candle in date order and tests
    # only OPEN. A loss branch terminates the remaining day entirely.
    for date,day in d.groupby("source_day",sort=True):
        if not start <= str(date) < end:
            continue
        if date not in summary.index or pd.isna(summary.at[date,"prev_pdh"]):
            continue
        prior=summary.loc[date]
        bullish=bool(prior["prev_bullish"])
        direction=1 if bullish else -1
        pdl=float(prior["prev_pdl"]);pdh=float(prior["prev_pdh"])
        swept=False
        sweep_open=None
        entry=None
        entry_time=None
        entry_sweep=None
        price_rows=list(day.iterrows())
        if not price_rows:
            continue
        if variant=="bias_hold_control":
            # Benchmark: same previous-day direction and 0.01 lot,
            # no claimed sweep alpha, first actual open to final open.
            et,er=price_rows[0]
            xt,xr=price_rows[-1]
            if len(price_rows)>=2:
                statement=true_price_and_costs(er,xr,direction,slip_mult,spread_mult)
                cash+=statement["net_usd"]
                ledger.append({
                    "source_day":str(date),"entry_time":str(et)+"Z",
                    "exit_time":str(xt)+"Z","direction":"LONG" if bullish else "SHORT",
                    "lot":LOT,"sweep_point":None,"entry_bid":statement["entry_bid"],
                    "exit_bid":statement["exit_bid"],"source_label":None,
                    "exit_reason":"daily_bias_last_open_baseline",**statement,
                    "balance_after":round(cash,6)})
            trace.append((str(xt)+"Z",round(cash,4)))
            continue
        # Same source state machine, including source's lack of protective stop.
        source_day_broken=False
        for j,(ts,r) in enumerate(price_rows):
            op=float(r["open"])
            if entry is not None:
                # Mark liquidation using the observable source opening quote.
                mark=true_price_and_costs(entry,r,direction,slip_mult,spread_mult)
                trace.append((str(ts)+"Z",round(cash+mark["net_usd"],4)))
                return_to_sweep=(op>=entry_sweep if bullish else op<=entry_sweep)
                if return_to_sweep:
                    # Source calls this a WIN whenever not exactly equal,
                    # irrespective of whether net USD P&L is NEGATIVE.
                    label="BE" if op==entry_sweep else "WIN"
                    reason="source_sweep_point_cross"
                else:
                    label="LOSE"
                    reason="source_adverse_next_open_break_day"
                    source_day_broken=True
                trade={
                    "source_day":str(date),"entry_time":str(entry_time)+"Z",
                    "exit_time":str(ts)+"Z","direction":"LONG" if bullish else "SHORT",
                    "lot":LOT,"sweep_point":round(entry_sweep,5),
                    "source_label":label,"exit_reason":reason,**mark,
                }
                cash+=mark["net_usd"]
                trade["balance_after"]=round(cash,6)
                ledger.append(trade)
                source_labels[label]+=1
                entry=None;entry_time=None
                swept=False;sweep_open=None;entry_sweep=None
                if source_day_broken:
                    break
                continue
            if not swept:
                if (bullish and op<=pdl) or ((not bullish) and op>=pdh):
                    swept=True
                    sweep_open=op
                continue
            # After sweep point source itself uses >= / <= running OPEN,
            # not a strict regain of PDL/PDH as the README implies.
            if (bullish and op>=sweep_open) or ((not bullish) and op<=sweep_open):
                entry=r
                entry_time=ts
                entry_sweep=sweep_open
                trace.append((str(ts)+"Z",round(cash-(
                    float(r["observed_open_spread"])*OZ*spread_mult+
                    2*SLIPPAGE_EACH_SIDE_USD_PER_OZ*OZ*slip_mult+
                    COMMISSION_PER_LOT_USD*LOT),4)))
            else:
                sweep_open=min(sweep_open,op) if bullish else max(sweep_open,op)
        if entry is not None and not source_day_broken:
            # The author closes at the end of the day based on last OPEN.
            exit_time,exit_r=price_rows[-1]
            pricing=true_price_and_costs(entry,exit_r,direction,slip_mult,spread_mult)
            real_gross=pricing["gross_usd"]
            if real_gross>0:label="WIN"
            elif real_gross==0:label="BE"
            else:label="LOSE"
            cash+=pricing["net_usd"]
            ledger.append({
                "source_day":str(date),"entry_time":str(entry_time)+"Z",
                "exit_time":str(exit_time)+"Z",
                "direction":"LONG" if bullish else "SHORT",
                "lot":LOT,"sweep_point":round(entry_sweep,5),
                "source_label":label,"exit_reason":"author_session_last_open",**pricing,
                "balance_after":round(cash,6)})
            source_labels[label]+=1
            trace.append((str(exit_time)+"Z",round(cash,4)))
    wins=[t for t in ledger if t["net_usd"]>0]
    losses=[t for t in ledger if t["net_usd"]<0]
    peak=REFERENCE_USD
    drawdown=0.
    for _,balance in trace:
        peak=max(peak,balance)
        if peak>0:drawdown=min(drawdown,100*(balance/peak-1))
    year_months=[f"{year}-{n:02d}" for n in range(1,n_months+1)]
    monthly=[]
    for m in year_months:
        t=[x for x in ledger if x["source_day"].startswith(m)]
        monthly.append({"month":m,"trades":len(t),
            "true_net_usd":round(sum(x["net_usd"] for x in t),2),
            "real_economic_wins":sum(x["net_usd"]>0 for x in t),
            "real_economic_losses":sum(x["net_usd"]<0 for x in t)})
    author_claimed_wins_negative=[
        t for t in ledger if t["source_label"]=="WIN" and t["net_usd"]<=0
    ]
    pf=sum(t["net_usd"] for t in wins)/-sum(t["net_usd"] for t in losses) if losses else None
    net=round(cash-REFERENCE_USD,2)
    if (sum(x["trades"] for x in monthly)!=len(ledger) or
        abs(net-sum(x["true_net_usd"] for x in monthly))>.15):
        raise ValueError("S002 month/account economic reconciliation failed")
    return {
        "period":year,"scenario":variant,"starting_usd":REFERENCE_USD,
        "ending_usd":round(cash,2),"net_usd":net,
        "return_pct":round(100*net/REFERENCE_USD,4),
        "trades":len(ledger),"wins":len(wins),"losses":len(losses),
        "win_rate_pct":round(100*len(wins)/len(ledger),3) if ledger else None,
        "profit_factor":round(pf,4) if pf is not None else None,
        "max_marked_equity_drawdown_pct":round(drawdown,3),
        "source_reported_label_counts":source_labels,
        "source_WIN_but_nonpositive_net_trades":len(author_claimed_wins_negative),
        "gross_price_pnl_usd":round(sum(t["gross_usd"] for t in ledger),2),
        "total_spread_cost_usd":round(sum(t["observed_spread_cost_usd"] for t in ledger),2),
        "total_slippage_usd":round(sum(t["two_sided_slippage_usd"] for t in ledger),2),
        "total_commission_usd":round(sum(t["commission_usd"] for t in ledger),2),
        "monthly":monthly,
        "trade_ledger":ledger,"equity_trace":trace,
    }


def write_csv(path,records):
    if not records:
        path.write_text("EMPTY SOURCE-FAITHFUL LEDGER\n",encoding="utf-8")
        return
    with path.open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=list(records[0]))
        w.writeheader();w.writerows(records)


def main():
    cli=argparse.ArgumentParser()
    cli.add_argument("--source-root",type=Path,required=True)
    cli.add_argument("--out",type=Path,default=DEFAULT_OUT)
    args=cli.parse_args()
    authenticated,receipts,market_sha=read_source(args.source_root)
    data,daily=author_daily_bias_and_levels(authenticated)
    results={}
    for year,(start,end,_n) in PERIODS.items():
        # all prior source history remains for previous day causality.
        results[year]={
            "source_literal":simulate(data,daily,year,"source_literal"),
            "bias_hold_control":simulate(data,daily,year,"bias_hold_control"),
            "double_costs":simulate(data,daily,year,"double_costs",spread_mult=2,slip_mult=2),
        }
        print("S002_YEAR",json.dumps({"year":year,"results":{
            k:{f:case[f] for f in ("trades","wins","losses","net_usd",
             "profit_factor","max_marked_equity_drawdown_pct",
             "source_WIN_but_nonpositive_net_trades")}
            for k,case in results[year].items()}},sort_keys=True),flush=True)
    packet={
        "schema":"aidy.strategy_lab.s002.literal_source_two_period_first_screen.v1",
        "source":SOURCE,
        "source_exact_signal_mechanics_reimplemented":True,
        "source_raw_author_code_was_executed":False,
        "original_author_trading_win_labels_rejected_as_profit_proof":True,
        "original_readme_strategy_differs_from_actual_author_source":True,
        "real_market_prices_from_authenticated_histdata_bid_ask_ticks":True,
        "reuses_verified_S001_source_conversion_receipts":True,
        "source_receipts":receipts,"source_m15_sha256":market_sha,
        "source_calendar_basis":"HISTDATA_FIXED_EST, NOT PUBLISHER_KAGGLE",
        "frozen_rules":RULES,"periods":results,
        "unseen_sealed_OOS":False,
        "author_risk_stop_missing":True,
        "brokers_and_live_positions_touched":False,
        "broker_native_fill_parity":False,
        "modelled_costs_explicit":True,
        "economic_screen_failed_both_periods":all(
            r["source_literal"]["net_usd"]<=0 for r in results.values()),
        "underperformed_matched_naive_baseline_both":all(
            r["source_literal"]["net_usd"]<=r["bias_hold_control"]["net_usd"]
            for r in results.values()),
        "author_win_label_misclassification_found":sum(
            r["source_literal"]["source_WIN_but_nonpositive_net_trades"]
            for r in results.values())>0,
        "research_decision":"INITIAL_SCREEN_FAIL" if all(
            r["source_literal"]["net_usd"]<=0 for r in results.values())
            else "SOURCE_QUALITY_FAIL_RESEARCH_ONLY",
        "limitations":[
            "Original author README 71.17% 15m win-rate excludes any real spread, slippage, commission; source considers crossing a sweep OPEN a win even where it loses dollars from entry.",
            "Original prior-day bullish test computes sum(open-close), not previous day close>open as README claims. AIDY honors CODE for primary, not silently reversed prose.",
            "No original protective stop exists; unlike S001 there is no valid 1%-of-stop-distance sizing. Use a fixed 0.01 standard lot (1 oz) with independent $10k accounts, no claim of capped 1% risk.",
            "Author source day state uses candle OPEN, not highs/lows. AIDY source-faithfully matches open-trigger logic. Day exit is last observable OPEN, not candle close.",
            "Publisher Kaggle input timezone is not documented. AIDY uses a single known fixed EST HistData-source calendar for BOTH periods.",
            "Author code leaves edge-case bugs (trades marked wins when price-based returns negative, equality case and end-of-day exit labels). AIDY reimplements timing but measures real profits economically.",
            "No verified broker-order, leverage, liquidation margin or live Vantage trading. This is retrospective modelled trading using observed historical HistData quote opens.",
            "Benchmark only measures previous-day bias first to final M15 open at the same fixed 0.01 lot, same quotes and modelled costs.",
            "AIDY reference account 2025 and Jan-Sep2026 reset to $10,000 independently, no look-ahead daily bias or invented sweep prices. Results are not an untouched holdout.",
        ],
    }
    packet["sha256"]=hashlib.sha256(json.dumps(packet,sort_keys=True,
      separators=(",",":"),allow_nan=False).encode()).hexdigest()
    args.out.mkdir(parents=True,exist_ok=True)
    (args.out/"S002_TWO_PERIOD_AIDY_SCREEN.json").write_text(
        json.dumps(packet,indent=2,sort_keys=True,allow_nan=False)+"\n",encoding="utf-8")
    for year in results:
        for kind,case in results[year].items():
            write_csv(args.out/(year+"_"+kind+"_closed_trades.csv"),case["trade_ledger"])
            write_csv(args.out/(year+"_"+kind+"_monthly.csv"),case["monthly"])
    p=[]
    p.append("# S002 GoldEA PDH/PDL | Two-period AIDY initial economic audit")
    p.append("")
    p.append("REAL HistData source BID/ASK M15; author source-literal rules, NOT author self-reported WIN labels.")
    p.append("")
    p.append("| Period | Capital | Trades | Net P&L | Return | End account | True win rate | PF | Max DD | Naive baseline | Double costs | Fake WIN labels |")
    p.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for yr,cases in results.items():
        c=cases["source_literal"]
        p.append("| "+yr+" | $10,000 | "+str(c["trades"])+" | "+str(c["net_usd"])+
            " | "+str(c["return_pct"])+"% | "+str(c["ending_usd"])+
            " | "+str(c["win_rate_pct"])+"% | "+str(c["profit_factor"])+
            " | "+str(c["max_marked_equity_drawdown_pct"])+
            "% | "+str(cases["bias_hold_control"]["net_usd"])+
            " | "+str(cases["double_costs"]["net_usd"])+
            " | "+str(c["source_WIN_but_nonpositive_net_trades"])+" |")
    p.extend(["","## Source-rule defects","The author labels some negative economic trades as WIN by testing against swept-price OPEN instead of actual entry-to-exit return.",
     "Published README previous-day bullish bias description contradicts original Python implementation.",
     "No source-defined protective stop exists. Fixed 0.01 lot is a transparent model-sizing constraint, NOT an invented 1% stop-risk strategy.",
     "Original author 71.17% / 4547 trades on older 2004-2024 Kaggle data is UNVERIFIED in AIDY and excludes costs.",
     "", "## Verdict",packet["research_decision"],"",
     "Original authenticated market-data receipts and full monthly and trade ledgers are packaged with the JSON.","Source SHA256: "+market_sha,"Run SHA256: "+packet["sha256"]])
    (args.out/"S002_INITIAL_SCREEN_RESULT.md").write_text("\n".join(p)+"\n",encoding="utf-8")
    print("S002_TWO_PERIOD_RESULT",json.dumps({
        "status":packet["research_decision"],"sha256":packet["sha256"],
        "years":{yr:{key:cases["source_literal"][key] for key in
              ("trades","wins","losses","net_usd","ending_usd",
               "profit_factor","max_marked_equity_drawdown_pct",
               "source_WIN_but_nonpositive_net_trades")} for yr,cases in results.items()}
    },sort_keys=True),flush=True)


if __name__=="__main__":
    main()
