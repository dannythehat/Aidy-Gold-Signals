from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from aidy.gold_api_gateway import GoldApiGateway, GoldApiReadError


@pytest.mark.asyncio
async def test_gold_api_normalizes_xau_usd_quote() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/price/XAU"
        return httpx.Response(
            200,
            json={
                "name": "Gold",
                "symbol": "XAU",
                "price": 3388.25,
                "updatedAt": "2026-08-19T09:20:15Z",
            },
        )

    quote = await GoldApiGateway(transport=httpx.MockTransport(handler)).read_xau_usd()

    assert quote["symbol"] == "XAUUSD"
    assert quote["price"] == Decimal("3388.25")
    assert quote["observed_at"] == datetime(2026, 8, 19, 9, 20, 15, tzinfo=UTC)
    assert quote["source"] == "gold_api"


@pytest.mark.asyncio
async def test_gold_api_rejects_invalid_price() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"symbol": "XAU", "price": -1, "updatedAt": "2026-08-19T09:20:15Z"},
        )

    with pytest.raises(GoldApiReadError, match="gold_api_invalid_price"):
        await GoldApiGateway(transport=httpx.MockTransport(handler)).read_xau_usd()


@pytest.mark.asyncio
async def test_gold_api_marks_upstream_failure_retryable() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "upstream unavailable"})

    with pytest.raises(GoldApiReadError) as exc_info:
        await GoldApiGateway(transport=httpx.MockTransport(handler)).read_xau_usd()

    assert exc_info.value.code == "gold_api_temporarily_unavailable"
    assert exc_info.value.retryable is True
