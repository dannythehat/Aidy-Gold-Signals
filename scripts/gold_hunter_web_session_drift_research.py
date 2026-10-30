"""Independent Gold session-drift falsification inspired by Donati & Jung (2019).

Publication: Gold Price Dynamics Around the Clock (CBS Research Portal).
Paper's broad hypothesis: positive return during eastern trading hours and
negative during western hours; authors explicitly found cost sensitivity.
THIS code's fixed 00-08 and 12-20 UTC windows are independently chosen
RESEARCH HYPOTHESES, not the paper's asserted executable original rules.

Two single-oz fixed-session tests on authentic AIDY spot BID/ASK 2023-25:
EAST_LONG_00_08_UTC, WEST_SHORT_12_20_UTC, and their nonoverlapping PAIR.
Every day scheduled by completed calendar time only; no future-price filter.
No stops; time-based exit, with verified gap penalties/first-available quote.
Not a tradable bot, a source-faithful author strategy, sealed OOS, or
broker-realistic financing/latency/contract parity.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from scripts.gold_hunter_web_gaussmacd_research import prices, YEARS

PUBLIC_SOURCE = "https://research.cbs.dk/en/studentProjects/gold-price-dynamics-around-the-clock/"
START_USD = 10000.0
OUNCES = 1.0
SESSIONS = {
    "EAST_LONG_00_08_UTC": (0, 8, 1),
    "WEST_SHORT_12_20_UTC": (12, 20, -1),
}
GROUPS = {
    "EAST_LONG_00_08_UTC": ("EAST_LONG_00_08_UTC",),
    "WEST_SHORT_12_20_UTC": ("WEST_SHORT_12_20_UTC",),
    "EAST_AND_WEST_IN_ONE_ACCOUNT": tuple(SESSIONS),
}


def digest(x):
    return hashlib.sha256(json.dumps(x, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def replay(market, families, slip=.05, fee=.0):
    """Hourly marked-account with native BID entry/exit and real ASK for buys."""
    balance = START_USD
    peak = START_USD
    drawdown = 0.0
    position = None
    trades = []
    misses = {"missing_entry_hours": 0, "late_exit": 0, "unclosed": 0}
    if market.index.has_duplicates or not market.index.is_monotonic_increasing:
        raise ValueError("History dates must be monotonically increasing and distinct")
    last_day = None
    for time, row in market.iterrows():
        day = time.date()
        if day != last_day:
            if last_day is not None:
                # Do not retroactively remove a day just because its entry/exit was unavailable.
                pass
            last_day = day
        h = time.hour
        # All exits occur first at the first available quote once time has passed.
        if position is not None and time >= position["deadline"]:
            s = position["side"]
            exit_quote = float(row["open"] if s == 1 else row["ask_o"])
            exit_price = exit_quote - s*slip
            pnl = ((exit_price-position["entry_price"])*s-fee)*OUNCES
            delay = (time - position["deadline"]).total_seconds()/60
            misses["late_exit"] += int(delay > 0)
            trades.append({
                "family": position["family"], "entry_utc": position["entry_time"].isoformat(),
                "exit_utc": time.isoformat(), "entry_price": position["entry_price"],
                "exit_price": round(exit_price, 6),
                "pnl_usd": round(pnl, 6), "exit_delay_minutes": delay,
            })
            balance += pnl
            position = None
        if position is None and time.weekday() < 5:
            for family in families:
                entry, exit_hour, side = SESSIONS[family]
                if h != entry:
                    continue
                entry_quote = float(row["ask_o"] if side == 1 else row["open"])
                entry_price = entry_quote + side*slip
                position = {
                    "family": family, "side": side,
                    "entry_price": entry_price, "entry_time": time,
                    "deadline": time.replace(hour=exit_hour),
                }
                break
        marked = balance
        if position is not None:
            side = position["side"]
            exit_quote = float(row["close"] if side == 1 else row["ask_c"])
            marked += ((exit_quote-position["entry_price"])*side-fee)*OUNCES
        peak = max(peak, marked)
        drawdown = min(drawdown, (marked/peak-1)*100)
    if position is not None:
        misses["unclosed"] = 1
    total = sum(t["pnl_usd"] for t in trades)
    if abs(total-(balance-START_USD)) > .001:
        raise ValueError("Source quote model cash mismatch")
    from collections import defaultdict
    months = defaultdict(float)
    for t in trades:
        months[t["exit_utc"][:7]] += t["pnl_usd"]
    by_month = [{"month": f"{market.index[0].year}-{m:02d}",
                 "realized_net_usd": round(months.get(
                     f"{market.index[0].year}-{m:02d}", 0), 3)}
                for m in range(1, 13)]
    gp = sum(max(t["pnl_usd"], 0) for t in trades)
    gl = -sum(min(t["pnl_usd"], 0) for t in trades)
    result = {
        "starting_usd": START_USD, "ending_balance_usd": round(balance, 2),
        "last_mark_equity_usd": round(marked, 2),
        "realized_net_usd": round(balance-START_USD, 2),
        "closed_trades": len(trades),
        "wins": sum(t["pnl_usd"] > 0 for t in trades),
        "profit_factor": round(gp/gl, 3) if gl else None,
        "max_marked_drawdown_pct": round(drawdown, 3),
        "marked_equity_includes_open": bool(position),
        "unrealized_usd": round(marked-balance, 2),
        "misses": misses, "monthly": by_month,
        "trades": trades,
        "quote_basis": "observed M1 BID+ASK H1 opening fills and hourly marked exits",
        "cost": {"slippage_per_side_per_oz": slip, "commission_roundtrip_per_oz": fee},
        "no_stop_or_native_broker_execution": True,
    }
    result["sha256"] = digest(result)
    return result


def main(root: Path, dest: Path):
    out = {
        "schema": "aidy.web_research.east_west_session_pre_registered_v1",
        "source_inspiration": PUBLIC_SOURCE,
        "original_author_rules_reproduced": False,
        "new_ai_hypothesis": "EAST 00-08 UTC LONG and WEST 12-20 UTC SHORT",
        "decision_time": "UTC H1 open; never choose today on its future returns",
        "previously_observed_development_years": list(YEARS),
        "sealed_oos": False, "broker_orders": 0,
        "risk_limit_gap": "No stops, no broker contract evidence; research only",
        "results": {},
    }
    for year in YEARS:
        market, trace = prices(root, year)
        rows = {}
        for family, members in GROUPS.items():
            scenarios = {}
            for name, slip, commission in [
                ("base", .05, 0.), ("stress", .25, .14)
            ]:
                result = replay(market, members, slip, commission)
                d = dest/str(year)
                d.mkdir(parents=True, exist_ok=True)
                (d/f"{family}_{name}.json").write_text(
                    json.dumps(result, sort_keys=True, indent=2, allow_nan=False)+"\n")
                scenarios[name] = {
                    k: result[k] for k in ("closed_trades", "realized_net_usd",
                                          "max_marked_drawdown_pct", "profit_factor",
                                          "wins", "misses", "sha256")
                }
            rows[family] = scenarios
        out["results"][str(year)] = {"trace": trace, "family": rows}
    out["sha256"] = digest(out)
    (dest/"report.json").write_text(
        json.dumps(out, sort_keys=True, indent=2, allow_nan=False)+"\n")
    print("AIDY_INDEPENDENT_SESSION_STUDY", json.dumps({
        y: {fam: {scenario: vals["realized_net_usd"]
                  for scenario, vals in entry.items()}
            for fam, entry in row["family"].items()}
        for y, row in out["results"].items()}, sort_keys=True))
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--quotes", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    try:
        main(args.quotes, args.out)
    except Exception as exc:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out/"BLOCKED.json").write_text(json.dumps({
            "status": "SOURCE_OR_RUN_BLOCKED", "exception_type": type(exc).__name__,
            "substitute_data": False, "broker_orders": 0}, indent=2)+"\n")
        raise
