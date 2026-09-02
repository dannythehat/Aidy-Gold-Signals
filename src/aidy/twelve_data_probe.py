"""Read-only Twelve Data entitlement and XAU/USD OHLC probe for Day 53."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

import httpx

TWELVE_DATA_BASE_URL = "https://api.twelvedata.com"
TWELVE_DATA_SYMBOL = "XAU/USD"
TWELVE_DATA_PROBE_VERSION = "aidy_twelve_data_basic_probe_v1"


class TwelveDataProbeError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _decimal(value: object, *, field: str) -> Decimal:
    if value is None or isinstance(value, bool):
        raise TwelveDataProbeError(f"twelve_data_invalid_{field}")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise TwelveDataProbeError(f"twelve_data_invalid_{field}") from exc
    if not parsed.is_finite() or parsed <= 0:
        raise TwelveDataProbeError(f"twelve_data_invalid_{field}")
    return parsed


def _timestamp(value: object) -> datetime:
    raw = str(value or "").strip()
    if not raw:
        raise TwelveDataProbeError("twelve_data_invalid_bar_datetime")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise TwelveDataProbeError("twelve_data_invalid_bar_datetime") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _safe_match(row: dict[str, object]) -> dict[str, object]:
    access = row.get("access") if isinstance(row.get("access"), dict) else {}
    assert isinstance(access, dict)
    return {
        "symbol": str(row.get("symbol") or ""),
        "instrument_name": str(row.get("instrument_name") or ""),
        "exchange": str(row.get("exchange") or ""),
        "instrument_type": str(row.get("instrument_type") or ""),
        "currency": str(row.get("currency") or ""),
        "access": {
            "global": str(access.get("global") or ""),
            "plan": str(access.get("plan") or ""),
            "plan_business": str(access.get("plan_business") or ""),
        },
    }


def _error_code(*, stage: str, response: httpx.Response, payload: object) -> str:
    provider_code = payload.get("code") if isinstance(payload, dict) else None
    if response.status_code == 403 or provider_code == 403:
        return f"twelve_data_{stage}_plan_restricted"
    if response.status_code == 401 or provider_code == 401:
        return f"twelve_data_{stage}_unauthorized"
    if response.status_code == 429 or provider_code == 429:
        return f"twelve_data_{stage}_rate_limited"
    return f"twelve_data_{stage}_request_failed"


async def _get_json(
    client: httpx.AsyncClient,
    *,
    path: str,
    params: dict[str, object],
    stage: str,
) -> dict[str, object]:
    try:
        response = await client.get(f"{TWELVE_DATA_BASE_URL}{path}", params=params)
    except httpx.TimeoutException as exc:
        raise TwelveDataProbeError(f"twelve_data_{stage}_timeout") from exc
    except httpx.HTTPError as exc:
        raise TwelveDataProbeError(f"twelve_data_{stage}_unreachable") from exc
    try:
        payload = response.json()
    except ValueError as exc:
        raise TwelveDataProbeError(f"twelve_data_{stage}_invalid_json") from exc
    if not isinstance(payload, dict):
        raise TwelveDataProbeError(f"twelve_data_{stage}_invalid_json")
    if response.status_code != 200 or str(payload.get("status") or "").lower() == "error":
        raise TwelveDataProbeError(_error_code(stage=stage, response=response, payload=payload))
    return payload


async def probe_twelve_data_basic(
    *,
    api_key: str,
    outputsize: int = 30,
    transport: httpx.AsyncBaseTransport | None = None,
    clock: Callable[[], datetime] | None = None,
) -> dict[str, object]:
    """Prove Basic entitlement and an actual vendor-built 1-minute XAU/USD series.

    The API key is sent only in the Twelve Data recommended Authorization header.
    It is never placed in the request URL or returned in probe evidence.
    """

    key = str(api_key).strip()
    if not key:
        raise TwelveDataProbeError("twelve_data_api_key_missing")
    if outputsize < 10 or outputsize > 120:
        raise ValueError("Probe outputsize must be between 10 and 120.")

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(15.0),
        transport=transport,
        headers={
            "Accept": "application/json",
            "Authorization": f"apikey {key}",
            "User-Agent": "AIDY-Signals/1.0",
        },
    ) as client:
        discovery = await _get_json(
            client,
            path="/symbol_search",
            params={"symbol": TWELVE_DATA_SYMBOL, "show_plan": "true", "outputsize": 120},
            stage="symbol_search",
        )
        rows = discovery.get("data")
        if not isinstance(rows, list):
            raise TwelveDataProbeError("twelve_data_symbol_search_missing_data")
        exact = [
            _safe_match(row)
            for row in rows
            if isinstance(row, dict)
            and str(row.get("symbol") or "").strip().upper() == TWELVE_DATA_SYMBOL
        ]
        if not exact:
            raise TwelveDataProbeError("twelve_data_xau_usd_not_discovered")
        basic = [
            row
            for row in exact
            if str(row["access"]["plan"]).strip().lower() == "basic"  # type: ignore[index]
        ]
        if not basic:
            raise TwelveDataProbeError("twelve_data_xau_usd_not_basic")

        series = await _get_json(
            client,
            path="/time_series",
            params={
                "symbol": TWELVE_DATA_SYMBOL,
                "interval": "1min",
                "outputsize": outputsize,
                "timezone": "UTC",
                "order": "DESC",
                "format": "JSON",
            },
            stage="time_series",
        )

    meta = series.get("meta")
    values = series.get("values")
    if not isinstance(meta, dict) or not isinstance(values, list):
        raise TwelveDataProbeError("twelve_data_time_series_missing_data")
    if str(meta.get("symbol") or "").strip().upper() != TWELVE_DATA_SYMBOL:
        raise TwelveDataProbeError("twelve_data_time_series_wrong_symbol")
    if str(meta.get("interval") or "").strip().lower() != "1min":
        raise TwelveDataProbeError("twelve_data_time_series_wrong_interval")
    if len(values) < 2:
        raise TwelveDataProbeError("twelve_data_time_series_too_short")

    timestamps: list[datetime] = []
    non_degenerate = 0
    for raw_bar in values:
        if not isinstance(raw_bar, dict):
            raise TwelveDataProbeError("twelve_data_invalid_bar")
        timestamp = _timestamp(raw_bar.get("datetime"))
        open_price = _decimal(raw_bar.get("open"), field="bar_open")
        high = _decimal(raw_bar.get("high"), field="bar_high")
        low = _decimal(raw_bar.get("low"), field="bar_low")
        close = _decimal(raw_bar.get("close"), field="bar_close")
        if high < max(open_price, close, low) or low > min(open_price, close, high):
            raise TwelveDataProbeError("twelve_data_invalid_ohlc_geometry")
        if high > low:
            non_degenerate += 1
        timestamps.append(timestamp)
    if len(set(timestamps)) != len(timestamps):
        raise TwelveDataProbeError("twelve_data_duplicate_bar_timestamps")
    if non_degenerate == 0:
        raise TwelveDataProbeError("twelve_data_all_bars_degenerate")

    now = (clock or (lambda: datetime.now(UTC)))()
    if now.tzinfo is None:
        raise ValueError("Probe clock must be timezone-aware.")
    return {
        "probe_version": TWELVE_DATA_PROBE_VERSION,
        "probed_at_utc": now.astimezone(UTC).isoformat(),
        "symbol": TWELVE_DATA_SYMBOL,
        "authorization_mode": "http_authorization_header",
        "api_key_in_url": False,
        "exact_symbol_matches": exact,
        "basic_exact_match_count": len(basic),
        "basic_plan_confirmed": True,
        "time_series_1min_confirmed": True,
        "bar_count": len(values),
        "non_degenerate_bar_count": non_degenerate,
        "earliest_bar_utc": min(timestamps).isoformat(),
        "latest_bar_utc": max(timestamps).isoformat(),
        "ohlc_geometry_valid": True,
        "ready_for_adapter_build": True,
    }
