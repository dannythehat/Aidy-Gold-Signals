"""AIDY production capture and Provider Context freshness watchdog.

Consumes a tiny bounded D1 heartbeat and verifies two independent facts:
1. scheduled Twelve Data capture is still succeeding; and
2. those captures are still producing complete snapshots eligible for Provider Context.

The script is stdlib-only so the recurring watchdog remains cheap and independent of
AIDY runtime imports.
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
    latest_provider_context_snapshot_utc: str | None
    success_lag_seconds: int | None
    provider_context_snapshot_lag_seconds: int | None
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
    """Mirror AIDY's canonical CME-style gold calendar."""

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
    if isinstance(payload, dict):
        if any(key in payload for key in ("latest_scheduled_success_utc", "latest_success")):
            return dict(payload)
        results = payload.get("results")
        if isinstance(results, list) and results and isinstance(results[0], dict):
            return dict(results[0])
    if isinstance(payload, list):
        for item in payload:
            if not isinstance(item, dict):
                continue
            results = item.get("results")
            if isinstance(results, list) and results and isinstance(results[0], dict):
                return dict(results[0])
    return {}


def _diagnostic(
    *,
    status: str,
    alert: bool,
    reason: str,
    observed: datetime,
    session_open: bool,
    session_opened: datetime | None,
    latest_success: datetime | None,
    latest_request: datetime | None,
    latest_status: str | None,
    latest_error: str | None,
    latest_context_snapshot: datetime | None,
    success_lag: int | None,
    snapshot_lag: int | None,
    stale_seconds: int,
    open_grace_seconds: int,
) -> WatchdogDiagnostic:
    return WatchdogDiagnostic(
        status=status,
        alert=alert,
        reason=reason,
        observed_at_utc=observed.isoformat(),
        session_calendar_version=SESSION_CALENDAR_VERSION,
        session_open=session_open,
        session_opened_at_utc=None if session_opened is None else session_opened.isoformat(),
        latest_scheduled_success_utc=None if latest_success is None else latest_success.isoformat(),
        latest_scheduled_request_utc=None if latest_request is None else latest_request.isoformat(),
        latest_scheduled_request_status=latest_status,
        latest_scheduled_error_code=latest_error,
        latest_provider_context_snapshot_utc=(
            None if latest_context_snapshot is None else latest_context_snapshot.isoformat()
        ),
        success_lag_seconds=success_lag,
        provider_context_snapshot_lag_seconds=snapshot_lag,
        stale_after_seconds=stale_seconds,
        open_grace_seconds=open_grace_seconds,
    )


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
    latest_context_snapshot = _parse_datetime(row.get("latest_provider_context_snapshot_utc"))
    latest_status_raw = row.get("latest_scheduled_request_status", row.get("latest_status"))
    latest_status = None if latest_status_raw is None else str(latest_status_raw)
    latest_error_raw = row.get("latest_scheduled_error_code", row.get("latest_error_code"))
    latest_error = None if latest_error_raw is None else str(latest_error_raw)

    success_lag = (
        None if latest_success is None else max(0, int((observed - latest_success).total_seconds()))
    )
    snapshot_lag = (
        None
        if latest_context_snapshot is None
        else max(0, int((observed - latest_context_snapshot).total_seconds()))
    )

    common = {
        "observed": observed,
        "latest_success": latest_success,
        "latest_request": latest_request,
        "latest_status": latest_status,
        "latest_error": latest_error,
        "latest_context_snapshot": latest_context_snapshot,
        "success_lag": success_lag,
        "snapshot_lag": snapshot_lag,
        "stale_seconds": stale_seconds,
        "open_grace_seconds": open_grace_seconds,
    }

    if not session_open:
        return _diagnostic(
            status="session_closed",
            alert=False,
            reason="capture freshness is not required while the canonical gold session is closed",
            session_open=False,
            session_opened=None,
            **common,
        )

    assert session_opened is not None
    if int((observed - session_opened).total_seconds()) < open_grace_seconds:
        return _diagnostic(
            status="open_grace",
            alert=False,
            reason="gold session has reopened but is still inside the capture startup grace window",
            session_open=True,
            session_opened=session_opened,
            **common,
        )

    if latest_success is None:
        return _diagnostic(
            status="stale_capture",
            alert=True,
            reason="gold session is open and no successful scheduled Twelve capture is recorded",
            session_open=True,
            session_opened=session_opened,
            **common,
        )

    assert success_lag is not None
    if success_lag > stale_seconds:
        return _diagnostic(
            status="stale_capture",
            alert=True,
            reason="successful scheduled Twelve capture is older than the allowed open-session lag",
            session_open=True,
            session_opened=session_opened,
            **common,
        )

    if latest_context_snapshot is None:
        return _diagnostic(
            status="stale_provider_context",
            alert=True,
            reason="scheduled Twelve capture is fresh but no complete Provider Context snapshot exists",
            session_open=True,
            session_opened=session_opened,
            **common,
        )

    assert snapshot_lag is not None
    if snapshot_lag > stale_seconds:
        return _diagnostic(
            status="stale_provider_context",
            alert=True,
            reason=(
                "scheduled Twelve capture is fresh but the latest complete Provider Context "
                "snapshot is older than the allowed open-session lag"
            ),
            session_open=True,
            session_opened=session_opened,
            **common,
        )

    return _diagnostic(
        status="fresh",
        alert=False,
        reason="scheduled Twelve capture and complete Provider Context snapshot are both fresh",
        session_open=True,
        session_opened=session_opened,
        **common,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--d1-json", required=True, help="D1 JSON heartbeat file")
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
        diagnostic = evaluate(
            now=now,
            row=_extract_first_result(payload),
            stale_seconds=args.stale_seconds,
            open_grace_seconds=args.open_grace_seconds,
        )
        output = asdict(diagnostic)
        target = Path(args.diagnostic)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(output, sort_keys=True))
        return 2 if diagnostic.alert else 0
    except Exception as exc:  # noqa: BLE001
        print(f"watchdog_error={type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
