"""AIDY point-in-time XAUUSD market recorder.

This recorder captures independent market evidence for AIDY's future reasoning.
It does not read broker positions, publish Telegram messages, or mutate accounts.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Protocol
from uuid import UUID

from .metaapi_read_gateway import MetaApiReadError, MetaApiReadGateway
from .storage_contracts import AidyMarketRepository

logger = logging.getLogger(__name__)

SYMBOL = "XAUUSD"
FAST_TIMEFRAMES = ("1m", "5m")
SLOW_TIMEFRAMES = ("15m", "1h", "4h", "1d")
ALL_TIMEFRAMES = FAST_TIMEFRAMES + SLOW_TIMEFRAMES
_TIMEFRAME_SECONDS = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
}
_CANDLE_LIMITS = {
    "1m": 20,
    "5m": 10,
    "15m": 5,
    "1h": 3,
    "4h": 3,
    "1d": 3,
}
_SNAPSHOT_CANDLE_KEYS = {
    "1m": "latest_m1_id",
    "5m": "latest_m5_id",
    "15m": "latest_m15_id",
    "1h": "latest_h1_id",
    "4h": "latest_h4_id",
    "1d": "latest_d1_id",
}


@dataclass(frozen=True, slots=True)
class MetaApiMarketDataConnection:
    token: str
    account_id: str


@dataclass(frozen=True, slots=True)
class CaptureResult:
    snapshot_id: UUID | None
    status: str
    market_open: bool
    stored_candles: int


class Sleep(Protocol):
    async def __call__(self, delay: float) -> None: ...


class Clock(Protocol):
    def __call__(self) -> datetime: ...


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("AIDY market recorder requires timezone-aware datetimes.")
    return value.astimezone(UTC)


def _parse_utc(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if raw.endswith("Z"):
        raw = f"{raw[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _decimal(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _digest(value: object) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _first_sunday(year: int, month: int) -> datetime:
    first = datetime(year, month, 1, tzinfo=UTC)
    return first + timedelta(days=(6 - first.weekday()) % 7)


def _last_sunday(year: int, month: int) -> datetime:
    if month == 12:
        first_next_month = datetime(year + 1, 1, 1, tzinfo=UTC)
    else:
        first_next_month = datetime(year, month + 1, 1, tzinfo=UTC)
    last = first_next_month - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - 6) % 7)


def _london_utc_offset_hours(now: datetime) -> int:
    """Return London offset without relying on host tzdata.

    AIDY uses the modern UK rule: clocks advance at 01:00 UTC on the last
    Sunday in March and return at 01:00 UTC on the last Sunday in October.
    """

    now = _utc(now)
    start_day = _last_sunday(now.year, 3)
    end_day = _last_sunday(now.year, 10)
    start = start_day.replace(hour=1)
    end = end_day.replace(hour=1)
    return 1 if start <= now < end else 0


def _new_york_utc_offset_hours(now: datetime) -> int:
    """Return New York offset without relying on host tzdata.

    AIDY uses the modern US rule (2007+): DST begins on the second Sunday in
    March at 07:00 UTC and ends on the first Sunday in November at 06:00 UTC.
    The live recorder and current research window are intentionally governed by
    this explicit rule so Cloudflare runtime images cannot change session labels.
    """

    now = _utc(now)
    first_march_sunday = _first_sunday(now.year, 3)
    second_march_sunday = first_march_sunday + timedelta(days=7)
    first_november_sunday = _first_sunday(now.year, 11)
    start = second_march_sunday.replace(hour=7)
    end = first_november_sunday.replace(hour=6)
    return -4 if start <= now < end else -5


def _session_code(now: datetime) -> str:
    now = _utc(now)
    london = now + timedelta(hours=_london_utc_offset_hours(now))
    new_york = now + timedelta(hours=_new_york_utc_offset_hours(now))
    tokyo = now + timedelta(hours=9)
    london_open = 8 <= london.hour < 17 and london.weekday() < 5
    new_york_open = 8 <= new_york.hour < 17 and new_york.weekday() < 5
    tokyo_open = 9 <= tokyo.hour < 18 and tokyo.weekday() < 5
    if london_open and new_york_open:
        return "london_new_york_overlap"
    if london_open:
        return "london"
    if new_york_open:
        return "new_york"
    if tokyo_open:
        return "asia"
    return "off_hours"


def _closed_candle(
    payload: dict[str, object],
    *,
    expected_timeframe: str,
    captured_at: datetime,
) -> dict[str, object] | None:
    if expected_timeframe not in _TIMEFRAME_SECONDS:
        raise ValueError("Unsupported recorder timeframe.")
    open_time = _parse_utc(payload.get("time"))
    if open_time is None:
        return None
    if open_time + timedelta(seconds=_TIMEFRAME_SECONDS[expected_timeframe]) > captured_at:
        return None
    symbol = str(payload.get("symbol") or "")
    timeframe = str(payload.get("timeframe") or "")
    if symbol != SYMBOL or timeframe != expected_timeframe:
        return None
    prices = {key: _decimal(payload.get(key)) for key in ("open", "high", "low", "close")}
    if any(value is None for value in prices.values()):
        return None
    open_price = prices["open"]
    high_price = prices["high"]
    low_price = prices["low"]
    close_price = prices["close"]
    assert open_price is not None and high_price is not None
    assert low_price is not None and close_price is not None
    if (
        high_price < low_price
        or high_price < open_price
        or high_price < close_price
        or low_price > open_price
        or low_price > close_price
    ):
        return None
    evidence = {
        "symbol": symbol,
        "timeframe": timeframe,
        "open_time_utc": open_time.isoformat(),
        "broker_open_time": str(payload.get("brokerTime") or "") or None,
        "open": str(open_price),
        "high": str(high_price),
        "low": str(low_price),
        "close": str(close_price),
        "tick_volume": payload.get("tickVolume"),
        "spread": payload.get("spread"),
        "volume": payload.get("volume"),
        "source": "metaapi",
    }
    return {
        **evidence,
        "open_time_utc": open_time,
        "first_observed_at": captured_at,
        "payload_digest": _digest(evidence),
    }


class AidyMarketRecorderService:
    def __init__(
        self,
        *,
        connection: MetaApiMarketDataConnection,
        repository: AidyMarketRepository,
        gateway: MetaApiReadGateway,
        market_closed_stale_seconds: float = 300.0,
    ) -> None:
        self._connection = connection
        self._repository = repository
        self._gateway = gateway
        self._market_closed_stale_seconds = max(float(market_closed_stale_seconds), 60.0)

    async def capture_once(
        self,
        *,
        timeframes: tuple[str, ...] = ALL_TIMEFRAMES,
        now: datetime | None = None,
    ) -> CaptureResult:
        captured_at = _utc(now or datetime.now(UTC))
        invalid = set(timeframes) - set(ALL_TIMEFRAMES)
        if invalid:
            raise ValueError(f"Unsupported recorder timeframes: {sorted(invalid)}")
        availability: dict[str, object] = {
            "cross_market": "not_configured_phase0",
            "external_events": "fed_rss_separate_loop",
            "orders": "not_captured_phase0",
        }
        try:
            region = await self._gateway.resolve_account_region(
                token=self._connection.token,
                account_id=self._connection.account_id,
            )
        except MetaApiReadError as exc:
            availability["region"] = exc.code
            return CaptureResult(
                await self._store_unavailable(captured_at, availability),
                "unavailable",
                False,
                0,
            )

        async def read(name: str, awaitable: object) -> object | None:
            try:
                value = await awaitable  # type: ignore[misc]
            except MetaApiReadError as exc:
                availability[name] = exc.code
                return None
            availability[name] = "available"
            return value

        quote_payload = await read(
            "quote",
            self._gateway.read_symbol_price(
                token=self._connection.token,
                account_id=self._connection.account_id,
                region=region,
                symbol=SYMBOL,
            ),
        )

        stored_candles = 0
        for timeframe in timeframes:
            payloads = await read(
                f"candles_{timeframe}",
                self._gateway.read_historical_candles(
                    token=self._connection.token,
                    account_id=self._connection.account_id,
                    region=region,
                    symbol=SYMBOL,
                    timeframe=timeframe,
                    limit=_CANDLE_LIMITS[timeframe],
                ),
            )
            if not isinstance(payloads, list):
                continue
            for payload in payloads:
                candle = _closed_candle(
                    payload,
                    expected_timeframe=timeframe,
                    captured_at=captured_at,
                )
                if candle is None:
                    continue
                _, _, created = await self._repository.store_candle(candle)
                stored_candles += int(created)

        quote = quote_payload if isinstance(quote_payload, dict) else {}
        bid = _decimal(quote.get("bid"))
        ask = _decimal(quote.get("ask"))
        quote_time = _parse_utc(quote.get("time"))
        quote_age = (
            max(0.0, (captured_at - quote_time).total_seconds()) if quote_time is not None else None
        )
        market_open = (
            bid is not None
            and ask is not None
            and quote_age is not None
            and quote_age <= self._market_closed_stale_seconds
        )
        availability["market_state"] = "open" if market_open else "closed_or_stale"
        event_ids = await self._repository.event_observation_ids_known_at(captured_at=captured_at)
        availability["external_events"] = "point_in_time_linked"
        availability["external_event_observation_count"] = len(event_ids)
        available_components = sum(1 for value in availability.values() if value == "available")
        expected_components = 1 + len(timeframes)
        status = (
            "complete"
            if available_components == expected_components
            else "partial"
            if available_components > 0
            else "unavailable"
        )
        latest_candle_ids = await self._repository.latest_candle_ids(symbol=SYMBOL)
        candle_ids = {
            column: latest_candle_ids.get(timeframe)
            for timeframe, column in _SNAPSHOT_CANDLE_KEYS.items()
        }
        mid = (bid + ask) / Decimal(2) if bid is not None and ask is not None else None
        spread = ask - bid if bid is not None and ask is not None else None
        snapshot = {
            "captured_at": captured_at,
            "symbol": SYMBOL,
            "capture_status": status,
            "bid": bid,
            "ask": ask,
            "mid": mid,
            "spread": spread,
            "quote_time": quote_time,
            "quote_age_seconds": quote_age,
            "session_code": _session_code(captured_at),
            # Legacy D1 field retained only so Day 2 evidence remains readable.
            # AIDY is a provider and never records follower/broker position state.
            "position_state_json": None,
            "data_availability_json": _canonical_json(availability),
            "event_observation_ids_json": _canonical_json([str(item) for item in event_ids]),
            **candle_ids,
        }
        snapshot["snapshot_digest"] = _digest(
            {
                key: str(value) if isinstance(value, (Decimal, datetime, UUID)) else value
                for key, value in snapshot.items()
                if key not in {"captured_at", "snapshot_digest"}
            }
        )
        snapshot_id = await self._repository.store_snapshot(snapshot)
        return CaptureResult(snapshot_id, status, market_open, stored_candles)

    async def _store_unavailable(
        self, captured_at: datetime, availability: dict[str, object]
    ) -> UUID:
        event_ids = await self._repository.event_observation_ids_known_at(captured_at=captured_at)
        snapshot = {
            "captured_at": captured_at,
            "symbol": SYMBOL,
            "capture_status": "unavailable",
            "bid": None,
            "ask": None,
            "mid": None,
            "spread": None,
            "quote_time": None,
            "quote_age_seconds": None,
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
                key: str(value) if isinstance(value, datetime) else value
                for key, value in snapshot.items()
                if key != "captured_at"
            }
        )
        return await self._repository.store_snapshot(snapshot)


class AidyMarketRecorderManager:
    def __init__(
        self,
        service: AidyMarketRecorderService,
        *,
        poll_seconds: float = 60.0,
        slow_poll_seconds: float = 300.0,
        market_closed_backoff_seconds: float = 900.0,
        sleep: Sleep = asyncio.sleep,
        clock: Clock = lambda: datetime.now(UTC),
    ) -> None:
        self._service = service
        self._clock = clock
        self._poll_seconds = max(float(poll_seconds), 60.0)
        self._slow_poll_seconds = max(float(slow_poll_seconds), self._poll_seconds)
        self._market_closed_backoff_seconds = max(
            float(market_closed_backoff_seconds), self._poll_seconds
        )
        self._sleep = sleep
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="aidy-market-recorder")

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
        last_slow_at: datetime | None = None
        while True:
            started_at = self._clock()
            include_slow = (
                last_slow_at is None
                or (started_at - last_slow_at).total_seconds() >= self._slow_poll_seconds
            )
            timeframes = ALL_TIMEFRAMES if include_slow else FAST_TIMEFRAMES
            if include_slow:
                last_slow_at = started_at
            try:
                result = await self._service.capture_once(timeframes=timeframes, now=started_at)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("AIDY market recorder cycle failed safely")
                delay = self._market_closed_backoff_seconds
            else:
                delay = (
                    self._poll_seconds
                    if result.market_open
                    else self._market_closed_backoff_seconds
                )
            await self._sleep(delay)
