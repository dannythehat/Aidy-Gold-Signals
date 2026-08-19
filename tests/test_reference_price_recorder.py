from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from aidy.reference_price_recorder import AidyReferencePriceRecorderService


class FakeRepository:
    def __init__(self) -> None:
        self.snapshots: list[dict[str, object]] = []

    async def event_observation_ids_known_at(self, *, captured_at: datetime, lookback_hours: int = 24):
        del captured_at, lookback_hours
        return []

    async def store_snapshot(self, snapshot: dict[str, object]) -> UUID:
        self.snapshots.append(snapshot)
        return uuid4()


class FakeGateway:
    def __init__(self, *, price: Decimal, observed_at: datetime) -> None:
        self.price = price
        self.observed_at = observed_at

    async def read_xau_usd(self) -> dict[str, object]:
        return {
            "symbol": "XAUUSD",
            "price": self.price,
            "observed_at": self.observed_at,
            "currency": "USD",
            "source": "gold_api",
        }


@pytest.mark.asyncio
async def test_reference_recorder_stores_fresh_mid_without_fake_bid_ask_or_candles() -> None:
    now = datetime(2026, 8, 19, 9, 25, tzinfo=UTC)
    repository = FakeRepository()
    result = await AidyReferencePriceRecorderService(
        repository=repository,  # type: ignore[arg-type]
        gateway=FakeGateway(price=Decimal("3388.25"), observed_at=now - timedelta(seconds=15)),  # type: ignore[arg-type]
        stale_seconds=300,
    ).capture_once(now=now)

    assert result.status == "complete"
    assert result.market_open is True
    assert result.stored_candles == 0
    snapshot = repository.snapshots[0]
    assert snapshot["mid"] == Decimal("3388.25")
    assert snapshot["bid"] is None
    assert snapshot["ask"] is None
    assert snapshot["spread"] is None
    assert snapshot["latest_m1_id"] is None
    assert snapshot["latest_m5_id"] is None
    assert '"market_data_source":"gold_api"' in str(snapshot["data_availability_json"])
    assert '"candles":"separate_research_feed"' in str(snapshot["data_availability_json"])


@pytest.mark.asyncio
async def test_reference_recorder_marks_stale_quote_partial() -> None:
    now = datetime(2026, 8, 19, 9, 25, tzinfo=UTC)
    repository = FakeRepository()
    result = await AidyReferencePriceRecorderService(
        repository=repository,  # type: ignore[arg-type]
        gateway=FakeGateway(price=Decimal("3388.25"), observed_at=now - timedelta(minutes=10)),  # type: ignore[arg-type]
        stale_seconds=300,
    ).capture_once(now=now)

    assert result.status == "partial"
    assert result.market_open is False
    assert repository.snapshots[0]["quote_age_seconds"] == 600.0
