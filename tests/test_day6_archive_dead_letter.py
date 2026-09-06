from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from aidy.cloudflare_storage import R2ArchiveStore
from aidy.cross_market_storage import D1CrossMarketOperationalEvidenceStore
from aidy.storage_contracts import AidyMarketRepository


class Prepared:
    def __init__(self, db: LocalD1, sql: str, params=()) -> None:
        self.db = db
        self.sql = sql
        self.params = params

    def bind(self, *params):
        return Prepared(self.db, self.sql, params)

    async def first(self):
        cursor = self.db.connection.execute(self.sql, self.params)
        row = cursor.fetchone()
        return None if row is None else dict(row)

    async def all(self):
        cursor = self.db.connection.execute(self.sql, self.params)
        return {"results": [dict(row) for row in cursor.fetchall()]}

    async def run(self):
        self.db.connection.execute(self.sql, self.params)
        self.db.connection.commit()
        return {"success": True}


class LocalD1:
    def __init__(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        for migration in (
            "migrations/d1/0001_aidy_ops.sql",
            "migrations/d1/0002_cross_market_evidence.sql",
            "migrations/d1/0012_live_gold_free_tier_read_budget.sql",
            "migrations/d1/0014_archive_delivery_state.sql",
        ):
            self.connection.executescript(Path(migration).read_text(encoding="utf-8"))

    def prepare(self, sql: str) -> Prepared:
        return Prepared(self, sql)

    async def batch(self, statements):
        results = []
        with self.connection:
            for statement in statements:
                cursor = self.connection.execute(statement.sql, statement.params)
                rows = cursor.fetchall() if cursor.description else []
                results.append({"success": True, "results": [dict(row) for row in rows]})
        return results


class SelectiveR2:
    def __init__(self) -> None:
        self.objects: dict[str, str] = {}
        self.fail_keys: set[str] = set()
        self.attempted_keys: list[str] = []

    async def head(self, key: str):
        return {"key": key} if key in self.objects else None

    async def put(self, key: str, value: str):
        self.attempted_keys.append(key)
        if key in self.fail_keys:
            raise RuntimeError("synthetic poison item")
        self.objects[key] = value
        return {"key": key}


def row(db: LocalD1, table: str, outbox_id: str):
    return db.connection.execute(
        f"SELECT * FROM {table} WHERE id=?", (outbox_id,)
    ).fetchone()


def make_snapshot(index: int, captured_at: datetime) -> dict[str, object]:
    return {
        "captured_at": captured_at,
        "symbol": "XAUUSD",
        "capture_status": "partial",
        "bid": None,
        "ask": None,
        "mid": None,
        "spread": None,
        "quote_time": None,
        "quote_age_seconds": None,
        "session_code": "off_hours",
        "data_availability_json": '{"market_data_source":"twelve_data"}',
        "event_observation_ids_json": "[]",
        "latest_m1_id": None,
        "latest_m5_id": None,
        "latest_m15_id": None,
        "latest_h1_id": None,
        "latest_h4_id": None,
        "latest_d1_id": None,
        "snapshot_digest": f"{index:064x}",
    }


@pytest.fixture
def store(monkeypatch):
    monkeypatch.chdir(Path(__file__).parents[1])
    db = LocalD1()
    operational = D1CrossMarketOperationalEvidenceStore(db)
    bucket = SelectiveR2()
    repository = AidyMarketRepository(operational, R2ArchiveStore(bucket))
    return db, operational, bucket, repository


def force_due(db: LocalD1, table: str, outbox_id: str) -> None:
    db.connection.execute(
        f"UPDATE {table} SET next_attempt_at=? WHERE id=?",
        ((datetime.now(UTC) - timedelta(seconds=1)).isoformat(), outbox_id),
    )
    db.connection.commit()


def test_migration_maps_legacy_status_without_rewriting_it() -> None:
    db = sqlite3.connect(":memory:")
    db.executescript(Path("migrations/d1/0001_aidy_ops.sql").read_text(encoding="utf-8"))
    db.executescript(
        Path("migrations/d1/0002_cross_market_evidence.sql").read_text(encoding="utf-8")
    )
    db.execute(
        "INSERT INTO archive_outbox(id,record_type,evidence_id,archive_key,payload_digest,status,created_at) "
        "VALUES (?,?,?,?,?,'pending',?)",
        ("p", "snapshot", "e", "pending.json", "a" * 64, datetime.now(UTC).isoformat()),
    )
    db.execute(
        "INSERT INTO archive_outbox(id,record_type,evidence_id,archive_key,payload_digest,status,created_at,archived_at) "
        "VALUES (?,?,?,?,?,'archived',?,?)",
        (
            "a",
            "snapshot",
            "e2",
            "archived.json",
            "b" * 64,
            datetime.now(UTC).isoformat(),
            datetime.now(UTC).isoformat(),
        ),
    )
    db.executescript(Path("migrations/d1/0014_archive_delivery_state.sql").read_text(encoding="utf-8"))
    values = db.execute(
        "SELECT id,status,delivery_state FROM archive_outbox ORDER BY id"
    ).fetchall()
    assert values == [("a", "archived", "archived"), ("p", "pending", "pending")]


@pytest.mark.asyncio
async def test_first_failure_enters_backoff_and_is_not_immediately_retried(store) -> None:
    db, operational, bucket, repository = store
    commit = await operational.commit_snapshot(make_snapshot(1, datetime.now(UTC)))
    assert commit.outbox_id is not None and commit.archive_key is not None
    bucket.fail_keys.add(commit.archive_key)

    first = await repository.flush_archive_outbox(limit=10)
    state = row(db, "archive_outbox", str(commit.outbox_id))
    assert first.attempted == 1 and first.failed == 1 and first.dead_lettered == 0
    assert state["attempts"] == 1
    assert state["delivery_state"] == "backoff"
    assert state["next_attempt_at"] is not None
    assert state["first_failed_at"] is not None

    second = await repository.flush_archive_outbox(limit=10)
    assert second.attempted == 0
    assert bucket.attempted_keys.count(commit.archive_key) == 1


@pytest.mark.asyncio
async def test_three_due_failures_dead_letter_and_stop_retrying(store) -> None:
    db, operational, bucket, repository = store
    commit = await operational.commit_snapshot(make_snapshot(2, datetime.now(UTC)))
    assert commit.outbox_id is not None and commit.archive_key is not None
    outbox_id = str(commit.outbox_id)
    bucket.fail_keys.add(commit.archive_key)

    first = await repository.flush_archive_outbox(limit=10)
    assert first.dead_lettered == 0
    force_due(db, "archive_outbox", outbox_id)
    second = await repository.flush_archive_outbox(limit=10)
    assert second.dead_lettered == 0
    state2 = row(db, "archive_outbox", outbox_id)
    assert state2["attempts"] == 2 and state2["delivery_state"] == "backoff"

    force_due(db, "archive_outbox", outbox_id)
    third = await repository.flush_archive_outbox(limit=10)
    state3 = row(db, "archive_outbox", outbox_id)
    assert third.attempted == 1 and third.failed == 1 and third.dead_lettered == 1
    assert state3["attempts"] == 3
    assert state3["delivery_state"] == "dead_letter"
    assert state3["next_attempt_at"] is None
    assert state3["dead_lettered_at"] is not None

    fourth = await repository.flush_archive_outbox(limit=10)
    assert fourth.attempted == 0
    assert bucket.attempted_keys.count(commit.archive_key) == 3


@pytest.mark.asyncio
async def test_healthy_item_archives_after_poison_failure_in_same_flush(store) -> None:
    db, operational, bucket, repository = store
    now = datetime.now(UTC)
    poison = await operational.commit_snapshot(make_snapshot(3, now))
    healthy = await operational.commit_snapshot(make_snapshot(4, now + timedelta(microseconds=1)))
    assert poison.archive_key and healthy.archive_key and healthy.outbox_id
    bucket.fail_keys.add(poison.archive_key)

    result = await repository.flush_archive_outbox(limit=10)
    healthy_state = row(db, "archive_outbox", str(healthy.outbox_id))
    assert result.attempted == 2
    assert result.failed == 1
    assert result.archived == 1
    assert healthy.archive_key in bucket.objects
    assert healthy_state["status"] == "archived"
    assert healthy_state["delivery_state"] == "archived"


@pytest.mark.asyncio
async def test_successful_retry_clears_error_and_archives(store) -> None:
    db, operational, bucket, repository = store
    commit = await operational.commit_snapshot(make_snapshot(5, datetime.now(UTC)))
    assert commit.archive_key and commit.outbox_id
    outbox_id = str(commit.outbox_id)
    bucket.fail_keys.add(commit.archive_key)
    await repository.flush_archive_outbox(limit=10)
    force_due(db, "archive_outbox", outbox_id)
    bucket.fail_keys.clear()

    result = await repository.flush_archive_outbox(limit=10)
    state = row(db, "archive_outbox", outbox_id)
    assert result.archived == 1 and result.failed == 0
    assert state["attempts"] == 1
    assert state["status"] == "archived"
    assert state["delivery_state"] == "archived"
    assert state["last_error"] is None
    assert state["next_attempt_at"] is None


@pytest.mark.asyncio
async def test_cross_market_outbox_uses_same_backoff_lifecycle(store) -> None:
    db, operational, bucket, repository = store
    observed = datetime.now(UTC)
    commit = await operational.commit_cross_market_observation(
        source="test_source",
        series_id="TEST",
        observation_date=date(2026, 9, 6),
        value="1.0",
        unit="index",
        source_url="https://example.invalid/test",
        source_document_digest="c" * 64,
        first_observed_at=observed,
        payload_digest="d" * 64,
    )
    assert commit.archive_key and commit.outbox_id
    bucket.fail_keys.add(commit.archive_key)

    result = await repository.flush_archive_outbox(limit=10)
    state = row(db, "cross_market_archive_outbox", str(commit.outbox_id))
    assert result.failed == 1
    assert state["attempts"] == 1
    assert state["delivery_state"] == "backoff"
    assert state["next_attempt_at"] is not None


@pytest.mark.asyncio
async def test_dead_letter_does_not_prevent_new_capture_evidence_commits(store) -> None:
    db, operational, bucket, repository = store
    poison = await operational.commit_snapshot(make_snapshot(6, datetime.now(UTC)))
    assert poison.archive_key and poison.outbox_id
    bucket.fail_keys.add(poison.archive_key)
    outbox_id = str(poison.outbox_id)
    await repository.flush_archive_outbox(limit=10)
    force_due(db, "archive_outbox", outbox_id)
    await repository.flush_archive_outbox(limit=10)
    force_due(db, "archive_outbox", outbox_id)
    await repository.flush_archive_outbox(limit=10)
    assert row(db, "archive_outbox", outbox_id)["delivery_state"] == "dead_letter"

    fresh = await operational.commit_snapshot(make_snapshot(7, datetime.now(UTC) + timedelta(seconds=1)))
    assert fresh.outbox_id is not None
    count = db.connection.execute(
        "SELECT COUNT(*) FROM market_snapshots WHERE id=?", (str(fresh.evidence_id),)
    ).fetchone()[0]
    assert count == 1
    fresh_state = row(db, "archive_outbox", str(fresh.outbox_id))
    assert fresh_state["delivery_state"] == "pending"
