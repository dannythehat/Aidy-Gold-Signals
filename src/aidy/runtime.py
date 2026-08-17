"""Portable AIDY recorder orchestration.

Cloudflare Workers own production scheduling. This module contains no database
engine creation and no long-running server process; callers inject the portable
storage repository explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from .config import AidySettings
from .fed_recorder import AidyFedRssRecorderService
from .fed_rss import FedRssCaptureResult, FedRssGateway
from .market_recorder import (
    ALL_TIMEFRAMES,
    FAST_TIMEFRAMES,
    AidyMarketRecorderService,
    CaptureResult,
    MetaApiMarketDataConnection,
)
from .metaapi_read_gateway import MetaApiReadGateway
from .storage_contracts import AidyMarketRepository, ArchiveFlushResult


@dataclass(frozen=True, slots=True)
class RecorderCycleResult:
    market: CaptureResult | None
    fed: FedRssCaptureResult | None
    archive: ArchiveFlushResult


def interval_due(now: datetime, interval_seconds: float, *, tick_seconds: int = 60) -> bool:
    """Return whether a periodic task is due on this scheduler tick.

    Worker Cron runs once per minute. AIDY intervals are therefore evaluated on
    deterministic UTC time rather than process memory, so restarts cannot shift
    the slow/Fed cadence.
    """

    if now.tzinfo is None:
        raise ValueError("AIDY scheduler requires a timezone-aware datetime.")
    interval = max(int(interval_seconds), tick_seconds)
    return int(now.astimezone(UTC).timestamp()) % interval < tick_seconds


async def run_capture_cycle(
    settings: AidySettings,
    *,
    repository: AidyMarketRepository,
    now: datetime | None = None,
    timeframes: tuple[str, ...] = ALL_TIMEFRAMES,
    include_market: bool = True,
    include_fed: bool = True,
    market_gateway: MetaApiReadGateway | None = None,
    fed_gateway: FedRssGateway | None = None,
) -> RecorderCycleResult | None:
    """Run one deterministic recorder cycle for a scheduler such as Workers Cron."""

    if not settings.capture_enabled:
        return None
    captured_at = (now or datetime.now(UTC)).astimezone(UTC)
    market: CaptureResult | None = None
    fed: FedRssCaptureResult | None = None

    if include_market:
        market_service = AidyMarketRecorderService(
            connection=MetaApiMarketDataConnection(
                token=settings.metaapi_token,
                account_id=settings.metaapi_account_id,
            ),
            repository=repository,
            gateway=market_gateway or MetaApiReadGateway(),
            market_closed_stale_seconds=settings.market_stale_seconds,
        )
        market = await market_service.capture_once(
            timeframes=timeframes,
            now=captured_at,
        )

    if include_fed:
        fed_service = AidyFedRssRecorderService(
            repository=repository,
            gateway=fed_gateway or FedRssGateway(),
        )
        fed = await fed_service.capture_once(now=captured_at)

    archive = await repository.flush_archive_outbox(limit=settings.archive_flush_limit)
    return RecorderCycleResult(market=market, fed=fed, archive=archive)


async def run_worker_scheduled_cycle(
    settings: AidySettings,
    *,
    repository: AidyMarketRepository,
    scheduled_at: datetime,
) -> RecorderCycleResult:
    """Run the serverless cron plan while always allowing archive retries."""

    scheduled_at = scheduled_at.astimezone(UTC)
    if not settings.capture_enabled:
        archive = await repository.flush_archive_outbox(limit=settings.archive_flush_limit)
        return RecorderCycleResult(market=None, fed=None, archive=archive)

    market_due = interval_due(scheduled_at, settings.market_poll_seconds)
    slow_due = interval_due(scheduled_at, settings.slow_poll_seconds)
    fed_due = interval_due(scheduled_at, settings.fed_rss_poll_seconds)

    if not market_due and not fed_due:
        archive = await repository.flush_archive_outbox(limit=settings.archive_flush_limit)
        return RecorderCycleResult(market=None, fed=None, archive=archive)

    result = await run_capture_cycle(
        settings,
        repository=repository,
        now=scheduled_at,
        timeframes=ALL_TIMEFRAMES if slow_due else FAST_TIMEFRAMES,
        include_market=market_due,
        include_fed=fed_due,
    )
    assert result is not None
    return result
