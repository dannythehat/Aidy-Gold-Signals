from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import aidy.episode_memory as memory
from aidy.episode_memory import (
    D1EpisodeMemoryStore,
    _resolve_no_trade_path,
    _resolve_trade_path,
)

ROOT = Path(__file__).resolve().parents[1]


class Prepared:
    def __init__(self, db: "LocalD1", sql: str, params=()) -> None:
        self.db = db
        self.sql = sql
        self.params = params

    def bind(self, *params):
        return Prepared(self.db, self.sql, params)

    async def first(self):
        row = self.db.connection.execute(self.sql, self.params).fetchone()
        return None if row is None else dict(row)

    async def all(self):
        rows = self.db.connection.execute(self.sql, self.params).fetchall()
        return {"results": [dict(row) for row in rows]}

    async def run(self):
        self.db.connection.execute(self.sql, self.params)
        self.db.connection.commit()
        return {"success": True}


class LocalD1:
    def __init__(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(
            """
            CREATE TABLE aidy_end_to_end_cycles (
              cycle_id TEXT PRIMARY KEY,
              source_state TEXT NOT NULL,
              ex_ante_json TEXT,
              ex_ante_digest TEXT,
              decision_id TEXT,
              created_at_utc TEXT NOT NULL
            );
            CREATE TABLE aidy_forward_evaluations (
              record_id TEXT PRIMARY KEY,
              ex_ante_digest TEXT,
              cohort_id TEXT,
              record_json TEXT,
              disposition TEXT,
              evaluated_at_utc TEXT
            );
            CREATE TABLE aidy_forward_outcomes (
              attachment_id TEXT PRIMARY KEY,
              attachment_json TEXT NOT NULL,
              outcome_type TEXT NOT NULL,
              attached_at_utc TEXT NOT NULL,
              record_id TEXT NOT NULL
            );
            """
        )
        self.connection.executescript(
            (ROOT / "migrations/d1/0019_aidy_episode_memory.sql").read_text(encoding="utf-8")
        )

    def prepare(self, sql: str) -> Prepared:
        return Prepared(self, sql)


def _ex_ante(*, action: str = "new_trade") -> dict[str, object]:
    decision: dict[str, object] = {
        "action": action,
        "direction": "long" if action == "new_trade" else None,
        "expected_horizon_minutes": 3 if action == "new_trade" else None,
        "thesis": "Price should continue higher while the structure remains constructive."
        if action == "new_trade"
        else None,
        "counter_argument": "A sharp reversal could invalidate the continuation premise.",
        "invalidation_condition": None,
        "shadow_thesis": "A break higher would support the rejected bullish scenario."
        if action == "no_trade"
        else None,
        "shadow_direction": "long" if action == "no_trade" else None,
        "shadow_horizon_minutes": 3 if action == "no_trade" else None,
        "shadow_evaluation_condition": None,
        "market_reference_price": 100.0,
        "stop_loss": 95.0 if action == "new_trade" else None,
        "targets": [102.0, 104.0] if action == "new_trade" else [],
    }
    return {
        "evaluation_id": "aidy_eval_fixture_0001",
        "decision_id": "aidy_dec_fixture_0001",
        "ex_ante_digest": "a" * 64,
        "evaluated_at_utc": "2026-09-10T12:00:30+00:00",
        "context_hash": "b" * 64,
        "cycle_disposition": "decision_admitted" if action == "new_trade" else "no_trade",
        "decision": decision,
        "reproducibility_bundle": {
            "evidence_grade": "exploratory",
            "effective_n": 12,
            "strategy_version": "strategy_v1",
            "config_version": "config_v1",
            "model_id": "model_v1",
            "analogue_case_ids": ["case_1"],
        },
        "data_quality_flags": {"state": "known_good"},
    }


def _bar(minute: int, *, high: float, low: float, close: float) -> dict[str, object]:
    return {
        "open_time_utc": f"2026-09-10T12:0{minute}:00+00:00",
        "open": "100.0",
        "high": str(high),
        "low": str(low),
        "close": str(close),
    }


def test_trade_outcome_resolves_only_with_unambiguous_m1_path() -> None:
    start = datetime(2026, 9, 10, 12, 1, tzinfo=UTC)
    deadline = datetime(2026, 9, 10, 12, 3, 30, tzinfo=UTC)
    bars = [
        _bar(1, high=101.0, low=99.0, close=100.5),
        _bar(2, high=102.5, low=99.5, close=102.0),
        _bar(3, high=104.5, low=101.0, close=104.0),
    ]
    outcome = _resolve_trade_path(ex_ante=_ex_ante(), bars=bars, start=start, deadline=deadline)
    assert outcome["outcome_state"] == "all_targets_hit"
    assert outcome["score_eligible"] is True
    assert outcome["hit_target_indices"] == [1, 2]
    assert outcome["realized_r"] == "0.600000"
    assert outcome["continuity"]["state"] == "complete"


def test_same_m1_bar_stop_and_target_is_ambiguous_and_never_scored() -> None:
    start = datetime(2026, 9, 10, 12, 1, tzinfo=UTC)
    deadline = datetime(2026, 9, 10, 12, 3, 30, tzinfo=UTC)
    bars = [
        _bar(1, high=102.5, low=94.5, close=100.0),
        _bar(2, high=101.0, low=99.0, close=100.0),
        _bar(3, high=101.0, low=99.0, close=100.0),
    ]
    outcome = _resolve_trade_path(ex_ante=_ex_ante(), bars=bars, start=start, deadline=deadline)
    assert outcome["outcome_state"] == "ambiguous_intrabar_order"
    assert outcome["score_eligible"] is False
    assert outcome["realized_r"] is None


def test_path_gap_before_terminal_event_fails_closed() -> None:
    start = datetime(2026, 9, 10, 12, 1, tzinfo=UTC)
    deadline = datetime(2026, 9, 10, 12, 4, 30, tzinfo=UTC)
    bars = [
        _bar(1, high=101.0, low=99.0, close=100.0),
        {
            "open_time_utc": "2026-09-10T12:03:00+00:00",
            "open": "100",
            "high": "101",
            "low": "94",
            "close": "95",
        },
        {
            "open_time_utc": "2026-09-10T12:04:00+00:00",
            "open": "95",
            "high": "96",
            "low": "94",
            "close": "95",
        },
    ]
    outcome = _resolve_trade_path(ex_ante=_ex_ante(), bars=bars, start=start, deadline=deadline)
    assert outcome["outcome_state"] == "stop_hit_after_path_gap"
    assert outcome["score_eligible"] is False


def test_no_trade_shadow_records_direction_without_pretending_it_was_a_trade() -> None:
    start = datetime(2026, 9, 10, 12, 1, tzinfo=UTC)
    deadline = datetime(2026, 9, 10, 12, 3, 30, tzinfo=UTC)
    bars = [
        _bar(1, high=101.0, low=99.0, close=100.5),
        _bar(2, high=102.0, low=100.0, close=101.5),
        _bar(3, high=103.0, low=101.0, close=102.0),
    ]
    outcome = _resolve_no_trade_path(
        ex_ante=_ex_ante(action="no_trade"), bars=bars, start=start, deadline=deadline
    )
    assert outcome["outcome_state"] == "shadow_direction_favorable"
    assert outcome["score_eligible"] is True
    assert outcome["move_points"] == "2.000000"
    assert "realized_r" not in outcome


@pytest.mark.asyncio
async def test_memory_is_append_only_and_learning_is_point_in_time_safe(monkeypatch) -> None:
    db = LocalD1()
    monkeypatch.setattr(memory, "verify_ex_ante_record", lambda value: True)
    ex_ante = _ex_ante()
    db.connection.execute(
        "INSERT INTO aidy_end_to_end_cycles VALUES (?,?,?,?,?,?)",
        (
            "cycle-1",
            "private_forward",
            json.dumps(ex_ante, sort_keys=True, separators=(",", ":")),
            ex_ante["ex_ante_digest"],
            ex_ante["decision_id"],
            ex_ante["evaluated_at_utc"],
        ),
    )
    db.connection.execute(
        "INSERT INTO aidy_forward_evaluations VALUES (?,?,?,?,?,?)",
        (
            "fwd-1",
            ex_ante["ex_ante_digest"],
            "cohort-1",
            "{}",
            "decision_admitted",
            ex_ante["evaluated_at_utc"],
        ),
    )
    db.connection.commit()

    store = D1EpisodeMemoryStore(db)
    inserted = await store.materialize_episodes(
        recorded_at_utc=datetime(2026, 9, 10, 12, 1, tzinfo=UTC)
    )
    assert inserted == 1
    assert await store.materialize_episodes(
        recorded_at_utc=datetime(2026, 9, 10, 12, 2, tzinfo=UTC)
    ) == 0

    attachment = {
        "attachment_id": "out-1",
        "attachment_digest": "c" * 64,
        "outcome_payload": {
            "outcome_state": "all_targets_hit",
            "score_eligible": True,
            "realized_r": "0.600000",
        },
    }
    attached_at = "2026-09-10T13:00:00+00:00"
    db.connection.execute(
        "INSERT INTO aidy_forward_outcomes VALUES (?,?,?,?,?)",
        (
            "out-1",
            json.dumps(attachment, sort_keys=True, separators=(",", ":")),
            "trade_outcome",
            attached_at,
            "fwd-1",
        ),
    )
    db.connection.commit()

    materialized = await store.materialize_outcomes_and_learning(
        recorded_at_utc=datetime(2026, 9, 10, 13, 1, tzinfo=UTC)
    )
    assert materialized == {"outcomes": 1, "learning_cards": 1}

    before = await store.recent_learning_cards(
        as_of_utc=datetime(2026, 9, 10, 12, 59, tzinfo=UTC)
    )
    after = await store.recent_learning_cards(
        as_of_utc=datetime(2026, 9, 10, 13, 1, tzinfo=UTC)
    )
    assert before == []
    assert len(after) == 1
    assert after[0]["outcome_class"] == "favorable"
    assert after[0]["same_episode_retrieval_allowed"] is False
    assert after[0]["hidden_reasoning_stored"] is False

    summary = await store.summary(as_of_utc=datetime(2026, 9, 10, 13, 1, tzinfo=UTC))
    assert summary["episode_count"] == 1
    assert summary["outcome_count"] == 1
    assert summary["learning_card_count"] == 1
    assert summary["score_eligible_learning_count"] == 1
    assert summary["point_in_time_retrieval_enforced"] is True


def test_phase_b_migration_forbids_future_mutation_and_same_episode_learning() -> None:
    migration = (ROOT / "migrations/d1/0019_aidy_episode_memory.sql").read_text(encoding="utf-8")
    assert "future_outcome_fields_present = 0" in migration
    assert "hidden_reasoning_stored = 0" in migration
    assert "same_episode_retrieval_allowed = 0" in migration
    assert "active_cohort_tuning_allowed" not in migration or "aidy_forward" not in migration
