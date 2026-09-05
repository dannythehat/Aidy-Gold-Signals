from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from workers import Response

PROVIDER_CLIENT = "super-signals-provider-lab"
PROVIDER_PUBLIC_KEY_B64URL = "itdRZAC8u-1N5NWEwqvMWtRT6WK4PeeyEpzIh4TDQ2w"
MAX_AUTH_SKEW_SECONDS = 300
MAX_WINDOW = timedelta(hours=48)
MAX_M1_ROWS = 3500


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _utc_iso(value: str, *, name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a valid ISO-8601 timestamp.") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware.")
    return parsed.astimezone(UTC)


def _row(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    try:
        return dict(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise TypeError("Unexpected D1 row shape.") from exc


def _results(value: object) -> list[dict[str, Any]]:
    rows = getattr(value, "results", None)
    if rows is None and isinstance(value, dict):
        rows = value.get("results")
    if rows is None:
        return []
    return [_row(item) for item in rows]


def _signing_payload(*, path: str, raw_query: str, timestamp: str, client: str) -> bytes:
    return f"GET\n{path}\n{raw_query}\n{timestamp}\n{client}".encode()


def _authorized(request: Any, *, now: datetime | None = None) -> bool:
    client = str(request.headers.get("X-AIDY-Client") or "").strip()
    timestamp = str(request.headers.get("X-AIDY-Timestamp") or "").strip()
    signature = str(request.headers.get("X-AIDY-Signature") or "").strip()
    if client != PROVIDER_CLIENT or not timestamp or not signature:
        return False
    try:
        signed_at = datetime.fromtimestamp(int(timestamp), tz=UTC)
        observed_at = (now or datetime.now(UTC)).astimezone(UTC)
        if abs((observed_at - signed_at).total_seconds()) > MAX_AUTH_SKEW_SECONDS:
            return False
        url = urlparse(request.url)
        public_key = Ed25519PublicKey.from_public_bytes(_b64url_decode(PROVIDER_PUBLIC_KEY_B64URL))
        public_key.verify(
            _b64url_decode(signature),
            _signing_payload(
                path=url.path,
                raw_query=url.query,
                timestamp=timestamp,
                client=client,
            ),
        )
    except (ValueError, InvalidSignature):
        return False
    return True


def _latest_revisions(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: dict[str, dict[str, Any]] = {}
    for row in rows:
        opened = str(row.get("open_time_utc") or "")
        if not opened:
            raise ValueError("Admitted market row lacks open_time_utc.")
        current = selected.get(opened)
        rank = (int(row.get("revision_index") or 0), str(row.get("first_observed_at") or ""))
        if current is None:
            selected[opened] = row
            continue
        current_rank = (
            int(current.get("revision_index") or 0),
            str(current.get("first_observed_at") or ""),
        )
        if rank > current_rank:
            selected[opened] = row
    return [selected[key] for key in sorted(selected)]


async def market_ohlc_response(request: Any, env: Any, *, now: datetime | None = None) -> Response:
    """Serve only admitted PIT-safe M1 OHLC through a bounded read-only interface."""

    if request.method != "GET":
        return Response("Method not allowed", status=405)
    if not _authorized(request, now=now):
        return Response("Unauthorized", status=401)

    url = urlparse(request.url)
    params = parse_qs(url.query, keep_blank_values=True)
    symbol = str(params.get("symbol", [""])[0]).strip().upper().replace("/", "")
    timeframe = str(params.get("timeframe", [""])[0]).strip().lower()
    raw_from = str(params.get("from", [""])[0]).strip()
    raw_to = str(params.get("to", [""])[0]).strip()
    if symbol != "XAUUSD" or timeframe != "1m":
        return Response.json({"ok": False, "error": "unsupported_market_request"}, status=400)

    try:
        start = _utc_iso(raw_from, name="from")
        end = _utc_iso(raw_to, name="to")
    except ValueError as exc:
        return Response.json({"ok": False, "error": "invalid_window", "message": str(exc)}, status=400)
    if start >= end:
        return Response.json({"ok": False, "error": "invalid_window"}, status=400)
    if end - start > MAX_WINDOW:
        return Response.json(
            {"ok": False, "error": "window_too_large", "max_window_hours": 48}, status=413
        )

    cutoff = end.isoformat()
    result = await env.AIDY_OPS.prepare(
        """
        SELECT open_time_utc,open,high,low,close,revision_index,first_observed_at
        FROM twelve_data_decision_admitted_m1_v1
        WHERE open_time_utc>=? AND open_time_utc<? AND first_observed_at<=?
        ORDER BY open_time_utc,revision_index
        LIMIT ?
        """
    ).bind(start.isoformat(), cutoff, cutoff, MAX_M1_ROWS + 1).all()
    rows = _results(result)
    if len(rows) > MAX_M1_ROWS:
        return Response.json(
            {"ok": False, "error": "m1_row_bound_exceeded", "max_rows": MAX_M1_ROWS},
            status=413,
        )

    admitted = _latest_revisions(rows)
    bars = [
        {
            "open_time_utc": str(row["open_time_utc"]),
            "open": str(row["open"]),
            "high": str(row["high"]),
            "low": str(row["low"]),
            "close": str(row["close"]),
        }
        for row in admitted
    ]
    return Response.json(
        {
            "ok": True,
            "symbol": "XAUUSD",
            "timeframe": "1m",
            "from": start.isoformat(),
            "to": end.isoformat(),
            "row_count": len(bars),
            "bars": bars,
        }
    )
