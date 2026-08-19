from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from aidy.cloudflare_storage import D1OperationalEvidenceStore, R2ArchiveStore
from aidy.continuity_auditor import ContinuityPolicy, D1R2ContinuityReader
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
        if row is None:
            return None
        return dict(row)

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
        schema = Path("migrations/d1/0001_aidy_ops.sql").read_text()
        self.connection.executescript(schema)

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


class LocalR2:
    def __init__(self) -> None:
        self.objects: dict[str, str] = {}
        self.fail_put = False

    async def head(self, key: str):
        return {"key": key} if key in self.objects else None

    async def put(self, key: str, value: str):
        if self.fail_put:
            raise RuntimeError("simulated outage")
        self.objects[key] = value
        return {"key": key}


@pytest.fixture
def operational(monkeypatch):
    monkeypatch.chdir(Path(__file__).parents[1])
    return D1OperationalEvidenceStore(LocalD1())


@pytest.mark.asyncio
async def test_d1_candle_revision_and_idempotency(operational) -> None:
    opened = datetime(2026, 8, 16, 8, 0, tzinfo=UTC)
    candle = {
        "symbol": "XAUUSD",
        "timeframe": "5m",
        "open_time_utc": opened,
        "broker_open_time": None,
        "open": "4350",
        "high": "4355",
        "low": "4348",
        "close": "4353",
        "tick_volume": 100,
        "spread": "0.20",
        "volume": None,
        "source": "metaapi",
        "payload_digest": "1" * 64,
        "first_observed_at": opened + timedelta(minutes=5),
    }
    first = await operational.commit_candle(candle)
    same = await operational.commit_candle(candle)
    revised = await operational.commit_candle(
        {**candle, "close": "4354", "payload_digest": "2" * 64}
    )
    assert first.created is True and first.revision_index == 1
    assert same.created is False and same.evidence_id == first.evidence_id
    assert revised.created is True and revised.revision_index == 2
    count = operational._db.connection.execute("SELECT COUNT(*) FROM archive_outbox").fetchone()[0]
    assert count == 2


@pytest.mark.asyncio
async def test_d1_snapshot_discards_broker_position_payload(operational) -> None:
    captured = datetime(2026, 8, 16, 9, 0, tzinfo=UTC)
    snapshot = {
        "captured_at": captured,
        "symbol": "XAUUSD",
        "capture_status": "partial",
        "bid": None,
        "ask": None,
        "mid": None,
        "spread": None,
        "quote_time": None,
        "quote_age_seconds": None,
        "session_code": "off_hours",
        "position_state_json": "[]",
        "data_availability_json": '{"positions":"available"}',
        "event_observation_ids_json": "[]",
        "latest_m1_id": None,
        "latest_m5_id": None,
        "latest_m15_id": None,
        "latest_h1_id": None,
        "latest_h4_id": None,
        "latest_d1_id": None,
        "snapshot_digest": "3" * 64,
    }
    committed = await operational.commit_snapshot(snapshot)
    row = operational._db.connection.execute(
        "SELECT position_state_json FROM market_snapshots WHERE id=?",
        (str(committed.evidence_id),),
    ).fetchone()
    assert row[0] is None


@pytest.mark.asyncio
async def test_d1_event_revision_is_point_in_time(operational) -> None:
    first_seen = datetime(2026, 8, 16, 7, 0, tzinfo=UTC)
    first = await operational.commit_event_observation(
        source="federal_reserve_rss",
        external_id="fed_speeches:test-event",
        event_type="fed_speeches",
        published_at=first_seen,
        first_observed_at=first_seen,
        headline="Initial",
        structured_data_json="{}",
        raw_payload_json='{"version":1}',
        payload_digest="a" * 64,
    )
    revised = await operational.commit_event_observation(
        source="federal_reserve_rss",
        external_id="fed_speeches:test-event",
        event_type="fed_speeches",
        published_at=first_seen,
        first_observed_at=first_seen + timedelta(minutes=10),
        headline="Revised",
        structured_data_json="{}",
        raw_payload_json='{"version":2}',
        payload_digest="b" * 64,
    )
    before = await operational.event_observation_ids_known_at(
        captured_at=first_seen + timedelta(minutes=5)
    )
    after = await operational.event_observation_ids_known_at(
        captured_at=first_seen + timedelta(minutes=11)
    )
    assert first.evidence_id in before and revised.evidence_id not in before
    assert revised.evidence_id in after and first.evidence_id not in after


@pytest.mark.asyncio
async def test_outbox_archive_round_trip_and_event_raw_pruning(operational) -> None:
    first_seen = datetime(2026, 8, 16, 7, 0, tzinfo=UTC)
    event = await operational.commit_event_observation(
        source="federal_reserve_rss",
        external_id="fed_press_monetary:archive-test",
        event_type="fed_press_monetary",
        published_at=first_seen,
        first_observed_at=first_seen,
        headline="Statement",
        structured_data_json="{}",
        raw_payload_json='{"raw":true}',
        payload_digest="c" * 64,
    )
    bucket = LocalR2()
    repository = AidyMarketRepository(operational, R2ArchiveStore(bucket))
    result = await repository.flush_archive_outbox(limit=100)
    assert result.failed == 0
    assert result.archived >= 1
    assert event.archive_key in bucket.objects
    raw = operational._db.connection.execute(
        "SELECT raw_payload_json FROM market_event_observations WHERE id=?",
        (str(event.evidence_id),),
    ).fetchone()[0]
    assert raw is None


@pytest.mark.asyncio
async def test_storage_smoke_uses_same_outbox_path(operational) -> None:
    probe = await operational.create_storage_smoke_probe(
        now=datetime(2026, 8, 16, 10, 0, tzinfo=UTC)
    )
    bucket = LocalR2()
    repository = AidyMarketRepository(operational, R2ArchiveStore(bucket))
    result = await repository.flush_archive_outbox(limit=100)
    assert result.failed == 0
    assert probe.archive_key in bucket.objects
    assert await operational.archive_status(outbox_id=probe.outbox_id) == "archived"


@pytest.mark.asyncio
async def test_day3_d1_r2_reader_proves_a_complete_window(operational) -> None:
    end = datetime.now(UTC).replace(second=0, microsecond=0) + timedelta(minutes=1)
    start = end - timedelta(minutes=11)
    for index in range(11):
        captured = start + timedelta(minutes=index)
        for timeframe in ("1m", "5m"):
            if timeframe == "5m" and index % 5:
                continue
            digest = f"{1000 + index * 10 + (timeframe == '5m'):064x}"
            await operational.commit_candle(
                {
                    "symbol": "XAUUSD",
                    "timeframe": timeframe,
                    "open_time_utc": captured,
                    "broker_open_time": None,
                    "open": "4350",
                    "high": "4355",
                    "low": "4348",
                    "close": "4353",
                    "tick_volume": 100,
                    "spread": "0.20",
                    "volume": None,
                    "source": "metaapi",
                    "payload_digest": digest,
                    "first_observed_at": captured,
                }
            )
        await operational.commit_snapshot(
            {
                "captured_at": captured,
                "symbol": "XAUUSD",
                "capture_status": "complete",
                "bid": "4352.9",
                "ask": "4353.1",
                "mid": "4353",
                "spread": "0.2",
                "quote_time": captured,
                "quote_age_seconds": 1.0,
                "session_code": "london",
                "data_availability_json": (
                    '{"quote":"available","candles_1m":"available",'
                    '"candles_5m":"available","market_state":"open"}'
                ),
                "event_observation_ids_json": "[]",
                "latest_m1_id": None,
                "latest_m5_id": None,
                "latest_m15_id": None,
                "latest_h1_id": None,
                "latest_h4_id": None,
                "latest_d1_id": None,
                "snapshot_digest": f"{2000 + index:064x}",
            }
        )

    bucket = LocalR2()
    repository = AidyMarketRepository(operational, R2ArchiveStore(bucket))
    flushed = await repository.flush_archive_outbox(limit=100)
    assert flushed.failed == 0

    report = await D1R2ContinuityReader(operational._db, bucket).load_and_audit(
        start=start,
        end=end,
        archive_limit=40,
        policy=ContinuityPolicy(
            expected_source="metaapi",
            capture_enabled=True,
            ownership_confirmed=True,
            stale_quote_seconds=30,
        ),
    )
    assert report.passed is True
    assert report.expected_cycles == 11
    assert report.observed_cycles == 11
    assert report.archive_population == flushed.archived
    assert report.archive_checked == flushed.archived
    assert report.archive_missing_objects == 0
