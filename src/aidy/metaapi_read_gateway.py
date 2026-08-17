"""Temporary read-only MetaAPI adapter for AIDY market-price observation.

The adapter is quarantined to XAUUSD quotes and candles. It exposes no account
position, order, trade, close, modify, or broker-mutation method and must never
use Super Signals credentials.
"""

from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import quote

import httpx

DEFAULT_METAAPI_PROVISIONING_URL = "https://mt-provisioning-api-v1.agiliumtrade.agiliumtrade.ai"
_ALLOWED_CANDLE_TIMEFRAMES = {
    "1m",
    "2m",
    "3m",
    "4m",
    "5m",
    "6m",
    "10m",
    "12m",
    "15m",
    "20m",
    "30m",
    "1h",
    "2h",
    "3h",
    "4h",
    "6h",
    "8h",
    "12h",
    "1d",
    "1w",
    "1mn",
}
_REGION_PATTERN = re.compile(r"^[a-z0-9-]+$")


class MetaApiReadError(RuntimeError):
    def __init__(self, code: str, *, retryable: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


def _normalize_region(region: str) -> str:
    normalized = region.strip().lower()
    if not normalized or _REGION_PATTERN.fullmatch(normalized) is None:
        raise MetaApiReadError("metaapi_region_unavailable")
    return normalized


class MetaApiReadGateway:
    def __init__(self, *, timeout_seconds: float = 30.0) -> None:
        self._timeout = httpx.Timeout(timeout_seconds)

    async def resolve_account_region(self, *, token: str, account_id: str) -> str:
        response = await self._request(
            "GET",
            f"{DEFAULT_METAAPI_PROVISIONING_URL}/users/current/accounts/{account_id}",
            token=token,
        )
        payload = self._json(response)
        if not isinstance(payload, dict):
            raise MetaApiReadError("metaapi_invalid_response")
        return _normalize_region(str(payload.get("region") or ""))

    async def read_historical_candles(
        self,
        *,
        token: str,
        account_id: str,
        region: str,
        symbol: str,
        timeframe: str,
        start_time: datetime | None = None,
        limit: int = 3,
    ) -> list[dict[str, object]]:
        if timeframe not in _ALLOWED_CANDLE_TIMEFRAMES:
            raise ValueError("Unsupported MetaAPI candle timeframe.")
        if not 1 <= limit <= 1000:
            raise ValueError("MetaAPI candle limit must be between 1 and 1000.")
        encoded_symbol = quote(symbol, safe="")
        encoded_timeframe = quote(timeframe, safe="")
        query_parts: list[str] = []
        if start_time is not None:
            encoded_start = quote(start_time.isoformat().replace("+00:00", "Z"), safe=":-T.Z+")
            query_parts.append(f"startTime={encoded_start}")
        query_parts.append(f"limit={limit}")
        query = "&".join(query_parts)
        normalized_region = _normalize_region(region)
        response = await self._request(
            "GET",
            (
                f"https://mt-market-data-client-api-v1.{normalized_region}.agiliumtrade.ai"
                f"/users/current/accounts/{account_id}/historical-market-data/"
                f"symbols/{encoded_symbol}/timeframes/{encoded_timeframe}/candles?{query}"
            ),
            token=token,
        )
        payload = self._json(response)
        if not isinstance(payload, list) or any(not isinstance(item, dict) for item in payload):
            raise MetaApiReadError("metaapi_invalid_response")
        return payload

    async def read_symbol_price(
        self,
        *,
        token: str,
        account_id: str,
        region: str,
        symbol: str,
    ) -> dict[str, object]:
        encoded_symbol = quote(symbol, safe="")
        payload = await self._read_terminal_json(
            token=token,
            region=region,
            path=(f"/users/current/accounts/{account_id}/symbols/{encoded_symbol}/current-price"),
        )
        if not isinstance(payload, dict):
            raise MetaApiReadError("metaapi_invalid_response")
        return payload

    async def _read_terminal_json(self, *, token: str, region: str, path: str) -> object:
        normalized_region = _normalize_region(region)
        response = await self._request(
            "GET",
            f"https://mt-client-api-v1.{normalized_region}.agiliumtrade.ai{path}",
            token=token,
        )
        return self._json(response)

    async def _request(self, method: str, url: str, *, token: str) -> httpx.Response:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.request(
                    method,
                    url,
                    headers={"Accept": "application/json", "auth-token": token},
                )
        except httpx.TimeoutException as exc:
            raise MetaApiReadError("metaapi_timeout", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise MetaApiReadError("metaapi_unreachable", retryable=True) from exc
        if response.status_code == 200:
            return response
        if response.status_code == 401:
            raise MetaApiReadError("metaapi_token_invalid")
        if response.status_code == 403:
            raise MetaApiReadError("metaapi_permission_denied")
        if response.status_code == 404:
            raise MetaApiReadError("metaapi_terminal_data_unavailable")
        if response.status_code in {408, 425, 429} or response.status_code >= 500:
            raise MetaApiReadError("metaapi_temporarily_unavailable", retryable=True)
        raise MetaApiReadError("metaapi_terminal_read_rejected")

    @staticmethod
    def _json(response: httpx.Response) -> object:
        try:
            return response.json()
        except ValueError as exc:
            raise MetaApiReadError("metaapi_invalid_response") from exc
