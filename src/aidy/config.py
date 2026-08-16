from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AidySettings:
    database_url: str
    metaapi_token: str
    metaapi_account_id: str
    capture_enabled: bool = False
    market_poll_seconds: float = 60.0
    slow_poll_seconds: float = 300.0
    market_closed_backoff_seconds: float = 900.0
    market_stale_seconds: float = 300.0
    fed_rss_poll_seconds: float = 120.0

    @classmethod
    def from_env(cls) -> "AidySettings":
        def required(name: str) -> str:
            value = os.getenv(name, "").strip()
            if not value:
                raise RuntimeError(f"Missing required environment variable: {name}")
            return value

        def positive_float(name: str, default: float) -> float:
            raw = os.getenv(name, str(default)).strip()
            try:
                value = float(raw)
            except ValueError as exc:
                raise RuntimeError(f"Invalid positive float: {name}") from exc
            if value <= 0:
                raise RuntimeError(f"Invalid positive float: {name}")
            return value

        enabled = os.getenv("AIDY_CAPTURE_ENABLED", "").strip().lower() in {
            "1", "true", "yes", "on"
        }
        return cls(
            database_url=required("AIDY_DATABASE_URL"),
            metaapi_token=required("AIDY_METAAPI_TOKEN"),
            metaapi_account_id=required("AIDY_METAAPI_ACCOUNT_ID"),
            capture_enabled=enabled,
            market_poll_seconds=positive_float("AIDY_MARKET_POLL_SECONDS", 60.0),
            slow_poll_seconds=positive_float("AIDY_SLOW_POLL_SECONDS", 300.0),
            market_closed_backoff_seconds=positive_float(
                "AIDY_MARKET_CLOSED_BACKOFF_SECONDS", 900.0
            ),
            market_stale_seconds=positive_float("AIDY_MARKET_STALE_SECONDS", 300.0),
            fed_rss_poll_seconds=positive_float("AIDY_FED_RSS_POLL_SECONDS", 120.0),
        )
