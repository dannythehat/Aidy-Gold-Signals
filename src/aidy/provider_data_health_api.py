"""Authenticated Provider/Hub data-health API."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

from workers import Response

from .config import AidySettings
from .data_health import collect_data_health, recent_data_health_events
from .provider_market_api import _authorized


def _history_limit(request: Any) -> int:
    raw = parse_qs(urlparse(request.url).query).get("limit", ["120"])[0]
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 120
    return max(1, min(value, 500))


async def provider_data_health_response(request: Any, env: Any) -> Any:
    if request.method != "GET":
        return Response("Method not allowed", status=405)
    if not _authorized(request, env):
        return Response("Unauthorized", status=401)

    settings = AidySettings.from_worker_env(env)
    try:
        current = await collect_data_health(
            env.AIDY_OPS,
            now=datetime.now(UTC),
            capture_enabled=settings.capture_enabled,
            market_data_source=settings.market_data_source,
            scheduler="direct-cron",
        )
        history = await recent_data_health_events(env.AIDY_OPS, limit=_history_limit(request))
    except Exception as exc:  # noqa: BLE001 - authenticated diagnostic endpoint must fail closed
        return Response.json(
            {
                "ok": False,
                "error": "data_health_store_unavailable",
                "exception_type": type(exc).__name__,
                "message": str(exc)[:500],
            },
            status=503,
        )

    return Response.json(
        {
            "ok": True,
            "current": current.to_dict(),
            "history": history,
            "history_count": len(history),
        }
    )
