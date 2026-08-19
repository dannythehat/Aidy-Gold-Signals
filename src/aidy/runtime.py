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
from .official_macro import OfficialMacroCaptureResult, OfficialMacroGateway
from .official_macro_recorder import AidyOfficialMacroRecorderService
from .reference_price_recorder import AidyReferencePriceRecorderService, ReferenceCaptureResult
from .storage_contracts import AidyMarketRepository, ArchiveFlushResult


@dataclass(frozen=True, slots=True)
class RecorderCycleResult:
    market: ReferenceCaptureResult | None
    fed: FedRssCaptureResult | None
    macro: OfficialMacroCaptureResult | None
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
    include_macro: bool = True,
    market_gateway: GoldApiGateway | None = None,
    fed_gateway: FedRssGateway | None = None,
    macro_gateway: OfficialMacroGateway | None = None,
) -> RecorderCycleResult | None:
    """Run one broker-free recorder cycle.

    `now` represents only the scheduler/event evaluation time. Market, Fed and
    official macro first-observed timestamps are deliberately stamped by their
    recorders after upstream HTTP responses arrive, not with this nominal tick.
    """

    if not settings.capture_enabled:
        return None
    _ = (now or datetime.now(UTC)).astimezone(UTC)
    market: ReferenceCaptureResult | None = None
    fed: FedRssCaptureResult | None = None
    macro: OfficialMacroCaptureResult | None = None

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
        ).capture_once()

    if include_macro:
        macro = await AidyOfficialMacroRecorderService(
            repository=repository,
            gateway=macro_gateway or OfficialMacroGateway(),
        ).capture_once()

    archive = await repository.flush_archive_outbox(limit=settings.archive_flush_limit)
    return RecorderCycleResult(market=market, fed=fed, macro=macro, archive=archive)


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
        return RecorderCycleResult(market=None, fed=None, macro=None, archive=archive)

    market_due = interval_due(scheduled_at, settings.market_poll_seconds)
    fed_due = interval_due(scheduled_at, settings.fed_rss_poll_seconds)
    macro_due = interval_due(scheduled_at, settings.macro_poll_seconds)

    if not market_due and not fed_due and not macro_due:
        archive = await repository.flush_archive_outbox(limit=settings.archive_flush_limit)
        return RecorderCycleResult(market=None, fed=None, macro=None, archive=archive)

    result = await run_capture_cycle(
        settings,
        repository=repository,
        now=scheduled_at,
        include_market=market_due,
        include_fed=fed_due,
        include_macro=macro_due,
    )
    assert result is not None
    return result
