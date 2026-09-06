from __future__ import annotations

from urllib.parse import urlparse

from aidy.provider_intelligence_health import capture_health_response
from aidy.provider_market_api import market_ohlc_response
from entry import Default as CoreDefault


class Default(CoreDefault):
    async def fetch(self, request):
        path = urlparse(request.url).path
        if path == "/market/ohlc":
            return await market_ohlc_response(request, self.env)
        if path == "/provider-intelligence/health":
            return await capture_health_response(request, self.env)
        return await super().fetch(request)
