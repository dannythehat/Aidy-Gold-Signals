"""Build 21: Environment-Aware Gate Selector for AIDY Gold.

The selector consumes frozen Build-2 expert packets, Build-3 conditional-trust
envelopes and the Build-20 dependency engine. It chooses *attention*, not trade
direction. Current/future outcomes are not accepted as selector inputs.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from hashlib import sha256
from typing import Any

from aidy.gold_cycle_environment import verify_cycle_environment
from aidy.gold_environment_contract import (
    FORBIDDEN_HINDSIGHT_KEYS,
    assert_no_hindsight_fields,
)
from aidy.gold_evidence_dependency import verify_evidence_dependency_engine
from aidy.gold_expert_gate_contract import verify_expert_gate_packet

ENVIRONMENT_GATE_SELECTOR_VERSION = "aidy_gold_environment_gate_selector_v1"

HIGH_TRUST_MIN_SAMPLE_N = 20
HIGH_TRUST_MIN_SHRUNK_ACCURACY = Decimal("0.58")
HIGH_TRUST_MIN_AUTHORITY_SCORE = Decimal("0.30")
LOW_WEIGHT_OBSERVATION_FLOOR = Decimal("0.05")

_SCOPE_BACKOFF_MULTIPLIERS = {
    "mini_exact": Decimal("1.00"),
    "global_core": Decimal("0.80"),
    "gate_global": Decimal("0.70"),
    "neutral_prior": Decimal("0.50"),
}

_RECENCY_MULTIPLIERS = {
    "recently_stronger": Decimal("1.00"),
    "stable": Decimal("1.00"),
    "insufficient_recent": Decimal("0.90"),
    "recently_weaker": Decimal("0.65"),
}

_CALIBRATION_MIN_N = 20


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value: object) -> str:
    return sha256(_canonical_json(value).encode()).hexdigest()


def _utc(value: datetime | str, *, name: str) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return parsed.astimezone(UTC)


def _decimal(value: Any, *, name: str, default: Decimal | None = None) -> Decimal:
    if value is None and default is not None:
        return default
    if isinstance(value, bool):
        raise TypeError(f"{name} must be numeric")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not parsed.is_finite():
        raise ValueError(f"{name} must be finite")
    return parsed


def _fmt(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_EVEN), "f")


def _root_hindsight_key_check(value: Mapping[str, Any], *, path: str) -> None:
    for key in value:
        normalized = str(key).strip().lower()
        if normalized in FORBIDDEN_HINDSIGHT_KEYS:
            raise ValueError(f"hindsight field is forbidden at {path}.{key}")


def _gate_profile(trust_envelope: Mapping[str, Any], gate_id: str) -> dict[str, Any]:
    for subject in trust_envelope.get("subject_profiles") or []:
        if not isinstance(subject, Mapping):
            continue
        if (
            str(subject.get("subject_type") or "") == "gate"
            and str(subject.get("subject_id") or "") == gate_id
        ):
            profile = subject.get("profile")
            return dict(profile) if isinstance(profile, Mapping) else {}
    return {}


def build_gate_selector_input(expert_result: Mapping[str, Any]) -> dict[str, Any]:
    """Strip a full expert result down to the pre-outcome fields Build 21 may read."""

    _root_hindsight_key_check(expert_result, path="expert_result")
    packet = expert_result.get("expert_packet")
    trust = expert_result.get("trust_envelope")
    if not isinstance(packet, Mapping) or not verify_expert_gate_packet(packet):
        raise ValueError("Build 21 requires a verified expert packet")
    if not isinstance(trust, Mapping):
        raise TypeError("Build 21 requires the Build-3 trust envelope")

    assert_no_hindsight_fields(packet, path="expert_packet")
    assert_no_hindsight_fields(trust, path="trust_envelope")

    gate_id = str(packet["gate_id"])
    if str(trust.get("packet_digest") or "") != str(packet["packet_digest"]):
        raise ValueError("trust envelope packet digest mismatch")
    if str(trust.get("gate_id") or "") != gate_id:
        raise ValueError("trust envelope gate id mismatch")
    if trust.get("future_values_used") is not False:
        raise ValueError("trust envelope must be pre-outcome")

    profile = _gate_profile(trust, gate_id)
    known_subcalculator_n = sum(
        1
        for item in packet.get("subcalculators") or []
        if isinstance(item, Mapping) and str(item.get("state") or "") == "known"
    )
    gate_mode = str(packet["gate_mode"])
    conclusion = str(packet["conclusion"])
    available = known_subcalculator_n > 0 and conclusion != "unknown"

    result = {
        "selector_input_version": ENVIRONMENT_GATE_SELECTOR_VERSION,
        "gate_id": gate_id,
        "gate_version": str(packet["gate_version"]),
        "packet_digest": str(packet["packet_digest"]),
        "as_of_utc": str(packet["as_of_utc"]),
        "gate_mode": gate_mode,
        "conclusion": conclusion,
        "gate_scoreable": bool(packet["gate_scoreable"]),
        "known_subcalculator_n": known_subcalculator_n,
        "availability_state": "available" if available else "unavailable",
        "trust_profile": profile,
        "future_values_used": False,
        "current_outcome_visible": False,
    }
    result["selector_input_digest"] = _digest(result)
    return result


def _verify_selector_input(value: Mapping[str, Any]) -> bool:
    body = dict(value)
    supplied = str(body.pop("selector_input_digest", ""))
    return (
        bool(supplied)
        and supplied == _digest(body)
        and body.get("selector_input_version") == ENVIRONMENT_GATE_SELECTOR_VERSION
        and body.get("future_values_used") is False
        and body.get("current_outcome_visible") is False
    )


def _scope_backoff(profile: Mapping[str, Any]) -> dict[str, Any]:
    scope_type = str(profile.get("selected_scope_type") or "neutral_prior")
    if scope_type.startswith("mini_reduced_"):
        multiplier = Decimal("0.90")
        state = "reduced_context"
    else:
        multiplier = _SCOPE_BACKOFF_MULTIPLIERS.get(
            scope_type,
            Decimal("0.60"),
        )
        state = {
            "mini_exact": "exact_context",
            "global_core": "global_core_backoff",
            "gate_global": "gate_global_backoff",
            "neutral_prior": "neutral_prior",
        }.get(scope_type, "unknown_scope_backoff")
    return {
        "scope_type": scope_type,
        "context_label": scope_type,
        "state": state,
        "multiplier": _fmt(multiplier),
        "selected_scope_payload": dict(profile.get("selected_scope_payload") or {}),
    }


def _recency_adjustment(profile: Mapping[str, Any]) -> dict[str, Any]:
    state = str(profile.get("recent_state") or "insufficient_recent")
    multiplier = _RECENCY_MULTIPLIERS.get(state, Decimal("0.85"))
    return {
        "state": state,
        "multiplier": _fmt(multiplier),
        "recent_sample_n": int(profile.get("recent_sample_n") or 0),
        "recent_accuracy": profile.get("recent_accuracy"),
        "boost_above_one_allowed": False,
    }


def _calibration_adjustment(
    *,
    gate_id: str,
    calibration_rows: Sequence[Mapping[str, Any]],
    as_of: datetime,
) -> dict[str, Any]:
    eligible: list[tuple[datetime, Mapping[str, Any]]] = []
    excluded_future_n = 0
    for row in calibration_rows:
        _root_hindsight_key_check(row, path="calibration_row")
        assert_no_hindsight_fields(row, path="calibration_row")
        if str(row.get("gate_id") or "") != gate_id:
            continue
        observed_raw = row.get("observed_at_utc")
        if observed_raw is None:
            continue
        observed = _utc(str(observed_raw), name="calibration.observed_at_utc")
        if observed >= as_of:
            excluded_future_n += 1
            continue
        eligible.append((observed, row))
    eligible.sort(key=lambda item: item[0])

    if not eligible:
        return {
            "state": "unknown",
            "sample_n": 0,
            "mean_absolute_calibration_error": None,
            "multiplier": "0.850000",
            "excluded_current_or_future_n": excluded_future_n,
        }

    observed, row = eligible[-1]
    sample_n = int(row.get("sample_n") or 0)
    error = _decimal(
        row.get("mean_absolute_calibration_error"),
        name="mean_absolute_calibration_error",
    )
    if error < 0 or error > 1:
        raise ValueError("mean_absolute_calibration_error must be between 0 and 1")

    if sample_n < _CALIBRATION_MIN_N:
        state = "insufficient"
        multiplier = Decimal("0.80")
    elif error <= Decimal("0.05"):
        state = "strong"
        multiplier = Decimal("1.00")
    elif error <= Decimal("0.10"):
        state = "acceptable"
        multiplier = Decimal("0.90")
    elif error <= Decimal("0.20"):
        state = "weak"
        multiplier = Decimal("0.75")
    else:
        state = "poor"
        multiplier = Decimal("0.50")

    return {
        "state": state,
        "sample_n": sample_n,
        "mean_absolute_calibration_error": _fmt(error),
        "observed_at_utc": observed.isoformat(),
        "multiplier": _fmt(multiplier),
        "excluded_current_or_future_n": excluded_future_n,
    }


def _dependency_adjustment(
    *,
    gate_id: str,
    gate_mode: str,
    dependency_engine: Mapping[str, Any],
) -> dict[str, Any]:
    adjusted = dependency_engine.get("adjustments")
    adjusted = adjusted if isinstance(adjusted, Mapping) else {}
    signals = adjusted.get("adjusted_signals")
    signals = signals if isinstance(signals, list) else []

    rows = [
        item
        for item in signals
        if isinstance(item, Mapping)
        and str(item.get("gate_id") or "") == gate_id
        and item.get("eligible_for_directional_weight") is True
    ]
    if not rows:
        if gate_mode == "context_only":
            return {
                "state": "context_only_no_directional_penalty",
                "covered_signal_n": 0,
                "raw_weight_total": "0.000000",
                "effective_weight_total": "0.000000",
                "multiplier": "1.000000",
            }
        return {
            "state": "missing_directional_dependency_coverage",
            "covered_signal_n": 0,
            "raw_weight_total": "0.000000",
            "effective_weight_total": "0.000000",
            "multiplier": "0.750000",
        }

    raw_total = sum(
        (
            _decimal(item.get("raw_weight"), name="dependency.raw_weight")
            for item in rows
        ),
        Decimal(0),
    )
    effective_total = sum(
        (
            _decimal(item.get("effective_weight"), name="dependency.effective_weight")
            for item in rows
        ),
        Decimal(0),
    )
    multiplier = (
        Decimal(0)
        if raw_total <= 0
        else max(Decimal(0), min(Decimal(1), effective_total / raw_total))
    )
    return {
        "state": "known",
        "covered_signal_n": len(rows),
        "raw_weight_total": _fmt(raw_total),
        "effective_weight_total": _fmt(effective_total),
        "multiplier": _fmt(multiplier),
    }


def _reasons(
    *,
    classification: str,
    sample_n: int,
    shrunk_accuracy: Decimal,
    scope: Mapping[str, Any],
    calibration: Mapping[str, Any],
    recency: Mapping[str, Any],
    dependency: Mapping[str, Any],
) -> list[str]:
    reasons: list[str] = []
    if classification == "high_trust":
        reasons.append("large_enough_contextual_history")
        reasons.append("shrunk_reliability_above_high_trust_floor")
    elif classification == "reduced_trust":
        if sample_n < HIGH_TRUST_MIN_SAMPLE_N:
            reasons.append("sample_n_below_high_trust_minimum")
        if shrunk_accuracy < HIGH_TRUST_MIN_SHRUNK_ACCURACY:
            reasons.append("shrunk_reliability_below_high_trust_floor")

    if str(scope.get("state")) != "exact_context":
        reasons.append(f"scope_backoff:{scope.get('state')}")
    if str(calibration.get("state")) in {"unknown", "insufficient", "weak", "poor"}:
        reasons.append(f"calibration:{calibration.get('state')}")
    if str(recency.get("state")) in {"recently_weaker", "insufficient_recent"}:
        reasons.append(f"recency:{recency.get('state')}")
    if str(dependency.get("state")) != "known":
        reasons.append(f"dependency:{dependency.get('state')}")
    elif _decimal(dependency.get("multiplier"), name="dependency.multiplier") < 1:
        reasons.append("dependency_penalty_applied")
    return sorted(set(reasons))


def build_environment_aware_gate_selector(
    *,
    global_environment: Mapping[str, Any],
    expected_gate_ids: Sequence[str],
    gate_inputs: Sequence[Mapping[str, Any]],
    dependency_engine: Mapping[str, Any],
    calibration_rows: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Select gate attention from pre-outcome evidence only."""

    if not verify_cycle_environment(global_environment):
        raise ValueError("Build 21 requires a verified cycle environment")
    if not verify_evidence_dependency_engine(dependency_engine):
        raise ValueError("Build 21 requires the verified Build-20 dependency engine")

    as_of = _utc(
        str(global_environment["exact_facts"]["as_of_utc"]),
        name="environment.as_of_utc",
    )
    expected = sorted({str(item).strip() for item in expected_gate_ids if str(item).strip()})
    if not expected:
        raise ValueError("Build 21 requires at least one expected gate")

    by_gate: dict[str, Mapping[str, Any]] = {}
    for item in gate_inputs:
        assert_no_hindsight_fields(item, path="gate_selector_input")
        if not _verify_selector_input(item):
            raise ValueError("invalid Build-21 gate selector input")
        gate_id = str(item["gate_id"])
        if gate_id in by_gate:
            raise ValueError(f"duplicate gate selector input: {gate_id}")
        if _utc(str(item["as_of_utc"]), name="gate_input.as_of_utc") != as_of:
            raise ValueError("gate selector input must share the frozen environment as-of")
        by_gate[gate_id] = item

    all_rows: list[dict[str, Any]] = []
    high: list[dict[str, Any]] = []
    reduced: list[dict[str, Any]] = []
    unavailable: list[dict[str, Any]] = []

    for gate_id in expected:
        item = by_gate.get(gate_id)
        if item is None:
            row = {
                "gate_id": gate_id,
                "classification": "unavailable",
                "availability_state": "missing_gate_packet",
                "trust_score": "0.000000",
                "observation_weight": "0.000000",
                "directional_authority_weight": "0.000000",
                "sample_n": 0,
                "context_label": "unavailable",
                "reasons": ["missing_gate_packet"],
                "future_values_used": False,
            }
            all_rows.append(row)
            unavailable.append(row)
            continue

        if str(item.get("availability_state")) != "available":
            row = {
                "gate_id": gate_id,
                "classification": "unavailable",
                "availability_state": str(item.get("availability_state") or "unavailable"),
                "trust_score": "0.000000",
                "observation_weight": "0.000000",
                "directional_authority_weight": "0.000000",
                "sample_n": 0,
                "context_label": "unavailable",
                "reasons": ["gate_has_no_current_known_evidence"],
                "future_values_used": False,
            }
            all_rows.append(row)
            unavailable.append(row)
            continue

        profile = item.get("trust_profile")
        profile = profile if isinstance(profile, Mapping) else {}
        sample_n = int(profile.get("sample_n") or 0)
        shrunk_accuracy = _decimal(
            profile.get("shrunk_accuracy"),
            name="shrunk_accuracy",
            default=Decimal("0.5"),
        )
        sample_confidence = _decimal(
            profile.get("sample_confidence"),
            name="sample_confidence",
            default=Decimal(0),
        )
        if not (Decimal(0) <= shrunk_accuracy <= Decimal(1)):
            raise ValueError("shrunk_accuracy must be between 0 and 1")
        if not (Decimal(0) <= sample_confidence <= Decimal(1)):
            raise ValueError("sample_confidence must be between 0 and 1")

        scope = _scope_backoff(profile)
        calibration = _calibration_adjustment(
            gate_id=gate_id,
            calibration_rows=calibration_rows,
            as_of=as_of,
        )
        recency = _recency_adjustment(profile)
        dependency = _dependency_adjustment(
            gate_id=gate_id,
            gate_mode=str(item["gate_mode"]),
            dependency_engine=dependency_engine,
        )

        authority = (
            shrunk_accuracy
            * sample_confidence
            * _decimal(scope["multiplier"], name="scope.multiplier")
            * _decimal(calibration["multiplier"], name="calibration.multiplier")
            * _decimal(recency["multiplier"], name="recency.multiplier")
            * _decimal(dependency["multiplier"], name="dependency.multiplier")
        )
        authority = max(Decimal(0), min(Decimal(1), authority))

        high_trust = (
            sample_n >= HIGH_TRUST_MIN_SAMPLE_N
            and shrunk_accuracy >= HIGH_TRUST_MIN_SHRUNK_ACCURACY
            and authority >= HIGH_TRUST_MIN_AUTHORITY_SCORE
            and str(recency["state"]) != "recently_weaker"
            and str(calibration["state"]) != "poor"
        )
        classification = "high_trust" if high_trust else "reduced_trust"
        observation_weight = max(LOW_WEIGHT_OBSERVATION_FLOOR, authority)
        directional_authority = (
            authority
            if str(item["gate_mode"]) == "directional"
            and str(item["conclusion"]) in {"bullish", "bearish", "neutral"}
            else Decimal(0)
        )
        reasons = _reasons(
            classification=classification,
            sample_n=sample_n,
            shrunk_accuracy=shrunk_accuracy,
            scope=scope,
            calibration=calibration,
            recency=recency,
            dependency=dependency,
        )

        row = {
            "gate_id": gate_id,
            "gate_version": item["gate_version"],
            "packet_digest": item["packet_digest"],
            "classification": classification,
            "availability_state": "available",
            "gate_mode": item["gate_mode"],
            "current_conclusion": item["conclusion"],
            "trust_score": _fmt(authority),
            "observation_weight": _fmt(observation_weight),
            "directional_authority_weight": _fmt(directional_authority),
            "sample_n": sample_n,
            "shrunk_accuracy": _fmt(shrunk_accuracy),
            "sample_confidence": _fmt(sample_confidence),
            "context_label": scope["context_label"],
            "scope_backoff": scope,
            "calibration_adjustment": calibration,
            "recency_adjustment": recency,
            "dependency_adjustment": dependency,
            "uncertainty_state": str(profile.get("uncertainty_state") or "unknown"),
            "reasons": reasons,
            "weak_gate_remains_observable": classification == "reduced_trust",
            "future_values_used": False,
            "current_outcome_visible": False,
        }
        all_rows.append(row)
        if high_trust:
            high.append(row)
        else:
            reduced.append(row)

    body = {
        "selector_version": ENVIRONMENT_GATE_SELECTOR_VERSION,
        "as_of_utc": as_of.isoformat(),
        "environment_key": str(global_environment["environment_key"]),
        "expected_gate_count": len(expected),
        "selected_high_trust_gates": high,
        "reduced_trust_gates": reduced,
        "unavailable_gates": unavailable,
        "all_gates": all_rows,
        "selection_thresholds": {
            "high_trust_min_sample_n": HIGH_TRUST_MIN_SAMPLE_N,
            "high_trust_min_shrunk_accuracy": _fmt(HIGH_TRUST_MIN_SHRUNK_ACCURACY),
            "high_trust_min_authority_score": _fmt(HIGH_TRUST_MIN_AUTHORITY_SCORE),
            "low_weight_observation_floor": _fmt(LOW_WEIGHT_OBSERVATION_FLOOR),
            "threshold_role": "frozen_engineering_attention_policy_not_probability",
        },
        "selector_creates_direction": False,
        "selector_can_see_current_outcome": False,
        "future_values_used": False,
        "formal_forward_evidence_created": False,
        "live_money_execution_allowed": False,
    }
    body["selector_digest"] = _digest(body)
    return body


def verify_environment_aware_gate_selector(value: Mapping[str, Any]) -> bool:
    body = dict(value)
    supplied = str(body.pop("selector_digest", ""))
    return (
        bool(supplied)
        and supplied == _digest(body)
        and body.get("selector_version") == ENVIRONMENT_GATE_SELECTOR_VERSION
        and body.get("selector_creates_direction") is False
        and body.get("selector_can_see_current_outcome") is False
        and body.get("future_values_used") is False
        and body.get("live_money_execution_allowed") is False
    )


__all__ = [
    "ENVIRONMENT_GATE_SELECTOR_VERSION",
    "HIGH_TRUST_MIN_AUTHORITY_SCORE",
    "HIGH_TRUST_MIN_SAMPLE_N",
    "HIGH_TRUST_MIN_SHRUNK_ACCURACY",
    "LOW_WEIGHT_OBSERVATION_FLOOR",
    "build_environment_aware_gate_selector",
    "build_gate_selector_input",
    "verify_environment_aware_gate_selector",
]
