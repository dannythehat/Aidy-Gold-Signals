"""Source-pinned S010 long-only MA12/34 + RSI14, closed-bar, next-open backtest.

Published original (AluminumShark/Tick-Backtest, main.py + src/strategy.py):
  signal +1 when SMA12 crosses SMA34 upward and RSI14<70;
  signal -1 when SMA12 crosses down and RSI14>30;
  remain in the current state otherwise; leveraged 3.28x account.
This is an independent execution implementation on verified bid H1 from real
HistData, not replication of author's unavailable private BID/ASK tick CSVs.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import sqrt

import numpy as np
import pandas as pd

STARTING_USD = 10_000.0
FAST = 12
SLOW = 34
RSI = 14
ORIGINAL_LEVERAGE = 3.28
SOURCE_URL = "https://github.com/AluminumShark/Tick-Backtest"
METHOD = "S010_2025_SOURCE_FIXED_MA12_MA34_RSI14_NEXT_OPEN_v1"


@dataclass(frozen=True)
class Costs:
    label: str
    spread_usd_per_oz: float
    slippage_usd_per_oz_each_side: float
    commission_usd_per_oz_round_trip: float

    def validate(self) -> None:
        vals = (self.spread_usd_per_oz, self.slippage_usd_per_oz_each_side,
                self.commission_usd_per_oz_round_trip)
        if any(v < 0 or not np.isfinite(v) for v in vals):
            raise ValueError("invalid scenario costs")


BASE = Costs("Illustrative base", 0.30, 0.05, 0.07)
STRESS = Costs("Illustrative stress", 0.80, 0.25, 0.14)


def derive_signals(bars: pd.DataFrame) -> pd.DataFrame:
    """Pandas rolling and adjusted EMA match original indicators; no hindsight."""
    required = ("open_time_utc", "open", "high", "low", "close", "m1_count")
    if any(c not in bars for c in required):
        raise ValueError("missing verified source columns")
    x = bars.copy()
    x["open_time_utc"] = pd.to_datetime(x["open_time_utc"], utc=True)
    if x["open_time_utc"].duplicated().any() or not x["open_time_utc"].is_monotonic_increasing:
        raise ValueError("history must be strictly chronological")
    for c in ("open", "high", "low", "close"):
        x[c] = pd.to_numeric(x[c], errors="raise")
    if not ((x["m1_count"] == 60).all()
            and ((x[["open","high","low","close"]] > 0).all().all())
            and (x["high"] >= x[["open","close","low"]].max(axis=1)).all()
            and (x["low"] <= x[["open","close","high"]].min(axis=1)).all()):
        raise ValueError("invalid original native-M1 complete hourly data")
    x["sma_fast"] = x["close"].rolling(FAST).mean()
    x["sma_slow"] = x["close"].rolling(SLOW).mean()
    delta = x["close"].diff()
    gain = delta.where(delta > 0, 0.)
    loss = -delta.where(delta < 0, 0.)
    # Author's _calculate_rsi uses pandas ewm(com=period-1,min_periods=period)
    avg_g = gain.ewm(com=RSI-1, min_periods=RSI).mean()
    avg_l = loss.ewm(com=RSI-1, min_periods=RSI).mean()
    x["rsi"] = 100 - 100/(1 + avg_g/avg_l)
    x["signal"] = 0
    valid = x["sma_slow"].notna() & x["rsi"].notna()
    cross_up = ((x["sma_fast"] > x["sma_slow"])
                & (x["sma_fast"].shift(1) <= x["sma_slow"].shift(1)))
    cross_down = ((x["sma_fast"] < x["sma_slow"])
                  & (x["sma_fast"].shift(1) >= x["sma_slow"].shift(1)))
    x.loc[valid & cross_up & (x["rsi"] < 70), "signal"] = 1
    x.loc[valid & cross_down & (x["rsi"] > 30), "signal"] = -1
    return x.reset_index(drop=True)


def simulate(bars: pd.DataFrame, leverage: float, costs: Costs) -> dict:
    """Marked-equity returns, actual rounded USD and per-oz cost ledger.

    Signal at completed bar i close; fill at bar i+1 open. Fills are modelled
    against BID plus synthetic ASK markup (not observed ask). No margin call,
    overnight financing or forced year-end close is modelled. An unfinished
    position is separately recorded as open/unrealised.
    """
    costs.validate()
    if not 0 < leverage <= 4:
        raise ValueError("leverage out of reviewed range")
    x = derive_signals(bars)
    equity = STARTING_USD
    q = 0.0
    last_bid: float | None = None
    opened: dict | None = None
    trades: list[dict] = []
    marks: list[dict] = []
    sum_cost = 0.0
    sum_gross = 0.0
    # Counts are in-sample closed signals and actions, not fabricated fills.
    signals = {"buy": int((x["signal"]==1).sum()), "sell": int((x["signal"]==-1).sum())}
    for i, row in x.iterrows():
        bid_o = float(row["open"])
        bid_c = float(row["close"])
        time_utc = row["open_time_utc"].isoformat()
        if q and last_bid is not None:
            equity += q * (bid_o - last_bid)  # overnight or weekend gap
        prior = int(x.iloc[i-1]["signal"]) if i else 0
        if q and prior == -1:
            assert opened is not None
            exit_cost = q*(costs.slippage_usd_per_oz_each_side
                           + costs.commission_usd_per_oz_round_trip/2)
            gross = q*(bid_o-float(opened["entry_bid"]))
            # The entry cost has already been paid at the entry instant.
            equity -= exit_cost
            sum_cost += exit_cost
            sum_gross += gross
            total_cost = float(opened["entry_cost_usd"]) + exit_cost
            net = gross-total_cost
            trades.append({
                "id": len(trades)+1,
                "entry_utc": opened["entry_utc"], "exit_utc":time_utc,
                "entry_bid": round(float(opened["entry_bid"]),5),
                "exit_bid":round(bid_o,5), "units_oz":round(q,6),
                "gross_usd":round(gross,4), "spread_slippage_commission_usd":round(total_cost,4),
                "net_usd":round(net,4),
                "holding_hours": round((row["open_time_utc"] - pd.Timestamp(opened["entry_utc"])).total_seconds()/3600,1),
            })
            q=0
            opened=None
        if not q and prior == 1:
            entry_ask = bid_o + costs.spread_usd_per_oz + costs.slippage_usd_per_oz_each_side
            q = max(0.0, equity*leverage/entry_ask)
            entry_cost = q*(costs.spread_usd_per_oz
                            + costs.slippage_usd_per_oz_each_side
                            + costs.commission_usd_per_oz_round_trip/2)
            equity -= entry_cost
            sum_cost += entry_cost
            opened = {"entry_utc":time_utc, "entry_bid":bid_o, "entry_cost_usd":entry_cost}
        if q:
            equity += q*(bid_c-bid_o)
        last_bid=bid_c
        if equity <= 0:
            raise ValueError("theoretical capital exhausted without specified margin/margin-call rule")
        marks.append({"time":time_utc, "equity":round(equity,4),
                      "long_position":bool(q), "bid_close":round(bid_c,5)})
    if len(marks) < 100:
        raise ValueError("insufficient historical candles")
    eq = pd.Series([m["equity"] for m in marks])
    peak = eq.cummax().clip(lower=STARTING_USD)
    drawdown_pct = (eq/peak-1)*100
    monthly = []
    frame = pd.DataFrame(marks)
    frame["dt"] = pd.to_datetime(frame["time"],utc=True)
    frame["month"] = frame["dt"].dt.strftime("%Y-%m")
    prior_equity = STARTING_USD
    for mon, group in frame.groupby("month",sort=True):
        endeq = float(group.iloc[-1]["equity"])
        month_closed=[t for t in trades if t["exit_utc"].startswith(mon)]
        monthly.append({"month":mon,"starting_equity":round(prior_equity,2),
                        "ending_equity":round(endeq,2),
                        "net_change_usd":round(endeq-prior_equity,2),
                        "return_pct":round((endeq/prior_equity-1)*100,3),
                        "closed_trades":len(month_closed)})
        prior_equity=endeq
    net_closed = [t["net_usd"] for t in trades]
    winners = sum(v > 0.00001 for v in net_closed)
    losers = sum(v < -0.00001 for v in net_closed)
    breakeven = len(trades)-winners-losers
    gross_wins = sum(v for v in net_closed if v > 0)
    gross_losses = -sum(v for v in net_closed if v < 0)
    changes = np.asarray(eq.pct_change().fillna(0).to_list())
    # Annualise to 2025 observed bars, not 24x365 untraded/calendar assumptions
    scale = sqrt(len(changes)*365.25/365)
    sd = float(changes.std(ddof=1))
    sharpe = (float(changes.mean())/sd*scale) if sd else None
    last = float(eq.iloc[-1])
    baseline = ((float(x.iloc[-1]["close"])/float(x.iloc[0]["open"])-1)*100)
    o = None
    if q and opened:
        # Marked equity contains this exact open position's unrealised BID P&L.
        o = {"entry_utc":opened["entry_utc"],
             "quantity_oz":round(q,6),
             "unrealised_gross_usd":round(q*(last_bid-float(opened["entry_bid"])),2),
             "will_need_future_opposite_crossover":True}
    return {
        "method":METHOD,"initial_usd":STARTING_USD,
        "leverage":leverage,
        "costs":vars(costs),
        "start_utc":marks[0]["time"],"end_utc":marks[-1]["time"],
        "bars":len(x),"signals":signals,
        "closed_trades":len(trades),"wins":winners,"losses":losers,"breakeven":breakeven,
        "win_rate_pct":round(100*winners/len(trades),2) if trades else None,
        "profit_factor":round(gross_wins/gross_losses,3) if gross_losses>0 else None,
        "ending_marked_equity_usd":round(last,2),
        "net_marked_pnl_usd":round(last-STARTING_USD,2),
        "marked_return_pct":round((last/STARTING_USD-1)*100,3),
        "max_marked_drawdown_pct":round(float(drawdown_pct.min()),3),
        "sharpe_approx":round(sharpe,3) if sharpe is not None else None,
        "gold_buy_hold_1x_pct":round(baseline,3),
        "sum_paid_execution_cost_usd":round(sum_cost,2),
        "sum_closed_trade_gross_usd":round(sum_gross,2),
        "net_closed_trade_usd":round(sum(net_closed),2),
        "open_position":o,"monthly":monthly,
        "trades":trades,"equity":marks,
        "risk_flags":["No strategy stop-loss", "3.28x leverage",
                      "No leverage margin call or financing model",
                      "HistData BID-only, synthetic ASK costs",
                      "Unverified original publisher tick-level replication"],
    }
