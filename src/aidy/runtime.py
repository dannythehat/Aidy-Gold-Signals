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
from .market_recorder import ALL_TIMEFRAMES, AidyMarketRecorderService, CaptureResult, MetaApiAccount
from .metaapi_read_gateway import MetaApiReadGateway
from .storage_contracts import AidyMarketRepository, ArchiveFlushResult


@dataclass(frozen=True, slots=True)
class RecorderCycleResult:
    market: CaptureResult
    fed: FedRssCaptureResult
    archive: ArchiveFlushResult


async def run_capture_cycle(
    settings: AidySettings,
    *,
    repository: AidyMarketRepository,
    now: datetime | None = None,
    market_gateway: MetaApiReadGateway | None = None,
    fed_gateway: FedRssGateway | None = None,
) -> RecorderCycleResult | None:
    """Run one deterministic recorder cycle for a scheduler such as Workers Cron."""

    if not settings.capture_enabled:
        return None
    captured_at = (now or datetime.now(UTC)).astimezone(UTC)
    market_service = AidyMarketRecorderService(
        account=MetaApiAccount(
            token=settings.metaapi_token,
            account_id=settings.metaapi_account_id,
        ),
        repository=repository,
        gateway=market_gateway or MetaApiReadGateway(),
        market_closed_stale_seconds=settings.market_stale_seconds,
    )
    fed_service = AidyFedRssRecorderService(
        repository=repository,
        gateway=fed_gateway or FedRssGateway(),
    )
    market = await market_service.capture_once(
        timeframes=ALL_TIMEFRAMES,
        now=captured_at,
    )
    fed = await fed_service.capture_once(now=captured_at)
    archive = await repository.flush_archive_outbox(limit=settings.archive_flush_limit)
    return RecorderCycleResult(market=market, fed=fed, archive=archive)
