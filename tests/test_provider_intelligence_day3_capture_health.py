from __future__ import annotations

import sys
import types
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

# Cloudflare's workers package imports the Pyodide-only ``js`` module on CPython.
# The queue test exercises our Python handler logic only, so supply the tiny ABI surface
# entry.py needs instead of pretending the full Workers runtime exists in GitHub Actions.
_workers = types.ModuleType("workers")
_workers.Response = type("Response", (), {})
_workers.WorkerEntrypoint = type("WorkerEntrypoint", (), {})
sys.modules.setdefault("workers", _workers)

import entry as worker_entry
from aidy.provider_intelligence_health import build_capture_health


class _Result:
    def __init__(self, rows):
        self.results = rows


class _Statement:
    def __init__(self, db, sql: str):
        self.db = db
        self.sql = sql
        self.params = ()

    def bind(self, *params):
        self.params = params
        self.db.calls.append((self.sql, params))
        return self

    async def all(self):
        if "WITH scheduled AS" in self.sql:
            return _Result(self.db.admitted_rows)
        if "FROM twelve_data_request_ledger" in self.sql:
            return _Result(self.db.request_rows)
        if "FROM archive_outbox" in self.sql:
            return _Result(self.db.archive_rows)
        raise AssertionError(f"unexpected all query: {self.sql}")

    async def first(self):
        if "FROM market_candles" in self.sql:
            return self.db.last_capture_row
        raise AssertionError(f"unexpected first query: {self.sql}")


class _D1:
    def __init__(self, *, admitted_rows=None, request_rows=None, archive_rows=None, last_capture_row=None):
        self.admitted_rows = list(admitted_rows or [])
        self.request_rows = list(request_rows or [])
        self.archive_rows = list(archive_rows or [])
        self.last_capture_row = last_capture_row
        self.calls = []

    def prepare(self, sql: str):
        return _Statement(self, sql)


def _bar(opened: str):
    return {
        "id": opened,
        "open_time_utc": opened,
        "open": "1",
        "high": "1",
        "low": "1",
        "close": "1",
        "revision_index": 1,
        "payload_digest": "a" * 64,
        "first_observed_at": opened,
    }


@pytest.mark.asyncio
async def test_closed_market_never_turns_zero_expected_minutes_into_green() -> None:
    now = datetime(2026, 9, 6, 10, 0, tzinfo=UTC)
    db = _D1(
        request_rows=[{
            "requested_at_utc": "2026-09-06T09:55:00+00:00",
            "completed_at_utc": "2026-09-06T09:55:01+00:00",
            "status": "succeeded",
            "error_code": None,
            "request_kind": "scheduled_capture",
        }],
        archive_rows=[{"status": "archived", "n": 3, "max_attempts": 1}],
    )
    health = await build_capture_health(
        db,
        start_utc=datetime(2026, 9, 6, 4, 0, tzinfo=UTC),
        end_utc=now,
        now=now,
        d1_rows_read=200_000,
    )
    assert health["market_open_now"] is False
    assert health["capture"]["expected_minutes"] == 0
    assert health["capture"]["unexpected_missing_minutes"] == []
    assert health["capture"]["live_gap_gate"] == "waiting_market_open"
    assert health["d1_rows_read_budget"]["state"] == "ok"


@pytest.mark.asyncio
async def test_missing_minute_inside_real_open_window_is_a_true_gap() -> None:
    opens = [
        "2026-09-06T22:00:00+00:00",
        "2026-09-06T22:01:00+00:00",
        "2026-09-06T22:03:00+00:00",
        "2026-09-06T22:04:00+00:00",
    ]
    db = _D1(
        admitted_rows=[_bar(value) for value in opens],
        request_rows=[{
            "requested_at_utc": "2026-09-06T22:05:00+00:00",
            "completed_at_utc": "2026-09-06T22:05:02+00:00",
            "status": "succeeded",
            "error_code": None,
            "request_kind": "scheduled_capture",
        }],
        last_capture_row={
            "open_time_utc": "2026-09-06T22:04:00+00:00",
            "first_observed_at": "2026-09-06T22:05:02+00:00",
            "revision_index": 1,
        },
    )
    health = await build_capture_health(
        db,
        start_utc=datetime(2026, 9, 6, 22, 0, tzinfo=UTC),
        end_utc=datetime(2026, 9, 6, 22, 5, tzinfo=UTC),
        now=datetime(2026, 9, 6, 22, 5, tzinfo=UTC),
        d1_rows_read=100,
    )
    assert health["market_open_now"] is True
    assert health["capture"]["expected_minutes"] == 5
    assert health["capture"]["observed_minutes"] == 4
    assert health["capture"]["unexpected_missing_minutes"] == ["2026-09-06T22:02:00+00:00"]
    assert health["capture"]["live_gap_gate"] == "gap_detected"
    assert health["ok"] is False


@pytest.mark.asyncio
async def test_recent_failed_capture_followed_by_success_is_reported_recovered() -> None:
    now = datetime(2026, 9, 6, 10, 0, tzinfo=UTC)
    db = _D1(request_rows=[
        {
            "requested_at_utc": "2026-09-06T09:55:00+00:00",
            "completed_at_utc": "2026-09-06T09:55:01+00:00",
            "status": "succeeded",
            "error_code": None,
            "request_kind": "scheduled_capture",
        },
        {
            "requested_at_utc": "2026-09-06T09:50:00+00:00",
            "completed_at_utc": "2026-09-06T09:50:02+00:00",
            "status": "failed",
            "error_code": "controlled_test_failure",
            "request_kind": "scheduled_capture",
        },
    ])
    health = await build_capture_health(
        db,
        start_utc=datetime(2026, 9, 6, 9, 0, tzinfo=UTC),
        end_utc=now,
        now=now,
    )
    retry = health["capture"]["retry"]
    assert retry["state"] == "recovered_after_failure"
    assert retry["latest_status"] == "succeeded"
    assert retry["consecutive_failures"] == 0


@pytest.mark.asyncio
async def test_every_health_query_is_time_bounded_and_small() -> None:
    now = datetime(2026, 9, 6, 10, 0, tzinfo=UTC)
    db = _D1()
    await build_capture_health(
        db,
        start_utc=datetime(2026, 9, 6, 9, 0, tzinfo=UTC),
        end_utc=now,
        now=now,
    )
    assert db.calls
    for sql, params in db.calls:
        normalized = " ".join(sql.split()).lower()
        assert "limit" in normalized or "group by status" in normalized
        assert ">=?" in normalized and "<?" in normalized
        assert len(params) >= 2


@pytest.mark.asyncio
async def test_queue_retry_then_success_ack_is_non_destructive(monkeypatch) -> None:
    settings = SimpleNamespace(capture_enabled=True)
    monkeypatch.setattr(worker_entry.AidySettings, "from_worker_env", staticmethod(lambda _env: settings))

    class _Operational:
        async def prune_archived_hot_data(self, *, now):
            raise AssertionError("minute 01 should not enter hourly prune")

    monkeypatch.setattr(worker_entry, "_repository", lambda _env: (_Operational(), object()))
    monkeypatch.setattr(worker_entry, "_market_runtime_dependencies", lambda _env, _settings: (None, None))

    attempts = {"n": 0}

    async def _cycle(*args, **kwargs):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise RuntimeError("controlled_non_destructive_failure")
        return SimpleNamespace(market=None)

    async def _no_error_write(*args, **kwargs):
        return None

    monkeypatch.setattr(worker_entry, "run_worker_scheduled_cycle", _cycle)
    monkeypatch.setattr(worker_entry, "_write_test_queue_error", _no_error_write)

    class _Message:
        def __init__(self):
            scheduled = datetime(2026, 9, 6, 8, 1, tzinfo=UTC)
            self.body = {"scheduledTime": scheduled.timestamp() * 1000.0, "cron": "* * * * *"}
            self.retry_calls = []
            self.ack_calls = 0

        def retry(self, **kwargs):
            self.retry_calls.append(kwargs)

        def ack(self):
            self.ack_calls += 1

    message = _Message()
    batch = SimpleNamespace(messages=[message])
    fake_self = SimpleNamespace(env=SimpleNamespace(AIDY_ENV="test"))

    await worker_entry.Default.queue(fake_self, batch, None, None)
    assert message.retry_calls == [{"delaySeconds": 30}]
    assert message.ack_calls == 0

    await worker_entry.Default.queue(fake_self, batch, None, None)
    assert message.retry_calls == [{"delaySeconds": 30}]
    assert message.ack_calls == 1
    assert attempts["n"] == 2
