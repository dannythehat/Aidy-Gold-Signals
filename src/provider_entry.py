from __future__ import annotations

from urllib.parse import urlparse

from aidy.provider_calibration_api import calibration_market_ohlc_response
from aidy.provider_context_api import provider_context_response
from aidy.provider_market_api import market_ohlc_response
from entry import Default as CoreDefault


class _DirectCronMessage:
    """Adapt a Cron Trigger into the existing single-message capture contract."""

    def __init__(self, *, scheduled_time: object, cron: object) -> None:
        self.body = {"scheduledTime": scheduled_time, "cron": cron}
        self.acked = False

    def ack(self) -> None:
        self.acked = True

    def retry(self, *, delaySeconds: int | None = None) -> None:
        del delaySeconds
        # Queue retries do not exist on a direct Cron Trigger. Surface the capture
        # failure so Cloudflare records the scheduled event as failed; the next
        # deterministic Cron tick is the safe retry boundary.
        raise RuntimeError("aidy_direct_cron_capture_retry_requested")


class _DirectCronBatch:
    def __init__(self, message: _DirectCronMessage) -> None:
        self.messages = [message]


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

    async def scheduled(self, controller, env, ctx):
        """Run capture directly from Cloudflare Cron without Queue operations.

        The mature queue consumer remains the single capture implementation. This
        adapter reuses it in-process, eliminating Queue write/read/delete usage and
        stale-backlog risk while preserving exactly the same recorder semantics.
        """
        message = _DirectCronMessage(
            scheduled_time=controller.scheduledTime,
            cron=controller.cron,
        )
        await super().queue(_DirectCronBatch(message), env, ctx)
        if not message.acked:
            raise RuntimeError("aidy_direct_cron_capture_not_acknowledged")

    async def queue(self, batch, env, ctx):
        """Retain the Queue ABI for safe rollback; production has no Queue consumer."""
        return await super().queue(batch, env, ctx)
