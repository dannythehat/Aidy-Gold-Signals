from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Any

from aidy.decision_ledger import verify_ex_ante_record
from aidy.forward_evaluation import (
    D1ForwardEvaluationStore,
    build_forward_outcome_attachment,
)
from aidy.twelve_data_storage import D1TwelveDataMarketStore

EPISODE_MEMORY_VERSION = "aidy_episode_memory_v1"
MEMORY_OUTCOME_VERSION = "aidy_episode_memory_outcome_v1"
LEARNING_CARD_VERSION = "aidy_structured_learning_card_v1"
OUTCOME_RESOLVER_VERSION = "aidy_m1_episode_outcome_resolver_v1"
MEMORY_SYNC_VERSION = "aidy_episode_memory_sync_v1"
MAX_AUTO_RESOLUTION_HORIZON_MINUTES = 1440


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value: object) -> str:
    return sha256(canonical_json(value).encode()).hexdigest()


def _utc(value: datetime | str, *, name: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip())
        except ValueError as exc:
            raise ValueError(f"{name} must be timezone-aware ISO-8601 text.") from exc
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


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None


def _q(value: Decimal | None) -> str | None:
    return None if value is None else str(value.quantize(Decimal("0.000000")))


def _safe_json_object(raw: Any, *, name: str) -> dict[str, Any]:
    if isinstance(raw, Mapping):
        return copy.deepcopy(dict(raw))
    if not isinstance(raw, str) or not raw:
        raise TypeError(f"{name} must be JSON object text.")
    decoded = json.loads(raw)
    if not isinstance(decoded, dict):
        raise TypeError(f"{name} must decode to an object.")
    return decoded


def _ceil_next_minute(value: datetime) -> datetime:
    stamp = value.astimezone(UTC).replace(second=0, microsecond=0)
    return stamp + timedelta(minutes=1)


def _decision_summary(ex_ante: Mapping[str, Any]) -> dict[str, Any]:
    decision = ex_ante.get("decision")
    if not isinstance(decision, Mapping):
        return {
            "action": None,
            "direction": None,
            "expected_horizon_minutes": None,
            "thesis": None,
            "counter_argument": None,
            "invalidation_condition": None,
            "shadow_thesis": None,
            "shadow_direction": None,
            "shadow_horizon_minutes": None,
            "shadow_evaluation_condition": None,
            "market_reference_price": None,
            "stop_loss": None,
            "targets": [],
        }
    return {
        "action": decision.get("action"),
        "direction": decision.get("direction"),
        "expected_horizon_minutes": decision.get("expected_horizon_minutes"),
        "thesis": decision.get("thesis"),
        "counter_argument": decision.get("counter_argument"),
        "invalidation_condition": copy.deepcopy(decision.get("invalidation_condition")),
        "shadow_thesis": decision.get("shadow_thesis"),
        "shadow_direction": decision.get("shadow_direction"),
        "shadow_horizon_minutes": decision.get("shadow_horizon_minutes"),
        "shadow_evaluation_condition": copy.deepcopy(decision.get("shadow_evaluation_condition")),
        "market_reference_price": decision.get("market_reference_price"),
        "stop_loss": decision.get("stop_loss"),
        "targets": copy.deepcopy(decision.get("targets") or []),
    }


def _episode_payload(
    *,
    cycle: Mapping[str, Any],
    ex_ante: Mapping[str, Any],
    forward: Mapping[str, Any] | None,
) -> dict[str, Any]:
    decision = _decision_summary(ex_ante)
    repro = ex_ante.get("reproducibility_bundle")
    repro = dict(repro) if isinstance(repro, Mapping) else {}
    payload: dict[str, Any] = {
        "memory_version": EPISODE_MEMORY_VERSION,
        "evaluation_id": ex_ante["evaluation_id"],
        "decision_id": ex_ante["decision_id"],
        "ex_ante_digest": ex_ante["ex_ante_digest"],
        "evaluated_at_utc": ex_ante["evaluated_at_utc"],
        "source_cycle_id": cycle["cycle_id"],
        "source_state": cycle["source_state"],
        "forward_record_id": None if forward is None else forward.get("record_id"),
        "cohort_id": None if forward is None else forward.get("cohort_id"),
        "context_hash": ex_ante["context_hash"],
        "disposition": ex_ante["cycle_disposition"],
        "decision": decision,
        "evidence": {
            "evidence_grade": repro.get("evidence_grade"),
            "effective_n": repro.get("effective_n"),
            "strategy_version": repro.get("strategy_version"),
            "config_version": repro.get("config_version"),
            "model_id": repro.get("model_id"),
            "analogue_case_ids": copy.deepcopy(repro.get("analogue_case_ids") or []),
            "data_quality_flags": copy.deepcopy(ex_ante.get("data_quality_flags") or {}),
        },
        "future_outcome_fields_present": False,
        "hidden_reasoning_stored": False,
        "broker_or_account_state_used": False,
        "follower_state_used": False,
        "super_signals_used": False,
        "live_money_execution_used": False,
    }
    payload["episode_digest"] = digest(payload)
    return payload


def _memory_episode_id(ex_ante_digest: str) -> str:
    return f"aidy_mem_{digest({'ex_ante_digest': ex_ante_digest})[:32]}"


def _continuity(bars: list[dict[str, Any]], *, start: datetime, deadline: datetime) -> dict[str, Any]:
    if not bars:
        return {"state": "missing", "gap_before_first": True, "gap_count": 0, "covers_deadline": False}
    opens = [_utc(str(row["open_time_utc"]), name="open_time_utc") for row in bars]
    gap_before_first = opens[0] > start + timedelta(seconds=5)
    gap_count = sum(
        1
        for left, right in zip(opens, opens[1:])
        if right - left > timedelta(seconds=65)
    )
    covers_deadline = opens[-1] + timedelta(minutes=1) >= deadline - timedelta(seconds=5)
    state = "complete" if not gap_before_first and gap_count == 0 and covers_deadline else "gapped"
    return {
        "state": state,
        "gap_before_first": gap_before_first,
        "gap_count": gap_count,
        "covers_deadline": covers_deadline,
        "first_open_utc": opens[0].isoformat(),
        "last_open_utc": opens[-1].isoformat(),
    }


def _directional_target_r(direction: str, entry: Decimal, stop: Decimal, target: Decimal) -> Decimal:
    risk = abs(entry - stop)
    if risk <= 0:
        raise ValueError("Trade geometry has zero risk distance.")
    move = target - entry if direction == "long" else entry - target
    return move / risk


def _resolve_trade_path(
    *,
    ex_ante: Mapping[str, Any],
    bars: list[dict[str, Any]],
    start: datetime,
    deadline: datetime,
) -> dict[str, Any]:
    decision = _decision_summary(ex_ante)
    direction = str(decision.get("direction") or "")
    entry = _decimal(decision.get("market_reference_price"))
    stop = _decimal(decision.get("stop_loss"))
    targets = [_decimal(item) for item in decision.get("targets") or []]
    if direction not in {"long", "short"} or entry is None or stop is None or not targets or any(
        item is None for item in targets
    ):
        return {
            "outcome_state": "invalid_geometry",
            "score_eligible": False,
            "realized_r": None,
            "hit_target_indices": [],
            "continuity": _continuity(bars, start=start, deadline=deadline),
        }
    concrete_targets = [item for item in targets if item is not None]
    continuity = _continuity(bars, start=start, deadline=deadline)
    hit: set[int] = set()
    previous_open: datetime | None = None
    gap_seen = continuity["gap_before_first"]
    terminal_state: str | None = None
    terminal_at: str | None = None

    for row in bars:
        opened = _utc(str(row["open_time_utc"]), name="open_time_utc")
        if previous_open is not None and opened - previous_open > timedelta(seconds=65):
            gap_seen = True
        previous_open = opened
        high = _decimal(row.get("high"))
        low = _decimal(row.get("low"))
        if high is None or low is None:
            gap_seen = True
            continue
        if direction == "long":
            stop_hit = low <= stop
            newly_hit = [i for i, target in enumerate(concrete_targets, start=1) if i not in hit and high >= target]
        else:
            stop_hit = high >= stop
            newly_hit = [i for i, target in enumerate(concrete_targets, start=1) if i not in hit and low <= target]
        if stop_hit and newly_hit:
            terminal_state = "ambiguous_intrabar_order"
            terminal_at = opened.isoformat()
            break
        if stop_hit:
            terminal_state = "stop_hit_after_path_gap" if gap_seen else "stop_hit"
            terminal_at = opened.isoformat()
            break
        hit.update(newly_hit)
        if len(hit) == len(concrete_targets):
            terminal_state = "targets_hit_after_path_gap" if gap_seen else "all_targets_hit"
            terminal_at = opened.isoformat()
            break

    if terminal_state is None:
        terminal_state = "horizon_complete_no_terminal" if continuity["covers_deadline"] else "insufficient_m1_path"

    score_eligible = terminal_state in {"stop_hit", "all_targets_hit"}
    realized: Decimal | None = None
    if terminal_state in {"stop_hit", "all_targets_hit"}:
        n = Decimal(len(concrete_targets))
        realized = sum(
            (_directional_target_r(direction, entry, stop, concrete_targets[index - 1]) / n)
            for index in sorted(hit)
        )
        if terminal_state == "stop_hit":
            realized -= Decimal(len(concrete_targets) - len(hit)) / n

    return {
        "outcome_state": terminal_state,
        "score_eligible": score_eligible,
        "realized_r": _q(realized),
        "hit_target_indices": sorted(hit),
        "terminal_at_utc": terminal_at,
        "continuity": continuity,
        "geometry": {
            "direction": direction,
            "entry_price": _q(entry),
            "stop_loss": _q(stop),
            "targets": [_q(item) for item in concrete_targets],
        },
    }


def _resolve_no_trade_path(
    *,
    ex_ante: Mapping[str, Any],
    bars: list[dict[str, Any]],
    start: datetime,
    deadline: datetime,
) -> dict[str, Any]:
    decision = _decision_summary(ex_ante)
    direction = str(decision.get("shadow_direction") or "")
    entry = _decimal(decision.get("market_reference_price"))
    continuity = _continuity(bars, start=start, deadline=deadline)
    if entry is None or not bars or direction not in {"long", "short", "flat"}:
        return {
            "outcome_state": "insufficient_shadow_geometry",
            "score_eligible": False,
            "continuity": continuity,
        }
    end_price = _decimal(bars[-1].get("close"))
    if end_price is None:
        return {
            "outcome_state": "invalid_terminal_price",
            "score_eligible": False,
            "continuity": continuity,
        }
    move = end_price - entry
    if direction == "long":
        signed = move
    elif direction == "short":
        signed = -move
    else:
        signed = Decimal(0)
    if direction == "flat":
        classification = "flat_shadow_observed"
    elif signed > 0:
        classification = "shadow_direction_favorable"
    elif signed < 0:
        classification = "shadow_direction_adverse"
    else:
        classification = "shadow_direction_flat"
    eligible = continuity["state"] == "complete"
    return {
        "outcome_state": classification,
        "score_eligible": eligible,
        "continuity": continuity,
        "shadow_direction": direction,
        "entry_price": _q(entry),
        "terminal_price": _q(end_price),
        "move_points": _q(move),
        "directional_move_points": _q(signed),
    }


def _outcome_class(outcome: Mapping[str, Any]) -> tuple[str, str | None]:
    state = str(outcome.get("outcome_state") or "unknown")
    realized = _decimal(outcome.get("realized_r"))
    if realized is not None:
        if realized > 0:
            return "favorable", _q(realized)
        if realized < 0:
            return "adverse", _q(realized)
        return "flat", _q(realized)
    if state == "shadow_direction_favorable":
        return "favorable_shadow", None
    if state == "shadow_direction_adverse":
        return "adverse_shadow", None
    if state in {"shadow_direction_flat", "flat_shadow_observed"}:
        return "flat_shadow", None
    if state.startswith("ambiguous") or "gap" in state or state.startswith("insufficient"):
        return "unscored", None
    return "observed", None


class D1EpisodeMemoryStore:
    def __init__(self, d1: Any) -> None:
        self._d1 = d1

    async def _first(self, sql: str, *params: object) -> dict[str, Any] | None:
        return _row(await self._d1.prepare(sql).bind(*params).first())

    async def materialize_episodes(self, *, recorded_at_utc: datetime, limit: int = 50) -> int:
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
        ).bind(int(limit)).all()
        rows = _results(result)
        inserted = 0
        stamp = _utc(recorded_at_utc, name="recorded_at_utc").isoformat()
        for row in rows:
            ex_ante = _safe_json_object(row["ex_ante_json"], name="ex_ante_json")
            if not verify_ex_ante_record(ex_ante):
                raise ValueError(f"Invalid immutable ex-ante record in cycle {row['cycle_id']}.")
            if str(ex_ante["ex_ante_digest"]) != str(row["ex_ante_digest"]):
                raise ValueError("End-to-end ex-ante digest mismatch.")
            forward = None
            if row.get("forward_record_id"):
                forward = {"record_id": row["forward_record_id"], "cohort_id": row.get("cohort_id")}
            payload = _episode_payload(cycle=row, ex_ante=ex_ante, forward=forward)
            episode_id = _memory_episode_id(str(ex_ante["ex_ante_digest"]))
            decision = payload["decision"]
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
            if stored is None or stored.get("episode_digest") != payload["episode_digest"] or stored.get("episode_json") != text:
                raise RuntimeError("Immutable AIDY memory episode conflict.")
            inserted += 1
        return inserted

    async def resolve_due_forward_outcomes(self, *, now_utc: datetime, limit: int = 20) -> dict[str, int]:
        now = _utc(now_utc, name="now_utc")
        result = await self._d1.prepare(
            """
            SELECT f.record_id,f.record_json,f.disposition,f.evaluated_at_utc,f.ex_ante_digest,
                   c.ex_ante_json
            FROM aidy_forward_evaluations f
            JOIN aidy_end_to_end_cycles c ON c.ex_ante_digest=f.ex_ante_digest
            LEFT JOIN aidy_forward_outcomes o ON o.record_id=f.record_id
            WHERE o.attachment_id IS NULL
              AND f.disposition IN ('decision_admitted','no_trade')
              AND c.ex_ante_json IS NOT NULL
            ORDER BY f.evaluated_at_utc,f.record_id
            LIMIT ?
            """
        ).bind(int(limit)).all()
        rows = _results(result)
        market = D1TwelveDataMarketStore(self._d1)
        forward_store = D1ForwardEvaluationStore(self._d1)
        stats = {"resolved": 0, "pending": 0, "skipped": 0}
        for row in rows:
            ex_ante = _safe_json_object(row["ex_ante_json"], name="ex_ante_json")
            if not verify_ex_ante_record(ex_ante):
                raise ValueError("Cannot resolve outcome from invalid ex-ante record.")
            evaluation = _safe_json_object(row["record_json"], name="record_json")
            decision = _decision_summary(ex_ante)
            action = str(decision.get("action") or "")
            evaluated = _utc(str(row["evaluated_at_utc"]), name="evaluated_at_utc")
            if action == "new_trade":
                horizon = decision.get("expected_horizon_minutes")
                outcome_type = "trade_outcome"
            elif action == "no_trade":
                horizon = decision.get("shadow_horizon_minutes")
                outcome_type = "no_trade_shadow"
            else:
                stats["skipped"] += 1
                continue
            if isinstance(horizon, bool) or not isinstance(horizon, int) or horizon <= 0:
                stats["skipped"] += 1
                continue
            if horizon > MAX_AUTO_RESOLUTION_HORIZON_MINUTES:
                stats["skipped"] += 1
                continue
            deadline = evaluated + timedelta(minutes=horizon)
            if now < deadline:
                stats["pending"] += 1
                continue
            start = _ceil_next_minute(evaluated)
            if start >= deadline:
                stats["skipped"] += 1
                continue
            bars = await market.latest_m1_bars(start_utc=start, end_utc=deadline)
            if action == "new_trade":
                outcome = _resolve_trade_path(ex_ante=ex_ante, bars=bars, start=start, deadline=deadline)
            else:
                outcome = _resolve_no_trade_path(ex_ante=ex_ante, bars=bars, start=start, deadline=deadline)
            payload: dict[str, Any] = {
                "resolver_version": OUTCOME_RESOLVER_VERSION,
                "evidence_source": "twelve_data_decision_admitted_m1_v1",
                "evaluated_at_utc": evaluated.isoformat(),
                "horizon_minutes": horizon,
                "resolution_deadline_utc": deadline.isoformat(),
                "first_eligible_m1_open_utc": start.isoformat(),
                "m1_bar_count": len(bars),
                "no_hindsight_intrabar_ordering": True,
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

    async def materialize_outcomes_and_learning(self, *, recorded_at_utc: datetime, limit: int = 50) -> dict[str, int]:
        stamp = _utc(recorded_at_utc, name="recorded_at_utc").isoformat()
        result = await self._d1.prepare(
            """
            SELECT o.attachment_id,o.attachment_json,o.outcome_type,o.attached_at_utc,
                   m.memory_episode_id,m.episode_json
            FROM aidy_forward_outcomes o
            JOIN aidy_forward_evaluations f ON f.record_id=o.record_id
            JOIN aidy_memory_episodes m ON m.ex_ante_digest=f.ex_ante_digest
            LEFT JOIN aidy_memory_outcomes mo ON mo.source_attachment_id=o.attachment_id
            WHERE mo.memory_outcome_id IS NULL
            ORDER BY o.attached_at_utc,o.attachment_id
            LIMIT ?
            """
        ).bind(int(limit)).all()
        rows = _results(result)
        stats = {"outcomes": 0, "learning_cards": 0}
        for row in rows:
            attachment = _safe_json_object(row["attachment_json"], name="attachment_json")
            payload = attachment.get("outcome_payload")
            payload = dict(payload) if isinstance(payload, Mapping) else {}
            outcome_state = str(payload.get("outcome_state") or payload.get("shadow_result") or "observed")
            eligible = bool(payload.get("score_eligible") is True)
            memory_outcome_id = f"aidy_mem_out_{digest({'attachment_id': row['attachment_id']})[:32]}"
            outcome_record = {
                "outcome_version": MEMORY_OUTCOME_VERSION,
                "memory_outcome_id": memory_outcome_id,
                "memory_episode_id": row["memory_episode_id"],
                "source_attachment_id": row["attachment_id"],
                "source_outcome_type": row["outcome_type"],
                "outcome_state": outcome_state,
                "score_eligible": eligible,
                "attached_at_utc": row["attached_at_utc"],
                "source_attachment_digest": attachment.get("attachment_digest"),
                "outcome_payload": copy.deepcopy(payload),
            }
            outcome_record["outcome_digest"] = digest(outcome_record)
            outcome_text = canonical_json(outcome_record)
            await self._d1.prepare(
                """
                INSERT INTO aidy_memory_outcomes (
                    memory_outcome_id,outcome_version,memory_episode_id,source_attachment_id,
                    source_outcome_type,outcome_state,score_eligible,attached_at_utc,
                    outcome_json,outcome_digest,recorded_at_utc
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(memory_outcome_id) DO NOTHING
                """
            ).bind(
                memory_outcome_id,
                MEMORY_OUTCOME_VERSION,
                row["memory_episode_id"],
                row["attachment_id"],
                row["outcome_type"],
                outcome_state,
                1 if eligible else 0,
                row["attached_at_utc"],
                outcome_text,
                outcome_record["outcome_digest"],
                stamp,
            ).run()
            stats["outcomes"] += 1

            episode = _safe_json_object(row["episode_json"], name="episode_json")
            action = str((episode.get("decision") or {}).get("action") or "unknown")
            direction = str((episode.get("decision") or {}).get("direction") or (episode.get("decision") or {}).get("shadow_direction") or "none")
            outcome_class, realized_r = _outcome_class(payload)
            thesis_class = str((payload.get("thesis_outcome") or {}).get("status") or "not_evaluated") if isinstance(payload.get("thesis_outcome"), Mapping) else "not_evaluated"
            tags = sorted({
                f"action:{action}",
                f"direction:{direction}",
                f"outcome:{outcome_class}",
                f"thesis:{thesis_class}",
                f"source:{row['outcome_type']}",
            })
            card_id = f"aidy_learn_{digest({'memory_outcome_id': memory_outcome_id})[:32]}"
            card = {
                "learning_version": LEARNING_CARD_VERSION,
                "card_id": card_id,
                "memory_episode_id": row["memory_episode_id"],
                "memory_outcome_id": memory_outcome_id,
                "available_at_utc": row["attached_at_utc"],
                "decision_action": action,
                "direction": direction,
                "outcome_class": outcome_class,
                "thesis_class": thesis_class,
                "realized_r": realized_r,
                "score_eligible": eligible,
                "tags": tags,
                "ex_ante_digest": episode.get("ex_ante_digest"),
                "episode_digest": episode.get("episode_digest"),
                "outcome_digest": outcome_record["outcome_digest"],
                "same_episode_retrieval_allowed": False,
                "hidden_reasoning_stored": False,
                "active_cohort_tuning_allowed": False,
            }
            card["card_digest"] = digest(card)
            card_text = canonical_json(card)
            await self._d1.prepare(
                """
                INSERT INTO aidy_learning_cards (
                    card_id,learning_version,memory_episode_id,memory_outcome_id,
                    available_at_utc,outcome_class,thesis_class,realized_r,tags_json,
                    card_json,card_digest,score_eligible,created_at_utc
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(card_id) DO NOTHING
                """
            ).bind(
                card_id,
                LEARNING_CARD_VERSION,
                row["memory_episode_id"],
                memory_outcome_id,
                row["attached_at_utc"],
                outcome_class,
                thesis_class,
                realized_r,
                canonical_json(tags),
                card_text,
                card["card_digest"],
                1 if eligible else 0,
                stamp,
            ).run()
            stats["learning_cards"] += 1
        return stats

    async def recent_learning_cards(
        self,
        *,
        as_of_utc: datetime,
        limit: int = 20,
        score_eligible_only: bool = True,
    ) -> list[dict[str, Any]]:
        as_of = _utc(as_of_utc, name="as_of_utc").isoformat()
        condition = "AND score_eligible=1" if score_eligible_only else ""
        result = await self._d1.prepare(
            f"""
            SELECT card_json FROM aidy_learning_cards
            WHERE available_at_utc<=? {condition}
            ORDER BY available_at_utc DESC,card_id DESC
            LIMIT ?
            """
        ).bind(as_of, max(1, min(int(limit), 200))).all()
        return [_safe_json_object(row["card_json"], name="card_json") for row in _results(result)]

    async def summary(self, *, as_of_utc: datetime) -> dict[str, Any]:
        as_of = _utc(as_of_utc, name="as_of_utc").isoformat()
        row = await self._first(
            """
            SELECT
              (SELECT COUNT(*) FROM aidy_memory_episodes WHERE evaluated_at_utc<=?) AS episode_count,
              (SELECT COUNT(*) FROM aidy_memory_outcomes WHERE attached_at_utc<=?) AS outcome_count,
              (SELECT COUNT(*) FROM aidy_learning_cards WHERE available_at_utc<=?) AS learning_card_count,
              (SELECT COUNT(*) FROM aidy_learning_cards WHERE available_at_utc<=? AND score_eligible=1) AS score_eligible_learning_count,
              (SELECT MAX(available_at_utc) FROM aidy_learning_cards WHERE available_at_utc<=?) AS latest_learning_available_at_utc
            """,
            as_of,
            as_of,
            as_of,
            as_of,
            as_of,
        ) or {}
        summary = {
            "memory_sync_version": MEMORY_SYNC_VERSION,
            "as_of_utc": as_of,
            "episode_count": int(row.get("episode_count") or 0),
            "outcome_count": int(row.get("outcome_count") or 0),
            "learning_card_count": int(row.get("learning_card_count") or 0),
            "score_eligible_learning_count": int(row.get("score_eligible_learning_count") or 0),
            "latest_learning_available_at_utc": row.get("latest_learning_available_at_utc"),
            "point_in_time_retrieval_enforced": True,
            "same_episode_retrieval_allowed": False,
            "hidden_reasoning_stored": False,
            "active_cohort_tuning_allowed": False,
        }
        summary["summary_digest"] = digest(summary)
        return summary


async def sync_aidy_episode_memory(
    d1: Any,
    *,
    now_utc: datetime,
    episode_limit: int = 50,
    outcome_limit: int = 20,
) -> dict[str, Any]:
    now = _utc(now_utc, name="now_utc")
    store = D1EpisodeMemoryStore(d1)
    episodes = await store.materialize_episodes(recorded_at_utc=now, limit=episode_limit)
    resolution = await store.resolve_due_forward_outcomes(now_utc=now, limit=outcome_limit)
    materialized = await store.materialize_outcomes_and_learning(recorded_at_utc=now, limit=episode_limit)
    summary = await store.summary(as_of_utc=now)
    result = {
        "memory_sync_version": MEMORY_SYNC_VERSION,
        "observed_at_utc": now.isoformat(),
        "episodes_materialized": episodes,
        "forward_outcomes": resolution,
        "outcomes_materialized": materialized["outcomes"],
        "learning_cards_materialized": materialized["learning_cards"],
        "summary": summary,
    }
    result["sync_digest"] = digest(result)
    return result
