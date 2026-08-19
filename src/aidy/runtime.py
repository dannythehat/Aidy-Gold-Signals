"""Portable AIDY recorder orchestration.

Cloudflare Workers own production scheduling. Live market capture is broker-free:
AIDY reads an indicative XAU/USD reference price and never reads account state.
Genuine OHLC research data is ingested through a separate historical pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from .config import AidySettings
from .fed_recorder import AidyFedRssRecorderService
from .fed_rss import FedRssCaptureResult, FedRssGateway
from .gold_api_gateway import GoldApiGateway
from .reference_price_recorder import AidyReferencePriceRecorderService, ReferenceCaptureResult
from .storage_contracts import AidyMarketRepository, ArchiveFlushResult


@dataclass(frozen=True, slots=True)
class RecorderCycleResult:
    market: ReferenceCaptureResult | None
    fed: FedRssCaptureResult | None
    archive: ArchiveFlushResult


def interval_due(now: datetime, interval_seconds: float, *, tick_seconds: int = 60) -> bool:
    """Return whether a periodic task is due on this scheduler tick."""

    if now.tzinfo is None:
        raise ValueError("AIDY scheduler requires a timezone-aware datetime.")
    interval = max(int(interval_seconds), tick_seconds)
    return int(now.astimezone(UTC).timestamp()) % interval < tick_seconds


async def run_capture_cycle(
    settings: AidySettings,
    *,
    repository: AidyMarketRepository,
    now: datetime | None = None,
    include_market: bool = True,
    include_fed: bool = True,
    market_gateway: GoldApiGateway | None = None,
    fed_gateway: FedRssGateway | None = None,
) -> RecorderCycleResult | None:
    """Run one broker-free recorder cycle.

    `now` represents the scheduler/event evaluation time. Market evidence is
    deliberately stamped by the market recorder after its HTTP response arrives,
    not with this nominal scheduler timestamp.
    """

    if not settings.capture_enabled:
        return None
    cycle_time = (now or datetime.now(UTC)).astimezone(UTC)
    market: ReferenceCaptureResult | None = None
    fed: FedRssCaptureResult | None = None

    if include_market:
        market = await AidyReferencePriceRecorderService(
            repository=repository,
            gateway=market_gateway or GoldApiGateway(),
            stale_seconds=settings.market_stale_seconds,
        ).capture_once()

    if include_fed:
        fed = await AidyFedRssRecorderService(
            repository=repository,
            gateway=fed_gateway or FedRssGateway(),
        ).capture_once(now=cycle_time)

    archive = await repository.flush_archive_outbox(limit=settings.archive_flush_limit)
    return RecorderCycleResult(market=market, fed=fed, archive=archive)


async def run_worker_scheduled_cycle(
    settings: AidySettings,
    *,
    repository: AidyMarketRepository,
    scheduled_at: datetime,
) -> RecorderCycleResult:
    """Run the Cloudflare one-minute plan while always allowing archive retries."""

    scheduled_at = scheduled_at.astimezone(UTC)
    if not settings.capture_enabled:
        archive = await repository.flush_archive_outbox(limit=settings.archive_flush_limit)
        return RecorderCycleResult(market=None, fed=None, archive=archive)

    market_due = interval_due(scheduled_at, settings.market_poll_seconds)
    fed_due = interval_due(scheduled_at, settings.fed_rss_poll_seconds)

    if not market_due and not fed_due:
        archive = await repository.flush_archive_outbox(limit=settings.archive_flush_limit)
        return RecorderCycleResult(market=None, fed=None, archive=archive)

    result = await run_capture_cycle(
        settings,
        repository=repository,
        now=scheduled_at,
        include_market=market_due,
        include_fed=fed_due,
    )
    assert result is not None
    return result
