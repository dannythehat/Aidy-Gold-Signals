"""Build 5: M5 Price Structure Expert for AIDY Gold.

This is the first timeframe mini-brain in the expert-gate programme. It consumes
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

M5_PRICE_STRUCTURE_EXPERT_VERSION = "aidy_gold_m5_price_structure_expert_v1"
M5_GATE_ID = "m5_price_structure_expert"
M5_TARGET_HORIZON_MINUTES = 15

M5_TRUST_REDUCED_CONTEXTS = (
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
    "m5_trend_path",
    "m5_swing_structure",
    "m5_breakout_acceptance",
    "m5_momentum_transition",
    "m5_candle_pressure",
)


def _utc(value: datetime | str) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError("M5 expert timestamps must be timezone-aware")
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


def _observed_at(m5_payload: Mapping[str, Any], as_of: datetime) -> datetime:
    latest = m5_payload.get("latest_completed_open_time_utc")
    if not latest:
        return as_of
    completed_at = _utc(str(latest)) + timedelta(minutes=5)
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
            "future_values_used": False,
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
        "observation": {"state": "insufficient"},
        "explanation": reason,
    }


def _trend_path(primitives: Mapping[str, Any]) -> dict[str, Any]:
    regressions = primitives["log_ols_slope"]["windows"]
    returns = primitives["multi_lookback_returns"]["values"]
    persistence = primitives["close_step_persistence"]
    efficiency = primitives["path_efficiency"]

    regression_rows = [
        regressions[name]
        for name in ("8_bar", "13_bar", "20_bar")
        if regressions[name]["state"] == "known"
    ]
    if (
        not regression_rows
        or persistence.get("state") != "known"
        or efficiency.get("state") != "known"
    ):
        return {
            "state": "insufficient",
            "vote": "unknown",
            "strength": None,
            "observation": {
                "regressions_known": len(regression_rows),
                "persistence_state": persistence.get("state"),
                "efficiency_state": efficiency.get("state"),
            },
            "explanation": "M5 trend path lacks enough completed-bar evidence.",
        }

    directions = [
        row["direction"]
        for row in regression_rows
        if row["direction"] in {"bullish", "bearish"}
    ]
    for name in ("5_bar", "8_bar"):
        row = returns[name]
        if row["state"] == "known" and row["direction"] in {"bullish", "bearish"}:
            directions.append(row["direction"])
    net_direction = persistence.get("net_direction")
    if net_direction in {"bullish", "bearish"}:
        directions.append(net_direction)

    bullish = directions.count("bullish")
    bearish = directions.count("bearish")
    total = bullish + bearish
    agreement = (
        Decimal(max(bullish, bearish)) / Decimal(total)
        if total
        else Decimal(0)
    )
    r2_values = [_decimal(row.get("r_squared")) for row in regression_rows]
    r2_values = [item for item in r2_values if item is not None]
    mean_r2 = (
        sum(r2_values, Decimal(0)) / Decimal(len(r2_values))
        if r2_values
        else Decimal(0)
    )
    path_efficiency = _decimal(efficiency.get("efficiency_ratio")) or Decimal(0)
    persistence_ratio = _decimal(persistence.get("directional_persistence_ratio")) or Decimal(0)
    quality = _clip01(
        mean_r2 * Decimal("0.40")
        + path_efficiency * Decimal("0.35")
        + persistence_ratio * Decimal("0.25")
    )
    directional_quality = _clip01(quality * agreement)

    if total < 3:
        vote = "neutral"
    elif bullish >= bearish + 2 and directional_quality >= Decimal("0.35"):
        vote = "bullish"
    elif bearish >= bullish + 2 and directional_quality >= Decimal("0.35"):
        vote = "bearish"
    else:
        vote = "neutral"

    return {
        "state": "known",
        "vote": vote,
        "strength": _fmt(directional_quality if vote in {"bullish", "bearish"} else None),
        "observation": {
            "bullish_inputs": bullish,
            "bearish_inputs": bearish,
            "agreement_ratio": _fmt(agreement),
            "mean_r_squared": _fmt(mean_r2),
            "path_efficiency": _fmt(path_efficiency),
            "persistence_ratio": _fmt(persistence_ratio),
            "quality_score": _fmt(quality),
            "quality_bucket": _quality_bucket(quality),
        },
        "explanation": (
            f"M5 trend path is {vote}: {max(bullish, bearish)}/{max(total, 1)} directional inputs "
            f"agree, with {_quality_bucket(quality)} path quality."
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
            "explanation": "M5 swing structure is not yet sufficiently confirmed.",
        }

    if combined == "bullish_structure":
        vote = "bullish"
        base = Decimal("0.70")
    elif combined == "bearish_structure":
        vote = "bearish"
        base = Decimal("0.70")
    else:
        vote = "neutral"
        base = Decimal("0")

    if vote == "bullish" and break_state == "close_above_confirmed_swing_high":
        base = Decimal("0.90")
    elif vote == "bearish" and break_state == "close_below_confirmed_swing_low":
        base = Decimal("0.90")
    elif vote == "bullish" and break_state == "close_below_confirmed_swing_low":
        base = Decimal("0.35")
    elif vote == "bearish" and break_state == "close_above_confirmed_swing_high":
        base = Decimal("0.35")

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
        "explanation": f"M5 confirmed swings show {combined}; latest break state is {break_state}.",
    }


def _breakout_acceptance(primitives: Mapping[str, Any]) -> dict[str, Any]:
    breakout = primitives["breakout_lifecycle"]
    high = breakout["high_side"]
    low = breakout["low_side"]
    high_state = str(high.get("state") or "unknown")
    low_state = str(low.get("state") or "unknown")

    bullish_states = {
        "accepted_hold": Decimal("0.85"),
        "retest_hold": Decimal("0.95"),
        "single_close_hold": Decimal("0.60"),
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
        strength = Decimal("0.55")
    elif low_state == "reclaimed_inside" and high_state != "reclaimed_inside":
        vote = "bullish"
        strength = Decimal("0.55")
    elif high_state == "unknown" and low_state == "unknown":
        return {
            "state": "insufficient",
            "vote": "unknown",
            "strength": None,
            "observation": {"high_state": high_state, "low_state": low_state},
            "explanation": "M5 breakout acceptance has no confirmed swing level to evaluate.",
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
            f"M5 breakout lifecycle is high={high_state}, low={low_state}, "
            f"producing {vote}."
        ),
    }


def _momentum_transition(primitives: Mapping[str, Any]) -> dict[str, Any]:
    acceleration = primitives["acceleration_deceleration"]
    returns = primitives["multi_lookback_returns"]["values"]
    normalised = primitives["atr_rv_normalisation"]["normalised_returns"]
    if acceleration.get("state") != "known" or returns["5_bar"]["state"] != "known":
        return {
            "state": "insufficient",
            "vote": "unknown",
            "strength": None,
            "observation": {
                "acceleration_state": acceleration.get("state"),
                "return_5_state": returns["5_bar"]["state"],
            },
            "explanation": "M5 momentum transition lacks enough completed-bar evidence.",
        }

    recent_direction = returns["5_bar"]["direction"]
    acceleration_state = str(acceleration.get("state_label") or "unknown")
    atr_units = _decimal(normalised["5_bar"].get("atr_units"))
    magnitude = (
        min(abs(atr_units), Decimal(2)) / Decimal(2)
        if atr_units is not None
        else Decimal("0.25")
    )

    if recent_direction not in {"bullish", "bearish"}:
        vote = "neutral"
        strength = None
    elif acceleration_state in {"accelerating", "direction_reversal"}:
        vote = recent_direction
        base = Decimal("0.55") + magnitude * Decimal("0.35")
        strength = _clip01(base)
    elif acceleration_state == "steady":
        vote = recent_direction
        strength = Decimal("0.50")
    elif acceleration_state == "decelerating":
        vote = "neutral"
        strength = None
    else:
        vote = "neutral"
        strength = None

    return {
        "state": "known",
        "vote": vote,
        "strength": _fmt(strength),
        "observation": {
            "five_bar_direction": recent_direction,
            "five_bar_return_bps": returns["5_bar"].get("return_bps"),
            "five_bar_atr_units": normalised["5_bar"].get("atr_units"),
            "acceleration_state": acceleration_state,
            "previous_return_bps": acceleration.get("previous_return_bps"),
            "recent_return_bps": acceleration.get("recent_return_bps"),
        },
        "explanation": (
            f"M5 momentum is {vote}: five-bar direction={recent_direction}, "
            f"transition={acceleration_state}."
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
            "explanation": "Latest completed M5 candle geometry is unavailable.",
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
        and close_location >= Decimal("0.70")
        and body_fraction is not None
        and body_fraction >= Decimal("0.35")
    ):
        vote = "bullish"
        strength = min(Decimal("0.60"), Decimal("0.35") + body_fraction * Decimal("0.25"))
    elif (
        body_direction == "bearish"
        and close_location is not None
        and close_location <= Decimal("0.30")
        and body_fraction is not None
        and body_fraction >= Decimal("0.35")
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
        "explanation": f"Latest completed M5 candle pressure is {vote}.",
    }


def _location_context(primitives: Mapping[str, Any]) -> dict[str, Any]:
    ranges = primitives["range_position"]["windows"]
    value = ranges["20_bar"]
    state = "known" if value.get("state") == "known" else "insufficient"
    return {
        "calculator_id": "m5_range_location",
        "version": "m5_range_location_v1",
        "role": "context_only",
        "dependency_family": "location",
        "state": state,
        "vote": "context_only" if state == "known" else "unknown",
        "evidence_refs": ["m5_range_location_evidence"],
        "observation": {
            "range_20_position": value.get("position"),
            "range_20_bucket": _range_bucket(value.get("position")),
            "range_50_position": ranges["50_bar"].get("position"),
        },
        "explanation": "M5 range location is context only and does not vote directionally.",
    }


def _diagnostic_context(
    primitives: Mapping[str, Any], *, m5_known: bool
) -> dict[str, Any]:
    diagnostic = primitives["contradiction_flags"]
    state = "known" if m5_known else "insufficient"
    return {
        "calculator_id": "m5_price_diagnostics",
        "version": "m5_price_diagnostics_v1",
        "role": "context_only",
        "dependency_family": "data_quality",
        "state": state,
        "vote": "context_only" if state == "known" else "unknown",
        "evidence_refs": ["m5_diagnostics_evidence"],
        "observation": {
            "contradiction_count": diagnostic.get("contradiction_count"),
            "flags": list(diagnostic.get("flags") or []),
        },
        "explanation": "Build-4 M5 contradiction diagnostics are retained explicitly.",
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
        "observation": dict(result["observation"]),
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
    trend_vote = str(trend_result.get("vote") or "unknown")
    trend_quality = str((trend_result.get("observation") or {}).get("quality_bucket") or "unknown")
    contradictions = primitives["contradiction_flags"]
    return {
        "timeframe": "M5",
        "session": dimensions["session"],
        "session_phase": dimensions["session_phase"],
        "m5_global_direction": dimensions["m5_direction"],
        "m15_direction": dimensions["m15_direction"],
        "h1_direction": dimensions["h1_direction"],
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
    return _direction(global_environment["learning_dimensions"].get("m5_direction"))


def _subject_keys(packet: Mapping[str, Any]) -> list[str]:
    keys = [f"gate:{packet['gate_id']}"]
    keys.extend(
        f"subcalculator:{item['calculator_id']}"
        for item in packet["subcalculators"]
    )
    return keys


def build_m5_price_structure_expert(
    *,
    global_environment: Mapping[str, Any],
    price_math_packet: Mapping[str, Any],
    trust_score_rows_by_subject: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Build one frozen M5 expert decision from already-known evidence."""

    if not verify_price_expert_math_packet(price_math_packet):
        raise ValueError("price_math_packet must satisfy Build-4 verification")
    as_of = _utc(str(price_math_packet["as_of_utc"]))
    exact = global_environment.get("exact_facts")
    exact = exact if isinstance(exact, Mapping) else {}
    if _utc(str(exact.get("as_of_utc"))) != as_of:
        raise ValueError("M5 expert requires price math and global environment at the same as-of")

    m5 = price_math_packet["timeframes"]["M5"]
    primitives = m5["primitives"]
    observed = _observed_at(m5, as_of)
    m5_known = m5.get("state") == "known"

    evidence_inputs = [
        _evidence(
            evidence_id="m5_trend_path_evidence",
            path="timeframes.M5.primitives.trend_path",
            observed_at=observed,
            state="known" if m5_known else "unknown",
            value={
                "returns": primitives["multi_lookback_returns"],
                "regressions": primitives["log_ols_slope"],
                "persistence": primitives["close_step_persistence"],
                "efficiency": primitives["path_efficiency"],
            } if m5_known else None,
            price_math_packet=price_math_packet,
        ),
        _evidence(
            evidence_id="m5_swing_structure_evidence",
            path="timeframes.M5.primitives.swing_structure",
            observed_at=observed,
            state="known" if m5_known else "unknown",
            value={
                "swings": primitives["confirmed_swing_sequence"],
                "structure_break": primitives["structure_break"],
            } if m5_known else None,
            price_math_packet=price_math_packet,
        ),
        _evidence(
            evidence_id="m5_breakout_evidence",
            path="timeframes.M5.primitives.breakout_lifecycle",
            observed_at=observed,
            state="known" if m5_known else "unknown",
            value=primitives["breakout_lifecycle"] if m5_known else None,
            price_math_packet=price_math_packet,
        ),
        _evidence(
            evidence_id="m5_momentum_evidence",
            path="timeframes.M5.primitives.momentum",
            observed_at=observed,
            state="known" if m5_known else "unknown",
            value={
                "acceleration": primitives["acceleration_deceleration"],
                "normalised": primitives["atr_rv_normalisation"],
                "returns": primitives["multi_lookback_returns"],
            } if m5_known else None,
            price_math_packet=price_math_packet,
        ),
        _evidence(
            evidence_id="m5_candle_pressure_evidence",
            path="timeframes.M5.primitives.candle_geometry",
            observed_at=observed,
            state="known" if m5_known else "unknown",
            value=primitives["candle_geometry"] if m5_known else None,
            price_math_packet=price_math_packet,
        ),
        _evidence(
            evidence_id="m5_range_location_evidence",
            path="timeframes.M5.primitives.range_position",
            observed_at=observed,
            state="known" if m5_known else "unknown",
            value=primitives["range_position"] if m5_known else None,
            price_math_packet=price_math_packet,
        ),
        _evidence(
            evidence_id="m5_diagnostics_evidence",
            path="timeframes.M5.primitives.contradiction_flags",
            observed_at=observed,
            state="known" if m5_known else "unknown",
            value=primitives["contradiction_flags"] if m5_known else None,
            price_math_packet=price_math_packet,
        ),
    ]

    if m5_known:
        trend = _trend_path(primitives)
        swing = _swing_structure(primitives)
        breakout = _breakout_acceptance(primitives)
        momentum = _momentum_transition(primitives)
        candle = _candle_pressure(primitives)
    else:
        missing = {
            "state": "insufficient",
            "vote": "unknown",
            "strength": None,
            "observation": {"state": "unknown"},
            "explanation": "M5 completed-bar evidence is unavailable.",
        }
        trend = swing = breakout = momentum = candle = missing

    calculators = [
        _directional_calculator(
            calculator_id="m5_trend_path",
            dependency_family="structure",
            evidence_ref="m5_trend_path_evidence",
            result=trend,
        ),
        _directional_calculator(
            calculator_id="m5_swing_structure",
            dependency_family="structure",
            evidence_ref="m5_swing_structure_evidence",
            result=swing,
        ),
        _directional_calculator(
            calculator_id="m5_breakout_acceptance",
            dependency_family="location",
            evidence_ref="m5_breakout_evidence",
            result=breakout,
        ),
        _directional_calculator(
            calculator_id="m5_momentum_transition",
            dependency_family="momentum",
            evidence_ref="m5_momentum_evidence",
            result=momentum,
        ),
        _directional_calculator(
            calculator_id="m5_candle_pressure",
            dependency_family="momentum",
            evidence_ref="m5_candle_pressure_evidence",
            result=candle,
        ),
        _location_context(primitives),
        _diagnostic_context(primitives, m5_known=m5_known),
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
        explanation_refs = ["evidence:m5_trend_path_evidence"]
    explanation_parts = [
        {
            "text": (
                f"M5 price-structure expert concludes {conclusion}. "
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
                            "M5 conclusion."
                        ),
                        "source_refs": [f"calc:{item['calculator_id']}"],
                    }
                )
    diagnostic_flags = list(primitives["contradiction_flags"].get("flags") or [])
    if diagnostic_flags:
        contradictions.append(
            {
                "text": "Build-4 M5 diagnostics report: " + ", ".join(diagnostic_flags) + ".",
                "source_refs": ["evidence:m5_diagnostics_evidence"],
            }
        )

    packet = build_expert_gate_packet(
        gate_id=M5_GATE_ID,
        gate_version=M5_PRICE_STRUCTURE_EXPERT_VERSION,
        gate_mode="directional",
        dependency_family="structure",
        target_horizon_minutes=M5_TARGET_HORIZON_MINUTES,
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
        raise ValueError("constructed M5 expert packet failed Build-2 verification")

    scopes = build_trust_scopes(
        packet=packet,
        reduced_contexts=M5_TRUST_REDUCED_CONTEXTS,
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
        "expert_version": M5_PRICE_STRUCTURE_EXPERT_VERSION,
        "expert_packet": packet,
        "trust_scopes": scopes,
        "trust_envelope": trust_envelope,
        "consensus_audit": consensus_audit,
        "legacy_comparison": {
            "legacy_m5_vote": legacy_vote,
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


def summarise_m5_chronological_replay(
    cases: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Compare frozen M5 expert decisions with the legacy M5 direction after outcomes resolve."""

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
    "M5_GATE_ID",
    "M5_PRICE_STRUCTURE_EXPERT_VERSION",
    "M5_TARGET_HORIZON_MINUTES",
    "M5_TRUST_REDUCED_CONTEXTS",
    "build_m5_price_structure_expert",
    "summarise_m5_chronological_replay",
]
