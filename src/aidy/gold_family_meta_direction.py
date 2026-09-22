"""Blocker-1 production family meta-direction aggregator.

Implements the frozen v7-v9 mathematics without changing Build 20 diagnostics.
The decision consumes real sub-calculator histories, PIT class baselines and
order-independent dependency components. Research/shadow only.
"""
from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from hashlib import sha256
from typing import Any

from aidy.gold_cycle_environment import verify_cycle_environment
from aidy.gold_environment_contract import assert_no_hindsight_fields
from aidy.gold_evidence_dependency import (
    extract_dependency_signals,
    verify_evidence_dependency_engine,
)
from aidy.gold_expert_gate_contract import verify_expert_gate_packet

FAMILY_META_DIRECTION_VERSION = "aidy_gold_family_meta_direction_v1"

BASELINE_PRIOR_PER_CLASS = Decimal(10)
BASELINE_PRIOR_STRENGTH = Decimal(30)
PRIOR_STRENGTH = Decimal(20)
EDGE_SCALE = Decimal("0.15")
MIN_CONTRIBUTOR_N = 12
MIN_FAMILY_STRENGTH = Decimal("0.20")
MIN_FAMILIES = 2
BALANCED_ABSTAIN_BAND = Decimal("0.20")
FAMILY_NEUTRAL_BAND = Decimal("0.20")
UNKNOWN_CALIBRATION_MULTIPLIER = Decimal("0.85")

_SCOPE_MULTIPLIERS = {
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


def _current_state(
    expert_results: Sequence[Mapping[str, Any]],
) -> tuple[
    dict[str, Mapping[str, Any]],
    dict[str, Mapping[str, Any]],
    dict[str, Mapping[str, Any]],
]:
    packets: dict[str, Mapping[str, Any]] = {}
    calculators: dict[str, Mapping[str, Any]] = {}
    profiles: dict[str, Mapping[str, Any]] = {}

    for result in expert_results:
        assert_no_hindsight_fields(result, path="family_meta.expert_result")
        packet = result.get("expert_packet")
        trust = result.get("trust_envelope")
        if not isinstance(packet, Mapping) or not verify_expert_gate_packet(packet):
            raise ValueError("family meta requires verified expert packets")
        if not isinstance(trust, Mapping):
            raise ValueError("family meta requires trust envelopes")
        if str(trust.get("packet_digest") or "") != str(packet["packet_digest"]):
            raise ValueError("trust envelope packet digest mismatch")

        gate_id = str(packet["gate_id"])
        if gate_id in packets:
            raise ValueError(f"duplicate expert gate: {gate_id}")
        packets[gate_id] = packet

        for calc in packet["subcalculators"]:
            sid = f"{gate_id}:{calc['calculator_id']}"
            if sid in calculators:
                raise ValueError(f"duplicate subcalculator identity: {sid}")
            calculators[sid] = calc

        for item in trust.get("subject_profiles") or []:
            if (
                isinstance(item, Mapping)
                and str(item.get("subject_type") or "") == "subcalculator"
            ):
                sid = f"{gate_id}:{item.get('subject_id')}"
                profile = item.get("profile")
                profiles[sid] = (
                    dict(profile) if isinstance(profile, Mapping) else {}
                )

    return packets, calculators, profiles


def _history_by_subject(
    rows: Sequence[Mapping[str, Any]],
    *,
    as_of: datetime,
) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen: set[str] = set()

    for raw in rows:
        gate_id = str(raw.get("gate_id") or "")
        subject_id = str(raw.get("subject_id") or "")
        subject_version = str(raw.get("subject_version") or "")
        result_id = str(raw.get("result_id") or "")
        predicted = str(raw.get("predicted_class") or "").lower()
        realised = str(raw.get("realised_direction") or "").lower()
        if not gate_id or not subject_id or not subject_version or not result_id:
            continue
        if result_id in seen:
            continue
        seen.add(result_id)

        decision = _utc(str(raw.get("decision_time_utc")), name="history.decision_time_utc")
        resolved = _utc(str(raw.get("resolved_at_utc")), name="history.resolved_at_utc")
        if not decision < resolved < as_of:
            raise ValueError("family meta history violates PIT ordering")
        correct_raw = raw.get("correct")
        correct = int(correct_raw) if correct_raw in {0, 1, "0", "1"} else None
        result[f"{gate_id}:{subject_id}"].append(
            {
                "result_id": result_id,
                "subject_version": subject_version,
                "decision_time_utc": decision.isoformat(),
                "resolved_at_utc": resolved.isoformat(),
                "predicted_class": predicted,
                "realised_direction": realised,
                "correct": correct,
            }
        )

    for items in result.values():
        items.sort(key=lambda row: (row["decision_time_utc"], row["result_id"]))
    return dict(result)


def _baseline_by_decision(
    history_by_subject: Mapping[str, Sequence[Mapping[str, Any]]],
    outcome_rows: Sequence[Mapping[str, Any]],
    *,
    as_of: datetime,
) -> dict[str, dict[str, Decimal]]:
    decision_times = sorted(
        {
            str(row["decision_time_utc"])
            for rows in history_by_subject.values()
            for row in rows
            if str(row.get("predicted_class") or "") in {"bullish", "bearish"}
            and row.get("correct") in {0, 1}
        }
    )
    outcomes: list[tuple[datetime, str]] = []
    for raw in outcome_rows:
        klass = str(raw.get("realised_direction") or "").lower()
        if klass not in {"bullish", "bearish", "neutral"}:
            continue
        resolved = _utc(str(raw.get("resolved_at_utc")), name="outcome.resolved_at_utc")
        if resolved >= as_of:
            continue
        outcomes.append((resolved, klass))
    outcomes.sort(key=lambda item: item[0])

    counts = {"bullish": 0, "bearish": 0, "neutral": 0}
    cursor = 0
    result: dict[str, dict[str, Decimal]] = {}
    for decision_iso in decision_times:
        decision = _utc(decision_iso, name="baseline.decision_time_utc")
        while cursor < len(outcomes) and outcomes[cursor][0] < decision:
            counts[outcomes[cursor][1]] += 1
            cursor += 1
        total = sum(counts.values())
        result[decision_iso] = {
            klass: (
                Decimal(counts[klass]) + BASELINE_PRIOR_PER_CLASS
            ) / (
                Decimal(total) + BASELINE_PRIOR_STRENGTH
            )
            for klass in counts
        }
    return result


def _calibration_multiplier(
    row: Mapping[str, Any] | None,
) -> tuple[str, Decimal]:
    if not isinstance(row, Mapping):
        return "unknown", UNKNOWN_CALIBRATION_MULTIPLIER
    state = str(row.get("state") or "unknown")
    value = _decimal(
        row.get("multiplier"),
        name="calibration.multiplier",
        default=UNKNOWN_CALIBRATION_MULTIPLIER,
    )
    if value < 0 or value > 1:
        raise ValueError("calibration multiplier must be in [0,1]")
    return state, value


def _reliability(
    *,
    sid: str,
    current_version: str,
    history_rows: Sequence[Mapping[str, Any]],
    profile: Mapping[str, Any],
    baselines: Mapping[str, Mapping[str, Decimal]],
    calibration: Mapping[str, Any] | None,
) -> dict[str, Any]:
    directional = [
        row
        for row in history_rows
        if str(row.get("subject_version") or "") == current_version
        and str(row.get("predicted_class") or "") in {"bullish", "bearish"}
        and row.get("correct") in {0, 1}
    ]
    n = len(directional)
    excess_sum = Decimal(0)
    for row in directional:
        decision = str(row["decision_time_utc"])
        predicted = str(row["predicted_class"])
        base = baselines.get(decision, {}).get(predicted)
        if base is None:
            raise ValueError(f"missing PIT baseline for {sid} at {decision}")
        excess_sum += Decimal(int(row["correct"])) - base

    shrunk_excess = (
        excess_sum / (Decimal(n) + PRIOR_STRENGTH)
        if n
        else Decimal(0)
    )
    quality = max(Decimal(0), min(Decimal(1), shrunk_excess / EDGE_SCALE))

    scope_type = str(profile.get("selected_scope_type") or "neutral_prior")
    if scope_type.startswith("mini_reduced_"):
        scope_multiplier = Decimal("0.90")
    else:
        scope_multiplier = _SCOPE_MULTIPLIERS.get(scope_type, Decimal("0.60"))

    recent_state = str(profile.get("recent_state") or "insufficient_recent")
    recency_multiplier = _RECENCY_MULTIPLIERS.get(recent_state, Decimal("0.85"))
    calibration_state, calibration_multiplier = _calibration_multiplier(calibration)
    reliability = (
        quality
        * scope_multiplier
        * calibration_multiplier
        * recency_multiplier
    )
    return {
        "n": n,
        "sum_excess": _fmt(excess_sum),
        "shrunk_excess": _fmt(shrunk_excess),
        "quality": _fmt(quality),
        "selected_scope_type": scope_type,
        "scope_multiplier": _fmt(scope_multiplier),
        "recent_state": recent_state,
        "recency_multiplier": _fmt(recency_multiplier),
        "calibration_state": calibration_state,
        "calibration_multiplier": _fmt(calibration_multiplier),
        "reliability": _fmt(reliability),
    }


class _DSU:
    def __init__(self, ids: Sequence[str]) -> None:
        self.parent = {item: item for item in ids}

    def find(self, item: str) -> str:
        root = item
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[item] != item:
            nxt = self.parent[item]
            self.parent[item] = root
            item = nxt
        return root

    def union(self, left: str, right: str) -> None:
        a, b = self.find(left), self.find(right)
        if a != b:
            self.parent[b] = a


def build_family_meta_direction_view(
    *,
    global_environment: Mapping[str, Any],
    expert_results: Sequence[Mapping[str, Any]],
    dependency_engine: Mapping[str, Any],
    historical_subcalculator_rows: Sequence[Mapping[str, Any]],
    resolved_outcome_rows: Sequence[Mapping[str, Any]],
    calibration_rows_by_subject: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the frozen family-based research direction from PIT evidence."""

    if not verify_cycle_environment(global_environment):
        raise ValueError("family meta requires a verified cycle environment")
    if not verify_evidence_dependency_engine(dependency_engine):
        raise ValueError("family meta requires a verified Build-20 dependency packet")

    as_of = _utc(
        str(global_environment["exact_facts"]["as_of_utc"]),
        name="environment.as_of_utc",
    )
    packets, calculators, profiles = _current_state(expert_results)
    history = _history_by_subject(historical_subcalculator_rows, as_of=as_of)
    baselines = _baseline_by_decision(history, resolved_outcome_rows, as_of=as_of)
    calibrations = calibration_rows_by_subject or {}

    signals = extract_dependency_signals(expert_results)
    signal_map = {str(row["signal_id"]): row for row in signals}
    reliability_rows: dict[str, dict[str, Any]] = {}
    eligible: list[dict[str, Any]] = []

    for sid in sorted(calculators):
        calc = calculators[sid]
        rel = _reliability(
            sid=sid,
            current_version=str(calc["version"]),
            history_rows=history.get(sid, ()),
            profile=profiles.get(sid, {}),
            baselines=baselines,
            calibration=calibrations.get(sid),
        )
        reliability_rows[sid] = rel
        reliability = Decimal(rel["reliability"])
        vote = str(calc["vote"])
        family_eligible = (
            str(calc["state"]) == "known"
            and str(calc["role"]) == "directional"
            and int(rel["n"]) >= MIN_CONTRIBUTOR_N
            and reliability > 0
            and vote in {"bullish", "bearish", "neutral"}
            and (vote == "neutral" or bool(calc["scoreable"]))
        )
        if not family_eligible:
            continue
        signal = signal_map.get(sid)
        if not isinstance(signal, Mapping):
            raise ValueError(f"missing Build-20 signal for eligible contributor {sid}")
        eligible.append(
            {
                "signal_id": sid,
                "gate_id": str(signal["gate_id"]),
                "calculator_id": str(signal["calculator_id"]),
                "vote": vote,
                "reliability": reliability,
                "parent_family": str(signal["parent_family"]),
                "correlation_group": str(signal["correlation_group"]),
                "evidence_identity": str(signal["evidence_identity"]),
            }
        )

    diagnostics = dependency_engine.get("rolling_diagnostics")
    diagnostics = diagnostics if isinstance(diagnostics, Mapping) else {}
    pair_lookup = diagnostics.get("pair_lookup")
    pair_lookup = pair_lookup if isinstance(pair_lookup, Mapping) else {}

    families: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in eligible:
        families[row["parent_family"]].append(row)

    family_rows: list[dict[str, Any]] = []
    weight_rows: list[dict[str, Any]] = []
    for family_id, members in sorted(families.items()):
        members = sorted(members, key=lambda row: row["signal_id"])
        ids = [row["signal_id"] for row in members]
        dsu = _DSU(ids)
        by_id = {row["signal_id"]: row for row in members}

        for i, left in enumerate(ids):
            for right in ids[i + 1 :]:
                lrow, rrow = by_id[left], by_id[right]
                pair_id = "|".join(sorted((left, right)))
                pair = pair_lookup.get(pair_id)
                pair = pair if isinstance(pair, Mapping) else {}
                if (
                    lrow["correlation_group"] == rrow["correlation_group"]
                    or lrow["evidence_identity"] == rrow["evidence_identity"]
                    or str(pair.get("state") or "") == "high_dependency"
                ):
                    dsu.union(left, right)

        components: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in members:
            components[dsu.find(row["signal_id"])].append(row)
        component_groups = sorted(
            (sorted(rows, key=lambda row: row["signal_id"]) for rows in components.values()),
            key=lambda rows: rows[0]["signal_id"],
        )
        component_count = len(component_groups)
        d_weights: dict[str, Decimal] = {}

        for component_members in component_groups:
            slots: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
            for row in component_members:
                slots[(row["evidence_identity"], row["vote"])].append(row)
            ordered_slots = sorted(slots.items(), key=lambda item: item[0])
            slot_count = len(ordered_slots)
            for _, slot_members in ordered_slots:
                max_r = max(row["reliability"] for row in slot_members)
                winners = sorted(
                    (
                        row
                        for row in slot_members
                        if row["reliability"] == max_r
                    ),
                    key=lambda row: row["signal_id"],
                )
                each = (
                    Decimal(1)
                    / Decimal(component_count)
                    / Decimal(slot_count)
                    / Decimal(len(winners))
                )
                for row in winners:
                    d_weights[row["signal_id"]] = each

        bull = Decimal(0)
        bear = Decimal(0)
        for row in members:
            d_weight = d_weights.get(row["signal_id"], Decimal(0))
            if d_weight <= 0:
                continue
            mass = d_weight * row["reliability"]
            if row["vote"] == "bullish":
                bull += mass
            elif row["vote"] == "bearish":
                bear += mass
            weight_rows.append(
                {
                    "signal_id": row["signal_id"],
                    "family_id": family_id,
                    "vote": row["vote"],
                    "reliability": _fmt(row["reliability"]),
                    "dependency_weight": _fmt(d_weight),
                }
            )

        signed = bull - bear
        strength = abs(signed)
        family_reliability = bull + bear
        balance = (
            signed / family_reliability
            if family_reliability > 0
            else Decimal(0)
        )
        family_rows.append(
            {
                "family_id": family_id,
                "bull_mass": _fmt(bull),
                "bear_mass": _fmt(bear),
                "family_signed_evidence": _fmt(signed),
                "family_strength": _fmt(strength),
                "family_reliability": _fmt(family_reliability),
                "family_balance": _fmt(balance),
                "diagnostic_consensus_state": (
                    "weak_no_directional_consensus"
                    if abs(balance) < FAMILY_NEUTRAL_BAND
                    else "directional_consensus"
                ),
                "qualifies": strength >= MIN_FAMILY_STRENGTH,
                "eligible_member_n": len(members),
                "component_count": component_count,
            }
        )

    signed_total = sum(
        (Decimal(row["family_signed_evidence"]) for row in family_rows),
        Decimal(0),
    )
    strength_total = sum(
        (Decimal(row["family_strength"]) for row in family_rows),
        Decimal(0),
    )
    qualifying = [
        row
        for row in family_rows
        if Decimal(row["family_strength"]) >= MIN_FAMILY_STRENGTH
    ]
    positive = [
        row for row in qualifying
        if Decimal(row["family_signed_evidence"]) > 0
    ]
    negative = [
        row for row in qualifying
        if Decimal(row["family_signed_evidence"]) < 0
    ]
    meta_balance = (
        signed_total / strength_total
        if strength_total > 0
        else Decimal(0)
    )

    if strength_total == 0:
        direction = "abstain"
        decision_reason = "no_directional_evidence"
    elif len(qualifying) < MIN_FAMILIES:
        direction = "abstain"
        decision_reason = "insufficient_independent_families"
    elif positive and negative:
        direction = "abstain"
        decision_reason = "genuine_independent_disagreement"
    elif abs(meta_balance) < BALANCED_ABSTAIN_BAND:
        direction = "abstain"
        decision_reason = "balanced_directional_evidence"
    else:
        direction = "bullish" if meta_balance > 0 else "bearish"
        decision_reason = f"{direction}_family_evidence"

    current_gates = [
        {
            "gate_id": gate_id,
            "conclusion": str(packet["conclusion"]),
            "gate_mode": str(packet["gate_mode"]),
            "packet_digest": str(packet["packet_digest"]),
        }
        for gate_id, packet in sorted(packets.items())
    ]
    supporting_gate_ids = sorted(
        {
            row["gate_id"]
            for row in eligible
            if row["vote"] == direction
            and direction in {"bullish", "bearish"}
        }
    )
    context_gate_ids = sorted(
        gate_id
        for gate_id, packet in packets.items()
        if str(packet["gate_mode"]) == "context_only"
    )
    unavailable_gate_ids = sorted(
        gate_id
        for gate_id, packet in packets.items()
        if str(packet["conclusion"]) == "unknown"
    )

    readable_why = (
        f"{direction}: {len(qualifying)} qualifying independent families; "
        f"family balance {_fmt(meta_balance)}."
        if direction in {"bullish", "bearish"}
        else f"abstain: {decision_reason}; family balance {_fmt(meta_balance)}."
    )

    body = {
        "aggregator_version": FAMILY_META_DIRECTION_VERSION,
        "as_of_utc": as_of.isoformat(),
        "environment_key": str(global_environment["environment_key"]),
        "environment_digest": str(global_environment["environment_digest"]),
        "dependency_digest": str(dependency_engine["engine_digest"]),
        "direction": direction,
        "decision_reason": decision_reason,
        "signed_total": _fmt(signed_total),
        "strength_total": _fmt(strength_total),
        "meta_balance": _fmt(meta_balance),
        "qualifying_family_count": len(qualifying),
        "families": family_rows,
        "weights": sorted(weight_rows, key=lambda row: row["signal_id"]),
        "reliabilities": reliability_rows,
        "authority_totals": {
            "bullish": _fmt(sum((Decimal(row["bull_mass"]) for row in family_rows), Decimal(0))),
            "bearish": _fmt(sum((Decimal(row["bear_mass"]) for row in family_rows), Decimal(0))),
            "neutral": "0.000000",
            "directional_total": _fmt(strength_total),
            "signed": _fmt(signed_total),
        },
        "supporting_gates": supporting_gate_ids,
        "context_only_gates": context_gate_ids,
        "unavailable_gates": unavailable_gate_ids,
        "all_gate_traces": current_gates,
        "calibrated_confidence": None,
        "confidence_state": "withheld_until_family_meta_calibration",
        "readable_why": readable_why,
        "constants": {
            "edge_scale": _fmt(EDGE_SCALE),
            "min_families": MIN_FAMILIES,
            "min_family_strength": _fmt(MIN_FAMILY_STRENGTH),
            "min_contributor_n": MIN_CONTRIBUTOR_N,
            "balanced_abstain_band": _fmt(BALANCED_ABSTAIN_BAND),
            "family_neutral_band_reporting_only": _fmt(FAMILY_NEUTRAL_BAND),
            "prior_strength": int(PRIOR_STRENGTH),
            "baseline_prior_per_class": int(BASELINE_PRIOR_PER_CLASS),
            "baseline_prior_strength": int(BASELINE_PRIOR_STRENGTH),
        },
        "traceability": {
            "subcalculator_only_decision_inputs": True,
            "build20_weights_consumed": False,
            "build20_structural_facts_consumed": True,
            "gate_conclusions_used_for_decision_weight": False,
            "current_outcome_visible": False,
        },
        "future_values_used": False,
        "research_only": True,
        "formal_forward_evidence_created": False,
        "live_money_execution_allowed": False,
    }
    body["view_digest"] = _digest(body)
    return body


def verify_family_meta_direction_view(value: Mapping[str, Any]) -> bool:
    body = dict(value)
    supplied = str(body.pop("view_digest", ""))
    return (
        bool(supplied)
        and supplied == _digest(body)
        and body.get("aggregator_version") == FAMILY_META_DIRECTION_VERSION
        and body.get("future_values_used") is False
        and body.get("research_only") is True
        and body.get("formal_forward_evidence_created") is False
        and body.get("live_money_execution_allowed") is False
        and body.get("direction") in {"bullish", "bearish", "abstain"}
    )


__all__ = [
    "BALANCED_ABSTAIN_BAND",
    "BASELINE_PRIOR_PER_CLASS",
    "BASELINE_PRIOR_STRENGTH",
    "EDGE_SCALE",
    "FAMILY_META_DIRECTION_VERSION",
    "FAMILY_NEUTRAL_BAND",
    "MIN_CONTRIBUTOR_N",
    "MIN_FAMILIES",
    "MIN_FAMILY_STRENGTH",
    "PRIOR_STRENGTH",
    "build_family_meta_direction_view",
    "verify_family_meta_direction_view",
]
