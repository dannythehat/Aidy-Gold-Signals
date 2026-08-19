"""Point-in-time broker-free XAU/USD reference-price recorder.

This recorder stores live indicative Gold observations from an independent public
market-data API. Genuine OHLC candles are intentionally not fabricated from
minute snapshots; they remain a separate research/backfill data product.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from uuid import UUID

from .gold_api_gateway import GoldApiGateway, GoldApiReadError
from .market_sessions import session_code_at
from .storage_contracts import AidyMarketRepository

SYMBOL = "XAUUSD"
Clock = Callable[[], datetime]


@dataclass(frozen=True, slots=True)
class ReferenceCaptureResult:
    snapshot_id: UUID | None
    status: str
    market_open: bool
    stored_candles: int = 0


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("AIDY reference capture requires timezone-aware datetimes.")
    return value.astimezone(UTC)


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _digest(value: object) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _session_code(now: datetime) -> str:
    """Compatibility wrapper around the canonical Day 7 session clock."""

    return session_code_at(now)


class AidyReferencePriceRecorderService:
    def __init__(
        self,
        *,
        repository: AidyMarketRepository,
        gateway: GoldApiGateway,
        stale_seconds: float = 300.0,
        clock: Clock = lambda: datetime.now(UTC),
    ) -> None:
        self._repository = repository
        self._gateway = gateway
        self._stale_seconds = max(float(stale_seconds), 30.0)
        self._clock = clock

    async def capture_once(self, *, now: datetime | None = None) -> ReferenceCaptureResult:
        """Capture one observation.

        `now` is an explicit deterministic override for tests/replay. Production
        callers omit it so `captured_at` is stamped only after the upstream read
        finishes: the first moment AIDY could actually know that quote.
        """

        override_time = _utc(now) if now is not None else None
        availability: dict[str, object] = {
            "market_data_source": "gold_api",
            "price_type": "indicative_mid",
            "candles": "separate_research_feed",
            "cross_market": "separate_point_in_time_daily_feed",
            "external_events": "fed_rss_separate_loop",
            "orders": "not_captured_phase0",
        }

        try:
            quote = await self._gateway.read_xau_usd()
        except GoldApiReadError as exc:
            captured_at = override_time or _utc(self._clock())
            availability["quote"] = exc.code
            snapshot_id = await self._store_snapshot(
                captured_at=captured_at,
                status="unavailable",
                price=None,
                quote_time=None,
                quote_age=None,
                availability=availability,
            )
            return ReferenceCaptureResult(snapshot_id, "unavailable", False)

        # Stamp the observation after the HTTP response is available. Using the
        # scheduler's nominal tick here would falsely pre-date the evidence.
        captured_at = override_time or _utc(self._clock())
        price = quote.get("price")
        quote_time = quote.get("observed_at")
        if not isinstance(price, Decimal) or not isinstance(quote_time, datetime):
            availability["quote"] = "gold_api_invalid_normalized_quote"
            snapshot_id = await self._store_snapshot(
                captured_at=captured_at,
                status="unavailable",
                price=None,
                quote_time=None,
                quote_age=None,
                availability=availability,
            )
            return ReferenceCaptureResult(snapshot_id, "unavailable", False)

        quote_time = _utc(quote_time)
        if quote_time > captured_at:
            availability["quote"] = "gold_api_future_timestamp"
            snapshot_id = await self._store_snapshot(
                captured_at=captured_at,
                status="unavailable",
                price=None,
                quote_time=quote_time,
                quote_age=None,
                availability=availability,
            )
            return ReferenceCaptureResult(snapshot_id, "unavailable", False)

        quote_age = (captured_at - quote_time).total_seconds()
        fresh = quote_age <= self._stale_seconds
        availability["quote"] = "available" if fresh else "gold_api_stale_quote"
        availability["market_state"] = "open" if fresh else "closed_or_stale"
        status = "complete" if fresh else "partial"
        snapshot_id = await self._store_snapshot(
            captured_at=captured_at,
            status=status,
            price=price,
            quote_time=quote_time,
            quote_age=quote_age,
            availability=availability,
        )
        return ReferenceCaptureResult(snapshot_id, status, fresh)

    async def _store_snapshot(
        self,
        *,
        captured_at: datetime,
        status: str,
        price: Decimal | None,
        quote_time: datetime | None,
        quote_age: float | None,
        availability: dict[str, object],
    ) -> UUID:
        event_ids = await self._repository.event_observation_ids_known_at(captured_at=captured_at)
        availability["external_events"] = "point_in_time_linked"
        availability["external_event_observation_count"] = len(event_ids)
        snapshot: dict[str, object] = {
            "captured_at": captured_at,
            "symbol": SYMBOL,
            "capture_status": status,
            "bid": None,
            "ask": None,
            "mid": price,
            "spread": None,
            "quote_time": quote_time,
            "quote_age_seconds": quote_age,
            "session_code": _session_code(captured_at),
            "position_state_json": None,
            "data_availability_json": _canonical_json(availability),
            "event_observation_ids_json": _canonical_json([str(item) for item in event_ids]),
            "latest_m1_id": None,
            "latest_m5_id": None,
            "latest_m15_id": None,
            "latest_h1_id": None,
            "latest_h4_id": None,
            "latest_d1_id": None,
        }
        snapshot["snapshot_digest"] = _digest(
            {
                key: str(value) if isinstance(value, (Decimal, datetime, UUID)) else value
                for key, value in snapshot.items()
                if key not in {"captured_at", "snapshot_digest"}
            }
        )
        return await self._repository.store_snapshot(snapshot)
