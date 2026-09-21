"""Build 10: Momentum / Impulse Expert for AIDY Gold.

The expert distinguishes continuation-quality momentum from noisy direction. It
uses exact completed M1 paths for 1/5/15/30/60-minute returns, volatility
normalisation, acceleration, persistence, path efficiency, impulse/drift,
exhaustion and multi-horizon agreement.

This module is research/shadow only. It does not grant live-money authority.
"""

from __future__ import annotations

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

MOMENTUM_IMPULSE_EXPERT_VERSION = "aidy_gold_momentum_impulse_expert_v1"
MOMENTUM_IMPULSE_GATE_ID = "momentum_impulse_expert"
MOMENTUM_TARGET_HORIZON_MINUTES = 15
MOMENTUM_HORIZONS_MINUTES = (1, 5, 15, 30, 60)

MOMENTUM_TRUST_REDUCED_CONTEXTS = (
    {
        "name": "clock_regime",
        "mini_dimensions": [
            "volatility_state",
            "utc_clock_bucket_15m",
            "session_phase",
        ],
        "global_dimensions": [],
        "minimum_sample_n": 12,
    },
    {
        "name": "momentum_regime",
        "mini_dimensions": [
            "momentum_state",
            "five_minute_distribution_state",
            "five_minute_range_state",
        ],
        "global_dimensions": [],
        "minimum_sample_n": 10,
    },
    {
        "name": "session_momentum",
        "mini_dimensions": ["session", "session_phase", "momentum_state"],
        "global_dimensions": [],
        "minimum_sample_n": 8,
    },
)

MOMENTUM_DEPENDENCY_METADATA = {
    "momentum_multi_horizon": {
        "dependency_family": "momentum",
        "correlation_group": "price_path_returns",
        "later_penalty_tag": "correlated_price_expert_input",
    },
    "momentum_persistence_efficiency": {
        "dependency_family": "momentum",
        "correlation_group": "price_path_quality",
        "later_penalty_tag": "correlated_price_expert_input",
    },
    "momentum_acceleration": {
        "dependency_family": "momentum",
        "correlation_group": "price_path_acceleration",
        "later_penalty_tag": "correlated_price_expert_input",
    },
    "momentum_impulse_drift": {
        "dependency_family": "momentum",
        "correlation_group": "price_path_composite",
        "later_penalty_tag": "correlated_price_expert_input",
    },
    "momentum_exhaustion": {
        "dependency_family": "momentum",
        "correlation_group": "price_path_exhaustion",
        "later_penalty_tag": "correlated_price_expert_input",
    },
    "momentum_clock_regime_context": {
        "dependency_family": "data_quality",
        "correlation_group": "momentum_normalisation_context",
        "later_penalty_tag": "none",
    },
}


def _utc(value: datetime | str) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError("momentum timestamps must be timezone-aware")
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


def _direction(value: Decimal | None) -> str:
    if value is None:
        return "unknown"
    if value > 0:
        return "bullish"
    if value < 0:
        return "bearish"
    return "neutral"


def _completed_m1(
    rows: Sequence[Mapping[str, Any]],
    *,
    as_of: datetime,
    mode: str,
) -> list[Candle]:
    grouped = normalize_candles(
        rows,
        as_of=as_of,
        symbol="XAUUSD",
        mode=mode,
    )
    return [
        candle
        for candle in grouped["M1"]
        if candle.open_time_utc + timedelta(minutes=1) <= as_of
    ]


def _contiguity(candles: Sequence[Candle], required: int = 61) -> dict[str, Any]:
    sample = list(candles[-required:])
    if len(sample) < required:
        return {
            "state": "insufficient",
            "required_bars": required,
            "observed_bars": len(sample),
            "contiguous": False,
        }
    gaps = [
        left.open_time_utc.isoformat()
        for left, right in pairwise(sample)
        if right.open_time_utc - left.open_time_utc != timedelta(minutes=1)
    ]
    return {
        "state": "known" if not gaps else "gapped",
        "required_bars": required,
        "observed_bars": len(sample),
        "contiguous": not gaps,
        "gap_after_open_times_utc": gaps,
    }


def _return_bps(current: Decimal, previous: Decimal) -> Decimal | None:
    if previous == 0:
        return None
    return (current - previous) / previous * Decimal(10000)


def _horizon_returns(candles: Sequence[Candle]) -> dict[str, dict[str, Any]]:
    current = candles[-1].close
    result: dict[str, dict[str, Any]] = {}
    for minutes in MOMENTUM_HORIZONS_MINUTES:
        previous = candles[-(minutes + 1)].close
        value = _return_bps(current, previous)
        result[f"{minutes}m"] = {
            "minutes": minutes,
            "return_bps": _fmt(value),
            "direction": _direction(value),
        }
    return result


def _realized_vol_1m_bps(candles: Sequence[Candle], period: int = 60) -> Decimal | None:
    if len(candles) < period + 1:
        return None
    sample = candles[-(period + 1):]
    returns: list[Decimal] = []
    for left, right in pairwise(sample):
        if left.close == 0:
            return None
        returns.append((right.close / left.close - Decimal(1)) * Decimal(10000))
    mean = sum(returns, Decimal(0)) / Decimal(period)
    variance = sum(((item - mean) ** 2 for item in returns), Decimal(0)) / Decimal(period)
    return variance.sqrt()


def _normalised_returns(
    horizon_returns: Mapping[str, Mapping[str, Any]],
    *,
    rv_1m_bps: Decimal | None,
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for minutes in MOMENTUM_HORIZONS_MINUTES:
        key = f"{minutes}m"
        value = _decimal(horizon_returns[key].get("return_bps"))
        denominator = (
            rv_1m_bps * Decimal(minutes).sqrt()
            if rv_1m_bps not in {None, Decimal(0)}
            else None
        )
        units = (
            value / denominator
            if value is not None and denominator not in {None, Decimal(0)}
            else None
        )
        result[key] = {
            "return_bps": horizon_returns[key].get("return_bps"),
            "rv_expected_bps": _fmt(denominator),
            "rv_units": _fmt(units),
        }
    return result


def _path_quality(candles: Sequence[Candle], minutes: int = 30) -> dict[str, Any]:
    sample = list(candles[-(minutes + 1):])
    changes = [right.close - left.close for left, right in pairwise(sample)]
    net = sample[-1].close - sample[0].close
    path = sum((abs(item) for item in changes), Decimal(0))
    direction = _direction(net)
    matching = (
        sum(item > 0 for item in changes)
        if direction == "bullish"
        else sum(item < 0 for item in changes)
        if direction == "bearish"
        else sum(item == 0 for item in changes)
    )
    persistence = Decimal(matching) / Decimal(len(changes))
    efficiency = Decimal(0) if path == 0 else abs(net) / path
    return {
        "window_minutes": minutes,
        "direction": direction,
        "persistence_ratio": _fmt(persistence),
        "efficiency_ratio": _fmt(efficiency),
        "net_return_bps": _fmt(_return_bps(sample[-1].close, sample[0].close)),
    }


def _acceleration(candles: Sequence[Candle]) -> dict[str, Any]:
    current = candles[-1].close
    five_ago = candles[-6].close
    ten_ago = candles[-11].close
    recent = _return_bps(current, five_ago)
    previous = _return_bps(five_ago, ten_ago)
    recent_direction = _direction(recent)
    previous_direction = _direction(previous)
    if recent_direction in {"bullish", "bearish"} and previous_direction == recent_direction:
        ratio = (
            abs(recent) / abs(previous)
            if previous not in {None, Decimal(0)}
            else None
        )
        state = (
            "accelerating"
            if ratio is not None and ratio >= Decimal("1.25")
            else "decelerating"
            if ratio is not None and ratio <= Decimal("0.75")
            else "steady"
        )
    elif (
        recent_direction in {"bullish", "bearish"}
        and previous_direction in {"bullish", "bearish"}
        and recent_direction != previous_direction
    ):
        ratio = None
        state = "direction_reversal"
    else:
        ratio = None
        state = "neutral"
    return {
        "recent_5m_return_bps": _fmt(recent),
        "previous_5m_return_bps": _fmt(previous),
        "recent_direction": recent_direction,
        "previous_direction": previous_direction,
        "magnitude_ratio": _fmt(ratio),
        "state": state,
    }


def _single_bar_concentration(candles: Sequence[Candle], minutes: int = 15) -> dict[str, Any]:
    sample = list(candles[-(minutes + 1):])
    changes = [right.close - left.close for left, right in pairwise(sample)]
    absolute = [abs(item) for item in changes]
    total = sum(absolute, Decimal(0))
    largest = max(absolute, default=Decimal(0))
    concentration = Decimal(0) if total == 0 else largest / total
    largest_index = absolute.index(largest) if absolute else 0
    largest_change = changes[largest_index] if changes else Decimal(0)
    return {
        "window_minutes": minutes,
        "largest_step_share": _fmt(concentration),
        "largest_step_direction": _direction(largest_change),
        "largest_step_is_latest": bool(absolute and largest_index == len(absolute) - 1),
    }


def _evidence(
    *,
    evidence_id: str,
    path: str,
    observed_at: datetime,
    state: str,
    value: Any,
    mode: str,
    identities: Sequence[str],
) -> dict[str, Any]:
    return {
        "evidence_id": evidence_id,
        "source": "completed_m1_candles",
        "path": path,
        "observed_at_utc": observed_at,
        "state": state,
        "value": value,
        "provenance": {
            "mode": mode,
            "completed_bars_only": True,
            "future_values_used": False,
            "m1_identity_count": len(identities),
            "m1_first_identity": identities[0] if identities else None,
            "m1_last_identity": identities[-1] if identities else None,
        },
    }


def _unknown_calculator(
    *,
    calculator_id: str,
    evidence_ref: str,
    reason: str,
) -> dict[str, Any]:
    meta = MOMENTUM_DEPENDENCY_METADATA[calculator_id]
    return {
        "calculator_id": calculator_id,
        "version": f"{calculator_id}_v1",
        "role": "directional",
        "dependency_family": meta["dependency_family"],
        "state": "insufficient",
        "vote": "unknown",
        "evidence_refs": [evidence_ref],
        "observation": {
            "state": "insufficient",
            "correlation_group": meta["correlation_group"],
            "later_penalty_tag": meta["later_penalty_tag"],
        },
        "explanation": reason,
    }


def _directional_calculator(
    *,
    calculator_id: str,
    evidence_ref: str,
    vote: str,
    strength: Decimal | None,
    observation: Mapping[str, Any],
    explanation: str,
) -> dict[str, Any]:
    meta = MOMENTUM_DEPENDENCY_METADATA[calculator_id]
    item = {
        "calculator_id": calculator_id,
        "version": f"{calculator_id}_v1",
        "role": "directional",
        "dependency_family": meta["dependency_family"],
        "state": "known",
        "vote": vote,
        "evidence_refs": [evidence_ref],
        "observation": {
            **dict(observation),
            "correlation_group": meta["correlation_group"],
            "later_penalty_tag": meta["later_penalty_tag"],
        },
        "explanation": explanation,
    }
    if vote in {"bullish", "bearish"} and strength is not None:
        item["strength"] = _fmt(max(Decimal(0), min(Decimal(1), strength)))
    return item


def _multi_horizon(
    returns: Mapping[str, Mapping[str, Any]],
    normalised: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    directions = [str(returns[f"{minutes}m"]["direction"]) for minutes in MOMENTUM_HORIZONS_MINUTES]
    bullish = directions.count("bullish")
    bearish = directions.count("bearish")
    agreement = Decimal(max(bullish, bearish)) / Decimal(len(directions))
    direction = "bullish" if bullish > bearish else "bearish" if bearish > bullish else "neutral"
    norm15 = _decimal(normalised["15m"].get("rv_units"))
    magnitude = min(abs(norm15), Decimal(3)) / Decimal(3) if norm15 is not None else Decimal(0)
    if direction in {"bullish", "bearish"} and max(bullish, bearish) >= 4 and agreement >= Decimal("0.80"):
        vote = direction
        strength = agreement * Decimal("0.65") + magnitude * Decimal("0.35")
    else:
        vote = "neutral"
        strength = None
    return {
        "vote": vote,
        "strength": strength,
        "observation": {
            "directions": {f"{m}m": returns[f"{m}m"]["direction"] for m in MOMENTUM_HORIZONS_MINUTES},
            "bullish_horizons": bullish,
            "bearish_horizons": bearish,
            "agreement_ratio": _fmt(agreement),
            "fifteen_minute_rv_units": normalised["15m"].get("rv_units"),
        },
        "explanation": (
            f"Multi-horizon momentum is {vote}: {max(bullish, bearish)}/5 horizons "
            f"agree with 15m move={normalised['15m'].get('rv_units')} RV units."
        ),
    }


def _persistence_efficiency(path: Mapping[str, Any]) -> dict[str, Any]:
    persistence = _decimal(path.get("persistence_ratio")) or Decimal(0)
    efficiency = _decimal(path.get("efficiency_ratio")) or Decimal(0)
    direction = str(path.get("direction") or "unknown")
    if (
        direction in {"bullish", "bearish"}
        and persistence >= Decimal("0.65")
        and efficiency >= Decimal("0.45")
    ):
        vote = direction
        strength = persistence * Decimal("0.55") + efficiency * Decimal("0.45")
    else:
        vote = "neutral"
        strength = None
    return {
        "vote": vote,
        "strength": strength,
        "observation": dict(path),
        "explanation": (
            f"30m path quality is {vote}: persistence={path.get('persistence_ratio')}, "
            f"efficiency={path.get('efficiency_ratio')}."
        ),
    }


def _acceleration_vote(acceleration: Mapping[str, Any]) -> dict[str, Any]:
    direction = str(acceleration.get("recent_direction") or "unknown")
    state = str(acceleration.get("state") or "unknown")
    ratio = _decimal(acceleration.get("magnitude_ratio"))
    if direction in {"bullish", "bearish"} and state == "accelerating":
        vote = direction
        strength = min(Decimal(1), Decimal("0.55") + (ratio or Decimal(1)) / Decimal(5))
    elif direction in {"bullish", "bearish"} and state == "direction_reversal":
        vote = direction
        strength = Decimal("0.50")
    else:
        vote = "neutral"
        strength = None
    return {
        "vote": vote,
        "strength": strength,
        "observation": dict(acceleration),
        "explanation": (
            f"Momentum acceleration is {vote}: state={state}, "
            f"recent 5m={acceleration.get('recent_5m_return_bps')} bps."
        ),
    }


def _impulse_drift(
    returns: Mapping[str, Mapping[str, Any]],
    normalised: Mapping[str, Mapping[str, Any]],
    path: Mapping[str, Any],
    agreement: Mapping[str, Any],
) -> dict[str, Any]:
    persistence = _decimal(path.get("persistence_ratio")) or Decimal(0)
    efficiency = _decimal(path.get("efficiency_ratio")) or Decimal(0)
    norm5 = _decimal(normalised["5m"].get("rv_units"))
    norm15 = _decimal(normalised["15m"].get("rv_units"))
    norm60 = _decimal(normalised["60m"].get("rv_units"))
    agree = _decimal(agreement.get("agreement_ratio")) or Decimal(0)
    direction = str(path.get("direction") or "unknown")
    slow_directions = [returns[name]["direction"] for name in ("15m", "30m", "60m")]
    slow_agree = len(set(slow_directions)) == 1 and slow_directions[0] in {"bullish", "bearish"}

    impulse = (
        direction in {"bullish", "bearish"}
        and agree >= Decimal("0.80")
        and norm5 is not None
        and norm15 is not None
        and abs(norm5) >= Decimal("1.20")
        and abs(norm15) >= Decimal("1.00")
        and persistence >= Decimal("0.70")
        and efficiency >= Decimal("0.55")
    )
    drift = (
        direction in {"bullish", "bearish"}
        and slow_agree
        and norm60 is not None
        and abs(norm60) >= Decimal("0.80")
        and persistence >= Decimal("0.65")
        and efficiency >= Decimal("0.45")
    )
    if impulse:
        state = "continuation_impulse"
        vote = direction
        strength = Decimal("0.85")
    elif drift:
        state = "persistent_drift"
        vote = direction
        strength = Decimal("0.62")
    else:
        state = "noisy_or_unconfirmed"
        vote = "neutral"
        strength = None
    return {
        "vote": vote,
        "strength": strength,
        "observation": {
            "state": state,
            "direction": direction,
            "five_minute_rv_units": normalised["5m"].get("rv_units"),
            "fifteen_minute_rv_units": normalised["15m"].get("rv_units"),
            "sixty_minute_rv_units": normalised["60m"].get("rv_units"),
            "persistence_ratio": path.get("persistence_ratio"),
            "efficiency_ratio": path.get("efficiency_ratio"),
            "agreement_ratio": agreement.get("agreement_ratio"),
        },
        "explanation": (
            f"Momentum regime is {state}; vote={vote}. A large move alone is insufficient "
            "without persistence, efficiency and multi-horizon confirmation."
        ),
    }


def _exhaustion(
    concentration: Mapping[str, Any],
    returns: Mapping[str, Mapping[str, Any]],
    normalised: Mapping[str, Mapping[str, Any]],
    path: Mapping[str, Any],
) -> dict[str, Any]:
    share = _decimal(concentration.get("largest_step_share")) or Decimal(0)
    persistence = _decimal(path.get("persistence_ratio")) or Decimal(0)
    norm1 = _decimal(normalised["1m"].get("rv_units"))
    latest_direction = str(returns["1m"].get("direction") or "unknown")
    exhausted = (
        bool(concentration.get("largest_step_is_latest"))
        and latest_direction in {"bullish", "bearish"}
        and share >= Decimal("0.55")
        and norm1 is not None
        and abs(norm1) >= Decimal("2.00")
        and persistence < Decimal("0.60")
    )
    if exhausted:
        vote = "bearish" if latest_direction == "bullish" else "bullish"
        strength = min(Decimal("0.80"), Decimal("0.45") + share * Decimal("0.40"))
        state = "single_bar_exhaustion_risk"
    else:
        vote = "neutral"
        strength = None
        state = "no_exhaustion_signal"
    return {
        "vote": vote,
        "strength": strength,
        "observation": {
            "state": state,
            "latest_direction": latest_direction,
            "largest_step_share": concentration.get("largest_step_share"),
            "largest_step_is_latest": concentration.get("largest_step_is_latest"),
            "one_minute_rv_units": normalised["1m"].get("rv_units"),
            "persistence_ratio": path.get("persistence_ratio"),
        },
        "explanation": (
            f"Exhaustion state={state}; one-bar concentration="
            f"{concentration.get('largest_step_share')}."
        ),
    }


def _family_balanced_conclusion(
    calculators: Sequence[Mapping[str, Any]],
) -> tuple[str, str | None, dict[str, Any]]:
    scores: dict[str, dict[str, Decimal]] = {}
    for item in calculators:
        if item.get("role") != "directional" or item.get("state") != "known":
            continue
        family = str((item.get("observation") or {}).get("correlation_group") or item["calculator_id"])
        bucket = scores.setdefault(family, {"bullish": Decimal(0), "bearish": Decimal(0)})
        vote = str(item.get("vote"))
        strength = _decimal(item.get("strength")) or Decimal(0)
        if vote in {"bullish", "bearish"}:
            bucket[vote] = max(bucket[vote], strength)

    family_nets = {
        family: values["bullish"] - values["bearish"]
        for family, values in scores.items()
    }
    positive = sum(value > Decimal("0.10") for value in family_nets.values())
    negative = sum(value < Decimal("-0.10") for value in family_nets.values())
    capacity = sum((max(v["bullish"], v["bearish"]) for v in scores.values()), Decimal(0))
    net = sum(family_nets.values(), Decimal(0))

    if positive and negative:
        conclusion = "abstain"
        conviction = None
    elif capacity == 0:
        conclusion = "neutral"
        conviction = None
    else:
        dominance = abs(net) / capacity
        if net > 0 and positive >= 2 and dominance >= Decimal("0.40"):
            conclusion = "bullish"
            conviction = _fmt(dominance)
        elif net < 0 and negative >= 2 and dominance >= Decimal("0.40"):
            conclusion = "bearish"
            conviction = _fmt(dominance)
        else:
            conclusion = "neutral"
            conviction = None
    return conclusion, conviction, {
        "family_scores": {
            family: {key: _fmt(value) for key, value in values.items()}
            for family, values in scores.items()
        },
        "family_nets": {key: _fmt(value) for key, value in family_nets.items()},
        "positive_family_count": positive,
        "negative_family_count": negative,
        "net_family_score": _fmt(net),
        "family_capacity": _fmt(capacity),
        "correlation_groups_prevent_vote_count_inflation": True,
    }


def _subject_keys(packet: Mapping[str, Any]) -> list[str]:
    keys = [f"gate:{packet['gate_id']}"]
    keys.extend(
        f"subcalculator:{item['calculator_id']}"
        for item in packet["subcalculators"]
    )
    return keys


def build_momentum_impulse_expert(
    *,
    global_environment: Mapping[str, Any],
    price_math_packet: Mapping[str, Any],
    m1_candle_rows: Sequence[Mapping[str, Any]],
    trust_score_rows_by_subject: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Build one frozen Momentum / Impulse expert decision."""

    if not verify_price_expert_math_packet(price_math_packet):
        raise ValueError("price_math_packet must satisfy Build-4 verification")
    as_of = _utc(str(price_math_packet["as_of_utc"]))
    exact = global_environment.get("exact_facts")
    exact = exact if isinstance(exact, Mapping) else {}
    if _utc(str(exact.get("as_of_utc"))) != as_of:
        raise ValueError("momentum expert requires price math and environment at same as-of")

    mode = str(price_math_packet["mode"])
    candles = _completed_m1(m1_candle_rows, as_of=as_of, mode=mode)
    continuity = _contiguity(candles)
    usable = continuity["contiguous"]
    identities = [candle.identity for candle in candles[-61:]]
    observed = candles[-1].open_time_utc + timedelta(minutes=1) if candles else as_of

    if usable:
        sample = candles[-61:]
        returns = _horizon_returns(sample)
        rv = _realized_vol_1m_bps(sample)
        normalised = _normalised_returns(returns, rv_1m_bps=rv)
        path = _path_quality(sample)
        acceleration = _acceleration(sample)
        concentration = _single_bar_concentration(sample)
        multi = _multi_horizon(returns, normalised)
        persistence = _persistence_efficiency(path)
        accel_vote = _acceleration_vote(acceleration)
        impulse = _impulse_drift(returns, normalised, path, multi["observation"])
        exhaustion = _exhaustion(concentration, returns, normalised, path)
    else:
        returns = {f"{m}m": {"return_bps": None, "direction": "unknown"} for m in MOMENTUM_HORIZONS_MINUTES}
        normalised = {f"{m}m": {"rv_units": None} for m in MOMENTUM_HORIZONS_MINUTES}
        rv = None
        path = {"direction": "unknown", "persistence_ratio": None, "efficiency_ratio": None}
        acceleration = {"state": "unknown"}
        concentration = {"largest_step_share": None}
        multi = persistence = accel_vote = impulse = exhaustion = None

    evidence_inputs = [
        _evidence(
            evidence_id="momentum_multi_horizon_evidence",
            path="m1.completed.returns_1_5_15_30_60m",
            observed_at=observed,
            state="known" if usable else "unknown",
            value={"returns": returns, "normalised_returns": normalised} if usable else None,
            mode=mode,
            identities=identities,
        ),
        _evidence(
            evidence_id="momentum_path_quality_evidence",
            path="m1.completed.path_quality_30m",
            observed_at=observed,
            state="known" if usable else "unknown",
            value=path if usable else None,
            mode=mode,
            identities=identities,
        ),
        _evidence(
            evidence_id="momentum_acceleration_evidence",
            path="m1.completed.acceleration_5m_vs_prior_5m",
            observed_at=observed,
            state="known" if usable else "unknown",
            value=acceleration if usable else None,
            mode=mode,
            identities=identities,
        ),
        _evidence(
            evidence_id="momentum_exhaustion_evidence",
            path="m1.completed.single_bar_concentration_15m",
            observed_at=observed,
            state="known" if usable else "unknown",
            value=concentration if usable else None,
            mode=mode,
            identities=identities,
        ),
        _evidence(
            evidence_id="momentum_data_quality_evidence",
            path="m1.completed.contiguity",
            observed_at=as_of,
            state="known",
            value=continuity,
            mode=mode,
            identities=identities,
        ),
    ]

    if usable:
        calculators = [
            _directional_calculator(
                calculator_id="momentum_multi_horizon",
                evidence_ref="momentum_multi_horizon_evidence",
                vote=str(multi["vote"]),
                strength=multi["strength"],
                observation=multi["observation"],
                explanation=str(multi["explanation"]),
            ),
            _directional_calculator(
                calculator_id="momentum_persistence_efficiency",
                evidence_ref="momentum_path_quality_evidence",
                vote=str(persistence["vote"]),
                strength=persistence["strength"],
                observation=persistence["observation"],
                explanation=str(persistence["explanation"]),
            ),
            _directional_calculator(
                calculator_id="momentum_acceleration",
                evidence_ref="momentum_acceleration_evidence",
                vote=str(accel_vote["vote"]),
                strength=accel_vote["strength"],
                observation=accel_vote["observation"],
                explanation=str(accel_vote["explanation"]),
            ),
            _directional_calculator(
                calculator_id="momentum_impulse_drift",
                evidence_ref="momentum_multi_horizon_evidence",
                vote=str(impulse["vote"]),
                strength=impulse["strength"],
                observation=impulse["observation"],
                explanation=str(impulse["explanation"]),
            ),
            _directional_calculator(
                calculator_id="momentum_exhaustion",
                evidence_ref="momentum_exhaustion_evidence",
                vote=str(exhaustion["vote"]),
                strength=exhaustion["strength"],
                observation=exhaustion["observation"],
                explanation=str(exhaustion["explanation"]),
            ),
        ]
    else:
        calculators = [
            _unknown_calculator(
                calculator_id=calculator_id,
                evidence_ref={
                    "momentum_multi_horizon": "momentum_multi_horizon_evidence",
                    "momentum_persistence_efficiency": "momentum_path_quality_evidence",
                    "momentum_acceleration": "momentum_acceleration_evidence",
                    "momentum_impulse_drift": "momentum_multi_horizon_evidence",
                    "momentum_exhaustion": "momentum_exhaustion_evidence",
                }[calculator_id],
                reason="Momentum evidence requires 61 contiguous completed M1 candles.",
            )
            for calculator_id in (
                "momentum_multi_horizon",
                "momentum_persistence_efficiency",
                "momentum_acceleration",
                "momentum_impulse_drift",
                "momentum_exhaustion",
            )
        ]

    dimensions = global_environment["learning_dimensions"]
    context_meta = MOMENTUM_DEPENDENCY_METADATA["momentum_clock_regime_context"]
    calculators.append(
        {
            "calculator_id": "momentum_clock_regime_context",
            "version": "momentum_clock_regime_context_v1",
            "role": "context_only",
            "dependency_family": "data_quality",
            "state": "known",
            "vote": "context_only",
            "evidence_refs": ["momentum_data_quality_evidence"],
            "observation": {
                "volatility_state": dimensions["volatility_state"],
                "session": dimensions["session"],
                "session_phase": dimensions["session_phase"],
                "utc_clock_bucket_15m": dimensions["utc_clock_bucket_15m"],
                "five_minute_distribution_state": dimensions["five_minute_distribution_state"],
                "five_minute_range_state": dimensions["five_minute_range_state"],
                "realized_vol_1m_bps": _fmt(rv),
                "correlation_group": context_meta["correlation_group"],
                "later_penalty_tag": context_meta["later_penalty_tag"],
            },
            "explanation": (
                "Momentum reliability is conditioned by volatility regime, session phase "
                "and 15-minute UTC clock bucket rather than using one universal weight."
            ),
        }
    )

    if usable:
        conclusion, conviction, consensus_audit = _family_balanced_conclusion(calculators)
        exhausted = str(exhaustion["observation"]["state"]) == "single_bar_exhaustion_risk"
        latest_direction = str(exhaustion["observation"]["latest_direction"])
        persistence_ratio = _decimal(path.get("persistence_ratio")) or Decimal(0)
        if (
            exhausted
            and conclusion == latest_direction
            and persistence_ratio < Decimal("0.60")
        ):
            consensus_audit["single_large_candle_guard_applied"] = True
            consensus_audit["pre_guard_conclusion"] = conclusion
            conclusion = "abstain"
            conviction = None
        else:
            consensus_audit["single_large_candle_guard_applied"] = False
    else:
        conclusion, conviction = "unknown", None
        consensus_audit = {
            "single_large_candle_guard_applied": False,
            "correlation_groups_prevent_vote_count_inflation": True,
        }

    momentum_state = (
        str(impulse["observation"]["state"])
        if usable
        else "unknown"
    )
    mini_environment = {
        "session": dimensions["session"],
        "session_phase": dimensions["session_phase"],
        "utc_clock_bucket_15m": dimensions["utc_clock_bucket_15m"],
        "volatility_state": dimensions["volatility_state"],
        "five_minute_distribution_state": dimensions["five_minute_distribution_state"],
        "five_minute_range_state": dimensions["five_minute_range_state"],
        "momentum_state": momentum_state,
        "m5_direction": dimensions["m5_direction"],
        "m15_direction": dimensions["m15_direction"],
        "h1_direction": dimensions["h1_direction"],
    }

    explanation_parts = [
        {
            "text": (
                f"Momentum/impulse conclusion={conclusion}; state={momentum_state}; "
                f"1/5/15/30/60m directions="
                f"{'/'.join(str(returns[f'{m}m']['direction']) for m in MOMENTUM_HORIZONS_MINUTES)}."
            ),
            "source_refs": ["calc:momentum_multi_horizon", "calc:momentum_impulse_drift"],
        },
        {
            "text": (
                f"Path quality: persistence={path.get('persistence_ratio')}, "
                f"efficiency={path.get('efficiency_ratio')}; "
                f"acceleration={acceleration.get('state')}."
            ),
            "source_refs": [
                "calc:momentum_persistence_efficiency",
                "calc:momentum_acceleration",
            ],
        },
        {
            "text": (
                "Price-derived overlap is explicitly tagged for a later correlation penalty; "
                "complexity does not create extra influence."
            ),
            "source_refs": ["calc:momentum_clock_regime_context"],
        },
    ]

    contradictions = []
    directional_votes = [
        (item["calculator_id"], item["vote"])
        for item in calculators
        if item["role"] == "directional" and item["state"] == "known"
    ]
    if conclusion in {"bullish", "bearish"}:
        opposite = "bearish" if conclusion == "bullish" else "bullish"
        for calculator_id, vote in directional_votes:
            if vote == opposite:
                contradictions.append(
                    {
                        "text": f"{calculator_id} contradicts the {conclusion} momentum conclusion.",
                        "source_refs": [f"calc:{calculator_id}"],
                    }
                )

    packet = build_expert_gate_packet(
        gate_id=MOMENTUM_IMPULSE_GATE_ID,
        gate_version=MOMENTUM_IMPULSE_EXPERT_VERSION,
        gate_mode="directional",
        dependency_family="momentum",
        target_horizon_minutes=MOMENTUM_TARGET_HORIZON_MINUTES,
        as_of_utc=as_of,
        global_environment=global_environment,
        mini_environment=mini_environment,
        evidence_inputs=evidence_inputs,
        subcalculators=calculators,
        conclusion=conclusion,
        internal_conviction=conviction,
        explanation_parts=explanation_parts,
        contradictions=contradictions,
    )
    if not verify_expert_gate_packet(packet):
        raise ValueError("constructed momentum expert packet failed Build-2 verification")

    scopes = build_trust_scopes(
        packet=packet,
        reduced_contexts=MOMENTUM_TRUST_REDUCED_CONTEXTS,
    )
    rows_by_subject = trust_score_rows_by_subject or {}
    profiles = {
        key: select_conditional_trust(
            score_rows=rows_by_subject.get(key, ()),
            scopes=scopes,
        )
        for key in _subject_keys(packet)
    }
    trust_envelope = build_trust_envelope(
        packet=packet,
        profiles_by_subject=profiles,
    )

    return {
        "expert_version": MOMENTUM_IMPULSE_EXPERT_VERSION,
        "expert_packet": packet,
        "trust_scopes": scopes,
        "trust_envelope": trust_envelope,
        "continuity": continuity,
        "returns": returns,
        "normalised_returns": normalised,
        "dependency_metadata": MOMENTUM_DEPENDENCY_METADATA,
        "normalisation_context": {
            "volatility_state": dimensions["volatility_state"],
            "session": dimensions["session"],
            "session_phase": dimensions["session_phase"],
            "utc_clock_bucket_15m": dimensions["utc_clock_bucket_15m"],
            "realized_vol_1m_bps": _fmt(rv),
            "trust_conditioned_on_clock_and_regime": True,
        },
        "correlation_policy": {
            "price_expert_overlap_tagged": True,
            "later_correlation_penalty_required": True,
            "automatic_extra_weight_for_shared_price_inputs": False,
        },
        "consensus_audit": consensus_audit,
        "research_only": True,
        "future_values_used": False,
        "live_money_execution_allowed": False,
    }


__all__ = [
    "MOMENTUM_DEPENDENCY_METADATA",
    "MOMENTUM_HORIZONS_MINUTES",
    "MOMENTUM_IMPULSE_EXPERT_VERSION",
    "MOMENTUM_IMPULSE_GATE_ID",
    "MOMENTUM_TARGET_HORIZON_MINUTES",
    "MOMENTUM_TRUST_REDUCED_CONTEXTS",
    "build_momentum_impulse_expert",
]
