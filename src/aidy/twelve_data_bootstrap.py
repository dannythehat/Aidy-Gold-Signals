"""Bounded administrative Twelve Data history ingest; never creates decision snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from .storage_contracts import AidyMarketRepository
from .twelve_data_market import AIDY_SYMBOL, RAW_M1_SOURCE, TwelveDataOhlcGateway, expected_market_minute_opens
from .twelve_data_recorder import bootstrap_required_m1_open_times
from .twelve_data_storage import D1TwelveDataMarketStore

MAX_BOOTSTRAP_WINDOW_MINUTES = 120


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Bootstrap timestamps must be timezone-aware.")
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class BootstrapWindow:
    index: int
    start_utc: datetime
    end_utc: datetime
    required_opens: frozenset[datetime]


def plan_bootstrap_windows(as_of: datetime, *, latest_m1_open_utc: datetime) -> tuple[BootstrapWindow, ...]:
    required = sorted(bootstrap_required_m1_open_times(_utc(as_of), latest_m1_open_utc=_utc(latest_m1_open_utc)))
    if not required:
        return ()
    windows: list[BootstrapWindow] = []
    bucket: list[datetime] = [required[0]]
    for opened in required[1:]:
        if opened - bucket[-1] == timedelta(minutes=1) and len(bucket) < MAX_BOOTSTRAP_WINDOW_MINUTES:
            bucket.append(opened)
            continue
        windows.append(BootstrapWindow(len(windows), bucket[0], bucket[-1] + timedelta(minutes=1), frozenset(bucket)))
        bucket = [opened]
    windows.append(BootstrapWindow(len(windows), bucket[0], bucket[-1] + timedelta(minutes=1), frozenset(bucket)))
    return tuple(windows)


class AidyTwelveDataBootstrapService:
    """Ingest exactly one bounded window. Completion is separate from live readiness."""

    def __init__(self, *, repository: AidyMarketRepository, gateway: TwelveDataOhlcGateway, store: D1TwelveDataMarketStore) -> None:
        self._repository = repository
        self._gateway = gateway
        self._store = store

    async def ingest_window(self, *, bootstrap_id: UUID, window: BootstrapWindow) -> dict[str, object]:
        requested_at = datetime.now(UTC)
        request_id = await self._store.reserve_request(
            requested_at=requested_at, request_kind="bootstrap", outputsize=None
        )
        await self._store.start_bootstrap_window(
            bootstrap_id=bootstrap_id,
            window_index=window.index,
            request_id=request_id,
            start_utc=window.start_utc,
            end_utc=window.end_utc,
            required_m1_minutes=len(window.required_opens),
        )
        try:
            fetch = await self._gateway.fetch_1m(start_date=window.start_utc, end_date=window.end_utc)
        except Exception as exc:
            await self._store.finish_request(
                request_id=request_id, completed_at=datetime.now(UTC), status="failed", error_code=type(exc).__name__
            )
            await self._store.finish_bootstrap_window(
                bootstrap_id=bootstrap_id, window_index=window.index, state="failed",
                persisted_m1_minutes=0, response_digest=None, failure_reason=type(exc).__name__,
            )
            raise
        await self._store.finish_request(
            request_id=request_id, completed_at=fetch.fetched_at_utc, status="succeeded", fetch=fetch
        )
        await self._store.record_feed_observation(fetch)
        by_open = {bar.open_time_utc: bar for bar in fetch.closed_bars}
        missing = window.required_opens - set(by_open)
        if missing:
            await self._store.finish_bootstrap_window(
                bootstrap_id=bootstrap_id, window_index=window.index, state="failed",
                persisted_m1_minutes=0, response_digest=fetch.response_digest,
                failure_reason="required_vendor_minutes_missing",
            )
            return {
                "bootstrap_id": str(bootstrap_id), "window_index": window.index,
                "required_m1_minutes": len(window.required_opens), "missing_m1_minutes": len(missing),
                "persisted_new_m1_minutes": 0, "state": "failed",
                "decision_snapshot_created": False, "decision_ready": False,
            }

        persisted = 0
        try:
            for opened in sorted(window.required_opens):
                bar = by_open[opened]
                _, _, created = await self._repository.store_candle({
                    "symbol": AIDY_SYMBOL, "timeframe": "1m", "open_time_utc": bar.open_time_utc,
                    "broker_open_time": None, "open": str(bar.open), "high": str(bar.high),
                    "low": str(bar.low), "close": str(bar.close), "tick_volume": None,
                    "spread": None, "volume": None, "source": RAW_M1_SOURCE,
                    "first_observed_at": fetch.fetched_at_utc, "payload_digest": bar.payload_digest,
                })
                persisted += int(created)
        except Exception as exc:
            await self._store.finish_bootstrap_window(
                bootstrap_id=bootstrap_id, window_index=window.index, state="failed",
                persisted_m1_minutes=persisted, response_digest=fetch.response_digest,
                failure_reason=f"persistence_error:{type(exc).__name__}",
            )
            raise

        await self._store.finish_bootstrap_window(
            bootstrap_id=bootstrap_id, window_index=window.index, state="succeeded",
            persisted_m1_minutes=persisted, response_digest=fetch.response_digest,
            failure_reason=None,
        )
        return {
            "bootstrap_id": str(bootstrap_id), "window_index": window.index,
            "required_m1_minutes": len(window.required_opens), "missing_m1_minutes": 0,
            "persisted_new_m1_minutes": persisted, "state": "succeeded",
            "decision_snapshot_created": False, "decision_ready": False,
        }