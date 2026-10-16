"""Frozen CROSSFIRE S010 research variants; no parameter search or paper orders.

Baseline: published MA12/34 RSI14 long-only, 3.28x, unchanged.
ATR: SAME original entries and exits plus fixed INITIAL stop 3x previous
closed H1 ATR(14), filled on BID at the stop or worse gap-open BID.
Trend: original entry only if previous closed H1 close > prior SMA200
and prior SMA200 exceeds value 24 closed H1 candles earlier.

All three use the SAME illustrative BID + synthetic spread/slip/commission
scheme as the frozen 2025 S010 model. This is not historical executable
Vantage ASK, interest/swap, margin-call or forced liquidation replication.
"""
from __future__ import annotations

from math import isfinite

import pandas as pd

from aidy.strategy_lab_s010_backtest import (
    BASE,
    ORIGINAL_LEVERAGE,
    STARTING_USD,
    Costs,
    derive_signals,
    simulate,
)

VARIANT_KEYS = ("original", "atr3_initial_stop", "sma200_rising_filter")
RESEARCH_CONTRACT = "crossfire.s010.2026.frozen_original_atr3_sma200_rising_v1"


def replay(raw: pd.DataFrame, variant: str, *, costs: Costs = BASE) -> dict:
    """No access to future bars or intrabar close; all fills are after signal."""
    if variant not in VARIANT_KEYS:
        raise ValueError("Not a pre-registered variant")
    if variant == "original":
        return simulate(raw, ORIGINAL_LEVERAGE, costs)
    costs.validate()
    df = derive_signals(raw)
    tr = pd.concat(
        (
            df["high"] - df["low"],
            (df["high"] - df["close"].shift(1)).abs(),
            (df["low"] - df["close"].shift(1)).abs(),
        ), axis=1,
    ).max(axis=1)
    df["atr_pre_entry"] = tr.rolling(14).mean().shift(1)
    df["sma200"] = df["close"].rolling(200).mean()
    df["filter_ok"] = (
        (df["close"] > df["sma200"])
        & (df["sma200"] > df["sma200"].shift(24))
    )
    equity = STARTING_USD
    qty = 0.0
    last_bid = None
    open_trade = None
    trades = []
    events = []
    paid_cost = 0.0
    stop_events = 0
    filtered_entries = 0
    for i, row in df.iterrows():
        opening_bid = float(row["open"])
        close_bid = float(row["close"])
        at = row["open_time_utc"].isoformat()
        if qty and last_bid is not None:
            equity += qty * (opening_bid - last_bid)
        previous_signal = int(df.iloc[i - 1]["signal"]) if i else 0

        def close_trade(exit_bid: float, reason: str) -> None:
            nonlocal qty, open_trade, equity, paid_cost, stop_events
            assert open_trade is not None
            paid_at_exit = qty * (
                costs.slippage_usd_per_oz_each_side
                + costs.commission_usd_per_oz_round_trip / 2
            )
            # If exit is intrabar: account equity is already marked to OPEN;
            # realise the additional BID move from open to the exit.
            equity += qty * (exit_bid - opening_bid)
            equity -= paid_at_exit
            paid_cost += paid_at_exit
            gross = qty * (exit_bid - open_trade["entry_bid"])
            net = gross - open_trade["paid_entry_cost"] - paid_at_exit
            trades.append({
                "id": len(trades) + 1,
                "entry_utc": open_trade["entry_utc"],
                "exit_utc": at,
                "exit_reason": reason,
                "entry_bid": round(open_trade["entry_bid"], 5),
                "exit_bid": round(exit_bid, 5),
                "units_oz": round(qty, 6),
                "gross_usd": round(gross, 4),
                "net_usd": round(net, 4),
                "execution_cost_usd": round(
                    open_trade["paid_entry_cost"] + paid_at_exit, 4,
                ),
            })
            if reason == "initial_atr_stop":
                stop_events += 1
            qty = 0.0
            open_trade = None

        if qty and previous_signal == -1:
            close_trade(opening_bid, "original_opposite_crossover")

        if not qty and previous_signal == 1:
            can_enter = True
            if variant == "sma200_rising_filter":
                can_enter = bool(df.iloc[i - 1]["filter_ok"])
                if not can_enter:
                    filtered_entries += 1
            if can_enter:
                atr = float(row["atr_pre_entry"])
                if variant == "atr3_initial_stop" and (
                    not isfinite(atr) or atr <= 0
                ):
                    raise ValueError("No causal 14-bar prior ATR for initial stop")
                entry_ask = (
                    opening_bid + costs.spread_usd_per_oz
                    + costs.slippage_usd_per_oz_each_side
                )
                qty = equity * ORIGINAL_LEVERAGE / entry_ask
                entry_cost = qty * (
                    costs.spread_usd_per_oz
                    + costs.slippage_usd_per_oz_each_side
                    + costs.commission_usd_per_oz_round_trip / 2
                )
                equity -= entry_cost
                paid_cost += entry_cost
                stop = (
                    opening_bid - 3.0 * atr
                    if variant == "atr3_initial_stop" else None
                )
                if stop is not None and stop <= 0:
                    raise ValueError("Invalid frozen initial ATR stop")
                open_trade = {
                    "entry_utc": at,
                    "entry_bid": opening_bid,
                    "paid_entry_cost": entry_cost,
                    "initial_stop_bid": stop,
                }

        if qty:
            stop = open_trade["initial_stop_bid"]
            if stop is not None and float(row["low"]) <= stop:
                # With actual OHLC we can know stop was crossed, not EXACT
                # executable tick/ASK; no favourable slip permitted here.
                close_trade(min(opening_bid, stop), "initial_atr_stop")
            else:
                equity += qty * (close_bid - opening_bid)
        last_bid = close_bid
        if not isfinite(equity) or equity <= 0:
            raise ValueError(
                "Capital exhausted or invalid; no verified broker stopout rule"
            )
        events.append({
            "time": at,
            "equity": round(equity, 4),
            "long_position": bool(qty),
            "bid_close": round(close_bid, 5),
        })
    if not events:
        raise ValueError("Empty source replay")
    series = pd.Series([x["equity"] for x in events])
    peak = series.cummax().clip(lower=STARTING_USD)
    dd = (series / peak - 1) * 100
    gains = [t["net_usd"] for t in trades if t["net_usd"] > 0]
    losses = [t["net_usd"] for t in trades if t["net_usd"] < 0]
    month_last = {}
    for mark in events:
        month_last[mark["time"][:7]] = mark["equity"]
    monthly = []
    before = STARTING_USD
    for month, value in sorted(month_last.items()):
        monthly.append({
            "month": month,
            "starting_equity": round(before, 2),
            "ending_equity": round(value, 2),
            "net_change_usd": round(value - before, 2),
            "return_pct": round((value / before - 1) * 100, 3),
            "closed_trades": sum(t["exit_utc"].startswith(month) for t in trades),
        })
        before = value
    return {
        "variant": variant,
        "original_entry_parameters_unchanged": True,
        "test_cost_model": vars(costs),
        "start_usd": STARTING_USD,
        "leverage": ORIGINAL_LEVERAGE,
        "bars": len(df),
        "closed_trades": len(trades),
        "wins": len(gains),
        "losses": len(losses),
        "win_rate_pct": round(100 * len(gains) / len(trades), 2) if trades else None,
        "profit_factor": (
            round(sum(gains) / -sum(losses), 3) if losses else None
        ),
        "ending_marked_equity_usd": round(equity, 2),
        "net_marked_pnl_usd": round(equity - STARTING_USD, 2),
        "marked_return_pct": round((equity / STARTING_USD - 1) * 100, 3),
        "max_marked_drawdown_pct": round(float(dd.min()), 3),
        "sum_paid_execution_cost_usd": round(paid_cost, 2),
        "stop_events": stop_events,
        "filtered_original_buy_signals": filtered_entries,
        "open_position": {
            "entry_utc": open_trade["entry_utc"],
            "quantity_oz": round(qty, 6),
        } if qty and open_trade else None,
        "monthly": monthly,
        "trades": trades,
        "equity": events,
        "limitations": [
            "Observed HistData BID, source ASK recorded but not used as Vantage execution",
            "Synthetic bid/ask fill spread + slip + fee scenario",
            "No swap/financing or Vantage margin liquidation model",
            "H1 ATR stop uses low/stop or worse gap open, no tick-level stop-price parity",
            "2026 holdout is only calendar Jan-Sep 2026",
        ],
    }
