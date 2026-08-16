from __future__ import annotations

import asyncio
import logging

from .config import AidySettings
from .db import build_session_factory
from .fed_recorder import AidyFedRssRecorderManager, AidyFedRssRecorderService
from .fed_rss import FedRssGateway
from .market_recorder import AidyMarketRecorderManager, AidyMarketRecorderService, MetaApiAccount
from .market_repository import AidyMarketRepository
from .metaapi_read_gateway import MetaApiReadGateway

logger = logging.getLogger(__name__)


async def run_recorder(settings: AidySettings) -> None:
    if not settings.capture_enabled:
        logger.info("AIDY capture is disabled")
        return

    engine, session_factory = build_session_factory(settings.database_url)
    repository = AidyMarketRepository(session_factory)
    market_service = AidyMarketRecorderService(
        account=MetaApiAccount(
            token=settings.metaapi_token,
            account_id=settings.metaapi_account_id,
        ),
        repository=repository,
        gateway=MetaApiReadGateway(),
        market_closed_stale_seconds=settings.market_stale_seconds,
    )
    market_manager = AidyMarketRecorderManager(
        market_service,
        poll_seconds=settings.market_poll_seconds,
        slow_poll_seconds=settings.slow_poll_seconds,
        market_closed_backoff_seconds=settings.market_closed_backoff_seconds,
    )
    fed_manager = AidyFedRssRecorderManager(
        AidyFedRssRecorderService(repository=repository, gateway=FedRssGateway()),
        poll_seconds=settings.fed_rss_poll_seconds,
    )

    await market_manager.start()
    await fed_manager.start()
    try:
        await asyncio.Event().wait()
    finally:
        await fed_manager.stop()
        await market_manager.stop()
        engine.dispose()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_recorder(AidySettings.from_env()))


if __name__ == "__main__":
    main()
