"""Build 12: Liquidity / Reclaim Expert for AIDY Gold.

This expert measures OHLC-based sweep/reclaim proxies around known price
references. It never describes those proxies as genuine order flow. Any real
GC-flow research evidence is stored separately and is not used in the proxy
decision path.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from itertools import pairwise
from typing import Any

from aidy.feature_engine import Candle, normalize_candles
from aidy.gold_expert_gate_contract import build_expert_gate_packet, verify_expert_gate_packet
from aidy.gold_expert_trust import (
    build_trust_envelope,
    build_trust_scopes,
    select_conditional_trust,
)
from aidy.gold_price_expert_math import verify_price_expert_math_packet

LIQUIDITY_RECLAIM_EXPERT_VERSION = "aidy_gold_liquidity_reclaim_expert_v1"
LIQUIDITY_RECLAIM_GATE_ID = "liquidity_reclaim_expert"
LIQUIDITY_RECLAIM_TARGET_HORIZON_MINUTES = 15
LIQUIDITY_PROXY_LOOKBACK_MINUTES = 30

LIQUIDITY_TRUST_REDUCED_CONTEXTS = (
    {
        "name": "session_liquidity",
        "mini_dimensions": [
            "session",
            "session_phase",
            "proxy_state",
            "level_category",
        ],
        "global_dimensions": ["volatility_state"],
        "minimum_sample_n": 12,
    },
    {
        "name": "reclaim_quality",
        "mini_dimensions": [
            "proxy_state",
            "reclaim_speed_bucket",
            "penetration_bucket",
            "retest_state",
        ],
        "global_dimensions": [],
        "minimum_sample_n": 10,
    },
    {
        "name": "liquidity_context",
        "mini_dimensions": ["level_category", "competing_level_band"],
        "global_dimensions": ["volatility_state"],
        "minimum_sample_n": 8,
    },
)

_FORBIDDEN_ORDER_FLOW_PHRASES = (
    "order flow confirms",
    "hidden orders",
    "real liquidity taken",
    "institutional orders",
    "smart money orders",
)


def _utc(value: datetime | str) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError("liquidity timestamps must be timezone-aware")
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
    return format(value.quantize(Decimal("0.000001")), "f")


def _bps(delta: Decimal, denominator: Decimal) -> Decimal | None:
    if denominator == 0:
        return None
    return delta / denominator * Decimal(10000)


def _completed_m1(
    rows: Sequence[Mapping[str, Any]],
    *,
    as_of: datetime,
    mode: str,
) -> list[Candle]:
    grouped = normalize_candles(rows, as_of=as_of, symbol="XAUUSD", mode=mode)
    return [
        candle
        for candle in grouped["M1"]
        if candle.open_time_utc + timedelta(minutes=1) <= as_of
    ]


def _contiguity(candles: Sequence[Candle], required: int = 30) -> dict[str, Any]:
    sample = list(candles[-required:])
    if len(sample) < required:
        return {
            "state": "insufficient",
            "required_bars": required,
            "observed_bars": len(sample),
            "contiguous": False,
        }
    gaps: list[str] = []
    for left, right in pairwise(sample):
        if right.open_time_utc - left.open_time_utc != timedelta(minutes=1):
            gaps.append(left.open_time_utc.isoformat())
    return {
        "state": "known" if not gaps else "gapped",
        "required_bars": required,
        "observed_bars": len(sample),
        "contiguous": not gaps,
        "gap_after_open_times_utc": gaps,
    }


def _level_side(reference: str) -> str | None:
    lowered = reference.lower()
    if lowered.endswith("_high") or "swing_high" in lowered:
        return "high"
    if lowered.endswith("_low") or "swing_low" in lowered:
        return "low"
    return None


def _safe_id(reference: str) -> str:
    token = re.sub(r"[^a-z0-9_.-]+", "_", reference.lower()).strip("_")
    return token[:70] or "unknown_level"


def _level_category(reference: str) -> str:
    if reference.startswith("prior_day_"):
        return "prior_day"
    if reference.startswith("asia_overnight_"):
        return "asia"
    if reference.startswith("confirmed_"):
        return "confirmed_swing"
    if "_opening_" in reference:
        return "opening_range"
    if reference.startswith(("london_", "new_york_", "asia_")):
        return "active_session"
    if reference.startswith("recent_"):
        return "recent_extrema"
    return "other"


def _competing_distance(
    *,
    level: Decimal,
    reference: str,
    references: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    candidates: list[tuple[Decimal, str, Decimal]] = []
    for item in references:
        name = str(item.get("reference") or "")
        if name == reference:
            continue
        other = _decimal(item.get("level"))
        if other is None:
            continue
        distance = abs(other - level)
        candidates.append((distance, name, other))
    if not candidates:
        return {
            "nearest_competing_reference": None,
            "nearest_competing_level": None,
            "distance_usd": None,
            "distance_bps": None,
        }
    distance, name, other = min(candidates, key=lambda row: (row[0], row[1]))
    return {
        "nearest_competing_reference": name,
        "nearest_competing_level": _fmt(other),
        "distance_usd": _fmt(distance),
        "distance_bps": _fmt(abs(_bps(distance, level) or Decimal(0))),
    }


def _penetration_bucket(value: Decimal | None) -> str:
    if value is None:
        return "unknown"
    if value <= Decimal(1):
        return "tiny"
    if value <= Decimal(3):
        return "small"
    if value <= Decimal(8):
        return "medium"
    return "deep"


def _speed_bucket(bars: int | None) -> str:
    if bars is None:
        return "none"
    if bars == 0:
        return "same_bar"
    if bars <= 2:
        return "fast"
    if bars <= 5:
        return "moderate"
    return "slow"


def _rejection_geometry(
    candle: Candle,
    *,
    side: str,
    level: Decimal,
) -> dict[str, Any]:
    total = candle.high - candle.low
    if total <= 0:
        return {
            "wick_fraction": None,
            "close_location": None,
            "rejection_quality": "unknown",
        }
    if side == "high":
        wick = candle.high - max(candle.open, candle.close)
        close_location = (candle.close - candle.low) / total
        favourable_close = close_location <= Decimal("0.45")
    else:
        wick = min(candle.open, candle.close) - candle.low
        close_location = (candle.close - candle.low) / total
        favourable_close = close_location >= Decimal("0.55")
    wick_fraction = wick / total
    crossed = candle.high > level if side == "high" else candle.low < level
    if crossed and wick_fraction >= Decimal("0.35") and favourable_close:
        quality = "strong"
    elif crossed and wick_fraction >= Decimal("0.20"):
        quality = "moderate"
    else:
        quality = "weak"
    return {
        "wick_fraction": _fmt(wick_fraction),
        "close_location": _fmt(close_location),
        "rejection_quality": quality,
    }


def _analyse_level(
    *,
    reference: Mapping[str, Any],
    candles: Sequence[Candle],
    references: Sequence[Mapping[str, Any]],
) -> dict[str, Any] | None:
    name = str(reference.get("reference") or "")
    side = _level_side(name)
    level = _decimal(reference.get("level"))
    if side is None or level is None:
        return None

    sample = list(candles[-LIQUIDITY_PROXY_LOOKBACK_MINUTES:])
    first_penetration: int | None = None
    max_depth = Decimal(0)

    for index, candle in enumerate(sample):
        if side == "high":
            depth = max(Decimal(0), candle.high - level)
        else:
            depth = max(Decimal(0), level - candle.low)
        if depth > 0 and first_penetration is None:
            first_penetration = index
        max_depth = max(max_depth, depth)

    if first_penetration is None:
        competing = _competing_distance(level=level, reference=name, references=references)
        return {
            "reference": name,
            "level": _fmt(level),
            "level_side": side,
            "level_category": _level_category(name),
            "proxy_state": "no_sweep",
            "penetrated": False,
            "penetration_depth_usd": "0.000000",
            "penetration_depth_bps": "0.000000",
            "reclaimed": False,
            "reclaim_speed_bars": None,
            "reclaim_speed_bucket": "none",
            "confirmation_closes": 0,
            "retest": False,
            "retest_hold": False,
            "latest_failed_back_through": False,
            "rejection_geometry": {
                "wick_fraction": None,
                "close_location": None,
                "rejection_quality": "unknown",
            },
            "competing_level": competing,
        }

    reclaim_index: int | None = None
    for index in range(first_penetration, len(sample)):
        candle = sample[index]
        reclaimed = candle.close < level if side == "high" else candle.close > level
        if reclaimed:
            reclaim_index = index
            break

    reclaim_speed = None if reclaim_index is None else reclaim_index - first_penetration
    confirmation_closes = 0
    retest = False
    retest_hold = False
    latest_failed_back_through = False
    geometry = {
        "wick_fraction": None,
        "close_location": None,
        "rejection_quality": "unknown",
    }

    if reclaim_index is not None:
        reclaim_candle = sample[reclaim_index]
        geometry = _rejection_geometry(reclaim_candle, side=side, level=level)
        after = sample[reclaim_index:]
        for candle in after:
            inside = candle.close < level if side == "high" else candle.close > level
            if inside:
                confirmation_closes += 1
        for candle in sample[reclaim_index + 1:]:
            touched = candle.high >= level if side == "high" else candle.low <= level
            held = candle.close < level if side == "high" else candle.close > level
            if touched:
                retest = True
                if held:
                    retest_hold = True
        latest = sample[-1]
        latest_failed_back_through = (
            latest.close > level if side == "high" else latest.close < level
        )

    penetration_bps = abs(_bps(max_depth, level) or Decimal(0))
    if reclaim_index is None:
        state = "penetrated_no_reclaim"
    elif latest_failed_back_through:
        state = "reclaim_failed"
    elif retest_hold and confirmation_closes >= 2:
        state = "reclaim_retest_hold"
    elif confirmation_closes >= 2:
        state = "reclaim_confirmed"
    else:
        state = "reclaim_unconfirmed"

    competing = _competing_distance(level=level, reference=name, references=references)
    return {
        "reference": name,
        "level": _fmt(level),
        "level_side": side,
        "level_category": _level_category(name),
        "proxy_state": state,
        "penetrated": True,
        "penetration_depth_usd": _fmt(max_depth),
        "penetration_depth_bps": _fmt(penetration_bps),
        "penetration_bucket": _penetration_bucket(penetration_bps),
        "reclaimed": reclaim_index is not None,
        "reclaim_speed_bars": reclaim_speed,
        "reclaim_speed_bucket": _speed_bucket(reclaim_speed),
        "confirmation_closes": confirmation_closes,
        "retest": retest,
        "retest_hold": retest_hold,
        "latest_failed_back_through": latest_failed_back_through,
        "rejection_geometry": geometry,
        "competing_level": competing,
    }


def _event_vote(event: Mapping[str, Any]) -> tuple[str, Decimal | None]:
    state = str(event.get("proxy_state") or "unknown")
    side = str(event.get("level_side") or "unknown")
    if state not in {"reclaim_confirmed", "reclaim_retest_hold"}:
        return "neutral", None

    base = Decimal("0.58")
    if state == "reclaim_retest_hold":
        base += Decimal("0.10")
    speed = str(event.get("reclaim_speed_bucket") or "")
    if speed in {"same_bar", "fast"}:
        base += Decimal("0.08")
    elif speed == "slow":
        base -= Decimal("0.05")
    geometry = event.get("rejection_geometry")
    geometry = geometry if isinstance(geometry, Mapping) else {}
    quality = str(geometry.get("rejection_quality") or "unknown")
    if quality == "strong":
        base += Decimal("0.10")
    elif quality == "weak":
        base -= Decimal("0.05")
    confirmation = int(event.get("confirmation_closes") or 0)
    if confirmation >= 3:
        base += Decimal("0.05")

    vote = "bearish" if side == "high" else "bullish"
    return vote, max(Decimal(0), min(Decimal(1), base))


def _event_calculator(event: Mapping[str, Any]) -> dict[str, Any]:
    reference = str(event["reference"])
    calculator_id = f"liquidity_{_safe_id(reference)}"
    vote, strength = _event_vote(event)
    item = {
        "calculator_id": calculator_id,
        "version": f"{calculator_id}_v1",
        "role": "directional",
        "dependency_family": "liquidity",
        "state": "known",
        "vote": vote,
        "evidence_refs": [f"liquidity_event_{_safe_id(reference)}"],
        "observation": {
            **dict(event),
            "proxy_not_order_flow": True,
            "hidden_order_flow_claimed": False,
            "correlation_group": f"liquidity_level_{_safe_id(reference)}",
        },
        "explanation": (
            f"OHLC sweep/reclaim proxy at {reference}: state={event['proxy_state']}, "
            f"penetration={event.get('penetration_depth_bps')} bps, "
            f"reclaim_speed={event.get('reclaim_speed_bucket')}, "
            f"confirmations={event.get('confirmation_closes')}. "
            "This is a price-action proxy, not genuine order flow."
        ),
    }
    if vote in {"bullish", "bearish"} and strength is not None:
        item["strength"] = _fmt(strength)
    return item


def _context_calculator(
    *,
    session: str,
    session_phase: str,
    volatility_state: str,
) -> dict[str, Any]:
    return {
        "calculator_id": "liquidity_session_volatility_context",
        "version": "liquidity_session_volatility_context_v1",
        "role": "context_only",
        "dependency_family": "session_participation",
        "state": "known",
        "vote": "context_only",
        "evidence_refs": ["liquidity_context_evidence"],
        "observation": {
            "session": session,
            "session_phase": session_phase,
            "volatility_state": volatility_state,
            "proxy_not_order_flow": True,
            "correlation_group": "liquidity_context",
        },
        "explanation": (
            "Sweep/reclaim proxy reliability is conditioned by session phase and "
            "volatility regime. No order-flow claim is made."
        ),
    }


def _conclusion(calculators: Sequence[Mapping[str, Any]]) -> tuple[str, str | None, dict[str, Any]]:
    directional = [
        item
        for item in calculators
        if item.get("role") == "directional"
        and item.get("vote") in {"bullish", "bearish"}
    ]
    bullish = [item for item in directional if item["vote"] == "bullish"]
    bearish = [item for item in directional if item["vote"] == "bearish"]
    if bullish and bearish:
        return "abstain", None, {
            "bullish_event_count": len(bullish),
            "bearish_event_count": len(bearish),
            "conflicting_reclaim_proxies": True,
        }
    chosen = bullish or bearish
    if not chosen:
        return "neutral", None, {
            "bullish_event_count": 0,
            "bearish_event_count": 0,
            "conflicting_reclaim_proxies": False,
        }
    strongest = max(
        (_decimal(item.get("strength")) or Decimal(0) for item in chosen),
        default=Decimal(0),
    )
    vote = "bullish" if bullish else "bearish"
    return vote, _fmt(strongest), {
        "bullish_event_count": len(bullish),
        "bearish_event_count": len(bearish),
        "conflicting_reclaim_proxies": False,
        "strongest_proxy_strength": _fmt(strongest),
    }


def _subject_keys(packet: Mapping[str, Any]) -> list[str]:
    keys = [f"gate:{packet['gate_id']}"]
    keys.extend(
        f"subcalculator:{item['calculator_id']}"
        for item in packet["subcalculators"]
    )
    return keys


def _gc_flow_storage(rows: Sequence[Mapping[str, Any]] | None) -> dict[str, Any]:
    payload = [dict(item) for item in (rows or ())]
    return {
        "state": "present" if payload else "unavailable",
        "provenance_class": "retrospective_genuine_gc_flow",
        "row_count": len(payload),
        "rows": payload,
        "used_in_ohlc_proxy_calculation": False,
        "used_in_expert_conclusion": False,
        "separate_from_ohlc_proxy": True,
    }


def build_liquidity_reclaim_expert(
    *,
    global_environment: Mapping[str, Any],
    price_math_packet: Mapping[str, Any],
    price_location_result: Mapping[str, Any],
    m1_candle_rows: Sequence[Mapping[str, Any]],
    retrospective_gc_flow_rows: Sequence[Mapping[str, Any]] | None = None,
    trust_score_rows_by_subject: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Build the frozen Liquidity / Reclaim proxy expert."""

    if not verify_price_expert_math_packet(price_math_packet):
        raise ValueError("price_math_packet must satisfy Build-4 verification")
    location_packet = price_location_result.get("expert_packet")
    if not isinstance(location_packet, Mapping) or not verify_expert_gate_packet(location_packet):
        raise ValueError("price_location_result must contain a valid Build-11 expert packet")

    as_of = _utc(str(price_math_packet["as_of_utc"]))
    exact = global_environment.get("exact_facts")
    exact = exact if isinstance(exact, Mapping) else {}
    if _utc(str(exact.get("as_of_utc"))) != as_of:
        raise ValueError("liquidity expert requires price math and environment at same as-of")
    if _utc(str(location_packet["as_of_utc"])) != as_of:
        raise ValueError("liquidity expert requires location result at same as-of")

    mode = str(price_math_packet["mode"])
    candles = _completed_m1(m1_candle_rows, as_of=as_of, mode=mode)
    continuity = _contiguity(candles, required=LIQUIDITY_PROXY_LOOKBACK_MINUTES)
    usable = continuity["contiguous"]
    references = list(price_location_result.get("references") or [])

    events: list[dict[str, Any]] = []
    if usable:
        for reference in references:
            if not isinstance(reference, Mapping):
                continue
            event = _analyse_level(
                reference=reference,
                candles=candles,
                references=references,
            )
            if event is not None:
                events.append(event)

    dimensions = global_environment["learning_dimensions"]
    evidence_inputs: list[dict[str, Any]] = []
    for event in events:
        reference = str(event["reference"])
        evidence_inputs.append(
            {
                "evidence_id": f"liquidity_event_{_safe_id(reference)}",
                "source": "completed_m1_ohlc_sweep_reclaim_proxy",
                "path": f"liquidity_proxy.events.{reference}",
                "observed_at_utc": as_of,
                "state": "known",
                "value": dict(event),
                "provenance": {
                    "price_math_packet_digest": price_math_packet["packet_digest"],
                    "location_packet_digest": location_packet["packet_digest"],
                    "completed_bars_only": True,
                    "proxy_not_order_flow": True,
                    "genuine_order_flow_used": False,
                    "future_values_used": False,
                },
            }
        )
    evidence_inputs.append(
        {
            "evidence_id": "liquidity_context_evidence",
            "source": "frozen_cycle_environment",
            "path": "learning_dimensions.session_volatility",
            "observed_at_utc": as_of,
            "state": "known",
            "value": {
                "session": dimensions["session"],
                "session_phase": dimensions["session_phase"],
                "volatility_state": dimensions["volatility_state"],
                "continuity": continuity,
            },
            "provenance": {
                "environment_key": global_environment["environment_key"],
                "proxy_not_order_flow": True,
                "future_values_used": False,
            },
        }
    )

    calculators: list[dict[str, Any]] = []
    if usable:
        calculators.extend(_event_calculator(event) for event in events)
    else:
        calculators.append(
            {
                "calculator_id": "liquidity_proxy_data_quality",
                "version": "liquidity_proxy_data_quality_v1",
                "role": "directional",
                "dependency_family": "liquidity",
                "state": "insufficient",
                "vote": "unknown",
                "evidence_refs": ["liquidity_context_evidence"],
                "observation": {
                    "continuity": continuity,
                    "proxy_not_order_flow": True,
                    "correlation_group": "liquidity_data_quality",
                },
                "explanation": "Liquidity proxy requires 30 contiguous completed M1 candles.",
            }
        )
    calculators.append(
        _context_calculator(
            session=str(dimensions["session"]),
            session_phase=str(dimensions["session_phase"]),
            volatility_state=str(dimensions["volatility_state"]),
        )
    )

    conclusion, conviction, audit = _conclusion(calculators)
    if not usable:
        conclusion, conviction = "unknown", None

    active_events = [
        event
        for event in events
        if event.get("proxy_state") not in {"no_sweep", "penetrated_no_reclaim"}
    ]
    representative = active_events[0] if active_events else (events[0] if events else {})
    competing = representative.get("competing_level")
    competing = competing if isinstance(competing, Mapping) else {}
    mini_environment = {
        "session": dimensions["session"],
        "session_phase": dimensions["session_phase"],
        "volatility_state": dimensions["volatility_state"],
        "proxy_state": representative.get("proxy_state", "unknown"),
        "level_category": representative.get("level_category", "unknown"),
        "reclaim_speed_bucket": representative.get("reclaim_speed_bucket", "none"),
        "penetration_bucket": representative.get("penetration_bucket", "unknown"),
        "retest_state": (
            "retest_hold"
            if representative.get("retest_hold") is True
            else "retest_failed"
            if representative.get("retest") is True
            else "none"
        ),
        "competing_level_band": (
            "near"
            if (_decimal(competing.get("distance_bps")) or Decimal(999)) <= Decimal(5)
            else "far"
        ),
    }

    explanation_parts = [
        {
            "text": (
                f"Liquidity/Reclaim Expert conclusion={conclusion}; "
                f"measured {len(events)} high/low level proxies using completed M1 OHLC."
            ),
            "source_refs": [f"calc:{item['calculator_id']}" for item in calculators],
        },
        {
            "text": (
                "All sweep/reclaim observations are OHLC price-action proxies. "
                "They are not genuine order flow and make no hidden-order claim."
            ),
            "source_refs": ["calc:liquidity_session_volatility_context"],
        },
    ]

    packet = build_expert_gate_packet(
        gate_id=LIQUIDITY_RECLAIM_GATE_ID,
        gate_version=LIQUIDITY_RECLAIM_EXPERT_VERSION,
        gate_mode="directional",
        dependency_family="liquidity",
        target_horizon_minutes=LIQUIDITY_RECLAIM_TARGET_HORIZON_MINUTES,
        as_of_utc=as_of,
        global_environment=global_environment,
        mini_environment=mini_environment,
        evidence_inputs=evidence_inputs,
        subcalculators=calculators,
        conclusion=conclusion,
        internal_conviction=conviction,
        explanation_parts=explanation_parts,
        contradictions=(),
    )
    if not verify_expert_gate_packet(packet):
        raise ValueError("constructed Liquidity/Reclaim packet failed Build-2 verification")

    rendered_text = " ".join(
        [part["text"] for part in packet["explanation_parts"]]
        + [item["explanation"] for item in packet["subcalculators"]]
    ).lower()
    if any(phrase in rendered_text for phrase in _FORBIDDEN_ORDER_FLOW_PHRASES):
        raise ValueError("forbidden genuine-order-flow language detected")

    scopes = build_trust_scopes(
        packet=packet,
        reduced_contexts=LIQUIDITY_TRUST_REDUCED_CONTEXTS,
    )
    rows_by_subject = trust_score_rows_by_subject or {}
    profiles = {
        key: select_conditional_trust(
            score_rows=rows_by_subject.get(key, ()),
            scopes=scopes,
        )
        for key in _subject_keys(packet)
    }
    trust_envelope = build_trust_envelope(packet=packet, profiles_by_subject=profiles)

    return {
        "expert_version": LIQUIDITY_RECLAIM_EXPERT_VERSION,
        "expert_packet": packet,
        "events": events,
        "continuity": continuity,
        "trust_scopes": scopes,
        "trust_envelope": trust_envelope,
        "consensus_audit": audit,
        "proxy_policy": {
            "ohlc_sweep_reclaim_is_proxy": True,
            "genuine_order_flow_claimed": False,
            "hidden_order_flow_claimed": False,
            "proxy_language_required": True,
        },
        "retrospective_gc_flow": _gc_flow_storage(retrospective_gc_flow_rows),
        "research_only": True,
        "future_values_used": False,
        "live_money_execution_allowed": False,
    }


__all__ = [
    "LIQUIDITY_PROXY_LOOKBACK_MINUTES",
    "LIQUIDITY_RECLAIM_EXPERT_VERSION",
    "LIQUIDITY_RECLAIM_GATE_ID",
    "LIQUIDITY_RECLAIM_TARGET_HORIZON_MINUTES",
    "LIQUIDITY_TRUST_REDUCED_CONTEXTS",
    "build_liquidity_reclaim_expert",
]
