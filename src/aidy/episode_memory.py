from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from uuid import uuid4

MEMORY_VERSION = "aidy_episode_memory_v1"
RETRIEVAL_VERSION = "aidy_episode_memory_retrieval_v1"


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


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


async def _all(d1: Any, sql: str, *params: object) -> list[dict[str, Any]]:
    result = await d1.prepare(sql).bind(*params).all()
    return _results(result)


async def _first(d1: Any, sql: str, *params: object) -> dict[str, Any] | None:
    return _row(await d1.prepare(sql).bind(*params).first())


def _limit(value: int, *, maximum: int = 100) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("limit must be an integer.")
    return max(1, min(value, maximum))


def _decode_json(value: object, *, fallback: object) -> object:
    if value is None:
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return fallback


def _episode_summary(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "memory_episode_id": row.get("memory_episode_id"),
        "independent_episode_id": row.get("independent_episode_id"),
        "evaluated_at_utc": row.get("evaluated_at_utc"),
        "available_at_utc": row.get("available_at_utc"),
        "disposition": row.get("disposition"),
        "data_quality_state": row.get("data_quality_state"),
        "data_quality_reason_code": row.get("data_quality_reason_code"),
        "decision_id": row.get("decision_id"),
        "decision_action": row.get("decision_action"),
        "direction": row.get("direction"),
        "setup_codes": _decode_json(row.get("setup_codes_json"), fallback=[]),
        "strategy_version": row.get("strategy_version"),
        "model_id": row.get("model_id"),
        "evidence_grade": row.get("evidence_grade"),
        "retrieval_effective_n": int(row.get("retrieval_effective_n") or 0),
        "authoritative_decision_input": False,
    }


def _lesson_summary(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "lesson_id": row.get("lesson_id"),
        "memory_episode_id": row.get("memory_episode_id"),
        "independent_episode_id": row.get("independent_episode_id"),
        "available_at_utc": row.get("available_at_utc"),
        "outcome_class": row.get("outcome_class"),
        "realized_r": row.get("realized_r"),
        "thesis_status": row.get("thesis_status"),
        "decision_action": row.get("decision_action"),
        "direction": row.get("direction"),
        "setup_codes": _decode_json(row.get("setup_codes_json"), fallback=[]),
        "strategy_version": row.get("strategy_version"),
        "model_id": row.get("model_id"),
        "evidence_grade": row.get("evidence_grade"),
        "research_only": True,
        "authoritative_decision_input": False,
    }


async def memory_snapshot(
    d1: Any,
    *,
    as_of_utc: datetime | str,
    limit: int = 25,
) -> dict[str, Any]:
    """Return only memory that existed at the requested point in time."""

    as_of = _utc(as_of_utc, name="as_of_utc").isoformat()
    bounded = _limit(limit)

    totals = await _first(
        d1,
        """
        SELECT
          (SELECT COUNT(*) FROM aidy_memory_episodes WHERE available_at_utc<=?) AS episode_count,
          (SELECT COUNT(DISTINCT independent_episode_id) FROM aidy_memory_episodes WHERE available_at_utc<=?) AS independent_episode_count,
          (SELECT COUNT(*) FROM aidy_memory_outcomes WHERE available_at_utc<=?) AS outcome_count,
          (SELECT COUNT(*) FROM aidy_memory_lessons WHERE available_at_utc<=?) AS lesson_count,
          (SELECT COUNT(*) FROM aidy_memory_retrieval_events WHERE queried_at_utc<=?) AS retrieval_event_count
        """,
        as_of,
        as_of,
        as_of,
        as_of,
        as_of,
    ) or {}

    dispositions = await _all(
        d1,
        """
        SELECT disposition,COUNT(*) AS count
        FROM aidy_memory_episodes
        WHERE available_at_utc<=?
        GROUP BY disposition
        ORDER BY disposition
        """,
        as_of,
    )
    quality = await _all(
        d1,
        """
        SELECT data_quality_state,COUNT(*) AS count
        FROM aidy_memory_episodes
        WHERE available_at_utc<=?
        GROUP BY data_quality_state
        ORDER BY data_quality_state
        """,
        as_of,
    )
    outcomes = await _all(
        d1,
        """
        SELECT outcome_class,COUNT(*) AS count
        FROM aidy_memory_lessons
        WHERE available_at_utc<=?
        GROUP BY outcome_class
        ORDER BY outcome_class
        """,
        as_of,
    )
    episodes = await _all(
        d1,
        """
        SELECT memory_episode_id,independent_episode_id,evaluated_at_utc,available_at_utc,
               disposition,data_quality_state,data_quality_reason_code,decision_id,
               decision_action,direction,setup_codes_json,strategy_version,model_id,
               evidence_grade,retrieval_effective_n
        FROM aidy_memory_episodes
        WHERE available_at_utc<=?
        ORDER BY evaluated_at_utc DESC,memory_episode_id DESC
        LIMIT ?
        """,
        as_of,
        bounded,
    )
    lessons = await _all(
        d1,
        """
        SELECT lesson_id,memory_episode_id,independent_episode_id,available_at_utc,
               outcome_class,realized_r,thesis_status,decision_action,direction,
               setup_codes_json,strategy_version,model_id,evidence_grade
        FROM aidy_memory_lessons
        WHERE available_at_utc<=?
        ORDER BY available_at_utc DESC,lesson_id DESC
        LIMIT ?
        """,
        as_of,
        bounded,
    )

    result: dict[str, Any] = {
        "memory_version": MEMORY_VERSION,
        "as_of_utc": as_of,
        "episode_count": int(totals.get("episode_count") or 0),
        "independent_episode_count": int(totals.get("independent_episode_count") or 0),
        "outcome_count": int(totals.get("outcome_count") or 0),
        "lesson_count": int(totals.get("lesson_count") or 0),
        "retrieval_event_count": int(totals.get("retrieval_event_count") or 0),
        "dispositions": {str(row["disposition"]): int(row["count"]) for row in dispositions},
        "data_quality": {
            str(row["data_quality_state"]): int(row["count"]) for row in quality
        },
        "outcomes": {str(row["outcome_class"]): int(row["count"]) for row in outcomes},
        "recent_episodes": [_episode_summary(row) for row in episodes],
        "recent_lessons": [_lesson_summary(row) for row in lessons],
        "pit_cutoff_enforced": True,
        "research_only": True,
        "authoritative_decision_input": False,
        "active_strategy_tuning_allowed": False,
    }
    result["snapshot_digest"] = digest(result)
    return result


async def retrieve_lessons(
    d1: Any,
    *,
    as_of_utc: datetime | str,
    direction: str | None = None,
    setup_code: str | None = None,
    limit: int = 12,
    queried_at_utc: datetime | str | None = None,
    record_audit: bool = True,
) -> dict[str, Any]:
    """Retrieve research lessons without allowing future memory to leak backwards."""

    as_of = _utc(as_of_utc, name="as_of_utc")
    queried_at = _utc(queried_at_utc or datetime.now(UTC), name="queried_at_utc")
    if as_of > queried_at:
        raise ValueError("as_of_utc cannot be later than queried_at_utc.")
    bounded = _limit(limit)
    normalized_direction = None if direction is None else str(direction).strip().lower() or None
    normalized_setup = None if setup_code is None else str(setup_code).strip() or None

    clauses = ["l.available_at_utc<=?"]
    params: list[object] = [as_of.isoformat()]
    if normalized_direction is not None:
        clauses.append("lower(l.direction)=?")
        params.append(normalized_direction)
    if normalized_setup is not None:
        clauses.append(
            "EXISTS (SELECT 1 FROM json_each(COALESCE(l.setup_codes_json,'[]')) WHERE value=?)"
        )
        params.append(normalized_setup)
    params.append(bounded)

    rows = await _all(
        d1,
        f"""
        SELECT l.lesson_id,l.memory_episode_id,l.independent_episode_id,l.available_at_utc,
               l.outcome_class,l.realized_r,l.thesis_status,l.decision_action,l.direction,
               l.setup_codes_json,l.strategy_version,l.model_id,l.evidence_grade
        FROM aidy_memory_lessons AS l
        WHERE {' AND '.join(clauses)}
        ORDER BY l.available_at_utc DESC,l.lesson_id DESC
        LIMIT ?
        """,
        *params,
    )
    lessons = [_lesson_summary(row) for row in rows]
    lesson_ids = [str(item["lesson_id"]) for item in lessons]
    query_body = {
        "retrieval_version": RETRIEVAL_VERSION,
        "as_of_utc": as_of.isoformat(),
        "direction": normalized_direction,
        "setup_code": normalized_setup,
        "limit": bounded,
        "selected_lesson_ids": lesson_ids,
    }
    query_digest = digest(query_body)
    retrieval_event_id: str | None = None

    if record_audit:
        retrieval_event_id = f"aidy_mem_ret_{uuid4()}"
        await d1.prepare(
            """
            INSERT INTO aidy_memory_retrieval_events (
              retrieval_event_id,retrieval_version,queried_at_utc,as_of_utc,
              direction_filter,setup_code_filter,requested_limit,result_count,
              selected_lesson_ids_json,query_digest
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """
        ).bind(
            retrieval_event_id,
            RETRIEVAL_VERSION,
            queried_at.isoformat(),
            as_of.isoformat(),
            normalized_direction,
            normalized_setup,
            bounded,
            len(lessons),
            canonical_json(lesson_ids),
            query_digest,
        ).run()

    return {
        "retrieval_version": RETRIEVAL_VERSION,
        "retrieval_event_id": retrieval_event_id,
        "queried_at_utc": queried_at.isoformat(),
        "as_of_utc": as_of.isoformat(),
        "direction": normalized_direction,
        "setup_code": normalized_setup,
        "requested_limit": bounded,
        "result_count": len(lessons),
        "lessons": lessons,
        "query_digest": query_digest,
        "pit_cutoff_enforced": True,
        "research_only": True,
        "authoritative_decision_input": False,
        "active_strategy_tuning_allowed": False,
    }
