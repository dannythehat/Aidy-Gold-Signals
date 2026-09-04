from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from aidy.twelve_data_bootstrap import AidyTwelveDataBootstrapService, BootstrapWindow
from aidy.twelve_data_market import TwelveDataFetch, TwelveDataM1Bar

ROOT = Path(__file__).resolve().parents[1]
FETCHED = datetime(2026, 9, 2, 8, 0, 30, tzinfo=UTC)


def _bar(opened: datetime, value: str = "4320") -> TwelveDataM1Bar:
    base = Decimal(value)
    return TwelveDataM1Bar(
        open_time_utc=opened,
        open=base,
        high=base + Decimal(1),
        low=base - Decimal(1),
        close=base + Decimal("0.25"),
    )


def _fetch(bars: tuple[TwelveDataM1Bar, ...]) -> TwelveDataFetch:
    latest = max(bars, key=lambda item: item.open_time_utc) if bars else None
    latest_close = None if latest is None else latest.close_time_utc
    return TwelveDataFetch(
        fetched_at_utc=FETCHED,
        meta={"symbol": "XAU/USD", "interval": "1min"},
        credit_headers={"api-credits-request": "1", "api-credits-used": "1"},
        response_digest="b" * 64,
        closed_bars=bars,
        raw_bar_count=len(bars),
        forming_bar_count=0,
        off_session_bar_count=0,
        latest_closed_bar_open_utc=None if latest is None else latest.open_time_utc,
        latest_closed_bar_close_utc=latest_close,
        open_session_lag_seconds=None,
        session_open_at_fetch=True,
    )


class FakeGateway:
    def __init__(self, fetch: TwelveDataFetch) -> None:
        self.fetch = fetch

    async def fetch_1m(self, **kwargs):
        del kwargs
        return self.fetch


class FakeRepository:
    def __init__(self, *, fail_on_call: int | None = None) -> None:
        self.candles: list[dict[str, object]] = []
        self.calls = 0
        self.fail_on_call = fail_on_call

    async def store_candle(self, candle):
        self.calls += 1
        if self.fail_on_call == self.calls:
            raise RuntimeError("synthetic_d1_write_failure")
        self.candles.append(dict(candle))
        return uuid4(), 1, True


class FakeStore:
    def __init__(self) -> None:
        self.request_finishes: list[dict[str, object]] = []
        self.window_finishes: list[dict[str, object]] = []
        self.feed_observations = 0

    async def reserve_request(self, **kwargs):
        del kwargs
        return uuid4()

    async def start_bootstrap_window(self, **kwargs):
        del kwargs

    async def finish_request(self, **kwargs):
        self.request_finishes.append(dict(kwargs))

    async def record_feed_observation(self, fetch):
        del fetch
        self.feed_observations += 1

    async def finish_bootstrap_window(self, **kwargs):
        self.window_finishes.append(dict(kwargs))


def _window() -> BootstrapWindow:
    first = datetime(2026, 9, 2, 7, 58, tzinfo=UTC)
    second = datetime(2026, 9, 2, 7, 59, tzinfo=UTC)
    return BootstrapWindow(
        index=3,
        start_utc=first,
        end_utc=datetime(2026, 9, 2, 8, 0, tzinfo=UTC),
        required_opens=frozenset({first, second}),
    )


@pytest.mark.asyncio
async def test_incomplete_vendor_window_makes_zero_canonical_candle_writes() -> None:
    window = _window()
    fetch = _fetch((_bar(window.start_utc),))
    repository = FakeRepository()
    store = FakeStore()

    result = await AidyTwelveDataBootstrapService(
        repository=repository,
        gateway=FakeGateway(fetch),
        store=store,
    ).ingest_window(bootstrap_id=uuid4(), window=window)

    assert result["state"] == "failed"
    assert result["missing_m1_minutes"] == 1
    assert result["persisted_new_m1_minutes"] == 0
    assert repository.candles == []
    assert store.feed_observations == 1
    assert store.window_finishes[-1]["state"] == "failed"
    assert store.window_finishes[-1]["persisted_m1_minutes"] == 0
    assert store.window_finishes[-1]["failure_reason"] == "required_vendor_minutes_missing"


@pytest.mark.asyncio
async def test_interrupted_persistence_marks_bootstrap_window_failed_for_quarantine() -> None:
    window = _window()
    bars = tuple(_bar(opened) for opened in sorted(window.required_opens))
    repository = FakeRepository(fail_on_call=2)
    store = FakeStore()

    with pytest.raises(RuntimeError, match="synthetic_d1_write_failure"):
        await AidyTwelveDataBootstrapService(
            repository=repository,
            gateway=FakeGateway(_fetch(bars)),
            store=store,
        ).ingest_window(bootstrap_id=uuid4(), window=window)

    assert len(repository.candles) == 1
    assert store.window_finishes[-1]["state"] == "failed"
    assert store.window_finishes[-1]["persisted_m1_minutes"] == 1
    assert store.window_finishes[-1]["response_digest"] == "b" * 64
    assert store.window_finishes[-1]["failure_reason"] == "persistence_error:RuntimeError"


def test_m1_read_paths_preserve_decision_admission_semantics() -> None:
    storage = (ROOT / "src" / "aidy" / "twelve_data_storage.py").read_text(encoding="utf-8")
    migration = (
        ROOT / "migrations" / "d1" / "0010_twelve_data_bootstrap_reattestation.sql"
    ).read_text(encoding="utf-8")

    assert 'DECISION_ADMITTED_M1_VIEW = "twelve_data_decision_admitted_m1_v1"' in storage
    assert storage.count("FROM {DECISION_ADMITTED_M1_VIEW}") >= 2

    # The bounded history reader expands the exact two view branches set-wise so
    # bootstrap recovery does not correlate every candle against every old window.
    assert "WITH scheduled AS" in storage
    assert "JOIN twelve_data_request_ledger r ON r.completed_at_utc=c.first_observed_at" in storage
    assert "r.status='succeeded'" in storage
    assert "r.request_kind='scheduled_capture'" in storage
    assert "r.outputsize BETWEEN 1 AND 30" in storage
    assert "FROM twelve_data_bootstrap_requests b" in storage
    assert "JOIN twelve_data_request_ledger r ON r.id=b.request_ledger_id" in storage
    assert "b.state='succeeded'" in storage
    assert "r.request_kind='bootstrap'" in storage
    assert "c.open_time_utc>=b.window_start_utc" in storage
    assert "c.open_time_utc<b.window_end_utc" in storage

    assert "CREATE VIEW twelve_data_decision_admitted_m1_v1" in migration
    assert "r.completed_at_utc=c.first_observed_at" in migration
    assert "r.status='succeeded'" in migration
    assert "r.request_kind='bootstrap'" in migration
    assert "b.state='succeeded'" in migration
    assert "r.request_kind='scheduled_capture'" in migration
