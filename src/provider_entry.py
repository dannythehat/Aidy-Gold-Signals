from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import urlparse

from workers import Response

from aidy.config import AidySettings
from aidy.data_health import collect_and_record_data_health, collect_data_health
from aidy.provider_calibration_api import calibration_market_ohlc_response
from aidy.provider_context_api import provider_context_response
from aidy.provider_data_health_api import provider_data_health_response
from aidy.provider_market_api import market_ohlc_response
from aidy.provider_memory_api import provider_memory_response
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


def _bool_env(env: object, name: str, default: str = "false") -> bool:
    return str(getattr(env, name, default)).strip().lower() in {"1", "true", "yes", "on"}


async def _public_health_response(env: object):
    """Production health must describe the brain, not merely the Worker process."""

    settings = AidySettings.from_worker_env(env)
    try:
        data_health = await collect_data_health(
            env.AIDY_OPS,
            now=datetime.now(UTC),
            capture_enabled=settings.capture_enabled,
            market_data_source=settings.market_data_source,
            scheduler="direct-cron",
        )
        health_summary = {
            "status": data_health.status,
            "alert": data_health.alert,
            "reason": data_health.reason,
            "session_open": data_health.session_open,
            "latest_scheduled_success_utc": data_health.latest_scheduled_success_utc,
            "latest_provider_context_snapshot_utc": (
                data_health.latest_provider_context_snapshot_utc
            ),
            "success_lag_seconds": data_health.success_lag_seconds,
            "provider_context_snapshot_lag_seconds": (
                data_health.provider_context_snapshot_lag_seconds
            ),
            "health_version": data_health.health_version,
        }
        overall_status = "degraded" if data_health.alert else "ok"
    except Exception as exc:  # noqa: BLE001 - public health must fail visibly, not crash
        health_summary = {
            "status": "monitor_error",
            "alert": True,
            "reason": "AIDY data-health evidence could not be read",
            "exception_type": type(exc).__name__,
            "message": str(exc)[:300],
        }
        overall_status = "degraded"

    return Response.json(
        {
            "service": "aidy-signals",
            "status": overall_status,
            "runtime": "cloudflare-workers",
            "environment": str(getattr(env, "AIDY_ENV", "unknown")),
            "capture_enabled": settings.capture_enabled,
            "formal_forward_enabled": _bool_env(env, "AIDY_FORMAL_FORWARD_ENABLED"),
            "private_forward_model_gateway_configured": bool(
                str(getattr(env, "OPENAI_API_KEY", "")).strip()
            ),
            "market_data_source": settings.market_data_source,
            "market_data_ownership": settings.market_data_ownership,
            "cross_market_source": "public_official_daily",
            "scheduler": "direct-cron",
            "data_health": health_summary,
        }
    )


async def _record_health_best_effort(env: object, *, scheduler: str) -> None:
    """Observability may report a failure but must never undo a successful capture."""

    try:
        settings = AidySettings.from_worker_env(env)
        await collect_and_record_data_health(
            env.AIDY_OPS,
            now=datetime.now(UTC),
            capture_enabled=settings.capture_enabled,
            market_data_source=settings.market_data_source,
            scheduler=scheduler,
        )
    except Exception as exc:  # noqa: BLE001 - capture is more important than telemetry
        print(f"AIDY data-health telemetry failed: {type(exc).__name__}: {str(exc)[:500]}")


class Default(CoreDefault):
    async def fetch(self, request):
        path = urlparse(request.url).path
        if request.method == "GET" and path == "/health":
            return await _public_health_response(self.env)
        if path == "/market/ohlc":
            return await market_ohlc_response(request, self.env)
        if path == "/calibration/market/ohlc":
            return await calibration_market_ohlc_response(request, self.env)
        if path == "/provider/context":
            return await provider_context_response(request, self.env)
        if path == "/provider/data-health":
            return await provider_data_health_response(request, self.env)
        if path == "/provider/memory":
            return await provider_memory_response(request, self.env)
        return await super().fetch(request)

    async def scheduled(self, controller, env, ctx):
        """Run capture directly from Cloudflare Cron without Queue operations.

        Cloudflare's Python scheduled ABI can pass ``env`` as None; bindings live on
        ``self.env`` just as the core queue consumer already expects.  Always use
        the bound Worker environment for telemetry so a successful capture also
        leaves a durable point-in-time health observation.
        """
        message = _DirectCronMessage(
            scheduled_time=controller.scheduledTime,
            cron=controller.cron,
        )
        try:
            await super().queue(_DirectCronBatch(message), env, ctx)
        finally:
            await _record_health_best_effort(self.env, scheduler="direct-cron")
        if not message.acked:
            raise RuntimeError("aidy_direct_cron_capture_not_acknowledged")

    async def queue(self, batch, env, ctx):
        """Retain the Queue ABI for safe rollback; production has no Queue consumer."""
        try:
            return await super().queue(batch, env, ctx)
        finally:
            await _record_health_best_effort(self.env, scheduler="queue-consumer")