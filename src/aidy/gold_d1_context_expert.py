"""Build 9: D1 Context Expert for AIDY Gold.

D1 is context-only. It describes slow structural/macro location, never emits a
15-minute directional forecast, and abstains from usable context when daily
evidence is stale or partial.
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
    select_conditional_trust,
)
from aidy.gold_price_expert_math import verify_price_expert_math_packet

D1_CONTEXT_EXPERT_VERSION = "aidy_gold_d1_context_expert_v1"
D1_GATE_ID = "d1_context_expert"
D1_TARGET_HORIZON_MINUTES = 1440
D1_MAX_CONTEXT_AGE_HOURS = 72

D1_TRUST_REDUCED_CONTEXTS = (
    {
        "name": "daily_structure_location",
        "mini_dimensions": ["structure_regime", "trend_regime", "range_zone"],
        "global_dimensions": ["volatility_state"],
        "minimum_sample_n": 12,
    },
    {
        "name": "daily_structure",
        "mini_dimensions": ["structure_regime", "trend_regime"],
        "global_dimensions": [],
        "minimum_sample_n": 10,
    },
    {
        "name": "daily_location",
        "mini_dimensions": ["range_zone", "breakout_state"],
        "global_dimensions": ["volatility_state"],
        "minimum_sample_n": 8,
    },
)

D1_DEPENDENCY_METADATA = {
    "d1_trend_context": {
        "dependency_family": "structure",
        "correlation_group": "d1_trend_structure",
    },
    "d1_structure_context": {
        "dependency_family": "structure",
        "correlation_group": "d1_trend_structure",
    },
    "d1_location_context": {
        "dependency_family": "location",
        "correlation_group": "d1_location",
    },
    "d1_breakout_context": {
        "dependency_family": "location",
        "correlation_group": "d1_location",
    },
    "d1_data_quality": {
        "dependency_family": "data_quality",
        "correlation_group": "d1_data_quality",
    },
}


def _utc(value: datetime | str) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError("D1 context timestamps must be timezone-aware")
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


def _observed_at(d1_payload: Mapping[str, Any], as_of: datetime) -> datetime | None:
    latest = d1_payload.get("latest_completed_open_time_utc")
    if not latest:
        return None
    return _utc(str(latest)) + timedelta(days=1)


def _freshness(d1_payload: Mapping[str, Any], as_of: datetime) -> dict[str, Any]:
    completed_at = _observed_at(d1_payload, as_of)
    if completed_at is None:
        return {
            "state": "missing",
            "completed_at_utc": None,
            "age_hours": None,
            "max_age_hours": D1_MAX_CONTEXT_AGE_HOURS,
            "stale": True,
        }
    age = max(timedelta(0), as_of - completed_at)
    age_hours = Decimal(str(age.total_seconds())) / Decimal(3600)
    stale = age_hours > Decimal(D1_MAX_CONTEXT_AGE_HOURS)
    return {
        "state": "stale" if stale else "fresh",
        "completed_at_utc": completed_at.isoformat(),
        "age_hours": _fmt(age_hours),
        "max_age_hours": D1_MAX_CONTEXT_AGE_HOURS,
        "stale": stale,
    }


def _core_completeness(primitives: Mapping[str, Any]) -> dict[str, Any]:
    returns = primitives["multi_lookback_returns"]["values"]["8_bar"]
    regression = primitives["log_ols_slope"]["windows"]["8_bar"]
    persistence = primitives["close_step_persistence"]
    efficiency = primitives["path_efficiency"]
    range20 = primitives["range_position"]["windows"]["20_bar"]
    geometry = primitives["candle_geometry"]
    swings = primitives["confirmed_swing_sequence"]
    checks = {
        "eight_bar_return": returns.get("state") == "known",
        "eight_bar_regression": regression.get("state") == "known",
        "persistence": persistence.get("state") == "known",
        "path_efficiency": efficiency.get("state") == "known",
        "range_20": range20.get("state") == "known",
        "latest_candle": geometry.get("state") == "known",
        "confirmed_swings": swings.get("combined_structure") != "insufficient",
    }
    missing = sorted(key for key, value in checks.items() if not value)
    return {
        "complete": not missing,
        "checks": checks,
        "missing_components": missing,
    }


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
        "observation": {
            **dict(observation),
            "correlation_group": D1_DEPENDENCY_METADATA[calculator_id][
                "correlation_group"
            ],
        },
        "explanation": explanation,
    }


def _subject_keys(packet: Mapping[str, Any]) -> list[str]:
    keys = [f"gate:{packet['gate_id']}"]
    keys.extend(
        f"subcalculator:{item['calculator_id']}"
        for item in packet["subcalculators"]
    )
    return keys


def evaluate_d1_context_value(
    cases: Sequence[Mapping[str, Any]],
    *,
    minimum_sample_n: int = 20,
) -> dict[str, Any]:
    """Separate context utility from direct directional forecast performance."""

    context_cases = [
        case
        for case in cases
        if case.get("baseline_correct") in {0, 1}
        and case.get("with_context_correct") in {0, 1}
    ]
    sample_n = len(context_cases)
    baseline_correct = sum(int(case["baseline_correct"]) for case in context_cases)
    context_correct = sum(int(case["with_context_correct"]) for case in context_cases)
    baseline_accuracy = (
        Decimal(baseline_correct) / Decimal(sample_n) if sample_n else None
    )
    with_context_accuracy = (
        Decimal(context_correct) / Decimal(sample_n) if sample_n else None
    )
    context_delta = (
        with_context_accuracy - baseline_accuracy
        if baseline_accuracy is not None and with_context_accuracy is not None
        else None
    )

    direct_rows = [
        case for case in cases if case.get("direct_d1_direction_correct") in {0, 1}
    ]
    direct_n = len(direct_rows)
    direct_accuracy = (
        Decimal(sum(int(case["direct_d1_direction_correct"]) for case in direct_rows))
        / Decimal(direct_n)
        if direct_n
        else None
    )

    context_proven = (
        sample_n >= minimum_sample_n
        and context_delta is not None
        and context_delta > Decimal(0)
    )
    return {
        "sample_n": sample_n,
        "minimum_sample_n": minimum_sample_n,
        "baseline_accuracy": _fmt(baseline_accuracy),
        "with_context_accuracy": _fmt(with_context_accuracy),
        "context_accuracy_delta": _fmt(context_delta),
        "context_value_proven": context_proven,
        "direct_forecast_sample_n": direct_n,
        "direct_forecast_accuracy": _fmt(direct_accuracy),
        "direct_forecast_metric_separate": True,
        "direct_15m_authority": False,
        "default_next_15m_weight": "0",
        "research_only": True,
        "live_money_execution_allowed": False,
    }


def build_d1_context_expert(
    *,
    global_environment: Mapping[str, Any],
    price_math_packet: Mapping[str, Any],
    trust_score_rows_by_subject: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
) -> dict[str, Any]:
    if not verify_price_expert_math_packet(price_math_packet):
        raise ValueError("price_math_packet must satisfy Build-4 verification")

    as_of = _utc(str(price_math_packet["as_of_utc"]))
    exact = global_environment.get("exact_facts")
    exact = exact if isinstance(exact, Mapping) else {}
    if _utc(str(exact.get("as_of_utc"))) != as_of:
        raise ValueError("D1 context expert requires price math and environment at same as-of")

    d1 = price_math_packet["timeframes"]["D1"]
    primitives = d1["primitives"]
    freshness = _freshness(d1, as_of)
    completeness = _core_completeness(primitives) if d1.get("state") == "known" else {
        "complete": False,
        "checks": {},
        "missing_components": ["d1_payload"],
    }
    usable = (
        d1.get("state") == "known"
        and not freshness["stale"]
        and completeness["complete"]
    )
    context_decision = "use_context" if usable else "abstain"

    observed = _observed_at(d1, as_of) or as_of
    evidence_state = "known" if usable else "unknown"

    trend_value = {
        "return_8": primitives["multi_lookback_returns"]["values"]["8_bar"],
        "return_20": primitives["multi_lookback_returns"]["values"]["20_bar"],
        "regression_8": primitives["log_ols_slope"]["windows"]["8_bar"],
        "regression_20": primitives["log_ols_slope"]["windows"]["20_bar"],
        "persistence": primitives["close_step_persistence"],
        "efficiency": primitives["path_efficiency"],
    }
    structure_value = {
        "swings": primitives["confirmed_swing_sequence"],
        "structure_break": primitives["structure_break"],
    }
    location_value = primitives["range_position"]
    breakout_value = primitives["breakout_lifecycle"]
    quality_value = {
        "freshness": freshness,
        "completeness": completeness,
        "bars_available": d1.get("bars_available"),
        "contradictions": primitives["contradiction_flags"],
    }

    evidence_inputs = [
        _evidence(
            evidence_id="d1_trend_context_evidence",
            path="timeframes.D1.primitives.trend_path",
            observed_at=observed,
            state=evidence_state,
            value=trend_value if usable else None,
            price_math_packet=price_math_packet,
        ),
        _evidence(
            evidence_id="d1_structure_context_evidence",
            path="timeframes.D1.primitives.swing_structure",
            observed_at=observed,
            state=evidence_state,
            value=structure_value if usable else None,
            price_math_packet=price_math_packet,
        ),
        _evidence(
            evidence_id="d1_location_context_evidence",
            path="timeframes.D1.primitives.range_position",
            observed_at=observed,
            state=evidence_state,
            value=location_value if usable else None,
            price_math_packet=price_math_packet,
        ),
        _evidence(
            evidence_id="d1_breakout_context_evidence",
            path="timeframes.D1.primitives.breakout_lifecycle",
            observed_at=observed,
            state=evidence_state,
            value=breakout_value if usable else None,
            price_math_packet=price_math_packet,
        ),
        _evidence(
            evidence_id="d1_data_quality_evidence",
            path="timeframes.D1.data_quality",
            observed_at=as_of,
            state="known",
            value=quality_value,
            price_math_packet=price_math_packet,
        ),
    ]

    range20 = primitives["range_position"]["windows"]["20_bar"]
    structure = primitives["confirmed_swing_sequence"].get("combined_structure") or "unknown"
    high_state = primitives["breakout_lifecycle"]["high_side"].get("state") or "unknown"
    low_state = primitives["breakout_lifecycle"]["low_side"].get("state") or "unknown"
    regression = primitives["log_ols_slope"]["windows"]["8_bar"]
    trend_context = {
        "direction": regression.get("direction"),
        "r_squared": regression.get("r_squared"),
        "slope_log_bps_per_bar": regression.get("slope_log_bps_per_bar"),
        "persistence_ratio": primitives["close_step_persistence"].get(
            "directional_persistence_ratio"
        ),
        "path_efficiency": primitives["path_efficiency"].get("efficiency_ratio"),
    }

    calculators = [
        _context_calculator(
            calculator_id="d1_trend_context",
            dependency_family="structure",
            evidence_ref="d1_trend_context_evidence",
            known=usable,
            observation=trend_context if usable else {"state": "abstain"},
            explanation=(
                "D1 trend context is available from completed daily bars."
                if usable
                else "D1 trend context abstains because daily evidence is stale or partial."
            ),
        ),
        _context_calculator(
            calculator_id="d1_structure_context",
            dependency_family="structure",
            evidence_ref="d1_structure_context_evidence",
            known=usable,
            observation={"combined_structure": structure} if usable else {"state": "abstain"},
            explanation=(
                f"D1 structure context is {structure}."
                if usable
                else "D1 structure context abstains because daily evidence is stale or partial."
            ),
        ),
        _context_calculator(
            calculator_id="d1_location_context",
            dependency_family="location",
            evidence_ref="d1_location_context_evidence",
            known=usable,
            observation={
                "range_20_position": range20.get("position"),
                "range_zone": _range_bucket(range20.get("position")),
            } if usable else {"state": "abstain"},
            explanation=(
                "D1 macro-location context is available."
                if usable
                else "D1 macro-location context abstains because daily evidence is stale or partial."
            ),
        ),
        _context_calculator(
            calculator_id="d1_breakout_context",
            dependency_family="location",
            evidence_ref="d1_breakout_context_evidence",
            known=usable,
            observation={
                "high_state": high_state,
                "low_state": low_state,
            } if usable else {"state": "abstain"},
            explanation=(
                f"D1 breakout context is high={high_state}, low={low_state}."
                if usable
                else "D1 breakout context abstains because daily evidence is stale or partial."
            ),
        ),
        _context_calculator(
            calculator_id="d1_data_quality",
            dependency_family="data_quality",
            evidence_ref="d1_data_quality_evidence",
            known=True,
            observation={
                "context_decision": context_decision,
                "freshness": freshness,
                "completeness": completeness,
            },
            explanation=(
                "D1 context evidence is fresh and complete."
                if usable
                else "D1 context is withheld because freshness/completeness requirements failed."
            ),
        ),
    ]

    dimensions = global_environment["learning_dimensions"]
    mini = {
        "timeframe": "D1",
        "session": dimensions["session"],
        "volatility_state": dimensions["volatility_state"],
        "structure_regime": structure if usable else "abstain",
        "trend_regime": (
            f"{regression.get('direction')}|r2:{regression.get('r_squared')}"
            if usable
            else "abstain"
        ),
        "range_zone": _range_bucket(range20.get("position")) if usable else "abstain",
        "breakout_state": (
            f"high:{high_state}|low:{low_state}" if usable else "abstain"
        ),
        "freshness_state": freshness["state"],
        "completeness_state": "complete" if completeness["complete"] else "partial",
    }

    explanation_parts = [
        {
            "text": (
                f"D1 context decision={context_decision}; freshness={freshness['state']}; "
                f"completeness={'complete' if completeness['complete'] else 'partial'}."
            ),
            "source_refs": ["calc:d1_data_quality"],
        },
        {
            "text": (
                "D1 provides slow structural and macro-location context only. "
                "It does not emit or force a 15-minute direction."
            ),
            "source_refs": ["calc:d1_trend_context", "calc:d1_location_context"],
        },
    ]

    packet = build_expert_gate_packet(
        gate_id=D1_GATE_ID,
        gate_version=D1_CONTEXT_EXPERT_VERSION,
        gate_mode="context_only",
        dependency_family="structure",
        target_horizon_minutes=D1_TARGET_HORIZON_MINUTES,
        as_of_utc=as_of,
        global_environment=global_environment,
        mini_environment=mini,
        evidence_inputs=evidence_inputs,
        subcalculators=calculators,
        conclusion="context_only",
        internal_conviction=None,
        explanation_parts=explanation_parts,
        contradictions=(),
    )
    if not verify_expert_gate_packet(packet):
        raise ValueError("constructed D1 context packet failed Build-2 verification")

    scopes = build_trust_scopes(
        packet=packet,
        reduced_contexts=D1_TRUST_REDUCED_CONTEXTS,
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
        "expert_version": D1_CONTEXT_EXPERT_VERSION,
        "expert_packet": packet,
        "context_decision": context_decision,
        "context_usable": usable,
        "freshness": freshness,
        "completeness": completeness,
        "trust_scopes": scopes,
        "trust_envelope": trust_envelope,
        "dependency_metadata": D1_DEPENDENCY_METADATA,
        "forecast_influence_policy": {
            "context_only": True,
            "direct_15m_direction_allowed": False,
            "direct_next_15m_authority": False,
            "default_next_15m_weight": "0",
            "context_value_must_be_tested_separately": True,
            "direct_forecast_value_is_separate_metric": True,
        },
        "price_math_packet_digest": price_math_packet["packet_digest"],
        "research_only": True,
        "future_values_used": False,
        "live_money_execution_allowed": False,
    }


__all__ = [
    "D1_CONTEXT_EXPERT_VERSION",
    "D1_DEPENDENCY_METADATA",
    "D1_GATE_ID",
    "D1_MAX_CONTEXT_AGE_HOURS",
    "D1_TARGET_HORIZON_MINUTES",
    "D1_TRUST_REDUCED_CONTEXTS",
    "build_d1_context_expert",
    "evaluate_d1_context_value",
]
