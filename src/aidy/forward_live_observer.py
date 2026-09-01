from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from aidy.forward_evaluation import build_forward_evaluation_record, digest
from aidy.forward_start_amendment import (
    D1ImmediateForwardEvaluationStore,
    FORWARD_COHORT_VERSION_V2,
)
from aidy.runtime import interval_due

FORWARD_LIVE_OBSERVER_VERSION = "aidy_day53_live_forward_observer_v1"
FORWARD_OBSERVATION_INTERVAL_SECONDS = 300
Clock = Callable[[], datetime]


@dataclass(frozen=True, slots=True)
class ForwardLiveObservationResult:
    status: str
    cohort_id: str | None = None
    record_id: str | None = None
    disposition: str | None = None
    reason_code: str | None = None
    cycle_id: str | None = None


def _utc(value: datetime | str, *, name: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        parsed = datetime.fromisoformat(value.strip())
    else:
        raise TypeError(f"{name} must be a timezone-aware datetime or ISO-8601 string.")
    if parsed.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware.")
    return parsed.astimezone(UTC)


def _row(value: object) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return dict(value)
    try:
        return dict(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise TypeError("Unexpected D1 row shape.") from exc


def _results(value: object) -> list[dict[str, Any]]:
    rows = getattr(value, "results", None)
    if rows is None and isinstance(value, dict):
        rows = value.get("results")
    if rows is None:
        return []
    return [row for item in rows if (row := _row(item)) is not None]


def _cycle_id(scheduled_at: datetime) -> str:
    utc = scheduled_at.astimezone(UTC)
    epoch = int(utc.timestamp())
    bucket_epoch = epoch - (epoch % FORWARD_OBSERVATION_INTERVAL_SECONDS)
    bucket = datetime.fromtimestamp(bucket_epoch, tz=UTC)
    return f"formal_market_{bucket.strftime('%Y%m%dT%H%MZ')}"


def _episode_id(snapshot: dict[str, Any], *, reason_code: str) -> str:
    captured = _utc(str(snapshot["captured_at"]), name="snapshot.captured_at")
    session = str(snapshot.get("session_code") or "unknown").strip().lower() or "unknown"
    identity = {
        "kind": "data_quality_episode",
        "date": captured.date().isoformat(),
        "session": session,
        "reason_code": reason_code,
    }
    return f"dq_{digest(identity)[:32]}"


def _context_hash(snapshot: dict[str, Any]) -> str:
    availability_raw = str(snapshot.get("data_availability_json") or "{}")
    try:
        availability = json.loads(availability_raw)
    except json.JSONDecodeError:
        availability = {"state": "invalid_json"}
    return digest(
        {
            "observer_version": FORWARD_LIVE_OBSERVER_VERSION,
            "snapshot_id": str(snapshot.get("id") or ""),
            "snapshot_digest": str(snapshot.get("snapshot_digest") or ""),
            "captured_at": str(snapshot.get("captured_at") or ""),
            "capture_status": str(snapshot.get("capture_status") or ""),
            "quote_time": str(snapshot.get("quote_time") or ""),
            "quote_age_seconds": snapshot.get("quote_age_seconds"),
            "session_code": str(snapshot.get("session_code") or ""),
            "data_availability": availability,
        }
    )


def _blocked_reason(snapshot: dict[str, Any]) -> str | None:
    status = str(snapshot.get("capture_status") or "").strip().lower()
    if status == "unavailable":
        return "market_reference_unavailable"
    if status != "complete":
        return "market_reference_not_complete"

    quote_age = snapshot.get("quote_age_seconds")
    if quote_age is None or isinstance(quote_age, bool):
        return "market_reference_age_unknown"
    try:
        if float(quote_age) > 300.0:
            return "market_reference_stale"
    except (TypeError, ValueError):
        return "market_reference_age_invalid"

    spread_fields = (snapshot.get("bid"), snapshot.get("ask"), snapshot.get("spread"))
    candle_fields = tuple(
        snapshot.get(name)
        for name in (
            "latest_m1_id",
            "latest_m5_id",
            "latest_m15_id",
            "latest_h1_id",
            "latest_h4_id",
            "latest_d1_id",
        )
    )
    missing_spread = any(value in {None, ""} for value in spread_fields)
    missing_ohlc = any(value in {None, ""} for value in candle_fields)
    if missing_spread and missing_ohlc:
        return "missing_genuine_live_ohlc_and_spread"
    if missing_spread:
        return "missing_genuine_live_spread"
    if missing_ohlc:
        return "missing_genuine_live_ohlc"
    return None


async def _active_amended_cohort(d1: Any) -> dict[str, Any] | None:
    result = await d1.prepare(
        """
        SELECT *
        FROM aidy_forward_cohorts
        WHERE state='active' AND cohort_version=?
        ORDER BY activated_at_utc DESC, cohort_id DESC
        """
    ).bind(FORWARD_COHORT_VERSION_V2).all()
    rows = _results(result)
    if not rows:
        return None
    if len(rows) != 1:
        raise RuntimeError("Formal forward observer requires exactly one active amended cohort.")
    return rows[0]


async def _snapshot(d1: Any, snapshot_id: str) -> dict[str, Any] | None:
    value = await d1.prepare(
        """
        SELECT id,captured_at,symbol,capture_status,bid,ask,mid,spread,quote_time,
               quote_age_seconds,session_code,data_availability_json,
               latest_m1_id,latest_m5_id,latest_m15_id,latest_h1_id,latest_h4_id,latest_d1_id,
               snapshot_digest
        FROM market_snapshots
        WHERE id=?
        LIMIT 1
        """
    ).bind(snapshot_id).first()
    return _row(value)


async def observe_private_forward_snapshot(
    *,
    d1: Any,
    scheduled_at: datetime,
    snapshot_id: UUID | str | None,
    clock: Clock = lambda: datetime.now(UTC),
) -> ForwardLiveObservationResult:
    scheduled = _utc(scheduled_at, name="scheduled_at")
    if not interval_due(
        scheduled,
        FORWARD_OBSERVATION_INTERVAL_SECONDS,
        tick_seconds=60,
    ):
        return ForwardLiveObservationResult(status="not_due")

    cohort = await _active_amended_cohort(d1)
    if cohort is None:
        return ForwardLiveObservationResult(status="no_active_cohort")

    cohort_id = str(cohort["cohort_id"])
    cycle_id = _cycle_id(scheduled)
    existing = await d1.prepare(
        "SELECT record_id,disposition,data_quality_reason_code FROM aidy_forward_evaluations "
        "WHERE cohort_id=? AND cycle_id=? LIMIT 1"
    ).bind(cohort_id, cycle_id).first()
    existing_row = _row(existing)
    if existing_row is not None:
        return ForwardLiveObservationResult(
            status="already_recorded",
            cohort_id=cohort_id,
            record_id=str(existing_row["record_id"]),
            disposition=str(existing_row["disposition"]),
            reason_code=str(existing_row.get("data_quality_reason_code") or "") or None,
            cycle_id=cycle_id,
        )

    if snapshot_id is None:
        return ForwardLiveObservationResult(
            status="no_snapshot",
            cohort_id=cohort_id,
            cycle_id=cycle_id,
        )
    snapshot = await _snapshot(d1, str(snapshot_id))
    if snapshot is None:
        return ForwardLiveObservationResult(
            status="snapshot_missing",
            cohort_id=cohort_id,
            cycle_id=cycle_id,
        )

    captured = _utc(str(snapshot["captured_at"]), name="snapshot.captured_at")
    activated = _utc(str(cohort["activated_at_utc"]), name="cohort.activated_at_utc")
    if captured < activated:
        return ForwardLiveObservationResult(
            status="snapshot_predates_activation",
            cohort_id=cohort_id,
            cycle_id=cycle_id,
        )

    reason = _blocked_reason(snapshot)
    if reason is None:
        disposition = "failed_closed"
        data_quality_state = "unknown"
        reason = "production_decision_context_adapter_not_enabled"
    else:
        disposition = "pre_model_blocked"
        data_quality_state = "failure"

    observed_at = _utc(clock(), name="clock")
    if observed_at < captured:
        observed_at = captured

    record = build_forward_evaluation_record(
        cohort=cohort,
        cycle_id=cycle_id,
        instruction_type="market_evaluation",
        evaluated_at_utc=observed_at,
        context_hash=_context_hash(snapshot),
        disposition=disposition,
        data_quality_state=data_quality_state,
        data_quality_reason_code=reason,
        episode_id=_episode_id(snapshot, reason_code=reason),
        decision_id=None,
        ex_ante_digest=None,
        self_consistency=None,
        retrieval_effective_n=0,
        gc_shadow={
            "state": "unknown",
            "gc_shadow_only": True,
            "authoritative_decision_input": False,
        },
        gc_feed_health={"state": "unknown", "authoritative_decision_input": False},
        macro_surprise={"state": "unknown", "forward_only": True},
        selective_shadow={
            "state": "unknown",
            "master_trader_block_allowed": False,
            "publication_block_allowed": False,
        },
    )
    stored = await D1ImmediateForwardEvaluationStore(d1).record_evaluation(
        record,
        recorded_at_utc=observed_at,
    )
    return ForwardLiveObservationResult(
        status="recorded",
        cohort_id=cohort_id,
        record_id=str(stored["record_id"]),
        disposition=str(stored["disposition"]),
        reason_code=str(stored.get("data_quality_reason_code") or "") or None,
        cycle_id=cycle_id,
    )


async def live_forward_status(d1: Any) -> dict[str, Any]:
    cohort = await _active_amended_cohort(d1)
    if cohort is None:
        return {
            "observer_version": FORWARD_LIVE_OBSERVER_VERSION,
            "active": False,
            "cohort_id": None,
        }
    progress = await D1ImmediateForwardEvaluationStore(d1).cohort_progress(str(cohort["cohort_id"]))
    latest = await d1.prepare(
        """
        SELECT record_id,cycle_id,evaluated_at_utc,disposition,data_quality_state,
               data_quality_reason_code,episode_id,recorded_at_utc
        FROM aidy_forward_evaluations
        WHERE cohort_id=?
        ORDER BY evaluated_at_utc DESC,recorded_at_utc DESC
        LIMIT 1
        """
    ).bind(str(cohort["cohort_id"])).first()
    return {
        "observer_version": FORWARD_LIVE_OBSERVER_VERSION,
        "active": True,
        "cohort_id": str(cohort["cohort_id"]),
        "cohort_state": str(cohort["state"]),
        "accepted_code_head": str(cohort["accepted_code_head"]),
        "manifest_digest": str(cohort["manifest_digest"]),
        "activated_at_utc": str(cohort["activated_at_utc"]),
        "progress": progress,
        "latest_evaluation": _row(latest),
        "openai_called_for_pre_model_block": False,
        "telegram_publication_enabled": False,
    }


def day53_live_forward_manifest() -> dict[str, Any]:
    result: dict[str, Any] = {
        "manifest_version": "aidy_day53_live_forward_activation_v1",
        "observer_version": FORWARD_LIVE_OBSERVER_VERSION,
        "observation_interval_seconds": FORWARD_OBSERVATION_INTERVAL_SECONDS,
        "requires_active_amended_cohort": True,
        "scheduled_timestamp_may_predate_snapshot_evaluation": False,
        "missing_live_ohlc_or_spread_fails_pre_model": True,
        "blocked_cycles_count_toward_day54_model_resolved_n": False,
        "decision_adapter_enabled_by_this_change": False,
        "openai_called_for_pre_model_block": False,
        "telegram_publication_enabled": False,
        "broker_or_account_state_allowed": False,
        "follower_state_allowed": False,
        "super_signals_dependency_allowed": False,
        "live_money_execution_allowed": False,
    }
    result["manifest_digest"] = digest(result)
    return result
