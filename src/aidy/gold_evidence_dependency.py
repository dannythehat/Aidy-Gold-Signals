"""Build 20: evidence dependency and double-counting engine for AIDY Gold.

The engine is deliberately pre-aggregation. It does not decide BUY/SELL and it
does not grant weight from performance. It maps declared evidence relationships,
measures rolling pre-outcome co-movement between directional signals, removes
exact duplicates and emits deterministic dependency multipliers for Build 21.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation, localcontext
from hashlib import sha256
from itertools import combinations
from typing import Any

from aidy.gold_environment_contract import assert_no_hindsight_fields
from aidy.gold_expert_gate_contract import (
    DEPENDENCY_FAMILIES,
    verify_expert_gate_packet,
)

EVIDENCE_DEPENDENCY_ENGINE_VERSION = "aidy_gold_evidence_dependency_engine_v1"
EVIDENCE_FAMILY_GRAPH_VERSION = "aidy_gold_evidence_family_graph_v1"
ROLLING_DEPENDENCY_DIAGNOSTIC_VERSION = "aidy_gold_rolling_dependency_diagnostic_v1"

CORRELATION_MIN_N = 12
HIGH_CORRELATION_THRESHOLD = Decimal("0.75")
MODERATE_CORRELATION_THRESHOLD = Decimal("0.50")
SAME_CORRELATION_GROUP_MULTIPLIER = Decimal("0.35")
HIGH_CORRELATION_FLOOR_MULTIPLIER = Decimal("0.25")
PARENT_GROUP_INCREMENTAL_CAP = Decimal("0.50")
INDEPENDENT_BONUS_PER_EXTRA_ROOT = Decimal("0.05")
INDEPENDENT_BONUS_MAX = Decimal("0.15")
INDEPENDENT_BONUS_MIN_ROOTS = 3

FAMILY_PARENT = {
    "structure": "price_action",
    "momentum": "price_action",
    "location": "price_action",
    "liquidity": "liquidity_mechanism",
    "volatility": "volatility_regime",
    "session_participation": "participation_flow",
    "futures_microstructure": "participation_flow",
    "event": "macro_information",
    "rates_usd": "macro_information",
    "cross_market": "macro_information",
    "news_mechanism": "macro_information",
    "analogue": "analogue_memory",
    "data_quality": "data_quality",
}

PARENT_CHILD_RELATIONSHIPS = tuple(
    {"parent": parent, "child": child}
    for child, parent in sorted(FAMILY_PARENT.items())
)

_DIRECTION_VALUE = {
    "bullish": Decimal(1),
    "bearish": Decimal(-1),
    "neutral": Decimal(0),
    "abstain": Decimal(0),
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


def _decimal(value: Any, *, name: str) -> Decimal:
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


def _vote(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"bullish", "bearish", "neutral", "abstain", "unknown", "context_only"}:
        return text
    raise ValueError(f"unsupported signal vote: {text}")


def _parent(dependency_family: str) -> str:
    parent = FAMILY_PARENT.get(dependency_family)
    if parent is None:
        raise ValueError(f"dependency family has no Build 20 parent: {dependency_family}")
    return parent


def evidence_family_graph() -> dict[str, Any]:
    parents: dict[str, list[str]] = defaultdict(list)
    for child, parent in FAMILY_PARENT.items():
        parents[parent].append(child)
    body = {
        "graph_version": EVIDENCE_FAMILY_GRAPH_VERSION,
        "roots": [
            {
                "root": root,
                "children": sorted(children),
            }
            for root, children in sorted(parents.items())
        ],
        "parent_child_relationships": list(PARENT_CHILD_RELATIONSHIPS),
        "price_action_children_share_underlying_price_path": [
            "structure",
            "momentum",
            "location",
        ],
        "macro_information_children_share_information_complex": [
            "event",
            "rates_usd",
            "cross_market",
            "news_mechanism",
        ],
        "independent_root_bonus_requires_distinct_roots": True,
        "future_values_used": False,
        "outcomes_used": False,
    }
    body["graph_digest"] = _digest(body)
    return body


def verify_evidence_family_graph(value: Mapping[str, Any]) -> bool:
    body = dict(value)
    supplied = str(body.pop("graph_digest", ""))
    return (
        bool(supplied)
        and supplied == _digest(body)
        and body.get("graph_version") == EVIDENCE_FAMILY_GRAPH_VERSION
        and body.get("future_values_used") is False
        and body.get("outcomes_used") is False
    )


def _evidence_identity(
    packet: Mapping[str, Any],
    evidence_refs: Sequence[str],
) -> str:
    by_id = {
        str(item.get("evidence_id")): item
        for item in packet.get("evidence_inputs") or []
        if isinstance(item, Mapping)
    }
    payload = []
    for ref in sorted(evidence_refs):
        item = by_id.get(str(ref))
        if item is None:
            raise ValueError(f"subcalculator references missing evidence: {ref}")
        payload.append(
            {
                "observed_at_utc": item.get("observed_at_utc"),
                "state": item.get("state"),
                "value": item.get("value"),
                "provenance": item.get("provenance"),
            }
        )
    return _digest(payload)


def extract_dependency_signals(
    expert_results: Sequence[Mapping[str, Any]],
    *,
    raw_weights: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Convert accepted expert outputs into Build-20 dependency signals.

    raw_weights are optional because Build 21 owns trust selection. A missing
    weight is represented as 1.0 only for dependency geometry / acceptance math.
    """

    weight_map = raw_weights or {}
    result: list[dict[str, Any]] = []
    for expert in expert_results:
        packet = expert.get("expert_packet")
        if not isinstance(packet, Mapping) or not verify_expert_gate_packet(packet):
            raise ValueError("Build 20 requires verified expert packets")
        metadata = expert.get("dependency_metadata")
        metadata = metadata if isinstance(metadata, Mapping) else {}
        gate_id = str(packet["gate_id"])

        for calculator in packet.get("subcalculators") or []:
            if not isinstance(calculator, Mapping):
                continue
            calc_id = str(calculator["calculator_id"])
            family = str(calculator["dependency_family"])
            meta = metadata.get(calc_id)
            meta = meta if isinstance(meta, Mapping) else {}
            observation = calculator.get("observation")
            observation = observation if isinstance(observation, Mapping) else {}
            correlation_group = str(
                meta.get("correlation_group")
                or observation.get("correlation_group")
                or f"{gate_id}:{family}"
            )
            signal_id = f"{gate_id}:{calc_id}"
            evidence_refs = [str(item) for item in calculator.get("evidence_refs") or []]
            result.append(
                {
                    "signal_id": signal_id,
                    "gate_id": gate_id,
                    "calculator_id": calc_id,
                    "dependency_family": family,
                    "correlation_group": correlation_group,
                    "parent_family": _parent(family),
                    "role": str(calculator["role"]),
                    "state": str(calculator["state"]),
                    "vote": str(calculator["vote"]),
                    "raw_weight": weight_map.get(signal_id, "1"),
                    "evidence_identity": _evidence_identity(packet, evidence_refs),
                    "later_penalty_tag": str(meta.get("later_penalty_tag") or "none"),
                    "source_packet_digest": str(packet["packet_digest"]),
                }
            )
    return result


def _normalise_signal(raw: Mapping[str, Any]) -> dict[str, Any]:
    assert_no_hindsight_fields(raw, path="dependency_signal")
    signal_id = str(raw.get("signal_id") or "").strip()
    if not signal_id:
        raise ValueError("dependency signal requires signal_id")
    family = str(raw.get("dependency_family") or "").strip().lower()
    if family not in DEPENDENCY_FAMILIES:
        raise ValueError(f"unsupported dependency family: {family}")
    parent = str(raw.get("parent_family") or _parent(family)).strip().lower()
    if parent != _parent(family):
        raise ValueError("signal parent_family conflicts with declared family graph")
    role = str(raw.get("role") or "directional").strip().lower()
    if role not in {"directional", "context_only"}:
        raise ValueError("signal role must be directional or context_only")
    state = str(raw.get("state") or "known").strip().lower()
    vote = _vote(raw.get("vote"))
    weight = _decimal(raw.get("raw_weight", "1"), name="raw_weight")
    if weight < 0 or weight > 1:
        raise ValueError("raw_weight must be between 0 and 1")
    correlation_group = str(raw.get("correlation_group") or "").strip()
    if not correlation_group:
        raise ValueError("dependency signal requires correlation_group")
    evidence_identity = str(raw.get("evidence_identity") or "").strip()
    if not evidence_identity:
        evidence_identity = _digest(
            {
                "signal_id": signal_id,
                "correlation_group": correlation_group,
            }
        )
    eligible = (
        role == "directional"
        and state == "known"
        and vote in {"bullish", "bearish", "neutral", "abstain"}
        and weight > 0
    )
    return {
        "signal_id": signal_id,
        "gate_id": str(raw.get("gate_id") or signal_id.split(":", 1)[0]),
        "calculator_id": str(raw.get("calculator_id") or signal_id),
        "dependency_family": family,
        "parent_family": parent,
        "correlation_group": correlation_group,
        "role": role,
        "state": state,
        "vote": vote,
        "raw_weight": weight,
        "evidence_identity": evidence_identity,
        "later_penalty_tag": str(raw.get("later_penalty_tag") or "none"),
        "eligible_for_directional_weight": eligible,
    }


def _history_vote(value: Any) -> Decimal | None:
    text = str(value or "").strip().lower()
    if text not in _DIRECTION_VALUE:
        return None
    return _DIRECTION_VALUE[text]


def _pearson(left: Sequence[Decimal], right: Sequence[Decimal]) -> Decimal | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    left_mean = sum(left, Decimal(0)) / Decimal(len(left))
    right_mean = sum(right, Decimal(0)) / Decimal(len(right))
    left_dev = [item - left_mean for item in left]
    right_dev = [item - right_mean for item in right]
    covariance = sum(
        a * b for a, b in zip(left_dev, right_dev, strict=True)
    )
    left_ss = sum((item * item for item in left_dev), Decimal(0))
    right_ss = sum((item * item for item in right_dev), Decimal(0))
    if left_ss == 0 or right_ss == 0:
        return None
    with localcontext() as ctx:
        ctx.prec = 40
        return covariance / (left_ss * right_ss).sqrt()


def rolling_dependency_diagnostics(
    *,
    signals: Sequence[Mapping[str, Any]],
    historical_rows: Sequence[Mapping[str, Any]],
    as_of_utc: datetime | str,
    min_n: int = CORRELATION_MIN_N,
    lookback_cycles: int = 120,
) -> dict[str, Any]:
    """Measure signal co-movement using only prior pre-outcome signal states."""

    as_of = _utc(as_of_utc, name="as_of_utc")
    normalized = [_normalise_signal(item) for item in signals]
    ids = sorted(
        item["signal_id"]
        for item in normalized
        if item["eligible_for_directional_weight"]
    )

    eligible_rows: list[tuple[datetime, Mapping[str, Any]]] = []
    for row in historical_rows:
        assert_no_hindsight_fields(row, path="historical_dependency_row")
        observed_raw = row.get("observed_at_utc")
        signal_values = row.get("signals")
        if observed_raw is None or not isinstance(signal_values, Mapping):
            continue
        observed = _utc(str(observed_raw), name="historical_row.observed_at_utc")
        if observed >= as_of:
            continue
        eligible_rows.append((observed, signal_values))
    eligible_rows.sort(key=lambda item: item[0], reverse=True)
    eligible_rows = eligible_rows[: max(1, int(lookback_cycles))]

    pairs: list[dict[str, Any]] = []
    pair_lookup: dict[str, dict[str, Any]] = {}
    for left_id, right_id in combinations(ids, 2):
        left_values: list[Decimal] = []
        right_values: list[Decimal] = []
        for _, values in eligible_rows:
            left = _history_vote(values.get(left_id))
            right = _history_vote(values.get(right_id))
            if left is None or right is None:
                continue
            left_values.append(left)
            right_values.append(right)
        correlation = _pearson(left_values, right_values)
        sample_n = len(left_values)
        if sample_n < int(min_n):
            state = "insufficient"
            correlation = None
        elif correlation is None:
            state = "zero_variance"
        elif abs(correlation) >= HIGH_CORRELATION_THRESHOLD:
            state = "high_dependency"
        elif abs(correlation) >= MODERATE_CORRELATION_THRESHOLD:
            state = "moderate_dependency"
        else:
            state = "weak_dependency"
        key = "|".join((left_id, right_id))
        item = {
            "pair_id": key,
            "left_signal_id": left_id,
            "right_signal_id": right_id,
            "sample_n": sample_n,
            "correlation": None if correlation is None else _fmt(correlation),
            "absolute_correlation": (
                None if correlation is None else _fmt(abs(correlation))
            ),
            "state": state,
            "minimum_sample_n": int(min_n),
            "outcomes_used": False,
            "future_rows_used": False,
        }
        pairs.append(item)
        pair_lookup[key] = item

    body = {
        "diagnostic_version": ROLLING_DEPENDENCY_DIAGNOSTIC_VERSION,
        "as_of_utc": as_of.isoformat(),
        "lookback_cycles": int(lookback_cycles),
        "eligible_historical_row_n": len(eligible_rows),
        "pair_count": len(pairs),
        "pairs": pairs,
        "pair_lookup": pair_lookup,
        "outcomes_used": False,
        "future_rows_used": False,
    }
    body["diagnostic_digest"] = _digest(body)
    return body


def verify_rolling_dependency_diagnostics(value: Mapping[str, Any]) -> bool:
    body = dict(value)
    supplied = str(body.pop("diagnostic_digest", ""))
    return (
        bool(supplied)
        and supplied == _digest(body)
        and body.get("diagnostic_version") == ROLLING_DEPENDENCY_DIAGNOSTIC_VERSION
        and body.get("outcomes_used") is False
        and body.get("future_rows_used") is False
    )


def _pair_diagnostic(
    diagnostics: Mapping[str, Any],
    left_id: str,
    right_id: str,
) -> Mapping[str, Any] | None:
    lookup = diagnostics.get("pair_lookup")
    if not isinstance(lookup, Mapping):
        return None
    key = "|".join(sorted((left_id, right_id)))
    item = lookup.get(key)
    return item if isinstance(item, Mapping) else None


def _independent_bonus(adjusted: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    by_root: dict[str, dict[str, Decimal]] = defaultdict(
        lambda: {"bullish": Decimal(0), "bearish": Decimal(0)}
    )
    for item in adjusted:
        if item.get("eligible_for_directional_weight") is not True:
            continue
        vote = str(item.get("vote"))
        if vote not in {"bullish", "bearish"}:
            continue
        weight = _decimal(item.get("effective_weight"), name="effective_weight")
        if weight <= 0:
            continue
        by_root[str(item["parent_family"])][vote] += weight

    bullish_roots = sorted(
        root
        for root, values in by_root.items()
        if values["bullish"] > values["bearish"]
    )
    bearish_roots = sorted(
        root
        for root, values in by_root.items()
        if values["bearish"] > values["bullish"]
    )
    if len(bullish_roots) >= INDEPENDENT_BONUS_MIN_ROOTS:
        direction = "bullish"
        roots = bullish_roots
    elif len(bearish_roots) >= INDEPENDENT_BONUS_MIN_ROOTS:
        direction = "bearish"
        roots = bearish_roots
    else:
        direction = "none"
        roots = []

    extra = max(0, len(roots) - (INDEPENDENT_BONUS_MIN_ROOTS - 1))
    bonus = min(
        INDEPENDENT_BONUS_MAX,
        INDEPENDENT_BONUS_PER_EXTRA_ROOT * Decimal(extra),
    )
    return {
        "state": "justified" if roots else "not_justified",
        "direction": direction,
        "independent_root_count": len(roots),
        "independent_roots": roots,
        "bonus_fraction": _fmt(bonus),
        "bonus_multiplier": _fmt(Decimal(1) + bonus),
        "requires_distinct_parent_roots": True,
    }


def apply_dependency_adjustments(
    *,
    signals: Sequence[Mapping[str, Any]],
    diagnostics: Mapping[str, Any],
) -> dict[str, Any]:
    if not verify_rolling_dependency_diagnostics(diagnostics):
        raise ValueError("Build 20 requires verified rolling dependency diagnostics")
    normalized = [_normalise_signal(item) for item in signals]
    if len({item["signal_id"] for item in normalized}) != len(normalized):
        raise ValueError("dependency signal_id values must be unique")

    ordered = sorted(
        normalized,
        key=lambda item: (-item["raw_weight"], item["signal_id"]),
    )
    adjusted: list[dict[str, Any]] = []
    seen_exact: set[tuple[str, str]] = set()

    for signal in ordered:
        multiplier = Decimal(1) if signal["eligible_for_directional_weight"] else Decimal(0)
        reasons: list[str] = []
        exact_key = (signal["evidence_identity"], signal["vote"])
        if multiplier > 0 and exact_key in seen_exact:
            multiplier = Decimal(0)
            reasons.append("exact_duplicate_zero_increment")
        elif multiplier > 0:
            seen_exact.add(exact_key)

        if multiplier > 0:
            for prior in adjusted:
                if prior["eligible_for_directional_weight"] is not True:
                    continue
                if _decimal(prior["effective_weight"], name="effective_weight") <= 0:
                    continue
                if (
                    prior["correlation_group"] == signal["correlation_group"]
                    and prior["vote"] == signal["vote"]
                ):
                    multiplier = min(
                        multiplier,
                        SAME_CORRELATION_GROUP_MULTIPLIER,
                    )
                    reasons.append("same_correlation_group_damped")

                diagnostic = _pair_diagnostic(
                    diagnostics,
                    str(prior["signal_id"]),
                    str(signal["signal_id"]),
                )
                if (
                    diagnostic is not None
                    and diagnostic.get("state") == "high_dependency"
                    and prior["parent_family"] == signal["parent_family"]
                ):
                    corr = _decimal(
                        diagnostic.get("absolute_correlation"),
                        name="absolute_correlation",
                    )
                    empirical = max(
                        HIGH_CORRELATION_FLOOR_MULTIPLIER,
                        Decimal(1) - corr,
                    )
                    multiplier = min(multiplier, empirical)
                    reasons.append("high_rolling_correlation_damped")

        adjusted.append(
            {
                **signal,
                "dependency_multiplier_pre_parent_cap": _fmt(multiplier),
                "dependency_multiplier": _fmt(multiplier),
                "effective_weight": _fmt(signal["raw_weight"] * multiplier),
                "adjustment_reasons": sorted(set(reasons)),
                "exact_duplicate_increment_zero": "exact_duplicate_zero_increment" in reasons,
            }
        )

    # Parent caps preserve the strongest signal, then cap all incremental evidence
    # from the same underlying root at 50% of that leader's raw weight.
    by_parent: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in adjusted:
        if item["eligible_for_directional_weight"]:
            by_parent[str(item["parent_family"])].append(item)

    for members in by_parent.values():
        active = [
            item
            for item in members
            if _decimal(item["effective_weight"], name="effective_weight") > 0
        ]
        if len(active) < 2:
            continue
        active.sort(
            key=lambda item: (
                -_decimal(item["raw_weight"], name="raw_weight"),
                item["signal_id"],
            )
        )
        leader = active[0]
        leader_weight = _decimal(leader["effective_weight"], name="effective_weight")
        incremental_cap = (
            _decimal(leader["raw_weight"], name="raw_weight")
            * PARENT_GROUP_INCREMENTAL_CAP
        )
        follower_total = sum(
            (
                _decimal(item["effective_weight"], name="effective_weight")
                for item in active[1:]
            ),
            Decimal(0),
        )
        if follower_total <= incremental_cap or follower_total == 0:
            continue
        scale = incremental_cap / follower_total
        for item in active[1:]:
            previous = _decimal(item["effective_weight"], name="effective_weight")
            effective = previous * scale
            raw_weight = _decimal(item["raw_weight"], name="raw_weight")
            item["effective_weight"] = _fmt(effective)
            item["dependency_multiplier"] = _fmt(
                Decimal(0) if raw_weight == 0 else effective / raw_weight
            )
            item["adjustment_reasons"] = sorted(
                set(item["adjustment_reasons"] + ["parent_root_incremental_cap"])
            )

        # Exact-duplicate invariance means a zero-increment duplicate never lowers
        # the leader when the group is capped.
        leader["effective_weight"] = _fmt(leader_weight)

    adjusted.sort(key=lambda item: item["signal_id"])
    bonus = _independent_bonus(adjusted)

    signed = Decimal(0)
    absolute = Decimal(0)
    for item in adjusted:
        if not item["eligible_for_directional_weight"]:
            continue
        direction = _DIRECTION_VALUE.get(str(item["vote"]))
        if direction is None:
            continue
        weight = _decimal(item["effective_weight"], name="effective_weight")
        signed += direction * weight
        absolute += weight

    base_score = Decimal(0) if absolute == 0 else signed / absolute
    bonus_multiplier = _decimal(
        bonus["bonus_multiplier"],
        name="bonus_multiplier",
    )
    boosted_signed = signed * bonus_multiplier
    result = {
        "adjusted_signals": adjusted,
        "independent_agreement_bonus": bonus,
        "directional_effective_weight_total": _fmt(absolute),
        "directional_signed_weight": _fmt(signed),
        "dependency_adjusted_research_score": _fmt(base_score),
        "bonus_adjusted_signed_weight": _fmt(boosted_signed),
        "score_is_research_diagnostic_only": True,
        "directional_decision_created": False,
        "live_money_execution_allowed": False,
    }
    return result


def build_evidence_dependency_engine(
    *,
    signals: Sequence[Mapping[str, Any]],
    historical_rows: Sequence[Mapping[str, Any]],
    as_of_utc: datetime | str,
    min_correlation_n: int = CORRELATION_MIN_N,
    lookback_cycles: int = 120,
) -> dict[str, Any]:
    """Build the complete Build-20 dependency packet."""

    graph = evidence_family_graph()
    diagnostics = rolling_dependency_diagnostics(
        signals=signals,
        historical_rows=historical_rows,
        as_of_utc=as_of_utc,
        min_n=min_correlation_n,
        lookback_cycles=lookback_cycles,
    )
    adjustments = apply_dependency_adjustments(
        signals=signals,
        diagnostics=diagnostics,
    )
    normalized = [_normalise_signal(item) for item in signals]
    exact_groups: dict[str, list[str]] = defaultdict(list)
    for item in normalized:
        key = _digest(
            {
                "evidence_identity": item["evidence_identity"],
                "vote": item["vote"],
            }
        )
        exact_groups[key].append(item["signal_id"])
    duplicate_groups = [
        {
            "duplicate_group_id": key,
            "signal_ids": sorted(ids),
            "signal_count": len(ids),
        }
        for key, ids in sorted(exact_groups.items())
        if len(ids) > 1
    ]

    body = {
        "engine_version": EVIDENCE_DEPENDENCY_ENGINE_VERSION,
        "as_of_utc": _utc(as_of_utc, name="as_of_utc").isoformat(),
        "family_graph": graph,
        "rolling_diagnostics": diagnostics,
        "duplicate_groups": duplicate_groups,
        "adjustments": adjustments,
        "exact_duplicates_do_not_add_weight": True,
        "same_correlation_group_damped": True,
        "highly_correlated_same_parent_damped": True,
        "parent_incremental_cap_fraction": _fmt(PARENT_GROUP_INCREMENTAL_CAP),
        "independent_family_bonus_only_when_justified": True,
        "outcomes_used": False,
        "future_values_used": False,
        "formal_forward_evidence_created": False,
        "live_money_execution_allowed": False,
    }
    body["engine_digest"] = _digest(body)
    return body


def verify_evidence_dependency_engine(value: Mapping[str, Any]) -> bool:
    body = dict(value)
    supplied = str(body.pop("engine_digest", ""))
    return (
        bool(supplied)
        and supplied == _digest(body)
        and body.get("engine_version") == EVIDENCE_DEPENDENCY_ENGINE_VERSION
        and body.get("outcomes_used") is False
        and body.get("future_values_used") is False
        and body.get("live_money_execution_allowed") is False
        and isinstance(body.get("family_graph"), Mapping)
        and verify_evidence_family_graph(body["family_graph"])
        and isinstance(body.get("rolling_diagnostics"), Mapping)
        and verify_rolling_dependency_diagnostics(body["rolling_diagnostics"])
    )


__all__ = [
    "CORRELATION_MIN_N",
    "EVIDENCE_DEPENDENCY_ENGINE_VERSION",
    "EVIDENCE_FAMILY_GRAPH_VERSION",
    "FAMILY_PARENT",
    "HIGH_CORRELATION_THRESHOLD",
    "PARENT_CHILD_RELATIONSHIPS",
    "ROLLING_DEPENDENCY_DIAGNOSTIC_VERSION",
    "apply_dependency_adjustments",
    "build_evidence_dependency_engine",
    "evidence_family_graph",
    "extract_dependency_signals",
    "rolling_dependency_diagnostics",
    "verify_evidence_dependency_engine",
    "verify_evidence_family_graph",
    "verify_rolling_dependency_diagnostics",
]
