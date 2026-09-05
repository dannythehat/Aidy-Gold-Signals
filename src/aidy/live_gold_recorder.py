"""PIT-safe live XAUUSD bid/ask recorder and quote-derived candle builder."""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Any, Protocol
from uuid import UUID

from .argentapi_gateway import ARGENT_API_SOURCE, ArgentApiReadError
from .market_sessions import session_code_at
from .reference_price_recorder import ReferenceCaptureResult
from .storage_contracts import AidyMarketRepository

SYMBOL = "XAUUSD"
CANDLE_SOURCE = "argentapi_quote_rollup_v1"
CANDLE_DERIVATION_VERSION = "aidy_live_sampled_mid_ohlc_v1"
MIN_COVERAGE_RATIO = Decimal("0.90")
_TIMEFRAME_SECONDS = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
}
_SNAPSHOT_CANDLE_KEYS = {
    "1m": "latest_m1_id",
    "5m": "latest_m5_id",
    "15m": "latest_m15_id",
    "1h": "latest_h1_id",
    "4h": "latest_h4_id",
    "1d": "latest_d1_id",
}
Clock = Callable[[], datetime]


class LiveGoldGateway(Protocol):
    async def read_xau_usd(self) -> dict[str, object]: ...


class LiveGoldQuoteHistory(Protocol):
    async def quote_observations(
        self,
        *,
        symbol: str,
        source: str,
        start_utc: datetime,
        end_utc: datetime,
    ) -> list[dict[str, Any]]: ...

    async def latest_candle_ids(self, *, symbol: str, source: str) -> dict[str, UUID]: ...

    async def candle_id_for_bucket(
        self,
        *,
        symbol: str,
        source: str,
        timeframe: str,
        open_time_utc: datetime,
    ) -> UUID | None: ...


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Live Gold recorder requires timezone-aware datetimes.")
    return value.astimezone(UTC)


def _parse_utc(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return _utc(value)
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if raw.endswith("Z"):
        raw = f"{raw[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return _utc(parsed) if parsed.tzinfo is not None else None


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


def _closed_bucket(now: datetime, timeframe: str) -> tuple[datetime, datetime]:
    seconds = _TIMEFRAME_SECONDS[timeframe]
    epoch = int(_utc(now).timestamp())
    end_epoch = epoch - (epoch % seconds)
    end = datetime.fromtimestamp(end_epoch, tz=UTC)
    return end - timedelta(seconds=seconds), end


def _minimum_samples(timeframe: str) -> int:
    expected = _TIMEFRAME_SECONDS[timeframe] // 60
    if expected == 1:
        return 1
    return math.ceil(expected * float(MIN_COVERAGE_RATIO))


def _sampled_candle(
    observations: list[dict[str, Any]],
    *,
    timeframe: str,
    start_utc: datetime,
    end_utc: datetime,
    first_observed_at: datetime,
) -> tuple[dict[str, object] | None, dict[str, object]]:
    per_minute: dict[int, tuple[datetime, Decimal, Decimal, str]] = {}
    for row in observations:
        quote_time = _parse_utc(row.get("quote_time"))
        mid = _decimal(row.get("mid"))
        spread = _decimal(row.get("spread"))
        if quote_time is None or mid is None or spread is None or mid <= 0 or spread < 0:
            continue
        if quote_time < start_utc or quote_time >= end_utc:
            continue
        minute = int(quote_time.timestamp()) // 60
        identity = str(row.get("snapshot_digest") or row.get("id") or "")
        per_minute[minute] = (quote_time, mid, spread, identity)

    samples = sorted(per_minute.values(), key=lambda item: item[0])
    expected = _TIMEFRAME_SECONDS[timeframe] // 60
    minimum = _minimum_samples(timeframe)
    coverage = len(samples) / expected
    state: dict[str, object] = {
        "timeframe": timeframe,
        "bucket_start_utc": start_utc.isoformat(),
        "bucket_end_utc": end_utc.isoformat(),
        "observed_minute_samples": len(samples),
        "expected_minute_samples": expected,
        "minimum_required_samples": minimum,
        "coverage_ratio": round(coverage, 6),
        "derivation_version": CANDLE_DERIVATION_VERSION,
        "price_basis": "observed_mid",
    }
    if len(samples) < minimum:
        state["state"] = "insufficient_live_coverage"
        return None, state

    mids = [item[1] for item in samples]
    closes_spread = samples[-1][2]
    lineage = [item[3] for item in samples]
    evidence = {
        "symbol": SYMBOL,
        "timeframe": timeframe,
        "open_time_utc": start_utc.isoformat(),
        "open": str(mids[0]),
        "high": str(max(mids)),
        "low": str(min(mids)),
        "close": str(mids[-1]),
        "spread": str(closes_spread),
        "source": CANDLE_SOURCE,
        "derivation_version": CANDLE_DERIVATION_VERSION,
        "price_basis": "observed_mid",
        "input_snapshot_identities": lineage,
        "coverage_ratio": state["coverage_ratio"],
    }
    candle: dict[str, object] = {
        "symbol": SYMBOL,
        "timeframe": timeframe,
        "open_time_utc": start_utc,
        "broker_open_time": None,
        "open": evidence["open"],
        "high": evidence["high"],
        "low": evidence["low"],
        "close": evidence["close"],
        "tick_volume": len(samples),
        "spread": evidence["spread"],
        "volume": None,
        "source": CANDLE_SOURCE,
        "first_observed_at": first_observed_at,
        "payload_digest": _digest(evidence),
    }
    state["state"] = "closed_bucket_materialized"
    state["payload_digest"] = candle["payload_digest"]
    return candle, state


class AidyLiveGoldRecorderService:
    def __init__(
        self,
        *,
        repository: AidyMarketRepository,
        gateway: LiveGoldGateway,
        quote_history: LiveGoldQuoteHistory,
        stale_seconds: float = 300.0,
        clock: Clock = lambda: datetime.now(UTC),
    ) -> None:
        self._repository = repository
        self._gateway = gateway
        self._quote_history = quote_history
        self._stale_seconds = max(float(stale_seconds), 30.0)
        self._clock = clock

    async def capture_once(self, *, now: datetime | None = None) -> ReferenceCaptureResult:
        override_time = _utc(now) if now is not None else None
        availability: dict[str, object] = {
            "market_data_source": ARGENT_API_SOURCE,
            "market_data_ownership": "public_independent",
            "quote_type": "live_bid_ask_mid",
            "candle_source": CANDLE_SOURCE,
            "candle_derivation_version": CANDLE_DERIVATION_VERSION,
            "candle_price_basis": "observed_mid",
            "minimum_candle_coverage_ratio": str(MIN_COVERAGE_RATIO),
            "cross_market": "separate_point_in_time_daily_feed",
            "external_events": "fed_rss_separate_loop",
            "orders": "not_captured",
        }
        try:
            quote = await self._gateway.read_xau_usd()
        except ArgentApiReadError as exc:
            captured_at = override_time or _utc(self._clock())
            availability["quote"] = exc.code
            snapshot_id = await self._store_snapshot(
                captured_at=captured_at,
                status="unavailable",
                bid=None,
                ask=None,
                mid=None,
                spread=None,
                quote_time=None,
                quote_age=None,
                availability=availability,
                latest_candle_ids={},
            )
            return ReferenceCaptureResult(snapshot_id, "unavailable", False)

        captured_at = override_time or _utc(self._clock())
        bid = quote.get("bid")
        ask = quote.get("ask")
        mid = quote.get("mid")
        spread = quote.get("spread")
        quote_time = quote.get("observed_at")
        if not all(isinstance(value, Decimal) for value in (bid, ask, mid, spread)) or not isinstance(
            quote_time, datetime
        ):
            availability["quote"] = "argentapi_invalid_normalized_quote"
            snapshot_id = await self._store_snapshot(
                captured_at=captured_at,
                status="unavailable",
                bid=None,
                ask=None,
                mid=None,
                spread=None,
                quote_time=None,
                quote_age=None,
                availability=availability,
                latest_candle_ids={},
            )
            return ReferenceCaptureResult(snapshot_id, "unavailable", False)

        quote_time = _utc(quote_time)
        if quote_time > captured_at:
            availability["quote"] = "argentapi_future_timestamp"
            snapshot_id = await self._store_snapshot(
                captured_at=captured_at,
                status="unavailable",
                bid=None,
                ask=None,
                mid=None,
                spread=None,
                quote_time=quote_time,
                quote_age=None,
                availability=availability,
                latest_candle_ids={},
            )
            return ReferenceCaptureResult(snapshot_id, "unavailable", False)

        quote_age = (captured_at - quote_time).total_seconds()
        fresh = quote_age <= self._stale_seconds
        availability["quote"] = "available" if fresh else "argentapi_stale_quote"
        availability["market_state"] = "open" if fresh else "closed_or_stale"
        latest_ids = await self._quote_history.latest_candle_ids(
            symbol=SYMBOL,
            source=CANDLE_SOURCE,
        )
        stored_candles = 0
        if fresh:
            candle_states: dict[str, object] = {}
            for timeframe in _TIMEFRAME_SECONDS:
                start, end = _closed_bucket(quote_time, timeframe)
                existing_id = await self._quote_history.candle_id_for_bucket(
                    symbol=SYMBOL,
                    source=CANDLE_SOURCE,
                    timeframe=timeframe,
                    open_time_utc=start,
                )
                if existing_id is not None:
                    latest_ids[timeframe] = existing_id
                    candle_states[timeframe] = {
                        "timeframe": timeframe,
                        "bucket_start_utc": start.isoformat(),
                        "bucket_end_utc": end.isoformat(),
                        "state": "closed_bucket_already_materialized",
                        "candle_id": str(existing_id),
                    }
                    continue
                rows = await self._quote_history.quote_observations(
                    symbol=SYMBOL,
                    source=ARGENT_API_SOURCE,
                    start_utc=start,
                    end_utc=end,
                )
                candle, state = _sampled_candle(
                    rows,
                    timeframe=timeframe,
                    start_utc=start,
                    end_utc=end,
                    first_observed_at=captured_at,
                )
                candle_states[timeframe] = state
                if candle is None:
                    continue
                candle_id, _, created = await self._repository.store_candle(candle)
                latest_ids[timeframe] = candle_id
                stored_candles += int(created)
            availability["candles"] = candle_states

        status = "complete" if fresh else "partial"
        snapshot_id = await self._store_snapshot(
            captured_at=captured_at,
            status=status,
            bid=bid,
            ask=ask,
            mid=mid,
            spread=spread,
            quote_time=quote_time,
            quote_age=quote_age,
            availability=availability,
            latest_candle_ids=latest_ids,
        )
        return ReferenceCaptureResult(snapshot_id, status, fresh, stored_candles)

    async def _store_snapshot(
        self,
        *,
        captured_at: datetime,
        status: str,
        bid: Decimal | None,
        ask: Decimal | None,
        mid: Decimal | None,
        spread: Decimal | None,
        quote_time: datetime | None,
        quote_age: float | None,
        availability: dict[str, object],
        latest_candle_ids: dict[str, UUID],
    ) -> UUID:
        event_ids = await self._repository.event_observation_ids_known_at(captured_at=captured_at)
        availability["external_events"] = "point_in_time_linked"
        availability["external_event_observation_count"] = len(event_ids)
        snapshot: dict[str, object] = {
            "captured_at": captured_at,
            "symbol": SYMBOL,
            "capture_status": status,
            "bid": bid,
            "ask": ask,
            "mid": mid,
            "spread": spread,
            "quote_time": quote_time,
            "quote_age_seconds": quote_age,
            "session_code": session_code_at(captured_at),
            "position_state_json": None,
            "data_availability_json": _canonical_json(availability),
            "event_observation_ids_json": _canonical_json([str(item) for item in event_ids]),
            **{
                column: latest_candle_ids.get(timeframe)
                for timeframe, column in _SNAPSHOT_CANDLE_KEYS.items()
            },
        }
        snapshot["snapshot_digest"] = _digest(
            {
                key: str(value) if isinstance(value, (Decimal, datetime, UUID)) else value
                for key, value in snapshot.items()
                if key not in {"captured_at", "snapshot_digest"}
            }
        )
        return await self._repository.store_snapshot(snapshot)


def day53_genuine_live_gold_feed_manifest() -> dict[str, object]:
    manifest: dict[str, object] = {
        "manifest_version": "aidy_day53_genuine_live_gold_feed_v1",
        "quote_source": ARGENT_API_SOURCE,
        "quote_endpoint": "/v1/spot/gold",
        "quote_fields_required": ["bid", "ask", "mid", "fetchedAt", "ageMs", "stale"],
        "candle_source": CANDLE_SOURCE,
        "candle_derivation_version": CANDLE_DERIVATION_VERSION,
        "candle_price_basis": "observed_mid",
        "timeframes": list(_TIMEFRAME_SECONDS),
        "minimum_coverage_ratio": str(MIN_COVERAGE_RATIO),
        "one_minute_bar_semantics": "one_or_more_genuine_observed_mid_samples",
        "missing_or_sparse_data_fails_closed": True,
        "api_key_header_only": True,
        "api_key_persisted": False,
        "broker_or_account_state_allowed": False,
        "super_signals_dependency_allowed": False,
        "live_money_execution_allowed": False,
        "decision_adapter_enabled_by_this_change": False,
        "freeze_break_reason": "material_safety_or_data_integrity_defect",
    }
    manifest["manifest_digest"] = _digest(manifest)
    return manifest
