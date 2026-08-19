"""Broker-free XAU/USD reference-price gateway for AIDY.

Gold-API is used only as an indicative market-data source. There is no account,
broker, order, position or execution surface in this adapter.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

import httpx

GOLD_API_BASE_URL = "https://api.gold-api.com"


class GoldApiReadError(RuntimeError):
    def __init__(self, code: str, *, retryable: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


def _parse_utc(value: object) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise GoldApiReadError("gold_api_invalid_timestamp")
    raw = value.strip()
    if raw.endswith("Z"):
        raw = f"{raw[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise GoldApiReadError("gold_api_invalid_timestamp") from exc
    if parsed.tzinfo is None:
        raise GoldApiReadError("gold_api_invalid_timestamp")
    return parsed.astimezone(UTC)


def _price(value: object) -> Decimal:
    if value is None or isinstance(value, bool):
        raise GoldApiReadError("gold_api_invalid_price")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise GoldApiReadError("gold_api_invalid_price") from exc
    if not parsed.is_finite() or parsed <= 0:
        raise GoldApiReadError("gold_api_invalid_price")
    return parsed


class GoldApiGateway:
    def __init__(
        self,
        *,
        timeout_seconds: float = 15.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._timeout = httpx.Timeout(timeout_seconds)
        self._transport = transport

    async def read_xau_usd(self) -> dict[str, object]:
        """Return one normalized keyless Gold-API XAU/USD observation."""

        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                transport=self._transport,
                headers={"Accept": "application/json", "User-Agent": "AIDY-Signals/1.0"},
            ) as client:
                response = await client.get(f"{GOLD_API_BASE_URL}/price/XAU")
        except httpx.TimeoutException as exc:
            raise GoldApiReadError("gold_api_timeout", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise GoldApiReadError("gold_api_unreachable", retryable=True) from exc

        if response.status_code == 429:
            raise GoldApiReadError("gold_api_rate_limited", retryable=True)
        if response.status_code >= 500:
            raise GoldApiReadError("gold_api_temporarily_unavailable", retryable=True)
        if response.status_code != 200:
            raise GoldApiReadError("gold_api_read_rejected")

        try:
            payload = response.json()
        except ValueError as exc:
            raise GoldApiReadError("gold_api_invalid_response") from exc
        if not isinstance(payload, dict):
            raise GoldApiReadError("gold_api_invalid_response")

        symbol = str(payload.get("symbol") or "").upper()
        if symbol not in {"XAU", "XAUUSD"}:
            raise GoldApiReadError("gold_api_wrong_symbol")
        observed_at = _parse_utc(payload.get("updatedAt") or payload.get("timestamp"))
        price = _price(payload.get("price"))

        return {
            "symbol": "XAUUSD",
            "price": price,
            "observed_at": observed_at,
            "currency": str(payload.get("currency") or "USD").upper(),
            "upstream_symbol": symbol,
            "source": "gold_api",
        }
