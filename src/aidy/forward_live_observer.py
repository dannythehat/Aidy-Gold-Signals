from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from aidy.end_to_end import run_market_evaluation_cycle
from aidy.end_to_end_store import D1EndToEndCycleStore
from aidy.forward_evaluation import build_forward_evaluation_record, digest
from aidy.forward_start_amendment import (
    FORWARD_COHORT_VERSION_V2,
    D1ImmediateForwardEvaluationStore,
)
from aidy.private_forward_context import build_private_forward_decision_inputs
from aidy.publication_ledger import D1PublicationLedgerStore
from aidy.runtime import interval_due
from aidy.self_consistency_ledger_v2 import build_self_consistency_selective_layer_state_v2

FORWARD_LIVE_OBSERVER_VERSION = "aidy_day53_live_forward_observer_v2_real_cycle"
FORWARD_OBSERVATION_INTERVAL_SECONDS = 300
Clock = Callable[[], datetime]
DecisionInputBuilder = Callable[..., Awaitable[dict[str, Any]]]


@dataclass(frozen=True, slots=True)
class ForwardLiveObservationResult:
    status: str
    cohort_id: str | None = None
    record_id: str | None = None
    disposition: str | None = None
    reason_code: str | None = None
    cycle_id: str | None = None
    end_to_end_cycle_id: str | None = None
    decision_id: str | None = None
    ex_ante_digest: str | None = None
    self_consistency_digest: str | None = None
    context_hash: str | None = None


class _ForbiddenPrivateForwardTransport:
    async def send_message(self, *args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        raise RuntimeError("Private-forward transport must never be called.")


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
    if any(value in {None, ""} for value in candle_fields):
        return "missing_genuine_live_ohlc"

    availability_raw = str(snapshot.get("data_availability_json") or "{}")
    try:
        availability = json.loads(availability_raw)
    except json.JSONDecodeError:
        return "market_reference_availability_invalid"
    spread_state = str(availability.get("spread_advisory_state") or "unavailable").strip().lower()
    if spread_state == "out_of_tolerance":
        return "observed_spread_out_of_tolerance"
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


def _decode_artifact(row: Mapping[str, Any] | None, key: str) -> dict[str, Any] | None:
    if row is None:
        return None
    raw = row.get(key)
    if raw in (None, ""):
        return None
    if not isinstance(raw, str):
        raise TypeError(f"Stored {key} must be JSON text.")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise TypeError(f"Stored {key} must decode to an object.")
    return value


def _model_failed(self_consistency: Mapping[str, Any] | None) -> bool:
    if not isinstance(self_consistency, Mapping):
        return False
    disagreement = self_consistency.get("disagreement")
    receipts = self_consistency.get("sample_receipts")
    if not isinstance(disagreement, Mapping) or not isinstance(receipts, list):
        return False
    if int(disagreement.get("eligible_sample_count") or 0) != 0:
        return False
    return bool(receipts) and all(
        isinstance(item, Mapping) and item.get("gateway_status") == "failed_closed"
        for item in receipts
    )


def _selective_shadow(self_consistency: Mapping[str, Any] | None) -> dict[str, Any]:
    if self_consistency is None:
        return {
            "state": "unknown",
            "master_trader_block_allowed": False,
            "publication_block_allowed": False,
        }
    return build_self_consistency_selective_layer_state_v2(self_consistency)


async def _record_forward(
    *,
    d1: Any,
    cohort: Mapping[str, Any],
    formal_cycle_id: str,
    observed_at: datetime,
    context_hash: str,
    disposition: str,
    data_quality_state: str,
    data_quality_reason_code: str | None,
    episode_id: str,
    decision_id: str | None,
    ex_ante_digest: str | None,
    self_consistency: Mapping[str, Any] | None,
    retrieval_effective_n: int,
) -> dict[str, Any]:
    record = build_forward_evaluation_record(
        cohort=cohort,
        cycle_id=formal_cycle_id,
        instruction_type="market_evaluation",
        evaluated_at_utc=observed_at,
        context_hash=context_hash,
        disposition=disposition,
        data_quality_state=data_quality_state,
        data_quality_reason_code=data_quality_reason_code,
        episode_id=episode_id,
        decision_id=decision_id,
        ex_ante_digest=ex_ante_digest,
        self_consistency=self_consistency,
        retrieval_effective_n=retrieval_effective_n,
        gc_shadow={
            "state": "unknown",
            "gc_shadow_only": True,
            "authoritative_decision_input": False,
        },
        gc_feed_health={"state": "unknown", "authoritative_decision_input": False},
        macro_surprise={"state": "unknown", "forward_only": True},
        selective_shadow=_selective_shadow(self_consistency),
    )
    return await D1ImmediateForwardEvaluationStore(d1).record_evaluation(
        record,
        recorded_at_utc=observed_at,
    )


async def observe_private_forward_snapshot(
    *,
    d1: Any,
    scheduled_at: datetime,
    snapshot_id: UUID | str | None,
    gateway: Any | None = None,
    clock: Clock = lambda: datetime.now(UTC),
    decision_input_builder: DecisionInputBuilder = build_private_forward_decision_inputs,
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
    formal_cycle_id = _cycle_id(scheduled)
    existing = await d1.prepare(
        "SELECT record_id,disposition,data_quality_reason_code,decision_id,ex_ante_digest,"
        "self_consistency_digest,context_hash FROM aidy_forward_evaluations "
        "WHERE cohort_id=? AND cycle_id=? LIMIT 1"
    ).bind(cohort_id, formal_cycle_id).first()
    existing_row = _row(existing)
    if existing_row is not None:
        e2e = await d1.prepare(
            "SELECT cycle_id FROM aidy_end_to_end_cycles WHERE context_hash=? AND "
            "instruction_type='market_evaluation' AND source_state='private_forward' LIMIT 1"
        ).bind(str(existing_row["context_hash"])).first()
        e2e_row = _row(e2e)
        return ForwardLiveObservationResult(
            status="already_recorded",
            cohort_id=cohort_id,
            record_id=str(existing_row["record_id"]),
            disposition=str(existing_row["disposition"]),
            reason_code=str(existing_row.get("data_quality_reason_code") or "") or None,
            cycle_id=formal_cycle_id,
            end_to_end_cycle_id=None if e2e_row is None else str(e2e_row["cycle_id"]),
            decision_id=str(existing_row.get("decision_id") or "") or None,
            ex_ante_digest=str(existing_row.get("ex_ante_digest") or "") or None,
            self_consistency_digest=str(existing_row.get("self_consistency_digest") or "") or None,
            context_hash=str(existing_row["context_hash"]),
        )

    if snapshot_id is None:
        return ForwardLiveObservationResult(
            status="no_snapshot",
            cohort_id=cohort_id,
            cycle_id=formal_cycle_id,
        )
    snapshot = await _snapshot(d1, str(snapshot_id))
    if snapshot is None:
        return ForwardLiveObservationResult(
            status="snapshot_missing",
            cohort_id=cohort_id,
            cycle_id=formal_cycle_id,
        )

    captured = _utc(str(snapshot["captured_at"]), name="snapshot.captured_at")
    activated = _utc(str(cohort["activated_at_utc"]), name="cohort.activated_at_utc")
    if captured < activated:
        return ForwardLiveObservationResult(
            status="snapshot_predates_activation",
            cohort_id=cohort_id,
            cycle_id=formal_cycle_id,
        )

    observed_at = max(_utc(clock(), name="clock"), captured)
    reason = _blocked_reason(snapshot)
    if reason is not None:
        stored = await _record_forward(
            d1=d1,
            cohort=cohort,
            formal_cycle_id=formal_cycle_id,
            observed_at=observed_at,
            context_hash=_context_hash(snapshot),
            disposition="pre_model_blocked",
            data_quality_state="failure",
            data_quality_reason_code=reason,
            episode_id=_episode_id(snapshot, reason_code=reason),
            decision_id=None,
            ex_ante_digest=None,
            self_consistency=None,
            retrieval_effective_n=0,
        )
        return ForwardLiveObservationResult(
            status="recorded",
            cohort_id=cohort_id,
            record_id=str(stored["record_id"]),
            disposition="pre_model_blocked",
            reason_code=reason,
            cycle_id=formal_cycle_id,
            context_hash=str(stored["context_hash"]),
        )

    if gateway is None:
        reason = "production_model_gateway_not_configured"
        stored = await _record_forward(
            d1=d1,
            cohort=cohort,
            formal_cycle_id=formal_cycle_id,
            observed_at=observed_at,
            context_hash=_context_hash(snapshot),
            disposition="failed_closed",
            data_quality_state="unknown",
            data_quality_reason_code=reason,
            episode_id=_episode_id(snapshot, reason_code=reason),
            decision_id=None,
            ex_ante_digest=None,
            self_consistency=None,
            retrieval_effective_n=0,
        )
        return ForwardLiveObservationResult(
            status="recorded",
            cohort_id=cohort_id,
            record_id=str(stored["record_id"]),
            disposition="failed_closed",
            reason_code=reason,
            cycle_id=formal_cycle_id,
            context_hash=str(stored["context_hash"]),
        )

    try:
        inputs = await decision_input_builder(d1=d1, snapshot_id=str(snapshot_id))
    except Exception:
        reason = "production_decision_context_build_failed"
        stored = await _record_forward(
            d1=d1,
            cohort=cohort,
            formal_cycle_id=formal_cycle_id,
            observed_at=observed_at,
            context_hash=_context_hash(snapshot),
            disposition="failed_closed",
            data_quality_state="unknown",
            data_quality_reason_code=reason,
            episode_id=_episode_id(snapshot, reason_code=reason),
            decision_id=None,
            ex_ante_digest=None,
            self_consistency=None,
            retrieval_effective_n=0,
        )
        return ForwardLiveObservationResult(
            status="recorded",
            cohort_id=cohort_id,
            record_id=str(stored["record_id"]),
            disposition="failed_closed",
            reason_code=reason,
            cycle_id=formal_cycle_id,
            context_hash=str(stored["context_hash"]),
        )

    context = inputs.get("context")
    semantic_retrieval = inputs.get("semantic_retrieval")
    if not isinstance(context, Mapping) or not isinstance(semantic_retrieval, Mapping):
        raise TypeError("Private-forward decision builder returned invalid semantic inputs.")

    cycle_store = D1EndToEndCycleStore(d1)
    result = await run_market_evaluation_cycle(
        context=context,
        aidy_state=inputs["aidy_state"],
        retrieval=inputs["retrieval"],
        evidence_report=inputs["evidence_report"],
        hypothesis_direction=str(inputs["hypothesis_direction"]),
        setup_family=inputs.get("setup_family"),
        invalidation_inputs=inputs["invalidation_inputs"],
        setup_detection=inputs["setup_detection"],
        now_utc=observed_at,
        gateway=gateway,
        cycle_store=cycle_store,
        publication_store=D1PublicationLedgerStore(d1),
        transport=_ForbiddenPrivateForwardTransport(),
        chat_id="private-forward-no-publication",
        source_state="private_forward",
        publish_enabled=False,
        semantic_retrieval=semantic_retrieval,
    )
    end_to_end_cycle_id = str(result["cycle_id"])
    cycle_row = await cycle_store.get(end_to_end_cycle_id)
    if cycle_row is None:
        raise RuntimeError("Real private-forward cycle did not persist its restart journal.")
    self_consistency = _decode_artifact(cycle_row, "self_consistency_json")
    ex_ante = _decode_artifact(cycle_row, "ex_ante_json")
    status = str(result["status"])

    if status == "pre_model_blocked":
        disposition = "pre_model_blocked"
        data_quality_state = "failure"
        reason_code = str((result.get("reason_codes") or ["pre_model_blocked"])[0])
        self_consistency = None
    elif status == "self_consistency_abstain":
        disposition = "model_failed" if _model_failed(self_consistency) else "self_consistency_abstain"
        data_quality_state = "known_good"
        reason_code = None
    elif status == "no_trade":
        disposition = "no_trade"
        data_quality_state = "known_good"
        reason_code = None
    elif status == "decision_admitted_not_published":
        disposition = "decision_admitted"
        data_quality_state = "known_good"
        reason_code = None
    else:
        disposition = "failed_closed"
        data_quality_state = "unknown"
        reason_code = "production_architecture_v2_unexpected_cycle_status"

    decision_id = None if ex_ante is None else str(ex_ante.get("decision_id") or "") or None
    ex_ante_digest = None if ex_ante is None else str(ex_ante.get("ex_ante_digest") or "") or None
    stored = await _record_forward(
        d1=d1,
        cohort=cohort,
        formal_cycle_id=formal_cycle_id,
        observed_at=observed_at,
        context_hash=str(context["context_hash"]),
        disposition=disposition,
        data_quality_state=data_quality_state,
        data_quality_reason_code=reason_code,
        episode_id=str(inputs["episode_id"]),
        decision_id=decision_id,
        ex_ante_digest=ex_ante_digest,
        self_consistency=self_consistency,
        retrieval_effective_n=int(inputs.get("retrieval_effective_n") or 0),
    )
    return ForwardLiveObservationResult(
        status="recorded",
        cohort_id=cohort_id,
        record_id=str(stored["record_id"]),
        disposition=str(stored["disposition"]),
        reason_code=str(stored.get("data_quality_reason_code") or "") or None,
        cycle_id=formal_cycle_id,
        end_to_end_cycle_id=end_to_end_cycle_id,
        decision_id=decision_id,
        ex_ante_digest=ex_ante_digest,
        self_consistency_digest=(
            None if self_consistency is None else str(self_consistency["self_consistency_digest"])
        ),
        context_hash=str(context["context_hash"]),
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
        SELECT record_id,cycle_id,evaluated_at_utc,context_hash,disposition,data_quality_state,
               data_quality_reason_code,episode_id,decision_id,ex_ante_digest,
               self_consistency_digest,retrieval_effective_n,recorded_at_utc
        FROM aidy_forward_evaluations
        WHERE cohort_id=?
        ORDER BY evaluated_at_utc DESC,recorded_at_utc DESC
        LIMIT 1
        """
    ).bind(str(cohort["cohort_id"])).first()
    latest_row = _row(latest)
    end_to_end = None
    if latest_row is not None:
        end_to_end = await d1.prepare(
            """
            SELECT cycle_id,cycle_state,last_error_code,decision_id,ex_ante_digest,
                   self_consistency_digest,paper_state_digest,updated_at_utc
            FROM aidy_end_to_end_cycles
            WHERE context_hash=? AND instruction_type='market_evaluation'
              AND source_state='private_forward'
            ORDER BY updated_at_utc DESC LIMIT 1
            """
        ).bind(str(latest_row["context_hash"])).first()
    return {
        "observer_version": FORWARD_LIVE_OBSERVER_VERSION,
        "active": True,
        "cohort_id": str(cohort["cohort_id"]),
        "cohort_state": str(cohort["state"]),
        "accepted_code_head": str(cohort["accepted_code_head"]),
        "manifest_digest": str(cohort["manifest_digest"]),
        "activated_at_utc": str(cohort["activated_at_utc"]),
        "progress": progress,
        "latest_evaluation": latest_row,
        "latest_end_to_end_cycle": _row(end_to_end),
        "decision_adapter_enabled": True,
        "semantic_twelve_context_required": True,
        "k3_model_resolution_required": True,
        "openai_called_for_pre_model_block": False,
        "telegram_publication_enabled": False,
        "live_money_execution_enabled": False,
    }


def day53_live_forward_manifest() -> dict[str, Any]:
    result: dict[str, Any] = {
        "manifest_version": "aidy_day53_live_forward_activation_v2_real_cycle",
        "observer_version": FORWARD_LIVE_OBSERVER_VERSION,
        "observation_interval_seconds": FORWARD_OBSERVATION_INTERVAL_SECONDS,
        "requires_active_amended_cohort": True,
        "scheduled_timestamp_may_predate_snapshot_evaluation": False,
        "missing_live_ohlc_fails_pre_model": True,
        "missing_spread_is_advisory": True,
        "observed_out_of_tolerance_spread_fails_pre_model": True,
        "blocked_cycles_count_toward_day54_model_resolved_n": False,
        "decision_adapter_enabled_by_this_change": True,
        "real_day52_architecture_v2_cycle_required": True,
        "semantic_twelve_context_required": True,
        "current_objective_context_exposed_to_master_trader": True,
        "price_liquidity_structure_preserved": True,
        "cross_source_analogue_inheritance_allowed": False,
        "openai_called_for_pre_model_block": False,
        "telegram_publication_enabled": False,
        "broker_or_account_state_allowed": False,
        "follower_state_allowed": False,
        "super_signals_dependency_allowed": False,
        "live_money_execution_allowed": False,
    }
    result["manifest_digest"] = digest(result)
    return result
