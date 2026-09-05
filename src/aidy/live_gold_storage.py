"""Source-aware read helpers for live broker-free Gold quote/candle evidence."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

_TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h", "1d")
_MAX_QUOTE_WINDOW = timedelta(days=1)
_MAX_QUOTE_ROWS = 3000


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
        if end - start > _MAX_QUOTE_WINDOW:
            raise ValueError("Live Gold quote-history reads are capped at one day.")
        result = await self._d1.prepare(
            """
            SELECT id,captured_at,bid,ask,mid,spread,quote_time,quote_age_seconds,
                   data_availability_json,snapshot_digest
            FROM market_snapshots
            WHERE symbol=? AND market_data_source=? AND capture_status='complete'
              AND quote_time>=? AND quote_time<?
              AND bid IS NOT NULL AND ask IS NOT NULL AND mid IS NOT NULL AND spread IS NOT NULL
            ORDER BY quote_time ASC,captured_at ASC,id ASC
            LIMIT ?
            """
        ).bind(
            symbol,
            source,
            start.isoformat(),
            end.isoformat(),
            _MAX_QUOTE_ROWS + 1,
        ).all()
        rows = _results(result)
        if len(rows) > _MAX_QUOTE_ROWS:
            raise RuntimeError("Live Gold quote-history row bound exceeded.")
        return rows

    async def latest_candle_ids(self, *, symbol: str, source: str) -> dict[str, UUID]:
        latest: dict[str, UUID] = {}
        for timeframe in _TIMEFRAMES:
            result = await self._d1.prepare(
                """
                SELECT id
                FROM market_candles
                WHERE source=? AND symbol=? AND timeframe=?
                ORDER BY open_time_utc DESC,revision_index DESC
                LIMIT 1
                """
            ).bind(source, symbol, timeframe).all()
            rows = _results(result)
            if rows:
                latest[timeframe] = UUID(str(rows[0]["id"]))
        return latest

    async def candle_id_for_bucket(
        self,
        *,
        symbol: str,
        source: str,
        timeframe: str,
        open_time_utc: datetime,
    ) -> UUID | None:
        if timeframe not in _TIMEFRAMES:
            raise ValueError("Unsupported live Gold candle timeframe.")
        result = await self._d1.prepare(
            """
            SELECT id
            FROM market_candles
            WHERE source=? AND symbol=? AND timeframe=? AND open_time_utc=?
            ORDER BY revision_index DESC
            LIMIT 1
            """
        ).bind(source, symbol, timeframe, _utc(open_time_utc).isoformat()).all()
        rows = _results(result)
        return None if not rows else UUID(str(rows[0]["id"]))
