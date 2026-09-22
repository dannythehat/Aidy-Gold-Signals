"""Tests for the scheduled Build-24 shadow loop watchdog.

The watchdog exists because the learning loop can stall silently: the
singleton health row is overwritten on every sync, so the 2026-09-21
135-minute gap had to be reconstructed from market_snapshots. These tests
pin the conditions that must raise an alert.
"""
from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "aidy_shadow_loop_watchdog",
    Path(__file__).resolve().parents[1] / "scripts" / "aidy_shadow_loop_watchdog.py",
)
assert _SPEC and _SPEC.loader
watchdog = importlib.util.module_from_spec(_SPEC)
sys.modules["aidy_shadow_loop_watchdog"] = watchdog
_SPEC.loader.exec_module(watchdog)

NOW = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)


def _row(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "latest_cycle_decided_at_utc": (NOW - timedelta(minutes=12)).isoformat(),
        "total_cycles": 41,
        "health_observed_at_utc": (NOW - timedelta(minutes=2)).isoformat(),
        "health_status": "ok",
        "health_error_type": None,
        "health_error_message": None,
        "expected_gate_n": 15,
        "known_gate_n": 10,
    }
    base.update(overrides)
    return base


def _run(monkeypatch: pytest.MonkeyPatch, row: dict[str, object]) -> int:
    monkeypatch.setattr(watchdog, "_query", lambda _sql: row)

    class _FrozenNow(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW if tz is None else NOW.astimezone(tz)

    monkeypatch.setattr(watchdog, "datetime", _FrozenNow)
    return watchdog.main()


def test_healthy_loop_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _run(monkeypatch, _row()) == 0


def test_stalled_loop_is_detected(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 135-minute gap passed unnoticed in production. A longer stall must not."""
    stalled = _row(
        latest_cycle_decided_at_utc=(NOW - timedelta(minutes=400)).isoformat()
    )
    assert _run(monkeypatch, stalled) == 1


def test_recorded_sync_error_is_detected(monkeypatch: pytest.MonkeyPatch) -> None:
    """A raised expert builder loses a whole cycle; it must not pass silently."""
    errored = _row(
        health_status="error",
        health_error_type="ValueError",
        health_error_message="neutral gate conclusion requires a known neutral subcalculator",
    )
    assert _run(monkeypatch, errored) == 1


def test_stale_health_is_detected(monkeypatch: pytest.MonkeyPatch) -> None:
    stale = _row(health_observed_at_utc=(NOW - timedelta(minutes=90)).isoformat())
    assert _run(monkeypatch, stale) == 1


def test_unexpected_gate_count_is_detected(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _run(monkeypatch, _row(expected_gate_n=14)) == 1


def test_never_recorded_loop_is_detected(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _run(monkeypatch, _row(latest_cycle_decided_at_utc=None)) == 1
