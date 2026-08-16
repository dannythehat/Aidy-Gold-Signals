from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID


def persisted_position_state_json(snapshot: dict[str, object]) -> str | None:
    """Persist positions only when the broker read explicitly succeeded.

    ``[]`` means AIDY checked and found no positions. ``None`` means AIDY did not
    know the position state at capture time, including read failure/not attempted.
    """

    raw_availability = snapshot.get("data_availability_json")
    if not isinstance(raw_availability, str):
        return None
    try:
        availability = json.loads(raw_availability)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(availability, dict) or availability.get("positions") != "available":
        return None
    value = snapshot.get("position_state_json")
    return value if isinstance(value, str) else None


@dataclass(frozen=True, slots=True)
class EvidenceCommit:
    evidence_id: UUID
    revision_index: int
    created: bool
    outbox_id: UUID | None = None
    archive_key: str | None = None


@dataclass(frozen=True, slots=True)
class ArchiveItem:
    outbox_id: UUID
    record_type: str
    evidence_id: UUID
    object_key: str
    payload_digest: str
    payload_json: str


@dataclass(frozen=True, slots=True)
class ArchiveFlushResult:
    attempted: int
    archived: int
    failed: int


class OperationalEvidenceStore(Protocol):
    async def commit_candle(self, candle: dict[str, object]) -> EvidenceCommit: ...

    async def latest_candle_ids(self, *, symbol: str) -> dict[str, UUID]: ...

    async def event_observation_ids_known_at(
        self, *, captured_at: datetime, lookback_hours: int = 24
    ) -> list[UUID]: ...

    async def commit_snapshot(self, snapshot: dict[str, object]) -> EvidenceCommit: ...

    async def commit_event_observation(
        self,
        *,
        source: str,
        external_id: str,
        event_type: str,
        published_at: datetime | None,
        first_observed_at: datetime,
        headline: str | None,
        structured_data_json: str,
        raw_payload_json: str,
        payload_digest: str,
    ) -> EvidenceCommit: ...

    async def pending_archive_items(self, *, limit: int) -> list[ArchiveItem]: ...

    async def mark_archive_success(
        self, *, item: ArchiveItem, archived_at: datetime
    ) -> None: ...

    async def mark_archive_failure(self, *, outbox_id: UUID, error_code: str) -> None: ...


class ArchiveStore(Protocol):
    async def put_immutable(self, item: ArchiveItem) -> None: ...


class AidyMarketRepository:
    """Portable async repository used by recorder services.

    D1 implementations commit an evidence row and its archive-outbox pointer in
    one transaction. R2 delivery is deliberately separate: a failed R2 write
    leaves the outbox pending, so operationally committed evidence cannot vanish
    silently.
    """

    def __init__(self, operational: OperationalEvidenceStore, archive: ArchiveStore) -> None:
        self._operational = operational
        self._archive = archive

    async def store_candle(self, candle: dict[str, object]) -> tuple[UUID, int, bool]:
        committed = await self._operational.commit_candle(candle)
        return committed.evidence_id, committed.revision_index, committed.created

    async def latest_candle_ids(self, *, symbol: str) -> dict[str, UUID]:
        return await self._operational.latest_candle_ids(symbol=symbol)

    async def event_observation_ids_known_at(
        self, *, captured_at: datetime, lookback_hours: int = 24
    ) -> list[UUID]:
        return await self._operational.event_observation_ids_known_at(
            captured_at=captured_at, lookback_hours=lookback_hours
        )

    async def store_snapshot(self, snapshot: dict[str, object]) -> UUID:
        committed = await self._operational.commit_snapshot(snapshot)
        return committed.evidence_id

    async def store_event_observation(
        self,
        *,
        source: str,
        external_id: str,
        event_type: str,
        published_at: datetime | None,
        first_observed_at: datetime,
        headline: str | None,
        structured_data_json: str,
        raw_payload_json: str,
        payload_digest: str,
    ) -> tuple[UUID, int, bool]:
        committed = await self._operational.commit_event_observation(
            source=source,
            external_id=external_id,
            event_type=event_type,
            published_at=published_at,
            first_observed_at=first_observed_at,
            headline=headline,
            structured_data_json=structured_data_json,
            raw_payload_json=raw_payload_json,
            payload_digest=payload_digest,
        )
        return committed.evidence_id, committed.revision_index, committed.created

    async def flush_archive_outbox(self, *, limit: int = 100) -> ArchiveFlushResult:
        if limit <= 0:
            raise ValueError("Archive flush limit must be positive.")
        items = await self._operational.pending_archive_items(limit=limit)
        archived = 0
        failed = 0
        for item in items:
            try:
                await self._archive.put_immutable(item)
            except Exception as exc:  # archive provider errors are deliberately isolated
                failed += 1
                await self._operational.mark_archive_failure(
                    outbox_id=item.outbox_id,
                    error_code=f"archive_error:{type(exc).__name__}",
                )
                continue
            await self._operational.mark_archive_success(
                item=item,
                archived_at=datetime.now(UTC),
            )
            archived += 1
        return ArchiveFlushResult(attempted=len(items), archived=archived, failed=failed)
