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


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Intraday repair requires timezone-aware datetimes.")
    return value.astimezone(UTC)


async def plan_intraday_repair_window(
    store: D1TwelveDataMarketStore,
    *,
    as_of: datetime,
) -> BootstrapWindow | None:
    """Return one tightly bounded repair window or None.

    Only minutes needed by the latest completed M5/M15/H1/H4 buckets are
    considered. D1 is intentionally excluded because Provider Context already
    has an explicit observational-only D1-missing state.
    """

    observed_at = _utc(as_of)
    if not gold_session_is_open(observed_at):
        return None

    required: set[datetime] = set()
    for timeframe in _INTRADAY_TIMEFRAMES:
        start, end = latest_completed_bucket(observed_at, timeframe)
        required.update(expected_market_minute_opens(start, end))
    if not required:
        return None

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
        return None

    span_minutes = int((missing[-1] - missing[0]).total_seconds() // 60) + 1
    if len(missing) > MAX_AUTO_REPAIR_MINUTES or span_minutes > MAX_AUTO_REPAIR_SPAN_MINUTES:
        return None

    return BootstrapWindow(
        index=0,
        start_utc=missing[0],
        end_utc=missing[-1] + timedelta(minutes=1),
        required_opens=frozenset(missing),
    )


async def repair_intraday_provider_context_gap(
    *,
    repository: AidyMarketRepository,
    gateway: TwelveDataOhlcGateway,
    store: D1TwelveDataMarketStore,
    as_of: datetime,
) -> dict[str, Any]:
    """Repair one small recent gap through the existing PIT-safe bootstrap ledger."""

    observed_at = _utc(as_of)
    window = await plan_intraday_repair_window(store, as_of=observed_at)
    if window is None:
        return {
            "repair_version": INTRADAY_REPAIR_VERSION,
            "attempted": False,
            "repaired": False,
            "reason": "no_bounded_intraday_gap",
        }

    bootstrap_id = await store.start_bootstrap(
        started_at=datetime.now(UTC),
        as_of=observed_at,
        planned_windows=1,
        required_m1_minutes=len(window.required_opens),
    )
    service = AidyTwelveDataBootstrapService(
        repository=repository,
        gateway=gateway,
        store=store,
    )
    result = await service.ingest_window(bootstrap_id=bootstrap_id, window=window)
    complete = await store.finalize_bootstrap(
        bootstrap_id=bootstrap_id,
        completed_at=datetime.now(UTC),
    )
    repaired = bool(complete and result.get("state") == "succeeded")
    return {
        "repair_version": INTRADAY_REPAIR_VERSION,
        "attempted": True,
        "repaired": repaired,
        "required_m1_minutes": len(window.required_opens),
        "window_start_utc": window.start_utc.isoformat(),
        "window_end_utc": window.end_utc.isoformat(),
        "bootstrap_id": str(bootstrap_id),
        "state": result.get("state"),
    }
