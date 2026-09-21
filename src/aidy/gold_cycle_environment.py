"""Canonical cycle-start Gold environment for AIDY.

This module separates *facts known at decision time* from directional marker opinions.
Exact facts are retained for audit, while repeatable categorical dimensions are used for
contextual learning so AIDY can accumulate comparable environments across many cycles.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Any

from aidy.market_sessions import (
    london_utc_offset_hours,
    new_york_utc_offset_hours,
)

GOLD_CYCLE_ENVIRONMENT_VERSION = "aidy_gold_cycle_environment_v2"


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value: object) -> str:
    return sha256(_canonical_json(value).encode()).hexdigest()


def _utc(value: datetime | str) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError("cycle environment timestamps must be timezone-aware")
    return parsed.astimezone(UTC)


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _bucket_distance_bps(value: Any) -> str:
    parsed = _decimal(value)
    if parsed is None:
        return "unknown"
    distance = abs(parsed)
    if distance <= Decimal(1):
        return "at_level_0_1bp"
    if distance <= Decimal(3):
        return "near_1_3bp"
    if distance <= Decimal(8):
        return "close_3_8bp"
    if distance <= Decimal(20):
        return "moderate_8_20bp"
    return "far_gt20bp"


def _bucket_ratio(value: Any) -> str:
    parsed = _decimal(value)
    if parsed is None:
        return "unknown"
    if parsed < 0:
        return "below_range"
    if parsed < Decimal("0.25"):
        return "lower_quartile"
    if parsed < Decimal("0.50"):
        return "lower_middle"
    if parsed < Decimal("0.75"):
        return "upper_middle"
    if parsed <= Decimal("1"):
        return "upper_quartile"
    return "above_range"


def _bucket_minutes(value: int | None) -> str:
    if value is None:
        return "unknown"
    if value < 0:
        return "not_started"
    if value <= 15:
        return "opening_0_15m"
    if value <= 30:
        return "opening_15_30m"
    if value <= 90:
        return "early_30_90m"
    if value <= 240:
        return "middle_90_240m"
    return "late_gt240m"


def _bucket_event_minutes(value: int | None) -> str:
    if value is None:
        return "unknown"
    if value < 0:
        return "event_already_started"
    if value <= 15:
        return "within_15m"
    if value <= 30:
        return "within_30m"
    if value <= 60:
        return "within_60m"
    if value <= 120:
        return "within_120m"
    return "gt120m"


def _session_timing(*, as_of: datetime, session_code: str) -> dict[str, Any]:
    now = _utc(as_of)
    london = now + timedelta(hours=london_utc_offset_hours(now))
    new_york = now + timedelta(hours=new_york_utc_offset_hours(now))
    tokyo = now + timedelta(hours=9)

    def since(local: datetime, hour: int) -> int:
        return (local.hour * 60 + local.minute) - (hour * 60)

    since_london = since(london, 8)
    since_new_york = since(new_york, 8)
    since_asia = since(tokyo, 9)

    active_minutes: int | None
    if session_code == "asia":
        active_minutes = since_asia
    elif session_code == "london":
        active_minutes = since_london
    elif session_code in {"new_york", "london_new_york_overlap"}:
        active_minutes = since_new_york
    else:
        active_minutes = None

    return {
        "utc_weekday": now.weekday(),
        "utc_time_slot": now.strftime("%H:%M"),
        "session_code": session_code,
        "active_session_minutes_since_open": active_minutes,
        "active_session_phase": _bucket_minutes(active_minutes),
        "minutes_since_london_open": since_london,
        "minutes_since_new_york_open": since_new_york,
        "minutes_since_asia_open": since_asia,
    }


def _timeframe_environment(gold_state: Mapping[str, Any]) -> dict[str, Any]:
    structure = gold_state.get("market_structure")
    structure = structure if isinstance(structure, Mapping) else {}
    timeframes = structure.get("timeframes")
    timeframes = timeframes if isinstance(timeframes, Mapping) else {}
    result: dict[str, Any] = {}
    for timeframe in ("M5", "M15", "H1", "H4", "D1"):
        frame = timeframes.get(timeframe)
        frame = frame if isinstance(frame, Mapping) else {}
        raw = str(frame.get("net_close_direction") or "unknown").lower()
        direction = {
            "up": "bullish",
            "down": "bearish",
            "flat": "neutral",
        }.get(raw, raw if raw in {"bullish", "bearish", "neutral"} else "unknown")
        result[timeframe] = {
            "direction": direction,
            "persistence_band": _bucket_ratio(frame.get("directional_persistence_ratio")),
            "range_position_band": _bucket_ratio(frame.get("latest_close_range_position")),
            "state": str(frame.get("state") or "unknown"),
        }
    return result


def _movement_environment(gold_state: Mapping[str, Any]) -> dict[str, Any]:
    move = gold_state.get("move_observation")
    move = move if isinstance(move, Mapping) else {}
    windows = move.get("windows")
    windows = windows if isinstance(windows, Mapping) else {}
    result: dict[str, Any] = {
        "five_minute_distribution_state": str(
            move.get("five_minute_distribution_state") or "unknown"
        ),
        "five_minute_range_state": str(move.get("five_minute_range_state") or "unknown"),
        "five_minute_abs_return_percentile": move.get(
            "five_minute_abs_return_percentile"
        ),
        "five_minute_range_percentile": move.get("five_minute_range_percentile"),
    }
    for horizon in ("5m", "15m", "60m"):
        item = windows.get(horizon)
        item = item if isinstance(item, Mapping) else {}
        raw = str(item.get("direction") or "unknown")
        result[horizon] = {
            "direction": {
                "up": "bullish",
                "down": "bearish",
                "flat": "neutral",
            }.get(raw, raw if raw in {"bullish", "bearish", "neutral"} else "unknown"),
            "return_bps": item.get("return_bps"),
            "range_bps": item.get("range_bps"),
        }
    return result


def _location_environment(
    *,
    gold_state: Mapping[str, Any],
    session_code: str,
) -> dict[str, Any]:
    location = gold_state.get("location")
    location = location if isinstance(location, Mapping) else {}
    references = location.get("reference_distances")
    references = references if isinstance(references, Mapping) else {}
    ranges = location.get("range_positions")
    ranges = ranges if isinstance(ranges, Mapping) else {}
    round_refs = location.get("round_number_references")
    round_refs = round_refs if isinstance(round_refs, Mapping) else {}

    ordered: list[tuple[Decimal, str, Mapping[str, Any]]] = []
    for name, payload in references.items():
        if not isinstance(payload, Mapping):
            continue
        distance = _decimal(payload.get("distance_bps"))
        if distance is None:
            continue
        ordered.append((abs(distance), str(name), payload))
    ordered.sort(key=lambda item: (item[0], item[1]))

    nearest = None
    if ordered:
        _, name, payload = ordered[0]
        nearest = {
            "reference": name,
            "relative_side": str(payload.get("relative_side") or "unknown"),
            "distance_bps": payload.get("distance_bps"),
            "distance_band": _bucket_distance_bps(payload.get("distance_bps")),
        }

    if session_code == "london_new_york_overlap":
        session_range = ranges.get("new_york", ranges.get("london"))
    else:
        session_range = ranges.get(session_code)

    exact_references = {
        str(name): {
            "relative_side": str(payload.get("relative_side") or "unknown"),
            "distance_bps": payload.get("distance_bps"),
            "level": payload.get("level"),
        }
        for name, payload in references.items()
        if isinstance(payload, Mapping)
    }

    return {
        "mid": location.get("mid"),
        "nearest_reference": nearest,
        "prior_day_zone": _bucket_ratio(ranges.get("prior_day")),
        "asia_overnight_zone": _bucket_ratio(ranges.get("asia_overnight")),
        "active_session_zone": _bucket_ratio(session_range),
        "london_opening_15m_zone": _bucket_ratio(ranges.get("london_opening_15m")),
        "new_york_opening_15m_zone": _bucket_ratio(
            ranges.get("new_york_opening_15m")
        ),
        "nearest_10_usd_band": _bucket_distance_bps(
            (round_refs.get("nearest_10_usd") or {}).get("distance_bps")
            if isinstance(round_refs.get("nearest_10_usd"), Mapping)
            else None
        ),
        "nearest_50_usd_band": _bucket_distance_bps(
            (round_refs.get("nearest_50_usd") or {}).get("distance_bps")
            if isinstance(round_refs.get("nearest_50_usd"), Mapping)
            else None
        ),
        "exact_reference_distances": exact_references,
        "exact_range_positions": dict(ranges),
    }


def _liquidity_environment(gold_state: Mapping[str, Any]) -> dict[str, Any]:
    liquidity = gold_state.get("liquidity")
    liquidity = liquidity if isinstance(liquidity, Mapping) else {}
    proxies = liquidity.get("sweep_reclaim_proxies")
    proxies = proxies if isinstance(proxies, list) else []
    sides = sorted(
        {
            str(item.get("side"))
            for item in proxies
            if isinstance(item, Mapping) and item.get("side") in {"high", "low"}
        }
    )
    if sides == ["high"]:
        signature = "high_side_reclaim"
    elif sides == ["low"]:
        signature = "low_side_reclaim"
    elif sides == ["high", "low"]:
        signature = "both_sides_reclaim"
    else:
        signature = "none"

    return {
        "proxy_count": len(proxies),
        "proxy_side_signature": signature,
        "proxy_kinds": sorted(
            {
                str(item.get("kind"))
                for item in proxies
                if isinstance(item, Mapping) and item.get("kind")
            }
        ),
        "prior_day_breakout_state": str(
            (liquidity.get("prior_day_breakout") or {}).get("state") or "unknown"
        )
        if isinstance(liquidity.get("prior_day_breakout"), Mapping)
        else "unknown",
    }


def _volatility_environment(gold_state: Mapping[str, Any]) -> dict[str, Any]:
    volatility = gold_state.get("volatility")
    volatility = volatility if isinstance(volatility, Mapping) else {}

    def state(name: str) -> str:
        payload = volatility.get(name)
        return (
            str(payload.get("state") or "unknown")
            if isinstance(payload, Mapping)
            else "unknown"
        )

    return {
        "state": str(volatility.get("state") or "unknown"),
        "realized_volatility_state": state("realized_volatility"),
        "jump_state": state("jump_continuous"),
        "vol_of_vol_state": state("vol_of_vol"),
        "gvz_state": state("gvz"),
        "iv_minus_rv_state": state("iv_minus_rv"),
    }


def _event_environment(
    *,
    gold_state: Mapping[str, Any],
    as_of: datetime,
) -> dict[str, Any]:
    event = gold_state.get("scheduled_event_risk")
    event = event if isinstance(event, Mapping) else {}
    next_event = event.get("next_scheduled_event")
    next_event = next_event if isinstance(next_event, Mapping) else {}
    scheduled_at = next_event.get("scheduled_at")
    minutes_to_next: int | None = None
    if scheduled_at:
        try:
            delta = _utc(str(scheduled_at)) - _utc(as_of)
            minutes_to_next = int(delta.total_seconds() // 60)
        except (TypeError, ValueError):
            minutes_to_next = None
    events = event.get("events_in_window")
    events = events if isinstance(events, list) else []
    return {
        "state": str(event.get("state") or "unknown"),
        "timing_state": str(event.get("timing_state") or "unknown"),
        "events_in_window_count": len(events),
        "next_event_type": str(next_event.get("event_type") or "unknown"),
        "minutes_to_next_event": minutes_to_next,
        "next_event_proximity": _bucket_event_minutes(minutes_to_next),
    }


def _cross_market_environment(
    semantic_context: Mapping[str, Any] | None,
) -> dict[str, Any]:
    semantic_context = semantic_context if isinstance(semantic_context, Mapping) else {}
    cross = semantic_context.get("cross_market")
    cross = cross if isinstance(cross, Mapping) else {}
    series = cross.get("series")
    series = series if isinstance(series, Mapping) else {}
    states: dict[str, str] = {}
    for name, payload in series.items():
        if isinstance(payload, Mapping):
            states[str(name)] = str(payload.get("state") or "unknown")
    known = sorted(name for name, state in states.items() if state == "known")
    return {
        "known_series_count": len(known),
        "known_series": known,
        "series_states": states,
    }


def build_cycle_environment(
    *,
    as_of_utc: datetime | str,
    target_window_start_utc: datetime | str,
    session_code: str,
    observed_state: str,
    gold_state: Mapping[str, Any],
    semantic_context: Mapping[str, Any] | None,
    regime: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Build exact cycle-start facts and repeatable learning dimensions."""

    as_of = _utc(as_of_utc)
    target = _utc(target_window_start_utc)
    if target <= as_of:
        raise ValueError("cycle environment must be frozen before the target window")

    regime = regime if isinstance(regime, Mapping) else {}
    session = _session_timing(as_of=as_of, session_code=session_code)
    structure = _timeframe_environment(gold_state)
    movement = _movement_environment(gold_state)
    location = _location_environment(gold_state=gold_state, session_code=session_code)
    liquidity = _liquidity_environment(gold_state)
    volatility = _volatility_environment(gold_state)
    event = _event_environment(gold_state=gold_state, as_of=as_of)
    cross_market = _cross_market_environment(semantic_context)
    compound_regime = str(regime.get("compound_regime_key") or "unknown")

    exact_facts = {
        "as_of_utc": as_of.isoformat(),
        "target_window_start_utc": target.isoformat(),
        "decision_lead_seconds": int((target - as_of).total_seconds()),
        "session": session,
        "observed_15m_state": observed_state,
        "structure": structure,
        "movement": movement,
        "location": location,
        "liquidity": liquidity,
        "volatility": volatility,
        "scheduled_event": event,
        "cross_market": cross_market,
        "compound_regime": compound_regime,
        "unknowns": list(gold_state.get("unknowns") or []),
    }

    learning_dimensions = {
        "session": session_code,
        "session_phase": session["active_session_phase"],
        "utc_weekday": session["utc_weekday"],
        "observed_15m_state": observed_state,
        "m5_direction": structure["M5"]["direction"],
        "m15_direction": structure["M15"]["direction"],
        "h1_direction": structure["H1"]["direction"],
        "h4_direction": structure["H4"]["direction"],
        "d1_direction": structure["D1"]["direction"],
        "five_minute_distribution_state": movement[
            "five_minute_distribution_state"
        ],
        "five_minute_range_state": movement["five_minute_range_state"],
        "m60_direction": movement["60m"]["direction"],
        "nearest_reference": (
            location["nearest_reference"]["reference"]
            if isinstance(location["nearest_reference"], Mapping)
            else "unknown"
        ),
        "nearest_reference_side": (
            location["nearest_reference"]["relative_side"]
            if isinstance(location["nearest_reference"], Mapping)
            else "unknown"
        ),
        "nearest_reference_distance_band": (
            location["nearest_reference"]["distance_band"]
            if isinstance(location["nearest_reference"], Mapping)
            else "unknown"
        ),
        "prior_day_zone": location["prior_day_zone"],
        "asia_overnight_zone": location["asia_overnight_zone"],
        "active_session_zone": location["active_session_zone"],
        "liquidity_signature": liquidity["proxy_side_signature"],
        "prior_day_breakout_state": liquidity["prior_day_breakout_state"],
        "volatility_state": volatility["state"],
        "jump_state": volatility["jump_state"],
        "event_timing_state": event["timing_state"],
        "event_proximity": event["next_event_proximity"],
        "cross_market_known_count": cross_market["known_series_count"],
        "compound_regime": compound_regime,
    }

    scope_payloads = [
        ("global", {"global": "all"}),
        ("session", {"session": session_code}),
        (
            "session_phase",
            {
                "session": session_code,
                "session_phase": session["active_session_phase"],
            },
        ),
        (
            "session_state",
            {"session": session_code, "observed_15m_state": observed_state},
        ),
        (
            "higher_timeframe",
            {
                "H1": structure["H1"]["direction"],
                "H4": structure["H4"]["direction"],
                "D1": structure["D1"]["direction"],
            },
        ),
        (
            "liquidity_location",
            {
                "liquidity": liquidity["proxy_side_signature"],
                "reference": learning_dimensions["nearest_reference"],
                "reference_side": learning_dimensions["nearest_reference_side"],
                "distance_band": learning_dimensions[
                    "nearest_reference_distance_band"
                ],
                "prior_day_zone": location["prior_day_zone"],
                "active_session_zone": location["active_session_zone"],
            },
        ),
        (
            "session_liquidity",
            {
                "session": session_code,
                "session_phase": session["active_session_phase"],
                "liquidity": liquidity["proxy_side_signature"],
                "prior_day_breakout_state": liquidity[
                    "prior_day_breakout_state"
                ],
            },
        ),
        (
            "location_structure",
            {
                "nearest_reference": learning_dimensions["nearest_reference"],
                "distance_band": learning_dimensions[
                    "nearest_reference_distance_band"
                ],
                "H1": structure["H1"]["direction"],
                "H4": structure["H4"]["direction"],
            },
        ),
        (
            "session_move_regime",
            {
                "session": session_code,
                "distribution": movement["five_minute_distribution_state"],
                "range": movement["five_minute_range_state"],
            },
        ),
        (
            "volatility_move_regime",
            {
                "volatility": volatility["state"],
                "jump": volatility["jump_state"],
                "distribution": movement["five_minute_distribution_state"],
                "range": movement["five_minute_range_state"],
            },
        ),
        (
            "session_state_event",
            {
                "session": session_code,
                "observed_15m_state": observed_state,
                "event_timing": event["timing_state"],
            },
        ),
        (
            "event_regime",
            {
                "event_timing": event["timing_state"],
                "event_proximity": event["next_event_proximity"],
                "compound_regime": compound_regime,
            },
        ),
        ("full_environment", learning_dimensions),
    ]
    scopes = [
        {
            "scope_type": scope_type,
            "scope_key": f"{scope_type}_" + _digest(payload)[:28],
            "payload": payload,
        }
        for scope_type, payload in scope_payloads
    ]

    result = {
        "environment_version": GOLD_CYCLE_ENVIRONMENT_VERSION,
        "environment_key": "env_" + _digest(learning_dimensions)[:32],
        "exact_facts": exact_facts,
        "learning_dimensions": learning_dimensions,
        "scopes": scopes,
        "research_only": True,
        "future_values_used": False,
        "live_money_execution_allowed": False,
    }
    result["environment_digest"] = _digest(result)
    return result


def verify_cycle_environment(value: Mapping[str, Any]) -> bool:
    body = dict(value)
    supplied = str(body.pop("environment_digest", ""))
    return (
        bool(supplied)
        and supplied == _digest(body)
        and body.get("environment_version") == GOLD_CYCLE_ENVIRONMENT_VERSION
        and body.get("research_only") is True
        and body.get("future_values_used") is False
        and body.get("live_money_execution_allowed") is False
        and isinstance(body.get("learning_dimensions"), Mapping)
        and isinstance(body.get("scopes"), list)
    )


__all__ = [
    "GOLD_CYCLE_ENVIRONMENT_VERSION",
    "build_cycle_environment",
    "verify_cycle_environment",
]
