"""Cheap, bounded health surface for Provider Intelligence market capture.

The Worker can report D1-backed capture continuity without scanning historical tables.
Cloudflare Analytics rows-read usage is intentionally supplied by the external budget
monitor; the Worker does not receive an account-wide Cloudflare API credential.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

from .twelve_data_market import RAW_M1_SOURCE, expected_market_minute_opens, gold_session_is_open
from .twelve_data_storage import D1TwelveDataMarketStore

MAX_HEALTH_WINDOW = timedelta(hours=6)
LAST_CAPTURE_LOOKBACK = timedelta(days=7)
REQUEST_LOOKBACK = timedelta(hours=24)
DEFAULT_D1_ROWS_READ_ALERT_THRESHOLD = 3_250_000
DEFAULT_D1_ROWS_READ_FREE_LIMIT = 5_000_000


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Provider Intelligence health timestamps must be timezone-aware.")
    return value.astimezone(UTC)


def _row(value: object) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return dict(value)
    try:
        return dict(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise TypeError("Unexpected D1 health row shape.") from exc


def _results(value: object) -> list[dict[str, Any]]:
    rows = getattr(value, "results", None)
    if rows is None and isinstance(value, dict):
        rows = value.get("results")
    if rows is None:
        return []
    out: list[dict[str, Any]] = []
    for item in rows:
        parsed = _row(item)
        if parsed is not None:
            out.append(parsed)
    return out


def _iso_minute(value: datetime) -> str:
    return _utc(value).replace(second=0, microsecond=0).isoformat()


def _parse_iso(value: str, *, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a valid ISO-8601 timestamp.") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must be timezone-aware.")
    if parsed.second or parsed.microsecond:
        raise ValueError(f"{field} must be minute-aligned.")
    return parsed.astimezone(UTC)


def _budget_state(rows_read: int | None, *, threshold: int, free_limit: int) -> dict[str, object]:
    if rows_read is None:
        state = "external_measurement_required"
    elif rows_read >= free_limit:
        state = "free_limit_exceeded"
    elif rows_read >= threshold:
        state = "alarm"
    else:
        state = "ok"
    return {
        "measurement_source": "cloudflare_graphql_external_monitor",
        "rows_read": rows_read,
        "alert_threshold": threshold,
        "free_limit_reference": free_limit,
        "state": state,
    }


def _retry_state(requests: list[dict[str, Any]]) -> dict[str, object]:
    if not requests:
        return {"state": "no_recent_request", "consecutive_failures": 0, "latest_error": None}
    consecutive_failures = 0
    for row in requests:
        if str(row.get("status") or "") == "failed":
            consecutive_failures += 1
        else:
            break
    latest = requests[0]
    latest_status = str(latest.get("status") or "unknown")
    recovered = latest_status == "succeeded" and any(
        str(row.get("status") or "") == "failed" for row in requests[1:]
    )
    if latest_status == "failed":
        state = "retry_expected"
    elif recovered:
        state = "recovered_after_failure"
    elif latest_status == "succeeded":
        state = "healthy"
    else:
        state = latest_status
    return {
        "state": state,
        "consecutive_failures": consecutive_failures,
        "latest_status": latest_status,
        "latest_error": latest.get("error_code"),
        "latest_requested_at": latest.get("requested_at_utc"),
        "latest_completed_at": latest.get("completed_at_utc"),
    }


async def build_capture_health(
    d1: Any,
    *,
    start_utc: datetime,
    end_utc: datetime,
    now: datetime,
    d1_rows_read: int | None = None,
    d1_alert_threshold: int = DEFAULT_D1_ROWS_READ_ALERT_THRESHOLD,
    d1_free_limit: int = DEFAULT_D1_ROWS_READ_FREE_LIMIT,
) -> dict[str, object]:
    """Build one bounded health snapshot from indexed D1 reads."""

    start = _utc(start_utc)
    end = _utc(end_utc)
    observed_now = _utc(now)
    if end <= start:
        raise ValueError("health window end must be after start")
    if end - start > MAX_HEALTH_WINDOW:
        raise ValueError("health window exceeds six-hour bound")
    if end > observed_now + timedelta(minutes=1):
        raise ValueError("health window may not extend into the future")

    store = D1TwelveDataMarketStore(d1)
    admitted_rows = await store.latest_m1_bars(start_utc=start, end_utc=end)
    expected = tuple(expected_market_minute_opens(start, end))
    expected_iso = [_iso_minute(value) for value in expected]
    observed_iso = {
        _iso_minute(datetime.fromisoformat(str(row["open_time_utc"]))) for row in admitted_rows
    }
    missing = [value for value in expected_iso if value not in observed_iso]

    lookback_start = observed_now - LAST_CAPTURE_LOOKBACK
    last_row = _row(
        await d1.prepare(
            """
            SELECT open_time_utc,first_observed_at,revision_index
            FROM market_candles
            WHERE symbol=? AND timeframe='1m' AND source=?
              AND open_time_utc>=? AND open_time_utc<?
            ORDER BY open_time_utc DESC,revision_index DESC
            LIMIT 1
            """
        ).bind(
            "XAUUSD",
            RAW_M1_SOURCE,
            lookback_start.isoformat(),
            observed_now.isoformat(),
        ).first()
    )

    request_start = observed_now - REQUEST_LOOKBACK
    request_result = await d1.prepare(
        """
        SELECT requested_at_utc,completed_at_utc,status,error_code,request_kind
        FROM twelve_data_request_ledger
        WHERE requested_at_utc>=? AND requested_at_utc<?
          AND request_kind='scheduled_capture'
        ORDER BY requested_at_utc DESC
        LIMIT 8
        """
    ).bind(request_start.isoformat(), observed_now.isoformat()).all()
    requests = _results(request_result)

    archive_result = await d1.prepare(
        """
        SELECT status,COUNT(*) AS n,MAX(attempts) AS max_attempts
        FROM archive_outbox
        WHERE status IN ('pending','archived') AND created_at>=? AND created_at<?
        GROUP BY status
        """
    ).bind(request_start.isoformat(), observed_now.isoformat()).all()
    archive_rows = _results(archive_result)
    archive = {
        str(row.get("status")): {
            "count": int(row.get("n") or 0),
            "max_attempts": int(row.get("max_attempts") or 0),
        }
        for row in archive_rows
    }

    market_open = gold_session_is_open(observed_now)
    if not market_open:
        live_gap_gate = "waiting_market_open"
    elif missing:
        live_gap_gate = "gap_detected"
    elif not expected:
        live_gap_gate = "waiting_nontrivial_open_window"
    else:
        live_gap_gate = "green"

    return {
        "ok": not missing or not market_open,
        "market_open_now": market_open,
        "window": {
            "from": start.isoformat(),
            "to": end.isoformat(),
            "max_hours": int(MAX_HEALTH_WINDOW.total_seconds() // 3600),
        },
        "capture": {
            "last_m1_captured_minute": None if last_row is None else last_row.get("open_time_utc"),
            "last_m1_first_observed_at": None if last_row is None else last_row.get("first_observed_at"),
            "expected_minutes": len(expected_iso),
            "observed_minutes": len(observed_iso & set(expected_iso)),
            "unexpected_missing_minutes": missing,
            "live_gap_gate": live_gap_gate,
            "retry": _retry_state(requests),
        },
        "archive_r2_outbox_24h": archive,
        "d1_rows_read_budget": _budget_state(
            d1_rows_read,
            threshold=int(d1_alert_threshold),
            free_limit=int(d1_free_limit),
        ),
        "query_policy": {
            "selected_window_bounded": True,
            "last_capture_lookback_days": int(LAST_CAPTURE_LOOKBACK.total_seconds() // 86400),
            "recent_request_lookback_hours": int(REQUEST_LOOKBACK.total_seconds() // 3600),
            "unbounded_history_scan": False,
        },
    }


async def capture_health_response(request: Any, env: Any, *, now: datetime | None = None) -> Any:
    """Bearer-protected Provider Intelligence health route."""

    from workers import Response
    from .provider_market_api import _authorized

    if request.method != "GET":
        return Response("Method not allowed", status=405)
    if not _authorized(request, env):
        return Response("Unauthorized", status=401)

    observed_now = _utc(now or datetime.now(UTC)).replace(second=0, microsecond=0)
    params = parse_qs(urlparse(request.url).query, keep_blank_values=True)
    raw_from = str(params.get("from", [""])[0]).strip()
    raw_to = str(params.get("to", [""])[0]).strip()
    try:
        end = _parse_iso(raw_to, field="to") if raw_to else observed_now
        start = _parse_iso(raw_from, field="from") if raw_from else end - MAX_HEALTH_WINDOW
        rows_read_raw = str(getattr(env, "AIDY_D1_ROWS_READ_LAST_MEASURED", "") or "").strip()
        rows_read = int(rows_read_raw) if rows_read_raw else None
        threshold = int(
            str(getattr(env, "D1_ROWS_READ_ALERT_THRESHOLD", DEFAULT_D1_ROWS_READ_ALERT_THRESHOLD))
        )
        free_limit = int(str(getattr(env, "D1_ROWS_READ_FREE_LIMIT", DEFAULT_D1_ROWS_READ_FREE_LIMIT)))
        payload = await build_capture_health(
            env.AIDY_OPS,
            start_utc=start,
            end_utc=end,
            now=observed_now,
            d1_rows_read=rows_read,
            d1_alert_threshold=threshold,
            d1_free_limit=free_limit,
        )
    except (TypeError, ValueError) as exc:
        return Response.json({"ok": False, "error": "invalid_health_window", "message": str(exc)}, status=400)
    return Response.json(payload, status=200 if bool(payload.get("ok")) else 503)
