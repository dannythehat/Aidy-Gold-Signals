from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass

ValueGetter = Callable[[str, str], str]


@dataclass(frozen=True, slots=True)
class AidySettings:
    market_data_ownership: str = "public_independent"
    market_data_source: str = "gold_api"
    capture_enabled: bool = False
    market_poll_seconds: float = 60.0
    slow_poll_seconds: float = 300.0
    market_closed_backoff_seconds: float = 900.0
    market_stale_seconds: float = 300.0
    fed_rss_poll_seconds: float = 120.0
    archive_flush_limit: int = 100

    @classmethod
    def _from_getter(cls, getter: ValueGetter) -> AidySettings:
        def optional(name: str) -> str:
            return getter(name, "").strip()

        def positive_float(name: str, default: float) -> float:
            raw = getter(name, str(default)).strip()
            try:
                value = float(raw)
            except ValueError as exc:
                raise RuntimeError(f"Invalid positive float: {name}") from exc
            if value <= 0:
                raise RuntimeError(f"Invalid positive float: {name}")
            return value

        def positive_int(name: str, default: int) -> int:
            raw = getter(name, str(default)).strip()
            try:
                value = int(raw)
            except ValueError as exc:
                raise RuntimeError(f"Invalid positive integer: {name}") from exc
            if value <= 0:
                raise RuntimeError(f"Invalid positive integer: {name}")
            return value

        enabled = optional("AIDY_CAPTURE_ENABLED").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        market_data_ownership = (
            optional("AIDY_MARKET_DATA_OWNERSHIP").lower() or "public_independent"
        )
        market_data_source = optional("AIDY_MARKET_DATA_SOURCE").lower() or "gold_api"

        if enabled:
            if market_data_source != "gold_api":
                raise RuntimeError(
                    "AIDY capture is enabled but the configured market-data source "
                    "does not match the installed broker-free adapter."
                )
            if market_data_ownership != "public_independent":
                raise RuntimeError(
                    "AIDY capture is enabled but market data is not explicitly marked "
                    "public_independent. Broker, MT5, MetaAPI and Super Signals credentials "
                    "are not valid AIDY market-data sources."
                )

        return cls(
            market_data_ownership=market_data_ownership,
            market_data_source=market_data_source,
            capture_enabled=enabled,
            market_poll_seconds=positive_float("AIDY_MARKET_POLL_SECONDS", 60.0),
            slow_poll_seconds=positive_float("AIDY_SLOW_POLL_SECONDS", 300.0),
            market_closed_backoff_seconds=positive_float(
                "AIDY_MARKET_CLOSED_BACKOFF_SECONDS", 900.0
            ),
            market_stale_seconds=positive_float("AIDY_MARKET_STALE_SECONDS", 300.0),
            fed_rss_poll_seconds=positive_float("AIDY_FED_RSS_POLL_SECONDS", 120.0),
            archive_flush_limit=positive_int("AIDY_ARCHIVE_FLUSH_LIMIT", 100),
        )

    @classmethod
    def from_env(cls) -> AidySettings:
        return cls._from_getter(lambda name, default: os.getenv(name, default))

    @classmethod
    def from_worker_env(cls, environment: object) -> AidySettings:
        """Load config from Cloudflare Worker vars without exposing secrets."""

        def getter(name: str, default: str) -> str:
            try:
                value = getattr(environment, name)
            except (AttributeError, TypeError):
                return default
            if value is None:
                return default
            return str(value)

        return cls._from_getter(getter)
