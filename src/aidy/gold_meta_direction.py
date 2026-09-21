"""Build 22: AIDY Meta Direction Aggregator & Explanation.

This module combines the Build-21 selector output into one traceable 15-minute
research view. It does not create live-money authority. Numerical confidence is
withheld unless there is enough historical meta-calibration observed before the
current cycle.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from hashlib import sha256
from typing import Any

from aidy.gold_cycle_environment import verify_cycle_environment
from aidy.gold_environment_contract import assert_no_hindsight_fields
from aidy.gold_environment_gate_selector import (
    verify_environment_aware_gate_selector,
)
from aidy.gold_expert_gate_contract import verify_expert_gate_packet

META_DIRECTION_AGGREGATOR_VERSION = "aidy_gold_meta_direction_aggregator_v1"

MIN_DIRECTIONAL_WEIGHT = Decimal("0.30")
NEUTRAL_MARGIN_RATIO = Decimal("0.15")
STRONG_CONTRADICTION_RATIO = Decimal("0.45")
META_CALIBRATION_MIN_N = 30
META_CALIBRATION_PRIOR_N = 20


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value: object) -> str:
    return sha256(_canonical_json(value).encode()).hexdigest()


def _utc(value: datetime | str, *, name: str) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return parsed.astimezone(UTC)


def _decimal(
    value: Any,
    *,
    name: str,
    default: Decimal | None = None,
) -> Decimal:
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


def _packet_map(expert_results: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for expert in expert_results:
        assert_no_hindsight_fields(expert, path="meta.expert_result")
        packet = expert.get("expert_packet")
        if not isinstance(packet, Mapping) or not verify_expert_gate_packet(packet):
            raise ValueError("Build 22 requires verified expert packets")
        gate_id = str(packet["gate_id"])
        if gate_id in result:
            raise ValueError(f"duplicate expert packet for gate: {gate_id}")
        result[gate_id] = packet
    return result


def _latest_meta_calibration(
    *,
    rows: Sequence[Mapping[str, Any]],
    environment_key: str,
    as_of: datetime,
) -> dict[str, Any]:
    eligible: list[tuple[datetime, Mapping[str, Any]]] = []
    excluded_current_or_future_n = 0
    for row in rows:
        assert_no_hindsight_fields(row, path="meta_calibration")
        if str(row.get("environment_key") or "") not in {environment_key, "*"}:
            continue
        observed_raw = row.get("observed_at_utc")
        if observed_raw is None:
            continue
        observed = _utc(str(observed_raw), name="meta_calibration.observed_at_utc")
        if observed >= as_of:
            excluded_current_or_future_n += 1
            continue
        eligible.append((observed, row))
    eligible.sort(key=lambda item: item[0])
    if not eligible:
        return {
            "state": "unavailable",
            "sample_n": 0,
            "calibrated_confidence": None,
            "excluded_current_or_future_n": excluded_current_or_future_n,
        }

    observed, row = eligible[-1]
    sample_n = int(row.get("sample_n") or 0)
    accuracy = _decimal(
        row.get("empirical_accuracy"),
        name="meta_calibration.empirical_accuracy",
    )
    if not Decimal(0) <= accuracy <= Decimal(1):
        raise ValueError("meta calibration empirical_accuracy must be between 0 and 1")

    if sample_n < META_CALIBRATION_MIN_N:
        return {
            "state": "insufficient_sample",
            "sample_n": sample_n,
            "raw_empirical_accuracy": _fmt(accuracy),
            "calibrated_confidence": None,
            "observed_at_utc": observed.isoformat(),
            "excluded_current_or_future_n": excluded_current_or_future_n,
        }

    shrunk = (
        accuracy * Decimal(sample_n)
        + Decimal("0.5") * Decimal(META_CALIBRATION_PRIOR_N)
    ) / Decimal(sample_n + META_CALIBRATION_PRIOR_N)
    return {
        "state": "known",
        "sample_n": sample_n,
        "raw_empirical_accuracy": _fmt(accuracy),
        "calibrated_confidence": _fmt(shrunk),
        "observed_at_utc": observed.isoformat(),
        "prior_accuracy": "0.500000",
        "prior_n": META_CALIBRATION_PRIOR_N,
        "excluded_current_or_future_n": excluded_current_or_future_n,
    }


def _short_reason(packet: Mapping[str, Any]) -> str:
    text = str(packet.get("readable_explanation") or "").strip()
    if text:
        return text
    return f"{packet['gate_id']} concluded {packet['conclusion']}."


def _gate_trace(
    *,
    selector_row: Mapping[str, Any],
    packet: Mapping[str, Any],
) -> dict[str, Any]:
    if str(selector_row.get("packet_digest") or "") != str(packet.get("packet_digest") or ""):
        raise ValueError("Build 22 selector/packet digest mismatch")
    return {
        "gate_id": str(selector_row["gate_id"]),
        "gate_version": str(packet["gate_version"]),
        "packet_digest": str(packet["packet_digest"]),
        "classification": str(selector_row.get("classification") or "unknown"),
        "gate_mode": str(packet["gate_mode"]),
        "conclusion": str(packet["conclusion"]),
        "trust_score": selector_row.get("trust_score"),
        "directional_authority_weight": selector_row.get(
            "directional_authority_weight"
        ),
        "observation_weight": selector_row.get("observation_weight"),
        "sample_n": int(selector_row.get("sample_n") or 0),
        "context_label": str(selector_row.get("context_label") or "unknown"),
        "dependency_adjustment": dict(
            selector_row.get("dependency_adjustment") or {}
        ),
        "selector_reasons": list(selector_row.get("reasons") or []),
        "readable_explanation": _short_reason(packet),
        "packet_contradictions": list(packet.get("contradictions") or []),
        "source_refs": {
            "selector_gate": str(selector_row["gate_id"]),
            "packet_digest": str(packet["packet_digest"]),
        },
    }


def build_meta_direction_view(
    *,
    global_environment: Mapping[str, Any],
    selector: Mapping[str, Any],
    expert_results: Sequence[Mapping[str, Any]],
    meta_calibration_rows: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Combine selected gates into one research-only 15-minute view."""

    if not verify_cycle_environment(global_environment):
        raise ValueError("Build 22 requires a verified cycle environment")
    if not verify_environment_aware_gate_selector(selector):
        raise ValueError("Build 22 requires a verified Build-21 selector")

    as_of = _utc(
        str(global_environment["exact_facts"]["as_of_utc"]),
        name="environment.as_of_utc",
    )
    if _utc(str(selector["as_of_utc"]), name="selector.as_of_utc") != as_of:
        raise ValueError("selector and environment as-of must match")
    if str(selector["environment_key"]) != str(global_environment["environment_key"]):
        raise ValueError("selector and environment key must match")

    packets = _packet_map(expert_results)
    rows = selector.get("all_gates")
    if not isinstance(rows, list):
        raise TypeError("selector all_gates must be a list")

    traces: list[dict[str, Any]] = []
    unavailable: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise TypeError("selector gate rows must be mappings")
        gate_id = str(row.get("gate_id") or "")
        classification = str(row.get("classification") or "")
        if classification == "unavailable":
            unavailable.append(
                {
                    "gate_id": gate_id,
                    "reasons": list(row.get("reasons") or []),
                    "directional_authority_weight": "0.000000",
                }
            )
            continue
        packet = packets.get(gate_id)
        if packet is None:
            raise ValueError(f"selector references missing expert packet: {gate_id}")
        traces.append(_gate_trace(selector_row=row, packet=packet))

    bullish = Decimal(0)
    bearish = Decimal(0)
    neutral = Decimal(0)
    context_only: list[dict[str, Any]] = []
    supporting: list[dict[str, Any]] = []
    contradictions: list[dict[str, Any]] = []

    for trace in traces:
        mode = trace["gate_mode"]
        conclusion = trace["conclusion"]
        if mode == "context_only":
            context_only.append(trace)
            continue
        weight = _decimal(
            trace["directional_authority_weight"],
            name=f"{trace['gate_id']}.directional_authority_weight",
            default=Decimal(0),
        )
        if weight < 0:
            raise ValueError("directional authority cannot be negative")
        if conclusion == "bullish":
            bullish += weight
        elif conclusion == "bearish":
            bearish += weight
        elif conclusion == "neutral":
            neutral += weight

    directional_total = bullish + bearish
    signed = bullish - bearish
    margin = abs(signed)
    margin_ratio = Decimal(0) if directional_total == 0 else margin / directional_total
    opposite = min(bullish, bearish)
    contradiction_ratio = (
        Decimal(0)
        if directional_total == 0
        else opposite / directional_total
    )

    high_trust_bull = [
        row for row in traces
        if row["gate_mode"] == "directional"
        and row["classification"] == "high_trust"
        and row["conclusion"] == "bullish"
        and _decimal(row["directional_authority_weight"], name="bull_weight") > 0
    ]
    high_trust_bear = [
        row for row in traces
        if row["gate_mode"] == "directional"
        and row["classification"] == "high_trust"
        and row["conclusion"] == "bearish"
        and _decimal(row["directional_authority_weight"], name="bear_weight") > 0
    ]
    strong_cross_contradiction = bool(high_trust_bull and high_trust_bear)
    strong_contradiction = (
        contradiction_ratio >= STRONG_CONTRADICTION_RATIO
        or strong_cross_contradiction
    )

    if directional_total < MIN_DIRECTIONAL_WEIGHT:
        direction = "abstain"
        decision_reason = "insufficient_directional_authority"
    elif strong_contradiction:
        direction = "abstain"
        decision_reason = "strong_cross_gate_contradiction"
    elif neutral >= max(bullish, bearish) and neutral > 0:
        direction = "neutral"
        decision_reason = "neutral_authority_dominates"
    elif margin_ratio < NEUTRAL_MARGIN_RATIO:
        direction = "neutral"
        decision_reason = "directional_margin_too_small"
    elif signed > 0:
        direction = "bullish"
        decision_reason = "bullish_authority_dominates"
    elif signed < 0:
        direction = "bearish"
        decision_reason = "bearish_authority_dominates"
    else:
        direction = "neutral"
        decision_reason = "balanced_directional_authority"

    for trace in traces:
        if trace["gate_mode"] != "directional":
            continue
        if trace["conclusion"] == direction and direction in {"bullish", "bearish"}:
            supporting.append(trace)
        elif (
            direction in {"bullish", "bearish"}
            and trace["conclusion"] in {"bullish", "bearish"}
            and trace["conclusion"] != direction
        ):
            contradictions.append(trace)
        elif direction in {"neutral", "abstain"} and trace["conclusion"] in {
            "bullish",
            "bearish",
        }:
            contradictions.append(trace)

    calibration = _latest_meta_calibration(
        rows=meta_calibration_rows,
        environment_key=str(global_environment["environment_key"]),
        as_of=as_of,
    )
    context_quality_reduced = any(
        trace["classification"] != "high_trust"
        for trace in context_only
    )
    if direction == "abstain":
        confidence_state = "withheld_abstain"
        calibrated_confidence = None
    elif strong_contradiction:
        confidence_state = "withheld_strong_contradiction"
        calibrated_confidence = None
    elif calibration["state"] != "known":
        confidence_state = f"withheld_{calibration['state']}"
        calibrated_confidence = None
    elif context_quality_reduced:
        confidence_state = "withheld_reduced_context_quality"
        calibrated_confidence = None
    else:
        confidence_state = "known_from_historical_meta_calibration"
        calibrated_confidence = calibration["calibrated_confidence"]

    supporting_ids = [row["gate_id"] for row in supporting]
    contradiction_ids = [row["gate_id"] for row in contradictions]
    context_ids = [row["gate_id"] for row in context_only]
    if direction in {"bullish", "bearish"}:
        why = (
            f"AIDY research view is {direction}: supporting gates "
            f"{', '.join(supporting_ids) if supporting_ids else 'none'}; "
            f"opposing gates {', '.join(contradiction_ids) if contradiction_ids else 'none'}. "
            f"Context-only gates observed: {', '.join(context_ids) if context_ids else 'none'}."
        )
    else:
        why = (
            f"AIDY research view is {direction} because {decision_reason}. "
            f"Bullish authority={_fmt(bullish)}, bearish authority={_fmt(bearish)}, "
            f"neutral authority={_fmt(neutral)}."
        )

    body = {
        "aggregator_version": META_DIRECTION_AGGREGATOR_VERSION,
        "as_of_utc": as_of.isoformat(),
        "environment_key": str(global_environment["environment_key"]),
        "environment_digest": str(global_environment["environment_digest"]),
        "selector_digest": str(selector["selector_digest"]),
        "direction": direction,
        "decision_reason": decision_reason,
        "calibrated_confidence": calibrated_confidence,
        "confidence_state": confidence_state,
        "meta_calibration": calibration,
        "authority_totals": {
            "bullish": _fmt(bullish),
            "bearish": _fmt(bearish),
            "neutral": _fmt(neutral),
            "directional_total": _fmt(directional_total),
            "signed": _fmt(signed),
            "margin_ratio": _fmt(margin_ratio),
            "contradiction_ratio": _fmt(contradiction_ratio),
        },
        "supporting_gates": supporting,
        "contradicting_gates": contradictions,
        "context_only_gates": context_only,
        "unavailable_gates": unavailable,
        "all_gate_traces": sorted(traces, key=lambda item: item["gate_id"]),
        "strong_contradiction": strong_contradiction,
        "readable_why": why,
        "traceability": {
            "every_directional_contribution_has_packet_digest": True,
            "selector_authority_reused_without_reweighting": True,
            "context_only_gates_cast_directional_vote": False,
            "magic_percentage_created": False,
        },
        "future_values_used": False,
        "research_only": True,
        "formal_forward_evidence_created": False,
        "live_money_execution_allowed": False,
    }
    body["view_digest"] = _digest(body)
    return body


def verify_meta_direction_view(value: Mapping[str, Any]) -> bool:
    body = dict(value)
    supplied = str(body.pop("view_digest", ""))
    return (
        bool(supplied)
        and supplied == _digest(body)
        and body.get("aggregator_version") == META_DIRECTION_AGGREGATOR_VERSION
        and body.get("direction") in {"bullish", "bearish", "neutral", "abstain"}
        and body.get("future_values_used") is False
        and body.get("research_only") is True
        and body.get("live_money_execution_allowed") is False
        and isinstance(body.get("traceability"), Mapping)
        and body["traceability"].get("magic_percentage_created") is False
        and body["traceability"].get("context_only_gates_cast_directional_vote") is False
    )


__all__ = [
    "META_DIRECTION_AGGREGATOR_VERSION",
    "META_CALIBRATION_MIN_N",
    "MIN_DIRECTIONAL_WEIGHT",
    "NEUTRAL_MARGIN_RATIO",
    "STRONG_CONTRADICTION_RATIO",
    "build_meta_direction_view",
    "verify_meta_direction_view",
]
