"""Gold Hunter: mechanical XAUUSD Bible interpretation, NOT a proven trading edge.

Source: The Candlestick Trading Bible, particularly printed pages 51-80,
81-108 (pin), 109-136 (engulf), 137-157 (inside/false break).
Machine thresholds are explicitly AI hypotheses, not quotations from the author.
All signals use completed H1 with as-of completed H4/D1/W1 context.
No network access, MT5 credentials, broker order API or execution capability.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd

FAMILIES = (
    "TREND_PIN", "TREND_ENGULF", "TREND_INSIDE", "TREND_FALSE_BREAK",
    "RANGE_PIN", "RANGE_ENGULF", "RANGE_FALSE_BREAK",
)
BIBLE_SOURCES = {
    "TREND_PIN": "B 83-99", "TREND_ENGULF": "B 109-124",
    "TREND_INSIDE": "B 137-147", "TREND_FALSE_BREAK": "B 148-154",
    "RANGE_PIN": "B 103-108", "RANGE_ENGULF": "B 125-135",
    "RANGE_FALSE_BREAK": "B 148-154",
}


@dataclass(frozen=True)
class Parameters:
    # Engineering definitions requiring multi-regime evaluation; NOT book constants.
    risk_fraction: float = .005
    min_rr: float = 2.0  # Bible printed p133
    spread_usd_oz: float = .30  # ILLUSTRATIVE, not observed broker spread
    slip_usd_oz_each_side: float = .05
    commission_usd_oz_roundtrip: float = .07
    near_level_atr: float = .42
    stop_buffer_atr: float = .08
    capital_usd: float = 10000.0

    def validate(self) -> None:
        if not (0 < self.risk_fraction <= .01 and self.min_rr >= 2 and
                0 <= self.spread_usd_oz < 20 and
                0 <= self.slip_usd_oz_each_side < 20 and
                0 <= self.commission_usd_oz_roundtrip < 20 and
                .1 <= self.near_level_atr <= 1 and
                0 <= self.stop_buffer_atr <= .5 and self.capital_usd > 0):
            raise ValueError("Invalid or non-Bible risk configuration")


def validate_h1(bars: pd.DataFrame) -> pd.DataFrame:
    needed = ("open_time_utc", "open", "high", "low", "close", "m1_count")
    if any(col not in bars.columns for col in needed):
        raise ValueError("AIDY source must supply complete native M1-derived H1 BID")
    df = bars.loc[:, needed].copy()
    df["open_time_utc"] = pd.to_datetime(df["open_time_utc"], utc=True)
    if (df["open_time_utc"].isna().any() or df["open_time_utc"].duplicated().any()
            or not df["open_time_utc"].is_monotonic_increasing):
        raise ValueError("XAUUSD time not strictly increasing UTC")
    if (df["open_time_utc"].dt.minute.ne(0).any()
            or df["open_time_utc"].dt.second.ne(0).any()
            or df["open_time_utc"].dt.microsecond.ne(0).any()):
        raise ValueError("Expected whole UTC hour boundaries")
    for col in ("open", "high", "low", "close"):
        df[col] = pd.to_numeric(df[col], errors="raise").astype(float)
    if (not np.isfinite(df[["open", "high", "low", "close"]].to_numpy()).all()
            or not df[["open", "high", "low", "close"]].gt(0).all().all()
            or not df["m1_count"].eq(60).all()
            or not df["high"].ge(df[["open", "low", "close"]].max(axis=1)).all()
            or not df["low"].le(df[["open", "high", "close"]].min(axis=1)).all()):
        raise ValueError("Incomplete/corrupt source or invalid OHLC geometry")
    if len(df) < 500:
        raise ValueError("Insufficient H1 source for multi-timeframe Bible context")
    return df.reset_index(drop=True)


def _resample(df: pd.DataFrame, freq: str, required: int) -> pd.DataFrame:
    x = df.set_index("open_time_utc")
    agg = x.resample(freq, label="left", closed="left").agg({
        "open": "first", "high": "max", "low": "min", "close": "last",
        "m1_count": "size",
    })
    agg = agg.loc[agg["m1_count"] >= required].copy()
    # A completed H4/day/week may be consulted only after its period ends.
    offset = pd.Timedelta(hours=4) if freq == "4h" else (
        pd.Timedelta(days=1) if freq == "1D" else pd.Timedelta(days=7))
    agg["completed_at"] = agg.index + offset
    agg["atr"] = (agg["high"] - agg["low"]).rolling(14).mean()
    agg["sma21"] = agg["close"].rolling(21).mean()
    return agg.reset_index(drop=True)


def _higher_frames(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    h4 = _resample(df, "4h", 4)
    day = _resample(df, "1D", 20)
    # Calendar weeks begin Monday UTC. Only 80+ original hourly observations.
    x = df.set_index("open_time_utc")
    w = x.resample("W-MON", label="left", closed="left").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "m1_count": "size"
    })
    w = w.loc[w["m1_count"] >= 80].copy()
    w["completed_at"] = w.index + pd.Timedelta(days=7)
    return h4, day, w.reset_index(drop=True)


def _confirmed_swings(x: pd.DataFrame) -> tuple[list[float], list[float]]:
    """2-left/2-right pivots known after confirmation; caller passes only past bars."""
    highs, lows = [], []
    for i in range(2, len(x) - 2):
        h = float(x.iloc[i]["high"])
        l = float(x.iloc[i]["low"])
        if h > max(float(v) for v in x.iloc[i-2:i]["high"]) and h >= max(
                float(v) for v in x.iloc[i+1:i+3]["high"]):
            highs.append(h)
        if l < min(float(v) for v in x.iloc[i-2:i]["low"]) and l <= min(
                float(v) for v in x.iloc[i+1:i+3]["low"]):
            lows.append(l)
    return highs, lows


def _market(h4: pd.DataFrame, daily: pd.DataFrame, weekly: pd.DataFrame,
            close: float) -> dict[str, Any]:
    if len(h4) < 64 or len(daily) < 21 or len(weekly) < 2:
        return {"mode": "UNKNOWN"}
    recent = h4.tail(70)
    hi, lo = _confirmed_swings(recent)
    rising = len(hi) >= 2 and len(lo) >= 2 and hi[-1] > hi[-2] and lo[-1] > lo[-2]
    falling = len(hi) >= 2 and len(lo) >= 2 and hi[-1] < hi[-2] and lo[-1] < lo[-2]
    d = daily.iloc[-1]
    daily_sma = float(d["sma21"])
    if not np.isfinite(daily_sma):
        return {"mode": "UNKNOWN"}
    direction = (1 if rising and close >= daily_sma else
                 -1 if falling and close <= daily_sma else 0)
    atr = float(h4.iloc[-1]["atr"])
    if not np.isfinite(atr) or atr <= 0:
        return {"mode": "UNKNOWN"}
    # Levels are actual *historical completed* H4 pivots, with 21SMA
    # a source-sanctioned dynamic alternative. Choppy != a defined range.
    levels_long = [v for v in hi[:-1] + lo if v < close] + [float(h4.iloc[-1]["sma21"])]
    levels_short = [v for v in lo[:-1] + hi if v > close] + [float(h4.iloc[-1]["sma21"])]
    resistances = sorted(v for v in hi if v > close)
    supports = sorted((v for v in lo if v < close), reverse=True)
    whi, wlo = _confirmed_swings(weekly.tail(28))
    return {
        "mode": "TREND" if direction else "CHOP",
        "direction": direction,
        "atr": atr,
        "support_levels": [v for v in levels_long if np.isfinite(v) and v < close],
        "resistance_levels": [v for v in levels_short if np.isfinite(v) and v > close],
        "targets_long": resistances,
        "targets_short": supports,
        "weekly_resistances": [v for v in whi if v > close],
        "weekly_supports": [v for v in wlo if v < close],
        "recent_h4": recent,
    }


def _range_context(h4: pd.DataFrame, atr: float) -> tuple[float, float] | None:
    r = h4.tail(38)
    if len(r) < 38:
        return None
    lower, upper = float(r["low"].min()), float(r["high"].max())
    width = upper - lower
    if not 3 * atr < width < 18 * atr:
        return None
    tolerance = .30 * atr
    # Two prior, separate H4 candles must have rejected each horizontal border.
    touches_low = int((r["low"] <= lower + tolerance).sum())
    touches_high = int((r["high"] >= upper - tolerance).sum())
    if touches_low < 2 or touches_high < 2:
        return None
    return lower, upper


def classify_pattern(last: list[dict[str, float]], side: int) -> list[tuple[str, float, float]]:
    """Return (Bible pattern, stop-reference low/high, signal-level-touch price)."""
    if len(last) < 3 or side not in (-1, 1):
        return []
    a, b, c = last[-3:]
    rng = c["high"] - c["low"]
    if rng <= 0:
        return []
    body = abs(c["close"] - c["open"])
    lower = min(c["close"], c["open"]) - c["low"]
    upper = c["high"] - max(c["close"], c["open"])
    ret = []
    if (body <= .35 * rng and
            (lower >= .60 * rng and lower >= 2 * body and lower > upper
             if side == 1 else
             upper >= .60 * rng and upper >= 2 * body and upper > lower)):
        ret.append(("PIN", c["low"] if side == 1 else c["high"],
                    c["low"] if side == 1 else c["high"]))
    if ((c["close"] > c["open"] and b["close"] < b["open"]
         and c["open"] <= b["close"] and c["close"] >= b["open"])
            if side == 1 else
            (c["close"] < c["open"] and b["close"] > b["open"]
             and c["open"] >= b["close"] and c["close"] <= b["open"])):
        ret.append(("ENGULF", min(b["low"], c["low"]) if side == 1 else
                    max(b["high"], c["high"]),
                    c["low"] if side == 1 else c["high"]))
    inside = b["high"] < a["high"] and b["low"] > a["low"]
    if inside:
        if (c["close"] > a["high"] if side == 1 else c["close"] < a["low"]):
            ret.append(("INSIDE", min(a["low"], b["low"]) if side == 1
                        else max(a["high"], b["high"]),
                        b["low"] if side == 1 else b["high"]))
        # Mother-bar sweep and reclaim, completed third candle, no future price.
        if ((c["low"] < a["low"] and a["low"] < c["close"] < a["high"])
                if side == 1 else
                (c["high"] > a["high"] and a["low"] < c["close"] < a["high"])):
            ret.append(("FALSE_BREAK", c["low"] if side == 1 else c["high"],
                        c["low"] if side == 1 else c["high"]))
    return ret


def candidates_at(df: pd.DataFrame, i: int, h4: pd.DataFrame,
                  day: pd.DataFrame, week: pd.DataFrame,
                  cfg: Parameters) -> list[dict]:
    t = df.iloc[i]["open_time_utc"] + pd.Timedelta(hours=1)
    h = h4.loc[h4["completed_at"] <= t]
    d = day.loc[day["completed_at"] <= t]
    w = week.loc[week["completed_at"] <= t]
    c = float(df.iloc[i]["close"])
    ctx = _market(h, d, w, c)
    if ctx["mode"] == "UNKNOWN":
        return []
    atr = ctx["atr"]
    recent = df.iloc[i-2:i+1].to_dict("records")
    market_mode = ctx["mode"]
    contexts = []
    if market_mode == "TREND":
        contexts.append(("TREND", ctx["direction"], None))
    else:
        bound = _range_context(h, atr)
        if bound:
            contexts.extend([("RANGE", 1, bound), ("RANGE", -1, bound)])
    out = []
    for regime, side, bound in contexts:
        if regime == "TREND":
            levels = (ctx["support_levels"] if side == 1 else ctx["resistance_levels"])
            targets = ctx["targets_long"] if side == 1 else ctx["targets_short"]
        else:
            levels = [bound[0] if side == 1 else bound[1]]
            targets = [bound[1] if side == 1 else bound[0]]
        if not levels or not targets:
            continue
        for pattern, stop_edge, touch in classify_pattern(recent, side):
            if regime == "RANGE" and pattern == "INSIDE":
                continue
            near = [level for level in levels if abs(level - touch) <= cfg.near_level_atr * atr]
            if not near:
                continue
            level = min(near, key=lambda n: abs(n - touch))
            entry_est = c + side * (cfg.spread_usd_oz / 2 + cfg.slip_usd_oz_each_side)
            stop = stop_edge - side * cfg.stop_buffer_atr * atr
            risk = side * (entry_est - stop)
            if risk <= 0 or risk > 3 * atr:
                continue
            # Take the first actual prior meaningful opposing H4 swing/range level.
            viable = [v for v in targets if side * (v - entry_est) > 0]
            if not viable:
                continue
            target = min(viable) if side == 1 else max(viable)
            reward = side * (target - entry_est) - (cfg.spread_usd_oz / 2 +
                                                   cfg.slip_usd_oz_each_side +
                                                   cfg.commission_usd_oz_roundtrip)
            rr = reward / risk
            if rr < cfg.min_rr:
                continue
            # Weekly major levels cannot be ignored as known near-target obstacles.
            barriers = ctx["weekly_resistances"] if side == 1 else ctx["weekly_supports"]
            if any(0 < side * (v - entry_est) < cfg.min_rr * risk for v in barriers):
                continue
            family = f"{regime}_{pattern}"
            if family not in FAMILIES:
                continue
            out.append({
                "family": family, "bible_reference": BIBLE_SOURCES[family],
                "signal_time_utc": t.isoformat(), "side": side,
                "mode": regime, "level": round(level, 6),
                "level_type": "H4_SWING_OR_SMA21" if regime == "TREND" else "H4_RANGE_BOUNDARY",
                "pattern": pattern, "stop": round(stop, 6),
                "target": round(target, 6), "estimated_rr": round(rr, 4),
                "signal_close": c,
            })
    return out


def research_backtest(bars: pd.DataFrame, *, cfg: Parameters | None = None,
                      families: tuple[str, ...] = FAMILIES) -> dict:
    """Research-only one-position portfolio. Simulated bid/ask; no real orders.

    Entry at following H1 OPEN, then stop/target on H1 range; if both touched,
    adverse STOP wins. A gap across stop is filled at worse open. Never claim
    broker-executable performance from an H1 retrospective price replay.
    """
    cfg = cfg or Parameters()
    cfg.validate()
    if not families or len(set(families)) != len(families) or any(
            f not in FAMILIES for f in families):
        raise ValueError("Unsupported Bible family or duplicates")
    df = validate_h1(bars)
    h4, day, week = _higher_frames(df)
    equity = cfg.capital_usd
    position = None
    pending = None
    trades, marks, counts = [], [], {family: 0 for family in families}
    rejections = {"conflicting_signals": 0, "portfolio_busy": 0, "not_bible_admitted": 0}
    half = cfg.spread_usd_oz / 2
    for i in range(len(df)):
        bar = df.iloc[i]
        bid_open, bid_hi, bid_lo, bid_close = [float(bar[k]) for k in
                                              ("open", "high", "low", "close")]
        if pending is not None:
            p = pending
            pending = None
            side = p["side"]
            fill = bid_open + side * (half + cfg.slip_usd_oz_each_side)
            risk = side * (fill - p["stop"])
            if (risk > 0 and (side * (p["target"] - fill) -
                              (half + cfg.slip_usd_oz_each_side +
                               cfg.commission_usd_oz_roundtrip)) / risk >= cfg.min_rr
                    and equity > 0):
                ounces = equity * cfg.risk_fraction / risk
                position = dict(p, entry_utc=bar["open_time_utc"].isoformat(),
                                entry=fill, ounces=ounces, risk_usd=ounces * risk,
                                entry_index=i, equity_at_entry=equity)
            else:
                rejections["not_bible_admitted"] += 1
        if position is not None:
            side = position["side"]
            stop, target = position["stop"], position["target"]
            # Real bid proxy has no historical ask. For short stop/target we
            # require synthetic ask adjusted levels, never free bid exits.
            hi_exit, lo_exit = ((bid_hi, bid_lo) if side == 1 else
                                (bid_hi + cfg.spread_usd_oz, bid_lo + cfg.spread_usd_oz))
            at_open_exit = bid_open if side == 1 else bid_open + cfg.spread_usd_oz
            stop_hit = lo_exit <= stop if side == 1 else hi_exit >= stop
            target_hit = hi_exit >= target if side == 1 else lo_exit <= target
            reason, exit_price = None, None
            if stop_hit:
                reason = "STOP"  # adverse tie-break if same H1 hits both
                exit_price = min(stop, at_open_exit) if side == 1 else max(stop, at_open_exit)
            elif target_hit:
                reason = "TARGET"
                exit_price = target
            if reason:
                exit_price -= side * cfg.slip_usd_oz_each_side
                pnl = (exit_price - position["entry"]) * side * position["ounces"]
                fee = cfg.commission_usd_oz_roundtrip * position["ounces"]
                pnl -= fee
                equity += pnl
                trades.append({k: position[k] for k in (
                    "family", "bible_reference", "signal_time_utc", "entry_utc", "side",
                    "mode", "level", "level_type", "pattern", "stop", "target",
                    "estimated_rr", "entry", "ounces", "risk_usd")}
                              | {"exit_utc": (bar["open_time_utc"] + pd.Timedelta(hours=1)).isoformat(),
                                 "exit_price": round(exit_price, 6),
                                 "reason": reason, "net_pnl_usd": round(pnl, 4)})
                position = None
        if position is not None:
            close_exit = bid_close if position["side"] == 1 else bid_close + cfg.spread_usd_oz
            marked = equity + ((close_exit - position["entry"]) * position["side"] -
                               cfg.commission_usd_oz_roundtrip) * position["ounces"]
        else:
            marked = equity
        marks.append({"time_utc": (bar["open_time_utc"] + pd.Timedelta(hours=1)).isoformat(),
                      "equity_usd": round(marked, 4)})
        if i == len(df) - 1:
            break
        possible = [c for c in candidates_at(df, i, h4, day, week, cfg)
                    if c["family"] in families]
        if position or pending:
            rejections["portfolio_busy"] += len(possible)
            continue
        if possible:
            possible.sort(key=lambda c: (-c["estimated_rr"], FAMILIES.index(c["family"])))
            chosen = possible[0]
            counts[chosen["family"]] += 1
            rejections["conflicting_signals"] += len(possible) - 1
            pending = chosen
    eq = np.asarray([m["equity_usd"] for m in marks])
    high = np.maximum.accumulate(np.concatenate([[cfg.capital_usd], eq]))[1:]
    dd = (eq / high - 1) * 100
    unrealized_position = None
    if position is not None:
        unrealized_position = {k: position[k] for k in (
            "family", "signal_time_utc", "entry_utc", "side", "entry",
            "stop", "target", "ounces", "risk_usd")}
        unrealized_position["status"] = "CENSORED_AT_HISTORY_END_NOT_CLOSED"
        unrealized_position["unrealized_model_pnl_usd"] = round(
            float(eq[-1]) - equity, 4)
    result = {
        "schema": "gold_hunter.bible_multisystem_research.v0",
        "status": "HISTORICAL_RESEARCH_ONLY",
        "data_basis": "H1_NATIVE_M1_HISTDATA_BID_WITH_ILLUSTRATIVE_ASK",
        "price_rows": len(df), "start_utc": df.iloc[0]["open_time_utc"].isoformat(),
        "end_utc": df.iloc[-1]["open_time_utc"].isoformat(),
        "families": list(families), "bible_gate": "HTF_TREND_OR_RANGE+SIGNIFICANT_LEVEL+COMPLETED_PATTERN+RR>=2",
        "costs_and_policy": asdict(cfg), "counts_selected": counts,
        "rejections": rejections, "closed_trades": len(trades),
        "win_rate_percent": round(100 * sum(t["net_pnl_usd"] > 0 for t in trades)/len(trades), 2) if trades else None,
        "net_modelled_usd": round(float(eq[-1]) - cfg.capital_usd, 2),
        "ending_equity_usd": round(float(eq[-1]), 2),
        "realized_balance_usd": round(equity, 2),
        "unrealized_open_position": unrealized_position,
        "max_marked_drawdown_percent": round(float(dd.min()), 3),
        "trades": trades, "equity_marks": marks,
        "limitations": ["Retrospective BID source; synthetic ASK/spread and slippage",
                        "No actual swap/funding/contract lots/stopout/partial fills",
                        "H1 OHLC cannot establish intrabar order; stop-first tie",
                        "Unreviewed AI mechanical thresholds; source chart parity pending",
                        "One position shared across eligible systems; no broker orders"],
    }
    result["result_sha256"] = hashlib.sha256(json.dumps(
        {k: v for k, v in result.items() if k != "result_sha256"},
        sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()).hexdigest()
    return result