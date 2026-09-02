"""D1 helpers for Twelve Data feed envelopes, quotas and bootstrap state."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from .twelve_data_market import AGGREGATE_SOURCE, AIDY_SYMBOL, RAW_M1_SOURCE, TwelveDataFetch

TWELVE_DATA_DAILY_SAFETY_CEILING = 720
TWELVE_DATA_ROLLING_24H_SAFETY_CEILING = 720


class TwelveDataQuotaExceeded(RuntimeError):
    pass


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


def _header_int(headers: dict[str, str], key: str) -> int | None:
    raw = headers.get(key)
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


class D1TwelveDataMarketStore:
    def __init__(self, d1: Any) -> None:
        self._d1 = d1

    async def quota_usage(self, *, now: datetime) -> dict[str, int]:
        observed = _utc(now)
        utc_day_start = observed.replace(hour=0, minute=0, second=0, microsecond=0)
        rolling_start = observed - timedelta(hours=24)
        row = _row(
            await self._d1.prepare(
                """
                SELECT
                  COALESCE(SUM(CASE WHEN requested_at_utc>=? THEN internal_accounted_credits ELSE 0 END),0) AS utc_day,
                  COALESCE(SUM(CASE WHEN requested_at_utc>=? THEN internal_accounted_credits ELSE 0 END),0) AS rolling_24h
                FROM twelve_data_request_ledger
                WHERE requested_at_utc<=?
                """
            ).bind(
                utc_day_start.isoformat(),
                rolling_start.isoformat(),
                observed.isoformat(),
            ).first()
        ) or {}
        return {"utc_day": int(row.get("utc_day") or 0), "rolling_24h": int(row.get("rolling_24h") or 0)}

    async def reserve_request(
        self,
        *,
        requested_at: datetime,
        request_kind: str,
        outputsize: int | None,
        internal_accounted_credits: int = 1,
    ) -> UUID:
        requested = _utc(requested_at)
        credits = max(1, int(internal_accounted_credits))
        usage = await self.quota_usage(now=requested)
        if usage["utc_day"] + credits > TWELVE_DATA_DAILY_SAFETY_CEILING:
            raise TwelveDataQuotaExceeded("twelve_data_utc_day_safety_ceiling")
        if usage["rolling_24h"] + credits > TWELVE_DATA_ROLLING_24H_SAFETY_CEILING:
            raise TwelveDataQuotaExceeded("twelve_data_rolling_24h_safety_ceiling")
        request_id = uuid4()
        await self._d1.prepare(
            """
            INSERT INTO twelve_data_request_ledger (
              id,requested_at_utc,endpoint,symbol,interval,outputsize,request_kind,status,
              internal_accounted_credits
            ) VALUES (?,?,?,?,?,?,?,?,?)
            """
        ).bind(
            str(request_id), requested.isoformat(), "time_series", "XAU/USD", "1min",
            outputsize, request_kind, "started", credits,
        ).run()
        return request_id

    async def finish_request(
        self,
        *,
        request_id: UUID,
        completed_at: datetime,
        status: str,
        fetch: TwelveDataFetch | None = None,
        error_code: str | None = None,
    ) -> None:
        headers = {} if fetch is None else fetch.credit_headers
        await self._d1.prepare(
            """
            UPDATE twelve_data_request_ledger
            SET completed_at_utc=?,status=?,provider_credits_request=?,provider_minute_credits_used=?,
                provider_minute_credits_left=?,response_digest=?,error_code=?
            WHERE id=? AND status='started'
            """
        ).bind(
            _utc(completed_at).isoformat(), status,
            _header_int(headers, "api-credits-request"),
            _header_int(headers, "api-credits-used"),
            _header_int(headers, "api-credits-left"),
            None if fetch is None else fetch.response_digest,
            error_code, str(request_id),
        ).run()

    async def start_bootstrap(
        self,
        *,
        started_at: datetime,
        as_of: datetime,
        planned_windows: int,
        required_m1_minutes: int,
    ) -> UUID:
        bootstrap_id = uuid4()
        await self._d1.prepare(
            """
            INSERT INTO twelve_data_bootstrap_runs (
              id,started_at_utc,as_of_utc,planned_windows,required_m1_minutes,state
            ) VALUES (?,?,?,?,?,'started')
            """
        ).bind(
            str(bootstrap_id), _utc(started_at).isoformat(), _utc(as_of).isoformat(),
            int(planned_windows), int(required_m1_minutes),
        ).run()
        return bootstrap_id

    async def start_bootstrap_window(
        self,
        *,
        bootstrap_id: UUID,
        window_index: int,
        request_id: UUID,
        start_utc: datetime,
        end_utc: datetime,
        required_m1_minutes: int,
    ) -> None:
        await self._d1.prepare(
            "UPDATE twelve_data_bootstrap_runs SET state='ingesting' WHERE id=? AND state='started'"
        ).bind(str(bootstrap_id)).run()
        await self._d1.prepare(
            """
            INSERT INTO twelve_data_bootstrap_requests (
              bootstrap_id,window_index,request_ledger_id,window_start_utc,window_end_utc,
              required_m1_minutes,state
            ) VALUES (?,?,?,?,?,?,'started')
            ON CONFLICT(bootstrap_id,window_index) DO UPDATE SET
              request_ledger_id=excluded.request_ledger_id,
              window_start_utc=excluded.window_start_utc,
              window_end_utc=excluded.window_end_utc,
              required_m1_minutes=excluded.required_m1_minutes,
              state='started',persisted_m1_minutes=0,response_digest=NULL,failure_reason=NULL
            """
        ).bind(
            str(bootstrap_id), int(window_index), str(request_id), _utc(start_utc).isoformat(),
            _utc(end_utc).isoformat(), int(required_m1_minutes),
        ).run()

    async def finish_bootstrap_window(
        self,
        *,
        bootstrap_id: UUID,
        window_index: int,
        state: str,
        persisted_m1_minutes: int,
        response_digest: str | None,
        failure_reason: str | None = None,
    ) -> None:
        await self._d1.prepare(
            """
            UPDATE twelve_data_bootstrap_requests
            SET state=?,persisted_m1_minutes=?,response_digest=?,failure_reason=?
            WHERE bootstrap_id=? AND window_index=?
            """
        ).bind(
            state, int(persisted_m1_minutes), response_digest, failure_reason,
            str(bootstrap_id), int(window_index),
        ).run()

    async def finalize_bootstrap(self, *, bootstrap_id: UUID, completed_at: datetime) -> bool:
        summary = _row(
            await self._d1.prepare(
                """
                SELECT r.planned_windows,
                       COUNT(q.window_index) AS observed_windows,
                       SUM(CASE WHEN q.state='succeeded' THEN 1 ELSE 0 END) AS succeeded_windows,
                       SUM(CASE WHEN q.state='succeeded' THEN q.required_m1_minutes ELSE 0 END) AS covered_minutes
                FROM twelve_data_bootstrap_runs r
                LEFT JOIN twelve_data_bootstrap_requests q ON q.bootstrap_id=r.id
                WHERE r.id=? GROUP BY r.id
                """
            ).bind(str(bootstrap_id)).first()
        ) or {}
        complete = (
            int(summary.get("planned_windows") or 0) > 0
            and int(summary.get("observed_windows") or 0) == int(summary.get("planned_windows") or 0)
            and int(summary.get("succeeded_windows") or 0) == int(summary.get("planned_windows") or 0)
        )
        await self._d1.prepare(
            "UPDATE twelve_data_bootstrap_runs SET state=?,completed_at_utc=? WHERE id=?"
        ).bind("complete" if complete else "failed", _utc(completed_at).isoformat(), str(bootstrap_id)).run()
        return complete

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
            str(observation_id), fetch.fetched_at_utc.isoformat(), "twelve_data", "XAU/USD", "1min",
            json.dumps(fetch.meta, sort_keys=True, separators=(",", ":"), default=str),
            json.dumps(fetch.credit_headers, sort_keys=True, separators=(",", ":")),
            fetch.raw_bar_count, len(fetch.closed_bars), fetch.forming_bar_count, fetch.off_session_bar_count,
            fetch.latest_closed_bar_open_utc.isoformat() if fetch.latest_closed_bar_open_utc else None,
            fetch.latest_closed_bar_close_utc.isoformat() if fetch.latest_closed_bar_close_utc else None,
            fetch.open_session_lag_seconds, 1 if fetch.session_open_at_fetch else 0,
            fetch.freshness_state, fetch.response_digest,
        ).run()
        return observation_id

    async def latest_m1_bars(self, *, start_utc: datetime, end_utc: datetime) -> list[dict[str, Any]]:
        result = await self._d1.prepare(
            """
            WITH admitted AS (
              SELECT c.*
              FROM market_candles c
              WHERE c.source=? AND c.symbol=? AND c.timeframe='1m'
                AND c.open_time_utc>=? AND c.open_time_utc<?
                AND NOT EXISTS (
                  SELECT 1
                  FROM twelve_data_bootstrap_requests b
                  JOIN twelve_data_request_ledger r ON r.id=b.request_ledger_id
                  WHERE r.completed_at_utc=c.first_observed_at
                    AND c.open_time_utc>=b.window_start_utc
                    AND c.open_time_utc<b.window_end_utc
                    AND b.state<>'succeeded'
                )
            )
            SELECT c.id,c.open_time_utc,c.open,c.high,c.low,c.close,c.revision_index,c.payload_digest,c.first_observed_at
            FROM admitted c
            WHERE NOT EXISTS (
              SELECT 1 FROM admitted newer
              WHERE newer.source=c.source AND newer.symbol=c.symbol
                AND newer.timeframe=c.timeframe AND newer.open_time_utc=c.open_time_utc
                AND newer.revision_index>c.revision_index
            )
            ORDER BY c.open_time_utc ASC
            """
        ).bind(RAW_M1_SOURCE, AIDY_SYMBOL, _utc(start_utc).isoformat(), _utc(end_utc).isoformat()).all()
        return _results(result)

    async def latest_candle_ids(self) -> dict[str, UUID]:
        result = await self._d1.prepare(
            """
            WITH admitted_m1 AS (
              SELECT c.*
              FROM market_candles c
              WHERE c.symbol=? AND c.timeframe='1m' AND c.source=?
                AND NOT EXISTS (
                  SELECT 1
                  FROM twelve_data_bootstrap_requests b
                  JOIN twelve_data_request_ledger r ON r.id=b.request_ledger_id
                  WHERE r.completed_at_utc=c.first_observed_at
                    AND c.open_time_utc>=b.window_start_utc
                    AND c.open_time_utc<b.window_end_utc
                    AND b.state<>'succeeded'
                )
            ), latest_m1 AS (
              SELECT timeframe,id FROM admitted_m1
              ORDER BY open_time_utc DESC,revision_index DESC LIMIT 1
            ), latest_aggregates AS (
              SELECT c.timeframe,c.id FROM market_candles c
              WHERE c.symbol=? AND c.timeframe IN ('5m','15m','1h','4h','1d') AND c.source=?
                AND NOT EXISTS (
                  SELECT 1 FROM market_candles newer
                  WHERE newer.source=c.source AND newer.symbol=c.symbol
                    AND newer.timeframe=c.timeframe AND (newer.open_time_utc>c.open_time_utc OR
                    (newer.open_time_utc=c.open_time_utc AND newer.revision_index>c.revision_index))
                )
            )
            SELECT timeframe,id FROM latest_m1
            UNION ALL
            SELECT timeframe,id FROM latest_aggregates
            ORDER BY timeframe
            """
        ).bind(AIDY_SYMBOL, RAW_M1_SOURCE, AIDY_SYMBOL, AGGREGATE_SOURCE).all()
        return {str(row["timeframe"]): UUID(str(row["id"])) for row in _results(result)}

    async def latest_m1_bar(self) -> dict[str, Any] | None:
        value = await self._d1.prepare(
            """
            WITH admitted AS (
              SELECT c.*
              FROM market_candles c
              WHERE c.source=? AND c.symbol=? AND c.timeframe='1m'
                AND NOT EXISTS (
                  SELECT 1
                  FROM twelve_data_bootstrap_requests b
                  JOIN twelve_data_request_ledger r ON r.id=b.request_ledger_id
                  WHERE r.completed_at_utc=c.first_observed_at
                    AND c.open_time_utc>=b.window_start_utc
                    AND c.open_time_utc<b.window_end_utc
                    AND b.state<>'succeeded'
                )
            )
            SELECT c.id,c.open_time_utc,c.open,c.high,c.low,c.close,c.revision_index,c.payload_digest,c.first_observed_at
            FROM admitted c
            ORDER BY c.open_time_utc DESC,c.revision_index DESC LIMIT 1
            """
        ).bind(RAW_M1_SOURCE, AIDY_SYMBOL).first()
        return _row(value)
