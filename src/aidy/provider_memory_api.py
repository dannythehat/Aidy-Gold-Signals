"""Authenticated Provider/Hub view of AIDY's permanent episode memory."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

from workers import Response

from .episode_memory import memory_snapshot
from .provider_market_api import _authorized


def _query(request: Any) -> tuple[datetime, int]:
    params = parse_qs(urlparse(request.url).query, keep_blank_values=True)
    raw_as_of = str(params.get("as_of", [""])[0]).strip()
    if raw_as_of:
        try:
            as_of = datetime.fromisoformat(raw_as_of)
        except ValueError as exc:
            raise ValueError("as_of must be valid ISO-8601.") from exc
        if as_of.tzinfo is None:
            raise ValueError("as_of must be timezone-aware.")
        as_of = as_of.astimezone(UTC)
    else:
        as_of = datetime.now(UTC)

    raw_limit = str(params.get("limit", ["25"])[0]).strip()
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError) as exc:
        raise ValueError("limit must be an integer.") from exc
    return as_of, max(1, min(limit, 100))


async def provider_memory_response(request: Any, env: Any) -> Any:
    if request.method != "GET":
        return Response("Method not allowed", status=405)
    if not _authorized(request, env):
        return Response("Unauthorized", status=401)
    try:
        as_of, limit = _query(request)
    except ValueError as exc:
        return Response.json({"ok": False, "error": "invalid_query", "message": str(exc)}, status=400)

    try:
        snapshot = await memory_snapshot(env.AIDY_OPS, as_of_utc=as_of, limit=limit)
    except Exception as exc:  # noqa: BLE001 - Hub diagnostic route must fail closed
        return Response.json(
            {
                "ok": False,
                "error": "episode_memory_store_unavailable",
                "exception_type": type(exc).__name__,
                "message": str(exc)[:500],
            },
            status=503,
        )

    return Response.json({"ok": True, "memory": snapshot})
