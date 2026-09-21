from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from aidy.twelve_data_intraday_repair import (
    MAX_AUTO_REPAIR_MINUTES,
    plan_intraday_repair_window,
)
from aidy.twelve_data_market import expected_market_minute_opens, latest_completed_bucket


class FakeStore:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows
        self.calls = 0

    async def latest_m1_bars(self, *, start_utc: datetime, end_utc: datetime):
        self.calls += 1
        return [
            row
            for row in self.rows
            if start_utc <= datetime.fromisoformat(str(row["open_time_utc"])) < end_utc
        ]


def _required_intraday(as_of: datetime) -> list[datetime]:
    required: set[datetime] = set()
    for timeframe in ("5m", "15m", "1h", "4h"):
        start, end = latest_completed_bucket(as_of, timeframe)
        required.update(expected_market_minute_opens(start, end))
    return sorted(required)


@pytest.mark.asyncio
async def test_one_missing_intraday_minute_gets_one_bounded_repair_window() -> None:
    as_of = datetime(2026, 9, 10, 12, 2, tzinfo=UTC)
    required = _required_intraday(as_of)
    missing = datetime(2026, 9, 10, 10, 17, tzinfo=UTC)
    assert missing in required
    store = FakeStore(
        [{"open_time_utc": opened.isoformat()} for opened in required if opened != missing]
    )

    window = await plan_intraday_repair_window(store, as_of=as_of)

    assert window is not None
    assert window.required_opens == frozenset({missing})
    assert window.start_utc == missing
    assert window.end_utc == missing + timedelta(minutes=1)
    assert store.calls == 1


@pytest.mark.asyncio
async def test_large_or_widely_spread_gap_fails_closed_instead_of_burning_quota() -> None:
    as_of = datetime(2026, 9, 10, 12, 2, tzinfo=UTC)
    required = _required_intraday(as_of)
    missing = set(required[: MAX_AUTO_REPAIR_MINUTES + 1])
    store = FakeStore(
        [{"open_time_utc": opened.isoformat()} for opened in required if opened not in missing]
    )

    assert await plan_intraday_repair_window(store, as_of=as_of) is None


@pytest.mark.asyncio
async def test_closed_session_never_launches_repair() -> None:
    as_of = datetime(2026, 9, 13, 12, 0, tzinfo=UTC)
    store = FakeStore([])

    assert await plan_intraday_repair_window(store, as_of=as_of) is None
    assert store.calls == 0


def test_runtime_retries_canonical_capture_only_after_successful_repair() -> None:
    from pathlib import Path

    runtime = (Path(__file__).resolve().parents[1] / "src/aidy/runtime.py").read_text(
        encoding="utf-8"
    )
    assert "repair_intraday_provider_context_gap" in runtime
    assert 'if repair.get("repaired") is True:' in runtime
    assert runtime.count("market = await recorder.capture_once()") == 2
