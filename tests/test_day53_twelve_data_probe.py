from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from aidy.twelve_data_probe import TwelveDataProbeError, probe_twelve_data_basic

API_KEY = "td_test_secret_value"
NOW = datetime(2026, 9, 2, 5, 0, tzinfo=UTC)


def _discovery(*, plan: str = "Basic") -> dict:
    return {
        "data": [
            {
                "symbol": "XAU/USD",
                "instrument_name": "Gold Spot / US Dollar",
                "exchange": "Commodity Aggregate",
                "instrument_type": "Commodity",
                "currency": "USD",
                "access": {
                    "global": plan,
                    "plan": plan,
                    "plan_business": "Basic",
                },
            }
        ],
        "status": "ok",
    }


def _series(*, degenerate: bool = False) -> dict:
    values = []
    for minute in range(30):
        base = 3500 + minute / 100
        if degenerate:
            open_price = high = low = close = base
        else:
            open_price = base
            high = base + 0.25
            low = base - 0.20
            close = base + 0.05
        values.append(
            {
                "datetime": f"2026-09-02 04:{59 - minute:02d}:00",
                "open": f"{open_price:.2f}",
                "high": f"{high:.2f}",
                "low": f"{low:.2f}",
                "close": f"{close:.2f}",
            }
        )
    return {
        "meta": {"symbol": "XAU/USD", "interval": "1min", "timezone": "UTC"},
        "values": values,
        "status": "ok",
    }


@pytest.mark.asyncio
async def test_probe_requires_basic_and_real_one_minute_ohlc_without_url_secret() -> None:
    seen_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == f"apikey {API_KEY}"
        assert API_KEY not in str(request.url)
        seen_paths.append(request.url.path)
        if request.url.path == "/symbol_search":
            assert request.url.params["symbol"] == "XAU/USD"
            assert request.url.params["show_plan"] == "true"
            return httpx.Response(200, json=_discovery())
        if request.url.path == "/time_series":
            assert request.url.params["symbol"] == "XAU/USD"
            assert request.url.params["interval"] == "1min"
            assert request.url.params["timezone"] == "UTC"
            return httpx.Response(200, json=_series())
        raise AssertionError(request.url.path)

    result = await probe_twelve_data_basic(
        api_key=API_KEY,
        transport=httpx.MockTransport(handler),
        clock=lambda: NOW,
    )

    assert seen_paths == ["/symbol_search", "/time_series"]
    assert result["basic_plan_confirmed"] is True
    assert result["time_series_1min_confirmed"] is True
    assert result["bar_count"] == 30
    assert result["non_degenerate_bar_count"] == 30
    assert result["ohlc_geometry_valid"] is True
    assert result["ready_for_adapter_build"] is True
    assert result["api_key_in_url"] is False
    assert API_KEY not in str(result)


@pytest.mark.asyncio
async def test_probe_refuses_xau_when_discovery_says_grow() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/symbol_search"
        return httpx.Response(200, json=_discovery(plan="Grow"))

    with pytest.raises(TwelveDataProbeError, match="twelve_data_xau_usd_not_basic"):
        await probe_twelve_data_basic(
            api_key=API_KEY,
            transport=httpx.MockTransport(handler),
            clock=lambda: NOW,
        )


@pytest.mark.asyncio
async def test_probe_refuses_plan_restricted_time_series_even_after_basic_discovery() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/symbol_search":
            return httpx.Response(200, json=_discovery())
        return httpx.Response(
            403,
            json={"code": 403, "message": "upgrade required", "status": "error"},
        )

    with pytest.raises(TwelveDataProbeError, match="twelve_data_time_series_plan_restricted"):
        await probe_twelve_data_basic(
            api_key=API_KEY,
            transport=httpx.MockTransport(handler),
            clock=lambda: NOW,
        )


@pytest.mark.asyncio
async def test_probe_refuses_close_only_degenerate_series() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/symbol_search":
            return httpx.Response(200, json=_discovery())
        return httpx.Response(200, json=_series(degenerate=True))

    with pytest.raises(TwelveDataProbeError, match="twelve_data_all_bars_degenerate"):
        await probe_twelve_data_basic(
            api_key=API_KEY,
            transport=httpx.MockTransport(handler),
            clock=lambda: NOW,
        )


@pytest.mark.asyncio
async def test_probe_refuses_incomplete_ohlc() -> None:
    payload = _series()
    payload["values"][0].pop("high")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/symbol_search":
            return httpx.Response(200, json=_discovery())
        return httpx.Response(200, json=payload)

    with pytest.raises(TwelveDataProbeError, match="twelve_data_invalid_bar_high"):
        await probe_twelve_data_basic(
            api_key=API_KEY,
            transport=httpx.MockTransport(handler),
            clock=lambda: NOW,
        )
