from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from aidy.twelve_data_market import TwelveDataFetch
from aidy.twelve_data_recorder import AidyTwelveDataRecorderService

ROOT = Path(__file__).resolve().parents[1]
REQUEST_ID = UUID("11111111-1111-4111-8111-111111111111")
FETCHED_AT = datetime(2026, 9, 2, 10, 30, tzinfo=UTC)


class _Gateway:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def fetch_1m(self, **kwargs) -> TwelveDataFetch:
        assert kwargs == {"outputsize": 30}
        self.events.append("fetch")
        return TwelveDataFetch(
            fetched_at_utc=FETCHED_AT,
            meta={"symbol": "XAU/USD", "interval": "1min"},
            credit_headers={"api-credits-request": "1"},
            response_digest="a" * 64,
            closed_bars=(),
            raw_bar_count=0,
            forming_bar_count=0,
            off_session_bar_count=0,
            latest_closed_bar_open_utc=None,
            latest_closed_bar_close_utc=None,
            open_session_lag_seconds=None,
            session_open_at_fetch=False,
        )


class _MarketStore:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def reserve_request(self, **kwargs):
        assert kwargs["request_kind"] == "scheduled_capture"
        assert kwargs["outputsize"] == 30
        self.events.append("reserve")
        return REQUEST_ID

    async def finish_request(self, **kwargs) -> None:
        assert kwargs["request_id"] == REQUEST_ID
        assert kwargs["status"] == "succeeded"
        assert kwargs["completed_at"] == FETCHED_AT
        self.events.append("finish")

    async def record_feed_observation(self, fetch: TwelveDataFetch):
        assert fetch.fetched_at_utc == FETCHED_AT
        self.events.append("feed_observation")
        return REQUEST_ID

    async def latest_m1_bars(self, **kwargs):
        return []


class _Repository:
    def __init__(self) -> None:
        self.snapshot = None

    async def event_observation_ids_known_at(self, **kwargs):
        return []

    async def store_snapshot(self, snapshot):
        self.snapshot = snapshot
        return REQUEST_ID

    async def store_candle(self, candle):  # pragma: no cover - no bars in this fixture
        raise AssertionError("No candle should be stored by empty fixture")


@pytest.mark.asyncio
async def test_canonical_recorder_reserves_quota_before_vendor_call() -> None:
    events: list[str] = []
    repository = _Repository()
    result = await AidyTwelveDataRecorderService(
        repository=repository,  # type: ignore[arg-type]
        gateway=_Gateway(events),  # type: ignore[arg-type]
        market_store=_MarketStore(events),  # type: ignore[arg-type]
    ).capture_once()

    assert events[:4] == ["reserve", "fetch", "finish", "feed_observation"]
    assert result.snapshot_id == REQUEST_ID
    assert result.capture_status == "partial"
    assert repository.snapshot is not None
    assert "scheduled_capture" in repository.snapshot["data_availability_json"]
    assert str(REQUEST_ID) in repository.snapshot["data_availability_json"]


def test_decision_admission_view_quarantines_unledgered_and_manual_probe_rows() -> None:
    migration = (
        ROOT / "migrations" / "d1" / "0009_twelve_data_decision_admission.sql"
    ).read_text(encoding="utf-8")
    assert "twelve_data_decision_admitted_m1_v1" in migration
    assert "r.status='succeeded'" in migration
    assert "r.request_kind='scheduled_capture'" in migration
    assert "r.outputsize BETWEEN 1 AND 30" in migration
    assert "r.request_kind='bootstrap'" in migration
    assert "b.state='succeeded'" in migration
    assert "manual_probe" not in migration


def test_storage_reads_canonical_m1_only_through_admission_view() -> None:
    storage = (ROOT / "src" / "aidy" / "twelve_data_storage.py").read_text(encoding="utf-8")
    assert 'DECISION_ADMITTED_M1_VIEW = "twelve_data_decision_admitted_m1_v1"' in storage
    assert storage.count("FROM {DECISION_ADMITTED_M1_VIEW}") >= 3


def test_manual_smoke_cannot_write_canonical_candles_or_run_legacy_bootstrap() -> None:
    entry = (ROOT / "src" / "entry.py").read_text(encoding="utf-8")
    assert "legacy_smoke_bootstrap_disabled" in entry
    assert 'request_kind="manual_probe"' in entry
    assert '"canonical_candles_written": 0' in entry
    assert 'url.path == "/day53/twelve-data-bootstrap"' in entry
    assert "AidyTwelveDataBootstrapService" in entry
