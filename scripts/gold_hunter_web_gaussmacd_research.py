"""Independent WEB-DISCOVERED GoldEA challenge via AIDY authentic BID/ASK data.

Upstream: Vinu-Kevin-Diesel/AI-Quant-Strategy-Lab,
mq5/Gold_GaussMACD_EA.mq5 blob 5edca9d12a55ee5168cc5e66bb5e1737216e95d4.
MIT. Source: 100 period 4-pole Gaussian trend, MACD(12,26,9) turning
histogram, RSI14(80/20), ATR14(2.5 stop/5.0 TP), H1 UTC 07-20,
0.01 standard lot (one ounce for assumed 100oz contract), USD60 max SL,
no pyramiding. Independent isolated $1000 reference account per year.

LIMITS: MQL5-native Gaussian CopyClose rolling-5000 warmup, MT5 indicator
seeds/signal smoothing, bid/ask quote conventions, network/fills, financing,
stop-order tick chronology, lot/margin provider parity NOT certified. Gaussian
uses full-history recursive approximation, not rolling 5000 exact identity.
This is candidate falsification, never a claim of publisher source parity.
No broker orders. Reuse existing AIDY original authenticated encrypted caches.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.gold_hunter_2023_2024_causal_research import read_month

UPSTREAM = "https://github.com/Vinu-Kevin-Diesel/AI-Quant-Strategy-Lab"
SOURCE_BLOB_SHA = "5edca9d12a55ee5168cc5e66bb5e1737216e95d4"
YEARS = (2023, 2024, 2025)
YEAR_START_BALANCE = 1000.0
OUNCES = 1.0  # source fixed 0.01 lot assumes 100oz contract size; unverified for owner broker
LEVERAGE = 20  # original source's specific reference account
GAUSS_PERIOD = 100
GAUSS_POLES = 4


def digest(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def true_wilder(values: pd.Series, period: int) -> pd.Series:
    """Wilder SMA seed, recursive 1/n smoothing, NaNs preserved."""
    raw = values.to_numpy(dtype=float)
    out = np.full(len(raw), np.nan)
    if len(raw) < period:
        return pd.Series(out, index=values.index)
    if not np.isfinite(raw[:period]).all():
        return pd.Series(out, index=values.index)
    out[period-1] = float(raw[:period].mean())
    for i in range(period, len(raw)):
        out[i] = (out[i-1] * (period - 1) + raw[i]) / period
    return pd.Series(out, index=values.index)


def gauss4(close: pd.Series):
    """Frozen author alpha/poles; full prefix vs native sliding max 5000."""
    beta = (1 - np.cos(2 * np.pi / GAUSS_PERIOD)) / (
        2**(1 / GAUSS_POLES) - 1)
    alpha = -beta + np.sqrt(beta**2 + 2*beta)
    x = close.astype(float)
    for _ in range(GAUSS_POLES):
        x = x.ewm(alpha=alpha, adjust=False).mean()
    return x


def prices(root: Path, year: int):
    """Strict 60-observation hourly BID/ASK, no synthetic candles."""
    if year not in YEARS:
        raise ValueError("year not in preregistered 2023-2025")
    periods = ([f"{year-1}12"] if year in (2024, 2025) else []) + [
        f"{year}{m:02d}" for m in range(1, 13)
    ]
    blocks, receipts = [], []
    for p in periods:
        frame, receipt = read_month(root, p)
        blocks.append(frame)
        receipts.append(receipt)
    minute = pd.concat(blocks, ignore_index=True)
    minute = minute.loc[minute["open_time_utc"].dt.year == year].copy()
    if minute.empty or minute["open_time_utc"].duplicated().any():
        raise ValueError("Missing or repeated M1 originals")
    minute = minute.sort_values("open_time_utc").set_index("open_time_utc")
    h = minute.resample("1h").agg(
        open=("bid_o", "first"), high=("bid_h", "max"),
        low=("bid_l", "min"), close=("bid_c", "last"),
        ask_o=("ask_o", "first"), ask_h=("ask_h", "max"),
        ask_l=("ask_l", "min"), ask_c=("ask_c", "last"),
        m1_count=("bid_o", "count"),
    )
    h = h[h["m1_count"] == 60].copy()
    if len(h) < 4500 or set(h.index.month) != set(range(1, 13)):
        raise ValueError("Historical year is not covered by 12 authentic months")
    if (not np.isfinite(h.to_numpy()).all()
            or (h["ask_o"] < h["open"]).any()
            or (h["ask_h"] < h["high"]).any()
            or (h["ask_l"] < h["low"]).any()):
        raise ValueError("Invalid actual BID/ASK geometry")
    return h, {"year": year, "original_months": receipts,
               "observed_complete_h1": len(h),
               "original_m1_rows": len(minute),
               "h1_sha256": hashlib.sha256(h.to_csv().encode()).hexdigest(),
               "source_not_sealed_oos": True}


def indicators(h):
    x = h.copy()
    c = x["close"]
    tr = pd.concat([x["high"]-x["low"], (x["high"]-c.shift()).abs(),
                    (x["low"]-c.shift()).abs()], axis=1).max(axis=1)
    x["atr"] = true_wilder(tr, 14)
    delta = c.diff().fillna(0)
    gains = true_wilder(delta.clip(lower=0), 14)
    losses = true_wilder((-delta).clip(lower=0), 14)
    rs = gains / losses.replace(0, np.nan)
    rsi = 100 - 100 / (1 + rs)
    # MT5/Wilder zero-loss semantics: 100 for all-up, 0 for all-down, 50 flat.
    rsi = rsi.mask((losses == 0) & (gains > 0), 100)
    rsi = rsi.mask((gains == 0) & (losses > 0), 0)
    rsi = rsi.mask((gains == 0) & (losses == 0), 50)
    x["rsi"] = rsi
    x["gauss"] = gauss4(c)
    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    macd = ema12-ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    x["hist"] = macd - signal
    return x


def signal_at(x, i):
    """Only fully closed H1 bar i and previous bar i-1 are considered."""
    if i < GAUSS_PERIOD*3:
        return 0
    row, previous = x.iloc[i], x.iloc[i-1]
    if (not np.isfinite(row[["atr", "rsi", "gauss", "hist"]]).all()
            or row["atr"] < .50 or row["atr"] <= 0
            or not 7 <= x.index[i].hour < 20):
        return 0
    rise = row["gauss"] > previous["gauss"]
    fall = row["gauss"] < previous["gauss"]
    up = row["hist"] > previous["hist"] and row["hist"] > -.5
    down = row["hist"] < previous["hist"] and row["hist"] < .5
    if rise and up and row["close"] > row["gauss"] and row["rsi"] <= 80:
        return 1
    if fall and down and row["close"] < row["gauss"] and row["rsi"] >= 20:
        return -1
    return 0


def simulate(ind, *, slippage, commission):
    """Separate source-config fixed-lot one-ounce account, conservative stop first."""
    capital = YEAR_START_BALANCE
    peak = capital
    deepest_dd = 0.0
    pending = None
    position = None
    trades = []
    monthly = {}
    counts = {"signals": 0, "rejected_margin": 0, "skipped_occupied": 0}
    for i in range(len(ind)):
        row = ind.iloc[i]
        time = ind.index[i]
        bid_open, ask_open = float(row["open"]), float(row["ask_o"])
        if pending is not None and position is None:
            side, atr, signal_utc = pending
            entry = (ask_open + slippage if side == 1
                     else bid_open - slippage)
            stopdist = min(2.5 * atr, 60.0)
            targetdist = stopdist * 2
            margin_required = entry*OUNCES/LEVERAGE
            if capital <= 0 or margin_required > capital*.80:
                counts["rejected_margin"] += 1
            else:
                position = {
                    "side": side, "entry": entry,
                    "sl": entry - side*stopdist,
                    "tp": entry + side*targetdist,
                    "signal_utc": signal_utc,
                    "entry_utc": time.isoformat(),
                    "starting_balance": capital,
                    "model_risk_usd": stopdist*OUNCES + 2*slippage*OUNCES
                                      + commission*OUNCES,
                }
            pending = None
        if position is not None:
            p = position
            s = p["side"]
            if s == 1:
                hitstop = row["low"] <= p["sl"]
                hittarget = row["high"] >= p["tp"]
                exit_open = bid_open
            else:
                hitstop = row["ask_h"] >= p["sl"]
                hittarget = row["ask_l"] <= p["tp"]
                exit_open = ask_open
            price = None
            reason = None
            if hitstop:
                price = min(p["sl"], exit_open) if s == 1 else max(p["sl"], exit_open)
                reason = "STOP_FIRST_CONSERVATIVE"
            elif hittarget:
                price = p["tp"]
                reason = "TARGET"
            if price is not None:
                price = price - s*slippage
                pnl = (price-p["entry"])*s*OUNCES-commission*OUNCES
                capital += pnl
                trade = dict(p, exit_utc=(time+pd.Timedelta(hours=1)).isoformat(),
                             exit_price=round(price, 6), exit_reason=reason,
                             pnl_usd=round(pnl, 6))
                trades.append(trade)
                month = trade["exit_utc"][:7]
                monthly[month] = monthly.get(month, 0.0)+pnl
                position = None
        mark = capital
        if position:
            s = position["side"]
            exit_quote = float(row["close"] if s == 1 else row["ask_c"])
            mark += (exit_quote-position["entry"])*s*OUNCES-commission*OUNCES
        peak = max(peak, mark)
        deepest_dd = min(deepest_dd, 100*(mark/peak-1))
        # MQL5 signal on bar close, pending for next bar open; none if occupied.
        if i < len(ind)-1:
            new_signal = signal_at(ind, i)
            if new_signal:
                counts["signals"] += 1
                if position is None and pending is None:
                    pending = (new_signal, float(row["atr"]),
                               (time+pd.Timedelta(hours=1)).isoformat())
                else:
                    counts["skipped_occupied"] += 1
    expected = capital-YEAR_START_BALANCE
    actual = sum(t["pnl_usd"] for t in trades)
    if abs(expected-actual) > .001:
        raise ValueError("Cash ledger does not reconcile")
    bymonth = [{"month": str(yr)+"-"+f"{m:02d}",
                "closed_pnl_usd": round(monthly.get(str(yr)+"-"+f"{m:02d}", 0), 4)}
               for yr in [ind.index[0].year] for m in range(1, 13)]
    result = {
        "source": UPSTREAM, "source_mq5_blob_sha": SOURCE_BLOB_SHA,
        "model": "GAUSSMACD_AUTHOR_DEFAULTS_APPROXIMATE_INDICATOR_REPLAY",
        "starting_usd": YEAR_START_BALANCE,
        "closed": len(trades), "wins": sum(t["pnl_usd"] > 0 for t in trades),
        "realized_net_usd": round(expected, 2),
        "ending_balance_usd": round(capital, 2),
        "last_mark_equity_usd": round(mark, 2),
        "max_marked_drawdown_pct": round(deepest_dd, 3),
        "profit_factor": (round(sum(t["pnl_usd"] for t in trades if t["pnl_usd"] > 0) /
                         -sum(t["pnl_usd"] for t in trades if t["pnl_usd"] < 0), 3)
                          if any(t["pnl_usd"] < 0 for t in trades) else None),
        "open_position_censored": bool(position),
        "unrealized_last_mark_usd": round(mark-capital, 2),
        "slippage_each_side_per_oz": slippage,
        "commission_roundtrip_per_oz": commission,
        "trades": trades, "monthly": bymonth, "counts": counts,
        "monthly_sum_check_usd": round(sum(monthly.values()), 2),
        "no_actual_mt5_order": True,
        "quote_model": "authentic spot M1 BID and ASK resampled to H1, stop-first when same H1",
        "critical_parity_gaps": [
            "GAUSS native uses last 5000, implementation entire available prefix",
            "MT5 iMACD signal smoothing and initial indicator state not native cross-checked",
            "2023,2024,2025 indicators restarted without previous-year warming",
            "Source assumes 1 oz fixed volume and 1:20 leverage, not owner's contract",
            "Stop/target chronology inside H1, native lot rounding and swaps unverified",
        ],
    }
    result["sha256"] = digest(result)
    return result


def run(quote_root, dest):
    report = {"schema": "aidy.independent_web_discovery.gaussmacd.v1_1",
              "source_repo": UPSTREAM, "source_blob_sha": SOURCE_BLOB_SHA,
              "source_license": "MIT",
              "source_is_not_original83_assumption": True,
              "original83_dedup_not_yet_verified": True,
              "research_only": True, "no_live_or_demo_orders": True,
              "native_source_parity": False, "historical_OOS": False, "years": {}}
    for year in YEARS:
        market, trace = prices(quote_root, year)
        indicators_df = indicators(market)
        scenarios = {}
        for name, slip, fee in [("base", .05, 0.), ("stress", .25, .14)]:
            result = simulate(indicators_df, slippage=slip, commission=fee)
            d = dest/str(year)
            d.mkdir(parents=True, exist_ok=True)
            (d/f"{name}_trades.json").write_text(
                json.dumps(result, sort_keys=True, indent=2, allow_nan=False)+"\n")
            scenarios[name] = {k: result[k] for k in
                               ("closed", "wins", "realized_net_usd",
                                "ending_balance_usd", "last_mark_equity_usd",
                                "max_marked_drawdown_pct", "profit_factor",
                                "open_position_censored", "sha256", "counts")}
        report["years"][str(year)] = {"trace": trace, "scenarios": scenarios}
    report["sha256"] = digest(report)
    dest.mkdir(parents=True, exist_ok=True)
    (dest/"report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False)+"\n")
    print("AIDY_INDEPENDENT_WEB_GAUSSMACD", json.dumps(
        {yr: {scenario: {key: values[key] for key in
                            ("closed", "wins", "realized_net_usd",
                             "max_marked_drawdown_pct", "profit_factor",
                             "open_position_censored", "counts")}
              for scenario, values in item["scenarios"].items()}
         for yr, item in report["years"].items()}, sort_keys=True))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--quotes", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    try:
        run(args.quotes, args.out)
    except Exception as exc:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out/"BLOCKED.json").write_text(json.dumps(
            {"status": "BLOCKED_NO_RESULT", "error_type": type(exc).__name__},
            indent=2)+"\n")
        raise
