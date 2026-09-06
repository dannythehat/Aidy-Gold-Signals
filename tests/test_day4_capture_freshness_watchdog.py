from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from aidy.twelve_data_market import gold_session_is_open as canonical_gold_session_is_open

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "aidy_capture_freshness_watchdog.py"


def _load_watchdog():
    spec = importlib.util.spec_from_file_location("aidy_capture_freshness_watchdog", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


watchdog = _load_watchdog()


@pytest.mark.parametrize(
    "moment",
    [
        datetime(2026, 3, 6, 21, 59, tzinfo=UTC),
        datetime(2026, 3, 8, 21, 59, tzinfo=UTC),
        datetime(2026, 3, 8, 22, 0, tzinfo=UTC),
        datetime(2026, 3, 9, 21, 0, tzinfo=UTC),
        datetime(2026, 3, 9, 22, 0, tzinfo=UTC),
        datetime(2026, 11, 1, 22, 59, tzinfo=UTC),
        datetime(2026, 11, 1, 23, 0, tzinfo=UTC),
        datetime(2026, 11, 2, 22, 0, tzinfo=UTC),
        datetime(2026, 11, 2, 23, 0, tzinfo=UTC),
        datetime(2026, 9, 6, 12, 45, tzinfo=UTC),
        datetime(2026, 9, 6, 22, 0, tzinfo=UTC),
        datetime(2026, 9, 11, 20, 59, tzinfo=UTC),
        datetime(2026, 9, 11, 21, 0, tzinfo=UTC),
    ],
)
def test_watchdog_calendar_matches_canonical_aidy_calendar(moment: datetime) -> None:
    assert watchdog.gold_session_is_open(moment) is canonical_gold_session_is_open(moment)


def test_closed_session_never_false_alerts_on_old_capture() -> None:
    now = datetime(2026, 9, 6, 12, 45, tzinfo=UTC)  # Sunday before 18:00 New York.
    row = {
        "latest_scheduled_success_utc": (now - timedelta(days=2)).isoformat(),
        "latest_scheduled_request_utc": (now - timedelta(days=2)).isoformat(),
        "latest_scheduled_request_status": "succeeded",
    }
    result = watchdog.evaluate(now=now, row=row)
    assert result.status == "session_closed"
    assert result.alert is False


def test_reopen_grace_prevents_false_alert() -> None:
    now = datetime(2026, 9, 6, 22, 7, tzinfo=UTC)  # Sunday 18:07 New York.
    result = watchdog.evaluate(now=now, row={})
    assert result.status == "open_grace"
    assert result.alert is False


def test_open_session_alerts_when_capture_is_stale() -> None:
    now = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)
    row = {
        "latest_scheduled_success_utc": (now - timedelta(minutes=16)).isoformat(),
        "latest_scheduled_request_utc": (now - timedelta(minutes=1)).isoformat(),
        "latest_scheduled_request_status": "failed",
        "latest_scheduled_error_code": "synthetic_failure",
    }
    result = watchdog.evaluate(now=now, row=row, stale_seconds=900)
    assert result.status == "stale"
    assert result.alert is True
    assert result.success_lag_seconds == 960
    assert result.latest_scheduled_request_status == "failed"


def test_open_session_is_fresh_inside_threshold() -> None:
    now = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)
    row = {
        "latest_scheduled_success_utc": (now - timedelta(minutes=6)).isoformat(),
        "latest_scheduled_request_utc": (now - timedelta(minutes=6)).isoformat(),
        "latest_scheduled_request_status": "succeeded",
    }
    result = watchdog.evaluate(now=now, row=row, stale_seconds=900)
    assert result.status == "fresh"
    assert result.alert is False
    assert result.success_lag_seconds == 360


def test_open_session_without_any_success_alerts_after_grace() -> None:
    now = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)
    result = watchdog.evaluate(now=now, row={}, stale_seconds=900)
    assert result.status == "stale"
    assert result.alert is True
    assert result.latest_scheduled_success_utc is None
