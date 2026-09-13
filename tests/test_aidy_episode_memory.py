from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from aidy.episode_memory import memory_snapshot, retrieve_lessons

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations" / "d1" / "0018_aidy_episode_memory.sql"


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
    def __init__(self, *, phase_b: bool = True) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        migrations = sorted((ROOT / "migrations" / "d1").glob("*.sql"))
        for migration in migrations:
            if migration.name == "0018_aidy_episode_memory.sql" and not phase_b:
                continue
            self.connection.executescript(migration.read_text(encoding="utf-8"))

    def prepare(self, sql: str) -> Prepared:
        return Prepared(self, sql)

    def apply_phase_b(self) -> None:
        self.connection.executescript(MIGRATION.read_text(encoding="utf-8"))


def _seed_forward_evidence(db: LocalD1) -> tuple[str, str, datetime, datetime]:
    evaluated = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)
    recorded = evaluated + timedelta(seconds=5)
    attached = evaluated + timedelta(minutes=20)
    context_hash = "c" * 64
    ex_ante_digest = "e" * 64
    record_id = "aidy_fwd_eval_memory_test_0001"
    attachment_id = "aidy_fwd_out_memory_test_0001"

    db.connection.execute(
        """
        INSERT INTO aidy_forward_cohorts(
          cohort_id,cohort_version,manifest_version,manifest_json,manifest_digest,
          accepted_code_head,earliest_start_utc,prepared_at_utc,activated_at_utc,state
        ) VALUES (?,?,?,?,?,?,?,?,?,?)
        """,
        (
            "cohort-memory-test",
            "test-cohort-v1",
            "test-manifest-v1",
            "{}",
            "m" * 64,
            "a" * 40,
            "2026-09-10T00:00:00+00:00",
            "2026-09-10T00:00:00+00:00",
            "2026-09-10T00:00:00+00:00",
            "active",
        ),
    )

    ex_ante = {
        "decision": {
            "action": "new_trade",
            "direction": "long",
            "setup_codes": ["breakout_retest", "london"],
        },
        "reproducibility_bundle": {
            "strategy_version": "strategy-memory-v1",
            "model_id": "model-memory-v1",
            "evidence_grade": "B",
        },
    }
    db.connection.execute(
        """
        INSERT INTO aidy_end_to_end_cycles(
          cycle_id,runtime_version,instruction_type,source_state,subject_id,context_hash,
          created_at_utc,updated_at_utc,cycle_state,ex_ante_json,ex_ante_digest,decision_id
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            "aidy-e2e-memory-test",
            "runtime-test-v1",
            "market_evaluation",
            "private_forward",
            "market",
            context_hash,
            recorded.isoformat(),
            recorded.isoformat(),
            "decision_admitted",
            json.dumps(ex_ante, sort_keys=True),
            ex_ante_digest,
            "decision-memory-test",
        ),
    )

    record_json = {
        "record_id": record_id,
        "episode_id": "independent-episode-memory-test",
        "evaluated_at_utc": evaluated.isoformat(),
        "disposition": "decision_admitted",
        "outcome_fields_present": False,
    }
    db.connection.execute(
        """
        INSERT INTO aidy_forward_evaluations(
          record_id,record_version,record_json,record_digest,cohort_id,cycle_id,
          instruction_type,source_state,evaluated_at_utc,context_hash,disposition,
          data_quality_state,data_quality_reason_code,episode_id,decision_id,
          ex_ante_digest,self_consistency_digest,disagreement_digest,retrieval_effective_n,
          gc_shadow_digest,gc_feed_health_digest,macro_surprise_digest,selective_shadow_digest,
          formal_forward_eligible,recorded_at_utc
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            record_id,
            "test-forward-record-v1",
            json.dumps(record_json, sort_keys=True),
            "r" * 64,
            "cohort-memory-test",
            "formal-market-memory-test",
            "market_evaluation",
            "private_forward",
            evaluated.isoformat(),
            context_hash,
            "decision_admitted",
            "known_good",
            None,
            "independent-episode-memory-test",
            "decision-memory-test",
            ex_ante_digest,
            "s" * 64,
            "d" * 64,
            27,
            "g" * 64,
            "h" * 64,
            "u" * 64,
            "v" * 64,
            1,
            recorded.isoformat(),
        ),
    )
    db.connection.commit()
    return record_id, attachment_id, evaluated, attached


def _attach_positive_outcome(db: LocalD1, record_id: str, attachment_id: str, attached: datetime) -> None:
    payload = {
        "attachment_id": attachment_id,
        "record_id": record_id,
        "outcome_type": "trade_outcome",
        "outcome_payload": {
            "economic_outcome": {"realized_r": "1.250000"},
            "thesis_outcome": {"status": "not_invalidated_observed"},
        },
    }
    db.connection.execute(
        """
        INSERT INTO aidy_forward_outcomes(
          attachment_id,attachment_version,attachment_json,attachment_digest,
          cohort_id,record_id,outcome_type,attached_at_utc,recorded_at_utc
        ) VALUES (?,?,?,?,?,?,?,?,?)
        """,
        (
            attachment_id,
            "test-outcome-v1",
            json.dumps(payload, sort_keys=True),
            "o" * 64,
            "cohort-memory-test",
            record_id,
            "trade_outcome",
            attached.isoformat(),
            (attached + timedelta(seconds=3)).isoformat(),
        ),
    )
    db.connection.commit()


def test_phase_b_backfills_existing_forward_episode_and_enrichment() -> None:
    db = LocalD1(phase_b=False)
    record_id, _, _, _ = _seed_forward_evidence(db)
    db.apply_phase_b()

    row = db.connection.execute(
        "SELECT * FROM aidy_memory_episodes WHERE forward_record_id=?", (record_id,)
    ).fetchone()
    assert row is not None
    row = dict(row)
    assert row["memory_episode_id"] == record_id
    assert row["independent_episode_id"] == "independent-episode-memory-test"
    assert row["decision_action"] == "new_trade"
    assert row["direction"] == "long"
    assert json.loads(row["setup_codes_json"]) == ["breakout_retest", "london"]
    assert row["strategy_version"] == "strategy-memory-v1"
    assert row["model_id"] == "model-memory-v1"
    assert row["evidence_grade"] == "B"
    assert row["authoritative_decision_input"] == 0


def test_phase_b_triggers_future_episode_outcome_and_deterministic_lesson() -> None:
    db = LocalD1()
    record_id, attachment_id, _, attached = _seed_forward_evidence(db)
    episode = db.connection.execute(
        "SELECT * FROM aidy_memory_episodes WHERE forward_record_id=?", (record_id,)
    ).fetchone()
    assert episode is not None

    _attach_positive_outcome(db, record_id, attachment_id, attached)
    outcome = db.connection.execute(
        "SELECT * FROM aidy_memory_outcomes WHERE forward_attachment_id=?", (attachment_id,)
    ).fetchone()
    lesson = db.connection.execute(
        "SELECT * FROM aidy_memory_lessons WHERE memory_outcome_id=?", (attachment_id,)
    ).fetchone()
    assert outcome is not None
    assert lesson is not None
    lesson = dict(lesson)
    assert lesson["outcome_class"] == "positive"
    assert lesson["realized_r"] == pytest.approx(1.25)
    assert lesson["thesis_status"] == "not_invalidated_observed"
    assert lesson["direction"] == "long"
    assert lesson["lesson_digest"] == "o" * 64
    assert lesson["research_only"] == 1
    assert lesson["active_strategy_tuning_allowed"] == 0
    assert lesson["authoritative_decision_input"] == 0


def test_phase_b_memory_is_hard_append_only() -> None:
    db = LocalD1()
    record_id, attachment_id, _, attached = _seed_forward_evidence(db)
    _attach_positive_outcome(db, record_id, attachment_id, attached)

    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        db.connection.execute(
            "UPDATE aidy_memory_episodes SET disposition='no_trade' WHERE memory_episode_id=?",
            (record_id,),
        )
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        db.connection.execute(
            "DELETE FROM aidy_memory_lessons WHERE memory_outcome_id=?", (attachment_id,)
        )


@pytest.mark.asyncio
async def test_phase_b_point_in_time_memory_never_retrieves_future_lesson() -> None:
    db = LocalD1()
    record_id, attachment_id, evaluated, attached = _seed_forward_evidence(db)
    _attach_positive_outcome(db, record_id, attachment_id, attached)
    lesson_available = attached + timedelta(seconds=3)

    before = await memory_snapshot(db, as_of_utc=evaluated + timedelta(minutes=10), limit=10)
    assert before["episode_count"] == 1
    assert before["lesson_count"] == 0

    retrieval_before = await retrieve_lessons(
        db,
        as_of_utc=evaluated + timedelta(minutes=10),
        queried_at_utc=lesson_available + timedelta(minutes=1),
        direction="long",
        setup_code="breakout_retest",
        record_audit=False,
    )
    assert retrieval_before["result_count"] == 0

    after = await retrieve_lessons(
        db,
        as_of_utc=lesson_available,
        queried_at_utc=lesson_available + timedelta(minutes=1),
        direction="long",
        setup_code="breakout_retest",
        record_audit=True,
    )
    assert after["result_count"] == 1
    assert after["lessons"][0]["outcome_class"] == "positive"
    assert after["authoritative_decision_input"] is False

    audit = db.connection.execute(
        "SELECT * FROM aidy_memory_retrieval_events WHERE retrieval_event_id=?",
        (after["retrieval_event_id"],),
    ).fetchone()
    assert audit is not None
    audit = dict(audit)
    assert audit["result_count"] == 1
    assert audit["authoritative_decision_input"] == 0
    assert json.loads(audit["selected_lesson_ids_json"]) == [f"lesson:{attachment_id}"]


def test_phase_b_contract_stays_research_only_and_hub_route_exists() -> None:
    migration = MIGRATION.read_text(encoding="utf-8")
    entry = (ROOT / "src" / "provider_entry.py").read_text(encoding="utf-8")
    assert "AFTER INSERT ON aidy_forward_evaluations" in migration
    assert "AFTER INSERT ON aidy_forward_outcomes" in migration
    assert "aidy_memory_retrieval_events" in migration
    assert "authoritative_decision_input INTEGER NOT NULL DEFAULT 0" in migration
    assert "active_strategy_tuning_allowed INTEGER NOT NULL DEFAULT 0" in migration
    assert "append-only" in migration
    assert 'path == "/provider/memory"' in entry
    assert "provider_memory_response" in entry
