"""Independent new outside-source Ichimoku CK/CP/DI Gold research. NO orders.

External MIT MQL5 by Neo Malesa, file profitable-gold-m30.mq5:
Git blob 7b9837c47a80928d21b6bee3e7b813d805c3e7e0.
This is an explicitly SOURCE-INSPIRED, NOT native MT5-parity implementation.
The author code uses 0.10 lot, Ichimoku 9/26/52, DI(14), three opposite
DI cross exit, XM SERVER 08:00-11:00 entries and no hard stop. Here we
declare UTC 08:00-11:00, assuming 100oz per lot (10oz) for comparison;
broker server timezone and contract are unknown. No invented broker swap.
Source Chikou buffer shift semantics need native MT5 tester comparison.
Historical 2023-25 are DEVELOPMENT, NOT sealed OOS. Uses pinned original
AIDY encrypted spot M1 BID+ASK archive reader. No futures substitution.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.gold_hunter_2023_2024_causal_research import read_month

ORIGIN = "https://github.com/n30dyn4m1c/ichimoku-chikou-kijun-crossover-ea"
SOURCE_BLOB = "7b9837c47a80928d21b6bee3e7b813d805c3e7e0"
LICENSE_BLOB = "7874e8fc5b21f333b241466dbf0f0abc308d553b"
YEARS = (2023, 2024, 2025)
START_USD = 10000.0
SOURCE_LOTS = .10
ASSUMED_OZ_PER_LOT = 100
OUNCES = SOURCE_LOTS * ASSUMED_OZ_PER_LOT
KIJUN = 26
DI_PERIOD = 14
OPPOSITE_DI_CROSSES_TO_EXIT = 3
SESSION_START_UTC = 8
SESSION_END_UTC = 11


def digest(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, allow_nan=False,
                                     separators=(",", ":")).encode()).hexdigest()


def m30_from_authentic(root: Path, year: int):
    if year not in YEARS:
        raise ValueError("Only preregistered 2023-2025")
    blocks, receipts = [], []
    for month in range(1, 13):
        frame, receipt = read_month(root, f"{year}{month:02d}")
        blocks.append(frame)
        receipts.append(receipt)
    m1 = pd.concat(blocks, ignore_index=True).sort_values("open_time_utc")
    if m1["open_time_utc"].duplicated().any():
        raise ValueError("Duplicate source M1 timestamp")
    if m1["open_time_utc"].dt.year.nunique() != 1 or m1["open_time_utc"].dt.year.iloc[0] != year:
        raise ValueError("Unexpected source year")
    m1 = m1.set_index("open_time_utc")
    h = m1.resample("30min").agg(
        bid_o=("bid_o", "first"), bid_h=("bid_h", "max"),
        bid_l=("bid_l", "min"), bid_c=("bid_c", "last"),
        ask_o=("ask_o", "first"), ask_h=("ask_h", "max"),
        ask_l=("ask_l", "min"), ask_c=("ask_c", "last"),
        n=("bid_o", "count"),
    )
    h = h[h["n"] == 30].copy()
    if len(h) < 9000 or set(h.index.month) != set(range(1, 13)):
        raise ValueError("Original M1 does not cover 12 complete M30 trading months")
    if not np.isfinite(h.to_numpy()).all():
        raise ValueError("Invalid quote")
    for side in ("o", "h", "l", "c"):
        if (h[f"ask_{side}"] < h[f"bid_{side}"]).any():
            raise ValueError("BID exceeds ASK")
    if h.index.tz is None or str(h.index.tz) not in ("UTC", "datetime.timezone.utc"):
        raise ValueError("UTC required")
    return h, {
        "year": year, "original_months": receipts,
        "original_m1_rows": len(m1), "complete_m30": len(h),
        "m30_sha256": hashlib.sha256(h.to_csv().encode()).hexdigest(),
        "unsealed_development_data": True,
    }


def wilder(series, n):
    """Wilder RMA with initial n-bar SMA, finite inputs required."""
    a = np.asarray(series, dtype=float)
    out = np.full(len(a), np.nan)
    if len(a) < n:
        return pd.Series(out, index=series.index)
    if not np.isfinite(a[:n]).all():
        raise ValueError("Wilder seed has missing values")
    out[n-1] = np.mean(a[:n])
    for i in range(n, len(a)):
        out[i] = (out[i-1]*(n-1)+a[i])/n
    return pd.Series(out, index=series.index)


def indicators(bars):
    x = bars.copy()
    high, low, close = x["bid_h"], x["bid_l"], x["bid_c"]
    x["kijun"] = (high.rolling(KIJUN).max()+low.rolling(KIJUN).min())/2
    # At last completed bar i, Chikou plotted at i-26 is close[i];
    # compare with Kijun at i-26. Never read future bar.
    x["ck_delta"] = close - x["kijun"].shift(KIJUN)
    x["cp_up"] = close > high.shift(KIJUN)
    x["cp_down"] = close < low.shift(KIJUN)
    up = high.diff().fillna(0)
    down = (-low.diff()).fillna(0)
    pdm = up.where((up > down) & (up > 0), 0)
    mdm = down.where((down > up) & (down > 0), 0)
    tr = pd.concat([high-low, (high-close.shift()).abs(),
                    (low-close.shift()).abs()], axis=1).max(axis=1)
    atr = wilder(tr, DI_PERIOD)
    x["pdi"] = 100*wilder(pdm, DI_PERIOD)/atr.replace(0, np.nan)
    x["mdi"] = 100*wilder(mdm, DI_PERIOD)/atr.replace(0, np.nan)
    x["di_delta"] = x["pdi"]-x["mdi"]
    return x


def carry_usd(entry, ounces, rate, first, last):
    """Hypothetical simple annual financing, not actual broker rollover."""
    if last < first:
        raise ValueError("Time reversal")
    return entry*ounces*rate*(last-first).total_seconds()/(365*86400)


def replay(x, *, slip=.25, commission=.14, annual_carry=.09):
    """Frozen 0.10 lot/10oz research account. No stops, no broker orders."""
    if x.index.has_duplicates or not x.index.is_monotonic_increasing:
        raise ValueError("Unsorted or duplicate bars")
    balance = START_USD
    peak, worst_dd = START_USD, 0.0
    state = "IDLE"
    position = None
    opp = 0
    trades = []
    signals = 0
    rejected_session = 0
    for i in range(1, len(x)):
        row, prev = x.iloc[i-1], x.iloc[i-2] if i >= 2 else x.iloc[0]
        t = x.index[i]  # first quote AFTER bar i-1 has finished
        if not np.isfinite(row[["ck_delta", "di_delta"]]).all():
            continue
        diff, prevdiff = float(row["ck_delta"]), float(prev["ck_delta"])
        di, prevdi = float(row["di_delta"]), float(prev["di_delta"])
        bull = np.isfinite(prevdiff) and prevdiff <= 0 < diff
        bear = np.isfinite(prevdiff) and prevdiff >= 0 > diff
        di_bull = np.isfinite(prevdi) and prevdi <= 0 < di
        di_bear = np.isfinite(prevdi) and prevdi >= 0 > di

        def close(reason):
            nonlocal balance, position, opp
            p = position
            if p is None:
                return
            side = p["side"]
            exit_price = (float(x.iloc[i]["bid_o"])-slip if side == 1
                          else float(x.iloc[i]["ask_o"])+slip)
            gross = (exit_price-p["entry"])*side*OUNCES
            cost = commission*OUNCES + carry_usd(
                p["entry"], OUNCES, annual_carry, p["at"], t)
            pnl = gross-cost
            balance += pnl
            trades.append({
                "entry_utc": p["at"].isoformat(), "exit_utc": t.isoformat(),
                "side": side, "entry_price": p["entry"], "exit_price": exit_price,
                "gross_usd": round(gross, 6), "cost_usd": round(cost, 6),
                "net_usd": round(pnl, 6), "reason": reason,
                "held_days": round((t-p["at"]).total_seconds()/86400, 6),
            })
            position = None
            opp = 0

        # Original v1.78: fresh CK cross always closes, then restarts.
        if bull or bear:
            signals += 1
            if position is not None:
                close("NEW_CK_CROSS")
            state = "WAIT_CP_BULL" if bull else "WAIT_CP_BEAR"
            opp = 0
        if state == "WAIT_CP_BULL" and bool(row["cp_up"]):
            state = "WAIT_DI_BULL"
        elif state == "WAIT_CP_BEAR" and bool(row["cp_down"]):
            state = "WAIT_DI_BEAR"

        # Author's three counted opposite DI crosses, no native SL/TP.
        if position is not None:
            if ((position["side"] == 1 and di_bear) or
                    (position["side"] == -1 and di_bull)):
                opp += 1
                if opp >= OPPOSITE_DI_CROSSES_TO_EXIT:
                    close("THIRD_OPPOSITE_DI")
                    state = "IDLE"

        # Session uses UTC as declared proxy for UNKNOWN XM SERVER clock.
        if position is None and state in ("WAIT_DI_BULL", "WAIT_DI_BEAR"):
            side = 1 if state == "WAIT_DI_BULL" else -1
            if (side == 1 and di > 0) or (side == -1 and di < 0):
                if SESSION_START_UTC <= t.hour < SESSION_END_UTC:
                    entry = (float(x.iloc[i]["ask_o"])+slip if side == 1
                             else float(x.iloc[i]["bid_o"])-slip)
                    position = {"at": t, "side": side, "entry": entry}
                    state = "LONG_OPEN" if side == 1 else "SHORT_OPEN"
                    opp = 0
                else:
                    rejected_session += 1

        # Mark-to-market on actual BID/ASK close, including accrued carry.
        mark = balance
        if position:
            side = position["side"]
            liquidation = (float(x.iloc[i]["bid_c"]) if side == 1
                           else float(x.iloc[i]["ask_c"]))
            mark += ((liquidation-position["entry"])*side*OUNCES
                     -commission*OUNCES
                     -carry_usd(position["entry"], OUNCES, annual_carry,
                                position["at"], t+pd.Timedelta(minutes=30)))
        peak = max(peak, mark)
        worst_dd = min(worst_dd, 100*(mark/peak-1))
    if abs((balance-START_USD)-sum(t["net_usd"] for t in trades)) > .002:
        raise ValueError("Closed cash ledger fails")
    months = {f"{x.index[0].year}-{m:02d}": 0.0 for m in range(1, 13)}
    for trade in trades:
        months[trade["exit_utc"][:7]] += trade["net_usd"]
    gp = sum(max(0, t["net_usd"]) for t in trades)
    gl = -sum(min(0, t["net_usd"]) for t in trades)
    out = {
        "closed_trades": len(trades), "ck_signals": signals,
        "session_rejections": rejected_session,
        "starting_usd": START_USD,
        "realized_net_usd": round(balance-START_USD, 2),
        "marked_net_usd": round(mark-START_USD, 2),
        "last_unrealized_usd": round(mark-balance, 2),
        "open_position_censored": bool(position),
        "max_m30_marked_drawdown_pct": round(worst_dd, 3),
        "profit_factor": round(gp/gl, 3) if gl else None,
        "largest_winner_usd": round(max((t["net_usd"] for t in trades), default=0), 2),
        "net_ex_largest_winner_usd": round(balance-START_USD-
                                          max((t["net_usd"] for t in trades), default=0), 2),
        "monthly": [{"month": k, "realized_net_usd": round(v, 2)}
                    for k, v in sorted(months.items())],
        "trades": trades,
        "hypothetical_cost": {"slip_each_side_usd_per_oz": slip,
                              "commission_roundtrip_usd_per_oz": commission,
                              "annual_simple_carry": annual_carry},
        "native_mt5_stop": False,
        "actual_broker_swap_or_lot_parity": False,
        "broker_orders": 0,
    }
    out["sha256"] = digest(out)
    return out


def main(root, outdir):
    report = {
        "schema": "aidy.external_ichimoku_ckcpdi_causal_m30_v1",
        "source": ORIGIN, "author_file": "profitable-gold-m30.mq5",
        "source_blob": SOURCE_BLOB, "licence": "MIT", "licence_blob": LICENSE_BLOB,
        "author_defaults": {"lots": SOURCE_LOTS, "kijun": KIJUN, "di_period": 14,
                            "ignore_first_opposite_di_crosses": 2,
                            "session_server_hours": "08:00-11:00"},
        "independent_adaptation": {"utc_session_proxy": "08:00-11:00",
                                   "assumed_oz_per_lot": ASSUMED_OZ_PER_LOT,
                                   "annual_carry_not_broker_rate": .09,
                                   "original_mt5_buffer_parity": False},
        "source_vs_model": "SOURCE_INSPIRED_NOT_NATIVE_PARITY",
        "sealed_oos": False, "broker_orders": 0, "years": {},
    }
    for year in YEARS:
        bars, manifest = m30_from_authentic(root, year)
        x = indicators(bars)
        scenarios = {}
        for name, slip, fee, carry in [
            ("base_no_funding", .05, 0.0, 0.0),
            ("stress_hypothetical_9pct_carry", .25, .14, .09),
        ]:
            result = replay(x, slip=slip, commission=fee, annual_carry=carry)
            folder = outdir/str(year)
            folder.mkdir(parents=True, exist_ok=True)
            (folder/f"{name}.json").write_text(
                json.dumps(result, indent=2, sort_keys=True, allow_nan=False)+"\n")
            scenarios[name] = {k: result[k] for k in (
                "closed_trades", "ck_signals", "session_rejections",
                "realized_net_usd", "marked_net_usd", "last_unrealized_usd",
                "open_position_censored", "max_m30_marked_drawdown_pct",
                "profit_factor", "largest_winner_usd",
                "net_ex_largest_winner_usd", "sha256")}
        report["years"][str(year)] = {"manifest": manifest, "scenarios": scenarios}
    report["sha256"] = digest(report)
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir/"report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False)+"\n")
    print("AIDY_NEW_SOURCE_ICHIMOKU", json.dumps({
        y: {s: {k: v[k] for k in ("closed_trades", "marked_net_usd",
                                 "max_m30_marked_drawdown_pct")}
             for s, v in d["scenarios"].items()}
        for y, d in report["years"].items()}, sort_keys=True))
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--quotes", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    args = p.parse_args()
    try:
        main(args.quotes, args.out)
    except Exception as exc:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out/"BLOCKED.json").write_text(json.dumps({
            "status": "SOURCE_OR_TEST_BLOCKED", "exception_type": type(exc).__name__,
            "broker_orders": 0, "no_substitute_quotes": True}, indent=2)+"\n")
        raise
