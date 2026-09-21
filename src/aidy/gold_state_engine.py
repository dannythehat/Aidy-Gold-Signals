from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN, localcontext
from hashlib import sha256
from itertools import pairwise
from typing import Any

from aidy.feature_engine import Candle, normalize_candles

GOLD_STATE_ENGINE_VERSION = "aidy_gold_state_engine_v1"
PROVIDER_GOLD_STATE_VERSION = "aidy_provider_gold_state_v2"

_TIMEFRAME_SECONDS = {
    "M1": 60,
    "M5": 300,
    "M15": 900,
    "H1": 3600,
    "H4": 14400,
}
_SCALE = Decimal("0.000001")


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value: object) -> str:
    return sha256(_canonical_json(value).encode()).hexdigest()


def _utc(value: datetime | str) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError("Gold-state timestamps must be timezone-aware.")
    return parsed.astimezone(UTC)


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _fmt(value: Decimal | None) -> str | None:
    if value is None:
        return None
    with localcontext() as ctx:
        ctx.prec = 34
        rounded = value.quantize(_SCALE, rounding=ROUND_HALF_EVEN)
    if rounded == 0:
        return "0"
    text = format(rounded, "f").rstrip("0").rstrip(".")
    return text or "0"


def _ratio(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    if denominator == 0:
        return None
    with localcontext() as ctx:
        ctx.prec = 34
        return numerator / denominator


def _bps(delta: Decimal, denominator: Decimal) -> Decimal | None:
    ratio = _ratio(delta, denominator)
    return None if ratio is None else ratio * Decimal(10000)


def _completed(
    grouped: Mapping[str, list[Candle]],
    *,
    as_of: datetime,
) -> dict[str, list[Candle]]:
    result: dict[str, list[Candle]] = {}
    for timeframe, seconds in _TIMEFRAME_SECONDS.items():
        rows = list(grouped.get(timeframe) or [])
        duration = timedelta(seconds=seconds)
        result[timeframe] = [
            row for row in rows if row.open_time_utc + duration <= as_of
        ]
    return result


def _timeframe_state(rows: list[Candle]) -> dict[str, Any]:
    sample = rows[-8:]
    if len(sample) < 2:
        return {
            "state": "unknown",
            "sample_bars": len(sample),
            "net_close_direction": "unknown",
            "net_return_bps": None,
            "higher_close_steps": None,
            "lower_close_steps": None,
            "flat_close_steps": None,
            "directional_persistence_ratio": None,
            "latest_close": None if not sample else _fmt(sample[-1].close),
            "sample_high": None,
            "sample_low": None,
            "latest_close_range_position": None,
            "first_open_time_utc": None if not sample else sample[0].open_time_utc.isoformat(),
            "last_open_time_utc": None if not sample else sample[-1].open_time_utc.isoformat(),
        }

    first = sample[0].close
    last = sample[-1].close
    delta = last - first
    if delta > 0:
        direction = "up"
    elif delta < 0:
        direction = "down"
    else:
        direction = "flat"

    higher = 0
    lower = 0
    flat = 0
    for left, right in pairwise(sample):
        if right.close > left.close:
            higher += 1
        elif right.close < left.close:
            lower += 1
        else:
            flat += 1
    transitions = len(sample) - 1
    persistence = Decimal(max(higher, lower, flat)) / Decimal(transitions)

    high = max(row.high for row in sample)
    low = min(row.low for row in sample)
    range_position = _ratio(last - low, high - low)

    return {
        "state": "known" if len(sample) >= 5 else "partial",
        "sample_bars": len(sample),
        "net_close_direction": direction,
        "net_return_bps": _fmt(_bps(delta, first)),
        "higher_close_steps": higher,
        "lower_close_steps": lower,
        "flat_close_steps": flat,
        "directional_persistence_ratio": _fmt(persistence),
        "latest_close": _fmt(last),
        "sample_high": _fmt(high),
        "sample_low": _fmt(low),
        "latest_close_range_position": _fmt(range_position),
        "first_open_time_utc": sample[0].open_time_utc.isoformat(),
        "last_open_time_utc": sample[-1].open_time_utc.isoformat(),
    }


def _market_structure(completed: Mapping[str, list[Candle]]) -> dict[str, Any]:
    timeframes = {
        timeframe: _timeframe_state(list(completed.get(timeframe) or []))
        for timeframe in _TIMEFRAME_SECONDS
    }
    known = sum(item["state"] in {"known", "partial"} for item in timeframes.values())
    return {
        "state": "known" if known == len(timeframes) else "partial" if known else "unknown",
        "decision_input_allowed": bool(known),
        "definition": "completed_bar_multi_timeframe_close_path_v1",
        "predictive_edge_claimed": False,
        "timeframes": timeframes,
    }


def _reference(
    *,
    mid: Decimal,
    value: Any,
    source_path: str,
) -> dict[str, Any] | None:
    level = _decimal(value)
    if level is None or level == 0:
        return None
    delta = mid - level
    return {
        "source_path": source_path,
        "level": _fmt(level),
        "mid_minus_level": _fmt(delta),
        "distance_bps": _fmt(_bps(delta, level)),
        "relative_side": "above" if delta > 0 else "below" if delta < 0 else "at",
    }


def _range_position(*, mid: Decimal, low: Any, high: Any) -> str | None:
    low_d = _decimal(low)
    high_d = _decimal(high)
    if low_d is None or high_d is None or high_d <= low_d:
        return None
    return _fmt(_ratio(mid - low_d, high_d - low_d))


def _nearest_increment(value: Decimal, increment: Decimal) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = 34
        units = (value / increment).quantize(Decimal(1), rounding=ROUND_HALF_EVEN)
        return units * increment


def _location(
    *,
    semantic_context: Mapping[str, Any],
    structure: Mapping[str, Any],
) -> dict[str, Any]:
    gold = semantic_context.get("gold")
    gold = gold if isinstance(gold, Mapping) else {}
    quote = gold.get("quote_context")
    quote = quote if isinstance(quote, Mapping) else {}
    mid = _decimal(quote.get("mid"))
    if mid is None:
        return {
            "state": "unknown",
            "decision_input_allowed": False,
            "mid": None,
            "reference_distances": {},
            "range_positions": {},
            "round_number_references": {},
        }

    references: dict[str, Any] = {}
    ranges: dict[str, Any] = {}

    prior = structure.get("prior_periods")
    prior = prior if isinstance(prior, Mapping) else {}
    prior_day = prior.get("prior_day")
    prior_day = prior_day if isinstance(prior_day, Mapping) else {}
    if prior_day.get("state") == "known":
        for field in ("high", "low", "close"):
            item = _reference(
                mid=mid,
                value=prior_day.get(field),
                source_path=f"price_structure.prior_periods.prior_day.{field}",
            )
            if item is not None:
                references[f"prior_day_{field}"] = item
        pos = _range_position(mid=mid, low=prior_day.get("low"), high=prior_day.get("high"))
        if pos is not None:
            ranges["prior_day"] = pos

    overnight = structure.get("asia_overnight_range")
    overnight = overnight if isinstance(overnight, Mapping) else {}
    if overnight.get("state") == "known":
        for field in ("high", "low"):
            item = _reference(
                mid=mid,
                value=overnight.get(field),
                source_path=f"price_structure.asia_overnight_range.{field}",
            )
            if item is not None:
                references[f"asia_overnight_{field}"] = item
        pos = _range_position(mid=mid, low=overnight.get("low"), high=overnight.get("high"))
        if pos is not None:
            ranges["asia_overnight"] = pos

    sessions = structure.get("session_extremes")
    sessions = sessions if isinstance(sessions, Mapping) else {}
    for session in ("asia", "london", "new_york"):
        payload = sessions.get(session)
        payload = payload if isinstance(payload, Mapping) else {}
        if payload.get("state") not in {"observed_so_far", "complete"}:
            continue
        for field in ("high", "low"):
            item = _reference(
                mid=mid,
                value=payload.get(field),
                source_path=f"price_structure.session_extremes.{session}.{field}",
            )
            if item is not None:
                references[f"{session}_{field}"] = item
        pos = _range_position(mid=mid, low=payload.get("low"), high=payload.get("high"))
        if pos is not None:
            ranges[session] = pos

    opening_ranges = structure.get("opening_ranges")
    opening_ranges = opening_ranges if isinstance(opening_ranges, Mapping) else {}
    for session in ("asia", "london", "new_york"):
        session_ranges = opening_ranges.get(session)
        session_ranges = session_ranges if isinstance(session_ranges, Mapping) else {}
        for window in ("15m", "30m", "60m"):
            payload = session_ranges.get(window)
            payload = payload if isinstance(payload, Mapping) else {}
            if payload.get("state") != "known":
                continue
            for field in ("high", "low"):
                item = _reference(
                    mid=mid,
                    value=payload.get(field),
                    source_path=(
                        f"price_structure.opening_ranges.{session}.{window}.{field}"
                    ),
                )
                if item is not None:
                    references[f"{session}_opening_{window}_{field}"] = item
            pos = _range_position(
                mid=mid,
                low=payload.get("low"),
                high=payload.get("high"),
            )
            if pos is not None:
                ranges[f"{session}_opening_{window}"] = pos

    round_refs: dict[str, Any] = {}
    for label, increment in (("nearest_10_usd", Decimal(10)), ("nearest_50_usd", Decimal(50))):
        level = _nearest_increment(mid, increment)
        round_refs[label] = {
            "level": _fmt(level),
            "mid_minus_level": _fmt(mid - level),
            "distance_bps": _fmt(_bps(mid - level, level)) if level else None,
            "descriptive_only": True,
        }

    return {
        "state": "known",
        "decision_input_allowed": True,
        "mid": _fmt(mid),
        "reference_distances": references,
        "range_positions": ranges,
        "round_number_references": round_refs,
        "round_numbers_predictive_edge_claimed": False,
    }


def _liquidity(
    *,
    structure: Mapping[str, Any],
) -> dict[str, Any]:
    proxies: list[dict[str, Any]] = []
    breakout = structure.get("prior_day_breakout")
    breakout = breakout if isinstance(breakout, Mapping) else {}
    state = str(breakout.get("state") or "unknown")
    if state == "upside_failed":
        proxies.append(
            {
                "kind": "prior_day_high_penetration_reclaim_proxy",
                "side": "high",
                "source_path": "price_structure.prior_day_breakout",
            }
        )
    elif state == "downside_failed":
        proxies.append(
            {
                "kind": "prior_day_low_penetration_reclaim_proxy",
                "side": "low",
                "source_path": "price_structure.prior_day_breakout",
            }
        )

    swing = structure.get("swing_extreme_penetration_with_reversion")
    swing = swing if isinstance(swing, Mapping) else {}
    for key, side in (("high_side", "high"), ("low_side", "low")):
        payload = swing.get(key)
        payload = payload if isinstance(payload, Mapping) else {}
        if payload.get("penetrated") is True and payload.get("reverted") is True:
            proxies.append(
                {
                    "kind": "confirmed_m15_swing_penetration_reclaim_proxy",
                    "side": side,
                    "swing_price": payload.get("swing_price"),
                    "max_penetration_bps": payload.get("max_penetration_bps"),
                    "source_path": (
                        "price_structure.swing_extreme_penetration_with_reversion."
                        f"{key}"
                    ),
                }
            )

    return {
        "state": "known" if structure else "unknown",
        "decision_input_allowed": bool(structure),
        "proxy_not_order_flow": True,
        "hidden_order_flow_claimed": False,
        "sweep_reclaim_proxies": proxies,
        "prior_periods": dict(structure.get("prior_periods") or {}),
        "asia_overnight_range": dict(structure.get("asia_overnight_range") or {}),
        "opening_ranges": dict(structure.get("opening_ranges") or {}),
        "session_extremes": dict(structure.get("session_extremes") or {}),
        "prior_day_breakout": dict(breakout),
        "swing_extreme_penetration_with_reversion": dict(swing),
        "wick_footprint": dict(structure.get("wick_footprint") or {}),
    }


def _window_move(rows: list[Candle], bars: int) -> dict[str, Any]:
    if len(rows) < bars:
        return {
            "state": "unknown_insufficient_bars",
            "required_bars": bars,
            "observed_bars": len(rows),
            "return_bps": None,
            "range_bps": None,
        }
    sample = rows[-bars:]
    start = sample[0].open
    finish = sample[-1].close
    high = max(row.high for row in sample)
    low = min(row.low for row in sample)
    return {
        "state": "known",
        "required_bars": bars,
        "observed_bars": bars,
        "start_open": _fmt(start),
        "last_close": _fmt(finish),
        "return_bps": _fmt(_bps(finish - start, start)),
        "absolute_return_bps": _fmt(abs(_bps(finish - start, start) or Decimal(0))),
        "range_bps": _fmt(_bps(high - low, start)),
        "direction": "up" if finish > start else "down" if finish < start else "flat",
        "first_open_time_utc": sample[0].open_time_utc.isoformat(),
        "last_open_time_utc": sample[-1].open_time_utc.isoformat(),
    }


def _five_minute_baseline(rows: list[Candle]) -> tuple[str, str | None, int]:
    if len(rows) < 65:
        return "unknown_insufficient_baseline", None, 0
    latest = rows[-5:]
    latest_start = latest[0].open
    latest_abs = abs(_bps(latest[-1].close - latest_start, latest_start) or Decimal(0))

    history = rows[:-5][-120:]
    blocks: list[Decimal] = []
    end = len(history)
    while end >= 5:
        sample = history[end - 5 : end]
        start = sample[0].open
        blocks.append(abs(_bps(sample[-1].close - start, start) or Decimal(0)))
        end -= 5
    if len(blocks) < 12:
        return "unknown_insufficient_baseline", None, len(blocks)
    rank = sum(value <= latest_abs for value in blocks)
    percentile = Decimal(rank) / Decimal(len(blocks))
    if percentile >= Decimal("0.95"):
        state = "extreme_recent_displacement"
    elif percentile >= Decimal("0.80"):
        state = "elevated_recent_displacement"
    else:
        state = "within_recent_distribution"
    return state, _fmt(percentile), len(blocks)


def _five_minute_range_baseline(rows: list[Candle]) -> tuple[str, str | None, int]:
    if len(rows) < 65:
        return "unknown_insufficient_baseline", None, 0
    latest = rows[-5:]
    latest_start = latest[0].open
    latest_range = _bps(
        max(row.high for row in latest) - min(row.low for row in latest),
        latest_start,
    ) or Decimal(0)

    history = rows[:-5][-120:]
    blocks: list[Decimal] = []
    end = len(history)
    while end >= 5:
        sample = history[end - 5 : end]
        start = sample[0].open
        value = _bps(
            max(row.high for row in sample) - min(row.low for row in sample),
            start,
        ) or Decimal(0)
        blocks.append(value)
        end -= 5
    if len(blocks) < 12:
        return "unknown_insufficient_baseline", None, len(blocks)
    rank = sum(value <= latest_range for value in blocks)
    percentile = Decimal(rank) / Decimal(len(blocks))
    if percentile >= Decimal("0.95"):
        state = "extreme_range_expansion"
    elif percentile >= Decimal("0.80"):
        state = "range_expansion"
    elif percentile <= Decimal("0.20"):
        state = "range_compression"
    else:
        state = "normal_range"
    return state, _fmt(percentile), len(blocks)


def _move_observation(
    *,
    m1: list[Candle],
    event_risk: Mapping[str, Any],
    liquidity: Mapping[str, Any],
    volatility: Mapping[str, Any],
) -> dict[str, Any]:
    windows = {
        "5m": _window_move(m1, 5),
        "15m": _window_move(m1, 15),
        "60m": _window_move(m1, 60),
    }
    classification, percentile, baseline_n = _five_minute_baseline(m1)
    range_state, range_percentile, range_baseline_n = _five_minute_range_baseline(m1)
    contexts: list[dict[str, Any]] = []

    if event_risk.get("evidence_state") == "known":
        timing = str(event_risk.get("timing_state") or "unknown")
        contexts.append(
            {
                "mechanism": "scheduled_event_timing_context",
                "state": timing,
                "causal_claim": False,
            }
        )

    proxies = liquidity.get("sweep_reclaim_proxies")
    if isinstance(proxies, list) and proxies:
        contexts.append(
            {
                "mechanism": "measured_liquidity_reclaim_proxy",
                "state": "present",
                "proxy_count": len(proxies),
                "causal_claim": False,
            }
        )

    jump = volatility.get("jump_continuous")
    jump = jump if isinstance(jump, Mapping) else {}
    jump_state = str(jump.get("state") or "unknown")
    if jump_state != "unknown":
        contexts.append(
            {
                "mechanism": "volatility_jump_continuity_context",
                "state": jump_state,
                "causal_claim": False,
            }
        )

    elevated = classification in {
        "extreme_recent_displacement",
        "elevated_recent_displacement",
    }

    return {
        "state": "known" if windows["5m"]["state"] == "known" else "unknown",
        "decision_input_allowed": windows["5m"]["state"] == "known",
        "windows": windows,
        "five_minute_distribution_state": classification,
        "five_minute_abs_return_percentile": percentile,
        "five_minute_baseline_blocks": baseline_n,
        "five_minute_range_state": range_state,
        "five_minute_range_percentile": range_percentile,
        "five_minute_range_baseline_blocks": range_baseline_n,
        "mechanism_context": contexts,
        "causal_attribution_proven": False,
        "cause_unknown": bool(elevated),
        "definition": "completed_m1_recent_displacement_vs_prior_nonoverlap_5m_blocks_v1",
    }


def build_gold_state_engine(
    *,
    as_of: datetime | str,
    symbol: str,
    candle_rows: Iterable[Mapping[str, Any]],
    semantic_context: Mapping[str, Any],
    price_structure_packet: Mapping[str, Any],
    volatility_state: Mapping[str, Any],
) -> dict[str, Any]:
    cutoff = _utc(as_of)
    if symbol != "XAUUSD":
        raise ValueError("Gold State Engine supports XAUUSD only.")
    if price_structure_packet.get("mode") != "pit":
        raise ValueError("Gold State Engine requires PIT price structure.")
    if price_structure_packet.get("pit_eligible") is not True:
        raise ValueError("Gold State Engine requires PIT-eligible price structure.")
    if price_structure_packet.get("future_values_used") is not False:
        raise ValueError("Gold State Engine rejects future-valued price structure.")
    if volatility_state.get("mode") != "pit":
        raise ValueError("Gold State Engine requires PIT volatility state.")
    if volatility_state.get("retrospective_history_included") is not False:
        raise ValueError("Gold State Engine rejects retrospective volatility history.")

    raw_rows = [dict(row) for row in candle_rows]
    grouped = normalize_candles(raw_rows, as_of=cutoff, symbol=symbol, mode="pit")
    completed = _completed(grouped, as_of=cutoff)

    structure = price_structure_packet.get("structure")
    structure = structure if isinstance(structure, Mapping) else {}
    event_risk = semantic_context.get("event_risk")
    event_risk = event_risk if isinstance(event_risk, Mapping) else {}
    session_context = semantic_context.get("session")
    session_context = session_context if isinstance(session_context, Mapping) else {}
    session_state = {
        "state": "known" if session_context else "unknown",
        "decision_input_allowed": bool(session_context),
        "computed_session_code": session_context.get("computed_session_code"),
        "recorded_session_code": session_context.get("recorded_session_code"),
        "session_code_consistent": session_context.get("session_code_consistent"),
    }

    market_structure = _market_structure(completed)
    liquidity = _liquidity(structure=structure)
    location = _location(semantic_context=semantic_context, structure=structure)

    volatility_allowed = (
        volatility_state.get("decision_input_allowed") is True
        and volatility_state.get("retrospective_history_included") is False
    )
    volatility = {
        "state": str(volatility_state.get("state") or "unknown"),
        "decision_input_allowed": volatility_allowed,
        "volatility_state_digest": volatility_state.get("volatility_state_digest"),
        "realized_volatility": (
            dict(volatility_state.get("realized_volatility") or {})
            if volatility_allowed
            else {}
        ),
        "jump_continuous": (
            dict(volatility_state.get("jump_continuous") or {})
            if volatility_allowed
            else {}
        ),
        "vol_of_vol": (
            dict(volatility_state.get("vol_of_vol") or {})
            if volatility_allowed
            else {}
        ),
        "gvz": (
            dict(volatility_state.get("gvz") or {})
            if volatility_allowed
            else {}
        ),
        "iv_minus_rv": (
            dict(volatility_state.get("iv_minus_rv") or {})
            if volatility_allowed
            else {}
        ),
    }

    event_allowed = event_risk.get("evidence_state") == "known"
    scheduled_event_risk = {
        "state": str(event_risk.get("evidence_state") or "unknown"),
        "decision_input_allowed": event_allowed,
        "timing_state": (
            event_risk.get("timing_state") if event_allowed else "unknown"
        ),
        "events_in_window": (
            list(event_risk.get("events_in_window") or []) if event_allowed else []
        ),
        "next_scheduled_event": (
            event_risk.get("next_scheduled_event") if event_allowed else None
        ),
    }

    move = _move_observation(
        m1=completed["M1"],
        event_risk=event_risk,
        liquidity=liquidity,
        volatility=volatility,
    )

    unknowns: list[str] = []
    if session_state["state"] == "unknown":
        unknowns.append("session")
    if location["state"] == "unknown":
        unknowns.append("current_mid")
    if market_structure["state"] != "known":
        unknowns.append("complete_multi_timeframe_structure")
    if not volatility_allowed:
        unknowns.append("qualified_volatility")
    if not event_allowed:
        unknowns.append("scheduled_event_context")
    if move["cause_unknown"]:
        unknowns.append("recent_move_cause")

    packet: dict[str, Any] = {
        "gold_state_engine_version": GOLD_STATE_ENGINE_VERSION,
        "contract_version": PROVIDER_GOLD_STATE_VERSION,
        "as_of_utc": cutoff.isoformat(),
        "symbol": symbol,
        "mode": "pit",
        "research_only": True,
        "descriptive_context_only": True,
        "predictive_edge_claimed": False,
        "live_money_execution_allowed": False,
        "future_values_used": False,
        "session": session_state,
        "market_structure": market_structure,
        "liquidity": liquidity,
        "location": location,
        "volatility": volatility,
        "scheduled_event_risk": scheduled_event_risk,
        "move_observation": move,
        "price_structure_semantic_digest": price_structure_packet.get(
            "structure_semantic_digest"
        ),
        "unknowns": unknowns,
        "unknown_stays_unknown": True,
    }
    packet["gold_state_digest"] = _digest(packet)
    return packet


def verify_gold_state_engine(packet: Mapping[str, Any]) -> bool:
    if packet.get("gold_state_engine_version") != GOLD_STATE_ENGINE_VERSION:
        return False
    if packet.get("contract_version") != PROVIDER_GOLD_STATE_VERSION:
        return False
    if packet.get("symbol") != "XAUUSD":
        return False
    if packet.get("mode") != "pit":
        return False
    if packet.get("research_only") is not True:
        return False
    if packet.get("descriptive_context_only") is not True:
        return False
    if packet.get("predictive_edge_claimed") is not False:
        return False
    if packet.get("live_money_execution_allowed") is not False:
        return False
    if packet.get("future_values_used") is not False:
        return False
    body = dict(packet)
    supplied = str(body.pop("gold_state_digest", ""))
    return bool(supplied) and supplied == _digest(body)


__all__ = [
    "GOLD_STATE_ENGINE_VERSION",
    "PROVIDER_GOLD_STATE_VERSION",
    "build_gold_state_engine",
    "verify_gold_state_engine",
]
