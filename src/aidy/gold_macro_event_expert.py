"""Build 15: Macro / Event Expert for AIDY Gold.

Wraps the accepted official macro-event stack in a Gold-specific specialist.
The expert is context-only. It preserves point-in-time timing, first-print /
revision separation, independent Gold event tiers and matched no-news controls.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any

from aidy.feature_engine import Candle, normalize_candles
from aidy.gold_expert_gate_contract import build_expert_gate_packet, verify_expert_gate_packet
from aidy.gold_expert_trust import (
    build_trust_envelope,
    build_trust_scopes,
    select_conditional_trust,
)
from aidy.macro_event_intelligence import (
    MIN_INDEPENDENT_EPISODES_PER_CLASS,
    build_pre_event_features,
    build_surprise_state,
    select_schedule_as_of,
    verify_j4_j15_study,
    verify_schedule_observation,
)

MACRO_EVENT_EXPERT_VERSION = "aidy_gold_macro_event_expert_v1"
MACRO_EVENT_GATE_ID = "macro_event_expert"
MACRO_EVENT_TARGET_HORIZON_MINUTES = 15
STANDARDIZED_SURPRISE_MIN_N = 20
CONDITIONAL_RESPONSE_MIN_N = 20
NO_NEWS_CONTROL_MIN_N = 20

MACRO_EVENT_TRUST_REDUCED_CONTEXTS = (
    {
        "name": "event_class_tier",
        "mini_dimensions": [
            "event_class",
            "gold_event_tier",
            "event_timing_state",
        ],
        "global_dimensions": [],
        "minimum_sample_n": 12,
    },
    {
        "name": "event_surprise",
        "mini_dimensions": [
            "event_class",
            "surprise_state",
            "standardized_surprise_band",
            "cluster_state",
        ],
        "global_dimensions": [],
        "minimum_sample_n": 10,
    },
    {
        "name": "event_response",
        "mini_dimensions": [
            "event_class",
            "historical_response_state",
            "post_release_confirmation_state",
        ],
        "global_dimensions": ["volatility_state"],
        "minimum_sample_n": 8,
    },
)


def _utc(value: datetime | str) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError("macro-event timestamps must be timezone-aware")
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


def _mean(values: Sequence[Decimal]) -> Decimal | None:
    if not values:
        return None
    return sum(values, Decimal(0)) / Decimal(len(values))


def _sample_std(values: Sequence[Decimal]) -> Decimal | None:
    if len(values) < 2:
        return None
    mean = _mean(values)
    assert mean is not None
    variance = sum((value - mean) ** 2 for value in values) / Decimal(len(values) - 1)
    with localcontext() as ctx:
        ctx.prec = 40
        return variance.sqrt()


def _median(values: Sequence[Decimal]) -> Decimal | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / Decimal(2)


def _surprise_band(value: Decimal | None) -> str:
    if value is None:
        return "unknown"
    absolute = abs(value)
    if absolute < Decimal("0.50"):
        return "small"
    if absolute < Decimal("1.00"):
        return "moderate"
    if absolute < Decimal("2.00"):
        return "large"
    return "extreme"


def _standardized_surprise(
    *,
    event_class: str,
    unit: str | None,
    raw_surprise: Decimal | None,
    historical_rows: Sequence[Mapping[str, Any]],
    as_of: datetime,
) -> dict[str, Any]:
    if raw_surprise is None or not unit:
        return {
            "state": "unknown_no_raw_surprise",
            "sample_n": 0,
            "z_score": None,
            "band": "unknown",
            "direction": "unknown",
        }

    values: list[Decimal] = []
    episode_ids: set[str] = set()
    for row in historical_rows:
        if str(row.get("event_class") or "") != event_class:
            continue
        if str(row.get("unit") or "") != unit:
            continue
        observed = row.get("first_observed_at")
        if observed is None:
            continue
        try:
            observed_at = _utc(str(observed))
        except ValueError:
            continue
        if observed_at >= as_of or row.get("pit_reconstructable") is not True:
            continue
        episode_id = str(row.get("independent_episode_id") or "")
        value = _decimal(row.get("surprise_value"))
        if not episode_id or value is None:
            continue
        if episode_id in episode_ids:
            continue
        episode_ids.add(episode_id)
        values.append(value)

    if len(values) < STANDARDIZED_SURPRISE_MIN_N:
        return {
            "state": "unknown_insufficient_history",
            "sample_n": len(values),
            "minimum_sample_n": STANDARDIZED_SURPRISE_MIN_N,
            "z_score": None,
            "band": "unknown",
            "direction": "positive" if raw_surprise > 0 else "negative" if raw_surprise < 0 else "zero",
        }

    mean = _mean(values)
    std = _sample_std(values)
    if mean is None or std in {None, Decimal(0)}:
        return {
            "state": "unknown_zero_dispersion",
            "sample_n": len(values),
            "z_score": None,
            "band": "unknown",
            "direction": "positive" if raw_surprise > 0 else "negative" if raw_surprise < 0 else "zero",
        }
    z_score = (raw_surprise - mean) / std
    return {
        "state": "known",
        "sample_n": len(values),
        "minimum_sample_n": STANDARDIZED_SURPRISE_MIN_N,
        "historical_mean": _fmt(mean),
        "historical_sample_std": _fmt(std),
        "z_score": _fmt(z_score),
        "band": _surprise_band(z_score),
        "direction": "positive" if z_score > 0 else "negative" if z_score < 0 else "zero",
    }


def _event_cluster(
    *,
    primary_schedule: Mapping[str, Any],
    schedule_records: Sequence[Mapping[str, Any]],
    as_of: datetime,
) -> dict[str, Any]:
    scheduled_at = primary_schedule.get("scheduled_at")
    if scheduled_at is None:
        return {
            "state": "unknown_primary_date_only",
            "event_count_30m": 0,
            "event_count_60m": 0,
            "neighbor_event_classes": [],
        }
    center = _utc(str(scheduled_at))
    selected = select_schedule_as_of(schedule_records, as_of=as_of)
    neighbors: list[dict[str, Any]] = []
    for row in selected:
        row_time = row.get("scheduled_at")
        if row_time is None:
            continue
        stamp = _utc(str(row_time))
        if row.get("schedule_digest") == primary_schedule.get("schedule_digest"):
            continue
        distance = abs((stamp - center).total_seconds()) / 60
        if distance <= 60:
            neighbors.append(
                {
                    "event_class": row.get("event_class"),
                    "scheduled_at": stamp.isoformat(),
                    "distance_minutes": _fmt(Decimal(str(distance))),
                }
            )
    count_30 = sum(
        1
        for row in neighbors
        if (_decimal(row.get("distance_minutes")) or Decimal(999)) <= Decimal(30)
    )
    if count_30 >= 2:
        state = "dense_cluster"
    elif count_30 == 1:
        state = "clustered"
    elif neighbors:
        state = "nearby_event_within_60m"
    else:
        state = "isolated_event"
    return {
        "state": state,
        "event_count_30m": count_30,
        "event_count_60m": len(neighbors),
        "neighbor_event_classes": sorted(
            str(row["event_class"]) for row in neighbors if row.get("event_class")
        ),
        "neighbors": neighbors,
    }


def _completed_m1(
    rows: Sequence[Mapping[str, Any]],
    *,
    as_of: datetime,
    mode: str,
) -> list[Candle]:
    grouped = normalize_candles(rows, as_of=as_of, symbol="XAUUSD", mode=mode)
    return [
        candle
        for candle in grouped["M1"]
        if candle.open_time_utc + timedelta(minutes=1) <= as_of
    ]


def _post_release_confirmation(
    *,
    schedule: Mapping[str, Any],
    candle_rows: Sequence[Mapping[str, Any]],
    as_of: datetime,
    mode: str,
) -> dict[str, Any]:
    scheduled_at = schedule.get("scheduled_at")
    if scheduled_at is None:
        return {
            "state": "unknown_release_time",
            "observed_minutes": 0,
            "return_5m_bps": None,
            "return_15m_bps": None,
        }
    event_at = _utc(str(scheduled_at))
    if as_of <= event_at:
        return {
            "state": "pre_release",
            "observed_minutes": 0,
            "return_5m_bps": None,
            "return_15m_bps": None,
        }

    candles = _completed_m1(candle_rows, as_of=as_of, mode=mode)
    after = [
        candle
        for candle in candles
        if candle.open_time_utc >= event_at
        and candle.open_time_utc < event_at + timedelta(minutes=15)
    ]
    if not after:
        return {
            "state": "unknown_no_post_release_bars",
            "observed_minutes": 0,
            "return_5m_bps": None,
            "return_15m_bps": None,
        }
    after.sort(key=lambda item: item.open_time_utc)
    first = after[0].open
    if first <= 0:
        return {
            "state": "unknown_invalid_price",
            "observed_minutes": len(after),
            "return_5m_bps": None,
            "return_15m_bps": None,
        }

    def ret(count: int) -> Decimal | None:
        if len(after) < count:
            return None
        return (after[count - 1].close / first - Decimal(1)) * Decimal(10000)

    ret_5 = ret(5)
    ret_15 = ret(15)
    reference = ret_15 if ret_15 is not None else ret_5
    if reference is None:
        state = "forming"
    elif abs(reference) < Decimal(1):
        state = "muted"
    elif reference > 0:
        state = "gold_up"
    else:
        state = "gold_down"
    return {
        "state": state,
        "observed_minutes": len(after),
        "return_5m_bps": _fmt(ret_5),
        "return_15m_bps": _fmt(ret_15),
        "future_values_used": False,
    }


def _conditional_response(
    *,
    event_class: str,
    standardized_surprise: Mapping[str, Any],
    historical_rows: Sequence[Mapping[str, Any]],
    as_of: datetime,
) -> dict[str, Any]:
    surprise_direction = str(standardized_surprise.get("direction") or "unknown")
    if surprise_direction not in {"positive", "negative"}:
        return {
            "state": "unknown_no_surprise_direction",
            "sample_n": 0,
            "median_gold_return_15m_bps": None,
        }

    rows: list[tuple[str, Decimal]] = []
    seen: set[str] = set()
    for row in historical_rows:
        if str(row.get("event_class") or "") != event_class:
            continue
        if str(row.get("standardized_surprise_direction") or "") != surprise_direction:
            continue
        observed = row.get("first_observed_at")
        if observed is None:
            continue
        try:
            observed_at = _utc(str(observed))
        except ValueError:
            continue
        if observed_at >= as_of or row.get("pit_reconstructable") is not True:
            continue
        episode_id = str(row.get("independent_episode_id") or "")
        gold_return = _decimal(row.get("gold_return_15m_bps"))
        if not episode_id or gold_return is None or episode_id in seen:
            continue
        seen.add(episode_id)
        rows.append((episode_id, gold_return))

    values = [item[1] for item in rows]
    if len(values) < CONDITIONAL_RESPONSE_MIN_N:
        return {
            "state": "unknown_insufficient_history",
            "sample_n": len(values),
            "minimum_sample_n": CONDITIONAL_RESPONSE_MIN_N,
            "median_gold_return_15m_bps": None,
        }
    med = _median(values)
    assert med is not None
    positive_share = Decimal(sum(value > 0 for value in values)) / Decimal(len(values))
    if abs(med) < Decimal(1):
        direction = "muted"
    elif med > 0:
        direction = "gold_up"
    else:
        direction = "gold_down"
    return {
        "state": "known",
        "sample_n": len(values),
        "minimum_sample_n": CONDITIONAL_RESPONSE_MIN_N,
        "median_gold_return_15m_bps": _fmt(med),
        "positive_return_share": _fmt(positive_share),
        "historical_response_direction": direction,
        "trade_pnl_used": False,
        "predictive_edge_claimed": False,
    }


def _no_news_control(
    *,
    control_rows: Sequence[Mapping[str, Any]],
    as_of: datetime,
) -> dict[str, Any]:
    values: list[Decimal] = []
    seen: set[str] = set()
    for row in control_rows:
        if str(row.get("control_type") or "") != "matched_no_news":
            continue
        observed = row.get("first_observed_at")
        if observed is None:
            continue
        try:
            observed_at = _utc(str(observed))
        except ValueError:
            continue
        if observed_at >= as_of or row.get("pit_reconstructable") is not True:
            continue
        control_id = str(row.get("control_id") or "")
        value = _decimal(row.get("abs_gold_return_15m_bps"))
        if not control_id or value is None or control_id in seen:
            continue
        seen.add(control_id)
        values.append(value)
    if len(values) < NO_NEWS_CONTROL_MIN_N:
        return {
            "state": "unknown_insufficient_control",
            "sample_n": len(values),
            "minimum_sample_n": NO_NEWS_CONTROL_MIN_N,
            "median_abs_gold_return_15m_bps": None,
        }
    med = _median(values)
    return {
        "state": "known",
        "sample_n": len(values),
        "minimum_sample_n": NO_NEWS_CONTROL_MIN_N,
        "median_abs_gold_return_15m_bps": _fmt(med),
        "control_is_no_news": True,
    }


def _tier_for_event(
    *,
    tier_study: Mapping[str, Any],
    event_class: str,
) -> dict[str, Any]:
    if not verify_j4_j15_study(tier_study):
        raise ValueError("macro expert requires a valid independent Gold event-tier study")
    row = tier_study["class_results"].get(event_class)
    if not isinstance(row, Mapping):
        return {
            "state": "unknown_event_class_not_studied",
            "tier": "unclassified_insufficient_evidence",
            "independent_episode_n": 0,
        }
    return {
        "state": "known" if str(row.get("tier_state") or "").startswith("tier_") else "unknown",
        "tier": row.get("tier_state"),
        "independent_episode_n": int(row.get("independent_episode_n") or 0),
        "minimum_independent_episode_n": MIN_INDEPENDENT_EPISODES_PER_CLASS,
        "trade_pnl_used": tier_study.get("trade_pnl_used") is True,
        "vendor_importance_label_used": False,
        "tier_source": "independent_gold_episodes",
    }


def _event_timing(
    *,
    schedule: Mapping[str, Any],
    as_of: datetime,
) -> str:
    scheduled_at = schedule.get("scheduled_at")
    if scheduled_at is None:
        return "unknown_release_time"
    delta_minutes = (as_of - _utc(str(scheduled_at))).total_seconds() / 60
    if delta_minutes < -60:
        return "more_than_60m_pre_event"
    if delta_minutes < 0:
        return "within_60m_pre_event"
    if delta_minutes <= 15:
        return "first_15m_post_event"
    if delta_minutes <= 60:
        return "within_60m_post_event"
    return "post_event_gt60m"


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
    keys.extend(
        f"subcalculator:{item['calculator_id']}"
        for item in packet["subcalculators"]
    )
    return keys


def build_macro_event_expert(
    *,
    global_environment: Mapping[str, Any],
    primary_schedule: Mapping[str, Any],
    schedule_records: Sequence[Mapping[str, Any]],
    consensus_observations: Sequence[Mapping[str, Any]],
    actual_observations: Sequence[Mapping[str, Any]],
    m1_candle_rows: Sequence[Mapping[str, Any]],
    tier_study: Mapping[str, Any],
    historical_surprise_rows: Sequence[Mapping[str, Any]],
    historical_response_rows: Sequence[Mapping[str, Any]],
    no_news_control_rows: Sequence[Mapping[str, Any]],
    mode: str = "retrospective",
    trust_score_rows_by_subject: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Build one frozen Gold macro/event specialist packet."""

    if not verify_schedule_observation(primary_schedule):
        raise ValueError("macro expert requires a valid official schedule observation")
    exact = global_environment.get("exact_facts")
    exact = exact if isinstance(exact, Mapping) else {}
    as_of = _utc(str(exact.get("as_of_utc")))
    selected = select_schedule_as_of([primary_schedule], as_of=as_of)
    if not selected:
        raise ValueError("primary schedule was not known at the requested as-of")
    primary = selected[0]
    event_class = str(primary["event_class"])
    scheduled_at = primary.get("scheduled_at")
    event_at = _utc(str(scheduled_at)) if scheduled_at else None

    if event_at is not None and as_of <= event_at:
        pre_event = build_pre_event_features(
            schedule=primary,
            candle_rows=m1_candle_rows,
            as_of=as_of,
        )
    else:
        pre_event = {
            "state": "not_pre_event_phase",
            "event_class": event_class,
            "future_values_used": False,
            "predictive_edge_claimed": False,
        }

    surprise = build_surprise_state(
        schedule=primary,
        consensus_observations=consensus_observations,
        actual_observations=actual_observations,
        as_of=as_of,
    )
    raw_surprise = _decimal(surprise.get("surprise_value"))
    unit = None
    first_digest = surprise.get("first_print_observation_digest")
    for row in actual_observations:
        if row.get("observation_digest") == first_digest:
            unit = str(row.get("unit") or "")
            break

    standardized = _standardized_surprise(
        event_class=event_class,
        unit=unit,
        raw_surprise=raw_surprise,
        historical_rows=historical_surprise_rows,
        as_of=as_of,
    )
    tier = _tier_for_event(tier_study=tier_study, event_class=event_class)
    cluster = _event_cluster(
        primary_schedule=primary,
        schedule_records=schedule_records,
        as_of=as_of,
    )
    post_release = _post_release_confirmation(
        schedule=primary,
        candle_rows=m1_candle_rows,
        as_of=as_of,
        mode=mode,
    )
    response = _conditional_response(
        event_class=event_class,
        standardized_surprise=standardized,
        historical_rows=historical_response_rows,
        as_of=as_of,
    )
    control = _no_news_control(
        control_rows=no_news_control_rows,
        as_of=as_of,
    )
    event_timing_state = _event_timing(schedule=primary, as_of=as_of)

    event_vs_control: dict[str, Any]
    response_median = _decimal(response.get("median_gold_return_15m_bps"))
    control_median = _decimal(control.get("median_abs_gold_return_15m_bps"))
    if response_median is not None and control_median is not None:
        event_vs_control = {
            "state": "known",
            "historical_event_abs_median_bps": _fmt(abs(response_median)),
            "no_news_abs_median_bps": _fmt(control_median),
            "event_minus_no_news_abs_bps": _fmt(abs(response_median) - control_median),
        }
    else:
        event_vs_control = {
            "state": "unknown",
            "historical_event_abs_median_bps": None,
            "no_news_abs_median_bps": _fmt(control_median),
            "event_minus_no_news_abs_bps": None,
        }

    evidence_inputs = [
        {
            "evidence_id": "macro_schedule_evidence",
            "source": "aidy_macro_event_intelligence_v2",
            "path": "macro_event.schedule_cluster_tier",
            "observed_at_utc": as_of,
            "state": "known",
            "value": {
                "schedule": primary,
                "tier": tier,
                "cluster": cluster,
                "event_timing_state": event_timing_state,
            },
            "provenance": {
                "official_schedule_verified": True,
                "vendor_importance_label_used": False,
                "future_values_used": False,
            },
        },
        {
            "evidence_id": "macro_surprise_evidence",
            "source": "aidy_forward_macro_surprise_v1",
            "path": "macro_event.surprise",
            "observed_at_utc": as_of,
            "state": "known" if surprise["surprise_state"] == "known" else "unknown",
            "value": {
                "surprise": surprise,
                "standardized_surprise": standardized,
            },
            "provenance": {
                "first_print_only_for_surprise": True,
                "revision_separate_from_first_print": True,
                "actual_visible_only_after_first_observed_at": True,
                "future_values_used": False,
            },
        },
        {
            "evidence_id": "macro_response_evidence",
            "source": "gold_event_response_history",
            "path": "macro_event.historical_and_post_release_response",
            "observed_at_utc": as_of,
            "state": "known" if response["state"] == "known" else "unknown",
            "value": {
                "post_release_confirmation": post_release,
                "historical_conditional_response": response,
                "no_news_control": control,
                "event_vs_no_news": event_vs_control,
            },
            "provenance": {
                "independent_episodes_only": True,
                "trade_pnl_used": False,
                "no_news_control_required": True,
                "future_values_used": False,
            },
        },
        {
            "evidence_id": "macro_pre_event_evidence",
            "source": "aidy_pre_event_structure_v1",
            "path": "macro_event.pre_event",
            "observed_at_utc": as_of,
            "state": "known" if pre_event.get("state") == "known" else "unknown",
            "value": pre_event,
            "provenance": {
                "actual_fields_used": False,
                "future_values_used": False,
            },
        },
    ]

    calculators = [
        _context_calculator(
            calculator_id="macro_event_tier_cluster",
            dependency_family="event",
            evidence_ref="macro_schedule_evidence",
            known=True,
            observation={
                "event_class": event_class,
                "tier": tier,
                "cluster": cluster,
                "event_timing_state": event_timing_state,
            },
            explanation=(
                "Event timing, cluster state and Gold-learned tier use official schedules and "
                "independent Gold episodes; vendor importance labels are not used."
            ),
        ),
        _context_calculator(
            calculator_id="macro_event_surprise",
            dependency_family="event",
            evidence_ref="macro_surprise_evidence",
            known=surprise["surprise_state"] == "known",
            observation={
                "surprise": surprise,
                "standardized_surprise": standardized,
            },
            explanation=(
                "Surprise uses the PIT-known consensus and immutable first print only. "
                "Later revisions remain separate."
            ),
        ),
        _context_calculator(
            calculator_id="macro_event_pre_event",
            dependency_family="event",
            evidence_ref="macro_pre_event_evidence",
            known=pre_event.get("state") == "known",
            observation=pre_event,
            explanation=(
                "Pre-event features use only closed Gold bars available before release and "
                "cannot see the actual print."
            ),
        ),
        _context_calculator(
            calculator_id="macro_event_response",
            dependency_family="event",
            evidence_ref="macro_response_evidence",
            known=response["state"] == "known",
            observation={
                "post_release_confirmation": post_release,
                "historical_conditional_response": response,
                "no_news_control": control,
                "event_vs_no_news": event_vs_control,
            },
            explanation=(
                "Historical Gold response uses independent episodes and a matched no-news "
                "control; trade P/L is never used."
            ),
        ),
    ]

    dimensions = global_environment["learning_dimensions"]
    mini_environment = {
        "event_class": event_class,
        "gold_event_tier": str(tier.get("tier") or "unknown"),
        "event_timing_state": event_timing_state,
        "surprise_state": str(surprise.get("surprise_state") or "unknown"),
        "standardized_surprise_band": str(standardized.get("band") or "unknown"),
        "cluster_state": str(cluster.get("state") or "unknown"),
        "historical_response_state": str(response.get("state") or "unknown"),
        "post_release_confirmation_state": str(post_release.get("state") or "unknown"),
        "session": dimensions["session"],
        "session_phase": dimensions["session_phase"],
        "volatility_state": dimensions["volatility_state"],
    }

    packet = build_expert_gate_packet(
        gate_id=MACRO_EVENT_GATE_ID,
        gate_version=MACRO_EVENT_EXPERT_VERSION,
        gate_mode="context_only",
        dependency_family="event",
        target_horizon_minutes=MACRO_EVENT_TARGET_HORIZON_MINUTES,
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
                    f"Macro event={event_class}; tier={tier.get('tier')}; "
                    f"timing={event_timing_state}; cluster={cluster.get('state')}; "
                    f"surprise={surprise.get('surprise_state')}."
                ),
                "source_refs": [
                    "calc:macro_event_tier_cluster",
                    "calc:macro_event_surprise",
                ],
            },
            {
                "text": (
                    "Build 15 is context-only. Macro-event evidence can change trust and "
                    "context but does not create a BUY/SELL forecast by itself."
                ),
                "source_refs": ["calc:macro_event_response"],
            },
        ),
        contradictions=(),
    )
    if not verify_expert_gate_packet(packet):
        raise ValueError("constructed Macro/Event packet failed Build-2 verification")

    scopes = build_trust_scopes(
        packet=packet,
        reduced_contexts=MACRO_EVENT_TRUST_REDUCED_CONTEXTS,
    )
    rows_by_subject = trust_score_rows_by_subject or {}
    profiles = {
        key: select_conditional_trust(
            score_rows=rows_by_subject.get(key, ()),
            scopes=scopes,
        )
        for key in _subject_keys(packet)
    }
    trust_envelope = build_trust_envelope(packet=packet, profiles_by_subject=profiles)

    return {
        "expert_version": MACRO_EVENT_EXPERT_VERSION,
        "expert_packet": packet,
        "event_class": event_class,
        "event_tier": tier,
        "event_cluster": cluster,
        "event_timing_state": event_timing_state,
        "pre_event": pre_event,
        "surprise": surprise,
        "standardized_surprise": standardized,
        "post_release_confirmation": post_release,
        "historical_conditional_response": response,
        "no_news_control": control,
        "event_vs_no_news": event_vs_control,
        "trust_scopes": scopes,
        "trust_envelope": trust_envelope,
        "direction_policy": {
            "directional_vote_allowed": False,
            "macro_event_alone_creates_direction": False,
            "vendor_importance_label_used": False,
            "trade_pnl_used": False,
        },
        "research_only": True,
        "future_values_used": False,
        "live_money_execution_allowed": False,
    }


__all__ = [
    "CONDITIONAL_RESPONSE_MIN_N",
    "MACRO_EVENT_EXPERT_VERSION",
    "MACRO_EVENT_GATE_ID",
    "MACRO_EVENT_TARGET_HORIZON_MINUTES",
    "MACRO_EVENT_TRUST_REDUCED_CONTEXTS",
    "NO_NEWS_CONTROL_MIN_N",
    "STANDARDIZED_SURPRISE_MIN_N",
    "build_macro_event_expert",
]
