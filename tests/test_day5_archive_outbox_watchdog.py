from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "aidy_archive_outbox_watchdog.py"


def _load():
    spec = importlib.util.spec_from_file_location("aidy_archive_outbox_watchdog", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


watchdog = _load()


def test_empty_pending_sample_is_healthy() -> None:
    now = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)
    result = watchdog.evaluate(now=now, rows=[])
    assert result.status == "healthy"
    assert result.alert is False
    assert result.pending_sample_count == 0


def test_recent_pending_item_is_not_false_alert() -> None:
    now = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)
    rows = [
        {
            "outbox_kind": "gold",
            "id": "a",
            "record_type": "snapshot",
            "archive_key": "gold/snapshots/a.json",
            "attempts": 0,
            "last_error": None,
            "created_at": (now - timedelta(minutes=3)).isoformat(),
        }
    ]
    result = watchdog.evaluate(now=now, rows=rows)
    assert result.status == "pending_recent"
    assert result.alert is False
    assert result.oldest_pending_age_seconds == 180


def test_old_pending_item_alerts_even_without_retry() -> None:
    now = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)
    rows = [
        {
            "outbox_kind": "gold",
            "id": "a",
            "record_type": "snapshot",
            "archive_key": "gold/snapshots/a.json",
            "attempts": 0,
            "last_error": None,
            "created_at": (now - timedelta(minutes=16)).isoformat(),
        }
    ]
    result = watchdog.evaluate(now=now, rows=rows, max_pending_age_seconds=900)
    assert result.status == "stale"
    assert result.alert is True
    assert result.oldest_pending_age_seconds == 960


def test_poison_attempt_threshold_alerts_before_age_threshold() -> None:
    now = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)
    rows = [
        {
            "outbox_kind": "gold",
            "id": "poison",
            "record_type": "snapshot",
            "archive_key": "gold/snapshots/poison.json",
            "attempts": 3,
            "last_error": "archive_error:RuntimeError",
            "created_at": (now - timedelta(minutes=4)).isoformat(),
        }
    ]
    result = watchdog.evaluate(now=now, rows=rows, poison_attempts=3)
    assert result.status == "poison"
    assert result.alert is True
    assert result.poison_count == 1
    assert result.retrying_count == 1
    assert result.max_attempts == 3


def test_cross_market_and_gold_counts_are_kept_separate() -> None:
    now = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)
    rows = [
        {
            "outbox_kind": "gold",
            "id": "g",
            "record_type": "snapshot",
            "archive_key": "gold/a.json",
            "attempts": 1,
            "last_error": "archive_error:TimeoutError",
            "created_at": (now - timedelta(minutes=2)).isoformat(),
        },
        {
            "outbox_kind": "cross_market",
            "id": "x",
            "record_type": "cross_market",
            "archive_key": "cross/a.json",
            "attempts": 0,
            "last_error": None,
            "created_at": (now - timedelta(minutes=1)).isoformat(),
        },
    ]
    result = watchdog.evaluate(now=now, rows=rows)
    assert result.alert is False
    assert result.gold_pending_count == 1
    assert result.cross_market_pending_count == 1
    assert result.retrying_count == 1


def test_sample_truncation_is_fail_closed() -> None:
    now = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)
    result = watchdog.evaluate(now=now, rows=[], sample_truncated=True)
    assert result.status == "sample_truncated"
    assert result.alert is True


def test_worst_items_prioritize_attempts_then_age() -> None:
    now = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)
    rows = [
        {
            "outbox_kind": "gold",
            "id": "old",
            "record_type": "snapshot",
            "archive_key": "old",
            "attempts": 1,
            "last_error": "x",
            "created_at": (now - timedelta(minutes=20)).isoformat(),
        },
        {
            "outbox_kind": "gold",
            "id": "many",
            "record_type": "snapshot",
            "archive_key": "many",
            "attempts": 3,
            "last_error": "x",
            "created_at": (now - timedelta(minutes=2)).isoformat(),
        },
    ]
    result = watchdog.evaluate(now=now, rows=rows)
    assert result.worst_items[0]["id"] == "many"
