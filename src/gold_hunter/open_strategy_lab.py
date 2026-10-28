"""Open-source-inspired XAUUSD strategy laboratory, independent of the Bible.

Research-only. Strategy identities are original, mechanically specified adaptations
of well-known public methods; no copy/paste trading bot and no live order API.
The identical replay engine handles every candidate, with no forward-bar signals.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, asdict
from collections import defaultdict

import numpy as np
import pandas as pd

from gold_hunter.bible_engine import validate_h1

SYSTEMS = (
    "DONCHIAN_TREND",
    "EMA_RSI_CROSS",
    "BOLLINGER_REENTRY",
    "ASIA_RANGE_BREAK",
    "ASIA_LIQUIDITY_SWEEP",
)
CANDIDATE_SOURCES = {
    "DONCHIAN_TREND": "AaroNLaU0307/quant-trend-research (Donchian breakout)",
    "EMA_RSI_CROSS": "doaneruby970-hub/gold-trader (EMA, RSI trend research)",
    "BOLLINGER_REENTRY": "succoe/mt5-forx-strategies (Bollinger mean reversion)",
    "ASIA_RANGE_BREAK": "anas1412/orb-backtest-script (Asian opening range)",
    "ASIA_LIQUIDITY_SWEEP": "ajinkyarepale/Gold-London-Liquidity-Backtest (Asia sweep)",
}


@dataclass(frozen=True)
class Settings:
    starting_usd: float = 10000
    risk_fraction: float = .005
    spread_floor: float = .30
    slippage_per_side: float = .05
    roundtrip_commission_per_oz: float = .07
    observed_quote_mode: bool = False
    hold_limit_h1: int = 120

    def validate(self) -> None:
        if not (self.starting_usd > 0 and 0 < self.risk_fraction <= .01
                and 0 <= self.spread_floor <= 20
                and 0 <= self.slippage_per_side <= 20
                and 0 <= self.roundtrip_commission_per_oz <= 20
                and 24 <= self.hold_limit_h1 <= 240):
            raise ValueError("Risk controls outside research limits")


def indicators(bars: pd.DataFrame) -> pd.DataFrame:
    """All features at bar i contain only candles at or before i."""
    df = validate_h1(bars).copy()
    c, h, l = df["close"], df["high"], df["low"]
    tr = pd.concat([(h-l), (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1)
    df["atr"] = tr.rolling(14, min_periods=14).mean()
    for k in (12, 34, 50, 200):
        df[f"ema{k}"] = c.ewm(span=k, adjust=False).mean()
    df["prior20hi"] = h.rolling(20, min_periods=20).max().shift(1)
    df["prior20lo"] = l.rolling(20, min_periods=20).min().shift(1)
    df["sma20"] = c.rolling(20, min_periods=20).mean()
    df["std20"] = c.rolling(20, min_periods=20).std(ddof=0)
    df["bbu"] = df["sma20"] + 2 * df["std20"]
    df["bbl"] = df["sma20"] - 2 * df["std20"]
    change = c.diff()
    gains = change.clip(lower=0).rolling(14, min_periods=14).mean()
    losses = (-change.clip(upper=0)).rolling(14, min_periods=14).mean()
    df["rsi14"] = 100 - 100 / (1 + gains / losses.replace(0, np.nan))
    df["hour"] = df["open_time_utc"].dt.hour
    df["date"] = df["open_time_utc"].dt.strftime("%Y-%m-%d")
    # Asia boundaries are available only AFTER 00:00-05:59 UTC has completed.
    asia = df.loc[df["hour"].between(0,5)].groupby("date").agg(
        asia_high=("high", "max"), asia_low=("low", "min"), count=("high", "size"))
    asia = asia.loc[asia["count"] == 6]
    df = df.join(asia[["asia_high","asia_low"]], on="date")
    return df


def signal_tape(raw: pd.DataFrame) -> tuple[pd.DataFrame, tuple[tuple[dict, ...], ...]]:
    df = indicators(raw)
    output: list[tuple[dict, ...]] = []
    # Prevent repeatedly selecting the same session range in an afternoon.
    prior_session_signals: set[tuple[str,str]] = set()
    for i in range(len(df)):
        row = df.iloc[i]
        candidates = []
        if i < 220 or not np.isfinite(row["atr"]) or row["atr"] <= 0:
            output.append(())
            continue
        prev = df.iloc[i-1]
        atr, close = float(row["atr"]), float(row["close"])
        def add(system: str, side: int, stop_factor: float, reward_multiple: float) -> None:
            if side not in (-1,1):
                return
            stop = close - side * stop_factor * atr
            target = close + side * stop_factor * atr * reward_multiple
            candidates.append({
                "system":system, "side":side, "signal_bar_index":i,
                "signal_utc":(row["open_time_utc"]+pd.Timedelta(hours=1)).isoformat(),
                "stop":round(stop,6), "target":round(target,6),
                "source":CANDIDATE_SOURCES[system],
            })
        if (row["close"] > row["prior20hi"] and
                row["ema50"] > row["ema200"] and prev["close"] <= prev["prior20hi"]):
            add("DONCHIAN_TREND",1,2.0,3.0)
        elif (row["close"] < row["prior20lo"] and
                row["ema50"] < row["ema200"] and prev["close"] >= prev["prior20lo"]):
            add("DONCHIAN_TREND",-1,2.0,3.0)
        if (row["ema12"] > row["ema34"] and prev["ema12"] <= prev["ema34"]
                and row["rsi14"] > 52 and row["ema50"] > row["ema200"]):
            add("EMA_RSI_CROSS",1,1.8,2.5)
        elif (row["ema12"] < row["ema34"] and prev["ema12"] >= prev["ema34"]
                and row["rsi14"] < 48 and row["ema50"] < row["ema200"]):
            add("EMA_RSI_CROSS",-1,1.8,2.5)
        # Confirm a closed-bar reentry through the band; avoid extended trends
        # by requiring current price near its long-term trend reference.
        if abs(close-row["ema200"]) <= 4 * atr:
            if prev["close"] < prev["bbl"] and close > row["bbl"]:
                add("BOLLINGER_REENTRY",1,1.5,2.5)
            elif prev["close"] > prev["bbu"] and close < row["bbu"]:
                add("BOLLINGER_REENTRY",-1,1.5,2.5)
        if (6 <= int(row["hour"]) <= 12 and
                np.isfinite(row.get("asia_high",np.nan))):
            day = str(row["date"])
            high, low = float(row["asia_high"]), float(row["asia_low"])
            if ("ASIA_RANGE_BREAK",day) not in prior_session_signals:
                if close > high and prev["close"] <= high:
                    add("ASIA_RANGE_BREAK",1,1.5,2.5)
                elif close < low and prev["close"] >= low:
                    add("ASIA_RANGE_BREAK",-1,1.5,2.5)
                if any(c["system"]=="ASIA_RANGE_BREAK" for c in candidates):
                    prior_session_signals.add(("ASIA_RANGE_BREAK",day))
            if ("ASIA_LIQUIDITY_SWEEP",day) not in prior_session_signals:
                if row["high"] > high and close < high and close > low:
                    add("ASIA_LIQUIDITY_SWEEP",-1,1.5,2.5)
                elif row["low"] < low and close > low and close < high:
                    add("ASIA_LIQUIDITY_SWEEP",1,1.5,2.5)
                if any(c["system"]=="ASIA_LIQUIDITY_SWEEP" for c in candidates):
                    prior_session_signals.add(("ASIA_LIQUIDITY_SWEEP",day))
        output.append(tuple(candidates))
    return df,tuple(output)


def replay(df: pd.DataFrame, tape: tuple[tuple[dict,...],...],
           systems: tuple[str,...], settings: Settings) -> dict:
    settings.validate()
    if not systems or len(set(systems))!=len(systems) or any(s not in SYSTEMS for s in systems):
        raise ValueError("Unknown/duplicate systems")
    if len(df)!=len(tape):
        raise ValueError("Source/tape length mismatch")
    if settings.observed_quote_mode and not all(
            field in df for field in ("observed_open_ask","observed_open_spread","observed_max_spread")):
        raise ValueError("Original observed ASK evidence required in observed quote mode")
    balance = settings.starting_usd
    position=None
    pending=None
    trades=[]
    marks=[]
    counts=defaultdict(int)
    rejected=defaultdict(int)
    for i in range(len(df)):
        row=df.iloc[i]
        bid_open,bid_high,bid_low,bid_close=(float(row[x]) for x in ("open","high","low","close"))
        if settings.observed_quote_mode:
            # H1 observed ASK open is actual; future hourly max spread is used
            # only for conservative exit bounds, not for entry selection.
            op_spread=max(settings.spread_floor,float(row["observed_open_spread"]))
            ask_open=max(float(row["observed_open_ask"]),bid_open+settings.spread_floor)
            exit_spread=max(op_spread,float(row["observed_max_spread"]))
        else:
            op_spread=exit_spread=settings.spread_floor
            ask_open=bid_open+op_spread
        if pending:
            p=pending;pending=None;side=p["side"]
            entry=(ask_open+settings.slippage_per_side if side==1
                   else bid_open-settings.slippage_per_side)
            risk=side*(entry-p["stop"])
            profitroom=side*(p["target"]-entry)-(exit_spread if side==-1 else 0)-settings.slippage_per_side-settings.roundtrip_commission_per_oz
            if (risk>0 and profitroom/risk>=2 and balance>0):
                risk_per_oz=risk+settings.slippage_per_side+settings.roundtrip_commission_per_oz
                ounces=balance*settings.risk_fraction/risk_per_oz
                position=dict(p,entry=entry,entry_utc=row["open_time_utc"].isoformat(),
                              start_index=i,ounces=ounces,
                              risk_usd=ounces*risk_per_oz)
                counts[p["system"]]+=1
            else:
                rejected["gap_or_cost_rr"]+=1
        if position:
            p=position;side=p["side"]
            stop,target=p["stop"],p["target"]
            ask_high=bid_high+exit_spread
            ask_low=bid_low+exit_spread
            stop_hit=(bid_low<=stop if side==1 else ask_high>=stop)
            target_hit=(bid_high>=target if side==1 else ask_low<=target)
            expired=i-p["start_index"]>=settings.hold_limit_h1
            exit_reason=None
            if stop_hit:
                exit_reason="STOP"
                price=(min(stop,bid_open) if side==1 else max(stop,ask_open))
            elif target_hit:
                exit_reason="TARGET"
                price=target
            elif expired:
                exit_reason="TIME_LIMIT"
                price=bid_close if side==1 else bid_close+exit_spread
            if exit_reason:
                price-=side*settings.slippage_per_side
                pnl=((price-p["entry"])*side-settings.roundtrip_commission_per_oz)*p["ounces"]
                balance+=pnl
                trades.append(dict(p,exit_utc=(row["open_time_utc"]+pd.Timedelta(hours=1)).isoformat(),
                                   exit_reason=exit_reason,exit_price=round(price,6),
                                   pnl_usd=round(pnl,4)))
                position=None
        mark=balance
        if position:
            closing=bid_close if position["side"]==1 else bid_close+exit_spread
            mark+=((closing-position["entry"])*position["side"]-
                   settings.roundtrip_commission_per_oz)*position["ounces"]
        marks.append({"utc":(row["open_time_utc"]+pd.Timedelta(hours=1)).isoformat(),
                      "equity":round(mark,4)})
        if i < len(df)-1 and not position and not pending:
            available=[x for x in tape[i] if x["system"] in systems]
            if available:
                available.sort(key=lambda x:SYSTEMS.index(x["system"]))
                pending=available[0]
                rejected["competition"]+=len(available)-1
    values=np.array([x["equity"] for x in marks])
    peaks=np.maximum.accumulate(np.concatenate([[settings.starting_usd],values]))[1:]
    dd=float(np.min((values/peaks-1)*100))
    pwin=sum(t["pnl_usd"]>0 for t in trades)
    month_pnl=defaultdict(float)
    for t in trades:
        month_pnl[t["exit_utc"][:7]]+=t["pnl_usd"]
    monthly=[]
    running=settings.starting_usd
    for m in sorted(set(df["open_time_utc"].dt.strftime("%Y-%m"))):
        p=month_pnl[m];ret=100*p/running if running else 0
        monthly.append({"month":m,"realized_net_usd":round(p,2),
                        "return_pct_on_starting_balance":round(ret,3)})
        running+=p
    grossplus=sum(max(t["pnl_usd"],0) for t in trades)
    grossminus=-sum(min(t["pnl_usd"],0) for t in trades)
    largest=max((t["pnl_usd"] for t in trades),default=0)
    censored=None
    if position:
        censored={"system":position["system"],"entry_utc":position["entry_utc"],
                  "modelled_unrealized_usd":round(float(values[-1]-balance),2)}
    result={
        "schema":"gold_hunter.open_multisystem.v0", "systems":list(systems),
        "settings":asdict(settings),"source_bars":len(df),
        "closed_trades":len(trades),"wins":pwin,"losses":len(trades)-pwin,
        "win_rate_pct":round(100*pwin/len(trades),2) if trades else None,
        "profit_factor":round(grossplus/grossminus,3) if grossminus else None,
        "net_marked_usd":round(float(values[-1]-settings.starting_usd),2),
        "realized_net_usd":round(balance-settings.starting_usd,2),
        "max_marked_drawdown_pct":round(dd,3),
        "largest_winning_trade_usd":round(largest,2),
        "net_ex_largest_winner_usd":round(float(values[-1]-settings.starting_usd-largest),2),
        "monthly":monthly,
        "months_above_10_pct":sum(x["return_pct_on_starting_balance"]>=10 for x in monthly),
        "selected_counts":dict(counts),"rejections":dict(rejected),
        "censored_open":censored,"trades":trades,
        "notes":["No broker orders","Next-H1-open fills only; same-hour STOP-first",
                 "2026 open ASK observed, hour MAX spread bound is NOT aligned to price extremes",
                 "2025 BID only with assumed spread","No true intrabar order of events",
                 "No swaps/margin/lot rounding","Portfolio has one position total"],
    }
    result["sha256"]=hashlib.sha256(json.dumps(result,sort_keys=True,
                            separators=(",",":"),allow_nan=False).encode()).hexdigest()
    return result


def run_family_matrix(raw: pd.DataFrame, settings: Settings) -> dict:
    df,tape=signal_tape(raw)
    groups=[("ALL_FIVE",SYSTEMS),
            ("TREND_PAIR",SYSTEMS[:2]),
            ("SESSION_PAIR",SYSTEMS[3:]),
            ("MEAN_REVERSION",("BOLLINGER_REENTRY",))]+[(s,(s,)) for s in SYSTEMS]
    return {name:replay(df,tape,arms,settings) for name,arms in groups}
