"""PIT-safe Twelve Data XAU/USD recorder using genuine vendor-built M1 OHLC."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from .market_sessions import session_code_at
from .reference_price_recorder import ReferenceCaptureResult
from .storage_contracts import AidyMarketRepository
from .twelve_data_market import (
    AGGREGATE_SOURCE,
    AIDY_SYMBOL,
    MAX_OPEN_SESSION_LAG_SECONDS,
    RAW_M1_SOURCE,
    TWELVE_DATA_SOURCE,
    TwelveDataFetch,
    TwelveDataMarketError,
    TwelveDataOhlcGateway,
    aggregate_m1,
    canonical_json,
    day53_twelve_data_market_manifest,
    digest,
    latest_completed_bucket,
)
from .twelve_data_storage import D1TwelveDataMarketStore

_SNAPSHOT_CANDLE_KEYS = {
    "1m": "latest_m1_id",
    "5m": "latest_m5_id",
    "15m": "latest_m15_id",
    "1h": "latest_h1_id",
    "4h": "latest_h4_id",
    "1d": "latest_d1_id",
}


class TwelveDataGateway(Protocol):
    async def fetch_1m(self, **kwargs) -> TwelveDataFetch: ...


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Twelve Data recorder requires timezone-aware datetimes.")
    return value.astimezone(UTC)


class AidyTwelveDataRecorderService:
    def __init__(
        self,
        *,
        repository: AidyMarketRepository,
        gateway: TwelveDataOhlcGateway | TwelveDataGateway,
        market_store: D1TwelveDataMarketStore,
        recent_outputsize: int = 30,
    ) -> None:
        self._repository = repository
        self._gateway = gateway
        self._market_store = market_store
        self._recent_outputsize = max(10, min(int(recent_outputsize), 5000))

    async def capture_once(self) -> ReferenceCaptureResult:
        try:
            fetch = await self._gateway.fetch_1m(outputsize=self._recent_outputsize)
        except TwelveDataMarketError as exc:
            captured_at = datetime.now(UTC)
            snapshot_id = await self._store_snapshot(
                captured_at=captured_at,
                status="unavailable",
                mid=None,
                quote_time=None,
                quote_age=None,
                availability={
                    "market_data_source": TWELVE_DATA_SOURCE,
                    "market_data_ownership": "public_independent",
                    "quote": exc.code,
                    "candle_source": RAW_M1_SOURCE,
                    "aggregate_source": AGGREGATE_SOURCE,
                    "spread_advisory_state": "unavailable",
                    "spread_missing_blocks": False,
                },
                latest_candle_ids={},
            )
            return ReferenceCaptureResult(snapshot_id, "unavailable", False)

        await self._market_store.record_feed_observation(fetch)
        stored = 0
        for bar in fetch.closed_bars:
            candle = {
                "symbol": AIDY_SYMBOL,
                "timeframe": "1m",
                "open_time_utc": bar.open_time_utc,
                "broker_open_time": None,
                "open": str(bar.open),
                "high": str(bar.high),
                "low": str(bar.low),
                "close": str(bar.close),
                "tick_volume": None,
                "spread": None,
                "volume": None,
                "source": RAW_M1_SOURCE,
                "first_observed_at": fetch.fetched_at_utc,
                "payload_digest": bar.payload_digest,
            }
            _, _, created = await self._repository.store_candle(candle)
            stored += int(created)

        candle_states: dict[str, object] = {}
        for timeframe in ("5m", "15m", "1h", "4h", "1d"):
            start, end = latest_completed_bucket(fetch.fetched_at_utc, timeframe)
            rows = await self._market_store.latest_m1_bars(start_utc=start, end_utc=end)
            candle, state = aggregate_m1(
                rows,
                timeframe=timeframe,
                start_utc=start,
                end_utc=end,
                first_observed_at=fetch.fetched_at_utc,
            )
            candle_states[timeframe] = state
            if candle is None:
                continue
            _, _, created = await self._repository.store_candle(candle)
            stored += int(created)

        latest_ids = await self._market_store.latest_candle_ids()
        latest_m1 = await self._market_store.latest_m1_bar()
        latest_close: Decimal | None = None
        latest_close_time: datetime | None = None
        if latest_m1 is not None:
            latest_close = Decimal(str(latest_m1["close"]))
            raw_open = latest_m1["open_time_utc"]
            if isinstance(raw_open, datetime):
                latest_close_time = _utc(raw_open) + timedelta(minutes=1)
            else:
                parsed = datetime.fromisoformat(str(raw_open))
                if parsed.tzinfo is None:
                    raise ValueError("Stored Twelve Data M1 open time is naive.")
                latest_close_time = parsed.astimezone(UTC) + timedelta(minutes=1)

        all_timeframes_ready = all(key in latest_ids for key in _SNAPSHOT_CANDLE_KEYS)
        fresh = fetch.freshness_state == "fresh"
        status = "complete" if fresh and all_timeframes_ready else "partial"
        availability: dict[str, object] = {
            "market_data_source": TWELVE_DATA_SOURCE,
            "market_data_ownership": "public_independent",
            "quote_type": "latest_closed_vendor_m1_close",
            "candle_source": RAW_M1_SOURCE,
            "aggregate_source": AGGREGATE_SOURCE,
            "adapter_manifest": day53_twelve_data_market_manifest(),
            "provider_meta": fetch.meta,
            "credit_headers": fetch.credit_headers,
            "response_digest": fetch.response_digest,
            "freshness_state": fetch.freshness_state,
            "session_open_at_fetch": fetch.session_open_at_fetch,
            "observed_open_session_lag_seconds": fetch.open_session_lag_seconds,
            "max_open_session_lag_seconds": MAX_OPEN_SESSION_LAG_SECONDS,
            "forming_bar_count_dropped": fetch.forming_bar_count,
            "off_session_bar_count_dropped": fetch.off_session_bar_count,
            "spread_advisory_state": "unavailable",
            "spread_missing_blocks": False,
            "candles": candle_states,
            "all_timeframes_ready": all_timeframes_ready,
            "orders": "not_captured",
        }
        snapshot_id = await self._store_snapshot(
            captured_at=fetch.fetched_at_utc,
            status=status,
            mid=latest_close,
            quote_time=latest_close_time,
            quote_age=fetch.open_session_lag_seconds,
            availability=availability,
            latest_candle_ids=latest_ids,
        )
        return ReferenceCaptureResult(snapshot_id, status, fresh and all_timeframes_ready, stored)

    async def _store_snapshot(
        self,
        *,
        captured_at: datetime,
        status: str,
        mid: Decimal | None,
        quote_time: datetime | None,
        quote_age: float | None,
        availability: dict[str, object],
        latest_candle_ids: dict[str, UUID],
    ) -> UUID:
        captured = _utc(captured_at)
        event_ids = await self._repository.event_observation_ids_known_at(captured_at=captured)
        availability["external_events"] = "point_in_time_linked"
        availability["external_event_observation_count"] = len(event_ids)
        snapshot: dict[str, object] = {
            "captured_at": captured,
            "symbol": AIDY_SYMBOL,
            "capture_status": status,
            "bid": None,
            "ask": None,
            "mid": mid,
            "spread": None,
            "quote_time": quote_time,
            "quote_age_seconds": quote_age,
            "session_code": session_code_at(captured),
            "position_state_json": None,
            "data_availability_json": canonical_json(availability),
            "event_observation_ids_json": canonical_json([str(value) for value in event_ids]),
        }
        for timeframe, field in _SNAPSHOT_CANDLE_KEYS.items():
            snapshot[field] = latest_candle_ids.get(timeframe)
        snapshot["snapshot_digest"] = digest(snapshot)
        return await self._repository.store_snapshot(snapshot)
