"""Source-aware read helpers for live broker-free Gold quote/candle evidence."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Live Gold storage requires timezone-aware datetimes.")
    return value.astimezone(UTC)


def _row(value: object) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return dict(value)
    try:
        return dict(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise TypeError("Unexpected D1 live Gold row shape.") from exc


def _results(value: object) -> list[dict[str, Any]]:
    rows = getattr(value, "results", None)
    if rows is None and isinstance(value, dict):
        rows = value.get("results")
    if rows is None:
        return []
    return [row for item in rows if (row := _row(item)) is not None]


class D1LiveGoldQuoteHistory:
    """Read only the exact public-independent source requested by the live recorder."""

    def __init__(self, d1: Any) -> None:
        self._d1 = d1

    async def quote_observations(
        self,
        *,
        symbol: str,
        source: str,
        start_utc: datetime,
        end_utc: datetime,
    ) -> list[dict[str, Any]]:
        start = _utc(start_utc)
        end = _utc(end_utc)
        if end <= start:
            raise ValueError("Live Gold quote-history end must be after start.")
        result = await self._d1.prepare(
            """
            SELECT id,captured_at,bid,ask,mid,spread,quote_time,quote_age_seconds,
                   data_availability_json,snapshot_digest
            FROM market_snapshots
            WHERE symbol=? AND capture_status='complete'
              AND quote_time>=? AND quote_time<?
              AND bid IS NOT NULL AND ask IS NOT NULL AND mid IS NOT NULL AND spread IS NOT NULL
              AND json_extract(data_availability_json,'$.market_data_source')=?
            ORDER BY quote_time ASC,captured_at ASC,id ASC
            """
        ).bind(symbol, start.isoformat(), end.isoformat(), source).all()
        return _results(result)

    async def latest_candle_ids(self, *, symbol: str, source: str) -> dict[str, UUID]:
        result = await self._d1.prepare(
            """
            SELECT c.timeframe,c.id
            FROM market_candles c
            WHERE c.source=? AND c.symbol=?
              AND NOT EXISTS (
                SELECT 1 FROM market_candles newer
                WHERE newer.source=c.source AND newer.symbol=c.symbol
                  AND newer.timeframe=c.timeframe
                  AND (
                    newer.open_time_utc>c.open_time_utc OR
                    (newer.open_time_utc=c.open_time_utc
                     AND newer.revision_index>c.revision_index)
                  )
              )
            ORDER BY c.timeframe
            """
        ).bind(source, symbol).all()
        return {
            str(row["timeframe"]): UUID(str(row["id"]))
            for row in _results(result)
        }
