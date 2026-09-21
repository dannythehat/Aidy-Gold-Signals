"""Build 17: Futures / Microstructure Expert for AIDY Gold.

Phase A only. Uses genuine historical COMEX GC TBBO-derived features and
official CME daily contract/OI context to test incremental value beyond spot
OHLC. No depth claim, paid activation, live authority or feature promotion is
created by this module.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from aidy.cme_contract_intelligence import (
    build_contract_roll_state,
    verify_contract_roll_state,
)
from aidy.gc_microstructure import (
    BASELINE_VERSION,
    MICROSTRUCTURE_VERSION,
    TBBO_SCHEMA,
    verify_weekday_clock_baseline,
)
from aidy.gold_expert_gate_contract import build_expert_gate_packet, verify_expert_gate_packet
from aidy.gold_expert_trust import (
    build_trust_envelope,
    build_trust_scopes,
    select_conditional_trust,
)

FUTURES_MICROSTRUCTURE_EXPERT_VERSION = "aidy_gold_futures_microstructure_expert_v1"
FUTURES_MICROSTRUCTURE_GATE_ID = "futures_microstructure_expert"
FUTURES_MICROSTRUCTURE_TARGET_HORIZON_MINUTES = 15
INCREMENTAL_HOLDOUT_MINIMUM_N = 30

FUTURES_MICROSTRUCTURE_TRUST_REDUCED_CONTEXTS = (
    {
        "name": "microstructure_state",
        "mini_dimensions": ["volume_state", "spread_state", "flow_state", "vwap_state"],
        "global_dimensions": ["volatility_state"],
        "minimum_sample_n": 12,
    },
    {
        "name": "roll_context",
        "mini_dimensions": ["roll_state", "active_contract_alignment"],
        "global_dimensions": [],
        "minimum_sample_n": 10,
    },
    {
        "name": "incremental_value",
        "mini_dimensions": ["holdout_state", "microstructure_state"],
        "global_dimensions": [],
        "minimum_sample_n": 8,
    },
)


def _utc(value: datetime | str) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError("futures/microstructure timestamps must be timezone-aware")
    return parsed.astimezone(UTC)


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _fmt(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value.quantize(Decimal("0.000001")), "f")


def _z_state(value: Any, *, positive_label: str, negative_label: str) -> str:
    parsed = _decimal(value)
    if parsed is None:
        return "unknown"
    if parsed >= Decimal(2):
        return f"extreme_{positive_label}"
    if parsed >= Decimal(1):
        return positive_label
    if parsed <= Decimal(-2):
        return f"extreme_{negative_label}"
    if parsed <= Decimal(-1):
        return negative_label
    return "normal"


def _verify_microstructure_minute(minute: Mapping[str, Any]) -> bool:
    required = {
        "microstructure_version",
        "minute_utc",
        "contract_symbol",
        "trade_volume",
        "mean_spread_bps",
        "anchored_vwap",
        "vwap_distance_bps",
        "genuine_exchange_trade_volume",
        "genuine_pretrade_bbo_spread",
        "signed_trade_flow_only",
        "unknown_aggressor_side_imputed",
        "depth_claimed",
        "order_book_imbalance_claimed",
        "provenance_class",
        "pit_eligible",
    }
    if not required.issubset(minute):
        return False
    try:
        _utc(str(minute["minute_utc"]))
    except ValueError:
        return False
    return (
        minute.get("microstructure_version") == MICROSTRUCTURE_VERSION
        and _decimal(minute.get("trade_volume")) is not None
        and _decimal(minute.get("mean_spread_bps")) is not None
        and _decimal(minute.get("anchored_vwap")) is not None
        and _decimal(minute.get("vwap_distance_bps")) is not None
        and minute.get("genuine_exchange_trade_volume") is True
        and minute.get("genuine_pretrade_bbo_spread") is True
        and minute.get("signed_trade_flow_only") is True
        and minute.get("unknown_aggressor_side_imputed") is False
        and minute.get("depth_claimed") is False
        and minute.get("order_book_imbalance_claimed") is False
    )


def _verify_normalized(
    normalized: Mapping[str, Any],
    baseline: Mapping[str, Any],
) -> bool:
    return (
        verify_weekday_clock_baseline(baseline)
        and baseline.get("baseline_version") == BASELINE_VERSION
        and normalized.get("baseline_digest") == baseline.get("baseline_digest")
        and normalized.get("state") in {"known", "baseline_insufficient", "baseline_missing"}
        and normalized.get("ordinary_session_activity_can_count_as_alpha") is False
        and normalized.get("outcome_fields_used_for_normalization") is False
    )


def _feature_context(
    minute: Mapping[str, Any],
    normalized: Mapping[str, Any],
) -> dict[str, Any]:
    signed = _decimal(minute.get("signed_trade_imbalance"))
    flow_state = (
        "unknown_aggressor_side_insufficient"
        if signed is None
        else "buy_aggressor_dominant"
        if signed >= Decimal("0.25")
        else "sell_aggressor_dominant"
        if signed <= Decimal("-0.25")
        else "balanced"
    )
    return {
        "state": "known" if normalized.get("state") == "known" else str(normalized.get("state")),
        "contract_symbol": minute.get("contract_symbol"),
        "trade_volume": minute.get("trade_volume"),
        "signed_trade_imbalance": minute.get("signed_trade_imbalance"),
        "mean_spread_bps": minute.get("mean_spread_bps"),
        "anchored_vwap": minute.get("anchored_vwap"),
        "vwap_distance_bps": minute.get("vwap_distance_bps"),
        "volume_z": normalized.get("volume_z"),
        "spread_z": normalized.get("spread_z"),
        "signed_trade_imbalance_z": normalized.get("signed_trade_imbalance_z"),
        "vwap_distance_z": normalized.get("vwap_distance_z"),
        "volume_state": _z_state(
            normalized.get("volume_z"),
            positive_label="high_volume",
            negative_label="low_volume",
        ),
        "spread_state": _z_state(
            normalized.get("spread_z"),
            positive_label="wide_spread",
            negative_label="tight_spread",
        ),
        "flow_state": flow_state,
        "vwap_state": _z_state(
            normalized.get("vwap_distance_z"),
            positive_label="above_vwap",
            negative_label="below_vwap",
        ),
        "genuine_trade_volume": True,
        "genuine_pretrade_bbo_spread": True,
        "aggressor_side_from_databento_when_known": True,
        "unknown_aggressor_side_imputed": False,
        "depth_claimed": False,
        "order_book_imbalance_claimed": False,
    }


def _validate_split_binding(binding: Mapping[str, Any]) -> None:
    if binding.get("manifest_version") != "aidy_chronological_split_manifest_v1":
        raise ValueError("Build 17 requires the chronological split manifest")
    if binding.get("purge_required") is not True:
        raise ValueError("Build 17 retrospective holdout requires purge")
    if binding.get("embargo_required") is not True:
        raise ValueError("Build 17 retrospective holdout requires embargo")
    if binding.get("holdout_tuning_allowed") is not False:
        raise ValueError("Build 17 cannot tune on holdout")


def summarise_incremental_holdout(
    rows: Sequence[Mapping[str, Any]],
    *,
    split_binding: Mapping[str, Any],
    minimum_independent_n: int = INCREMENTAL_HOLDOUT_MINIMUM_N,
) -> dict[str, Any]:
    """Compare frozen spot-only versus spot+microstructure holdout accuracy."""

    _validate_split_binding(split_binding)
    seen: set[str] = set()
    usable: list[tuple[int, int]] = []
    for row in rows:
        if str(row.get("split") or "") != "holdout":
            continue
        episode_id = str(row.get("independent_episode_id") or "")
        if not episode_id or episode_id in seen:
            continue
        spot = row.get("spot_ohlc_correct")
        rich = row.get("spot_plus_microstructure_correct")
        if spot not in {0, 1} or rich not in {0, 1}:
            continue
        seen.add(episode_id)
        usable.append((int(spot), int(rich)))

    sample_n = len(usable)
    spot_correct = sum(item[0] for item in usable)
    rich_correct = sum(item[1] for item in usable)
    spot_accuracy = Decimal(spot_correct) / Decimal(sample_n) if sample_n else None
    rich_accuracy = Decimal(rich_correct) / Decimal(sample_n) if sample_n else None
    delta = (
        rich_accuracy - spot_accuracy
        if spot_accuracy is not None and rich_accuracy is not None
        else None
    )
    if sample_n < minimum_independent_n:
        state = "insufficient"
    elif delta is not None and delta > 0:
        state = "incremental_value_observed"
    elif delta == 0:
        state = "null_no_incremental_value"
    else:
        state = "microstructure_underperformed_spot"

    return {
        "state": state,
        "sample_n": sample_n,
        "minimum_independent_n": minimum_independent_n,
        "spot_ohlc_accuracy": _fmt(spot_accuracy),
        "spot_plus_microstructure_accuracy": _fmt(rich_accuracy),
        "incremental_accuracy": _fmt(delta),
        "split_digest": split_binding.get("split_digest"),
        "purge_required": True,
        "embargo_required": True,
        "holdout_tuning_allowed": False,
        "independent_episode_ids_required": True,
        "retrospective_holdout_only": True,
        "statistically_validated": False,
        "gate_promoted": False,
        "live_weight_granted": False,
        "paid_feed_activation_allowed": False,
    }


def _roll_context(
    *,
    as_of: datetime,
    daily_contract_records: Sequence[Mapping[str, Any]],
    contract_calendar_records: Sequence[Mapping[str, Any]],
    micro_contract_symbol: str,
) -> dict[str, Any]:
    state = build_contract_roll_state(
        as_of=as_of,
        daily_records=daily_contract_records,
        calendar_records=contract_calendar_records,
    )
    if not verify_contract_roll_state(state):
        raise ValueError("invalid CME contract roll state")
    active_contract = state.get("active_contract")
    alignment = (
        "aligned_to_active_contract"
        if active_contract == micro_contract_symbol
        else "micro_contract_differs_from_oi_leader"
        if active_contract
        else "unknown"
    )
    return {
        **state,
        "microstructure_contract_symbol": micro_contract_symbol,
        "active_contract_alignment": alignment,
        "open_interest_is_intraday": False,
        "open_interest_frequency": state.get("open_interest_frequency"),
    }


def _entitlement_contract() -> dict[str, Any]:
    return {
        "provider": "Databento",
        "dataset": "GLBX.MDP3",
        "schema": TBBO_SCHEMA,
        "historical_phase_a_only": True,
        "approved_features": [
            "genuine_trade_volume",
            "pretrade_best_bid_ask_spread",
            "known_aggressor_signed_trade_flow",
            "trade_price_size_vwap",
            "session_anchored_vwap",
        ],
        "bid_ask_sizes_do_not_authorize_depth_claim": True,
        "full_depth_claimed": False,
        "order_book_imbalance_claimed": False,
        "l2_claimed": False,
        "l3_claimed": False,
        "mbo_claimed": False,
        "mbp10_claimed": False,
    }


def _phase_b_policy() -> dict[str, Any]:
    return {
        "status": "not_activated",
        "live_or_delayed_paid_feed_enabled": False,
        "recurring_paid_data_enabled": False,
        "owner_approval_required": True,
        "price_and_entitlement_review_required": True,
        "pit_contract_required_before_live_use": True,
        "phase_a_incremental_value_required": True,
        "feature_count_alone_can_justify_activation": False,
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
        "observation": dict(observation),
        "explanation": explanation,
    }


def _subject_keys(packet: Mapping[str, Any]) -> list[str]:
    keys = [f"gate:{packet['gate_id']}"]
    keys.extend(f"subcalculator:{item['calculator_id']}" for item in packet["subcalculators"])
    return keys


def build_futures_microstructure_expert(
    *,
    global_environment: Mapping[str, Any],
    current_microstructure_minute: Mapping[str, Any],
    normalized_microstructure: Mapping[str, Any],
    weekday_clock_baseline: Mapping[str, Any],
    daily_contract_records: Sequence[Mapping[str, Any]],
    contract_calendar_records: Sequence[Mapping[str, Any]],
    retrospective_holdout_rows: Sequence[Mapping[str, Any]],
    holdout_split_binding: Mapping[str, Any],
    trust_score_rows_by_subject: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Build one frozen Phase-A futures/microstructure context packet."""

    exact = global_environment.get("exact_facts")
    exact = exact if isinstance(exact, Mapping) else {}
    as_of = _utc(str(exact.get("as_of_utc")))

    if not _verify_microstructure_minute(current_microstructure_minute):
        raise ValueError("Build 17 requires a genuine Day-42 GC microstructure minute")
    if not _verify_normalized(normalized_microstructure, weekday_clock_baseline):
        raise ValueError("Build 17 requires a valid outcome-blind weekday/clock normalization")

    minute_time = _utc(str(current_microstructure_minute["minute_utc"]))
    if minute_time > as_of:
        raise ValueError("microstructure minute is from the future")

    feature = _feature_context(current_microstructure_minute, normalized_microstructure)
    roll = _roll_context(
        as_of=as_of,
        daily_contract_records=daily_contract_records,
        contract_calendar_records=contract_calendar_records,
        micro_contract_symbol=str(current_microstructure_minute["contract_symbol"]),
    )
    holdout = summarise_incremental_holdout(
        retrospective_holdout_rows,
        split_binding=holdout_split_binding,
    )
    entitlement = _entitlement_contract()
    phase_b = _phase_b_policy()

    evidence_inputs = [
        {
            "evidence_id": "futures_microstructure_feature_evidence",
            "source": "aidy_gc_microstructure_v1",
            "path": "futures_microstructure.current",
            "observed_at_utc": as_of,
            "state": "known" if feature["state"] == "known" else "unknown",
            "value": feature,
            "provenance": {
                "historical_databento_tbbo": True,
                "genuine_exchange_trade_volume": True,
                "genuine_pretrade_bbo": True,
                "unknown_aggressor_side_imputed": False,
                "depth_claimed": False,
                "future_values_used": False,
            },
        },
        {
            "evidence_id": "futures_roll_oi_evidence",
            "source": "aidy_cme_gold_contract_intelligence_v1",
            "path": "futures_microstructure.roll_oi",
            "observed_at_utc": as_of,
            "state": "known" if roll.get("state") == "known" else "unknown",
            "value": roll,
            "provenance": {
                "official_cme_daily_oi": True,
                "intraday_open_interest_inferred": False,
                "future_values_used": False,
            },
        },
        {
            "evidence_id": "futures_incremental_holdout_evidence",
            "source": "build17_retrospective_holdout_ablation",
            "path": "futures_microstructure.incremental_holdout",
            "observed_at_utc": as_of,
            "state": "known" if holdout["state"] != "insufficient" else "unknown",
            "value": holdout,
            "provenance": {
                "retrospective_holdout_only": True,
                "purge_required": True,
                "embargo_required": True,
                "holdout_tuning_allowed": False,
                "future_values_used": False,
            },
        },
        {
            "evidence_id": "futures_entitlement_evidence",
            "source": "day42_databento_entitlement_contract",
            "path": "futures_microstructure.entitlement",
            "observed_at_utc": as_of,
            "state": "known",
            "value": {"entitlement": entitlement, "phase_b": phase_b},
            "provenance": {
                "paid_activation_performed": False,
                "depth_claimed": False,
                "future_values_used": False,
            },
        },
    ]

    calculators = [
        _context_calculator(
            calculator_id="futures_gc_flow_volume_vwap",
            dependency_family="futures_microstructure",
            evidence_ref="futures_microstructure_feature_evidence",
            known=feature["state"] == "known",
            observation=feature,
            explanation=(
                "Genuine historical GC trade volume, known-side aggressor flow, BBO spread "
                "and VWAP are normalized to the matched weekday/clock baseline. No depth is claimed."
            ),
        ),
        _context_calculator(
            calculator_id="futures_gc_roll_oi",
            dependency_family="futures_microstructure",
            evidence_ref="futures_roll_oi_evidence",
            known=roll.get("state") == "known",
            observation=roll,
            explanation=(
                "Official CME open interest remains daily T+1 contract context; intraday OI "
                "is never inferred. Contract/roll state is explicit."
            ),
        ),
        _context_calculator(
            calculator_id="futures_incremental_holdout",
            dependency_family="futures_microstructure",
            evidence_ref="futures_incremental_holdout_evidence",
            known=holdout["state"] != "insufficient",
            observation=holdout,
            explanation=(
                "Frozen retrospective holdout compares spot-OHLC baseline accuracy with "
                "spot+microstructure using independent episodes, purge and embargo."
            ),
        ),
        _context_calculator(
            calculator_id="futures_entitlement_boundary",
            dependency_family="data_quality",
            evidence_ref="futures_entitlement_evidence",
            known=True,
            observation={"entitlement": entitlement, "phase_b": phase_b},
            explanation=(
                "Feature definitions are restricted to the historical TBBO entitlement. "
                "Phase-B paid/live activation remains OFF and requires owner approval."
            ),
        ),
    ]

    dimensions = global_environment["learning_dimensions"]
    mini_environment = {
        "session": dimensions["session"],
        "session_phase": dimensions["session_phase"],
        "volatility_state": dimensions["volatility_state"],
        "microstructure_state": feature["state"],
        "volume_state": feature["volume_state"],
        "spread_state": feature["spread_state"],
        "flow_state": feature["flow_state"],
        "vwap_state": feature["vwap_state"],
        "roll_state": str(roll.get("roll_state") or "unknown"),
        "active_contract_alignment": roll["active_contract_alignment"],
        "holdout_state": holdout["state"],
    }

    packet = build_expert_gate_packet(
        gate_id=FUTURES_MICROSTRUCTURE_GATE_ID,
        gate_version=FUTURES_MICROSTRUCTURE_EXPERT_VERSION,
        gate_mode="context_only",
        dependency_family="futures_microstructure",
        target_horizon_minutes=FUTURES_MICROSTRUCTURE_TARGET_HORIZON_MINUTES,
        as_of_utc=as_of,
        global_environment=global_environment,
        mini_environment=mini_environment,
        evidence_inputs=evidence_inputs,
        subcalculators=calculators,
        conclusion="context_only",
        internal_conviction=None,
        explanation_parts=(
            {
                "text": (
                    f"GC microstructure={feature['state']}; roll={roll.get('roll_state')}; "
                    f"retrospective holdout={holdout['state']}."
                ),
                "source_refs": [
                    "calc:futures_gc_flow_volume_vwap",
                    "calc:futures_gc_roll_oi",
                    "calc:futures_incremental_holdout",
                ],
            },
            {
                "text": (
                    "Build 17 Phase A is retrospective research only. No depth claim, live "
                    "feed activation, paid subscription, formal-forward evidence or live weight is created."
                ),
                "source_refs": ["calc:futures_entitlement_boundary"],
            },
        ),
        contradictions=(),
    )
    if not verify_expert_gate_packet(packet):
        raise ValueError("constructed Futures/Microstructure packet failed Build-2 verification")

    scopes = build_trust_scopes(
        packet=packet,
        reduced_contexts=FUTURES_MICROSTRUCTURE_TRUST_REDUCED_CONTEXTS,
    )
    rows_by_subject = trust_score_rows_by_subject or {}
    profiles = {
        key: select_conditional_trust(score_rows=rows_by_subject.get(key, ()), scopes=scopes)
        for key in _subject_keys(packet)
    }
    trust_envelope = build_trust_envelope(packet=packet, profiles_by_subject=profiles)

    return {
        "expert_version": FUTURES_MICROSTRUCTURE_EXPERT_VERSION,
        "expert_packet": packet,
        "microstructure": feature,
        "contract_roll_oi": roll,
        "incremental_holdout": holdout,
        "entitlement_contract": entitlement,
        "phase_b_policy": phase_b,
        "trust_scopes": scopes,
        "trust_envelope": trust_envelope,
        "research_phase": "phase_a_retrospective",
        "statistically_validated": False,
        "formal_forward_evidence_created": False,
        "paid_feed_activated": False,
        "future_values_used": False,
        "live_money_execution_allowed": False,
    }


__all__ = [
    "FUTURES_MICROSTRUCTURE_EXPERT_VERSION",
    "FUTURES_MICROSTRUCTURE_GATE_ID",
    "FUTURES_MICROSTRUCTURE_TARGET_HORIZON_MINUTES",
    "FUTURES_MICROSTRUCTURE_TRUST_REDUCED_CONTEXTS",
    "INCREMENTAL_HOLDOUT_MINIMUM_N",
    "build_futures_microstructure_expert",
    "summarise_incremental_holdout",
]
