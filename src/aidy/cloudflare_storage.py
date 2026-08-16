from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from .storage_contracts import ArchiveItem, EvidenceCommit, persisted_position_state_json

_SAFE_SEGMENT = re.compile(r"[^A-Za-z0-9._=-]+")


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("AIDY storage requires timezone-aware datetimes.")
    return value.astimezone(UTC)


def _iso(value: datetime | None) -> str | None:
    return _utc(value).isoformat() if value is not None else None


def _db_value(value: object) -> object:
    if isinstance(value, datetime):
        return _iso(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        return str(value)
    return value


def _row_value(row: object, key: str, default: object = None) -> object:
    if row is None:
        return default
    if isinstance(row, dict):
        return row.get(key, default)
    try:
        return row[key]  # type: ignore[index]
    except Exception:
        return getattr(row, key, default)


def _segment(value: object) -> str:
    cleaned = _SAFE_SEGMENT.sub("_", str(value).strip())
    return cleaned or "unknown"


def _stamp(value: datetime) -> str:
    return _utc(value).strftime("%Y%m%dT%H%M%S.%fZ")


def candle_archive_key(candle: dict[str, object]) -> str:
    opened = candle.get("open_time_utc")
    if not isinstance(opened, datetime):
        raise ValueError("Candle archive key requires open_time_utc.")
    day = _utc(opened).strftime("%Y/%m/%d")
    digest = _segment(candle.get("payload_digest"))
    return (
        f"gold/candles/{day}/{_segment(candle.get('symbol'))}/"
        f"{_segment(candle.get('timeframe'))}/{_stamp(opened)}-{digest}.json"
    )


def snapshot_archive_key(snapshot: dict[str, object], evidence_id: UUID) -> str:
    captured = snapshot.get("captured_at")
    if not isinstance(captured, datetime):
        raise ValueError("Snapshot archive key requires captured_at.")
    day = _utc(captured).strftime("%Y/%m/%d")
    digest = _segment(snapshot.get("snapshot_digest"))
    return f"gold/snapshots/{day}/{_stamp(captured)}-{evidence_id}-{digest}.json"


def event_archive_key(
    *, event_type: str, first_observed_at: datetime, payload_digest: str
) -> str:
    day = _utc(first_observed_at).strftime("%Y/%m/%d")
    return (
        f"gold/events/{day}/{_segment(event_type)}/"
        f"{_stamp(first_observed_at)}-{_segment(payload_digest)}.json"
    )


class D1OperationalEvidenceStore:
    """Cloudflare D1 operational evidence store with an atomic archive outbox."""

    def __init__(self, database: object) -> None:
        self._db = database

    async def _first(self, sql: str, *params: object) -> object:
        statement = self._db.prepare(sql).bind(*[_db_value(value) for value in params])
        return await statement.first()

    def _stmt(self, sql: str, *params: object) -> object:
        return self._db.prepare(sql).bind(*[_db_value(value) for value in params])

    async def commit_candle(self, candle: dict[str, object]) -> EvidenceCommit:
        required = (
            "source",
            "symbol",
            "timeframe",
            "open_time_utc",
            "open",
            "high",
            "low",
            "close",
            "payload_digest",
            "first_observed_at",
        )
        if any(candle.get(key) is None for key in required):
            raise ValueError("Incomplete candle evidence.")
        existing = await self._first(
            """
            SELECT id, revision_index, archive_key
            FROM market_candles
            WHERE source=? AND symbol=? AND timeframe=? AND open_time_utc=?
              AND payload_digest=?
            LIMIT 1
            """,
            candle["source"],
            candle["symbol"],
            candle["timeframe"],
            candle["open_time_utc"],
            candle["payload_digest"],
        )
        if existing is not None:
            return EvidenceCommit(
                UUID(str(_row_value(existing, "id"))),
                int(_row_value(existing, "revision_index")),
                False,
                archive_key=str(_row_value(existing, "archive_key")),
            )

        evidence_id = uuid4()
        outbox_id = uuid4()
        logical_key = "|".join(
            (
                "candle",
                str(candle["source"]),
                str(candle["symbol"]),
                str(candle["timeframe"]),
                str(_iso(candle["open_time_utc"])),  # type: ignore[arg-type]
            )
        )
        archive_key = candle_archive_key(candle)
        counter = self._stmt(
            """
            INSERT INTO revision_counters (logical_key, next_revision)
            SELECT ?, 2
            WHERE NOT EXISTS (
                SELECT 1 FROM market_candles
                WHERE source=? AND symbol=? AND timeframe=? AND open_time_utc=?
                  AND payload_digest=?
            )
            ON CONFLICT(logical_key) DO UPDATE SET next_revision=next_revision+1
            """,
            logical_key,
            candle["source"],
            candle["symbol"],
            candle["timeframe"],
            candle["open_time_utc"],
            candle["payload_digest"],
        )
        insert = self._stmt(
            """
            INSERT INTO market_candles (
                id,symbol,timeframe,open_time_utc,broker_open_time,
                open,high,low,close,tick_volume,spread,volume,source,
                revision_index,payload_digest,first_observed_at,archive_key
            )
            SELECT ?,?,?,?,?,?,?,?,?,?,?,?,?,next_revision-1,?,?,?
            FROM revision_counters WHERE logical_key=?
            ON CONFLICT DO NOTHING
            """,
            evidence_id,
            candle["symbol"],
            candle["timeframe"],
            candle["open_time_utc"],
            candle.get("broker_open_time"),
            candle["open"],
            candle["high"],
            candle["low"],
            candle["close"],
            candle.get("tick_volume"),
            candle.get("spread"),
            candle.get("volume"),
            candle["source"],
            candle["payload_digest"],
            candle["first_observed_at"],
            archive_key,
            logical_key,
        )
        outbox = self._stmt(
            """
            INSERT INTO archive_outbox (
                id,record_type,evidence_id,archive_key,payload_digest,status,created_at
            )
            SELECT ?,'candle',id,archive_key,payload_digest,'pending',?
            FROM market_candles WHERE id=?
            """,
            outbox_id,
            datetime.now(UTC),
            evidence_id,
        )
        await self._db.batch([counter, insert, outbox])
        row = await self._first(
            "SELECT id,revision_index,archive_key FROM market_candles WHERE id=?", evidence_id
        )
        if row is None:
            row = await self._first(
                """
                SELECT id,revision_index,archive_key FROM market_candles
                WHERE source=? AND symbol=? AND timeframe=? AND open_time_utc=?
                  AND payload_digest=? LIMIT 1
                """,
                candle["source"],
                candle["symbol"],
                candle["timeframe"],
                candle["open_time_utc"],
                candle["payload_digest"],
            )
            if row is None:
                raise RuntimeError("D1 candle commit did not persist evidence.")
            return EvidenceCommit(
                UUID(str(_row_value(row, "id"))),
                int(_row_value(row, "revision_index")),
                False,
                archive_key=str(_row_value(row, "archive_key")),
            )
        return EvidenceCommit(
            evidence_id,
            int(_row_value(row, "revision_index")),
            True,
            outbox_id=outbox_id,
            archive_key=archive_key,
        )

    async def latest_candle_ids(self, *, symbol: str) -> dict[str, UUID]:
        statement = self._stmt(
            """
            SELECT c.timeframe, c.id
            FROM market_candles c
            WHERE c.source='metaapi' AND c.symbol=?
              AND NOT EXISTS (
                SELECT 1 FROM market_candles newer
                WHERE newer.source=c.source AND newer.symbol=c.symbol
                  AND newer.timeframe=c.timeframe
                  AND (
                    newer.open_time_utc > c.open_time_utc OR
                    (newer.open_time_utc = c.open_time_utc
                     AND newer.revision_index > c.revision_index)
                  )
              )
            ORDER BY c.timeframe
            """,
            symbol,
        )
        result = await statement.all()
        rows = _row_value(result, "results", [])
        return {
            str(_row_value(row, "timeframe")): UUID(str(_row_value(row, "id")))
            for row in rows or []
        }

    async def event_observation_ids_known_at(
        self, *, captured_at: datetime, lookback_hours: int = 24
    ) -> list[UUID]:
        if lookback_hours <= 0:
            raise ValueError("Event lookback must be positive.")
        captured = _utc(captured_at)
        earliest = captured - timedelta(hours=lookback_hours)
        statement = self._stmt(
            """
            SELECT e.id
            FROM market_event_observations e
            WHERE e.first_observed_at <= ? AND e.first_observed_at >= ?
              AND NOT EXISTS (
                SELECT 1 FROM market_event_observations newer
                WHERE newer.source=e.source AND newer.external_id=e.external_id
                  AND newer.first_observed_at <= ? AND newer.first_observed_at >= ?
                  AND (
                    newer.revision_index > e.revision_index OR
                    (newer.revision_index=e.revision_index
                     AND newer.first_observed_at > e.first_observed_at)
                  )
              )
            ORDER BY e.first_observed_at,e.source,e.external_id
            """,
            captured,
            earliest,
            captured,
            earliest,
        )
        result = await statement.all()
        rows = _row_value(result, "results", [])
        return [UUID(str(_row_value(row, "id"))) for row in rows or []]

    async def commit_snapshot(self, snapshot: dict[str, object]) -> EvidenceCommit:
        captured = snapshot.get("captured_at")
        if not isinstance(captured, datetime):
            raise ValueError("Snapshot requires captured_at.")
        evidence_id = uuid4()
        outbox_id = uuid4()
        archive_key = snapshot_archive_key(snapshot, evidence_id)
        position_state = persisted_position_state_json(snapshot)
        insert = self._stmt(
            """
            INSERT INTO market_snapshots (
                id,captured_at,symbol,capture_status,bid,ask,mid,spread,
                quote_time,quote_age_seconds,session_code,position_state_json,
                data_availability_json,event_observation_ids_json,
                latest_m1_id,latest_m5_id,latest_m15_id,latest_h1_id,
                latest_h4_id,latest_d1_id,snapshot_digest,archive_key
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            evidence_id,
            captured,
            snapshot["symbol"],
            snapshot["capture_status"],
            snapshot.get("bid"),
            snapshot.get("ask"),
            snapshot.get("mid"),
            snapshot.get("spread"),
            snapshot.get("quote_time"),
            snapshot.get("quote_age_seconds"),
            snapshot["session_code"],
            position_state,
            snapshot["data_availability_json"],
            snapshot["event_observation_ids_json"],
            snapshot.get("latest_m1_id"),
            snapshot.get("latest_m5_id"),
            snapshot.get("latest_m15_id"),
            snapshot.get("latest_h1_id"),
            snapshot.get("latest_h4_id"),
            snapshot.get("latest_d1_id"),
            snapshot["snapshot_digest"],
            archive_key,
        )
        outbox = self._stmt(
            """
            INSERT INTO archive_outbox (
                id,record_type,evidence_id,archive_key,payload_digest,status,created_at
            ) VALUES (?,'snapshot',?,?,?,'pending',?)
            """,
            outbox_id,
            evidence_id,
            archive_key,
            snapshot["snapshot_digest"],
            datetime.now(UTC),
        )
        await self._db.batch([insert, outbox])
        return EvidenceCommit(
            evidence_id, 1, True, outbox_id=outbox_id, archive_key=archive_key
        )

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
    ) -> EvidenceCommit:
        first_seen = _utc(first_observed_at)
        existing = await self._first(
            """
            SELECT id,revision_index,archive_key FROM market_event_observations
            WHERE source=? AND external_id=? AND payload_digest=? LIMIT 1
            """,
            source,
            external_id,
            payload_digest,
        )
        if existing is not None:
            return EvidenceCommit(
                UUID(str(_row_value(existing, "id"))),
                int(_row_value(existing, "revision_index")),
                False,
                archive_key=str(_row_value(existing, "archive_key")),
            )
        evidence_id = uuid4()
        outbox_id = uuid4()
        logical_key = f"event|{source}|{external_id}"
        archive_key = event_archive_key(
            event_type=event_type,
            first_observed_at=first_seen,
            payload_digest=payload_digest,
        )
        counter = self._stmt(
            """
            INSERT INTO revision_counters (logical_key,next_revision)
            SELECT ?,2
            WHERE NOT EXISTS (
                SELECT 1 FROM market_event_observations
                WHERE source=? AND external_id=? AND payload_digest=?
            )
            ON CONFLICT(logical_key) DO UPDATE SET next_revision=next_revision+1
            """,
            logical_key,
            source,
            external_id,
            payload_digest,
        )
        insert = self._stmt(
            """
            INSERT INTO market_event_observations (
                id,source,external_id,event_type,published_at,first_observed_at,
                revision_index,headline,structured_data_json,raw_payload_json,
                payload_digest,archive_key
            )
            SELECT ?,?,?,?,?,?,next_revision-1,?,?,?,?,?
            FROM revision_counters WHERE logical_key=?
            ON CONFLICT DO NOTHING
            """,
            evidence_id,
            source,
            external_id,
            event_type,
            published_at,
            first_seen,
            headline,
            structured_data_json,
            raw_payload_json,
            payload_digest,
            archive_key,
            logical_key,
        )
        outbox = self._stmt(
            """
            INSERT INTO archive_outbox (
                id,record_type,evidence_id,archive_key,payload_digest,status,created_at
            )
            SELECT ?,'event',id,archive_key,payload_digest,'pending',?
            FROM market_event_observations WHERE id=?
            """,
            outbox_id,
            datetime.now(UTC),
            evidence_id,
        )
        await self._db.batch([counter, insert, outbox])
        row = await self._first(
            "SELECT id,revision_index,archive_key FROM market_event_observations WHERE id=?",
            evidence_id,
        )
        if row is None:
            row = await self._first(
                """
                SELECT id,revision_index,archive_key FROM market_event_observations
                WHERE source=? AND external_id=? AND payload_digest=? LIMIT 1
                """,
                source,
                external_id,
                payload_digest,
            )
            if row is None:
                raise RuntimeError("D1 event commit did not persist evidence.")
            return EvidenceCommit(
                UUID(str(_row_value(row, "id"))),
                int(_row_value(row, "revision_index")),
                False,
                archive_key=str(_row_value(row, "archive_key")),
            )
        return EvidenceCommit(
            evidence_id,
            int(_row_value(row, "revision_index")),
            True,
            outbox_id=outbox_id,
            archive_key=archive_key,
        )

    async def create_storage_smoke_probe(self, *, now: datetime) -> EvidenceCommit:
        created_at = _utc(now)
        evidence_id = uuid4()
        outbox_id = uuid4()
        payload = {
            "kind": "aidy_day1_storage_smoke",
            "created_at": created_at.isoformat(),
            "probe_id": str(evidence_id),
        }
        payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        from hashlib import sha256

        digest = sha256(payload_json.encode("utf-8")).hexdigest()
        day = created_at.strftime("%Y/%m/%d")
        archive_key = f"day1/storage-smoke/{day}/{evidence_id}-{digest}.json"
        insert = self._stmt(
            """
            INSERT INTO storage_smoke_probes
                (id,created_at,payload_json,payload_digest,archive_key)
            VALUES (?,?,?,?,?)
            """,
            evidence_id,
            created_at,
            payload_json,
            digest,
            archive_key,
        )
        outbox = self._stmt(
            """
            INSERT INTO archive_outbox (
                id,record_type,evidence_id,archive_key,payload_digest,status,created_at
            ) VALUES (?,'storage_smoke',?,?,?,'pending',?)
            """,
            outbox_id,
            evidence_id,
            archive_key,
            digest,
            created_at,
        )
        await self._db.batch([insert, outbox])
        return EvidenceCommit(
            evidence_id, 1, True, outbox_id=outbox_id, archive_key=archive_key
        )

    async def archive_status(self, *, outbox_id: UUID) -> str | None:
        row = await self._first("SELECT status FROM archive_outbox WHERE id=?", outbox_id)
        value = _row_value(row, "status")
        return str(value) if value is not None else None

    async def pending_archive_items(self, *, limit: int) -> list[ArchiveItem]:
        statement = self._stmt(
            """
            SELECT id,record_type,evidence_id,archive_key,payload_digest
            FROM archive_outbox
            WHERE status='pending'
            ORDER BY created_at,id
            LIMIT ?
            """,
            limit,
        )
        result = await statement.all()
        rows = _row_value(result, "results", []) or []
        items: list[ArchiveItem] = []
        for row in rows:
            record_type = str(_row_value(row, "record_type"))
            evidence_id = UUID(str(_row_value(row, "evidence_id")))
            payload_json = await self._archive_payload_json(
                record_type=record_type, evidence_id=evidence_id
            )
            items.append(
                ArchiveItem(
                    outbox_id=UUID(str(_row_value(row, "id"))),
                    record_type=record_type,
                    evidence_id=evidence_id,
                    object_key=str(_row_value(row, "archive_key")),
                    payload_digest=str(_row_value(row, "payload_digest")),
                    payload_json=payload_json,
                )
            )
        return items

    async def _archive_payload_json(self, *, record_type: str, evidence_id: UUID) -> str:
        if record_type == "candle":
            sql = """
            SELECT json_object(
              'schema_version',1,'record_type','candle','evidence_id',id,
              'archive_key',archive_key,'payload_digest',payload_digest,
              'revision_index',revision_index,
              'payload',json_object(
                'symbol',symbol,'timeframe',timeframe,'open_time_utc',open_time_utc,
                'broker_open_time',broker_open_time,'open',open,'high',high,'low',low,
                'close',close,'tick_volume',tick_volume,'spread',spread,'volume',volume,
                'source',source,'first_observed_at',first_observed_at
              )
            ) AS payload_json FROM market_candles WHERE id=?
            """
        elif record_type == "snapshot":
            sql = """
            SELECT json_object(
              'schema_version',1,'record_type','snapshot','evidence_id',id,
              'archive_key',archive_key,'payload_digest',snapshot_digest,
              'payload',json_object(
                'captured_at',captured_at,'symbol',symbol,'capture_status',capture_status,
                'bid',bid,'ask',ask,'mid',mid,'spread',spread,'quote_time',quote_time,
                'quote_age_seconds',quote_age_seconds,'session_code',session_code,
                'position_state',CASE WHEN position_state_json IS NULL THEN NULL ELSE json(position_state_json) END,
                'data_availability',json(data_availability_json),
                'event_observation_ids',json(event_observation_ids_json),
                'latest_m1_id',latest_m1_id,'latest_m5_id',latest_m5_id,
                'latest_m15_id',latest_m15_id,'latest_h1_id',latest_h1_id,
                'latest_h4_id',latest_h4_id,'latest_d1_id',latest_d1_id
              )
            ) AS payload_json FROM market_snapshots WHERE id=?
            """
        elif record_type == "event":
            sql = """
            SELECT json_object(
              'schema_version',1,'record_type','event','evidence_id',id,
              'archive_key',archive_key,'payload_digest',payload_digest,
              'revision_index',revision_index,
              'payload',json_object(
                'source',source,'external_id',external_id,'event_type',event_type,
                'published_at',published_at,'first_observed_at',first_observed_at,
                'headline',headline,'structured_data',json(structured_data_json),
                'raw_payload',json(raw_payload_json)
              )
            ) AS payload_json FROM market_event_observations WHERE id=?
            """
        elif record_type == "storage_smoke":
            sql = """
            SELECT json_object(
              'schema_version',1,'record_type','storage_smoke','evidence_id',id,
              'archive_key',archive_key,'payload_digest',payload_digest,
              'payload',json(payload_json)
            ) AS payload_json FROM storage_smoke_probes WHERE id=?
            """
        else:
            raise RuntimeError("Unsupported archive outbox record type.")
        row = await self._first(sql, evidence_id)
        payload = _row_value(row, "payload_json")
        if not isinstance(payload, str):
            raise RuntimeError("Archive outbox points to missing operational evidence.")
        return payload

    async def mark_archive_success(
        self, *, item: ArchiveItem, archived_at: datetime
    ) -> None:
        statements = [
            self._stmt(
                """
                UPDATE archive_outbox
                SET status='archived',archived_at=?,last_error=NULL
                WHERE id=? AND status='pending'
                """,
                archived_at,
                item.outbox_id,
            )
        ]
        if item.record_type == "event":
            statements.append(
                self._stmt(
                    "UPDATE market_event_observations SET raw_payload_json=NULL WHERE id=?",
                    item.evidence_id,
                )
            )
        await self._db.batch(statements)

    async def mark_archive_failure(self, *, outbox_id: UUID, error_code: str) -> None:
        code = error_code[:160]
        await self._stmt(
            """
            UPDATE archive_outbox
            SET attempts=attempts+1,last_error=?
            WHERE id=? AND status='pending'
            """,
            code,
            outbox_id,
        ).run()


class R2ArchiveStore:
    """Append-only R2 writer.

    Archive keys include the evidence digest. Existing objects are treated as a
    successful idempotent retry and are never overwritten.
    """

    def __init__(self, bucket: object) -> None:
        self._bucket = bucket

    async def put_immutable(self, item: ArchiveItem) -> None:
        existing = await self._bucket.head(item.object_key)
        if existing is not None:
            return
        await self._bucket.put(item.object_key, item.payload_json)
