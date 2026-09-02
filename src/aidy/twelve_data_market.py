"""Twelve Data vendor-built XAU/USD OHLC adapter and AIDY gold session calendar."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Any
from zoneinfo import ZoneInfo

import httpx

TWELVE_DATA_BASE_URL = "https://api.twelvedata.com"
TWELVE_DATA_SYMBOL = "XAU/USD"
AIDY_SYMBOL = "XAUUSD"
TWELVE_DATA_SOURCE = "twelve_data"
RAW_M1_SOURCE = "twelve_data_vendor_m1_v1"
AGGREGATE_SOURCE = "twelve_data_session_aggregate_v1"
ADAPTER_VERSION = "aidy_twelve_data_ohlc_adapter_v1"
SESSION_CALENDAR_VERSION = "aidy_gold_session_calendar_ny_v1"
NEW_YORK = ZoneInfo("America/New_York")
MAX_OPEN_SESSION_LAG_SECONDS = 180.0
COMPLETENESS_THRESHOLDS = {
    "1m": Decimal("1.00"),
    "5m": Decimal("1.00"),
    "15m": Decimal("1.00"),
    "1h": Decimal("1.00"),
    "4h": Decimal("1.00"),
    "1d": Decimal("1.00"),
}
_TIMEFRAME_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400}


class TwelveDataMarketError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def digest(value: object) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Twelve Data market adapter requires timezone-aware datetimes.")
    return value.astimezone(UTC)


def _decimal(value: object, *, field: str) -> Decimal:
    if value is None or isinstance(value, bool):
        raise TwelveDataMarketError(f"twelve_data_invalid_{field}")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise TwelveDataMarketError(f"twelve_data_invalid_{field}") from exc
    if not parsed.is_finite() or parsed <= 0:
        raise TwelveDataMarketError(f"twelve_data_invalid_{field}")
    return parsed


def _bar_open_time(value: object) -> datetime:
    raw = str(value or "").strip()
    if not raw:
        raise TwelveDataMarketError("twelve_data_invalid_bar_datetime")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise TwelveDataMarketError("twelve_data_invalid_bar_datetime") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class TwelveDataM1Bar:
    open_time_utc: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal

    @property
    def close_time_utc(self) -> datetime:
        return self.open_time_utc + timedelta(minutes=1)

    @property
    def payload_digest(self) -> str:
        return digest(
            {
                "source": RAW_M1_SOURCE,
                "symbol": AIDY_SYMBOL,
                "timeframe": "1m",
                "open_time_utc": self.open_time_utc.isoformat(),
                "open": str(self.open),
                "high": str(self.high),
                "low": str(self.low),
                "close": str(self.close),
            }
        )


@dataclass(frozen=True, slots=True)
class TwelveDataFetch:
    fetched_at_utc: datetime
    meta: dict[str, object]
    credit_headers: dict[str, str]
    response_digest: str
    closed_bars: tuple[TwelveDataM1Bar, ...]
    raw_bar_count: int
    forming_bar_count: int
    off_session_bar_count: int
    latest_closed_bar_open_utc: datetime | None
    latest_closed_bar_close_utc: datetime | None
    open_session_lag_seconds: float | None
    session_open_at_fetch: bool

    @property
    def freshness_state(self) -> str:
        if not self.session_open_at_fetch:
            return "session_closed"
        if self.open_session_lag_seconds is None:
            return "lag_unknown"
        if self.open_session_lag_seconds > MAX_OPEN_SESSION_LAG_SECONDS:
            return "stale"
        return "fresh"


def gold_session_is_open(value: datetime) -> bool:
    """CME-style gold session: Sun 18:00-Fri 17:00 NY, with 17:00-18:00 daily break."""

    local = _utc(value).astimezone(NEW_YORK)
    weekday = local.weekday()
    wall = local.time().replace(tzinfo=None)
    if weekday == 5:
        return False
    if weekday == 6:
        return wall >= time(18, 0)
    if weekday == 4:
        return wall < time(17, 0)
    return wall < time(17, 0) or wall >= time(18, 0)


def expected_market_minute_opens(start_utc: datetime, end_utc: datetime) -> tuple[datetime, ...]:
    start = _utc(start_utc).replace(second=0, microsecond=0)
    end = _utc(end_utc).replace(second=0, microsecond=0)
    if end <= start:
        return ()
    out: list[datetime] = []
    cursor = start
    while cursor < end:
        if gold_session_is_open(cursor):
            out.append(cursor)
        cursor += timedelta(minutes=1)
    return tuple(out)


def _ny_wall(day: date, hour: int) -> datetime:
    return datetime.combine(day, time(hour, 0), tzinfo=NEW_YORK)


def latest_completed_d1_bucket(as_of_utc: datetime) -> tuple[datetime, datetime]:
    """Return the most recent 17:00 New York gold daily close strictly before as-of."""

    as_of = _utc(as_of_utc)
    candidate_day = as_of.astimezone(NEW_YORK).date()
    for _ in range(10):
        if candidate_day.weekday() < 5:
            close_utc = _ny_wall(candidate_day, 17).astimezone(UTC)
            if close_utc < as_of:
                previous = candidate_day - timedelta(days=1)
                start_utc = _ny_wall(previous, 18).astimezone(UTC)
                return start_utc, close_utc
        candidate_day -= timedelta(days=1)
    raise RuntimeError("Unable to resolve completed gold D1 session.")


def latest_completed_bucket(as_of_utc: datetime, timeframe: str) -> tuple[datetime, datetime]:
    as_of = _utc(as_of_utc)
    if timeframe == "1d":
        return latest_completed_d1_bucket(as_of)
    seconds = _TIMEFRAME_SECONDS[timeframe]
    epoch = int(as_of.timestamp())
    end_epoch = epoch - (epoch % seconds)
    end = datetime.fromtimestamp(end_epoch, tz=UTC)
    if end >= as_of:
        end -= timedelta(seconds=seconds)
    return end - timedelta(seconds=seconds), end


def _row_time(row: dict[str, Any]) -> datetime:
    value = row.get("open_time_utc")
    if isinstance(value, datetime):
        return _utc(value)
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError("Stored Twelve Data bar time must be timezone-aware.")
    return parsed.astimezone(UTC)


def completeness(
    bars: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    start_utc: datetime,
    end_utc: datetime,
    timeframe: str,
) -> dict[str, object]:
    expected = expected_market_minute_opens(start_utc, end_utc)
    expected_set = set(expected)
    actual_times = {_row_time(row) for row in bars}
    in_session = actual_times & expected_set
    ratio = Decimal(len(in_session)) / Decimal(len(expected)) if expected else Decimal(0)
    threshold = COMPLETENESS_THRESHOLDS[timeframe]
    return {
        "timeframe": timeframe,
        "bucket_start_utc": _utc(start_utc).isoformat(),
        "bucket_end_utc": _utc(end_utc).isoformat(),
        "expected_market_minutes": len(expected),
        "observed_market_minutes": len(in_session),
        "unexpected_or_off_session_minutes": len(actual_times - expected_set),
        "coverage_ratio": str(ratio.quantize(Decimal("0.000001"))),
        "minimum_coverage_ratio": str(threshold),
        "admissible": bool(expected) and ratio >= threshold,
        "session_calendar_version": SESSION_CALENDAR_VERSION,
    }


def aggregate_m1(
    bars: list[dict[str, Any]],
    *,
    timeframe: str,
    start_utc: datetime,
    end_utc: datetime,
    first_observed_at: datetime,
) -> tuple[dict[str, object] | None, dict[str, object]]:
    state = completeness(bars, start_utc=start_utc, end_utc=end_utc, timeframe=timeframe)
    if not state["admissible"]:
        return None, state
    expected = set(expected_market_minute_opens(start_utc, end_utc))
    ordered = sorted((row for row in bars if _row_time(row) in expected), key=_row_time)
    opens = [Decimal(str(row["open"])) for row in ordered]
    highs = [Decimal(str(row["high"])) for row in ordered]
    lows = [Decimal(str(row["low"])) for row in ordered]
    closes = [Decimal(str(row["close"])) for row in ordered]
    lineage = [
        {
            "id": str(row.get("id") or ""),
            "revision_index": int(row.get("revision_index") or 1),
            "payload_digest": str(row.get("payload_digest") or ""),
        }
        for row in ordered
    ]
    evidence = {
        "source": AGGREGATE_SOURCE,
        "symbol": AIDY_SYMBOL,
        "timeframe": timeframe,
        "open_time_utc": _utc(start_utc).isoformat(),
        "close_time_utc": _utc(end_utc).isoformat(),
        "open": str(opens[0]),
        "high": str(max(highs)),
        "low": str(min(lows)),
        "close": str(closes[-1]),
        "session_calendar_version": SESSION_CALENDAR_VERSION,
        "coverage": state,
        "input_m1_revisions": lineage,
    }
    candle = {
        "symbol": AIDY_SYMBOL,
        "timeframe": timeframe,
        "open_time_utc": _utc(start_utc),
        "broker_open_time": None,
        "open": evidence["open"],
        "high": evidence["high"],
        "low": evidence["low"],
        "close": evidence["close"],
        "tick_volume": len(ordered),
        "spread": None,
        "volume": None,
        "source": AGGREGATE_SOURCE,
        "first_observed_at": _utc(first_observed_at),
        "payload_digest": digest(evidence),
    }
    return candle, state


class TwelveDataOhlcGateway:
    def __init__(self, *, api_key: str, transport: httpx.AsyncBaseTransport | None = None) -> None:
        key = str(api_key).strip()
        if not key:
            raise TwelveDataMarketError("twelve_data_api_key_missing")
        self._key = key
        self._transport = transport

    async def fetch_1m(
        self,
        *,
        outputsize: int = 30,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        clock=lambda: datetime.now(UTC),
    ) -> TwelveDataFetch:
        params: dict[str, object] = {
            "symbol": TWELVE_DATA_SYMBOL,
            "interval": "1min",
            "timezone": "UTC",
            "order": "DESC",
            "format": "JSON",
        }
        if start_date is None and end_date is None:
            params["outputsize"] = outputsize
        else:
            if start_date is None or end_date is None:
                raise ValueError("Twelve Data backfill requires both start_date and end_date.")
            params["start_date"] = _utc(start_date).strftime("%Y-%m-%dT%H:%M:%S")
            params["end_date"] = _utc(end_date).strftime("%Y-%m-%dT%H:%M:%S")

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(30.0),
            transport=self._transport,
            headers={
                "Accept": "application/json",
                "Authorization": f"apikey {self._key}",
                "User-Agent": "AIDY-Signals/1.0",
            },
        ) as client:
            try:
                response = await client.get(f"{TWELVE_DATA_BASE_URL}/time_series", params=params)
            except httpx.TimeoutException as exc:
                raise TwelveDataMarketError("twelve_data_time_series_timeout") from exc
            except httpx.HTTPError as exc:
                raise TwelveDataMarketError("twelve_data_time_series_unreachable") from exc
        fetched_at = _utc(clock())
        try:
            payload = response.json()
        except ValueError as exc:
            raise TwelveDataMarketError("twelve_data_time_series_invalid_json") from exc
        if not isinstance(payload, dict):
            raise TwelveDataMarketError("twelve_data_time_series_invalid_json")
        if response.status_code != 200 or str(payload.get("status") or "").lower() == "error":
            code = payload.get("code")
            if response.status_code == 429 or code == 429:
                raise TwelveDataMarketError("twelve_data_time_series_rate_limited")
            if response.status_code in {401, 403} or code in {401, 403}:
                raise TwelveDataMarketError("twelve_data_time_series_not_authorized")
            raise TwelveDataMarketError("twelve_data_time_series_request_failed")

        meta = payload.get("meta")
        values = payload.get("values")
        if not isinstance(meta, dict) or not isinstance(values, list):
            raise TwelveDataMarketError("twelve_data_time_series_missing_data")
        if str(meta.get("symbol") or "").strip().upper() != TWELVE_DATA_SYMBOL:
            raise TwelveDataMarketError("twelve_data_time_series_wrong_symbol")
        if str(meta.get("interval") or "").strip().lower() != "1min":
            raise TwelveDataMarketError("twelve_data_time_series_wrong_interval")

        all_bars: list[TwelveDataM1Bar] = []
        admitted: list[TwelveDataM1Bar] = []
        forming = 0
        off_session = 0
        for row in values:
            if not isinstance(row, dict):
                raise TwelveDataMarketError("twelve_data_invalid_bar")
            bar = TwelveDataM1Bar(
                open_time_utc=_bar_open_time(row.get("datetime")),
                open=_decimal(row.get("open"), field="bar_open"),
                high=_decimal(row.get("high"), field="bar_high"),
                low=_decimal(row.get("low"), field="bar_low"),
                close=_decimal(row.get("close"), field="bar_close"),
            )
            if bar.high < max(bar.open, bar.close) or bar.low > min(bar.open, bar.close):
                raise TwelveDataMarketError("twelve_data_invalid_ohlc_geometry")
            all_bars.append(bar)
            if bar.close_time_utc >= fetched_at:
                forming += 1
                continue
            if not gold_session_is_open(bar.open_time_utc):
                off_session += 1
                continue
            admitted.append(bar)

        admitted.sort(key=lambda item: item.open_time_utc)
        latest = admitted[-1] if admitted else None
        session_open = gold_session_is_open(fetched_at)
        lag = (
            (fetched_at - latest.close_time_utc).total_seconds()
            if session_open and latest is not None
            else None
        )
        credit_headers: dict[str, str] = {}
        for key in ("api-credits-request", "api-credits-used", "api-credits-left"):
            value = response.headers.get(key)
            if value is not None:
                credit_headers[key] = value
        return TwelveDataFetch(
            fetched_at_utc=fetched_at,
            meta={str(key): value for key, value in meta.items()},
            credit_headers=credit_headers,
            response_digest=digest(payload),
            closed_bars=tuple(admitted),
            raw_bar_count=len(all_bars),
            forming_bar_count=forming,
            off_session_bar_count=off_session,
            latest_closed_bar_open_utc=latest.open_time_utc if latest else None,
            latest_closed_bar_close_utc=latest.close_time_utc if latest else None,
            open_session_lag_seconds=lag,
            session_open_at_fetch=session_open,
        )


def day53_twelve_data_market_manifest() -> dict[str, object]:
    result: dict[str, object] = {
        "manifest_version": "aidy_day53_twelve_data_market_v1",
        "adapter_version": ADAPTER_VERSION,
        "vendor": "Twelve Data",
        "vendor_symbol": TWELVE_DATA_SYMBOL,
        "raw_m1_source": RAW_M1_SOURCE,
        "aggregate_source": AGGREGATE_SOURCE,
        "vendor_bar_datetime_semantics": "bar_open_time",
        "forming_bar_rule": "admit_only_when_close_time_strictly_before_fetch_time",
        "max_open_session_lag_seconds": MAX_OPEN_SESSION_LAG_SECONDS,
        "session_calendar_version": SESSION_CALENDAR_VERSION,
        "session_timezone": "America/New_York",
        "weekly_open": "Sunday 18:00 America/New_York",
        "weekly_close": "Friday 17:00 America/New_York",
        "daily_maintenance_break": "17:00-18:00 America/New_York Monday-Thursday",
        "daily_close_boundary": "17:00 America/New_York",
        "off_session_vendor_bars_admissible": False,
        "completeness_thresholds": {
            key: str(value) for key, value in COMPLETENESS_THRESHOLDS.items()
        },
        "holiday_or_unmodeled_early_close_behavior": "fail_closed_as_incomplete",
        "response_meta_persisted": True,
        "credit_headers_persisted": True,
        "observed_lag_persisted": True,
        "vendor_revisions_overwrite_prior_evidence": False,
        "spread_missing_blocks": False,
        "observed_out_of_tolerance_spread_may_block": True,
        "broker_or_account_state_allowed": False,
        "super_signals_dependency_allowed": False,
        "live_money_execution_allowed": False,
    }
    result["manifest_digest"] = digest(result)
    return result
