from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from aidy.cloudflare_storage import candle_archive_key, event_archive_key
from aidy.storage_contracts import (
    AidyMarketRepository,
    ArchiveItem,
    EvidenceCommit,
    persisted_position_state_json,
)


def test_position_truth_known_empty_is_preserved() -> None:
    snapshot = {
        "position_state_json": "[]",
        "data_availability_json": json.dumps({"positions": "available"}),
    }
    assert persisted_position_state_json(snapshot) == "[]"


def test_position_truth_failed_read_is_unknown() -> None:
    snapshot = {
        "position_state_json": "[]",
        "data_availability_json": json.dumps({"positions": "metaapi_timeout"}),
    }
    assert persisted_position_state_json(snapshot) is None


def test_archive_keys_are_digest_bearing_and_partitioned() -> None:
    opened = datetime(2026, 8, 16, 7, 5, tzinfo=UTC)
    digest = "a" * 64
    candle_key = candle_archive_key(
        {
            "symbol": "XAUUSD",
            "timeframe": "5m",
            "open_time_utc": opened,
            "payload_digest": digest,
        }
    )
    event_key = event_archive_key(
        event_type="fed_speeches",
        first_observed_at=opened,
        payload_digest=digest,
    )
    assert candle_key.startswith("gold/candles/2026/08/16/XAUUSD/5m/")
    assert digest in candle_key
    assert event_key.startswith("gold/events/2026/08/16/fed_speeches/")
    assert digest in event_key


class FakeOperational:
    def __init__(self) -> None:
        self.item = ArchiveItem(
            outbox_id=uuid4(),
            record_type="candle",
            evidence_id=uuid4(),
            object_key="gold/candles/test.json",
            payload_digest="b" * 64,
            payload_json='{"schema_version":1}',
        )
        self.pending = [self.item]
        self.successes: list[ArchiveItem] = []
        self.failures: list[str] = []

    async def commit_candle(self, candle):
        return EvidenceCommit(self.item.evidence_id, 1, True, self.item.outbox_id, self.item.object_key)

    async def latest_candle_ids(self, *, symbol):
        return {}

    async def event_observation_ids_known_at(self, *, captured_at, lookback_hours=24):
        return []

    async def commit_snapshot(self, snapshot):
        return EvidenceCommit(uuid4(), 1, True)

    async def commit_event_observation(self, **kwargs):
        return EvidenceCommit(uuid4(), 1, True)

    async def pending_archive_items(self, *, limit):
        return self.pending[:limit]

    async def mark_archive_success(self, *, item, archived_at):
        self.successes.append(item)
        self.pending = [row for row in self.pending if row.outbox_id != item.outbox_id]

    async def mark_archive_failure(self, *, outbox_id, error_code):
        self.failures.append(error_code)


class FlakyArchive:
    def __init__(self) -> None:
        self.fail = True
        self.writes: list[str] = []

    async def put_immutable(self, item):
        if self.fail:
            raise RuntimeError("simulated R2 outage")
        self.writes.append(item.object_key)


@pytest.mark.asyncio
async def test_r2_failure_keeps_operational_outbox_pending_for_retry() -> None:
    operational = FakeOperational()
    archive = FlakyArchive()
    repository = AidyMarketRepository(operational, archive)

    first = await repository.flush_archive_outbox()
    assert first.attempted == 1
    assert first.archived == 0
    assert first.failed == 1
    assert operational.pending == [operational.item]
    assert operational.failures == ["archive_error:RuntimeError"]

    archive.fail = False
    second = await repository.flush_archive_outbox()
    assert second.archived == 1
    assert operational.pending == []
    assert archive.writes == [operational.item.object_key]
