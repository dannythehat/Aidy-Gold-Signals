"""D1 helpers for Twelve Data feed envelopes and revision-aware candle reads."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from .twelve_data_market import AGGREGATE_SOURCE, AIDY_SYMBOL, RAW_M1_SOURCE, TwelveDataFetch


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Twelve Data storage requires timezone-aware datetimes.")
    return value.astimezone(UTC)


def _row(value: object) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return dict(value)
    try:
        return dict(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise TypeError("Unexpected D1 Twelve Data row shape.") from exc


def _results(value: object) -> list[dict[str, Any]]:
    rows = getattr(value, "results", None)
    if rows is None and isinstance(value, dict):
        rows = value.get("results")
    if rows is None:
        return []
    return [row for item in rows if (row := _row(item)) is not None]


class D1TwelveDataMarketStore:
    def __init__(self, d1: Any) -> None:
        self._d1 = d1

    async def record_feed_observation(self, fetch: TwelveDataFetch) -> UUID:
        observation_id = uuid4()
        await self._d1.prepare(
            """
            INSERT INTO twelve_data_feed_observations (
                id,fetched_at_utc,source,symbol,interval,meta_json,credit_headers_json,
                raw_bar_count,admitted_closed_bar_count,forming_bar_count,off_session_bar_count,
                latest_closed_bar_open_utc,latest_closed_bar_close_utc,observed_lag_seconds,
                session_open_at_fetch,freshness_state,response_digest
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """
        ).bind(
            str(observation_id),
            fetch.fetched_at_utc.isoformat(),
            "twelve_data",
            "XAU/USD",
            "1min",
            json.dumps(fetch.meta, sort_keys=True, separators=(",", ":"), default=str),
            json.dumps(fetch.credit_headers, sort_keys=True, separators=(",", ":")),
            fetch.raw_bar_count,
            len(fetch.closed_bars),
            fetch.forming_bar_count,
            fetch.off_session_bar_count,
            fetch.latest_closed_bar_open_utc.isoformat()
            if fetch.latest_closed_bar_open_utc is not None
            else None,
            fetch.latest_closed_bar_close_utc.isoformat()
            if fetch.latest_closed_bar_close_utc is not None
            else None,
            fetch.open_session_lag_seconds,
            1 if fetch.session_open_at_fetch else 0,
            fetch.freshness_state,
            fetch.response_digest,
        ).run()
        return observation_id

    async def latest_m1_bars(
        self,
        *,
        start_utc: datetime,
        end_utc: datetime,
    ) -> list[dict[str, Any]]:
        start = _utc(start_utc)
        end = _utc(end_utc)
        result = await self._d1.prepare(
            """
            SELECT c.id,c.open_time_utc,c.open,c.high,c.low,c.close,c.revision_index,
                   c.payload_digest,c.first_observed_at
            FROM market_candles c
            WHERE c.source=? AND c.symbol=? AND c.timeframe='1m'
              AND c.open_time_utc>=? AND c.open_time_utc<?
              AND NOT EXISTS (
                  SELECT 1 FROM market_candles newer
                  WHERE newer.source=c.source AND newer.symbol=c.symbol
                    AND newer.timeframe=c.timeframe
                    AND newer.open_time_utc=c.open_time_utc
                    AND newer.revision_index>c.revision_index
              )
            ORDER BY c.open_time_utc ASC
            """
        ).bind(RAW_M1_SOURCE, AIDY_SYMBOL, start.isoformat(), end.isoformat()).all()
        return _results(result)

    async def latest_candle_ids(self) -> dict[str, UUID]:
        result = await self._d1.prepare(
            """
            SELECT c.timeframe,c.id
            FROM market_candles c
            WHERE c.symbol=?
              AND (
                (c.timeframe='1m' AND c.source=?) OR
                (c.timeframe IN ('5m','15m','1h','4h','1d') AND c.source=?)
              )
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
        ).bind(AIDY_SYMBOL, RAW_M1_SOURCE, AGGREGATE_SOURCE).all()
        return {str(row["timeframe"]): UUID(str(row["id"])) for row in _results(result)}

    async def latest_m1_bar(self) -> dict[str, Any] | None:
        value = await self._d1.prepare(
            """
            SELECT c.id,c.open_time_utc,c.open,c.high,c.low,c.close,c.revision_index,
                   c.payload_digest,c.first_observed_at
            FROM market_candles c
            WHERE c.source=? AND c.symbol=? AND c.timeframe='1m'
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
            ORDER BY c.open_time_utc DESC
            LIMIT 1
            """
        ).bind(RAW_M1_SOURCE, AIDY_SYMBOL).first()
        return _row(value)
