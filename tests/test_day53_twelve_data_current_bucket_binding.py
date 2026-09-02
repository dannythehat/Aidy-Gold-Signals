from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import NAMESPACE_URL, uuid5

import pytest

from aidy.twelve_data_market import TwelveDataFetch, TwelveDataM1Bar, latest_completed_bucket
from aidy.twelve_data_recorder import (
    AidyTwelveDataRecorderService,
    bootstrap_required_m1_open_times,
)

FETCHED = datetime(2026, 9, 2, 5, 30, 40, tzinfo=UTC)


def _bar(opened: datetime, value: str = "4320") -> TwelveDataM1Bar:
    base = Decimal(value)
    return TwelveDataM1Bar(
        open_time_utc=opened,
        open=base,
        high=base + Decimal("1"),
        low=base - Decimal("1"),
        close=base + Decimal("0.25"),
    )


def _fetch(bars: tuple[TwelveDataM1Bar, ...]) -> TwelveDataFetch:
    latest = max(bars, key=lambda item: item.open_time_utc) if bars else None
    latest_close = None if latest is None else latest.close_time_utc
    return TwelveDataFetch(
        fetched_at_utc=FETCHED,
        meta={"symbol": "XAU/USD", "interval": "1min"},
        credit_headers={
            "api-credits-request": "1",
            "api-credits-used": "1",
            "api-credits-left": "7",
        },
        response_digest="a" * 64,
        closed_bars=bars,
        raw_bar_count=len(bars),
        forming_bar_count=0,
        off_session_bar_count=0,
        latest_closed_bar_open_utc=None if latest is None else latest.open_time_utc,
        latest_closed_bar_close_utc=latest_close,
        open_session_lag_seconds=(
            None if latest_close is None else (FETCHED - latest_close).total_seconds()
        ),
        session_open_at_fetch=True,
    )


class FakeGateway:
    def __init__(self, fetch: TwelveDataFetch) -> None:
        self.fetch = fetch
        self.outputsize = None

    async def fetch_1m(self, **kwargs):
        self.outputsize = kwargs.get("outputsize")
        return self.fetch


class FakeRepository:
    def __init__(self) -> None:
        self.candles: list[dict[str, object]] = []
        self.snapshots: list[dict[str, object]] = []

    async def store_candle(self, candle):
        payload = dict(candle)
        self.candles.append(payload)
        identity = uuid5(
            NAMESPACE_URL,
            f"{payload['source']}|{payload['timeframe']}|{payload['open_time_utc']}|{payload['payload_digest']}",
        )
        return identity, 1, True

    async def event_observation_ids_known_at(self, *, captured_at, lookback_hours=24):
        del captured_at, lookback_hours
        return []

    async def store_snapshot(self, snapshot):
        payload = dict(snapshot)
        self.snapshots.append(payload)
        return uuid5(NAMESPACE_URL, str(payload["snapshot_digest"]))


class IncompleteCurrentStore:
    """Pretend old complete aggregates exist while current buckets are incomplete."""

    def __init__(self) -> None:
        self.feed_observations = 0

    async def record_feed_observation(self, fetch):
        del fetch
        self.feed_observations += 1

    async def latest_m1_bars(self, *, start_utc, end_utc):
        del start_utc, end_utc
        return []

    async def latest_candle_ids(self):
        raise AssertionError("Current snapshot must never fall back to stale latest candle IDs.")


@pytest.mark.asyncio
async def test_stale_old_aggregate_ids_cannot_make_current_snapshot_complete() -> None:
    latest = _bar(datetime(2026, 9, 2, 5, 29, tzinfo=UTC))
    gateway = FakeGateway(_fetch((latest,)))
    repository = FakeRepository()
    store = IncompleteCurrentStore()

    result = await AidyTwelveDataRecorderService(
        repository=repository,
        gateway=gateway,
        market_store=store,
    ).capture_once()

    assert result.status == "partial"
    assert store.feed_observations == 1
    snapshot = repository.snapshots[-1]
    assert snapshot["latest_m1_id"] is not None
    for field in ("latest_m5_id", "latest_m15_id", "latest_h1_id", "latest_h4_id", "latest_d1_id"):
        assert snapshot[field] is None


@pytest.mark.asyncio
async def test_current_snapshot_m1_id_is_from_current_vendor_fetch_not_prior_storage() -> None:
    latest = _bar(datetime(2026, 9, 2, 5, 29, tzinfo=UTC), "4330")
    gateway = FakeGateway(_fetch((latest,)))
    repository = FakeRepository()

    result = await AidyTwelveDataRecorderService(
        repository=repository,
        gateway=gateway,
        market_store=IncompleteCurrentStore(),
    ).capture_once()

    snapshot = repository.snapshots[-1]
    raw = next(candle for candle in repository.candles if candle["timeframe"] == "1m")
    expected_id = uuid5(
        NAMESPACE_URL,
        f"{raw['source']}|{raw['timeframe']}|{raw['open_time_utc']}|{raw['payload_digest']}",
    )
    assert snapshot["latest_m1_id"] == expected_id
    assert result.status == "partial"


def test_bootstrap_required_union_reaches_previous_completed_d1_without_storing_5000_rows() -> None:
    latest_m1 = datetime(2026, 9, 2, 5, 29, tzinfo=UTC)
    required = bootstrap_required_m1_open_times(FETCHED, latest_m1_open_utc=latest_m1)
    d1_start, d1_end = latest_completed_bucket(FETCHED, "1d")

    assert latest_m1 in required
    assert d1_start in required
    assert d1_end - timedelta(minutes=1) in required
    assert len(required) < 2000
    assert len(required) < 5000


def test_bootstrap_fetch_capacity_exceeds_required_union_by_large_margin() -> None:
    required = bootstrap_required_m1_open_times(
        FETCHED,
        latest_m1_open_utc=datetime(2026, 9, 2, 5, 29, tzinfo=UTC),
    )
    assert 1000 < len(required) < 2000
    assert 5000 - len(required) > 3000
