from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime

from .bls_calendar_parser import parse_bls_official_calendar
from .fomc_calendar_parser import parse_fomc_calendar
from .official_macro import (
    BEA_CURRENT_RELEASES_URL,
    BEA_SCHEDULE_URL,
    BLS_CALENDAR_URL,
    BLS_RSS_FEEDS,
    OfficialMacroCaptureResult,
    OfficialMacroError,
    OfficialMacroGateway,
    parse_bea_current_releases_html,
    parse_bea_schedule_html,
    parse_bls_release_rss,
    upcoming_fed_calendar_sources,
)
from .storage_contracts import AidyMarketRepository

logger = logging.getLogger(__name__)
Clock = Callable[[], datetime]


class AidyOfficialMacroRecorderService:
    """Capture free official Fed/BLS/BEA macro schedule/release evidence."""

    def __init__(
        self,
        *,
        repository: AidyMarketRepository,
        gateway: OfficialMacroGateway,
        clock: Clock = lambda: datetime.now(UTC),
    ) -> None:
        self._repository = repository
        self._gateway = gateway
        self._clock = clock

    async def capture_once(self, *, now: datetime | None = None) -> OfficialMacroCaptureResult:
        """Capture one bounded official-source cycle.

        `now` is a deterministic test/replay override only. Production callers
        omit it so every first_observed_at is stamped after the corresponding
        HTTP response has actually become available to AIDY.
        """

        override = None
        if now is not None:
            if now.tzinfo is None:
                raise ValueError("Official macro capture override must be timezone-aware.")
            override = now.astimezone(UTC)
        reference = override or self._clock().astimezone(UTC)

        source_specs: list[tuple[str, str, tuple[int, int] | None]] = [
            ("bls_calendar", BLS_CALENDAR_URL, None),
            *((key, url, None) for key, url in BLS_RSS_FEEDS.items()),
            ("bea_schedule", BEA_SCHEDULE_URL, None),
            ("bea_releases", BEA_CURRENT_RELEASES_URL, None),
        ]
        source_specs.extend(
            (key, url, (year, month))
            for key, url, year, month in upcoming_fed_calendar_sources(reference, months=4)
        )

        failures = 0
        unchanged = 0
        seen = 0
        added = 0

        for source_key, url, calendar_period in source_specs:
            try:
                fetched = await self._gateway.fetch(source_key=source_key, url=url)
                if fetched.text is None:
                    unchanged += 1
                    continue
                observed_at = override or self._clock().astimezone(UTC)
                if source_key == "bls_calendar":
                    observations = parse_bls_official_calendar(fetched.text)
                elif source_key in BLS_RSS_FEEDS:
                    observations = parse_bls_release_rss(fetched.text, feed_key=source_key)
                elif source_key == "bea_schedule":
                    observations = parse_bea_schedule_html(fetched.text, year=reference.year)
                elif source_key == "bea_releases":
                    observations = parse_bea_current_releases_html(fetched.text)
                elif source_key.startswith("fed_calendar_") and calendar_period is not None:
                    year, month = calendar_period
                    observations = parse_fomc_calendar(
                        fetched.text,
                        year=year,
                        month=month,
                        source_url=url,
                    )
                else:
                    raise OfficialMacroError("official_macro_parser_not_configured")
            except (OfficialMacroError, ValueError) as exc:
                failures += 1
                logger.warning(
                    "AIDY official macro capture failed source=%s code=%s",
                    source_key,
                    exc,
                )
                continue

            seen += len(observations)
            for observation in observations:
                _, _, created = await self._repository.store_event_observation(
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

        return OfficialMacroCaptureResult(
            sources_checked=len(source_specs),
            sources_failed=failures,
            observations_seen=seen,
            observations_added=added,
            sources_unchanged=unchanged,
        )
