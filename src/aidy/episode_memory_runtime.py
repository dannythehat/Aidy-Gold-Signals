from __future__ import annotations

import copy
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any

from aidy.episode_memory import (
    EPISODE_MEMORY_VERSION,
    MAX_AUTO_RESOLUTION_HORIZON_MINUTES,
    MEMORY_SYNC_VERSION,
    OUTCOME_RESOLVER_VERSION,
    D1EpisodeMemoryStore,
    _ceil_next_minute,
    _episode_payload,
    _memory_episode_id,
    _resolve_no_trade_path,
    _resolve_trade_path,
    _results,
    _safe_json_object,
    _utc,
    canonical_json,
    digest,
)
from aidy.decision_ledger import verify_ex_ante_record
from aidy.forward_evaluation import D1ForwardEvaluationStore, build_forward_outcome_attachment
from aidy.twelve_data_storage import D1TwelveDataMarketStore

RUNTIME_VERSION = "aidy_episode_memory_runtime_v1"


def _context_reference_price(ex_ante: Mapping[str, Any]) -> Any:
    """Read the exact ex-ante market mid for a no-trade shadow."""

    context = ex_ante.get("context_snapshot")
    if not isinstance(context, Mapping):
        return None
    gold = context.get("gold")
    if isinstance(gold, Mapping):
        quote = gold.get("quote_context")
        if isinstance(quote, Mapping) and quote.get("mid") is not None:
            return quote.get("mid")
    quote = context.get("quote_context")
    if isinstance(quote, Mapping):
        return quote.get("mid")
    return None


def _shadow_resolution_record(ex_ante: Mapping[str, Any]) -> dict[str, Any]:
    """Create a resolver-only copy with PIT shadow reference geometry.

    The immutable ex-ante record remains untouched. This derived copy exists only so
    a no-trade shadow can start from the market mid that was genuinely known then.
    """

    copied = copy.deepcopy(dict(ex_ante))
    decision = copied.get("decision")
    if not isinstance(decision, Mapping):
        return copied
    normalized = copy.deepcopy(dict(decision))
    if normalized.get("action") == "no_trade" and normalized.get("market_reference_price") is None:
        normalized["market_reference_price"] = _context_reference_price(ex_ante)
    copied["decision"] = normalized
    return copied


def _enriched_episode_payload(
    *,
    cycle: Mapping[str, Any],
    ex_ante: Mapping[str, Any],
    forward: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Build compact durable memory with enough setup/regime evidence to learn later."""

    payload = _episode_payload(cycle=cycle, ex_ante=ex_ante, forward=forward)
    raw_decision = ex_ante.get("decision")
    if isinstance(raw_decision, Mapping):
        decision = payload.get("decision")
        if isinstance(decision, dict):
            decision.update(
                {
                    "confidence": raw_decision.get("confidence"),
                    "setup_codes": copy.deepcopy(raw_decision.get("setup_codes") or []),
                    "reason_codes": copy.deepcopy(raw_decision.get("reason_codes") or []),
                    "decision_summary": raw_decision.get("decision_summary"),
                    "valid_until_utc": raw_decision.get("valid_until_utc"),
                    "entry_type": raw_decision.get("entry_type"),
                }
            )

    repro = ex_ante.get("reproducibility_bundle")
    if isinstance(repro, Mapping):
        evidence = payload.get("evidence")
        if isinstance(evidence, dict):
            evidence.update(
                {
                    "regime_state": copy.deepcopy(repro.get("regime_state") or {}),
                    "setup_state": copy.deepcopy(repro.get("setup_state") or {}),
                    "selective_layer_state": copy.deepcopy(repro.get("selective_layer_state")),
                    "analogue_retrieval_version": repro.get("analogue_retrieval_version"),
                    "analogue_retrieval_digest": repro.get("analogue_retrieval_digest"),
                }
            )

    context = ex_ante.get("context_snapshot")
    context_summary: dict[str, Any] = {
        "as_of_utc": None,
        "symbol": "XAUUSD",
        "market_mid": _context_reference_price(ex_ante),
    }
    if isinstance(context, Mapping):
        context_summary["as_of_utc"] = context.get("as_of_utc")
        context_summary["symbol"] = context.get("symbol") or "XAUUSD"
    payload["context_summary"] = context_summary
    payload["episode_digest"] = ""
    payload.pop("episode_digest", None)
    payload["episode_digest"] = digest(payload)
    return payload


class D1EpisodeMemoryRuntimeStore(D1EpisodeMemoryStore):
    async def materialize_episodes(
        self,
        *,
        recorded_at_utc: datetime,
        limit: int = 50,
    ) -> int:
        result = await self._d1.prepare(
            """
            SELECT c.cycle_id,c.source_state,c.ex_ante_json,c.ex_ante_digest,c.decision_id,
                   f.record_id AS forward_record_id,f.cohort_id
            FROM aidy_end_to_end_cycles c
            LEFT JOIN aidy_forward_evaluations f ON f.ex_ante_digest=c.ex_ante_digest
            LEFT JOIN aidy_memory_episodes m ON m.ex_ante_digest=c.ex_ante_digest
            WHERE c.ex_ante_json IS NOT NULL AND c.ex_ante_digest IS NOT NULL
              AND m.memory_episode_id IS NULL
            ORDER BY c.created_at_utc,c.cycle_id
            LIMIT ?
            """
        ).bind(max(1, min(int(limit), 500))).all()
        rows = _results(result)
        stamp = _utc(recorded_at_utc, name="recorded_at_utc").isoformat()
        inserted = 0

        for row in rows:
            ex_ante = _safe_json_object(row["ex_ante_json"], name="ex_ante_json")
            if not verify_ex_ante_record(ex_ante):
                raise ValueError(f"Invalid immutable ex-ante record in cycle {row['cycle_id']}.")
            if str(ex_ante["ex_ante_digest"]) != str(row["ex_ante_digest"]):
                raise ValueError("End-to-end ex-ante digest mismatch.")
            forward = None
            if row.get("forward_record_id"):
                forward = {
                    "record_id": row["forward_record_id"],
                    "cohort_id": row.get("cohort_id"),
                }
            payload = _enriched_episode_payload(cycle=row, ex_ante=ex_ante, forward=forward)
            episode_id = _memory_episode_id(str(ex_ante["ex_ante_digest"]))
            decision = payload.get("decision") if isinstance(payload.get("decision"), Mapping) else {}
            text = canonical_json(payload)
            await self._d1.prepare(
                """
                INSERT INTO aidy_memory_episodes (
                    memory_episode_id,memory_version,source_cycle_id,source_state,
                    forward_record_id,cohort_id,evaluation_id,decision_id,ex_ante_digest,
                    evaluated_at_utc,context_hash,disposition,decision_action,direction,
                    expected_horizon_minutes,thesis_text,episode_json,episode_digest,
                    recorded_at_utc
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(memory_episode_id) DO NOTHING
                """
            ).bind(
                episode_id,
                EPISODE_MEMORY_VERSION,
                row["cycle_id"],
                row["source_state"],
                row.get("forward_record_id"),
                row.get("cohort_id"),
                ex_ante["evaluation_id"],
                ex_ante["decision_id"],
                ex_ante["ex_ante_digest"],
                ex_ante["evaluated_at_utc"],
                ex_ante["context_hash"],
                ex_ante["cycle_disposition"],
                decision.get("action"),
                decision.get("direction"),
                decision.get("expected_horizon_minutes"),
                decision.get("thesis"),
                text,
                payload["episode_digest"],
                stamp,
            ).run()
            stored = await self._first(
                "SELECT episode_digest,episode_json FROM aidy_memory_episodes WHERE memory_episode_id=? LIMIT 1",
                episode_id,
            )
            if (
                stored is None
                or stored.get("episode_digest") != payload["episode_digest"]
                or stored.get("episode_json") != text
            ):
                raise RuntimeError("Immutable AIDY memory episode conflict.")
            inserted += 1
        return inserted

    async def resolve_due_forward_outcomes(
        self,
        *,
        now_utc: datetime,
        limit: int = 20,
    ) -> dict[str, int]:
        """Resolve only matured bounded-horizon private-forward episodes."""

        now = _utc(now_utc, name="now_utc")
        result = await self._d1.prepare(
            """
            SELECT f.record_id,f.record_json,f.disposition,f.evaluated_at_utc,f.ex_ante_digest,
                   c.ex_ante_json,
                   json_extract(c.ex_ante_json,'$.decision.action') AS decision_action,
                   CASE
                     WHEN json_extract(c.ex_ante_json,'$.decision.action')='new_trade'
                       THEN CAST(json_extract(c.ex_ante_json,'$.decision.expected_horizon_minutes') AS INTEGER)
                     WHEN json_extract(c.ex_ante_json,'$.decision.action')='no_trade'
                       THEN CAST(json_extract(c.ex_ante_json,'$.decision.shadow_horizon_minutes') AS INTEGER)
                     ELSE NULL
                   END AS resolution_horizon_minutes
            FROM aidy_forward_evaluations f
            JOIN aidy_end_to_end_cycles c ON c.ex_ante_digest=f.ex_ante_digest
            LEFT JOIN aidy_forward_outcomes o ON o.record_id=f.record_id
            WHERE o.attachment_id IS NULL
              AND f.disposition IN ('decision_admitted','no_trade')
              AND c.ex_ante_json IS NOT NULL
              AND json_extract(c.ex_ante_json,'$.decision.action') IN ('new_trade','no_trade')
              AND CASE
                    WHEN json_extract(c.ex_ante_json,'$.decision.action')='new_trade'
                      THEN CAST(json_extract(c.ex_ante_json,'$.decision.expected_horizon_minutes') AS INTEGER)
                    ELSE CAST(json_extract(c.ex_ante_json,'$.decision.shadow_horizon_minutes') AS INTEGER)
                  END BETWEEN 1 AND ?
              AND julianday(f.evaluated_at_utc) + (
                    CASE
                      WHEN json_extract(c.ex_ante_json,'$.decision.action')='new_trade'
                        THEN CAST(json_extract(c.ex_ante_json,'$.decision.expected_horizon_minutes') AS REAL)
                      ELSE CAST(json_extract(c.ex_ante_json,'$.decision.shadow_horizon_minutes') AS REAL)
                    END / 1440.0
                  ) <= julianday(?)
            ORDER BY f.evaluated_at_utc,f.record_id
            LIMIT ?
            """
        ).bind(
            MAX_AUTO_RESOLUTION_HORIZON_MINUTES,
            now.isoformat(),
            max(1, min(int(limit), 100)),
        ).all()
        rows = _results(result)
        market = D1TwelveDataMarketStore(self._d1)
        forward_store = D1ForwardEvaluationStore(self._d1)
        stats = {"resolved": 0, "pending": 0, "skipped": 0}

        for row in rows:
            ex_ante = _safe_json_object(row["ex_ante_json"], name="ex_ante_json")
            if not verify_ex_ante_record(ex_ante):
                raise ValueError("Cannot resolve outcome from invalid ex-ante record.")
            evaluation = _safe_json_object(row["record_json"], name="record_json")
            action = str(row.get("decision_action") or "")
            horizon = row.get("resolution_horizon_minutes")
            if isinstance(horizon, bool) or not isinstance(horizon, int) or horizon <= 0:
                stats["skipped"] += 1
                continue

            evaluated = _utc(str(row["evaluated_at_utc"]), name="evaluated_at_utc")
            deadline = evaluated + timedelta(minutes=horizon)
            start = _ceil_next_minute(evaluated)
            if start >= deadline:
                stats["skipped"] += 1
                continue
            bars = await market.latest_m1_bars(start_utc=start, end_utc=deadline)

            if action == "new_trade":
                outcome_type = "trade_outcome"
                outcome = _resolve_trade_path(
                    ex_ante=ex_ante,
                    bars=bars,
                    start=start,
                    deadline=deadline,
                )
            elif action == "no_trade":
                outcome_type = "no_trade_shadow"
                outcome = _resolve_no_trade_path(
                    ex_ante=_shadow_resolution_record(ex_ante),
                    bars=bars,
                    start=start,
                    deadline=deadline,
                )
            else:
                stats["skipped"] += 1
                continue

            payload: dict[str, Any] = {
                "resolver_version": OUTCOME_RESOLVER_VERSION,
                "runtime_version": RUNTIME_VERSION,
                "evidence_source": "twelve_data_decision_admitted_m1_v1",
                "evaluated_at_utc": evaluated.isoformat(),
                "horizon_minutes": horizon,
                "resolution_deadline_utc": deadline.isoformat(),
                "first_eligible_m1_open_utc": start.isoformat(),
                "m1_bar_count": len(bars),
                "no_hindsight_intrabar_ordering": True,
                "no_trade_reference_is_ex_ante_context_mid": action == "no_trade",
                "active_cohort_tuning_allowed": False,
                **outcome,
            }
            attachment = build_forward_outcome_attachment(
                evaluation_record=evaluation,
                outcome_type=outcome_type,
                attached_at_utc=now,
                outcome_payload=payload,
            )
            await forward_store.attach_outcome(attachment, recorded_at_utc=now)
            stats["resolved"] += 1

        return stats


async def sync_aidy_episode_memory_runtime(
    d1: Any,
    *,
    now_utc: datetime,
    episode_limit: int = 50,
    outcome_limit: int = 20,
) -> dict[str, Any]:
    now = _utc(now_utc, name="now_utc")
    store = D1EpisodeMemoryRuntimeStore(d1)
    episodes = await store.materialize_episodes(recorded_at_utc=now, limit=episode_limit)
    resolution = await store.resolve_due_forward_outcomes(now_utc=now, limit=outcome_limit)
    materialized = await store.materialize_outcomes_and_learning(
        recorded_at_utc=now,
        limit=episode_limit,
    )
    summary = await store.summary(as_of_utc=now)
    result = {
        "memory_sync_version": MEMORY_SYNC_VERSION,
        "runtime_version": RUNTIME_VERSION,
        "observed_at_utc": now.isoformat(),
        "episodes_materialized": episodes,
        "forward_outcomes": resolution,
        "outcomes_materialized": materialized["outcomes"],
        "learning_cards_materialized": materialized["learning_cards"],
        "summary": summary,
    }
    result["sync_digest"] = digest(result)
    return result
