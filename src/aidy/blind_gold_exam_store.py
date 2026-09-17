from __future__ import annotations

import json
from typing import Any, Mapping

from aidy.blind_gold_exam import ExamEpisode, evaluate_learning
from aidy.blind_gold_exam_context import frozen_exam_context


def _obj(raw: Any) -> dict[str, Any]:
    if isinstance(raw, Mapping):
        return dict(raw)
    if isinstance(raw, str) and raw:
        value = json.loads(raw)
        return dict(value) if isinstance(value, Mapping) else {}
    return {}


def _actual_direction(*, predicted: str, outcome: Mapping[str, Any]) -> str:
    state = str(outcome.get("outcome_state") or "")
    if state in {"all_targets_hit", "shadow_direction_favorable"}:
        return predicted
    if state in {"stop_hit", "shadow_direction_adverse"}:
        return "short" if predicted == "long" else "long" if predicted == "short" else "unknown"
    move = outcome.get("directional_move_points")
    try:
        signed = float(move)
    except (TypeError, ValueError):
        return "unknown"
    if signed > 0:
        return predicted
    if signed < 0:
        return "short" if predicted == "long" else "long" if predicted == "short" else "unknown"
    return "unknown"


def _confidence(episode: Mapping[str, Any]) -> float | None:
    decision = _obj(episode.get("decision"))
    for key in ("confidence", "probability", "direction_confidence"):
        value = decision.get(key)
        if value is None:
            continue
        try:
            result = float(value)
        except (TypeError, ValueError):
            continue
        if result > 1 and result <= 100:
            result /= 100
        if 0 <= result <= 1:
            return result
    return None


def _predicted_direction(episode: Mapping[str, Any]) -> str:
    decision = _obj(episode.get("decision"))
    value = str(decision.get("direction") or decision.get("shadow_direction") or "unknown").lower()
    return {"buy": "long", "sell": "short"}.get(value, value)


def _regime_label(context: Mapping[str, Any]) -> str | None:
    parts = [str(context[key]) for key in ("market_structure", "volatility_state", "liquidity_state", "session", "event_state") if context.get(key)]
    return "|".join(parts) if parts else None


class D1BlindGoldExamStore:
    """Read-only bridge from immutable PIT memory to the research-only exam."""

    def __init__(self, d1: Any) -> None:
        self._d1 = d1

    async def episodes(self, *, limit: int = 5000) -> list[ExamEpisode]:
        result = await self._d1.prepare(
            """
            SELECT m.memory_episode_id,m.evaluated_at_utc,m.episode_json,
                   o.outcome_json,o.attached_at_utc,
                   (SELECT COUNT(*) FROM aidy_learning_cards c
                    WHERE c.available_at_utc<=m.evaluated_at_utc
                      AND c.memory_episode_id<>m.memory_episode_id) AS available_learning_count
            FROM aidy_memory_episodes m
            JOIN aidy_memory_outcomes o ON o.memory_episode_id=m.memory_episode_id
            WHERE o.score_eligible=1
            ORDER BY m.evaluated_at_utc,m.memory_episode_id
            LIMIT ?
            """
        ).bind(max(1, min(int(limit), 20000))).all()
        rows = getattr(result, "results", None)
        if rows is None and isinstance(result, Mapping):
            rows = result.get("results")
        output: list[ExamEpisode] = []
        for raw in rows or []:
            row = dict(raw)
            episode = _obj(row.get("episode_json"))
            outcome_record = _obj(row.get("outcome_json"))
            outcome = _obj(outcome_record.get("outcome_payload"))
            predicted = _predicted_direction(episode)
            actual = _actual_direction(predicted=predicted, outcome=outcome)
            context = frozen_exam_context(episode)
            output.append(
                ExamEpisode(
                    episode_id=str(row["memory_episode_id"]),
                    evaluated_at_utc=str(row["evaluated_at_utc"]),
                    available_learning_count=int(row.get("available_learning_count") or 0),
                    predicted_direction=predicted,
                    actual_direction=actual,
                    confidence=_confidence(episode),
                    provider=None,
                    regime=_regime_label(context),
                    difficulty=int(context["difficulty"]),
                )
            )
        return output

    async def context_coverage(self, *, limit: int = 5000) -> dict[str, Any]:
        result = await self._d1.prepare(
            "SELECT episode_json FROM aidy_memory_episodes ORDER BY evaluated_at_utc,memory_episode_id LIMIT ?"
        ).bind(max(1, min(int(limit), 20000))).all()
        rows = getattr(result, "results", None)
        if rows is None and isinstance(result, Mapping):
            rows = result.get("results")
        contexts = [frozen_exam_context(_obj(dict(row).get("episode_json"))) for row in (rows or [])]
        counts = {name: sum(1 for c in contexts if c.get(name) is not None) for name in ("market_structure", "volatility_state", "liquidity_state", "session", "event_state")}
        total = len(contexts)
        return {"episode_count": total, "known_counts": counts, "fully_contextualized": sum(1 for c in contexts if c["context_dimension_count"] == 5), "context_enrichment_is_pit_only": True}

    async def report(self, *, batch_size: int = 20, limit: int = 5000) -> dict[str, Any]:
        episodes = await self.episodes(limit=limit)
        result = evaluate_learning(episodes, batch_size=batch_size)
        result.update(
            {
                "source": "immutable_aidy_episode_memory",
                "episode_count_loaded": len(episodes),
                "context_coverage": await self.context_coverage(limit=limit),
                "pit_learning_count_enforced": True,
                "same_episode_learning_excluded": True,
                "future_outcome_used_as_input": False,
                "research_only": True,
                "live_money_execution_allowed": False,
            }
        )
        return result
