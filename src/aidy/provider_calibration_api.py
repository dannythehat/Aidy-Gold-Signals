from __future__ import annotations

from datetime import UTC, timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

from aidy.provider_market_api import _authorized, _results, _utc_iso
from aidy.twelve_data_market import expected_market_minute_opens

MAX_WINDOW = timedelta(hours=48)
MAX_M1_ROWS = 3500
SOURCE_KIND = "calibration_backfill"
SOURCE_PROVIDER = "twelve_data"


def _flag_false(value: object) -> bool:
    return str(value).strip().lower() in {"0", "false"}


def _flag_true(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true"}


async def calibration_market_ohlc_response(request: Any, env: Any) -> Any:
    """Serve only frozen retrospective Day 11 calibration windows.

    This endpoint never reads market_candles or decision-admitted views. Every returned row
    must be Twelve Data calibration_backfill evidence with pit_eligible=false,
    research_only=true and live_money_execution_allowed=false.
    """
    from workers import Response

    if request.method != "GET":
        return Response("Method not allowed", status=405)
    if not _authorized(request, env):
        return Response("Unauthorized", status=401)

    url = urlparse(request.url)
    params = parse_qs(url.query, keep_blank_values=True)
    window_id = str(params.get("window_id", [""])[0]).strip()
    symbol = str(params.get("symbol", [""])[0]).strip().upper().replace("/", "")
    timeframe = str(params.get("timeframe", [""])[0]).strip().lower()
    raw_from = str(params.get("from", [""])[0]).strip()
    raw_to = str(params.get("to", [""])[0]).strip()
    if not window_id or symbol != "XAUUSD" or timeframe != "1m":
        return Response.json({"ok": False, "error": "unsupported_calibration_request"}, status=400)

    try:
        start = _utc_iso(raw_from, name="from")
        end = _utc_iso(raw_to, name="to")
    except ValueError as exc:
        return Response.json({"ok": False, "error": "invalid_window", "message": str(exc)}, status=400)
    if start >= end or start.second or start.microsecond or end.second or end.microsecond:
        return Response.json({"ok": False, "error": "invalid_window"}, status=400)
    if end - start > MAX_WINDOW:
        return Response.json({"ok": False, "error": "window_too_large"}, status=413)

    window_result = await env.AIDY_OPS.prepare(
        """
        SELECT window_id,window_from,window_to,source_kind,source_provider,pit_eligible,
               research_only,live_money_execution_allowed,status,expected_row_count,
               observed_row_count,missing_row_count,fetched_at_utc,response_digest
        FROM provider_calibration_backfill_windows
        WHERE window_id=?
        LIMIT 1
        """
    ).bind(window_id).all()
    windows = _results(window_result)
    if len(windows) != 1:
        return Response.json({"ok": False, "error": "calibration_window_not_found"}, status=404)
    window = windows[0]

    try:
        stored_from = _utc_iso(str(window["window_from"]), name="window_from")
        stored_to = _utc_iso(str(window["window_to"]), name="window_to")
        if stored_from != start or stored_to != end:
            raise ValueError("requested_window_does_not_match_frozen_manifest")
        if str(window.get("source_kind")) != SOURCE_KIND:
            raise ValueError("calibration_source_kind_invalid")
        if str(window.get("source_provider")) != SOURCE_PROVIDER:
            raise ValueError("calibration_source_provider_invalid")
        if not _flag_false(window.get("pit_eligible")):
            raise ValueError("calibration_row_became_pit_eligible")
        if not _flag_true(window.get("research_only")):
            raise ValueError("calibration_row_not_research_only")
        if not _flag_false(window.get("live_money_execution_allowed")):
            raise ValueError("calibration_row_allows_live_money")
    except (KeyError, TypeError, ValueError) as exc:
        return Response.json(
            {"ok": False, "error": "calibration_boundary_invalid", "message": str(exc)}, status=503
        )

    rows_result = await env.AIDY_OPS.prepare(
        """
        SELECT open_time_utc,open,high,low,close,first_observed_at,payload_digest,
               source_kind,source_provider,pit_eligible,research_only,live_money_execution_allowed
        FROM provider_calibration_m1_backfill
        WHERE open_time_utc>=? AND open_time_utc<?
          AND source_kind='calibration_backfill'
          AND source_provider='twelve_data'
          AND pit_eligible=0
          AND research_only=1
          AND live_money_execution_allowed=0
        ORDER BY open_time_utc
        LIMIT ?
        """
    ).bind(start.isoformat(), end.isoformat(), MAX_M1_ROWS + 1).all()
    rows = _results(rows_result)
    if len(rows) > MAX_M1_ROWS:
        return Response.json({"ok": False, "error": "m1_row_bound_exceeded"}, status=413)

    expected = [value.isoformat() for value in expected_market_minute_opens(start, end)]
    expected_set = set(expected)
    actual: set[str] = set()
    bars: list[dict[str, str | int | bool]] = []
    try:
        for row in rows:
            opened_dt = _utc_iso(str(row["open_time_utc"]), name="open_time_utc")
            if opened_dt.second or opened_dt.microsecond:
                raise ValueError("calibration_open_not_minute_aligned")
            opened = opened_dt.isoformat()
            if opened not in expected_set:
                raise ValueError("calibration_off_session_or_unexpected_minute")
            digest = str(row.get("payload_digest") or "").strip().lower()
            if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
                raise ValueError("calibration_payload_digest_invalid")
            first_observed = _utc_iso(
                str(row["first_observed_at"]), name="first_observed_at"
            ).astimezone(UTC).isoformat()
            actual.add(opened)
            bars.append(
                {
                    "open_time_utc": opened,
                    "open": str(row["open"]),
                    "high": str(row["high"]),
                    "low": str(row["low"]),
                    "close": str(row["close"]),
                    "revision_index": 0,
                    "first_observed_at": first_observed,
                    "payload_digest": digest,
                    "source_kind": SOURCE_KIND,
                    "source_provider": SOURCE_PROVIDER,
                    "pit_eligible": False,
                    "research_only": True,
                    "live_money_execution_allowed": False,
                }
            )
    except (KeyError, TypeError, ValueError) as exc:
        return Response.json(
            {"ok": False, "error": "calibration_evidence_invalid", "message": str(exc)}, status=503
        )

    missing = [opened for opened in expected if opened not in actual]
    return Response.json(
        {
            "ok": True,
            "symbol": "XAUUSD",
            "timeframe": "1m",
            "from": start.isoformat(),
            "to": end.isoformat(),
            "window_id": window_id,
            "source_kind": SOURCE_KIND,
            "source_provider": SOURCE_PROVIDER,
            "pit_eligible": False,
            "research_only": True,
            "live_money_execution_allowed": False,
            "row_count": len(bars),
            "expected_row_count": len(expected),
            "complete": not missing,
            "expected_open_times": expected,
            "missing_open_times": missing,
            "bars": bars,
        }
    )
