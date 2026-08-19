from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID, uuid4

from .cloudflare_storage import (
    D1OperationalEvidenceStore,
    _row_value,
    _segment,
    _stamp,
    _utc,
)
from .storage_contracts import ArchiveItem, EvidenceCommit


def cross_market_archive_key(
    *,
    source: str,
    series_id: str,
    observation_date: date,
    first_observed_at: datetime,
    payload_digest: str,
) -> str:
    day = _utc(first_observed_at).strftime("%Y/%m/%d")
    return (
        f"cross-market/{day}/{_segment(source)}/{_segment(series_id)}/"
        f"{observation_date.isoformat()}-{_stamp(first_observed_at)}-"
        f"{_segment(payload_digest)}.json"
    )


class D1CrossMarketOperationalEvidenceStore(D1OperationalEvidenceStore):
    """Day 9 extension of the proven D1/R2 operational evidence store."""

    async def commit_cross_market_observation(
        self,
        *,
        source: str,
        series_id: str,
        observation_date: date,
        value: str,
        unit: str,
        source_url: str,
        source_document_digest: str,
        first_observed_at: datetime,
        payload_digest: str,
    ) -> EvidenceCommit:
        first_seen = _utc(first_observed_at)
        observation_day = observation_date.isoformat()
        existing = await self._first(
            """
            SELECT id,revision_index,archive_key FROM cross_market_observations
            WHERE source=? AND series_id=? AND observation_date=? AND payload_digest=?
            LIMIT 1
            """,
            source,
            series_id,
            observation_day,
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
        logical_key = f"cross_market|{source}|{series_id}|{observation_day}"
        archive_key = cross_market_archive_key(
            source=source,
            series_id=series_id,
            observation_date=observation_date,
            first_observed_at=first_seen,
            payload_digest=payload_digest,
        )
        counter = self._stmt(
            """
            INSERT INTO revision_counters (logical_key,next_revision)
            SELECT ?,2
            WHERE NOT EXISTS (
                SELECT 1 FROM cross_market_observations
                WHERE source=? AND series_id=? AND observation_date=? AND payload_digest=?
            )
            ON CONFLICT(logical_key) DO UPDATE SET next_revision=next_revision+1
            """,
            logical_key,
            source,
            series_id,
            observation_day,
            payload_digest,
        )
        insert = self._stmt(
            """
            INSERT INTO cross_market_observations (
                id,source,series_id,observation_date,value,unit,source_url,
                source_document_digest,first_observed_at,revision_index,
                payload_digest,archive_key
            )
            SELECT ?,?,?,?,?,?,?,?,?,next_revision-1,?,?
            FROM revision_counters WHERE logical_key=?
            ON CONFLICT DO NOTHING
            """,
            evidence_id,
            source,
            series_id,
            observation_day,
            value,
            unit,
            source_url,
            source_document_digest,
            first_seen,
            payload_digest,
            archive_key,
            logical_key,
        )
        outbox = self._stmt(
            """
            INSERT INTO cross_market_archive_outbox (
                id,evidence_id,archive_key,payload_digest,status,created_at
            )
            SELECT ?,id,archive_key,payload_digest,'pending',?
            FROM cross_market_observations WHERE id=?
            """,
            outbox_id,
            datetime.now(UTC),
            evidence_id,
        )
        await self._db.batch([counter, insert, outbox])
        row = await self._first(
            "SELECT id,revision_index,archive_key FROM cross_market_observations WHERE id=?",
            evidence_id,
        )
        if row is None:
            row = await self._first(
                """
                SELECT id,revision_index,archive_key FROM cross_market_observations
                WHERE source=? AND series_id=? AND observation_date=? AND payload_digest=?
                LIMIT 1
                """,
                source,
                series_id,
                observation_day,
                payload_digest,
            )
            if row is None:
                raise RuntimeError("D1 cross-market commit did not persist evidence.")
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

    async def pending_archive_items(self, *, limit: int) -> list[ArchiveItem]:
        statement = self._stmt(
            """
            SELECT id,record_type,evidence_id,archive_key,payload_digest,created_at FROM (
              SELECT id,record_type,evidence_id,archive_key,payload_digest,created_at
              FROM archive_outbox WHERE status='pending'
              UNION ALL
              SELECT id,'cross_market' AS record_type,evidence_id,archive_key,payload_digest,created_at
              FROM cross_market_archive_outbox WHERE status='pending'
            )
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
        if record_type != "cross_market":
            return await super()._archive_payload_json(
                record_type=record_type, evidence_id=evidence_id
            )
        row = await self._first(
            """
            SELECT json_object(
              'schema_version',1,'record_type','cross_market','evidence_id',id,
              'archive_key',archive_key,'payload_digest',payload_digest,
              'revision_index',revision_index,
              'payload',json_object(
                'source',source,'series_id',series_id,'observation_date',observation_date,
                'value',value,'unit',unit,'source_url',source_url,
                'source_document_digest',source_document_digest,
                'first_observed_at',first_observed_at
              )
            ) AS payload_json
            FROM cross_market_observations WHERE id=?
            """,
            evidence_id,
        )
        payload = _row_value(row, "payload_json")
        if not isinstance(payload, str):
            raise RuntimeError("Cross-market outbox points to missing evidence.")
        return payload

    async def mark_archive_success(
        self, *, item: ArchiveItem, archived_at: datetime
    ) -> None:
        if item.record_type != "cross_market":
            await super().mark_archive_success(item=item, archived_at=archived_at)
            return
        await self._stmt(
            """
            UPDATE cross_market_archive_outbox
            SET status='archived',archived_at=?,last_error=NULL
            WHERE id=? AND status='pending'
            """,
            archived_at,
            item.outbox_id,
        ).run()

    async def mark_archive_failure(self, *, outbox_id: UUID, error_code: str) -> None:
        code = error_code[:160]
        await self._stmt(
            """
            UPDATE cross_market_archive_outbox
            SET attempts=attempts+1,last_error=?
            WHERE id=? AND status='pending'
            """,
            code,
            outbox_id,
        ).run()
        await super().mark_archive_failure(outbox_id=outbox_id, error_code=error_code)
