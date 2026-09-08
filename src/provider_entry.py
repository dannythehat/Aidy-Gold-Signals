from __future__ import annotations

from urllib.parse import urlparse

from aidy.provider_calibration_api import calibration_market_ohlc_response
from aidy.provider_context_api import provider_context_response
from aidy.provider_market_api import market_ohlc_response
from entry import Default as CoreDefault


class Default(CoreDefault):
    async def fetch(self, request):
        path = urlparse(request.url).path
        if path == "/market/ohlc":
            return await market_ohlc_response(request, self.env)
        if path == "/calibration/market/ohlc":
            return await calibration_market_ohlc_response(request, self.env)
        if path == "/provider/context":
            return await provider_context_response(request, self.env)
        return await super().fetch(request)

    async def queue(self, batch, env, ctx):
        """Expose the queue event on the concrete Worker entrypoint.

        Cloudflare dispatches queue events against the configured entrypoint class.
        Keep this method concrete here rather than relying on inherited event-handler
        discovery so provider HTTP routing cannot accidentally strand capture messages.
        """
        return await super().queue(batch, env, ctx)
