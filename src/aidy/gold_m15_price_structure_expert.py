"""Build 6: M15 Price Structure Expert for AIDY Gold.

This is the second timeframe mini-brain in the expert-gate programme. It consumes
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

M15_PRICE_STRUCTURE_EXPERT_VERSION = "aidy_gold_m15_price_structure_expert_v1"
M15_GATE_ID = "m15_price_structure_expert"
M15_TARGET_HORIZON_MINUTES = 60

M15_TRUST_REDUCED_CONTEXTS = (
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
    "m15_8_bar_path",
    "m15_swing_structure",
    "m15_breakout_acceptance",
    "m15_latest_15m_momentum",
    "m15_candle_pressure",
)

M15_DEPENDENCY_METADATA = {
    "m15_8_bar_path": {
        "dependency_family": "structure",
        "correlation_group": "m15_path_structure",
    },
    "m15_swing_structure": {
        "dependency_family": "structure",
        "correlation_group": "m15_path_structure",
    },
    "m15_breakout_acceptance": {
        "dependency_family": "location",
        "correlation_group": "m15_breakout_location",
    },
    "m15_latest_15m_momentum": {
        "dependency_family": "momentum",
        "correlation_group": "m15_latest_bar_momentum",
    },
    "m15_candle_pressure": {
        "dependency_family": "momentum",
        "correlation_group": "m15_latest_bar_momentum",
    },
    "m15_range_location": {
        "dependency_family": "location",
        "correlation_group": "m15_breakout_location",
    },
    "m15_price_diagnostics": {
        "dependency_family": "data_quality",
        "correlation_group": "m15_diagnostics",
    },
}


def _utc(value: datetime | str) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError("M15 expert timestamps must be timezone-aware")
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


def _observed_at(m15_payload: Mapping[str, Any], as_of: datetime) -> datetime:
    latest = m15_payload.get("latest_completed_open_time_utc")
    if not latest:
        return as_of
    completed_at = _utc(str(latest)) + timedelta(minutes=15)
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
            "correlation_group": M15_DEPENDENCY_METADATA.get(
                calculator_id, {}
            ).get("correlation_group", "unknown"),
        },
        "explanation": reason,
    }


def _eight_bar_path(primitives: Mapping[str, Any]) -> dict[str, Any]:
    regressions = primitives["log_ols_slope"]["windows"]
    returns = primitives["multi_lookback_returns"]["values"]
    persistence = primitives["close_step_persistence"]
    efficiency = primitives["path_efficiency"]
    normalised = primitives["atr_rv_normalisation"]["normalised_returns"]

    regression = regressions["8_bar"]
    path_return = returns["8_bar"]
    normalised_return = normalised["8_bar"]
    if (
        regression.get("state") != "known"
        or path_return.get("state") != "known"
        or persistence.get("state") != "known"
        or efficiency.get("state") != "known"
        or normalised_return.get("state") != "known"
    ):
        return {
            "state": "insufficient",
            "vote": "unknown",
            "strength": None,
            "observation": {
                "eight_bar_return_state": path_return.get("state"),
                "eight_bar_regression_state": regression.get("state"),
                "persistence_state": persistence.get("state"),
                "efficiency_state": efficiency.get("state"),
                "normalised_state": normalised_return.get("state"),
            },
            "explanation": "M15 eight-bar path lacks enough completed-bar evidence.",
        }

    directions = [
        _direction(path_return.get("direction")),
        _direction(regression.get("direction")),
        _direction(persistence.get("net_direction")),
    ]
    bullish = directions.count("bullish")
    bearish = directions.count("bearish")
    total = bullish + bearish
    agreement = (
        Decimal(max(bullish, bearish)) / Decimal(total)
        if total
        else Decimal(0)
    )

    r_squared = _decimal(regression.get("r_squared")) or Decimal(0)
    path_efficiency = _decimal(efficiency.get("efficiency_ratio")) or Decimal(0)
    persistence_ratio = _decimal(persistence.get("directional_persistence_ratio")) or Decimal(0)
    atr_units = _decimal(normalised_return.get("atr_units"))
    displacement_quality = (
        min(abs(atr_units), Decimal(4)) / Decimal(4)
        if atr_units is not None
        else Decimal(0)
    )

    quality = _clip01(
        r_squared * Decimal("0.35")
        + path_efficiency * Decimal("0.30")
        + persistence_ratio * Decimal("0.20")
        + displacement_quality * Decimal("0.15")
    )
    directional_quality = _clip01(quality * agreement)

    if total < 2:
        vote = "neutral"
    elif bullish >= 2 and bullish > bearish and directional_quality >= Decimal("0.42"):
        vote = "bullish"
    elif bearish >= 2 and bearish > bullish and directional_quality >= Decimal("0.42"):
        vote = "bearish"
    else:
        vote = "neutral"

    return {
        "state": "known",
        "vote": vote,
        "strength": _fmt(directional_quality if vote in {"bullish", "bearish"} else None),
        "observation": {
            "eight_bar_horizon_minutes": 120,
            "eight_bar_return_bps": path_return.get("return_bps"),
            "eight_bar_direction": path_return.get("direction"),
            "eight_bar_atr_units": normalised_return.get("atr_units"),
            "eight_bar_rv_units": normalised_return.get("rv_units"),
            "eight_bar_slope_log_bps_per_bar": regression.get("slope_log_bps_per_bar"),
            "eight_bar_regression_r_squared": regression.get("r_squared"),
            "path_efficiency": efficiency.get("efficiency_ratio"),
            "persistence_ratio": persistence.get("directional_persistence_ratio"),
            "agreement_ratio": _fmt(agreement),
            "quality_score": _fmt(quality),
            "quality_bucket": _quality_bucket(quality),
        },
        "explanation": (
            f"M15 eight-bar path is {vote}: {max(bullish, bearish)}/{max(total, 1)} "
            f"directional path inputs agree with {_quality_bucket(quality)} quality."
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
            "explanation": "M15 swing structure is not yet sufficiently confirmed.",
        }

    if combined == "bullish_structure":
        vote = "bullish"
        base = Decimal("0.72")
    elif combined == "bearish_structure":
        vote = "bearish"
        base = Decimal("0.72")
    else:
        vote = "neutral"
        base = Decimal(0)

    if (
        (vote == "bullish" and break_state == "close_above_confirmed_swing_high")
        or (vote == "bearish" and break_state == "close_below_confirmed_swing_low")
    ):
        base = Decimal("0.92")
    elif (
        (vote == "bullish" and break_state == "close_below_confirmed_swing_low")
        or (vote == "bearish" and break_state == "close_above_confirmed_swing_high")
    ):
        base = Decimal("0.30")

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
        "explanation": f"M15 confirmed swings show {combined}; latest break state is {break_state}.",
    }


def _breakout_acceptance(primitives: Mapping[str, Any]) -> dict[str, Any]:
    breakout = primitives["breakout_lifecycle"]
    high = breakout["high_side"]
    low = breakout["low_side"]
    high_state = str(high.get("state") or "unknown")
    low_state = str(low.get("state") or "unknown")

    bullish_states = {
        "accepted_hold": Decimal("0.82"),
        "retest_hold": Decimal("0.93"),
        "single_close_hold": Decimal("0.52"),
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
        strength = Decimal("0.50")
    elif low_state == "reclaimed_inside" and high_state != "reclaimed_inside":
        vote = "bullish"
        strength = Decimal("0.50")
    elif high_state == "unknown" and low_state == "unknown":
        return {
            "state": "insufficient",
            "vote": "unknown",
            "strength": None,
            "observation": {"high_state": high_state, "low_state": low_state},
            "explanation": "M15 breakout acceptance has no confirmed swing level to evaluate.",
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
            f"M15 breakout lifecycle is high={high_state}, low={low_state}, "
            f"producing {vote}."
        ),
    }


def _latest_15m_momentum(primitives: Mapping[str, Any]) -> dict[str, Any]:
    returns = primitives["multi_lookback_returns"]["values"]
    geometry = primitives["candle_geometry"]
    normalisation = primitives["atr_rv_normalisation"]

    one_bar = returns["1_bar"]
    atr_bps = _decimal(normalisation.get("atr_14_bps"))
    return_bps = _decimal(one_bar.get("return_bps"))
    if (
        one_bar.get("state") != "known"
        or geometry.get("state") != "known"
        or atr_bps in {None, Decimal(0)}
        or return_bps is None
    ):
        return {
            "state": "insufficient",
            "vote": "unknown",
            "strength": None,
            "observation": {
                "one_bar_state": one_bar.get("state"),
                "candle_geometry_state": geometry.get("state"),
                "atr_14_bps": normalisation.get("atr_14_bps"),
            },
            "explanation": "Latest completed 15-minute momentum cannot be normalised reliably.",
        }

    direction = _direction(one_bar.get("direction"))
    body_direction = _direction(geometry.get("body_direction"))
    close_location = _decimal(geometry.get("close_location"))
    body_fraction = _decimal(geometry.get("body_fraction_of_range"))
    atr_units = abs(return_bps) / atr_bps

    bullish_support = (
        direction == "bullish"
        and body_direction == "bullish"
        and close_location is not None
        and close_location >= Decimal("0.62")
    )
    bearish_support = (
        direction == "bearish"
        and body_direction == "bearish"
        and close_location is not None
        and close_location <= Decimal("0.38")
    )
    body_ok = body_fraction is not None and body_fraction >= Decimal("0.25")
    magnitude_ok = atr_units >= Decimal("0.18")

    if bullish_support and body_ok and magnitude_ok:
        vote = "bullish"
    elif bearish_support and body_ok and magnitude_ok:
        vote = "bearish"
    else:
        vote = "neutral"

    strength = None
    if vote in {"bullish", "bearish"}:
        magnitude_component = min(atr_units, Decimal("1.50")) / Decimal("1.50")
        body_component = min(body_fraction or Decimal(0), Decimal(1))
        strength = _clip01(
            Decimal("0.40")
            + magnitude_component * Decimal("0.30")
            + body_component * Decimal("0.15")
        )

    return {
        "state": "known",
        "vote": vote,
        "strength": _fmt(strength),
        "observation": {
            "latest_15m_return_bps": one_bar.get("return_bps"),
            "latest_15m_direction": one_bar.get("direction"),
            "latest_15m_atr_units": _fmt(atr_units),
            "body_direction": geometry.get("body_direction"),
            "body_fraction_of_range": geometry.get("body_fraction_of_range"),
            "close_location": geometry.get("close_location"),
            "magnitude_threshold_atr_units": "0.18",
            "body_threshold": "0.25",
        },
        "explanation": (
            f"Latest completed M15 candle momentum is {vote}: "
            f"{_fmt(atr_units)} ATR units with close/body confirmation."
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
            "explanation": "Latest completed M15 candle geometry is unavailable.",
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
        and close_location >= Decimal("0.72")
        and body_fraction is not None
        and body_fraction >= Decimal("0.40")
    ):
        vote = "bullish"
        strength = min(Decimal("0.60"), Decimal("0.35") + body_fraction * Decimal("0.25"))
    elif (
        body_direction == "bearish"
        and close_location is not None
        and close_location <= Decimal("0.28")
        and body_fraction is not None
        and body_fraction >= Decimal("0.40")
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
        "explanation": f"Latest completed M15 candle pressure is {vote}.",
    }


def _location_context(primitives: Mapping[str, Any]) -> dict[str, Any]:
    ranges = primitives["range_position"]["windows"]
    value = ranges["20_bar"]
    state = "known" if value.get("state") == "known" else "insufficient"
    return {
        "calculator_id": "m15_range_location",
        "version": "m15_range_location_v1",
        "role": "context_only",
        "dependency_family": "location",
        "state": state,
        "vote": "context_only" if state == "known" else "unknown",
        "evidence_refs": ["m15_range_location_evidence"],
        "observation": {
            "range_20_position": value.get("position"),
            "range_20_bucket": _range_bucket(value.get("position")),
            "range_50_position": ranges["50_bar"].get("position"),
            "correlation_group": "m15_breakout_location",
        },
        "explanation": "M15 range location is context only and does not vote directionally.",
    }


def _diagnostic_context(
    primitives: Mapping[str, Any], *, m15_known: bool
) -> dict[str, Any]:
    diagnostic = primitives["contradiction_flags"]
    state = "known" if m15_known else "insufficient"
    return {
        "calculator_id": "m15_price_diagnostics",
        "version": "m15_price_diagnostics_v1",
        "role": "context_only",
        "dependency_family": "data_quality",
        "state": state,
        "vote": "context_only" if state == "known" else "unknown",
        "evidence_refs": ["m15_diagnostics_evidence"],
        "observation": {
            "contradiction_count": diagnostic.get("contradiction_count"),
            "flags": list(diagnostic.get("flags") or []),
            "correlation_group": "m15_diagnostics",
        },
        "explanation": "Build-4 M15 contradiction diagnostics are retained explicitly.",
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
            "correlation_group": M15_DEPENDENCY_METADATA.get(
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
    path_vote = str(trend_result.get("vote") or "unknown")
    path_quality = str(
        (trend_result.get("observation") or {}).get("quality_bucket") or "unknown"
    )
    contradictions = primitives["contradiction_flags"]
    return {
        "timeframe": "M15",
        "session": dimensions["session"],
        "session_phase": dimensions["session_phase"],
        "m5_direction": dimensions["m5_direction"],
        "m15_global_direction": dimensions["m15_direction"],
        "h1_direction": dimensions["h1_direction"],
        "h4_direction": dimensions["h4_direction"],
        "volatility_state": dimensions["volatility_state"],
        "structure_regime": swings.get("combined_structure") or "unknown",
        "trend_regime": f"{path_vote}|quality:{path_quality}",
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
    return _direction(global_environment["learning_dimensions"].get("m15_direction"))


def _subject_keys(packet: Mapping[str, Any]) -> list[str]:
    keys = [f"gate:{packet['gate_id']}"]
    keys.extend(
        f"subcalculator:{item['calculator_id']}"
        for item in packet["subcalculators"]
    )
    return keys


def build_m15_price_structure_expert(
    *,
    global_environment: Mapping[str, Any],
    price_math_packet: Mapping[str, Any],
    trust_score_rows_by_subject: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Build one frozen M15 expert decision from already-known evidence."""

    if not verify_price_expert_math_packet(price_math_packet):
        raise ValueError("price_math_packet must satisfy Build-4 verification")
    as_of = _utc(str(price_math_packet["as_of_utc"]))
    exact = global_environment.get("exact_facts")
    exact = exact if isinstance(exact, Mapping) else {}
    if _utc(str(exact.get("as_of_utc"))) != as_of:
        raise ValueError("M15 expert requires price math and global environment at the same as-of")

    m15 = price_math_packet["timeframes"]["M15"]
    primitives = m15["primitives"]
    observed = _observed_at(m15, as_of)
    m15_known = m15.get("state") == "known"

    evidence_inputs = [
        _evidence(
            evidence_id="m15_8_bar_path_evidence",
            path="timeframes.M15.primitives.trend_path",
            observed_at=observed,
            state="known" if m15_known else "unknown",
            value={
                "eight_bar_return": primitives["multi_lookback_returns"]["values"]["8_bar"],
                "eight_bar_regression": primitives["log_ols_slope"]["windows"]["8_bar"],
                "persistence": primitives["close_step_persistence"],
                "efficiency": primitives["path_efficiency"],
                "normalised_eight_bar": primitives["atr_rv_normalisation"]["normalised_returns"]["8_bar"],
            } if m15_known else None,
            price_math_packet=price_math_packet,
        ),
        _evidence(
            evidence_id="m15_swing_structure_evidence",
            path="timeframes.M15.primitives.swing_structure",
            observed_at=observed,
            state="known" if m15_known else "unknown",
            value={
                "swings": primitives["confirmed_swing_sequence"],
                "structure_break": primitives["structure_break"],
            } if m15_known else None,
            price_math_packet=price_math_packet,
        ),
        _evidence(
            evidence_id="m15_breakout_evidence",
            path="timeframes.M15.primitives.breakout_lifecycle",
            observed_at=observed,
            state="known" if m15_known else "unknown",
            value=primitives["breakout_lifecycle"] if m15_known else None,
            price_math_packet=price_math_packet,
        ),
        _evidence(
            evidence_id="m15_latest_15m_momentum_evidence",
            path="timeframes.M15.primitives.momentum",
            observed_at=observed,
            state="known" if m15_known else "unknown",
            value={
                "latest_15m_return": primitives["multi_lookback_returns"]["values"]["1_bar"],
                "candle_geometry": primitives["candle_geometry"],
                "atr_rv_normalisation": primitives["atr_rv_normalisation"],
            } if m15_known else None,
            price_math_packet=price_math_packet,
        ),
        _evidence(
            evidence_id="m15_candle_pressure_evidence",
            path="timeframes.M15.primitives.candle_geometry",
            observed_at=observed,
            state="known" if m15_known else "unknown",
            value=primitives["candle_geometry"] if m15_known else None,
            price_math_packet=price_math_packet,
        ),
        _evidence(
            evidence_id="m15_range_location_evidence",
            path="timeframes.M15.primitives.range_position",
            observed_at=observed,
            state="known" if m15_known else "unknown",
            value=primitives["range_position"] if m15_known else None,
            price_math_packet=price_math_packet,
        ),
        _evidence(
            evidence_id="m15_diagnostics_evidence",
            path="timeframes.M15.primitives.contradiction_flags",
            observed_at=observed,
            state="known" if m15_known else "unknown",
            value=primitives["contradiction_flags"] if m15_known else None,
            price_math_packet=price_math_packet,
        ),
    ]

    if m15_known:
        trend = _eight_bar_path(primitives)
        swing = _swing_structure(primitives)
        breakout = _breakout_acceptance(primitives)
        momentum = _latest_15m_momentum(primitives)
        candle = _candle_pressure(primitives)
    else:
        missing = {
            "state": "insufficient",
            "vote": "unknown",
            "strength": None,
            "observation": {"state": "unknown"},
            "explanation": "M15 completed-bar evidence is unavailable.",
        }
        trend = swing = breakout = momentum = candle = missing

    calculators = [
        _directional_calculator(
            calculator_id="m15_8_bar_path",
            dependency_family="structure",
            evidence_ref="m15_8_bar_path_evidence",
            result=trend,
        ),
        _directional_calculator(
            calculator_id="m15_swing_structure",
            dependency_family="structure",
            evidence_ref="m15_swing_structure_evidence",
            result=swing,
        ),
        _directional_calculator(
            calculator_id="m15_breakout_acceptance",
            dependency_family="location",
            evidence_ref="m15_breakout_evidence",
            result=breakout,
        ),
        _directional_calculator(
            calculator_id="m15_latest_15m_momentum",
            dependency_family="momentum",
            evidence_ref="m15_latest_15m_momentum_evidence",
            result=momentum,
        ),
        _directional_calculator(
            calculator_id="m15_candle_pressure",
            dependency_family="momentum",
            evidence_ref="m15_candle_pressure_evidence",
            result=candle,
        ),
        _location_context(primitives),
        _diagnostic_context(primitives, m15_known=m15_known),
    ]

    conclusion, conviction, consensus_audit = _family_balanced_conclusion(calculators)
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
        explanation_refs = ["evidence:m15_8_bar_path_evidence"]
    explanation_parts = [
        {
            "text": (
                f"M15 price-structure expert concludes {conclusion}. "
                "Family-balanced evidence prevents correlated calculators from gaining "
                "weight merely by count."
            ),
            "source_refs": explanation_refs,
        }
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
                            "M15 conclusion."
                        ),
                        "source_refs": [f"calc:{item['calculator_id']}"],
                    }
                )
    diagnostic_flags = list(primitives["contradiction_flags"].get("flags") or [])
    if diagnostic_flags:
        contradictions.append(
            {
                "text": "Build-4 M15 diagnostics report: " + ", ".join(diagnostic_flags) + ".",
                "source_refs": ["evidence:m15_diagnostics_evidence"],
            }
        )

    packet = build_expert_gate_packet(
        gate_id=M15_GATE_ID,
        gate_version=M15_PRICE_STRUCTURE_EXPERT_VERSION,
        gate_mode="directional",
        dependency_family="structure",
        target_horizon_minutes=M15_TARGET_HORIZON_MINUTES,
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
        raise ValueError("constructed M15 expert packet failed Build-2 verification")

    scopes = build_trust_scopes(
        packet=packet,
        reduced_contexts=M15_TRUST_REDUCED_CONTEXTS,
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
        "expert_version": M15_PRICE_STRUCTURE_EXPERT_VERSION,
        "expert_packet": packet,
        "trust_scopes": scopes,
        "trust_envelope": trust_envelope,
        "consensus_audit": consensus_audit,
        "dependency_metadata": M15_DEPENDENCY_METADATA,
        "independent_calibration": {
            "timeframe": "M15",
            "target_horizon_minutes": M15_TARGET_HORIZON_MINUTES,
            "eight_bar_path_horizon_minutes": 120,
            "eight_bar_directional_quality_threshold": "0.42",
            "latest_15m_momentum_atr_threshold": "0.18",
            "latest_15m_body_fraction_threshold": "0.25",
            "copied_m5_thresholds": False,
        },
        "legacy_comparison": {
            "legacy_m15_vote": legacy_vote,
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


def summarise_m15_chronological_replay(
    cases: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Compare frozen M15 expert decisions with the legacy M15 direction after outcomes resolve."""

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
    "M15_GATE_ID",
    "M15_PRICE_STRUCTURE_EXPERT_VERSION",
    "M15_TARGET_HORIZON_MINUTES",
    "M15_TRUST_REDUCED_CONTEXTS",
    "M15_DEPENDENCY_METADATA",
    "build_m15_price_structure_expert",
    "summarise_m15_chronological_replay",
]
