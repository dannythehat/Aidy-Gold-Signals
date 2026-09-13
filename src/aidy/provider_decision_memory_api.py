"""Authenticated read-only AIDY decision-memory API for the future Hub."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

from workers import Response

from .episode_memory import D1EpisodeMemoryStore
from .provider_market_api import _authorized


def _limit(request: Any) -> int:
    raw = parse_qs(urlparse(request.url).query).get("limit", ["20"])[0]
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 20
    return max(1, min(value, 100))


async def provider_decision_memory_response(request: Any, env: Any) -> Any:
    if request.method != "GET":
        return Response("Method not allowed", status=405)
    if not _authorized(request, env):
        return Response("Unauthorized", status=401)

    store = D1EpisodeMemoryStore(env.AIDY_OPS)
    now = datetime.now(UTC)
    try:
        summary = await store.summary(as_of_utc=now)
        cards = await store.recent_learning_cards(
            as_of_utc=now,
            limit=_limit(request),
            score_eligible_only=False,
        )
    except Exception as exc:  # noqa: BLE001 - protected diagnostic route fails closed
        return Response.json(
            {
                "ok": False,
                "error": "decision_memory_store_unavailable",
                "exception_type": type(exc).__name__,
                "message": str(exc)[:500],
            },
            status=503,
        )

    return Response.json(
        {
            "ok": True,
            "summary": summary,
            "recent_learning_cards": cards,
            "recent_learning_card_count": len(cards),
        }
    )
