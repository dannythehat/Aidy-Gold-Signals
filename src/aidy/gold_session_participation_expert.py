"""Build 14: Session / Participation Expert for AIDY Gold.

Quantifies likely regional market participation and whether current activity is
unusual for the exact weekday/clock slot. Context-only: there are no hardcoded
session-direction rules.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation, localcontext
from itertools import pairwise
from typing import Any

from aidy.feature_engine import Candle, normalize_candles
from aidy.gc_microstructure import BASELINE_VERSION
from aidy.gold_expert_gate_contract import build_expert_gate_packet, verify_expert_gate_packet
from aidy.gold_expert_trust import (
    build_trust_envelope,
    build_trust_scopes,
    select_conditional_trust,
)
from aidy.market_sessions import (
    london_utc_offset_hours,
    new_york_utc_offset_hours,
    session_code_at,
)

SESSION_PARTICIPATION_EXPERT_VERSION = "aidy_gold_session_participation_expert_v1"
SESSION_PARTICIPATION_GATE_ID = "session_participation_expert"
SESSION_PARTICIPATION_TARGET_HORIZON_MINUTES = 15
MATCHED_CLOCK_MINIMUM_N = 20

SESSION_PARTICIPATION_TRUST_REDUCED_CONTEXTS = (
    {
        "name": "session_activity",
        "mini_dimensions": [
            "session",
            "session_phase",
            "overlap_state",
            "activity_state",
        ],
        "global_dimensions": [],
        "minimum_sample_n": 12,
    },
    {
        "name": "clock_participation",
        "mini_dimensions": [
            "utc_weekday",
            "utc_clock_bucket_15m",
            "activity_state",
            "gc_participation_state",
        ],
        "global_dimensions": [],
        "minimum_sample_n": 10,
    },
    {
        "name": "event_confounding",
        "mini_dimensions": [
            "session",
            "activity_state",
            "event_confounding_state",
        ],
        "global_dimensions": ["volatility_state"],
        "minimum_sample_n": 8,
    },
)

_NEAR_EVENT_STATES = frozenset(
    {
        "inside_event_window",
        "near_event_window",
        "inside_near_event_window",
        "event_imminent",
        "inside_post_event_window",
    }
)


def _utc(value: datetime | str) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError("session-participation timestamps must be timezone-aware")
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


def _clock_bucket(timestamp: datetime) -> str:
    minute = (timestamp.minute // 15) * 15
    return f"{timestamp.hour:02d}:{minute:02d}"


def _session_snapshot(as_of: datetime) -> dict[str, Any]:
    now = _utc(as_of)
    london_offset = london_utc_offset_hours(now)
    ny_offset = new_york_utc_offset_hours(now)
    london = now + timedelta(hours=london_offset)
    new_york = now + timedelta(hours=ny_offset)
    tokyo = now + timedelta(hours=9)

    london_open = now.weekday() < 5 and 8 <= london.hour < 17
    new_york_open = now.weekday() < 5 and 8 <= new_york.hour < 17
    asia_open = now.weekday() < 5 and 9 <= tokyo.hour < 18

    active_markets: list[str] = []
    if asia_open:
        active_markets.append("asia")
    if london_open:
        active_markets.append("london")
    if new_york_open:
        active_markets.append("new_york")

    overlap = (
        "london_new_york_overlap"
        if london_open and new_york_open
        else "multi_region_overlap"
        if len(active_markets) >= 2
        else "single_region"
        if len(active_markets) == 1
        else "off_hours"
    )
    return {
        "session_code": session_code_at(now),
        "active_markets": active_markets,
        "active_market_count": len(active_markets),
        "overlap_state": overlap,
        "london_utc_offset_hours": london_offset,
        "new_york_utc_offset_hours": ny_offset,
        "london_local_time": london.strftime("%Y-%m-%dT%H:%M"),
        "new_york_local_time": new_york.strftime("%Y-%m-%dT%H:%M"),
        "tokyo_local_time": tokyo.strftime("%Y-%m-%dT%H:%M"),
        "who_is_active_claim": "regional_market_hours_only",
        "individual_participant_identity_claimed": False,
    }


def _infer_mode(rows: Sequence[Mapping[str, Any]]) -> str:
    if rows and all(
        row.get("pit_eligible") is True
        and str(row.get("provenance_class") or "") == "pit_observed"
        for row in rows
    ):
        return "pit"
    return "retrospective"


def _completed_m1(
    rows: Sequence[Mapping[str, Any]],
    *,
    as_of: datetime,
) -> tuple[list[Candle], str]:
    mode = _infer_mode(rows)
    grouped = normalize_candles(rows, as_of=as_of, symbol="XAUUSD", mode=mode)
    candles = [
        candle
        for candle in grouped["M1"]
        if candle.open_time_utc + timedelta(minutes=1) <= as_of
    ]
    return candles, mode


def _current_activity(candles: Sequence[Candle]) -> dict[str, Any]:
    sample = list(candles[-16:])
    if len(sample) < 16:
        return {
            "state": "unknown_insufficient_m1",
            "realized_volatility_bps": None,
            "range_bps": None,
            "completed_return_count": max(0, len(sample) - 1),
        }
    if any(
        right.open_time_utc - left.open_time_utc != timedelta(minutes=1)
        for left, right in pairwise(sample)
    ):
        return {
            "state": "unknown_gapped_m1",
            "realized_volatility_bps": None,
            "range_bps": None,
            "completed_return_count": 15,
        }

    returns: list[Decimal] = []
    for left, right in pairwise(sample):
        if left.close == 0:
            return {
                "state": "unknown_invalid_price",
                "realized_volatility_bps": None,
                "range_bps": None,
                "completed_return_count": 15,
            }
        returns.append((right.close / left.close - Decimal(1)) * Decimal(10000))

    with localcontext() as ctx:
        ctx.prec = 40
        mean_square = sum((item * item for item in returns), Decimal(0)) / Decimal(
            len(returns)
        )
        realized = mean_square.sqrt()

    window = sample[-15:]
    high = max(candle.high for candle in window)
    low = min(candle.low for candle in window)
    denominator = sample[0].close
    range_bps = None if denominator == 0 else (high - low) / denominator * Decimal(10000)
    return {
        "state": "known",
        "realized_volatility_bps": _fmt(realized),
        "range_bps": _fmt(range_bps),
        "completed_return_count": len(returns),
        "first_open_time_utc": sample[0].open_time_utc.isoformat(),
        "last_open_time_utc": sample[-1].open_time_utc.isoformat(),
    }


def _matched_history(
    rows: Sequence[Mapping[str, Any]],
    *,
    as_of: datetime,
    weekday: int,
    bucket: str,
) -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]]]:
    matched: list[Mapping[str, Any]] = []
    clean: list[Mapping[str, Any]] = []
    for row in rows:
        if row.get("weekday_utc") != weekday:
            continue
        if str(row.get("utc_clock_bucket_15m") or "") != bucket:
            continue
        observed = row.get("observed_at_utc")
        if observed is None:
            continue
        try:
            observed_at = _utc(str(observed))
        except ValueError:
            continue
        if observed_at >= as_of:
            continue
        volatility = _decimal(row.get("realized_volatility_bps"))
        range_bps = _decimal(row.get("range_bps"))
        if volatility is None or range_bps is None or volatility < 0 or range_bps < 0:
            continue
        matched.append(row)
        if str(row.get("event_timing_state") or "unknown") not in _NEAR_EVENT_STATES:
            clean.append(row)
    return matched, clean


def _percentile(value: Decimal | None, history: Sequence[Decimal]) -> Decimal | None:
    if value is None or len(history) < MATCHED_CLOCK_MINIMUM_N:
        return None
    rank = sum(item <= value for item in history)
    return Decimal(rank) / Decimal(len(history))


def _activity_baseline(
    current: Mapping[str, Any],
    history_rows: Sequence[Mapping[str, Any]],
    *,
    as_of: datetime,
) -> dict[str, Any]:
    weekday = as_of.weekday()
    bucket = _clock_bucket(as_of - timedelta(minutes=1))
    matched, clean = _matched_history(
        history_rows,
        as_of=as_of,
        weekday=weekday,
        bucket=bucket,
    )
    use_clean = len(clean) >= MATCHED_CLOCK_MINIMUM_N
    selected = clean if use_clean else matched
    population = "event_clean_weekday_clock" if use_clean else "all_weekday_clock"
    vol_history = [
        value
        for row in selected
        if (value := _decimal(row.get("realized_volatility_bps"))) is not None
    ]
    range_history = [
        value
        for row in selected
        if (value := _decimal(row.get("range_bps"))) is not None
    ]
    current_vol = _decimal(current.get("realized_volatility_bps"))
    current_range = _decimal(current.get("range_bps"))
    vol_pct = _percentile(current_vol, vol_history)
    range_pct = _percentile(current_range, range_history)

    if vol_pct is None or range_pct is None:
        state = "unknown_insufficient_matched_clock_history"
    elif vol_pct >= Decimal("0.90") and range_pct >= Decimal("0.90"):
        state = "unusually_high_activity"
    elif vol_pct <= Decimal("0.10") and range_pct <= Decimal("0.10"):
        state = "unusually_quiet"
    elif max(vol_pct, range_pct) >= Decimal("0.80"):
        state = "elevated_activity"
    else:
        state = "typical_activity"

    return {
        "state": state,
        "weekday_utc": weekday,
        "utc_clock_bucket_15m": bucket,
        "matched_sample_n": len(matched),
        "event_clean_sample_n": len(clean),
        "selected_sample_n": len(selected),
        "baseline_population": population,
        "volatility_percentile": _fmt(vol_pct),
        "range_percentile": _fmt(range_pct),
        "minimum_sample_n": MATCHED_CLOCK_MINIMUM_N,
    }


def _gc_participation_context(
    raw: Mapping[str, Any] | None,
    *,
    as_of: datetime,
) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        return {
            "state": "unknown",
            "qualification": "missing",
            "volume_z": None,
            "spread_z": None,
            "research_only": True,
        }

    observed = raw.get("observed_at_utc")
    try:
        observed_at = _utc(str(observed)) if observed is not None else None
    except ValueError:
        observed_at = None

    baseline_ok = str(raw.get("baseline_version") or "") == BASELINE_VERSION
    boundary_ok = (
        raw.get("ordinary_session_activity_can_count_as_alpha") is False
        and raw.get("outcome_fields_used_for_normalization") is False
    )
    time_ok = observed_at is not None and observed_at <= as_of
    volume_z = _decimal(raw.get("volume_z"))
    spread_z = _decimal(raw.get("spread_z"))
    known = (
        str(raw.get("state") or "") == "known"
        and baseline_ok
        and boundary_ok
        and time_ok
        and volume_z is not None
        and spread_z is not None
    )
    if not known:
        return {
            "state": "unknown",
            "qualification": "unqualified_or_incomplete",
            "volume_z": None,
            "spread_z": None,
            "research_only": True,
        }

    pit_eligible = raw.get("pit_eligible") is True
    if volume_z >= Decimal(2):
        volume_state = "unusually_high"
    elif volume_z <= Decimal(-2):
        volume_state = "unusually_low"
    else:
        volume_state = "typical"

    if spread_z >= Decimal(2):
        spread_state = "unusually_wide"
    elif spread_z <= Decimal(-2):
        spread_state = "unusually_tight"
    else:
        spread_state = "typical"

    return {
        "state": "known",
        "qualification": "pit_qualified" if pit_eligible else "retrospective_research_only",
        "volume_z": _fmt(volume_z),
        "spread_z": _fmt(spread_z),
        "volume_state": volume_state,
        "spread_state": spread_state,
        "baseline_version": BASELINE_VERSION,
        "baseline_digest": raw.get("baseline_digest"),
        "genuine_exchange_trade_volume": raw.get("genuine_exchange_trade_volume") is True,
        "genuine_pretrade_bbo_spread": raw.get("genuine_pretrade_bbo_spread") is True,
        "depth_claimed": False,
        "order_book_imbalance_claimed": False,
        "ordinary_session_activity_can_count_as_alpha": False,
        "research_only": not pit_eligible,
    }


def _event_confounding(exact: Mapping[str, Any]) -> dict[str, Any]:
    event = exact.get("scheduled_event")
    event = event if isinstance(event, Mapping) else {}
    timing = str(event.get("timing_state") or "unknown")
    confounded = timing in _NEAR_EVENT_STATES
    return {
        "state": "event_time_confounded" if confounded else "not_event_time_confounded",
        "event_timing_state": timing,
        "confounded": confounded,
        "activity_attributed_to_session_only": False if confounded else None,
        "event_causal_claim": False,
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
    keys.extend(
        f"subcalculator:{item['calculator_id']}"
        for item in packet["subcalculators"]
    )
    return keys


def build_session_participation_expert(
    *,
    global_environment: Mapping[str, Any],
    m1_candle_rows: Sequence[Mapping[str, Any]],
    weekday_clock_history: Sequence[Mapping[str, Any]],
    gc_activity_context: Mapping[str, Any] | None = None,
    trust_score_rows_by_subject: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Build one frozen direction-neutral session/participation context packet."""

    exact = global_environment.get("exact_facts")
    exact = exact if isinstance(exact, Mapping) else {}
    as_of = _utc(str(exact.get("as_of_utc")))
    session = exact.get("session")
    session = session if isinstance(session, Mapping) else {}
    dimensions = global_environment["learning_dimensions"]

    snapshot = _session_snapshot(as_of)
    expected_session = str(session.get("session_code") or dimensions["session"])
    if snapshot["session_code"] != expected_session:
        raise ValueError("session expert requires DST-safe session code to match environment")

    candles, mode = _completed_m1(m1_candle_rows, as_of=as_of)
    current = _current_activity(candles)
    baseline = _activity_baseline(current, weekday_clock_history, as_of=as_of)
    event_confounding = _event_confounding(exact)
    gc = _gc_participation_context(gc_activity_context, as_of=as_of)

    evidence_inputs = [
        {
            "evidence_id": "session_clock_evidence",
            "source": "aidy_market_sessions",
            "path": "session_participation.session_snapshot",
            "observed_at_utc": as_of,
            "state": "known",
            "value": snapshot,
            "provenance": {
                "dst_safe_london": True,
                "dst_safe_new_york": True,
                "future_values_used": False,
            },
        },
        {
            "evidence_id": "session_activity_evidence",
            "source": "completed_m1_weekday_clock_baseline",
            "path": "session_participation.activity",
            "observed_at_utc": as_of,
            "state": "known" if current["state"] == "known" else "unknown",
            "value": {
                "current": current,
                "matched_clock": baseline,
            },
            "provenance": {
                "m1_mode": mode,
                "completed_bars_only": True,
                "future_values_used": False,
                "matched_weekday_clock_only": True,
            },
        },
        {
            "evidence_id": "session_gc_participation_evidence",
            "source": "aidy_gc_microstructure_weekday_clock15_v1",
            "path": "session_participation.gc_activity",
            "observed_at_utc": as_of,
            "state": "known" if gc["state"] == "known" else "unknown",
            "value": gc if gc["state"] == "known" else None,
            "provenance": {
                "genuine_exchange_trade_volume": gc.get("genuine_exchange_trade_volume") is True,
                "genuine_pretrade_bbo_spread": gc.get("genuine_pretrade_bbo_spread") is True,
                "ordinary_session_activity_can_count_as_alpha": False,
                "future_values_used": False,
            },
        },
        {
            "evidence_id": "session_event_confounding_evidence",
            "source": "frozen_cycle_environment",
            "path": "exact_facts.scheduled_event",
            "observed_at_utc": as_of,
            "state": "known",
            "value": event_confounding,
            "provenance": {
                "environment_key": global_environment["environment_key"],
                "future_values_used": False,
                "event_causal_claim": False,
            },
        },
    ]

    calculators = [
        _context_calculator(
            calculator_id="session_active_markets",
            dependency_family="session_participation",
            evidence_ref="session_clock_evidence",
            known=True,
            observation=snapshot,
            explanation=(
                "Active-market context is derived only from DST-safe regional market hours; "
                "it does not identify individual participants."
            ),
        ),
        _context_calculator(
            calculator_id="session_matched_clock_activity",
            dependency_family="session_participation",
            evidence_ref="session_activity_evidence",
            known=current["state"] == "known" and not baseline["state"].startswith("unknown"),
            observation={
                "current": current,
                "matched_clock": baseline,
            },
            explanation=(
                "Current completed-M1 volatility/range is compared only with the same "
                "weekday and UTC 15-minute clock slot."
            ),
        ),
        _context_calculator(
            calculator_id="session_gc_volume_spread",
            dependency_family="session_participation",
            evidence_ref="session_gc_participation_evidence",
            known=gc["state"] == "known",
            observation=gc,
            explanation=(
                "GC volume/spread context uses the existing genuine exchange-trade and "
                "pre-trade BBO baseline. Ordinary session activity is not alpha."
            ),
        ),
        _context_calculator(
            calculator_id="session_event_confounding",
            dependency_family="event",
            evidence_ref="session_event_confounding_evidence",
            known=True,
            observation=event_confounding,
            explanation=(
                "Event-time overlap is explicit so unusual activity is not automatically "
                "attributed to the session itself."
            ),
        ),
    ]

    session_phase = str(dimensions["session_phase"])
    mini_environment = {
        "session": dimensions["session"],
        "session_phase": session_phase,
        "overlap_state": snapshot["overlap_state"],
        "active_markets": snapshot["active_markets"],
        "utc_weekday": as_of.weekday(),
        "utc_clock_bucket_15m": _clock_bucket(as_of),
        "activity_state": baseline["state"],
        "gc_participation_state": (
            f"{gc.get('volume_state', 'unknown')}|{gc.get('spread_state', 'unknown')}"
            if gc["state"] == "known"
            else "unknown"
        ),
        "event_confounding_state": event_confounding["state"],
        "volatility_state": dimensions["volatility_state"],
    }

    explanation_parts = [
        {
            "text": (
                f"Session={snapshot['session_code']}; active markets="
                f"{','.join(snapshot['active_markets']) or 'none'}; "
                f"overlap={snapshot['overlap_state']}; activity={baseline['state']}."
            ),
            "source_refs": [
                "calc:session_active_markets",
                "calc:session_matched_clock_activity",
            ],
        },
        {
            "text": (
                "Session/participation context is direction-neutral. There is no hardcoded "
                "'London bullish', 'New York bearish' or equivalent session-direction rule."
            ),
            "source_refs": ["calc:session_active_markets"],
        },
        {
            "text": (
                f"Event confounding={event_confounding['state']}; "
                f"GC participation={gc['state']}."
            ),
            "source_refs": [
                "calc:session_event_confounding",
                "calc:session_gc_volume_spread",
            ],
        },
    ]

    packet = build_expert_gate_packet(
        gate_id=SESSION_PARTICIPATION_GATE_ID,
        gate_version=SESSION_PARTICIPATION_EXPERT_VERSION,
        gate_mode="context_only",
        dependency_family="session_participation",
        target_horizon_minutes=SESSION_PARTICIPATION_TARGET_HORIZON_MINUTES,
        as_of_utc=as_of,
        global_environment=global_environment,
        mini_environment=mini_environment,
        evidence_inputs=evidence_inputs,
        subcalculators=calculators,
        conclusion="context_only",
        internal_conviction=None,
        explanation_parts=explanation_parts,
        contradictions=(),
    )
    if not verify_expert_gate_packet(packet):
        raise ValueError("constructed Session/Participation packet failed Build-2 verification")

    scopes = build_trust_scopes(
        packet=packet,
        reduced_contexts=SESSION_PARTICIPATION_TRUST_REDUCED_CONTEXTS,
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
        "expert_version": SESSION_PARTICIPATION_EXPERT_VERSION,
        "expert_packet": packet,
        "session_snapshot": snapshot,
        "current_activity": current,
        "matched_clock_activity": baseline,
        "gc_participation": gc,
        "event_confounding": event_confounding,
        "trust_scopes": scopes,
        "trust_envelope": trust_envelope,
        "direction_policy": {
            "directional_vote_allowed": False,
            "session_direction_rule_present": False,
            "ordinary_session_activity_can_count_as_alpha": False,
            "event_proximity_is_causal_claim": False,
        },
        "research_only": True,
        "future_values_used": False,
        "live_money_execution_allowed": False,
    }


__all__ = [
    "MATCHED_CLOCK_MINIMUM_N",
    "SESSION_PARTICIPATION_EXPERT_VERSION",
    "SESSION_PARTICIPATION_GATE_ID",
    "SESSION_PARTICIPATION_TARGET_HORIZON_MINUTES",
    "SESSION_PARTICIPATION_TRUST_REDUCED_CONTEXTS",
    "build_session_participation_expert",
]
