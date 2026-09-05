from __future__ import annotations

import base64
import binascii
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from aidy.twelve_data_market import expected_market_minute_opens

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
    except (TypeError, ValueError) as exc:
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
    except (ValueError, TypeError, OverflowError, binascii.Error, InvalidSignature):
        return False
    return True


def _latest_revisions(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: dict[str, dict[str, Any]] = {}
    for row in rows:
        opened_dt = _utc_iso(str(row.get("open_time_utc") or ""), name="open_time_utc")
        if opened_dt.second or opened_dt.microsecond:
            raise ValueError("Admitted M1 open_time_utc must be minute-aligned.")
        opened = opened_dt.isoformat()
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


async def market_ohlc_response(request: Any, env: Any, *, now: datetime | None = None) -> Any:
    """Serve admitted PIT-safe M1 OHLC plus continuity/provenance, read-only and bounded."""
    from workers import Response

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
    if start.second or start.microsecond or end.second or end.microsecond:
        return Response.json({"ok": False, "error": "window_not_minute_aligned"}, status=400)
    if end - start > MAX_WINDOW:
        return Response.json(
            {"ok": False, "error": "window_too_large", "max_window_hours": 48}, status=413
        )

    cutoff = end.isoformat()
    result = await env.AIDY_OPS.prepare(
        """
        SELECT open_time_utc,open,high,low,close,revision_index,first_observed_at,payload_digest
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

    selected = _latest_revisions(rows)
    expected = [value.isoformat() for value in expected_market_minute_opens(start, end)]
    expected_set = set(expected)
    bars: list[dict[str, str | int]] = []
    actual: set[str] = set()
    try:
        for row in selected:
            opened = _utc_iso(str(row["open_time_utc"]), name="open_time_utc").isoformat()
            if opened not in expected_set:
                raise ValueError("admitted_off_session_or_unexpected_minute")
            first_observed = _utc_iso(
                str(row["first_observed_at"]), name="first_observed_at"
            ).isoformat()
            if first_observed > cutoff:
                raise ValueError("admitted_row_exceeds_pit_cutoff")
            digest = str(row.get("payload_digest") or "").strip().lower()
            if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
                raise ValueError("admitted_row_missing_payload_digest")
            actual.add(opened)
            bars.append(
                {
                    "open_time_utc": opened,
                    "open": str(row["open"]),
                    "high": str(row["high"]),
                    "low": str(row["low"]),
                    "close": str(row["close"]),
                    "revision_index": int(row.get("revision_index") or 0),
                    "first_observed_at": first_observed,
                    "payload_digest": digest,
                }
            )
    except (KeyError, TypeError, ValueError) as exc:
        return Response.json(
            {"ok": False, "error": "market_evidence_invalid", "message": str(exc)}, status=503
        )

    missing = [opened for opened in expected if opened not in actual]
    return Response.json(
        {
            "ok": True,
            "symbol": "XAUUSD",
            "timeframe": "1m",
            "from": start.isoformat(),
            "to": end.isoformat(),
            "row_count": len(bars),
            "expected_row_count": len(expected),
            "complete": not missing,
            "expected_open_times": expected,
            "missing_open_times": missing,
            "bars": bars,
        }
    )
