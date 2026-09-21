"""Build 8: H4 Price Structure Expert for AIDY Gold.

This is the fourth timeframe mini-brain in the expert-gate programme. It consumes
Build-4 factual price mathematics, emits an auditable Build-2 expert packet, and
attaches Build-3 conditional trust without granting live-money authority.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from aidy.gold_expert_gate_contract import build_expert_gate_packet, verify_expert_gate_packet
from aidy.gold_expert_trust import (
    build_trust_envelope,
    build_trust_scopes,
    score_directional_outcome,
    select_conditional_trust,
)
from aidy.gold_price_expert_math import verify_price_expert_math_packet

H4_PRICE_STRUCTURE_EXPERT_VERSION = "aidy_gold_h4_price_structure_expert_v1"
H4_GATE_ID = "h4_price_structure_expert"
H4_TARGET_HORIZON_MINUTES = 960

H4_TRUST_REDUCED_CONTEXTS = (
    {
        "name": "structure_regime",
        "mini_dimensions": ["structure_regime", "trend_regime", "breakout_state"],
        "global_dimensions": ["volatility_state"],
        "minimum_sample_n": 12,
    },
    {
        "name": "session_structure",
        "mini_dimensions": ["session", "session_phase", "structure_regime"],
        "global_dimensions": [],
        "minimum_sample_n": 10,
    },
    {
        "name": "movement_regime",
        "mini_dimensions": ["trend_regime", "breakout_state"],
        "global_dimensions": [
            "five_minute_distribution_state",
            "five_minute_range_state",
        ],
        "minimum_sample_n": 8,
    },
)

_DIRECTIONAL_IDS = (
    "h4_trend_quality",
    "h4_swing_structure",
    "h4_breakout_acceptance",
    "h4_acceleration",
    "h4_candle_pressure",
    "h4_lower_timeframe_conflict",
)

H4_DEPENDENCY_METADATA = {
    "h4_trend_quality": {
        "dependency_family": "structure",
        "correlation_group": "h4_path_structure",
    },
    "h4_swing_structure": {
        "dependency_family": "structure",
        "correlation_group": "h4_path_structure",
    },
    "h4_breakout_acceptance": {
        "dependency_family": "location",
        "correlation_group": "h4_breakout_location",
    },
    "h4_acceleration": {
        "dependency_family": "momentum",
        "correlation_group": "h4_momentum_transition",
    },
    "h4_candle_pressure": {
        "dependency_family": "momentum",
        "correlation_group": "h4_latest_bar_pressure",
    },
    "h4_range_location": {
        "dependency_family": "location",
        "correlation_group": "h4_breakout_location",
    },
    "h4_price_diagnostics": {
        "dependency_family": "data_quality",
        "correlation_group": "h4_diagnostics",
    },
    "h4_lower_timeframe_conflict": {
        "dependency_family": "cross_market",
        "correlation_group": "h4_lower_timeframe_conflict",
    },
}


def _utc(value: datetime | str) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError("H4 expert timestamps must be timezone-aware")
    return parsed.astimezone(UTC)


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _clip01(value: Decimal) -> Decimal:
    return max(Decimal(0), min(Decimal(1), value))


def _fmt(value: Decimal | None) -> str | None:
    if value is None:
        return None
    quantized = value.quantize(Decimal("0.000001"))
    return format(quantized, "f")


def _direction(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"up", "bullish", "higher", "positive"}:
        return "bullish"
    if text in {"down", "bearish", "lower", "negative"}:
        return "bearish"
    if text in {"flat", "neutral", "mixed"}:
        return "neutral"
    return "unknown"


def _quality_bucket(value: Decimal | None) -> str:
    if value is None:
        return "unknown"
    if value >= Decimal("0.75"):
        return "high"
    if value >= Decimal("0.50"):
        return "medium"
    if value >= Decimal("0.30"):
        return "low"
    return "poor"


def _range_bucket(value: Any) -> str:
    parsed = _decimal(value)
    if parsed is None:
        return "unknown"
    if parsed < Decimal("0.20"):
        return "low_extreme"
    if parsed < Decimal("0.40"):
        return "lower"
    if parsed <= Decimal("0.60"):
        return "middle"
    if parsed <= Decimal("0.80"):
        return "upper"
    return "high_extreme"


def _observed_at(h4_payload: Mapping[str, Any], as_of: datetime) -> datetime:
    latest = h4_payload.get("latest_completed_open_time_utc")
    if not latest:
        return as_of
    completed_at = _utc(str(latest)) + timedelta(hours=4)
    return min(completed_at, as_of)

def _evidence(
    *,
    evidence_id: str,
    path: str,
    observed_at: datetime,
    state: str,
    value: Any,
    price_math_packet: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "evidence_id": evidence_id,
        "source": "aidy_gold_price_expert_math_v1",
        "path": path,
        "observed_at_utc": observed_at,
        "state": state,
        "value": value,
        "provenance": {
            "price_math_packet_digest": price_math_packet["packet_digest"],
            "price_math_mode": price_math_packet["mode"],
            "completed_bars_only": True,
        },
    }


def _unknown_calculator(
    *,
    calculator_id: str,
    dependency_family: str,
    evidence_ref: str,
    reason: str,
) -> dict[str, Any]:
    return {
        "calculator_id": calculator_id,
        "version": f"{calculator_id}_v1",
        "role": "directional",
        "dependency_family": dependency_family,
        "state": "insufficient",
        "vote": "unknown",
        "evidence_refs": [evidence_ref],
        "observation": {
            "state": "insufficient",
            "correlation_group": H4_DEPENDENCY_METADATA.get(
                calculator_id, {}
            ).get("correlation_group", "unknown"),
        },
        "explanation": reason,
    }


def _trend_quality(primitives: Mapping[str, Any]) -> dict[str, Any]:
    regressions = primitives["log_ols_slope"]["windows"]
    returns = primitives["multi_lookback_returns"]["values"]
    persistence = primitives["close_step_persistence"]
    efficiency = primitives["path_efficiency"]
    normalised = primitives["atr_rv_normalisation"]["normalised_returns"]

    regression_8 = regressions["8_bar"]
    regression_13 = regressions["13_bar"]
    return_8 = returns["8_bar"]
    return_13 = returns["13_bar"]
    norm_8 = normalised["8_bar"]

    required = (
        regression_8.get("state") == "known",
        return_8.get("state") == "known",
        persistence.get("state") == "known",
        efficiency.get("state") == "known",
        norm_8.get("state") == "known",
    )
    if not all(required):
        return {
            "state": "insufficient",
            "vote": "unknown",
            "strength": None,
            "observation": {
                "eight_bar_return_state": return_8.get("state"),
                "eight_bar_regression_state": regression_8.get("state"),
                "thirteen_bar_regression_state": regression_13.get("state"),
                "persistence_state": persistence.get("state"),
                "efficiency_state": efficiency.get("state"),
            },
            "explanation": "H4 trend quality lacks enough completed-hour evidence.",
        }

    directions = [
        _direction(return_8.get("direction")),
        _direction(regression_8.get("direction")),
        _direction(persistence.get("net_direction")),
    ]
    if regression_13.get("state") == "known":
        directions.append(_direction(regression_13.get("direction")))
    if return_13.get("state") == "known":
        directions.append(_direction(return_13.get("direction")))

    bullish = directions.count("bullish")
    bearish = directions.count("bearish")
    total = bullish + bearish
    agreement = (
        Decimal(max(bullish, bearish)) / Decimal(total)
        if total
        else Decimal(0)
    )

    r2_8 = _decimal(regression_8.get("r_squared")) or Decimal(0)
    r2_13 = (
        _decimal(regression_13.get("r_squared"))
        if regression_13.get("state") == "known"
        else None
    )
    mean_r2 = (
        (r2_8 + r2_13) / Decimal(2)
        if r2_13 is not None
        else r2_8
    )
    path_efficiency = _decimal(efficiency.get("efficiency_ratio")) or Decimal(0)
    persistence_ratio = (
        _decimal(persistence.get("directional_persistence_ratio")) or Decimal(0)
    )
    atr_units = _decimal(norm_8.get("atr_units"))
    displacement_quality = (
        min(abs(atr_units), Decimal(5)) / Decimal(5)
        if atr_units is not None
        else Decimal(0)
    )

    quality = _clip01(
        mean_r2 * Decimal("0.40")
        + path_efficiency * Decimal("0.30")
        + persistence_ratio * Decimal("0.20")
        + displacement_quality * Decimal("0.10")
    )
    directional_quality = _clip01(quality * agreement)

    quality_gate = (
        mean_r2 >= Decimal("0.50")
        and path_efficiency >= Decimal("0.45")
        and persistence_ratio >= Decimal("0.58")
        and directional_quality >= Decimal("0.52")
    )

    if bullish >= 3 and bullish > bearish and quality_gate:
        vote = "bullish"
    elif bearish >= 3 and bearish > bullish and quality_gate:
        vote = "bearish"
    else:
        vote = "neutral"

    return {
        "state": "known",
        "vote": vote,
        "strength": _fmt(
            directional_quality if vote in {"bullish", "bearish"} else None
        ),
        "observation": {
            "eight_bar_horizon_hours": 32,
            "eight_bar_return_bps": return_8.get("return_bps"),
            "thirteen_bar_return_bps": return_13.get("return_bps"),
            "eight_bar_slope_log_bps_per_bar": regression_8.get(
                "slope_log_bps_per_bar"
            ),
            "eight_bar_r_squared": regression_8.get("r_squared"),
            "thirteen_bar_slope_log_bps_per_bar": regression_13.get(
                "slope_log_bps_per_bar"
            ),
            "thirteen_bar_r_squared": regression_13.get("r_squared"),
            "mean_r_squared": _fmt(mean_r2),
            "path_efficiency": efficiency.get("efficiency_ratio"),
            "persistence_ratio": persistence.get("directional_persistence_ratio"),
            "eight_bar_atr_units": norm_8.get("atr_units"),
            "agreement_ratio": _fmt(agreement),
            "quality_score": _fmt(quality),
            "quality_bucket": _quality_bucket(quality),
            "quality_gate_passed": quality_gate,
        },
        "explanation": (
            f"H4 slow trend quality is {vote}: 8-bar slope={regression_8.get('slope_log_bps_per_bar')} "
            f"log-bps/bar, mean R²={_fmt(mean_r2)}, persistence="
            f"{persistence.get('directional_persistence_ratio')}, efficiency="
            f"{efficiency.get('efficiency_ratio')}, quality={_quality_bucket(quality)}."
        ),
    }

def _swing_structure(primitives: Mapping[str, Any]) -> dict[str, Any]:
    swings = primitives["confirmed_swing_sequence"]
    structure_break = primitives["structure_break"]
    combined = str(swings.get("combined_structure") or "insufficient")
    break_state = str(structure_break.get("state") or "unknown")

    if combined == "insufficient":
        return {
            "state": "insufficient",
            "vote": "unknown",
            "strength": None,
            "observation": {
                "combined_structure": combined,
                "structure_break": break_state,
            },
            "explanation": "H4 swing structure is not yet sufficiently confirmed.",
        }

    if combined == "bullish_structure":
        vote = "bullish"
        base = Decimal("0.78")
    elif combined == "bearish_structure":
        vote = "bearish"
        base = Decimal("0.78")
    else:
        vote = "neutral"
        base = Decimal(0)

    if (
        (vote == "bullish" and break_state == "close_above_confirmed_swing_high")
        or (vote == "bearish" and break_state == "close_below_confirmed_swing_low")
    ):
        base = Decimal("0.96")
    elif (
        (vote == "bullish" and break_state == "close_below_confirmed_swing_low")
        or (vote == "bearish" and break_state == "close_above_confirmed_swing_high")
    ):
        base = Decimal("0.25")

    return {
        "state": "known",
        "vote": vote,
        "strength": _fmt(base if vote in {"bullish", "bearish"} else None),
        "observation": {
            "combined_structure": combined,
            "high_sequence": swings.get("high_sequence"),
            "low_sequence": swings.get("low_sequence"),
            "structure_break": break_state,
        },
        "explanation": f"H4 confirmed swings show {combined}; latest break state is {break_state}.",
    }


def _breakout_acceptance(primitives: Mapping[str, Any]) -> dict[str, Any]:
    breakout = primitives["breakout_lifecycle"]
    high = breakout["high_side"]
    low = breakout["low_side"]
    high_state = str(high.get("state") or "unknown")
    low_state = str(low.get("state") or "unknown")

    bullish_states = {
        "accepted_hold": Decimal("0.86"),
        "retest_hold": Decimal("0.96"),
        "single_close_hold": Decimal("0.45"),
    }
    bearish_states = bullish_states

    if high_state in bullish_states and low_state in bearish_states:
        vote = "neutral"
        strength = None
    elif high_state in bullish_states:
        vote = "bullish"
        strength = bullish_states[high_state]
    elif low_state in bearish_states:
        vote = "bearish"
        strength = bearish_states[low_state]
    elif high_state == "reclaimed_inside" and low_state != "reclaimed_inside":
        vote = "bearish"
        strength = Decimal("0.48")
    elif low_state == "reclaimed_inside" and high_state != "reclaimed_inside":
        vote = "bullish"
        strength = Decimal("0.48")
    elif high_state == "unknown" and low_state == "unknown":
        return {
            "state": "insufficient",
            "vote": "unknown",
            "strength": None,
            "observation": {"high_state": high_state, "low_state": low_state},
            "explanation": "H4 breakout acceptance has no confirmed swing level to evaluate.",
        }
    else:
        vote = "neutral"
        strength = None

    return {
        "state": "known",
        "vote": vote,
        "strength": _fmt(strength),
        "observation": {
            "high_state": high_state,
            "low_state": low_state,
            "high_level": high.get("level"),
            "low_level": low.get("level"),
            "high_close_beyond_count": high.get("close_beyond_count"),
            "low_close_beyond_count": low.get("close_beyond_count"),
        },
        "explanation": (
            f"H4 breakout lifecycle is high={high_state}, low={low_state}, "
            f"producing {vote}."
        ),
    }


def _acceleration(primitives: Mapping[str, Any]) -> dict[str, Any]:
    acceleration = primitives["acceleration_deceleration"]
    returns = primitives["multi_lookback_returns"]["values"]
    normalised = primitives["atr_rv_normalisation"]["normalised_returns"]

    if (
        acceleration.get("state") != "known"
        or returns["3_bar"].get("state") != "known"
        or normalised["3_bar"].get("state") != "known"
    ):
        return {
            "state": "insufficient",
            "vote": "unknown",
            "strength": None,
            "observation": {
                "acceleration_state": acceleration.get("state"),
                "three_bar_return_state": returns["3_bar"].get("state"),
                "three_bar_normalised_state": normalised["3_bar"].get("state"),
            },
            "explanation": "H4 acceleration lacks enough completed-hour evidence.",
        }

    recent_direction = _direction(returns["3_bar"].get("direction"))
    transition = str(acceleration.get("state_label") or "unknown")
    atr_units = _decimal(normalised["3_bar"].get("atr_units"))
    magnitude = (
        min(abs(atr_units), Decimal(3)) / Decimal(3)
        if atr_units is not None
        else Decimal(0)
    )

    if recent_direction in {"bullish", "bearish"} and transition in {
        "accelerating",
        "direction_reversal",
    }:
        vote = recent_direction
        strength = _clip01(Decimal("0.50") + magnitude * Decimal("0.35"))
    elif recent_direction in {"bullish", "bearish"} and transition == "steady":
        vote = recent_direction
        strength = Decimal("0.48")
    else:
        vote = "neutral"
        strength = None

    return {
        "state": "known",
        "vote": vote,
        "strength": _fmt(strength),
        "observation": {
            "three_bar_horizon_hours": 12,
            "three_bar_direction": returns["3_bar"].get("direction"),
            "three_bar_return_bps": returns["3_bar"].get("return_bps"),
            "three_bar_atr_units": normalised["3_bar"].get("atr_units"),
            "acceleration_state": transition,
            "previous_return_bps": acceleration.get("previous_return_bps"),
            "recent_return_bps": acceleration.get("recent_return_bps"),
        },
        "explanation": (
            f"H4 acceleration is {vote}: three-hour direction={recent_direction}, "
            f"transition={transition}, ATR units={normalised['3_bar'].get('atr_units')}."
        ),
    }

def _candle_pressure(primitives: Mapping[str, Any]) -> dict[str, Any]:
    geometry = primitives["candle_geometry"]
    if geometry.get("state") != "known":
        return {
            "state": "insufficient",
            "vote": "unknown",
            "strength": None,
            "observation": {"state": geometry.get("state")},
            "explanation": "Latest completed H4 candle geometry is unavailable.",
        }

    body_direction = _direction(geometry.get("body_direction"))
    close_location = _decimal(geometry.get("close_location"))
    body_fraction = _decimal(geometry.get("body_fraction_of_range"))
    upper_wick = _decimal(geometry.get("upper_wick_bps")) or Decimal(0)
    lower_wick = _decimal(geometry.get("lower_wick_bps")) or Decimal(0)

    vote = "neutral"
    strength: Decimal | None = None
    if (
        body_direction == "bullish"
        and close_location is not None
        and close_location >= Decimal("0.75")
        and body_fraction is not None
        and body_fraction >= Decimal("0.45")
    ):
        vote = "bullish"
        strength = min(Decimal("0.60"), Decimal("0.35") + body_fraction * Decimal("0.25"))
    elif (
        body_direction == "bearish"
        and close_location is not None
        and close_location <= Decimal("0.25")
        and body_fraction is not None
        and body_fraction >= Decimal("0.45")
    ):
        vote = "bearish"
        strength = min(Decimal("0.60"), Decimal("0.35") + body_fraction * Decimal("0.25"))
    elif (
        lower_wick > upper_wick * Decimal("1.8")
        and close_location is not None
        and close_location > Decimal("0.55")
    ):
        vote = "bullish"
        strength = Decimal("0.45")
    elif (
        upper_wick > lower_wick * Decimal("1.8")
        and close_location is not None
        and close_location < Decimal("0.45")
    ):
        vote = "bearish"
        strength = Decimal("0.45")

    return {
        "state": "known",
        "vote": vote,
        "strength": _fmt(strength),
        "observation": {
            "body_direction": body_direction,
            "close_location": geometry.get("close_location"),
            "body_fraction_of_range": geometry.get("body_fraction_of_range"),
            "upper_wick_bps": geometry.get("upper_wick_bps"),
            "lower_wick_bps": geometry.get("lower_wick_bps"),
        },
        "explanation": f"Latest completed H4 candle pressure is {vote}.",
    }


def _location_context(primitives: Mapping[str, Any]) -> dict[str, Any]:
    ranges = primitives["range_position"]["windows"]
    value = ranges["20_bar"]
    state = "known" if value.get("state") == "known" else "insufficient"
    return {
        "calculator_id": "h4_range_location",
        "version": "h4_range_location_v1",
        "role": "context_only",
        "dependency_family": "location",
        "state": state,
        "vote": "context_only" if state == "known" else "unknown",
        "evidence_refs": ["h4_range_location_evidence"],
        "observation": {
            "range_20_position": value.get("position"),
            "range_20_bucket": _range_bucket(value.get("position")),
            "range_50_position": ranges["50_bar"].get("position"),
            "correlation_group": "h4_breakout_location",
        },
        "explanation": "H4 range location is context only and does not vote directionally.",
    }


def _diagnostic_context(
    primitives: Mapping[str, Any], *, h4_known: bool
) -> dict[str, Any]:
    diagnostic = primitives["contradiction_flags"]
    state = "known" if h4_known else "insufficient"
    return {
        "calculator_id": "h4_price_diagnostics",
        "version": "h4_price_diagnostics_v1",
        "role": "context_only",
        "dependency_family": "data_quality",
        "state": state,
        "vote": "context_only" if state == "known" else "unknown",
        "evidence_refs": ["h4_diagnostics_evidence"],
        "observation": {
            "contradiction_count": diagnostic.get("contradiction_count"),
            "flags": list(diagnostic.get("flags") or []),
            "correlation_group": "h4_diagnostics",
        },
        "explanation": "Build-4 H4 contradiction diagnostics are retained explicitly.",
    }


def _directional_calculator(
    *,
    calculator_id: str,
    dependency_family: str,
    evidence_ref: str,
    result: Mapping[str, Any],
) -> dict[str, Any]:
    if result["state"] != "known":
        return _unknown_calculator(
            calculator_id=calculator_id,
            dependency_family=dependency_family,
            evidence_ref=evidence_ref,
            reason=str(result["explanation"]),
        )
    item = {
        "calculator_id": calculator_id,
        "version": f"{calculator_id}_v1",
        "role": "directional",
        "dependency_family": dependency_family,
        "state": "known",
        "vote": result["vote"],
        "evidence_refs": [evidence_ref],
        "observation": {
            **dict(result["observation"]),
            "correlation_group": H4_DEPENDENCY_METADATA.get(
                calculator_id, {}
            ).get("correlation_group", "unknown"),
        },
        "explanation": str(result["explanation"]),
    }
    if result["vote"] in {"bullish", "bearish"}:
        item["strength"] = result["strength"]
    return item


def _family_balanced_conclusion(
    calculators: Sequence[Mapping[str, Any]],
) -> tuple[str, str | None, dict[str, Any]]:
    directional = [
        item
        for item in calculators
        if item.get("role") == "directional" and item.get("state") == "known"
    ]
    if not directional:
        return "unknown", None, {"family_scores": {}, "directional_known": 0}

    families: dict[str, dict[str, Decimal]] = {}
    for item in directional:
        family = str(item["dependency_family"])
        family_scores = families.setdefault(
            family,
            {"bullish": Decimal(0), "bearish": Decimal(0)},
        )
        vote = str(item["vote"])
        if vote in {"bullish", "bearish"}:
            strength = _decimal(item.get("strength")) or Decimal(0)
            family_scores[vote] = max(family_scores[vote], strength)

    family_nets = {
        family: scores["bullish"] - scores["bearish"]
        for family, scores in families.items()
    }
    capacity = sum(
        (max(scores["bullish"], scores["bearish"]) for scores in families.values()),
        Decimal(0),
    )
    net = sum(family_nets.values(), Decimal(0))
    positive_families = sum(value > Decimal("0.10") for value in family_nets.values())
    negative_families = sum(value < Decimal("-0.10") for value in family_nets.values())
    known_neutral = any(item.get("vote") == "neutral" for item in directional)

    if positive_families and negative_families:
        conclusion = "abstain"
        conviction = None
    elif capacity == 0:
        conclusion = "neutral" if known_neutral else "unknown"
        conviction = None
    else:
        dominance = abs(net) / capacity
        strongest_family = max((abs(value) for value in family_nets.values()), default=Decimal(0))
        strong_single_family = strongest_family >= Decimal("0.75")
        if (
            net > 0
            and (positive_families >= 2 or strong_single_family)
            and dominance >= Decimal("0.35")
        ):
            conclusion = "bullish"
            conviction = _fmt(_clip01(dominance))
        elif (
            net < 0
            and (negative_families >= 2 or strong_single_family)
            and dominance >= Decimal("0.35")
        ):
            conclusion = "bearish"
            conviction = _fmt(_clip01(dominance))
        else:
            conclusion = "neutral" if known_neutral else "abstain"
            conviction = None

    audit = {
        "family_scores": {
            family: {key: _fmt(value) for key, value in scores.items()}
            for family, scores in families.items()
        },
        "family_nets": {family: _fmt(value) for family, value in family_nets.items()},
        "net_family_score": _fmt(net),
        "family_capacity": _fmt(capacity),
        "positive_family_count": positive_families,
        "negative_family_count": negative_families,
        "directional_known": len(directional),
        "complexity_does_not_add_weight": True,
    }
    return conclusion, conviction, audit


def _lower_timeframe_conflict(
    *,
    global_environment: Mapping[str, Any],
    h4_reference_vote: str,
) -> dict[str, Any]:
    dimensions = global_environment["learning_dimensions"]
    if h4_reference_vote not in {"bullish", "bearish", "neutral"}:
        return {
            "calculator_id": "h4_lower_timeframe_conflict",
            "version": "h4_lower_timeframe_conflict_v1",
            "role": "directional",
            "dependency_family": "cross_market",
            "state": "insufficient",
            "vote": "unknown",
            "evidence_refs": ["h4_lower_timeframe_conflict_evidence"],
            "observation": {
                "h4_reference_vote": h4_reference_vote,
                "conflict": False,
                "scoreable_when_conflict": True,
                "correlation_group": "h4_lower_timeframe_conflict",
            },
            "explanation": "H4/lower-timeframe conflict cannot be scored without an H4 view.",
        }

    lower = {
        "M5": _direction(dimensions.get("m5_direction")),
        "M15": _direction(dimensions.get("m15_direction")),
        "H1": _direction(dimensions.get("h1_direction")),
    }
    directional = [
        value for value in lower.values() if value in {"bullish", "bearish"}
    ]
    bullish = directional.count("bullish")
    bearish = directional.count("bearish")
    if bullish > bearish:
        lower_consensus = "bullish"
    elif bearish > bullish:
        lower_consensus = "bearish"
    else:
        lower_consensus = "neutral"

    conflict = (
        h4_reference_vote in {"bullish", "bearish"}
        and lower_consensus in {"bullish", "bearish"}
        and h4_reference_vote != lower_consensus
    )
    if conflict:
        vote = h4_reference_vote
        strength = "0.500000"
        explanation = (
            f"H4 conflicts with lower-timeframe consensus: H4={h4_reference_vote}, "
            f"M5={lower['M5']}, M15={lower['M15']}, H1={lower['H1']}. "
            "This is a scoreable conflict hypothesis, not an override."
        )
    else:
        vote = "neutral"
        strength = None
        explanation = (
            f"H4 has no directional conflict with lower-timeframe consensus "
            f"(M5={lower['M5']}, M15={lower['M15']}, H1={lower['H1']})."
        )

    return {
        "calculator_id": "h4_lower_timeframe_conflict",
        "version": "h4_lower_timeframe_conflict_v1",
        "role": "directional",
        "dependency_family": "cross_market",
        "state": "known",
        "vote": vote,
        "evidence_refs": ["h4_lower_timeframe_conflict_evidence"],
        "observation": {
            "h4_reference_vote": h4_reference_vote,
            "lower_timeframes": lower,
            "lower_consensus": lower_consensus,
            "conflict": conflict,
            "scoreable_when_conflict": True,
            "correlation_group": "h4_lower_timeframe_conflict",
        },
        "explanation": explanation,
        **({"strength": strength} if strength is not None else {}),
    }


def evaluate_h4_incremental_value(
    cases: Sequence[Mapping[str, Any]],
    *,
    minimum_sample_n: int = 20,
) -> dict[str, Any]:
    """Evaluate whether H4 adds value over a lower-timeframe baseline.

    This does not assign live weight. It only records whether historical,
    conditional evidence has earned the right to be considered by a later
    fusion build.
    """

    eligible_cases = [
        case
        for case in cases
        if case.get("baseline_correct") in {0, 1}
        and case.get("with_h4_correct") in {0, 1}
    ]
    sample_n = len(eligible_cases)
    baseline_correct = sum(int(case["baseline_correct"]) for case in eligible_cases)
    with_h4_correct = sum(int(case["with_h4_correct"]) for case in eligible_cases)
    baseline_accuracy = (
        Decimal(baseline_correct) / Decimal(sample_n) if sample_n else None
    )
    with_h4_accuracy = (
        Decimal(with_h4_correct) / Decimal(sample_n) if sample_n else None
    )
    accuracy_delta = (
        with_h4_accuracy - baseline_accuracy
        if baseline_accuracy is not None and with_h4_accuracy is not None
        else None
    )
    proven = (
        sample_n >= minimum_sample_n
        and accuracy_delta is not None
        and accuracy_delta > Decimal(0)
    )
    return {
        "sample_n": sample_n,
        "minimum_sample_n": minimum_sample_n,
        "baseline_accuracy": _fmt(baseline_accuracy),
        "with_h4_accuracy": _fmt(with_h4_accuracy),
        "accuracy_delta": _fmt(accuracy_delta),
        "incremental_conditional_value_proven": proven,
        "eligible_for_future_next_15m_influence": proven,
        "timeframe_priority_bonus": "0",
        "default_next_15m_weight": "0",
        "research_only": True,
        "live_money_execution_allowed": False,
    }


def _mini_environment(
    *,
    global_environment: Mapping[str, Any],
    primitives: Mapping[str, Any],
    trend_result: Mapping[str, Any],
) -> dict[str, Any]:
    dimensions = global_environment["learning_dimensions"]
    swings = primitives["confirmed_swing_sequence"]
    breakout = primitives["breakout_lifecycle"]
    high_state = str(breakout["high_side"].get("state") or "unknown")
    low_state = str(breakout["low_side"].get("state") or "unknown")
    breakout_state = f"high:{high_state}|low:{low_state}"
    trend_vote = str(trend_result.get("vote") or "unknown")
    trend_quality = str(
        (trend_result.get("observation") or {}).get("quality_bucket") or "unknown"
    )
    contradictions = primitives["contradiction_flags"]
    return {
        "timeframe": "H4",
        "session": dimensions["session"],
        "session_phase": dimensions["session_phase"],
        "m5_direction": dimensions["m5_direction"],
        "m15_direction": dimensions["m15_direction"],
        "h1_direction": dimensions["h1_direction"],
        "h4_global_direction": dimensions["h4_direction"],
        "volatility_state": dimensions["volatility_state"],
        "structure_regime": swings.get("combined_structure") or "unknown",
        "trend_regime": f"{trend_vote}|quality:{trend_quality}",
        "breakout_state": breakout_state,
        "range_zone": _range_bucket(
            primitives["range_position"]["windows"]["20_bar"].get("position")
        ),
        "contradiction_state": (
            "none"
            if int(contradictions.get("contradiction_count") or 0) == 0
            else "present"
        ),
    }

def _legacy_vote(global_environment: Mapping[str, Any]) -> str:
    return _direction(global_environment["learning_dimensions"].get("h4_direction"))


def _subject_keys(packet: Mapping[str, Any]) -> list[str]:
    keys = [f"gate:{packet['gate_id']}"]
    keys.extend(
        f"subcalculator:{item['calculator_id']}"
        for item in packet["subcalculators"]
    )
    return keys


def build_h4_price_structure_expert(
    *,
    global_environment: Mapping[str, Any],
    price_math_packet: Mapping[str, Any],
    trust_score_rows_by_subject: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Build one frozen H4 expert decision from already-known evidence."""

    if not verify_price_expert_math_packet(price_math_packet):
        raise ValueError("price_math_packet must satisfy Build-4 verification")
    as_of = _utc(str(price_math_packet["as_of_utc"]))
    exact = global_environment.get("exact_facts")
    exact = exact if isinstance(exact, Mapping) else {}
    if _utc(str(exact.get("as_of_utc"))) != as_of:
        raise ValueError("H4 expert requires price math and global environment at the same as-of")

    h4 = price_math_packet["timeframes"]["H4"]
    primitives = h4["primitives"]
    observed = _observed_at(h4, as_of)
    h4_known = h4.get("state") == "known"

    evidence_inputs = [
        _evidence(
            evidence_id="h4_trend_quality_evidence",
            path="timeframes.H4.primitives.trend_path",
            observed_at=observed,
            state="known" if h4_known else "unknown",
            value={
                "returns": primitives["multi_lookback_returns"],
                "regressions": primitives["log_ols_slope"],
                "persistence": primitives["close_step_persistence"],
                "efficiency": primitives["path_efficiency"],
                "normalisation": primitives["atr_rv_normalisation"],
            } if h4_known else None,
            price_math_packet=price_math_packet,
        ),
        _evidence(
            evidence_id="h4_swing_structure_evidence",
            path="timeframes.H4.primitives.swing_structure",
            observed_at=observed,
            state="known" if h4_known else "unknown",
            value={
                "swings": primitives["confirmed_swing_sequence"],
                "structure_break": primitives["structure_break"],
            } if h4_known else None,
            price_math_packet=price_math_packet,
        ),
        _evidence(
            evidence_id="h4_breakout_evidence",
            path="timeframes.H4.primitives.breakout_lifecycle",
            observed_at=observed,
            state="known" if h4_known else "unknown",
            value=primitives["breakout_lifecycle"] if h4_known else None,
            price_math_packet=price_math_packet,
        ),
        _evidence(
            evidence_id="h4_acceleration_evidence",
            path="timeframes.H4.primitives.momentum",
            observed_at=observed,
            state="known" if h4_known else "unknown",
            value={
                "acceleration": primitives["acceleration_deceleration"],
                "three_bar_return": primitives["multi_lookback_returns"]["values"]["3_bar"],
                "three_bar_normalised": primitives["atr_rv_normalisation"]["normalised_returns"]["3_bar"],
            } if h4_known else None,
            price_math_packet=price_math_packet,
        ),
        _evidence(
            evidence_id="h4_candle_pressure_evidence",
            path="timeframes.H4.primitives.candle_geometry",
            observed_at=observed,
            state="known" if h4_known else "unknown",
            value=primitives["candle_geometry"] if h4_known else None,
            price_math_packet=price_math_packet,
        ),
        _evidence(
            evidence_id="h4_range_location_evidence",
            path="timeframes.H4.primitives.range_position",
            observed_at=observed,
            state="known" if h4_known else "unknown",
            value=primitives["range_position"] if h4_known else None,
            price_math_packet=price_math_packet,
        ),
        _evidence(
            evidence_id="h4_diagnostics_evidence",
            path="timeframes.H4.primitives.contradiction_flags",
            observed_at=observed,
            state="known" if h4_known else "unknown",
            value=primitives["contradiction_flags"] if h4_known else None,
            price_math_packet=price_math_packet,
        ),
        _evidence(
            evidence_id="h4_lower_timeframe_conflict_evidence",
            path="global_environment.learning_dimensions.lower_timeframe_directions",
            observed_at=as_of,
            state="known",
            value={
                "m5_direction": global_environment["learning_dimensions"].get("m5_direction"),
                "m15_direction": global_environment["learning_dimensions"].get("m15_direction"),
                "h1_direction": global_environment["learning_dimensions"].get("h1_direction"),
            },
            price_math_packet=price_math_packet,
        ),
    ]

    if h4_known:
        trend = _trend_quality(primitives)
        swing = _swing_structure(primitives)
        breakout = _breakout_acceptance(primitives)
        momentum = _acceleration(primitives)
        candle = _candle_pressure(primitives)
    else:
        missing = {
            "state": "insufficient",
            "vote": "unknown",
            "strength": None,
            "observation": {"state": "unknown"},
            "explanation": "H4 completed-bar evidence is unavailable.",
        }
        trend = swing = breakout = momentum = candle = missing

    calculators = [
        _directional_calculator(
            calculator_id="h4_trend_quality",
            dependency_family="structure",
            evidence_ref="h4_trend_quality_evidence",
            result=trend,
        ),
        _directional_calculator(
            calculator_id="h4_swing_structure",
            dependency_family="structure",
            evidence_ref="h4_swing_structure_evidence",
            result=swing,
        ),
        _directional_calculator(
            calculator_id="h4_breakout_acceptance",
            dependency_family="location",
            evidence_ref="h4_breakout_evidence",
            result=breakout,
        ),
        _directional_calculator(
            calculator_id="h4_acceleration",
            dependency_family="momentum",
            evidence_ref="h4_acceleration_evidence",
            result=momentum,
        ),
        _directional_calculator(
            calculator_id="h4_candle_pressure",
            dependency_family="momentum",
            evidence_ref="h4_candle_pressure_evidence",
            result=candle,
        ),
        _lower_timeframe_conflict(
            global_environment=global_environment,
            h4_reference_vote=str(trend.get("vote") or "unknown"),
        ),
        _location_context(primitives),
        _diagnostic_context(primitives, h4_known=h4_known),
    ]

    conclusion, conviction, consensus_audit = _family_balanced_conclusion(calculators)
    trend_observation = trend.get("observation") or {}
    eight_bar_return_direction = _direction(
        primitives["multi_lookback_returns"]["values"]["8_bar"].get("direction")
    )
    quality_gate_passed = trend_observation.get("quality_gate_passed")
    if (
        conclusion in {"bullish", "bearish"}
        and quality_gate_passed is False
        and conclusion == eight_bar_return_direction
    ):
        consensus_audit["h4_trend_quality_guard_applied"] = True
        consensus_audit["pre_quality_guard_conclusion"] = conclusion
        conclusion = "abstain"
        conviction = None
    else:
        consensus_audit["h4_trend_quality_guard_applied"] = False

    mini = _mini_environment(
        global_environment=global_environment,
        primitives=primitives,
        trend_result=trend,
    )

    known_directional = [
        item
        for item in calculators
        if item["role"] == "directional" and item["state"] == "known"
    ]
    explanation_refs = [f"calc:{item['calculator_id']}" for item in known_directional]
    if not explanation_refs:
        explanation_refs = ["evidence:h4_trend_quality_evidence"]
    explanation_parts = [
        {
            "text": (
                "H4 slow trend quality: "
                f"slope={trend.get('observation', {}).get('eight_bar_slope_log_bps_per_bar')}, "
                f"quality={trend.get('observation', {}).get('quality_bucket')}, "
                f"persistence={trend.get('observation', {}).get('persistence_ratio')}, "
                f"efficiency={trend.get('observation', {}).get('path_efficiency')}."
            ),
            "source_refs": ["calc:h4_trend_quality"],
        },
        {
            "text": (
                "H4 swings/breakout: "
                f"structure={swing.get('observation', {}).get('combined_structure')}, "
                f"break={swing.get('observation', {}).get('structure_break')}, "
                f"breakout={breakout.get('observation', {}).get('high_state')}/"
                f"{breakout.get('observation', {}).get('low_state')}."
            ),
            "source_refs": ["calc:h4_swing_structure", "calc:h4_breakout_acceptance"],
        },
        {
            "text": (
                "H4 location: "
                f"20-bar zone={_range_bucket(primitives['range_position']['windows']['20_bar'].get('position'))}."
            ),
            "source_refs": ["calc:h4_range_location"],
        },
        {
            "text": (
                "H4 contradictions: "
                + (
                    ", ".join(primitives["contradiction_flags"].get("flags") or [])
                    or "none"
                )
                + "."
            ),
            "source_refs": ["calc:h4_price_diagnostics"],
        },
        {
            "text": (
                f"H4 price-structure expert concludes {conclusion}. "
                "Family-balanced evidence prevents correlated calculators from gaining "
                "weight merely by count."
            ),
            "source_refs": explanation_refs,
        },
    ]

    contradictions = []
    if conclusion in {"bullish", "bearish"}:
        opposite = "bearish" if conclusion == "bullish" else "bullish"
        for item in known_directional:
            if item["vote"] == opposite:
                contradictions.append(
                    {
                        "text": (
                            f"{item['calculator_id']} disagrees with the {conclusion} "
                            "H4 conclusion."
                        ),
                        "source_refs": [f"calc:{item['calculator_id']}"],
                    }
                )
    diagnostic_flags = list(primitives["contradiction_flags"].get("flags") or [])
    if diagnostic_flags:
        contradictions.append(
            {
                "text": "Build-4 H4 diagnostics report: " + ", ".join(diagnostic_flags) + ".",
                "source_refs": ["evidence:h4_diagnostics_evidence"],
            }
        )

    packet = build_expert_gate_packet(
        gate_id=H4_GATE_ID,
        gate_version=H4_PRICE_STRUCTURE_EXPERT_VERSION,
        gate_mode="directional",
        dependency_family="structure",
        target_horizon_minutes=H4_TARGET_HORIZON_MINUTES,
        as_of_utc=as_of,
        global_environment=global_environment,
        mini_environment=mini,
        evidence_inputs=evidence_inputs,
        subcalculators=calculators,
        conclusion=conclusion,
        internal_conviction=conviction,
        explanation_parts=explanation_parts,
        contradictions=contradictions,
    )
    if not verify_expert_gate_packet(packet):
        raise ValueError("constructed H4 expert packet failed Build-2 verification")

    scopes = build_trust_scopes(
        packet=packet,
        reduced_contexts=H4_TRUST_REDUCED_CONTEXTS,
    )
    rows_by_subject = trust_score_rows_by_subject or {}
    profiles: dict[str, Mapping[str, Any]] = {}
    for key in _subject_keys(packet):
        profiles[key] = select_conditional_trust(
            score_rows=rows_by_subject.get(key, ()),
            scopes=scopes,
        )
    trust_envelope = build_trust_envelope(
        packet=packet,
        profiles_by_subject=profiles,
    )

    legacy_vote = _legacy_vote(global_environment)
    result = {
        "expert_version": H4_PRICE_STRUCTURE_EXPERT_VERSION,
        "expert_packet": packet,
        "trust_scopes": scopes,
        "trust_envelope": trust_envelope,
        "consensus_audit": consensus_audit,
        "dependency_metadata": H4_DEPENDENCY_METADATA,
        "forecast_influence_policy": {
            "direct_next_15m_authority": False,
            "timeframe_priority_bonus": "0",
            "default_next_15m_weight": "0",
            "requires_incremental_conditional_value": True,
            "requires_future_fusion_build": True,
            "higher_timeframe_does_not_imply_higher_weight": True,
        },
        "independent_calibration": {
            "timeframe": "H4",
            "target_horizon_minutes": H4_TARGET_HORIZON_MINUTES,
            "trend_quality_primary_horizon_hours": 32,
            "trend_quality_secondary_horizon_hours": 52,
            "minimum_mean_r_squared": "0.50",
            "minimum_path_efficiency": "0.45",
            "minimum_persistence_ratio": "0.58",
            "minimum_directional_quality": "0.52",
            "copied_h1_thresholds": False,
        },
        "legacy_comparison": {
            "legacy_h4_vote": legacy_vote,
            "expert_conclusion": conclusion,
            "agreement": legacy_vote == conclusion,
            "legacy_rule_is_baseline_only": True,
            "complexity_grants_no_weight": True,
        },
        "price_math_packet_digest": price_math_packet["packet_digest"],
        "research_only": True,
        "future_values_used": False,
        "live_money_execution_allowed": False,
    }
    return result


def summarise_h4_chronological_replay(
    cases: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Compare frozen H4 expert decisions with the legacy H4 direction after outcomes resolve."""

    expert_score = 0
    legacy_score = 0
    expert_correct = 0
    legacy_correct = 0
    expert_n = 0
    legacy_n = 0

    for case in cases:
        expert = str(case.get("expert_conclusion") or "unknown")
        legacy = str(case.get("legacy_vote") or "unknown")
        realised = str(case.get("realised_direction") or "unknown")
        move = case.get("realised_return_bps")

        expert_row = score_directional_outcome(
            vote=expert,
            realised_direction=realised,
            realised_return_bps=move,
            scoreable=expert in {"bullish", "bearish"},
        )
        legacy_row = score_directional_outcome(
            vote=legacy,
            realised_direction=realised,
            realised_return_bps=move,
            scoreable=legacy in {"bullish", "bearish"},
        )
        if expert_row["correct"] in {0, 1}:
            expert_n += 1
            expert_correct += int(expert_row["correct"])
            expert_score += int(expert_row["score"])
        if legacy_row["correct"] in {0, 1}:
            legacy_n += 1
            legacy_correct += int(legacy_row["correct"])
            legacy_score += int(legacy_row["score"])

    return {
        "case_count": len(cases),
        "expert_scoreable_n": expert_n,
        "legacy_scoreable_n": legacy_n,
        "expert_accuracy": _fmt(Decimal(expert_correct) / Decimal(expert_n)) if expert_n else None,
        "legacy_accuracy": _fmt(Decimal(legacy_correct) / Decimal(legacy_n)) if legacy_n else None,
        "expert_net_impact_score": expert_score,
        "legacy_net_impact_score": legacy_score,
        "net_impact_delta_vs_legacy": expert_score - legacy_score,
        "expert_complexity_is_not_acceptance_evidence": True,
        "research_only": True,
        "live_money_execution_allowed": False,
    }


__all__ = [
    "H4_DEPENDENCY_METADATA",
    "H4_GATE_ID",
    "H4_PRICE_STRUCTURE_EXPERT_VERSION",
    "H4_TARGET_HORIZON_MINUTES",
    "H4_TRUST_REDUCED_CONTEXTS",
    "build_h4_price_structure_expert",
    "evaluate_h4_incremental_value",
    "summarise_h4_chronological_replay",
]
