"""AIDY production capture-freshness watchdog.

Consumes the tiny JSON result from a bounded Cloudflare D1 query and decides whether
scheduled Twelve Data capture is fresh enough for the current gold session.

This script is deliberately stdlib-only so the recurring GitHub Actions watchdog does
not need to install the AIDY runtime or make market-data/broker calls.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

NEW_YORK = ZoneInfo("America/New_York")
SESSION_CALENDAR_VERSION = "aidy_gold_session_calendar_ny_v1"
DEFAULT_STALE_SECONDS = 900
DEFAULT_OPEN_GRACE_SECONDS = 900


@dataclass
class WatchdogDiagnostic:
    status: str
    alert: bool
    reason: str
    observed_at_utc: str
    session_calendar_version: str
    session_open: bool
    session_opened_at_utc: str | None
    latest_scheduled_success_utc: str | None
    latest_scheduled_request_utc: str | None
    latest_scheduled_request_status: str | None
    latest_scheduled_error_code: str | None
    success_lag_seconds: int | None
    stale_after_seconds: int
    open_grace_seconds: int


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("watchdog datetimes must be timezone-aware")
    return value.astimezone(UTC)


def _parse_datetime(value: object | None) -> datetime | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def gold_session_is_open(value: datetime) -> bool:
    """Mirror AIDY's canonical CME-style gold calendar.

    Open Sunday 18:00 through Friday 17:00 New York, with the daily
    17:00-18:00 New York maintenance break.
    """

    local = _utc(value).astimezone(NEW_YORK)
    weekday = local.weekday()
    wall = local.time().replace(tzinfo=None)
    if weekday == 5:
        return False
    if weekday == 6:
        return wall >= time(18, 0)
    if weekday == 4:
        return wall < time(17, 0)
    return wall < time(17, 0) or wall >= time(18, 0)


def current_session_open_utc(value: datetime) -> datetime | None:
    """Return the start of the current uninterrupted open segment."""

    now = _utc(value)
    if not gold_session_is_open(now):
        return None
    local = now.astimezone(NEW_YORK)
    wall = local.time().replace(tzinfo=None)

    if wall >= time(18, 0):
        local_open = datetime.combine(local.date(), time(18, 0), tzinfo=NEW_YORK)
        return local_open.astimezone(UTC)

    previous = local.date() - timedelta(days=1)
    local_open = datetime.combine(previous, time(18, 0), tzinfo=NEW_YORK)
    return local_open.astimezone(UTC)


def _extract_first_result(payload: object) -> dict[str, Any]:
    """Accept Wrangler D1 --json output or a direct object used by tests."""

    if isinstance(payload, dict):
        if any(key in payload for key in ("latest_scheduled_success_utc", "latest_success")):
            return dict(payload)
        results = payload.get("results")
        if isinstance(results, list) and results:
            row = results[0]
            if isinstance(row, dict):
                return dict(row)
    if isinstance(payload, list):
        for item in payload:
            if not isinstance(item, dict):
                continue
            results = item.get("results")
            if isinstance(results, list) and results:
                row = results[0]
                if isinstance(row, dict):
                    return dict(row)
    return {}


def evaluate(
    *,
    now: datetime,
    row: dict[str, Any],
    stale_seconds: int = DEFAULT_STALE_SECONDS,
    open_grace_seconds: int = DEFAULT_OPEN_GRACE_SECONDS,
) -> WatchdogDiagnostic:
    if stale_seconds < 60:
        raise ValueError("stale_seconds must be >= 60")
    if open_grace_seconds < 0:
        raise ValueError("open_grace_seconds must be >= 0")

    observed = _utc(now)
    session_open = gold_session_is_open(observed)
    session_opened = current_session_open_utc(observed)
    latest_success = _parse_datetime(
        row.get("latest_scheduled_success_utc", row.get("latest_success"))
    )
    latest_request = _parse_datetime(
        row.get("latest_scheduled_request_utc", row.get("latest_request"))
    )
    latest_status_raw = row.get("latest_scheduled_request_status", row.get("latest_status"))
    latest_status = None if latest_status_raw is None else str(latest_status_raw)
    latest_error_raw = row.get("latest_scheduled_error_code", row.get("latest_error_code"))
    latest_error = None if latest_error_raw is None else str(latest_error_raw)

    lag_seconds = None
    if latest_success is not None:
        lag_seconds = max(0, int((observed - latest_success).total_seconds()))

    if not session_open:
        return WatchdogDiagnostic(
            status="session_closed",
            alert=False,
            reason="capture freshness is not required while the canonical gold session is closed",
            observed_at_utc=observed.isoformat(),
            session_calendar_version=SESSION_CALENDAR_VERSION,
            session_open=False,
            session_opened_at_utc=None,
            latest_scheduled_success_utc=None if latest_success is None else latest_success.isoformat(),
            latest_scheduled_request_utc=None if latest_request is None else latest_request.isoformat(),
            latest_scheduled_request_status=latest_status,
            latest_scheduled_error_code=latest_error,
            success_lag_seconds=lag_seconds,
            stale_after_seconds=stale_seconds,
            open_grace_seconds=open_grace_seconds,
        )

    assert session_opened is not None
    open_age = int((observed - session_opened).total_seconds())
    if open_age < open_grace_seconds:
        return WatchdogDiagnostic(
            status="open_grace",
            alert=False,
            reason="gold session has reopened but is still inside the capture startup grace window",
            observed_at_utc=observed.isoformat(),
            session_calendar_version=SESSION_CALENDAR_VERSION,
            session_open=True,
            session_opened_at_utc=session_opened.isoformat(),
            latest_scheduled_success_utc=None if latest_success is None else latest_success.isoformat(),
            latest_scheduled_request_utc=None if latest_request is None else latest_request.isoformat(),
            latest_scheduled_request_status=latest_status,
            latest_scheduled_error_code=latest_error,
            success_lag_seconds=lag_seconds,
            stale_after_seconds=stale_seconds,
            open_grace_seconds=open_grace_seconds,
        )

    if latest_success is None:
        return WatchdogDiagnostic(
            status="stale",
            alert=True,
            reason="gold session is open and no successful scheduled Twelve capture is recorded",
            observed_at_utc=observed.isoformat(),
            session_calendar_version=SESSION_CALENDAR_VERSION,
            session_open=True,
            session_opened_at_utc=session_opened.isoformat(),
            latest_scheduled_success_utc=None,
            latest_scheduled_request_utc=None if latest_request is None else latest_request.isoformat(),
            latest_scheduled_request_status=latest_status,
            latest_scheduled_error_code=latest_error,
            success_lag_seconds=None,
            stale_after_seconds=stale_seconds,
            open_grace_seconds=open_grace_seconds,
        )

    assert lag_seconds is not None
    if lag_seconds > stale_seconds:
        return WatchdogDiagnostic(
            status="stale",
            alert=True,
            reason="successful scheduled Twelve capture is older than the allowed open-session lag",
            observed_at_utc=observed.isoformat(),
            session_calendar_version=SESSION_CALENDAR_VERSION,
            session_open=True,
            session_opened_at_utc=session_opened.isoformat(),
            latest_scheduled_success_utc=latest_success.isoformat(),
            latest_scheduled_request_utc=None if latest_request is None else latest_request.isoformat(),
            latest_scheduled_request_status=latest_status,
            latest_scheduled_error_code=latest_error,
            success_lag_seconds=lag_seconds,
            stale_after_seconds=stale_seconds,
            open_grace_seconds=open_grace_seconds,
        )

    return WatchdogDiagnostic(
        status="fresh",
        alert=False,
        reason="scheduled Twelve capture is fresh for the open gold session",
        observed_at_utc=observed.isoformat(),
        session_calendar_version=SESSION_CALENDAR_VERSION,
        session_open=True,
        session_opened_at_utc=session_opened.isoformat(),
        latest_scheduled_success_utc=latest_success.isoformat(),
        latest_scheduled_request_utc=None if latest_request is None else latest_request.isoformat(),
        latest_scheduled_request_status=latest_status,
        latest_scheduled_error_code=latest_error,
        success_lag_seconds=lag_seconds,
        stale_after_seconds=stale_seconds,
        open_grace_seconds=open_grace_seconds,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--d1-json", required=True, help="Wrangler D1 --json output file")
    parser.add_argument("--diagnostic", required=True, help="Diagnostic JSON output file")
    parser.add_argument("--now", help="Override observation time with an ISO-8601 timestamp")
    parser.add_argument("--stale-seconds", type=int, default=DEFAULT_STALE_SECONDS)
    parser.add_argument("--open-grace-seconds", type=int, default=DEFAULT_OPEN_GRACE_SECONDS)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        now = _parse_datetime(args.now) if args.now else datetime.now(UTC)
        assert now is not None
        payload = json.loads(Path(args.d1_json).read_text(encoding="utf-8"))
        row = _extract_first_result(payload)
        diagnostic = evaluate(
            now=now,
            row=row,
            stale_seconds=args.stale_seconds,
            open_grace_seconds=args.open_grace_seconds,
        )
        output = asdict(diagnostic)
        target = Path(args.diagnostic)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(output, sort_keys=True))
        return 2 if diagnostic.alert else 0
    except Exception as exc:  # noqa: BLE001 - CLI must emit a deterministic failure.
        print(f"watchdog_error={type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
