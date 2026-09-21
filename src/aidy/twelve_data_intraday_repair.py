"""Bounded self-heal for the live Twelve Data intraday evidence stack.

A scheduled capture may be fresh while one older M1 minute is missing from the
latest M5/M15/H1/H4 bucket. Strict 100% completeness is deliberate, so Provider
Context must not simply waive that gap. Instead, this module uses the existing
ledgered bootstrap admission path to repair only a small recent gap that is
already in the past. Nothing here creates a decision snapshot or relaxes PIT
semantics.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from .storage_contracts import AidyMarketRepository
from .twelve_data_bootstrap import AidyTwelveDataBootstrapService, BootstrapWindow
from .twelve_data_market import (
    TwelveDataOhlcGateway,
    expected_market_minute_opens,
    gold_session_is_open,
    latest_completed_bucket,
)
from .twelve_data_storage import D1TwelveDataMarketStore

INTRADAY_REPAIR_VERSION = "aidy_twelve_intraday_self_heal_v1"
_INTRADAY_TIMEFRAMES = ("5m", "15m", "1h", "4h")
MAX_AUTO_REPAIR_MINUTES = 30
MAX_AUTO_REPAIR_SPAN_MINUTES = 30
MAX_AUTO_REPAIR_WINDOWS = 2


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Intraday repair requires timezone-aware datetimes.")
    return value.astimezone(UTC)


async def plan_intraday_repair_windows(
    store: D1TwelveDataMarketStore,
    *,
    as_of: datetime,
) -> tuple[BootstrapWindow, ...]:
    """Return up to two tightly bounded repair windows.

    The total number of missing minutes remains capped. A wider sparse hole may
    be split into at most two requests, each spanning no more than the existing
    30-minute safety boundary.
    """

    observed_at = _utc(as_of)
    if not gold_session_is_open(observed_at):
        return ()

    required: set[datetime] = set()
    for timeframe in _INTRADAY_TIMEFRAMES:
        start, end = latest_completed_bucket(observed_at, timeframe)
        required.update(expected_market_minute_opens(start, end))
    if not required:
        return ()

    start = min(required)
    end = max(required) + timedelta(minutes=1)
    rows = await store.latest_m1_bars(start_utc=start, end_utc=end)
    observed = {
        datetime.fromisoformat(str(row["open_time_utc"])).astimezone(UTC)
        for row in rows
        if row.get("open_time_utc") is not None
    }
    missing = sorted(required - observed)
    if not missing:
        return ()
    if len(missing) > MAX_AUTO_REPAIR_MINUTES:
        return ()

    buckets: list[list[datetime]] = []
    current: list[datetime] = []
    for opened in missing:
        if not current:
            current = [opened]
            continue
        span_minutes = int((opened - current[0]).total_seconds() // 60) + 1
        if span_minutes <= MAX_AUTO_REPAIR_SPAN_MINUTES:
            current.append(opened)
            continue
        buckets.append(current)
        current = [opened]
    if current:
        buckets.append(current)

    if len(buckets) > MAX_AUTO_REPAIR_WINDOWS:
        return ()

    return tuple(
        BootstrapWindow(
            index=index,
            start_utc=bucket[0],
            end_utc=bucket[-1] + timedelta(minutes=1),
            required_opens=frozenset(bucket),
        )
        for index, bucket in enumerate(buckets)
    )


async def plan_intraday_repair_window(
    store: D1TwelveDataMarketStore,
    *,
    as_of: datetime,
) -> BootstrapWindow | None:
    """Backward-compatible single-window planner used by older tests/tools."""

    windows = await plan_intraday_repair_windows(store, as_of=as_of)
    return windows[0] if len(windows) == 1 else None


async def repair_intraday_provider_context_gap(
    *,
    repository: AidyMarketRepository,
    gateway: TwelveDataOhlcGateway,
    store: D1TwelveDataMarketStore,
    as_of: datetime,
) -> dict[str, Any]:
    """Repair one small recent gap through the existing PIT-safe bootstrap ledger."""

    observed_at = _utc(as_of)
    windows = await plan_intraday_repair_windows(store, as_of=observed_at)
    if not windows:
        return {
            "repair_version": INTRADAY_REPAIR_VERSION,
            "attempted": False,
            "repaired": False,
            "reason": "no_bounded_intraday_gap",
        }

    required_minutes = sum(len(window.required_opens) for window in windows)
    bootstrap_id = await store.start_bootstrap(
        started_at=datetime.now(UTC),
        as_of=observed_at,
        planned_windows=len(windows),
        required_m1_minutes=required_minutes,
    )
    service = AidyTwelveDataBootstrapService(
        repository=repository,
        gateway=gateway,
        store=store,
    )
    results: list[dict[str, object]] = []
    for window in windows:
        results.append(
            await service.ingest_window(bootstrap_id=bootstrap_id, window=window)
        )
    complete = await store.finalize_bootstrap(
        bootstrap_id=bootstrap_id,
        completed_at=datetime.now(UTC),
    )
    repaired = bool(
        complete and all(result.get("state") == "succeeded" for result in results)
    )
    return {
        "repair_version": INTRADAY_REPAIR_VERSION,
        "attempted": True,
        "repaired": repaired,
        "required_m1_minutes": required_minutes,
        "repair_window_count": len(windows),
        "window_start_utc": windows[0].start_utc.isoformat(),
        "window_end_utc": windows[-1].end_utc.isoformat(),
        "windows": [
            {
                "index": window.index,
                "start_utc": window.start_utc.isoformat(),
                "end_utc": window.end_utc.isoformat(),
                "required_m1_minutes": len(window.required_opens),
                "state": results[index].get("state"),
            }
            for index, window in enumerate(windows)
        ],
        "bootstrap_id": str(bootstrap_id),
        "state": "succeeded" if repaired else "failed",
    }
