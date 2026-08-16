from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from .fed_rss import FED_RSS_FEEDS, FedRssCaptureResult, FedRssError, FedRssGateway, parse_fed_rss
from .market_repository import AidyMarketRepository

logger = logging.getLogger(__name__)


class AidyFedRssRecorderService:
    def __init__(self, *, repository: AidyMarketRepository, gateway: FedRssGateway) -> None:
        self._repository = repository
        self._gateway = gateway

    async def capture_once(self, *, now: datetime | None = None) -> FedRssCaptureResult:
        observed_at = (now or datetime.now(UTC)).astimezone(UTC)
        failures = 0
        unchanged = 0
        seen = 0
        added = 0
        for feed_key, url in FED_RSS_FEEDS.items():
            try:
                xml_text = await self._gateway.fetch(feed_key=feed_key, url=url)
                if xml_text is None:
                    unchanged += 1
                    continue
                observations = parse_fed_rss(xml_text, feed_key=feed_key)
            except FedRssError as exc:
                failures += 1
                logger.warning("AIDY Fed RSS capture failed feed=%s code=%s", feed_key, exc)
                continue
            seen += len(observations)
            for observation in observations:
                _, _, created = self._repository.store_event_observation(
                    source=str(observation["source"]),
                    external_id=str(observation["external_id"]),
                    event_type=str(observation["event_type"]),
                    published_at=observation["published_at"],
                    first_observed_at=observed_at,
                    headline=(
                        str(observation["headline"])
                        if observation["headline"] is not None
                        else None
                    ),
                    structured_data_json=str(observation["structured_data_json"]),
                    raw_payload_json=str(observation["raw_payload_json"]),
                    payload_digest=str(observation["payload_digest"]),
                )
                added += int(created)
        return FedRssCaptureResult(
            feeds_checked=len(FED_RSS_FEEDS),
            feeds_failed=failures,
            observations_seen=seen,
            observations_added=added,
            feeds_unchanged=unchanged,
        )


class AidyFedRssRecorderManager:
    def __init__(self, service: AidyFedRssRecorderService, *, poll_seconds: float = 120.0, sleep=asyncio.sleep) -> None:
        self._service = service
        self._poll_seconds = max(float(poll_seconds), 30.0)
        self._sleep = sleep
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="aidy-fed-rss-recorder")

    async def stop(self) -> None:
        task = self._task
        self._task = None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _run(self) -> None:
        while True:
            try:
                await self._service.capture_once(now=datetime.now(UTC))
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("AIDY Fed RSS cycle failed safely")
            await self._sleep(self._poll_seconds)
