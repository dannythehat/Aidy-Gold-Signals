"""Build 4: shared deterministic price mathematics for AIDY Gold experts.

This module generalises already-proven AIDY feature/structure ideas across every
price timeframe. It emits factual, PIT-safe primitives only. It does not create a
gate vote, historical trust weight or live-money action.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation, localcontext
from hashlib import sha256
from itertools import pairwise
from typing import Any

from aidy.feature_engine import Candle, normalize_candles
from aidy.historical_backfill import RETROSPECTIVE_PROVENANCE

PRICE_EXPERT_MATH_VERSION = "aidy_gold_price_expert_math_v1"
PIT_PROVENANCE = "pit_observed"

TIMEFRAME_SECONDS = {
    "M1": 60,
    "M5": 300,
    "M15": 900,
    "H1": 3600,
    "H4": 14400,
    "D1": 86400,
}
MULTI_RETURN_LOOKBACKS = (1, 3, 5, 8, 13, 20)
REGRESSION_WINDOWS = (5, 8, 13, 20)
RANGE_WINDOWS = (20, 50)
SWING_WING = 2
_SCALE = Decimal("0.000001")

PRIMITIVE_DEFINITIONS = (
    ("multi_lookback_returns", "trend_path"),
    ("log_ols_slope", "trend_path"),
    ("close_step_persistence", "trend_path"),
    ("path_efficiency", "trend_path"),
    ("atr_rv_normalisation", "volatility"),
    ("acceleration_deceleration", "momentum"),
    ("confirmed_swing_sequence", "swing_structure"),
    ("structure_break", "swing_structure"),
    ("breakout_lifecycle", "breakout_acceptance"),
    ("range_position", "location"),
    ("candle_geometry", "candle_pressure"),
    ("contradiction_flags", "diagnostic"),
)


def _utc(value: datetime | str) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError("price-expert timestamps must be timezone-aware")
    return parsed.astimezone(UTC)


def _decimal(value: Any, *, field: str) -> Decimal:
    if value is None or isinstance(value, bool):
        raise ValueError(f"{field} is required")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field} must be a finite decimal") from exc
    if not parsed.is_finite():
        raise ValueError(f"{field} must be a finite decimal")
    return parsed


def _fmt(value: Decimal | None) -> str | None:
    if value is None:
        return None
    with localcontext() as ctx:
        ctx.prec = 34
        rounded = value.quantize(_SCALE, rounding=ROUND_HALF_EVEN)
    if rounded == 0:
        return "0"
    return format(rounded, "f").rstrip("0").rstrip(".")


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value: object) -> str:
    return sha256(_canonical_json(value).encode()).hexdigest()


def _bps(delta: Decimal, denominator: Decimal) -> Decimal | None:
    if denominator == 0:
        return None
    with localcontext() as ctx:
        ctx.prec = 34
        return delta / denominator * Decimal(10000)


def _completed(grouped: Mapping[str, list[Candle]], *, as_of: datetime) -> dict[str, list[Candle]]:
    result: dict[str, list[Candle]] = {}
    for timeframe, candles in grouped.items():
        duration = timedelta(seconds=TIMEFRAME_SECONDS[timeframe])
        result[timeframe] = [
            candle
            for candle in candles
            if candle.open_time_utc + duration <= as_of
        ]
    return result


def _direction(value: Decimal | None) -> str:
    if value is None:
        return "unknown"
    if value > 0:
        return "bullish"
    if value < 0:
        return "bearish"
    return "flat"


def _return_bps(current: Decimal, previous: Decimal) -> Decimal | None:
    return _bps(current - previous, previous)


def _multi_returns(candles: list[Candle]) -> dict[str, Any]:
    current = candles[-1].close if candles else None
    values: dict[str, Any] = {}
    for lookback in MULTI_RETURN_LOOKBACKS:
        key = f"{lookback}_bar"
        if current is None or len(candles) < lookback + 1:
            values[key] = {
                "lookback_bars": lookback,
                "state": "insufficient",
                "return_bps": None,
                "direction": "unknown",
            }
            continue
        value = _return_bps(current, candles[-(lookback + 1)].close)
        values[key] = {
            "lookback_bars": lookback,
            "state": "known",
            "return_bps": _fmt(value),
            "direction": _direction(value),
        }
    return {
        "primitive_id": "multi_lookback_returns",
        "family": "trend_path",
        "values": values,
    }


def _log_regression(candles: list[Candle], window: int) -> dict[str, Any]:
    if len(candles) < window:
        return {
            "window_bars": window,
            "state": "insufficient",
            "slope_log_bps_per_bar": None,
            "r_squared": None,
            "direction": "unknown",
        }
    sample = candles[-window:]
    if any(item.close <= 0 for item in sample):
        return {
            "window_bars": window,
            "state": "invalid",
            "slope_log_bps_per_bar": None,
            "r_squared": None,
            "direction": "unknown",
        }

    with localcontext() as ctx:
        ctx.prec = 34
        xs = [Decimal(i) for i in range(window)]
        ys = [item.close.ln() for item in sample]
        x_mean = sum(xs, Decimal(0)) / Decimal(window)
        y_mean = sum(ys, Decimal(0)) / Decimal(window)
        ss_x = sum(((x - x_mean) ** 2 for x in xs), Decimal(0))
        ss_y = sum(((y - y_mean) ** 2 for y in ys), Decimal(0))
        covariance = sum(
            ((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys, strict=True)),
            Decimal(0),
        )
        slope = Decimal(0) if ss_x == 0 else covariance / ss_x
        fitted = [y_mean + slope * (x - x_mean) for x in xs]
        residual_ss = sum(
            ((y - y_hat) ** 2 for y, y_hat in zip(ys, fitted, strict=True)),
            Decimal(0),
        )
        if ss_y == 0:
            r_squared = Decimal(1)
        else:
            r_squared = max(Decimal(0), min(Decimal(1), Decimal(1) - residual_ss / ss_y))
        slope_bps = slope * Decimal(10000)

    return {
        "window_bars": window,
        "state": "known",
        "slope_log_bps_per_bar": _fmt(slope_bps),
        "r_squared": _fmt(r_squared),
        "direction": _direction(slope_bps),
    }


def _regressions(candles: list[Candle]) -> dict[str, Any]:
    return {
        "primitive_id": "log_ols_slope",
        "family": "trend_path",
        "windows": {
            f"{window}_bar": _log_regression(candles, window)
            for window in REGRESSION_WINDOWS
        },
    }


def _persistence(candles: list[Candle], window: int = 8) -> dict[str, Any]:
    if len(candles) < window:
        return {
            "primitive_id": "close_step_persistence",
            "family": "trend_path",
            "window_bars": window,
            "state": "insufficient",
            "net_direction": "unknown",
            "up_step_ratio": None,
            "down_step_ratio": None,
            "flat_step_ratio": None,
            "directional_persistence_ratio": None,
        }
    sample = candles[-window:]
    changes = [right.close - left.close for left, right in pairwise(sample)]
    transitions = Decimal(len(changes))
    up = sum(item > 0 for item in changes)
    down = sum(item < 0 for item in changes)
    flat = sum(item == 0 for item in changes)
    net = sample[-1].close - sample[0].close
    direction = _direction(net)
    matching = up if direction == "bullish" else down if direction == "bearish" else flat
    with localcontext() as ctx:
        ctx.prec = 34
        return {
            "primitive_id": "close_step_persistence",
            "family": "trend_path",
            "window_bars": window,
            "state": "known",
            "net_direction": direction,
            "up_step_ratio": _fmt(Decimal(up) / transitions),
            "down_step_ratio": _fmt(Decimal(down) / transitions),
            "flat_step_ratio": _fmt(Decimal(flat) / transitions),
            "directional_persistence_ratio": _fmt(Decimal(matching) / transitions),
        }


def _path_efficiency(candles: list[Candle], window: int = 8) -> dict[str, Any]:
    if len(candles) < window:
        return {
            "primitive_id": "path_efficiency",
            "family": "trend_path",
            "window_bars": window,
            "state": "insufficient",
            "efficiency_ratio": None,
            "signed_efficiency": None,
            "net_displacement_bps": None,
            "total_path_bps": None,
        }
    sample = candles[-window:]
    net = sample[-1].close - sample[0].close
    path = sum(
        (abs(right.close - left.close) for left, right in pairwise(sample)),
        Decimal(0),
    )
    efficiency = Decimal(0) if path == 0 else abs(net) / path
    signed = efficiency if net > 0 else -efficiency if net < 0 else Decimal(0)
    net_bps = _bps(net, sample[0].close)
    path_bps = _bps(path, sample[0].close)
    return {
        "primitive_id": "path_efficiency",
        "family": "trend_path",
        "window_bars": window,
        "state": "known",
        "efficiency_ratio": _fmt(efficiency),
        "signed_efficiency": _fmt(signed),
        "net_displacement_bps": _fmt(net_bps),
        "total_path_bps": _fmt(path_bps),
    }


def _atr_bps(candles: list[Candle], period: int = 14) -> Decimal | None:
    if len(candles) < period + 1:
        return None
    sample = candles[-(period + 1):]
    true_ranges: list[Decimal] = []
    for previous, current in pairwise(sample):
        true_ranges.append(
            max(
                current.high - current.low,
                abs(current.high - previous.close),
                abs(current.low - previous.close),
            )
        )
    with localcontext() as ctx:
        ctx.prec = 34
        average = sum(true_ranges, Decimal(0)) / Decimal(period)
    return _bps(average, sample[-1].close)


def _realized_vol_bps(candles: list[Candle], period: int = 20) -> Decimal | None:
    if len(candles) < period + 1:
        return None
    sample = candles[-(period + 1):]
    returns: list[Decimal] = []
    for left, right in pairwise(sample):
        if left.close == 0:
            return None
        returns.append(right.close / left.close - Decimal(1))
    with localcontext() as ctx:
        ctx.prec = 34
        mean = sum(returns, Decimal(0)) / Decimal(period)
        variance = sum(((item - mean) ** 2 for item in returns), Decimal(0)) / Decimal(period)
        return variance.sqrt() * Decimal(10000)


def _normalised_movement(candles: list[Candle]) -> dict[str, Any]:
    atr = _atr_bps(candles)
    rv = _realized_vol_bps(candles)
    values: dict[str, Any] = {}
    for lookback in (3, 5, 8, 13):
        if len(candles) < lookback + 1:
            values[f"{lookback}_bar"] = {
                "state": "insufficient",
                "return_bps": None,
                "atr_units": None,
                "rv_units": None,
            }
            continue
        value = _return_bps(candles[-1].close, candles[-(lookback + 1)].close)
        atr_units = None if atr in (None, Decimal(0)) or value is None else value / atr
        rv_units = None if rv in (None, Decimal(0)) or value is None else value / rv
        values[f"{lookback}_bar"] = {
            "state": "known",
            "return_bps": _fmt(value),
            "atr_units": _fmt(atr_units),
            "rv_units": _fmt(rv_units),
        }
    return {
        "primitive_id": "atr_rv_normalisation",
        "family": "volatility",
        "atr_14_bps": _fmt(atr),
        "realized_vol_20_bps": _fmt(rv),
        "normalised_returns": values,
    }


def _acceleration(candles: list[Candle], segment: int = 4) -> dict[str, Any]:
    required = segment * 2 + 1
    if len(candles) < required:
        return {
            "primitive_id": "acceleration_deceleration",
            "family": "momentum",
            "state": "insufficient",
            "segment_bars": segment,
            "previous_return_bps": None,
            "recent_return_bps": None,
            "signed_acceleration_bps": None,
            "absolute_acceleration_bps": None,
            "state_label": "unknown",
        }
    sample = candles[-required:]
    previous = _return_bps(sample[segment].close, sample[0].close)
    recent = _return_bps(sample[-1].close, sample[segment].close)
    assert previous is not None and recent is not None
    signed = recent - previous
    absolute = abs(recent) - abs(previous)
    previous_direction = _direction(previous)
    recent_direction = _direction(recent)
    if previous_direction in {"bullish", "bearish"} and recent_direction != previous_direction:
        label = "direction_reversal"
    elif recent_direction == "flat" and previous_direction == "flat":
        label = "flat"
    elif previous_direction == recent_direction:
        if absolute > 0:
            label = "accelerating"
        elif absolute < 0:
            label = "decelerating"
        else:
            label = "steady"
    else:
        label = "mixed"
    return {
        "primitive_id": "acceleration_deceleration",
        "family": "momentum",
        "state": "known",
        "segment_bars": segment,
        "previous_return_bps": _fmt(previous),
        "recent_return_bps": _fmt(recent),
        "signed_acceleration_bps": _fmt(signed),
        "absolute_acceleration_bps": _fmt(absolute),
        "state_label": label,
    }


def _confirmed_pivots(candles: list[Candle], *, high: bool, wing: int = SWING_WING) -> list[dict[str, Any]]:
    pivots: list[dict[str, Any]] = []
    if len(candles) < wing * 2 + 1:
        return pivots
    for index in range(wing, len(candles) - wing):
        candidate = candles[index]
        neighbors = candles[index - wing:index] + candles[index + 1:index + wing + 1]
        price = candidate.high if high else candidate.low
        qualifies = (
            all(price > item.high for item in neighbors)
            if high
            else all(price < item.low for item in neighbors)
        )
        if not qualifies:
            continue
        confirmed_index = index + wing
        pivots.append(
            {
                "index": index,
                "confirmed_index": confirmed_index,
                "open_time_utc": candidate.open_time_utc.isoformat(),
                "confirmed_after_open_time_utc": candles[confirmed_index].open_time_utc.isoformat(),
                "price": _fmt(price),
                "identity": candidate.identity,
            }
        )
    return pivots


def _sequence_label(pivots: list[dict[str, Any]], *, high: bool) -> str:
    if len(pivots) < 2:
        return "unknown"
    left = _decimal(pivots[-2]["price"], field="swing price")
    right = _decimal(pivots[-1]["price"], field="swing price")
    if right > left:
        return "higher_high" if high else "higher_low"
    if right < left:
        return "lower_high" if high else "lower_low"
    return "equal_high" if high else "equal_low"


def _swings(candles: list[Candle]) -> dict[str, Any]:
    highs = _confirmed_pivots(candles, high=True)
    lows = _confirmed_pivots(candles, high=False)
    high_label = _sequence_label(highs, high=True)
    low_label = _sequence_label(lows, high=False)
    if high_label == "higher_high" and low_label == "higher_low":
        combined = "bullish_structure"
    elif high_label == "lower_high" and low_label == "lower_low":
        combined = "bearish_structure"
    elif high_label == "unknown" or low_label == "unknown":
        combined = "insufficient"
    else:
        combined = "mixed_structure"
    return {
        "primitive_id": "confirmed_swing_sequence",
        "family": "swing_structure",
        "wing": SWING_WING,
        "confirmed_highs": highs[-3:],
        "confirmed_lows": lows[-3:],
        "high_sequence": high_label,
        "low_sequence": low_label,
        "combined_structure": combined,
    }


def _structure_break(candles: list[Candle], swings: Mapping[str, Any]) -> dict[str, Any]:
    if not candles:
        return {
            "primitive_id": "structure_break",
            "family": "swing_structure",
            "state": "unknown",
            "latest_close": None,
            "latest_swing_high": None,
            "latest_swing_low": None,
        }
    highs = list(swings.get("confirmed_highs") or [])
    lows = list(swings.get("confirmed_lows") or [])
    high = _decimal(highs[-1]["price"], field="swing high") if highs else None
    low = _decimal(lows[-1]["price"], field="swing low") if lows else None
    close = candles[-1].close
    if high is not None and close > high:
        state = "close_above_confirmed_swing_high"
    elif low is not None and close < low:
        state = "close_below_confirmed_swing_low"
    elif high is None and low is None:
        state = "unknown"
    else:
        state = "inside_confirmed_swings"
    return {
        "primitive_id": "structure_break",
        "family": "swing_structure",
        "state": state,
        "latest_close": _fmt(close),
        "latest_swing_high": _fmt(high),
        "latest_swing_low": _fmt(low),
    }


def _breakout_side(
    candles: list[Candle],
    pivot: Mapping[str, Any] | None,
    *,
    high: bool,
) -> dict[str, Any]:
    side = "high" if high else "low"
    if pivot is None:
        return {
            "side": side,
            "state": "unknown",
            "level": None,
            "penetrated": False,
            "close_beyond_count": 0,
            "accepted": False,
            "held_at_latest_close": False,
            "retest_hold": False,
            "reclaimed_inside": False,
        }
    level = _decimal(pivot["price"], field="breakout level")
    start = int(pivot["confirmed_index"]) + 1
    later = candles[start:]
    if not later:
        return {
            "side": side,
            "state": "no_post_confirmation_bars",
            "level": _fmt(level),
            "penetrated": False,
            "close_beyond_count": 0,
            "accepted": False,
            "held_at_latest_close": False,
            "retest_hold": False,
            "reclaimed_inside": False,
        }

    if high:
        penetrated = any(item.high > level for item in later)
        closes_beyond = [index for index, item in enumerate(later) if item.close > level]
        held = later[-1].close > level
        first_close_index = closes_beyond[0] if closes_beyond else None
        retest_hold = False
        if first_close_index is not None:
            retest_hold = any(
                item.low <= level and item.close > level
                for item in later[first_close_index + 1:]
            )
    else:
        penetrated = any(item.low < level for item in later)
        closes_beyond = [index for index, item in enumerate(later) if item.close < level]
        held = later[-1].close < level
        first_close_index = closes_beyond[0] if closes_beyond else None
        retest_hold = False
        if first_close_index is not None:
            retest_hold = any(
                item.high >= level and item.close < level
                for item in later[first_close_index + 1:]
            )

    accepted = len(closes_beyond) >= 2
    reclaimed = penetrated and not held
    if retest_hold:
        state = "retest_hold"
    elif accepted and held:
        state = "accepted_hold"
    elif closes_beyond and held:
        state = "single_close_hold"
    elif reclaimed:
        state = "reclaimed_inside"
    elif penetrated:
        state = "penetrated_no_close"
    else:
        state = "none"

    return {
        "side": side,
        "state": state,
        "level": _fmt(level),
        "penetrated": penetrated,
        "close_beyond_count": len(closes_beyond),
        "accepted": accepted,
        "held_at_latest_close": held,
        "retest_hold": retest_hold,
        "reclaimed_inside": reclaimed,
    }


def _breakout_lifecycle(candles: list[Candle], swings: Mapping[str, Any]) -> dict[str, Any]:
    highs = list(swings.get("confirmed_highs") or [])
    lows = list(swings.get("confirmed_lows") or [])
    return {
        "primitive_id": "breakout_lifecycle",
        "family": "breakout_acceptance",
        "high_side": _breakout_side(candles, highs[-1] if highs else None, high=True),
        "low_side": _breakout_side(candles, lows[-1] if lows else None, high=False),
    }


def _range_positions(candles: list[Candle]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for window in RANGE_WINDOWS:
        if len(candles) < window:
            values[f"{window}_bar"] = {
                "state": "insufficient",
                "high": None,
                "low": None,
                "position": None,
            }
            continue
        sample = candles[-window:]
        high = max(item.high for item in sample)
        low = min(item.low for item in sample)
        span = high - low
        position = None if span == 0 else (sample[-1].close - low) / span
        values[f"{window}_bar"] = {
            "state": "known",
            "high": _fmt(high),
            "low": _fmt(low),
            "position": _fmt(position),
        }
    return {
        "primitive_id": "range_position",
        "family": "location",
        "windows": values,
    }


def _candle_geometry(candles: list[Candle]) -> dict[str, Any]:
    if not candles:
        return {
            "primitive_id": "candle_geometry",
            "family": "candle_pressure",
            "state": "unknown",
        }
    candle = candles[-1]
    body_signed = candle.close - candle.open
    body = abs(body_signed)
    upper = candle.high - max(candle.open, candle.close)
    lower = min(candle.open, candle.close) - candle.low
    total = candle.high - candle.low
    close_location = None if total == 0 else (candle.close - candle.low) / total
    body_fraction = None if total == 0 else body / total
    return {
        "primitive_id": "candle_geometry",
        "family": "candle_pressure",
        "state": "known",
        "open_time_utc": candle.open_time_utc.isoformat(),
        "body_direction": _direction(body_signed),
        "body_bps": _fmt(_bps(body, candle.open)),
        "signed_body_bps": _fmt(_bps(body_signed, candle.open)),
        "upper_wick_bps": _fmt(_bps(upper, candle.open)),
        "lower_wick_bps": _fmt(_bps(lower, candle.open)),
        "range_bps": _fmt(_bps(total, candle.open)),
        "close_location": _fmt(close_location),
        "body_fraction_of_range": _fmt(body_fraction),
    }


def _contradictions(
    *,
    returns: Mapping[str, Any],
    regressions: Mapping[str, Any],
    swings: Mapping[str, Any],
    breakout: Mapping[str, Any],
    acceleration: Mapping[str, Any],
) -> dict[str, Any]:
    flags: list[str] = []
    regression_directions = {
        payload["direction"]
        for payload in regressions["windows"].values()
        if payload["state"] == "known" and payload["direction"] in {"bullish", "bearish"}
    }
    if len(regression_directions) > 1:
        flags.append("regression_windows_disagree")

    return_5 = returns["values"]["5_bar"]
    if return_5["state"] == "known" and len(regression_directions) == 1:
        slope_direction = next(iter(regression_directions))
        if return_5["direction"] in {"bullish", "bearish"} and return_5["direction"] != slope_direction:
            flags.append("recent_return_opposes_regression")

    combined = str(swings.get("combined_structure") or "")
    if combined == "bullish_structure" and "bearish" in regression_directions:
        flags.append("bullish_swings_opposed_by_regression")
    if combined == "bearish_structure" and "bullish" in regression_directions:
        flags.append("bearish_swings_opposed_by_regression")

    high_state = str((breakout.get("high_side") or {}).get("state") or "")
    low_state = str((breakout.get("low_side") or {}).get("state") or "")
    if high_state in {"accepted_hold", "retest_hold"} and "bearish" in regression_directions:
        flags.append("upside_acceptance_opposes_regression")
    if low_state in {"accepted_hold", "retest_hold"} and "bullish" in regression_directions:
        flags.append("downside_acceptance_opposes_regression")

    if acceleration.get("state_label") == "direction_reversal":
        flags.append("recent_acceleration_direction_reversal")

    return {
        "primitive_id": "contradiction_flags",
        "family": "diagnostic",
        "flags": sorted(set(flags)),
        "contradiction_count": len(set(flags)),
    }


def _analyze_timeframe(candles: list[Candle], *, timeframe: str) -> dict[str, Any]:
    returns = _multi_returns(candles)
    regressions = _regressions(candles)
    persistence = _persistence(candles)
    efficiency = _path_efficiency(candles)
    normalised = _normalised_movement(candles)
    acceleration = _acceleration(candles)
    swings = _swings(candles)
    structure_break = _structure_break(candles, swings)
    breakout = _breakout_lifecycle(candles, swings)
    ranges = _range_positions(candles)
    geometry = _candle_geometry(candles)
    contradictions = _contradictions(
        returns=returns,
        regressions=regressions,
        swings=swings,
        breakout=breakout,
        acceleration=acceleration,
    )

    primitives = [
        returns,
        regressions,
        persistence,
        efficiency,
        normalised,
        acceleration,
        swings,
        structure_break,
        breakout,
        ranges,
        geometry,
        contradictions,
    ]
    primitive_ids = [str(item["primitive_id"]) for item in primitives]
    if len(primitive_ids) != len(set(primitive_ids)):
        raise ValueError("duplicate price primitive id")

    return {
        "state": "known" if candles else "unknown",
        "timeframe": timeframe,
        "bars_available": len(candles),
        "latest_completed_open_time_utc": (
            candles[-1].open_time_utc.isoformat() if candles else None
        ),
        "source_identities": [item.identity for item in candles],
        "primitive_ids": primitive_ids,
        "duplicate_primitive_count": len(primitive_ids) - len(set(primitive_ids)),
        "primitives": {item["primitive_id"]: item for item in primitives},
    }


def build_price_expert_math_packet(
    *,
    as_of: datetime | str,
    symbol: str,
    candle_rows: Iterable[Mapping[str, Any]],
    mode: str,
) -> dict[str, Any]:
    cutoff = _utc(as_of)
    raw_rows = [dict(row) for row in candle_rows]
    grouped = normalize_candles(raw_rows, as_of=cutoff, symbol=symbol, mode=mode)
    completed = _completed(grouped, as_of=cutoff)

    if mode == "pit":
        provenance_class = PIT_PROVENANCE
        pit_eligible = True
    elif mode == "retrospective":
        provenance_class = RETROSPECTIVE_PROVENANCE
        pit_eligible = False
    else:
        raise ValueError("price-expert mode must be pit or retrospective")

    timeframes = {
        timeframe: _analyze_timeframe(completed[timeframe], timeframe=timeframe)
        for timeframe in TIMEFRAME_SECONDS
    }
    packet: dict[str, Any] = {
        "price_expert_math_version": PRICE_EXPERT_MATH_VERSION,
        "as_of_utc": cutoff.isoformat(),
        "symbol": symbol,
        "mode": mode,
        "provenance_class": provenance_class,
        "pit_eligible": pit_eligible,
        "completed_bar_policy": "open_time_plus_nominal_duration_lte_as_of",
        "timeframe_durations_seconds": dict(TIMEFRAME_SECONDS),
        "multi_return_lookbacks": list(MULTI_RETURN_LOOKBACKS),
        "regression_windows": list(REGRESSION_WINDOWS),
        "range_windows": list(RANGE_WINDOWS),
        "swing_wing": SWING_WING,
        "primitive_manifest": [
            {"primitive_id": primitive_id, "family": family}
            for primitive_id, family in PRIMITIVE_DEFINITIONS
        ],
        "timeframes": timeframes,
        "future_values_used": False,
        "directional_gate_vote_emitted": False,
        "historical_outcome_used": False,
        "research_only": True,
        "live_money_execution_allowed": False,
    }
    packet["packet_digest"] = _digest(packet)
    return packet


def verify_price_expert_math_packet(packet: Mapping[str, Any]) -> bool:
    if packet.get("price_expert_math_version") != PRICE_EXPERT_MATH_VERSION:
        return False
    body = dict(packet)
    supplied = str(body.pop("packet_digest", ""))
    if not supplied or supplied != _digest(body):
        return False
    if packet.get("future_values_used") is not False:
        return False
    if packet.get("directional_gate_vote_emitted") is not False:
        return False
    if packet.get("historical_outcome_used") is not False:
        return False
    if packet.get("research_only") is not True:
        return False
    if packet.get("live_money_execution_allowed") is not False:
        return False
    manifest = packet.get("primitive_manifest")
    if not isinstance(manifest, list):
        return False
    primitive_ids = [str(item.get("primitive_id") or "") for item in manifest if isinstance(item, Mapping)]
    if len(primitive_ids) != len(PRIMITIVE_DEFINITIONS) or len(primitive_ids) != len(set(primitive_ids)):
        return False
    timeframes = packet.get("timeframes")
    if not isinstance(timeframes, Mapping):
        return False
    for timeframe in TIMEFRAME_SECONDS:
        payload = timeframes.get(timeframe)
        if not isinstance(payload, Mapping):
            return False
        ids = payload.get("primitive_ids")
        if not isinstance(ids, list) or len(ids) != len(set(ids)):
            return False
        if payload.get("duplicate_primitive_count") != 0:
            return False
    return True


__all__ = [
    "MULTI_RETURN_LOOKBACKS",
    "PRICE_EXPERT_MATH_VERSION",
    "PRIMITIVE_DEFINITIONS",
    "RANGE_WINDOWS",
    "REGRESSION_WINDOWS",
    "SWING_WING",
    "TIMEFRAME_SECONDS",
    "build_price_expert_math_packet",
    "verify_price_expert_math_packet",
]
