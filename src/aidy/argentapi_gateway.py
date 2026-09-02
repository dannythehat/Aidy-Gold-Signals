"""Broker-free ArgentAPI XAU/USD bid/ask gateway for AIDY."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation

import httpx

ARGENT_API_BASE_URL = "https://api.argentapi.com"
ARGENT_API_SOURCE = "argentapi"


class ArgentApiReadError(RuntimeError):
    def __init__(self, code: str, *, retryable: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


def _price(value: object, *, code: str) -> Decimal:
    if value is None or isinstance(value, bool):
        raise ArgentApiReadError(code)
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ArgentApiReadError(code) from exc
    if not parsed.is_finite() or parsed <= 0:
        raise ArgentApiReadError(code)
    return parsed


def _nonnegative_number(value: object, *, code: str) -> float:
    if value is None or isinstance(value, bool):
        raise ArgentApiReadError(code)
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ArgentApiReadError(code) from exc
    if parsed < 0 or parsed != parsed or parsed == float("inf"):
        raise ArgentApiReadError(code)
    return parsed


def _optional_price(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        return _price(value, code="argentapi_invalid_session_range")
    except ArgentApiReadError:
        return None


class ArgentApiGateway:
    """Read one authenticated public-independent Gold spot observation.

    The API key is sent only in the ``X-API-Key`` header. It is never included
    in exception messages, normalized payloads, URLs, logs, or stored evidence.
    """

    def __init__(
        self,
        *,
        api_key: str,
        timeout_seconds: float = 15.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = str(api_key).strip()
        self._timeout = httpx.Timeout(timeout_seconds)
        self._transport = transport

    async def read_xau_usd(self) -> dict[str, object]:
        if not self._api_key:
            raise ArgentApiReadError("argentapi_credentials_missing")
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                transport=self._transport,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "AIDY-Signals/1.0",
                    "X-API-Key": self._api_key,
                },
            ) as client:
                response = await client.get(f"{ARGENT_API_BASE_URL}/v1/spot/gold")
        except httpx.TimeoutException as exc:
            raise ArgentApiReadError("argentapi_timeout", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise ArgentApiReadError("argentapi_unreachable", retryable=True) from exc

        if response.status_code == 429:
            raise ArgentApiReadError("argentapi_rate_limited", retryable=True)
        if response.status_code >= 500:
            raise ArgentApiReadError("argentapi_temporarily_unavailable", retryable=True)
        if response.status_code in {401, 403}:
            raise ArgentApiReadError("argentapi_authorization_rejected")
        if response.status_code != 200:
            raise ArgentApiReadError("argentapi_read_rejected")

        try:
            payload = response.json()
        except ValueError as exc:
            raise ArgentApiReadError("argentapi_invalid_response") from exc
        if not isinstance(payload, dict):
            raise ArgentApiReadError("argentapi_invalid_response")

        if str(payload.get("metal") or "").strip().lower() != "gold":
            raise ArgentApiReadError("argentapi_wrong_metal")
        if str(payload.get("currency") or "").strip().upper() != "USD":
            raise ArgentApiReadError("argentapi_wrong_currency")
        if str(payload.get("unit") or "").strip().upper() != "OUNCE":
            raise ArgentApiReadError("argentapi_wrong_unit")
        if str(payload.get("symbol") or "").strip().upper() not in {"AU", "XAU", "XAUUSD"}:
            raise ArgentApiReadError("argentapi_wrong_symbol")
        if payload.get("stale") is not False:
            raise ArgentApiReadError("argentapi_stale_or_unknown_quote")

        bid = _price(payload.get("bid"), code="argentapi_invalid_bid")
        ask = _price(payload.get("ask"), code="argentapi_invalid_ask")
        if ask < bid:
            raise ArgentApiReadError("argentapi_crossed_quote")
        midpoint = (bid + ask) / Decimal(2)
        raw_mid = payload.get("mid")
        mid = midpoint if raw_mid is None else _price(raw_mid, code="argentapi_invalid_mid")
        if mid < bid or mid > ask:
            raise ArgentApiReadError("argentapi_mid_outside_quote")

        fetched_at_ms = _nonnegative_number(
            payload.get("fetchedAt"), code="argentapi_invalid_fetched_at"
        )
        age_ms = _nonnegative_number(payload.get("ageMs"), code="argentapi_invalid_age")
        try:
            fetched_at = datetime.fromtimestamp(fetched_at_ms / 1000.0, tz=UTC)
        except (OverflowError, OSError, ValueError) as exc:
            raise ArgentApiReadError("argentapi_invalid_fetched_at") from exc
        observed_at = fetched_at - timedelta(milliseconds=age_ms)

        return {
            "symbol": "XAUUSD",
            "bid": bid,
            "ask": ask,
            "mid": mid,
            "spread": ask - bid,
            "observed_at": observed_at,
            "fetched_at": fetched_at,
            "provider_age_ms": age_ms,
            "session_high": _optional_price(payload.get("high")),
            "session_low": _optional_price(payload.get("low")),
            "source_timestamp_text": str(payload.get("sourceTimestamp") or "") or None,
            "source": ARGENT_API_SOURCE,
            "ownership": "public_independent",
        }
