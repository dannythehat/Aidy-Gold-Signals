"""Build 3: environment-conditional trust and scoring for AIDY expert gates.

This module is deliberately independent from the legacy marker-weighting path. It provides
the score/reliability foundation that future expert gates will use after their immutable
Build-2 packet has been frozen.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from hashlib import sha256
from typing import Any

from aidy.gold_expert_gate_contract import verify_expert_gate_packet

EXPERT_TRUST_ENGINE_VERSION = "aidy_gold_expert_conditional_trust_v3"
TRUST_PRIOR_STRENGTH = 20
RECENT_WINDOW_SIZE = 20
LARGE_MOVE_BPS = Decimal("5")

_DEFAULT_MINIMUMS = {
    "mini_exact": 12,
    "global_core": 6,
    "gate_global": 1,
}


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value: object) -> str:
    return sha256(_canonical_json(value).encode()).hexdigest()


def _utc(value: datetime | str) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError("trust-engine timestamps must be timezone-aware")
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
    return format(value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_EVEN), "f")


def _scope_key(scope_type: str, payload: Mapping[str, Any]) -> str:
    return f"{scope_type}_" + _digest(payload)[:28]


def _wilson_interval(correct_n: int, sample_n: int) -> tuple[str | None, str | None]:
    if sample_n <= 0:
        return None, None
    z = 1.959963984540054
    p = correct_n / sample_n
    denominator = 1 + (z * z / sample_n)
    centre = (p + z * z / (2 * sample_n)) / denominator
    margin = (
        z
        * math.sqrt(
            (p * (1 - p) / sample_n) + (z * z / (4 * sample_n * sample_n))
        )
        / denominator
    )
    return (
        _fmt(Decimal(str(max(0.0, centre - margin)))),
        _fmt(Decimal(str(min(1.0, centre + margin)))),
    )


def score_directional_outcome(
    *,
    vote: str,
    realised_direction: str,
    realised_return_bps: Any,
    scoreable: bool,
) -> dict[str, Any]:
    """Score one frozen directional opinion using the owner's +/-2/+/-1/0 rule."""

    vote = str(vote or "").strip().lower()
    realised_direction = str(realised_direction or "").strip().lower()
    move = _decimal(realised_return_bps)

    if not scoreable or vote not in {"bullish", "bearish", "neutral"}:
        return {
            "score": 0,
            "correct": None,
            "impact_class": "unscoreable",
            "realised_return_bps": _fmt(move),
        }
    if realised_direction not in {"bullish", "bearish", "neutral"}:
        return {
            "score": 0,
            "correct": None,
            "impact_class": "outcome_unknown",
            "realised_return_bps": _fmt(move),
        }

    impact = 2 if abs(move or Decimal(0)) >= LARGE_MOVE_BPS else 1
    correct = int(vote == realised_direction)
    return {
        "score": impact if correct else -impact,
        "correct": correct,
        "impact_class": "large" if impact == 2 else "normal",
        "realised_return_bps": _fmt(move),
    }


def build_trust_scopes(
    *,
    packet: Mapping[str, Any],
    reduced_contexts: Sequence[Mapping[str, Any]] = (),
) -> list[dict[str, Any]]:
    """Build exact -> reduced -> global-core -> gate-global lookup scopes.

    Reduced scopes are gate-specific policy supplied by each future expert build.
    The engine never guesses which mini-environment dimensions matter.
    """

    if not verify_expert_gate_packet(packet):
        raise ValueError("packet must satisfy Expert Gate Contract v1")

    gate_id = str(packet["gate_id"])
    gate_version = str(packet["gate_version"])
    mini = packet["mini_environment"]["dimensions"]
    global_dimensions = packet["global_environment_dimensions"]
    global_ref = packet["global_environment_ref"]

    scopes: list[dict[str, Any]] = []
    exact_payload = {
        "gate_id": gate_id,
        "gate_version": gate_version,
        "mini_environment": dict(mini),
    }
    scopes.append(
        {
            "scope_type": "mini_exact",
            "scope_key": _scope_key("mini_exact", exact_payload),
            "payload": exact_payload,
            "minimum_sample_n": _DEFAULT_MINIMUMS["mini_exact"],
            "specificity_rank": 0,
        }
    )

    seen_names: set[str] = set()
    for rank, spec in enumerate(reduced_contexts, start=1):
        name = str(spec.get("name") or "").strip().lower()
        if not name or name in seen_names:
            raise ValueError("reduced context names must be unique and non-empty")
        seen_names.add(name)
        mini_names = [str(item) for item in (spec.get("mini_dimensions") or [])]
        global_names = [str(item) for item in (spec.get("global_dimensions") or [])]
        if not mini_names and not global_names:
            raise ValueError(f"reduced context {name} has no dimensions")
        missing_mini = [field for field in mini_names if field not in mini]
        missing_global = [field for field in global_names if field not in global_dimensions]
        if missing_mini or missing_global:
            raise ValueError(
                f"reduced context {name} references missing dimensions: "
                f"mini={missing_mini} global={missing_global}"
            )
        minimum = int(spec.get("minimum_sample_n") or 8)
        if minimum < 2:
            raise ValueError("reduced context minimum_sample_n must be at least 2")
        payload = {
            "gate_id": gate_id,
            "gate_version": gate_version,
            "context_name": name,
            "mini": {field: mini[field] for field in mini_names},
            "global": {field: global_dimensions[field] for field in global_names},
        }
        scope_type = f"mini_reduced_{name}"
        scopes.append(
            {
                "scope_type": scope_type,
                "scope_key": _scope_key(scope_type, payload),
                "payload": payload,
                "minimum_sample_n": minimum,
                "specificity_rank": rank,
            }
        )

    core_payload = {
        "gate_id": gate_id,
        "gate_version": gate_version,
        "environment_key": global_ref["environment_key"],
    }
    scopes.append(
        {
            "scope_type": "global_core",
            "scope_key": _scope_key("global_core", core_payload),
            "payload": core_payload,
            "minimum_sample_n": _DEFAULT_MINIMUMS["global_core"],
            "specificity_rank": len(scopes),
        }
    )

    gate_payload = {"gate_id": gate_id, "gate_version": gate_version}
    scopes.append(
        {
            "scope_type": "gate_global",
            "scope_key": _scope_key("gate_global", gate_payload),
            "payload": gate_payload,
            "minimum_sample_n": _DEFAULT_MINIMUMS["gate_global"],
            "specificity_rank": len(scopes),
        }
    )
    return scopes


def _subject_specs(packet: Mapping[str, Any]) -> list[dict[str, Any]]:
    subjects = [
        {
            "subject_type": "gate",
            "subject_id": str(packet["gate_id"]),
            "subject_version": str(packet["gate_version"]),
            "vote": str(packet["conclusion"]),
            "scoreable": bool(packet["gate_scoreable"]),
        }
    ]
    for calculator in packet["subcalculators"]:
        subjects.append(
            {
                "subject_type": "subcalculator",
                "subject_id": str(calculator["calculator_id"]),
                "subject_version": str(calculator["version"]),
                "vote": str(calculator["vote"]),
                "scoreable": bool(calculator["scoreable"]),
            }
        )
    return subjects


def score_expert_packet(
    *,
    packet: Mapping[str, Any],
    scopes: Sequence[Mapping[str, Any]],
    resolved_at_utc: datetime | str,
    realised_direction: str,
    realised_return_bps: Any,
) -> list[dict[str, Any]]:
    """Resolve gate and sub-calculator outcomes without mutating the frozen packet."""

    if not verify_expert_gate_packet(packet):
        raise ValueError("packet must satisfy Expert Gate Contract v1")

    resolved = _utc(resolved_at_utc)
    as_of = _utc(str(packet["as_of_utc"]))
    if resolved <= as_of:
        raise ValueError("outcome must resolve after the frozen gate as-of timestamp")

    scope_keys = [str(scope.get("scope_key") or "") for scope in scopes]
    if not scope_keys or any(not key for key in scope_keys):
        raise ValueError("scopes must contain non-empty scope keys")
    if len(scope_keys) != len(set(scope_keys)):
        raise ValueError("scope keys must be unique")

    results: list[dict[str, Any]] = []
    for subject in _subject_specs(packet):
        scored = score_directional_outcome(
            vote=subject["vote"],
            realised_direction=realised_direction,
            realised_return_bps=realised_return_bps,
            scoreable=subject["scoreable"],
        )
        identity = {
            "packet_digest": packet["packet_digest"],
            "subject_type": subject["subject_type"],
            "subject_id": subject["subject_id"],
            "subject_version": subject["subject_version"],
        }
        body = {
            "result_id": "expert_result_" + _digest(identity)[:28],
            **identity,
            "gate_id": str(packet["gate_id"]),
            "gate_version": str(packet["gate_version"]),
            "target_horizon_minutes": int(packet["target_horizon_minutes"]),
            "resolved_at_utc": resolved.isoformat(),
            "realised_direction": str(realised_direction),
            "score": scored["score"],
            "correct": scored["correct"],
            "impact_class": scored["impact_class"],
            "realised_return_bps": scored["realised_return_bps"],
            "scope_keys": scope_keys,
            "research_only": True,
            "live_money_execution_allowed": False,
        }
        body["result_digest"] = _digest(body)
        results.append(body)
    return results


def aggregate_context_rows(
    *,
    results: Sequence[Mapping[str, Any]],
    scopes: Sequence[Mapping[str, Any]],
    subject_type: str,
    subject_id: str,
    subject_version: str,
    as_of_utc: datetime | str,
    recent_window: int = RECENT_WINDOW_SIZE,
) -> list[dict[str, Any]]:
    """Aggregate only history already resolved before the current decision time."""

    as_of = _utc(as_of_utc)
    if recent_window <= 0:
        raise ValueError("recent_window must be positive")

    scoped_results = []
    excluded_future_n = 0
    for result in results:
        if (
            str(result.get("subject_type") or "") != subject_type
            or str(result.get("subject_id") or "") != subject_id
            or str(result.get("subject_version") or "") != subject_version
        ):
            continue
        resolved = _utc(str(result.get("resolved_at_utc")))
        if resolved >= as_of:
            excluded_future_n += 1
            continue
        scoped_results.append((resolved, result))
    scoped_results.sort(key=lambda item: item[0])

    rows: list[dict[str, Any]] = []
    for scope in scopes:
        scope_key = str(scope.get("scope_key") or "")
        eligible = [
            (resolved, result)
            for resolved, result in scoped_results
            if scope_key in (result.get("scope_keys") or [])
            and result.get("correct") in {0, 1}
        ]
        recent = eligible[-recent_window:]
        sample_n = len(eligible)
        correct_n = sum(int(result["correct"]) for _, result in eligible)
        net_score = sum(int(result.get("score") or 0) for _, result in eligible)
        recent_sample_n = len(recent)
        recent_correct_n = sum(int(result["correct"]) for _, result in recent)
        recent_net_score = sum(int(result.get("score") or 0) for _, result in recent)
        lower, upper = _wilson_interval(correct_n, sample_n)
        rows.append(
            {
                "scope_key": scope_key,
                "scope_type": str(scope.get("scope_type") or ""),
                "sample_n": sample_n,
                "correct_n": correct_n,
                "incorrect_n": sample_n - correct_n,
                "net_score": net_score,
                "score_mean": (
                    _fmt(Decimal(net_score) / Decimal(sample_n))
                    if sample_n
                    else None
                ),
                "accuracy": (
                    _fmt(Decimal(correct_n) / Decimal(sample_n))
                    if sample_n
                    else None
                ),
                "wilson_95_low": lower,
                "wilson_95_high": upper,
                "recent_window": recent_window,
                "recent_sample_n": recent_sample_n,
                "recent_correct_n": recent_correct_n,
                "recent_net_score": recent_net_score,
                "recent_accuracy": (
                    _fmt(Decimal(recent_correct_n) / Decimal(recent_sample_n))
                    if recent_sample_n
                    else None
                ),
                "first_resolved_at_utc": (
                    eligible[0][0].isoformat() if eligible else None
                ),
                "last_resolved_at_utc": (
                    eligible[-1][0].isoformat() if eligible else None
                ),
                "excluded_current_or_future_n": excluded_future_n,
            }
        )
    return rows


def _shrink_row(
    *,
    row: Mapping[str, Any],
    prior_accuracy: Decimal,
    prior_score_mean: Decimal,
    prior_strength: int,
) -> dict[str, Any]:
    sample_n = int(row.get("sample_n") or 0)
    correct_n = int(row.get("correct_n") or 0)
    net_score = int(row.get("net_score") or 0)
    denominator = Decimal(sample_n + prior_strength)

    shrunk_accuracy = (
        (Decimal(correct_n) + prior_accuracy * Decimal(prior_strength)) / denominator
        if denominator
        else prior_accuracy
    )
    shrunk_score_mean = (
        (Decimal(net_score) + prior_score_mean * Decimal(prior_strength)) / denominator
        if denominator
        else prior_score_mean
    )
    evidence_weight = (
        Decimal(sample_n) / denominator if denominator else Decimal(0)
    )
    result = dict(row)
    result.update(
        {
            "prior_accuracy": _fmt(prior_accuracy),
            "prior_score_mean": _fmt(prior_score_mean),
            "prior_strength": prior_strength,
            "shrunk_accuracy": _fmt(shrunk_accuracy),
            "shrunk_score_mean": _fmt(shrunk_score_mean),
            "sample_confidence": _fmt(evidence_weight),
        }
    )
    return result


def select_conditional_trust(
    *,
    score_rows: Sequence[Mapping[str, Any]],
    scopes: Sequence[Mapping[str, Any]],
    prior_strength: int = TRUST_PRIOR_STRENGTH,
) -> dict[str, Any]:
    """Select the most specific sufficiently-sampled context after hierarchical shrinkage."""

    if prior_strength <= 0:
        raise ValueError("prior_strength must be positive")

    rows_by_key = {str(row.get("scope_key") or ""): row for row in score_rows}
    ordered_scopes = list(scopes)
    if not ordered_scopes:
        raise ValueError("at least one trust scope is required")

    shrunk_by_key: dict[str, dict[str, Any]] = {}
    parent_accuracy = Decimal("0.5")
    parent_score_mean = Decimal(0)

    # Work broad -> specific so each child shrinks toward the broader learned context.
    for scope in reversed(ordered_scopes):
        key = str(scope.get("scope_key") or "")
        row = rows_by_key.get(key) or {
            "scope_key": key,
            "scope_type": scope.get("scope_type"),
            "sample_n": 0,
            "correct_n": 0,
            "incorrect_n": 0,
            "net_score": 0,
            "score_mean": None,
            "accuracy": None,
            "recent_sample_n": 0,
            "recent_correct_n": 0,
            "recent_net_score": 0,
            "recent_accuracy": None,
        }
        shrunk = _shrink_row(
            row=row,
            prior_accuracy=parent_accuracy,
            prior_score_mean=parent_score_mean,
            prior_strength=prior_strength,
        )
        shrunk_by_key[key] = shrunk
        parent_accuracy = Decimal(str(shrunk["shrunk_accuracy"]))
        parent_score_mean = Decimal(str(shrunk["shrunk_score_mean"]))

    selected_scope: Mapping[str, Any] | None = None
    selected_row: Mapping[str, Any] | None = None
    fallback_path: list[dict[str, Any]] = []
    for scope in ordered_scopes:
        key = str(scope.get("scope_key") or "")
        row = shrunk_by_key[key]
        minimum = int(scope.get("minimum_sample_n") or 1)
        meets = int(row.get("sample_n") or 0) >= minimum
        fallback_path.append(
            {
                "scope_type": scope.get("scope_type"),
                "scope_key": key,
                "sample_n": int(row.get("sample_n") or 0),
                "minimum_sample_n": minimum,
                "meets_minimum": meets,
            }
        )
        if meets:
            selected_scope = scope
            selected_row = row
            break

    if selected_scope is None or selected_row is None:
        return {
            "engine_version": EXPERT_TRUST_ENGINE_VERSION,
            "selected_scope_type": "neutral_prior",
            "selected_scope_key": None,
            "selected_scope_payload": {},
            "sample_n": 0,
            "raw_accuracy": None,
            "shrunk_accuracy": "0.500000",
            "raw_score_mean": None,
            "shrunk_score_mean": "0.000000",
            "sample_confidence": "0.000000",
            "uncertainty_state": "no_qualified_history",
            "recent_state": "insufficient_recent",
            "fallback_path": fallback_path,
        }

    sample_n = int(selected_row.get("sample_n") or 0)
    recent_n = int(selected_row.get("recent_sample_n") or 0)
    raw_accuracy = _decimal(selected_row.get("accuracy"))
    recent_accuracy = _decimal(selected_row.get("recent_accuracy"))
    recent_state = "insufficient_recent"
    if recent_n >= 8 and raw_accuracy is not None and recent_accuracy is not None:
        delta = recent_accuracy - raw_accuracy
        if delta >= Decimal("0.15"):
            recent_state = "recently_stronger"
        elif delta <= Decimal("-0.15"):
            recent_state = "recently_weaker"
        else:
            recent_state = "stable"

    confidence = Decimal(str(selected_row["sample_confidence"]))
    if sample_n < 5:
        uncertainty = "very_high"
    elif confidence < Decimal("0.40"):
        uncertainty = "high"
    elif confidence < Decimal("0.70"):
        uncertainty = "moderate"
    else:
        uncertainty = "lower"

    return {
        "engine_version": EXPERT_TRUST_ENGINE_VERSION,
        "selected_scope_type": str(selected_scope.get("scope_type") or ""),
        "selected_scope_key": str(selected_scope.get("scope_key") or ""),
        "selected_scope_payload": dict(selected_scope.get("payload") or {}),
        "sample_n": sample_n,
        "correct_n": int(selected_row.get("correct_n") or 0),
        "incorrect_n": int(selected_row.get("incorrect_n") or 0),
        "net_score": int(selected_row.get("net_score") or 0),
        "raw_accuracy": selected_row.get("accuracy"),
        "shrunk_accuracy": selected_row.get("shrunk_accuracy"),
        "raw_score_mean": selected_row.get("score_mean"),
        "shrunk_score_mean": selected_row.get("shrunk_score_mean"),
        "sample_confidence": selected_row.get("sample_confidence"),
        "wilson_95_low": selected_row.get("wilson_95_low"),
        "wilson_95_high": selected_row.get("wilson_95_high"),
        "recent_window": selected_row.get("recent_window"),
        "recent_sample_n": recent_n,
        "recent_accuracy": selected_row.get("recent_accuracy"),
        "recent_net_score": int(selected_row.get("recent_net_score") or 0),
        "recent_state": recent_state,
        "uncertainty_state": uncertainty,
        "fallback_path": fallback_path,
    }


def build_trust_envelope(
    *,
    packet: Mapping[str, Any],
    profiles_by_subject: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Attach pre-decision history without rewriting the immutable Build-2 packet."""

    if not verify_expert_gate_packet(packet):
        raise ValueError("packet must satisfy Expert Gate Contract v1")

    subjects: list[dict[str, Any]] = []
    for subject in _subject_specs(packet):
        key = f"{subject['subject_type']}:{subject['subject_id']}"
        profile = dict(profiles_by_subject.get(key) or {})
        subjects.append(
            {
                "subject_type": subject["subject_type"],
                "subject_id": subject["subject_id"],
                "subject_version": subject["subject_version"],
                "profile": profile,
            }
        )

    result = {
        "engine_version": EXPERT_TRUST_ENGINE_VERSION,
        "packet_digest": packet["packet_digest"],
        "gate_id": packet["gate_id"],
        "gate_version": packet["gate_version"],
        "as_of_utc": packet["as_of_utc"],
        "internal_conviction": packet.get("internal_conviction"),
        "historical_reliability_separate_from_internal_conviction": True,
        "subject_profiles": subjects,
        "research_only": True,
        "live_money_execution_allowed": False,
        "future_values_used": False,
    }
    result["trust_digest"] = _digest(result)
    return result


__all__ = [
    "EXPERT_TRUST_ENGINE_VERSION",
    "LARGE_MOVE_BPS",
    "RECENT_WINDOW_SIZE",
    "TRUST_PRIOR_STRENGTH",
    "aggregate_context_rows",
    "build_trust_envelope",
    "build_trust_scopes",
    "score_directional_outcome",
    "score_expert_packet",
    "select_conditional_trust",
]
