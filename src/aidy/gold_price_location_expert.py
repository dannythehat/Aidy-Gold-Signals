"""Build 11: Price Location Expert for AIDY Gold.

This expert answers where Gold is relative to known price references. It is
context-only by contract: location cannot invent a directional forecast unless
a separately tested reaction rule exists in a later build.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation, localcontext
from typing import Any

from aidy.gold_expert_gate_contract import build_expert_gate_packet, verify_expert_gate_packet
from aidy.gold_expert_trust import (
    build_trust_envelope,
    build_trust_scopes,
    select_conditional_trust,
)
from aidy.gold_price_expert_math import verify_price_expert_math_packet

PRICE_LOCATION_EXPERT_VERSION = "aidy_gold_price_location_expert_v1"
PRICE_LOCATION_GATE_ID = "price_location_expert"
PRICE_LOCATION_TARGET_HORIZON_MINUTES = 15

LOCATION_TRUST_REDUCED_CONTEXTS = (
    {
        "name": "session_location",
        "mini_dimensions": [
            "session",
            "session_phase",
            "nearest_category",
            "nearest_side",
            "nearest_atr_band",
        ],
        "global_dimensions": [],
        "minimum_sample_n": 12,
    },
    {
        "name": "structural_location",
        "mini_dimensions": [
            "priority_category",
            "priority_side",
            "confluence_state",
            "bracket_conflict_state",
        ],
        "global_dimensions": ["volatility_state"],
        "minimum_sample_n": 10,
    },
    {
        "name": "range_location",
        "mini_dimensions": [
            "prior_day_zone",
            "asia_zone",
            "active_session_zone",
        ],
        "global_dimensions": [],
        "minimum_sample_n": 8,
    },
)

REFERENCE_PRIORITY = {
    "prior_day": (1, "prior-day structural reference"),
    "confirmed_swing": (1, "confirmed swing structure"),
    "asia": (2, "Asia range reference"),
    "active_session": (2, "active-session extreme"),
    "opening_range": (3, "session opening-range reference"),
    "recent_extrema": (4, "recent completed-bar extreme"),
    "round_number": (5, "descriptive round-number reference"),
}


def _utc(value: datetime | str) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError("location timestamps must be timezone-aware")
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


def _nearest_increment(value: Decimal, increment: Decimal) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = 34
        units = (value / increment).quantize(Decimal(1), rounding=ROUND_HALF_EVEN)
        return units * increment


def _side(mid: Decimal, level: Decimal) -> str:
    if mid > level:
        return "above"
    if mid < level:
        return "below"
    return "at"


def _category(name: str) -> str:
    if name.startswith("prior_day_"):
        return "prior_day"
    if name.startswith("asia_overnight_"):
        return "asia"
    if name.startswith("confirmed_"):
        return "confirmed_swing"
    if name.startswith("recent_"):
        return "recent_extrema"
    if name.startswith("round_"):
        return "round_number"
    if "_opening_" in name:
        return "opening_range"
    if name.startswith(("london_", "new_york_", "asia_")):
        return "active_session"
    return "recent_extrema"


def _priority(category: str) -> tuple[int, str]:
    return REFERENCE_PRIORITY.get(category, (9, "other measured reference"))


def _atr_bps(price_math_packet: Mapping[str, Any]) -> tuple[Decimal | None, str | None]:
    for timeframe in ("M15", "M5", "H1"):
        payload = price_math_packet["timeframes"][timeframe]
        if payload.get("state") != "known":
            continue
        atr = _decimal(payload["primitives"]["atr_rv_normalisation"].get("atr_14_bps"))
        if atr not in {None, Decimal(0)}:
            return atr, timeframe
    return None, None


def _atr_band(value: Decimal | None) -> str:
    if value is None:
        return "unknown"
    if value <= Decimal("0.10"):
        return "within_0_10_atr"
    if value <= Decimal("0.25"):
        return "within_0_25_atr"
    if value <= Decimal("0.50"):
        return "within_0_50_atr"
    if value <= Decimal("1.00"):
        return "within_1_00_atr"
    return "beyond_1_00_atr"


def _reference_row(
    *,
    name: str,
    level: Decimal,
    mid: Decimal,
    atr_bps: Decimal | None,
    source_path: str,
    source_kind: str,
) -> dict[str, Any]:
    delta = mid - level
    distance_bps = _bps(delta, level)
    abs_bps = abs(distance_bps) if distance_bps is not None else None
    atr_units = (
        abs_bps / atr_bps
        if abs_bps is not None and atr_bps not in {None, Decimal(0)}
        else None
    )
    category = _category(name)
    tier, reason = _priority(category)
    return {
        "reference": name,
        "category": category,
        "priority_tier": tier,
        "priority_reason": reason,
        "source_kind": source_kind,
        "source_path": source_path,
        "level": _fmt(level),
        "mid_minus_level": _fmt(delta),
        "absolute_distance_usd": _fmt(abs(delta)),
        "distance_bps": _fmt(distance_bps),
        "absolute_distance_bps": _fmt(abs_bps),
        "distance_atr_units": _fmt(atr_units),
        "atr_distance_band": _atr_band(atr_units),
        "relative_side": _side(mid, level),
    }


def _environment_references(
    location: Mapping[str, Any],
    *,
    mid: Decimal,
    atr_bps: Decimal | None,
) -> list[dict[str, Any]]:
    references = location.get("exact_reference_distances")
    references = references if isinstance(references, Mapping) else {}
    result: list[dict[str, Any]] = []
    for name, payload in references.items():
        if not isinstance(payload, Mapping):
            continue
        level = _decimal(payload.get("level"))
        if level is None:
            continue
        result.append(
            _reference_row(
                name=str(name),
                level=level,
                mid=mid,
                atr_bps=atr_bps,
                source_path=f"global_environment.exact_facts.location.exact_reference_distances.{name}",
                source_kind="frozen_environment_reference",
            )
        )
    return result


def _swing_references(
    price_math_packet: Mapping[str, Any],
    *,
    mid: Decimal,
    atr_bps: Decimal | None,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for timeframe in ("M15", "H1"):
        payload = price_math_packet["timeframes"][timeframe]
        if payload.get("state") != "known":
            continue
        swings = payload["primitives"]["confirmed_swing_sequence"]
        highs = list(swings.get("confirmed_highs") or [])
        lows = list(swings.get("confirmed_lows") or [])
        if highs:
            level = _decimal(highs[-1].get("price"))
            if level is not None:
                result.append(
                    _reference_row(
                        name=f"confirmed_{timeframe.lower()}_swing_high",
                        level=level,
                        mid=mid,
                        atr_bps=atr_bps,
                        source_path=(
                            f"price_math.timeframes.{timeframe}."
                            "primitives.confirmed_swing_sequence.confirmed_highs[-1]"
                        ),
                        source_kind="confirmed_completed_bar_swing",
                    )
                )
        if lows:
            level = _decimal(lows[-1].get("price"))
            if level is not None:
                result.append(
                    _reference_row(
                        name=f"confirmed_{timeframe.lower()}_swing_low",
                        level=level,
                        mid=mid,
                        atr_bps=atr_bps,
                        source_path=(
                            f"price_math.timeframes.{timeframe}."
                            "primitives.confirmed_swing_sequence.confirmed_lows[-1]"
                        ),
                        source_kind="confirmed_completed_bar_swing",
                    )
                )
    return result


def _recent_extrema(
    price_math_packet: Mapping[str, Any],
    *,
    mid: Decimal,
    atr_bps: Decimal | None,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for timeframe in ("M5", "M15"):
        payload = price_math_packet["timeframes"][timeframe]
        if payload.get("state") != "known":
            continue
        windows = payload["primitives"]["range_position"]["windows"]
        for bars in (20, 50):
            item = windows[f"{bars}_bar"]
            if item.get("state") != "known":
                continue
            for side in ("high", "low"):
                level = _decimal(item.get(side))
                if level is None:
                    continue
                result.append(
                    _reference_row(
                        name=f"recent_{timeframe.lower()}_{bars}_bar_{side}",
                        level=level,
                        mid=mid,
                        atr_bps=atr_bps,
                        source_path=(
                            f"price_math.timeframes.{timeframe}."
                            f"primitives.range_position.windows.{bars}_bar.{side}"
                        ),
                        source_kind="completed_bar_recent_extreme",
                    )
                )
    return result


def _round_references(
    *,
    mid: Decimal,
    atr_bps: Decimal | None,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for label, increment in (
        ("round_nearest_10_usd", Decimal(10)),
        ("round_nearest_50_usd", Decimal(50)),
    ):
        level = _nearest_increment(mid, increment)
        result.append(
            _reference_row(
                name=label,
                level=level,
                mid=mid,
                atr_bps=atr_bps,
                source_path=f"derived_from_frozen_mid.nearest_{int(increment)}_usd",
                source_kind="deterministic_round_number",
            )
        )
    return result


def _dedupe(references: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    result: list[dict[str, Any]] = []
    for item in references:
        key = (str(item["reference"]), str(item["level"]))
        if key in seen:
            continue
        seen.add(key)
        result.append(dict(item))
    return result


def _rankings(references: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    known = [
        item
        for item in references
        if _decimal(item.get("absolute_distance_usd")) is not None
    ]
    geometric = sorted(
        known,
        key=lambda item: (
            _decimal(item["absolute_distance_usd"]) or Decimal("Infinity"),
            int(item["priority_tier"]),
            str(item["reference"]),
        ),
    )
    priority = sorted(
        known,
        key=lambda item: (
            int(item["priority_tier"]),
            _decimal(item["absolute_distance_usd"]) or Decimal("Infinity"),
            str(item["reference"]),
        ),
    )
    return {
        "geometric_nearest": dict(geometric[0]) if geometric else None,
        "structural_priority_reference": dict(priority[0]) if priority else None,
        "geometric_order": [str(item["reference"]) for item in geometric],
        "priority_order": [str(item["reference"]) for item in priority],
        "priority_policy": [
            {
                "category": category,
                "priority_tier": tier,
                "reason": reason,
            }
            for category, (tier, reason) in sorted(
                REFERENCE_PRIORITY.items(), key=lambda item: (item[1][0], item[0])
            )
        ],
    }


def _confluence(
    references: Sequence[Mapping[str, Any]],
    *,
    mid: Decimal,
    atr_bps: Decimal | None,
) -> dict[str, Any]:
    if atr_bps in {None, Decimal(0)}:
        return {
            "state": "unknown_no_atr",
            "threshold_atr_units": "0.250000",
            "threshold_usd": None,
            "clusters": [],
        }

    atr_usd = mid * atr_bps / Decimal(10000)
    threshold = atr_usd * Decimal("0.25")
    ordered = sorted(
        references,
        key=lambda item: (
            _decimal(item.get("level")) or Decimal("Infinity"),
            str(item.get("reference")),
        ),
    )
    clusters: list[list[Mapping[str, Any]]] = []
    current: list[Mapping[str, Any]] = []
    last_level: Decimal | None = None
    for item in ordered:
        level = _decimal(item.get("level"))
        if level is None:
            continue
        if last_level is None or level - last_level <= threshold:
            current.append(item)
        else:
            if len(current) >= 2:
                clusters.append(current)
            current = [item]
        last_level = level
    if len(current) >= 2:
        clusters.append(current)

    output = []
    for index, cluster in enumerate(clusters, start=1):
        levels = [_decimal(item["level"]) for item in cluster]
        levels = [level for level in levels if level is not None]
        categories = sorted({str(item["category"]) for item in cluster})
        output.append(
            {
                "cluster_id": f"location_cluster_{index}",
                "reference_count": len(cluster),
                "references": [str(item["reference"]) for item in cluster],
                "categories": categories,
                "multi_category": len(categories) > 1,
                "low_level": _fmt(min(levels)),
                "high_level": _fmt(max(levels)),
                "span_usd": _fmt(max(levels) - min(levels)),
                "mid_side_signature": sorted({str(item["relative_side"]) for item in cluster}),
            }
        )

    return {
        "state": "confluence_present" if output else "none",
        "threshold_atr_units": "0.250000",
        "threshold_usd": _fmt(threshold),
        "clusters": output,
    }


def _bracket_conflict(
    references: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    nearby = [
        item
        for item in references
        if (
            (_decimal(item.get("distance_atr_units")) or Decimal("Infinity"))
            <= Decimal("0.50")
        )
    ]
    above = sorted(
        (item for item in nearby if item.get("relative_side") == "below"),
        key=lambda item: _decimal(item.get("absolute_distance_usd")) or Decimal("Infinity"),
    )
    below = sorted(
        (item for item in nearby if item.get("relative_side") == "above"),
        key=lambda item: _decimal(item.get("absolute_distance_usd")) or Decimal("Infinity"),
    )
    # relative_side describes the mid relative to the level:
    # mid below a level => level is above price; mid above a level => level is below price.
    conflict = bool(above and below)
    return {
        "state": "bracketed_by_nearby_levels" if conflict else "none",
        "threshold_atr_units": "0.500000",
        "nearest_level_above_price": dict(above[0]) if above else None,
        "nearest_level_below_price": dict(below[0]) if below else None,
        "nearby_reference_count": len(nearby),
    }


def _context_calculator(
    *,
    calculator_id: str,
    dependency_family: str,
    evidence_ref: str,
    known: bool,
    observation: Mapping[str, Any],
    explanation: str,
) -> dict[str, Any]:
    return {
        "calculator_id": calculator_id,
        "version": f"{calculator_id}_v1",
        "role": "context_only",
        "dependency_family": dependency_family,
        "state": "known" if known else "insufficient",
        "vote": "context_only" if known else "unknown",
        "evidence_refs": [evidence_ref],
        "observation": dict(observation),
        "explanation": explanation,
    }


def _subject_keys(packet: Mapping[str, Any]) -> list[str]:
    keys = [f"gate:{packet['gate_id']}"]
    keys.extend(
        f"subcalculator:{item['calculator_id']}"
        for item in packet["subcalculators"]
    )
    return keys


def build_price_location_expert(
    *,
    global_environment: Mapping[str, Any],
    price_math_packet: Mapping[str, Any],
    trust_score_rows_by_subject: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Build the frozen Price Location context expert."""

    if not verify_price_expert_math_packet(price_math_packet):
        raise ValueError("price_math_packet must satisfy Build-4 verification")

    as_of = _utc(str(price_math_packet["as_of_utc"]))
    exact = global_environment.get("exact_facts")
    exact = exact if isinstance(exact, Mapping) else {}
    if _utc(str(exact.get("as_of_utc"))) != as_of:
        raise ValueError("location expert requires price math and environment at same as-of")

    location = exact.get("location")
    location = location if isinstance(location, Mapping) else {}
    mid = _decimal(location.get("mid"))
    atr_bps, atr_timeframe = _atr_bps(price_math_packet)
    usable = mid is not None

    references: list[dict[str, Any]] = []
    if usable and mid is not None:
        references.extend(_environment_references(location, mid=mid, atr_bps=atr_bps))
        references.extend(_swing_references(price_math_packet, mid=mid, atr_bps=atr_bps))
        references.extend(_recent_extrema(price_math_packet, mid=mid, atr_bps=atr_bps))
        references.extend(_round_references(mid=mid, atr_bps=atr_bps))
    references = _dedupe(references)

    rankings = _rankings(references)
    confluence = _confluence(references, mid=mid or Decimal(0), atr_bps=atr_bps) if usable else {
        "state": "unknown",
        "clusters": [],
    }
    bracket = _bracket_conflict(references) if usable else {"state": "unknown"}

    ranges = location.get("exact_range_positions")
    ranges = ranges if isinstance(ranges, Mapping) else {}
    dimensions = global_environment["learning_dimensions"]

    observed_at = as_of
    evidence_inputs = [
        {
            "evidence_id": "location_reference_evidence",
            "source": "frozen_environment_plus_completed_price_math",
            "path": "price_location.references",
            "observed_at_utc": observed_at,
            "state": "known" if usable else "unknown",
            "value": references if usable else None,
            "provenance": {
                "environment_key": global_environment["environment_key"],
                "price_math_packet_digest": price_math_packet["packet_digest"],
                "completed_bars_only": True,
                "future_values_used": False,
            },
        },
        {
            "evidence_id": "location_range_evidence",
            "source": "frozen_environment",
            "path": "exact_facts.location.exact_range_positions",
            "observed_at_utc": observed_at,
            "state": "known" if usable else "unknown",
            "value": dict(ranges) if usable else None,
            "provenance": {
                "environment_key": global_environment["environment_key"],
                "future_values_used": False,
            },
        },
        {
            "evidence_id": "location_confluence_evidence",
            "source": "deterministic_location_math_v1",
            "path": "price_location.confluence_and_conflict",
            "observed_at_utc": observed_at,
            "state": "known" if usable else "unknown",
            "value": {
                "rankings": rankings,
                "confluence": confluence,
                "bracket_conflict": bracket,
            } if usable else None,
            "provenance": {
                "environment_key": global_environment["environment_key"],
                "price_math_packet_digest": price_math_packet["packet_digest"],
                "future_values_used": False,
            },
        },
    ]

    calculators = [
        _context_calculator(
            calculator_id="location_nearest_reference",
            dependency_family="location",
            evidence_ref="location_reference_evidence",
            known=usable and rankings["geometric_nearest"] is not None,
            observation={
                "geometric_nearest": rankings["geometric_nearest"],
                "atr_source_timeframe": atr_timeframe,
                "atr_14_bps": _fmt(atr_bps),
            } if usable else {"state": "unknown"},
            explanation=(
                "Geometric nearest reference is calculated by exact absolute USD distance, "
                "with bps and ATR-normalised distance retained."
                if usable
                else "Price location is unavailable because frozen mid price is unknown."
            ),
        ),
        _context_calculator(
            calculator_id="location_structural_priority",
            dependency_family="location",
            evidence_ref="location_reference_evidence",
            known=usable and rankings["structural_priority_reference"] is not None,
            observation={
                "structural_priority_reference": rankings["structural_priority_reference"],
                "priority_policy": rankings["priority_policy"],
                "priority_order": rankings["priority_order"],
            } if usable else {"state": "unknown"},
            explanation=(
                "Structural priority is deterministic and separate from geometric nearness; "
                "every tier and reason is exposed."
                if usable
                else "Structural priority is unavailable without price references."
            ),
        ),
        _context_calculator(
            calculator_id="location_range_context",
            dependency_family="location",
            evidence_ref="location_range_evidence",
            known=usable,
            observation={
                "prior_day_zone": dimensions["prior_day_zone"],
                "asia_zone": dimensions["asia_overnight_zone"],
                "active_session_zone": dimensions["active_session_zone"],
                "exact_range_positions": dict(ranges),
            } if usable else {"state": "unknown"},
            explanation="Range-position context is descriptive only and cannot vote direction.",
        ),
        _context_calculator(
            calculator_id="location_confluence",
            dependency_family="location",
            evidence_ref="location_confluence_evidence",
            known=usable,
            observation=confluence if usable else {"state": "unknown"},
            explanation="Confluence clusters group measured levels within 0.25 ATR.",
        ),
        _context_calculator(
            calculator_id="location_bracket_conflict",
            dependency_family="location",
            evidence_ref="location_confluence_evidence",
            known=usable,
            observation=bracket if usable else {"state": "unknown"},
            explanation=(
                "Bracket conflict records nearby levels on both sides of price within 0.50 ATR."
            ),
        ),
    ]

    nearest = rankings["geometric_nearest"] if usable else None
    priority_ref = rankings["structural_priority_reference"] if usable else None
    mini_environment = {
        "session": dimensions["session"],
        "session_phase": dimensions["session_phase"],
        "volatility_state": dimensions["volatility_state"],
        "nearest_category": (
            str(nearest["category"]) if isinstance(nearest, Mapping) else "unknown"
        ),
        "nearest_side": (
            str(nearest["relative_side"]) if isinstance(nearest, Mapping) else "unknown"
        ),
        "nearest_atr_band": (
            str(nearest["atr_distance_band"]) if isinstance(nearest, Mapping) else "unknown"
        ),
        "priority_category": (
            str(priority_ref["category"]) if isinstance(priority_ref, Mapping) else "unknown"
        ),
        "priority_side": (
            str(priority_ref["relative_side"]) if isinstance(priority_ref, Mapping) else "unknown"
        ),
        "confluence_state": str(confluence.get("state") or "unknown"),
        "bracket_conflict_state": str(bracket.get("state") or "unknown"),
        "prior_day_zone": dimensions["prior_day_zone"],
        "asia_zone": dimensions["asia_overnight_zone"],
        "active_session_zone": dimensions["active_session_zone"],
    }

    explanation_parts = [
        {
            "text": (
                "Price Location Expert is context-only: it describes where Gold is "
                "relative to measured references and never invents directional edge."
            ),
            "source_refs": ["calc:location_nearest_reference", "calc:location_range_context"],
        },
        {
            "text": (
                f"Geometric nearest={nearest['reference'] if isinstance(nearest, Mapping) else 'unknown'}; "
                f"structural priority={priority_ref['reference'] if isinstance(priority_ref, Mapping) else 'unknown'}; "
                f"confluence={confluence.get('state')}; bracket conflict={bracket.get('state')}."
            ),
            "source_refs": [
                "calc:location_nearest_reference",
                "calc:location_structural_priority",
                "calc:location_confluence",
                "calc:location_bracket_conflict",
            ],
        },
    ]

    packet = build_expert_gate_packet(
        gate_id=PRICE_LOCATION_GATE_ID,
        gate_version=PRICE_LOCATION_EXPERT_VERSION,
        gate_mode="context_only",
        dependency_family="location",
        target_horizon_minutes=PRICE_LOCATION_TARGET_HORIZON_MINUTES,
        as_of_utc=as_of,
        global_environment=global_environment,
        mini_environment=mini_environment,
        evidence_inputs=evidence_inputs,
        subcalculators=calculators,
        conclusion="context_only",
        internal_conviction=None,
        explanation_parts=explanation_parts,
        contradictions=(),
    )
    if not verify_expert_gate_packet(packet):
        raise ValueError("constructed Price Location packet failed Build-2 verification")

    scopes = build_trust_scopes(
        packet=packet,
        reduced_contexts=LOCATION_TRUST_REDUCED_CONTEXTS,
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
        "expert_version": PRICE_LOCATION_EXPERT_VERSION,
        "expert_packet": packet,
        "mid": _fmt(mid),
        "atr_14_bps": _fmt(atr_bps),
        "atr_source_timeframe": atr_timeframe,
        "references": references,
        "rankings": rankings,
        "confluence": confluence,
        "bracket_conflict": bracket,
        "trust_scopes": scopes,
        "trust_envelope": trust_envelope,
        "reaction_rule_policy": {
            "directional_vote_allowed": False,
            "tested_location_reaction_rules": [],
            "location_alone_creates_edge": False,
            "separate_reaction_rule_required": True,
        },
        "research_only": True,
        "future_values_used": False,
        "live_money_execution_allowed": False,
    }


__all__ = [
    "LOCATION_TRUST_REDUCED_CONTEXTS",
    "PRICE_LOCATION_EXPERT_VERSION",
    "PRICE_LOCATION_GATE_ID",
    "PRICE_LOCATION_TARGET_HORIZON_MINUTES",
    "REFERENCE_PRIORITY",
    "build_price_location_expert",
]
