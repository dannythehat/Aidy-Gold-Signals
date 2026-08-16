from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable


ValueGetter = Callable[[str, str], str]


@dataclass(frozen=True, slots=True)
class AidySettings:
    metaapi_token: str
    metaapi_account_id: str
    capture_enabled: bool = False
    market_poll_seconds: float = 60.0
    slow_poll_seconds: float = 300.0
    market_closed_backoff_seconds: float = 900.0
    market_stale_seconds: float = 300.0
    fed_rss_poll_seconds: float = 120.0
    archive_flush_limit: int = 100

    @classmethod
    def _from_getter(cls, getter: ValueGetter) -> "AidySettings":
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
        metaapi_token = optional("AIDY_METAAPI_TOKEN")
        metaapi_account_id = optional("AIDY_METAAPI_ACCOUNT_ID")

        if enabled:
            required = {
                "AIDY_METAAPI_TOKEN": metaapi_token,
                "AIDY_METAAPI_ACCOUNT_ID": metaapi_account_id,
            }
            missing = [name for name, value in required.items() if not value]
            if missing:
                raise RuntimeError(
                    "AIDY capture is enabled but required environment variables are missing: "
                    + ", ".join(missing)
                )

        return cls(
            metaapi_token=metaapi_token,
            metaapi_account_id=metaapi_account_id,
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
    def from_env(cls) -> "AidySettings":
        return cls._from_getter(lambda name, default: os.getenv(name, default))

    @classmethod
    def from_worker_env(cls, environment: object) -> "AidySettings":
        """Load config from Cloudflare Worker vars/secrets without exposing them."""

        def getter(name: str, default: str) -> str:
            try:
                value = getattr(environment, name)
            except (AttributeError, TypeError):
                return default
            if value is None:
                return default
            return str(value)

        return cls._from_getter(getter)
