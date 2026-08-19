from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from .cross_market import CrossMarketError, CrossMarketGateway, CrossMarketObservation
from .storage_contracts import AidyMarketRepository

Clock = Callable[[], datetime]


@dataclass(frozen=True, slots=True)
class CrossMarketCaptureResult:
    sources_checked: int
    sources_failed: int
    observations_seen: int
    observations_added: int


class AidyCrossMarketRecorderService:
    def __init__(
        self,
        *,
        repository: AidyMarketRepository,
        gateway: CrossMarketGateway,
        clock: Clock = lambda: datetime.now(UTC),
    ) -> None:
        self._repository = repository
        self._gateway = gateway
        self._clock = clock

    async def _store(
        self,
        observation: CrossMarketObservation,
        *,
        observed_at: datetime,
    ) -> bool:
        _, _, created = await self._repository.store_cross_market_observation(
            source=observation.source,
            series_id=observation.series_id,
            observation_date=observation.observation_date,
            value=observation.value,
            unit=observation.unit,
            source_url=observation.source_url,
            source_document_digest=observation.source_document_digest,
            first_observed_at=observed_at,
            payload_digest=observation.payload_digest,
        )
        return created

    async def capture_once(self) -> CrossMarketCaptureResult:
        checked = 0
        failed = 0
        seen = 0
        added = 0

        calls = (
            self._gateway.fetch_broad_dollar,
            self._gateway.fetch_treasury_nominal,
            self._gateway.fetch_treasury_real,
        )
        for call in calls:
            checked += 1
            try:
                result = await call()
            except CrossMarketError:
                failed += 1
                continue
            # first_observed_at is stamped only after the HTTP read+parse is available.
            first_observed_at = self._clock().astimezone(UTC)
            observations = result if isinstance(result, list) else [result]
            seen += len(observations)
            for observation in observations:
                added += int(await self._store(observation, observed_at=first_observed_at))

        return CrossMarketCaptureResult(
            sources_checked=checked,
            sources_failed=failed,
            observations_seen=seen,
            observations_added=added,
        )
