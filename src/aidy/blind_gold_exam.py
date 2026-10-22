from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from statistics import mean
from typing import Iterable, Mapping, Any

EXAM_VERSION = "aidy_blind_gold_exam_v1"
MIN_BATCH_SIZE = 20
MIN_LEARNING_BATCHES = 3


@dataclass(frozen=True)
class ExamEpisode:
    episode_id: str
    evaluated_at_utc: str
    available_learning_count: int
    predicted_direction: str
    actual_direction: str
    confidence: float | None = None
    provider: str | None = None
    regime: str | None = None
    difficulty: int = 1

    @property
    def directional(self) -> bool:
        return self.predicted_direction in {"long", "short"} and self.actual_direction in {"long", "short"}

    @property
    def correct(self) -> bool:
        return self.directional and self.predicted_direction == self.actual_direction


def _validate(ep: ExamEpisode) -> None:
    if ep.difficulty not in {1, 2, 3, 4, 5}:
        raise ValueError("difficulty must be 1..5")
    if ep.confidence is not None and not 0 <= ep.confidence <= 1:
        raise ValueError("confidence must be between 0 and 1")
    if ep.available_learning_count < 0:
        raise ValueError("available_learning_count cannot be negative")


def _brier(ep: ExamEpisode) -> float | None:
    if not ep.directional or ep.confidence is None:
        return None
    y = 1.0 if ep.correct else 0.0
    return (ep.confidence - y) ** 2


def score_batch(episodes: Iterable[ExamEpisode]) -> dict[str, Any]:
    rows = list(episodes)
    for row in rows:
        _validate(row)
    directional = [row for row in rows if row.directional]
    briers = [score for row in directional if (score := _brier(row)) is not None]
    by_difficulty: dict[str, dict[str, float | int | None]] = {}
    for level in range(1, 6):
        subset = [row for row in directional if row.difficulty == level]
        by_difficulty[str(level)] = {
            "n": len(subset),
            "accuracy": None if not subset else sum(row.correct for row in subset) / len(subset),
        }
    return {
        "n": len(rows),
        "directional_n": len(directional),
        "direction_accuracy": None if not directional else sum(row.correct for row in directional) / len(directional),
        "brier_n": len(briers),
        "brier_score": None if not briers else mean(briers),
        "mean_available_learning_count": None if not rows else mean(row.available_learning_count for row in rows),
        "difficulty": by_difficulty,
    }


def chronological_batches(episodes: Iterable[ExamEpisode], *, batch_size: int = MIN_BATCH_SIZE) -> list[list[ExamEpisode]]:
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    rows = sorted(episodes, key=lambda row: (row.evaluated_at_utc, row.episode_id))
    return [rows[index:index + batch_size] for index in range(0, len(rows), batch_size) if len(rows[index:index + batch_size]) == batch_size]


def _two_proportion_z(first_correct: int, first_n: int, last_correct: int, last_n: int) -> float | None:
    if first_n == 0 or last_n == 0:
        return None
    pooled = (first_correct + last_correct) / (first_n + last_n)
    variance = pooled * (1 - pooled) * ((1 / first_n) + (1 / last_n))
    if variance <= 0:
        return None
    return ((last_correct / last_n) - (first_correct / first_n)) / sqrt(variance)


def evaluate_learning(episodes: Iterable[ExamEpisode], *, batch_size: int = MIN_BATCH_SIZE) -> dict[str, Any]:
    batches = chronological_batches(episodes, batch_size=batch_size)
    scored = [score_batch(batch) for batch in batches]
    result: dict[str, Any] = {
        "exam_version": EXAM_VERSION,
        "batch_size": batch_size,
        "complete_batch_count": len(batches),
        "batches": scored,
        "state": "insufficient_evidence",
        "learning_observed": False,
        "research_only": True,
        "live_money_execution_allowed": False,
    }
    if len(batches) < MIN_LEARNING_BATCHES:
        return result

    first_rows = [row for row in batches[0] if row.directional]
    last_rows = [row for row in batches[-1] if row.directional]
    if len(first_rows) < batch_size // 2 or len(last_rows) < batch_size // 2:
        return result

    first_acc = sum(row.correct for row in first_rows) / len(first_rows)
    last_acc = sum(row.correct for row in last_rows) / len(last_rows)
    delta = last_acc - first_acc
    z = _two_proportion_z(sum(row.correct for row in first_rows), len(first_rows), sum(row.correct for row in last_rows), len(last_rows))
    memory_grew = mean(row.available_learning_count for row in last_rows) > mean(row.available_learning_count for row in first_rows)
    result.update({"first_accuracy": first_acc, "latest_accuracy": last_acc, "accuracy_delta": delta, "improvement_z": z, "memory_grew": memory_grew})

    if not memory_grew:
        result["state"] = "memory_accumulating"
    elif delta <= -0.05:
        result["state"] = "regression_candidate"
    elif delta > 0:
        result["state"] = "learning_candidate"
    else:
        result["state"] = "memory_accumulating"

    # Conservative v1 gate: >=5 percentage-point unseen improvement and approx
    # two-sided 5% normal threshold. This is evidence of improvement, not authority.
    if memory_grew and delta >= 0.05 and z is not None and z >= 1.96:
        result["state"] = "learning_observed"
        result["learning_observed"] = True
    return result


def episode_from_mapping(row: Mapping[str, Any]) -> ExamEpisode:
    return ExamEpisode(
        episode_id=str(row["episode_id"]),
        evaluated_at_utc=str(row["evaluated_at_utc"]),
        available_learning_count=int(row.get("available_learning_count") or 0),
        predicted_direction=str(row.get("predicted_direction") or "unknown").lower(),
        actual_direction=str(row.get("actual_direction") or "unknown").lower(),
        confidence=None if row.get("confidence") is None else float(row["confidence"]),
        provider=None if row.get("provider") is None else str(row["provider"]),
        regime=None if row.get("regime") is None else str(row["regime"]),
        difficulty=int(row.get("difficulty") or 1),
    )
