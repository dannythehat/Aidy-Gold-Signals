"""Audited fixed-one-unit Pine accounts, not a generic Pine interpreter.

Original quantities/capital/entry and management order are preserved. Fills use
TradingView's documented historical broker emulator, NOT invented broker ticks.
Native friction and separately comparable existing AIDY cost overlays are kept.
No actual broker/financing attestation or sealed OOS qualification is claimed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path

import numpy as np
import pandas as pd

from aidy.strategy_lab_s010_backtest import BASE, STRESS
from scripts.oracle_gold.history import digest
from scripts.oracle_gold.minute_history import load
from scripts.oracle_gold.recover_sources import get

ROOT = Path(__file__).resolve().parents[2]
PINS = ROOT/"research/gold_oracle/phase03/account_source_pins.json"
PROFILES = {"S058": (15, 10000., .0001, 0., True),
            "S060": (5, 1000000., 0., 100., False),
            "S061": (60, 10000., .0001, 100., False),
            "S081": (1, 1000000., 0., 0., False)}


def source(ident, root):
    pin = json.loads(PINS.read_text())[ident]["source"]
    path = root/(ident+".pine")
    if not path.exists():
        raw, _ = get(pin["endpoint"])
        value = json.loads(raw)
        if value.get("scriptAccess") != "open_no_auth":
            raise ValueError("Original source not openly accessible")
        root.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value["source"].encode())
    if hashlib.sha256(path.read_bytes()).hexdigest() != pin["sha256"]:
        raise ValueError("Original Pine bytes changed: "+ident)
    return path.read_text()


def rma(series, n):
    out = np.full(len(series), np.nan)
    values, previous = [], None
    for i, value in enumerate(series):
        if pd.isna(value):
            out[i] = previous if previous is not None else np.nan
            continue
        if previous is None:
            values.append(value)
            if len(values) == n:
                previous = sum(values)/n
        else:
            previous += (value-previous)/n
        if previous is not None:
            out[i] = previous
    return pd.Series(out, index=series.index)


def features(rows, minutes, ident):
    frame = pd.DataFrame(rows)
    frame.index = pd.to_datetime(frame.pop("open_time_utc"), utc=True)
    g = frame.resample(f"{minutes}min", label="left", closed="left")
    x = g.agg({"open": "first", "high": "max", "low": "min", "close": "last"})
    count = g.close.count()
    x = x.loc[count == minutes].copy()  # no synthetic/partial chart bars
    tr = pd.concat([x.high-x.low, (x.high-x.close.shift()).abs(), (x.low-x.close.shift()).abs()], axis=1).max(axis=1)
    x["atr"] = rma(tr, 14)
    for n in (3, 33, 50, 100, 200, 600):
        x[f"ema{n}"] = x.close.ewm(span=n, adjust=False).mean()
    if ident == "S061":
        lo, hi = x.low.rolling(10, min_periods=1).min().shift(), x.high.rolling(10, min_periods=1).max().shift()
        x["buy"] = (x.low < lo)&(x.close > lo)&(x.close > x.ema200)
        x["sell"] = (x.high > hi)&(x.close < hi)&(x.close < x.ema200)
    elif ident == "S058":
        # ta.pivot* emits only on the confirmation bar, five bars AFTER pivot.
        last_hi = last_lo = np.nan
        buys, sells = [], []
        for i in range(len(x)):
            if i >= 10:
                k = i-5
                # Ties to the right invalidate the earlier pivot, as in Pine.
                if x.high.iloc[k] >= x.high.iloc[k-5:k].max() and x.high.iloc[k] > x.high.iloc[k+1:i+1].max():
                    last_hi = x.high.iloc[k]
                if x.low.iloc[k] <= x.low.iloc[k-5:k].min() and x.low.iloc[k] < x.low.iloc[k+1:i+1].min():
                    last_lo = x.low.iloc[k]
            local = x.index[i].tz_convert("America/New_York")
            clock = local.hour*60+local.minute
            allowed = 420 <= clock < 600 or 750 <= clock < 960
            b = x.iloc[i]
            buys.append(bool(i >= 2 and allowed and b.low < last_lo < b.close and b.close > x.high.iloc[i-1] and b.low > x.high.iloc[i-2]))
            sells.append(bool(i >= 2 and allowed and b.high > last_hi > b.close and b.close < x.low.iloc[i-1] and b.high < x.low.iloc[i-2]))
        x["buy"], x["sell"] = buys, sells
    else:
        n = 6 if ident == "S060" else 12
        d = x.close.diff()
        gain, loss = rma(d.clip(lower=0), n), rma((-d).clip(lower=0), n)
        rsi = 100.-100./(1.+gain/loss)
        rsi = rsi.mask(loss == 0, 100.).mask((gain == 0)&(loss != 0), 0.)
        if ident == "S060":
            bull = (x.ema50 > x.ema100)&(x.ema100 > x.ema200)&(x.ema200 > x.ema600)
            bear = (x.ema50 < x.ema100)&(x.ema100 < x.ema200)&(x.ema200 < x.ema600)
            x["buy"] = bull&(rsi < 20)&(rsi.shift() >= 20)
            x["sell"] = bear&(rsi > 80)&(rsi.shift() <= 80)
        else:
            def wma(s, n):
                w = np.arange(1, n+1)
                return s.rolling(n).apply(lambda a: np.dot(a, w)/sum(w), raw=True)
            hma = wma(2*wma(x.close, 33)-wma(x.close, 66), 8)
            room = x.high.rolling(14, min_periods=1).max()-x.low.rolling(14, min_periods=1).min() > x.atr*.5
            window = (x.index >= pd.Timestamp("2023-01-01", tz="UTC"))&(x.index <= pd.Timestamp("2024-12-31 23:59", tz="UTC"))
            x["buy"] = (x.ema3 > x.ema33)&(x.ema3.shift() <= x.ema33.shift())&(rsi > 56)&(hma > hma.shift())&room&window
            x["sell"] = (x.ema3 < x.ema33)&(x.ema3.shift() >= x.ema33.shift())&(rsi < 45)&(hma < hma.shift())&room&window
    return x


@dataclass
class Position:
    side: int
    entry: float
    entry_time: str
    entry_fee: float
    signal_time: str
    stop: float | None = None
    target: float | None = None


def evaluate(x, ident, scenario):
    minutes, initial, commission, margin, on_close = PROFILES[ident]
    overlay = None if scenario == "native" else BASE if scenario == "common_base" else STRESS
    # Common scenarios REPLACE native friction, preserving the native case too.
    unit_fee = 0. if overlay is None else (overlay.spread_usd_per_oz+2*overlay.slippage_usd_per_oz_each_side+overlay.commission_usd_per_oz_round_trip)/2
    balance, peak, worst, close_peak, close_worst = initial, initial, 0., initial, 0.
    position, pending = None, None
    trades, equity = [], []
    max_leverage = 0.
    equal_paths = 0

    def fee(price):
        return price*commission if overlay is None else unit_fee

    def marked(price):
        return balance+(position.side*(price-position.entry) if position else 0.)

    def track(price):
        nonlocal peak, worst, max_leverage
        value = marked(price)
        peak = max(peak, value)
        worst = min(worst, (value/peak-1)*100)
        if position:
            max_leverage = max(max_leverage, price/value if value > 0 else float("inf"))
            if margin and value+1e-8 < price*margin/100:
                raise ValueError("Native margin liquidation required; unsupported rather than fabricated")

    def close(price, stamp, reason):
        nonlocal balance, position
        if position is None:
            return
        p = position
        exit_fee = fee(price)
        gross = p.side*(price-p.entry)
        balance += gross-exit_fee
        trades.append({"id": len(trades)+1, "strategy_id": ident, "side": "LONG" if p.side == 1 else "SHORT",
            "signal_utc": p.signal_time, "entry_utc": p.entry_time, "exit_bar_utc": stamp,
            "units": 1., "entry_reference": p.entry, "exit_reference": price,
            "gross_usd": gross, "declared_trading_cost_usd": p.entry_fee+exit_fee,
            "net_excluding_unverified_funding_usd": gross-p.entry_fee-exit_fee,
            "exit_reason": reason, "funding_usd": None})
        position = None

    def enter(side, price, stamp, signal_stamp, bracket):
        nonlocal balance, position
        if position and position.side == side:
            return
        if position:
            close(price, stamp, "SOURCE_REVERSAL")
        cost = fee(price)
        if margin and balance-cost < price*margin/100:
            return  # exact native account cannot afford one whole source unit
        balance -= cost
        position = Position(side, price, stamp, cost, signal_stamp,
                            bracket[0] if bracket else None, bracket[1] if bracket else None)

    for stamp, row in x.iterrows():
        ts = stamp.isoformat()
        if pending:
            # Pine market orders fill before price-based brackets on next tick.
            enter(*pending[:1], row.open, ts, pending[1], pending[2])
            pending = None
        track(row.open)
        if abs(row.high-row.open) < abs(row.open-row.low):
            path = (row.open, row.high, row.low, row.close)
        else:
            if abs(row.high-row.open) == abs(row.open-row.low) and position:
                equal_paths += 1
            path = (row.open, row.low, row.high, row.close)
        # At a gap, already crossed stop/limit fills at the OPEN, not its level.
        if position and position.stop is not None:
            hit_stop = position.side*(row.open-position.stop) <= 0
            hit_target = position.side*(row.open-position.target) >= 0
            if hit_stop or hit_target:
                close(row.open, ts, "STOP_GAP" if hit_stop else "TARGET_GAP")
        for a, b in pairwise(path):
            if position and position.stop is not None:
                levels = [(v, label) for v, label in ((position.stop, "STOP"), (position.target, "TARGET")) if min(a, b) <= v <= max(a, b)]
                if levels:
                    price, reason = min(levels, key=lambda z: abs(z[0]-a))
                    track(price)
                    close(price, ts, reason)
            track(b)
        side = 1 if row.buy else -1 if row.sell else 0
        avg = position.entry if position else None
        atr = row.atr
        brackets = {}
        if ident == "S061" and avg is not None and np.isfinite(atr):
            brackets = {d: (avg-d*atr*1.5, avg+d*atr*4.5) for d in (1, -1)}
            position.stop, position.target = brackets[position.side]
        elif ident == "S060" and position and np.isfinite(atr):
            d = position.side
            position.stop, position.target = row.close-d*atr, row.close+d*atr*2.
        if side:
            signal_time = (stamp+pd.Timedelta(minutes=minutes)).isoformat()
            bracket = brackets.get(side)
            if ident == "S058":
                stop = row.low if side == 1 else row.high
                bracket = (stop, row.close+side*abs(row.close-stop)*2.)
            if not position or position.side != side:
                if on_close:
                    enter(side, row.close, signal_time, signal_time, bracket)
                else:
                    pending = (side, signal_time, bracket)
            elif bracket:
                position.stop, position.target = bracket
        end = marked(row.close)
        close_peak = max(close_peak, end)
        close_worst = min(close_worst, (end/close_peak-1)*100)
        track(row.close)
        equity.append({"bar_open_utc": ts, "balance": balance, "marked_equity": end,
                       "open_side": position.side if position else 0})
    # Preserve native still-open positions; never add an invented end liquidation.
    realised = sum(t["net_excluding_unverified_funding_usd"] for t in trades)
    final = equity[-1]["marked_equity"]
    outstanding_entry_fee = position.entry_fee if position else 0.
    if abs(balance-(initial+realised-outstanding_entry_fee)) > 1e-6:
        raise ValueError("Account cash ledger does not reconcile")
    wins = sum(t["net_excluding_unverified_funding_usd"] for t in trades if t["net_excluding_unverified_funding_usd"] > 0)
    losses = -sum(t["net_excluding_unverified_funding_usd"] for t in trades if t["net_excluding_unverified_funding_usd"] < 0)
    eq = pd.DataFrame(equity)
    eq["month"] = pd.to_datetime(eq.bar_open_utc, utc=True).dt.strftime("%Y-%m")
    monthly, prior = [], initial
    for month, group in eq.groupby("month", sort=True):
        end = float(group.marked_equity.iloc[-1])
        monthly.append({"month": month, "start_equity": prior, "end_equity": end,
                        "net_excluding_unverified_funding_usd": end-prior, "return_pct": (end/prior-1)*100})
        prior = end
    return {"strategy_id": ident, "scenario": scenario, "initial_capital": initial,
        "quantity_rule": "ORIGINAL_FIXED_ONE_UNIT", "closed_trades": len(trades),
        "long_trades": sum(t["side"] == "LONG" for t in trades), "short_trades": sum(t["side"] == "SHORT" for t in trades),
        "net_marked_excluding_unverified_funding_usd": final-initial,
        "net_closed_excluding_unverified_funding_usd": realised,
        "unrealised_reference_usd": final-balance, "open_positions_at_end": int(position is not None),
        "open_entry_fee_usd": outstanding_entry_fee, "profit_factor": wins/losses if losses else None,
        "win_rate_pct": 100*sum(t["net_excluding_unverified_funding_usd"] > 0 for t in trades)/len(trades) if trades else None,
        "largest_closed_winner_usd": max([0.]+[t["net_excluding_unverified_funding_usd"] for t in trades]),
        "closed_net_without_largest_winner_usd": realised-max([0.]+[t["net_excluding_unverified_funding_usd"] for t in trades]),
        "profitable_months": sum(m["net_excluding_unverified_funding_usd"] > 0 for m in monthly),
        "worst_month_pct": min(m["return_pct"] for m in monthly),
        "max_modelled_pine_path_drawdown_pct": worst, "max_bar_close_drawdown_pct": close_worst,
        "max_modelled_gross_notional_to_equity": max_leverage, "margin_liquidations_required": 0,
        "equal_distance_bar_paths_unverified": equal_paths, "monthly": monthly, "trades": trades,
        "funding_verified": False, "native_platform_output_parity": False, "native_broker_qualified": False,
        "sealed_oos": False, "status": "SOURCE_DEFINED_UNIT_ACCOUNT_MODEL_NOT_BROKER_QUALIFIED",
        "ledger_sha256": digest(trades)}


def csv_out(path, rows):
    import csv
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ["ZERO_TRADES"])
        w.writeheader()
        w.writerows(rows)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--snapshots", required=True, type=Path)
    p.add_argument("--sources", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--ids", nargs="+", default=list(PROFILES))
    a = p.parse_args()
    rows, manifests = [], []
    expected_cache = json.loads((ROOT/"research/gold_oracle/phase03/minute_cache_receipt.json").read_text())["frozen_snapshots"]
    for year in (2023, 2024, 2025):
        values, manifest = load(a.snapshots/str(year))
        if manifest["rows_sha256"] != expected_cache[str(year)]["rows_sha256"] or manifest["sha256"] != expected_cache[str(year)]["sha256"]:
            raise ValueError("Authenticated research cache identity changed")
        rows.extend(values)
        manifests.append(manifest)
    results = {}
    a.out.mkdir(parents=True, exist_ok=True)
    for ident in a.ids:
        source(ident, a.sources)
        x = features(rows, PROFILES[ident][0], ident)
        # Only signal parity is compared on prefixes, not future trade outcomes.
        prefix_checks = []
        for cut in (len(rows)//2, 3*len(rows)//4):
            partial = features(rows[:cut], PROFILES[ident][0], ident)
            common = partial.index.intersection(x.index)
            same = x.loc[common, ["buy", "sell"]].equals(partial.loc[common, ["buy", "sell"]])
            prefix_checks.append(same)
        if not all(prefix_checks):
            raise ValueError("Source signal prefix parity failed: "+ident)
        for scenario in ("native", "common_base", "common_stress"):
            result = evaluate(x, ident, scenario)
            result["signal_prefix_parity"] = prefix_checks
            csv_out(a.out/f"{ident}_{scenario}_trades.csv", result.pop("trades"))
            csv_out(a.out/f"{ident}_{scenario}_monthly.csv", result["monthly"])
            results[ident+"/"+scenario] = result
            print("PINE_UNIT_ACCOUNT", ident, scenario, result["closed_trades"], result["net_marked_excluding_unverified_funding_usd"], flush=True)
    report = {"schema": "oracle.gold.source_fixed_unit_accounts.v1", "models": results,
              "input_manifests": manifests, "source_pins": json.loads(PINS.read_text()),
              "source_rules_changed": False, "account_unit": "XAUUSD_USD_PER_PRICE_UNIT_POINTVALUE1",
              "native_emulator_docs": "https://www.tradingview.com/pine-script-docs/concepts/strategies/",
              "scope": "Original code-default accounts; target XAUUSD; published S058/S061 chart examples were BTC/silver, not gold evidence",
              "costs": "Native declared percentage commissions OR separate existing AIDY common per-ounce cash cost overlays; never broker-attested fills/funding",
              "all83_backtested": False}
    report["sha256"] = digest(report)
    (a.out/"report.json").write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False)+"\n")


if __name__ == "__main__":
    main()
