"""The scorecard must publish the baselines every accuracy figure is read against.

On the first live sample, always answering "bearish" scored 57.9 per cent while
the legacy 15-minute view scored 36.11 per cent and M5 31.82 per cent. Both were
below a trivial constant guess and below 3-class chance, but nothing in the
system computed a baseline, so the figures looked merely weak rather than
worse-than-trivial.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from aidy.gold_expert_shadow import D1GoldExpertShadowStore

AS_OF = datetime(2026, 9, 22, 4, 0, tzinfo=UTC)


class _StubStatement:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def bind(self, *_args: object) -> _StubStatement:
        return self

    async def all(self) -> dict[str, object]:
        return {"results": self._rows}


class _StubD1:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def prepare(self, _sql: str) -> _StubStatement:
        return _StubStatement(self._rows)


def _store(labels: list[str]) -> D1GoldExpertShadowStore:
    return D1GoldExpertShadowStore(
        _StubD1([{"realised_direction": label} for label in labels])
    )


@pytest.mark.asyncio
async def test_majority_class_baseline_matches_the_live_sample() -> None:
    """22 bearish / 11 bullish / 5 neutral -> always-bearish scores 22/38."""
    labels = ["bearish"] * 22 + ["bullish"] * 11 + ["neutral"] * 5
    result = await _store(labels)._outcome_baselines(as_of=AS_OF)

    assert result["state"] == "known"
    assert result["sample_n"] == 38
    assert result["majority_class"] == "bearish"
    assert result["majority_class_accuracy"] == "0.578947"
    assert result["uniform_random_accuracy"] == "0.333333"
    assert result["class_counts"] == {"bearish": 22, "bullish": 11, "neutral": 5}
    assert result["future_values_used"] is False


@pytest.mark.asyncio
async def test_persistence_baseline_counts_repeats() -> None:
    labels = ["bullish", "bullish", "bearish", "bearish", "bearish"]
    result = await _store(labels)._outcome_baselines(as_of=AS_OF)
    # repeats at index 1, 3 and 4 -> 3 of 4 transitions
    assert result["persistence_sample_n"] == 4
    assert result["persistence_accuracy"] == "0.750000"


@pytest.mark.asyncio
async def test_no_outcomes_yet_is_explicit_not_fabricated() -> None:
    result = await _store([])._outcome_baselines(as_of=AS_OF)
    assert result["state"] == "no_resolved_outcomes_yet"
    assert result["sample_n"] == 0
    assert result["majority_class"] is None
    assert result["majority_class_accuracy"] is None
