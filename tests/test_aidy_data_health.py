from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from aidy.data_health import (
    HEALTH_VERSION,
    collect_data_health,
    evaluate_data_health,
    recent_data_health_events,
    record_data_health,
)

ROOT = Path(__file__).resolve().parents[1]


class Prepared:
    def __init__(self, db: "LocalD1", sql: str, params=()) -> None:
        self.db = db
        self.sql = sql
        self.params = params

    def bind(self, *params):
        return Prepared(self.db, self.sql, params)

    async def first(self):
        cursor = self.db.connection.execute(self.sql, self.params)
        row = cursor.fetchone()
        return None if row is None else dict(row)

    async def all(self):
        cursor = self.db.connection.execute(self.sql, self.params)
        return {"results": [dict(row) for row in cursor.fetchall()]}

    async def run(self):
        self.db.connection.execute(self.sql, self.params)
        self.db.connection.commit()
        return {"success": True}


class LocalD1:
    def __init__(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        for migration in (
            "migrations/d1/0001_aidy_ops.sql",
            "migrations/d1/0002_cross_market_evidence.sql",
            "migrations/d1/0007_twelve_data_quota_bootstrap.sql",
            "migrations/d1/0012_live_gold_free_tier_read_budget.sql",
            "migrations/d1/0014_archive_delivery_state.sql",
            "migrations/d1/0017_aidy_data_health_events.sql",
        ):
            self.connection.executescript((ROOT / migration).read_text(encoding="utf-8"))

    def prepare(self, sql: str) -> Prepared:
        return Prepared(self, sql)


def _fresh_facts(now: datetime) -> dict[str, object]:
    return {
        "latest_scheduled_success_utc": (now - timedelta(minutes=5)).isoformat(),
        "latest_scheduled_request_utc": (now - timedelta(minutes=5)).isoformat(),
        "latest_scheduled_request_status": "succeeded",
        "latest_scheduled_error_code": None,
        "latest_provider_context_snapshot_utc": (now - timedelta(minutes=4)).isoformat(),
        "archive_pending_count": 0,
        "archive_backoff_count": 0,
        "archive_dead_letter_count": 0,
        "oldest_archive_unarchived_utc": None,
        "cross_market_archive_pending_count": 0,
        "cross_market_archive_backoff_count": 0,
        "cross_market_archive_dead_letter_count": 0,
        "oldest_cross_market_archive_unarchived_utc": None,
        "latest_cross_market_first_observed_at": None,
        "latest_macro_event_first_observed_at": None,
    }


def test_closed_gold_session_is_not_false_stale() -> None:
    now = datetime(2026, 9, 13, 7, 0, tzinfo=UTC)  # Sunday before NY reopen
    facts = _fresh_facts(now)
    facts["latest_scheduled_success_utc"] = (now - timedelta(days=2)).isoformat()
    facts["latest_provider_context_snapshot_utc"] = (now - timedelta(days=2)).isoformat()
    result = evaluate_data_health(
        now=now,
        facts=facts,
        capture_enabled=True,
        market_data_source="twelve_data",
        scheduler="direct-cron",
    )
    assert result.status == "session_closed"
    assert result.alert is False
    assert result.session_open is False


def test_open_session_stale_capture_alerts() -> None:
    now = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)
    facts = _fresh_facts(now)
    facts["latest_scheduled_success_utc"] = (now - timedelta(minutes=16)).isoformat()
    result = evaluate_data_health(
        now=now,
        facts=facts,
        capture_enabled=True,
        market_data_source="twelve_data",
        scheduler="direct-cron",
    )
    assert result.status == "stale_capture"
    assert result.alert is True
    assert result.success_lag_seconds == 960


def test_latest_failed_capture_is_visible_immediately() -> None:
    now = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)
    facts = _fresh_facts(now)
    facts["latest_scheduled_request_utc"] = (now - timedelta(minutes=1)).isoformat()
    facts["latest_scheduled_request_status"] = "failed"
    facts["latest_scheduled_error_code"] = "synthetic_failure"
    result = evaluate_data_health(
        now=now,
        facts=facts,
        capture_enabled=True,
        market_data_source="twelve_data",
        scheduler="direct-cron",
    )
    assert result.status == "capture_failed"
    assert result.alert is True
    assert result.latest_scheduled_error_code == "synthetic_failure"


def test_archive_backlog_alerts_even_while_gold_is_closed() -> None:
    now = datetime(2026, 9, 13, 7, 0, tzinfo=UTC)
    facts = _fresh_facts(now)
    facts["archive_pending_count"] = 12
    facts["oldest_archive_unarchived_utc"] = (now - timedelta(hours=2)).isoformat()
    result = evaluate_data_health(
        now=now,
        facts=facts,
        capture_enabled=True,
        market_data_source="twelve_data",
        scheduler="direct-cron",
    )
    assert result.status == "archive_backlog"
    assert result.alert is True
    assert result.oldest_archive_unarchived_age_seconds == 7200


def test_fresh_open_session_is_green_only_with_capture_and_context() -> None:
    now = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)
    result = evaluate_data_health(
        now=now,
        facts=_fresh_facts(now),
        capture_enabled=True,
        market_data_source="twelve_data",
        scheduler="direct-cron",
    )
    assert result.status == "fresh"
    assert result.alert is False
    assert result.health_version == HEALTH_VERSION


@pytest.mark.asyncio
async def test_d1_health_is_append_only_and_hub_readable(monkeypatch) -> None:
    monkeypatch.chdir(ROOT)
    db = LocalD1()
    now = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)
    success = now - timedelta(minutes=5)
    context = now - timedelta(minutes=4)

    db.connection.execute(
        """
        INSERT INTO twelve_data_request_ledger(
          id,requested_at_utc,completed_at_utc,endpoint,symbol,interval,outputsize,
          request_kind,status,internal_accounted_credits
        ) VALUES (?,?,?,?,?,?,?,?,?,?)
        """,
        (
            "request-1",
            success.isoformat(),
            success.isoformat(),
            "time_series",
            "XAU/USD",
            "1min",
            30,
            "scheduled_capture",
            "succeeded",
            1,
        ),
    )
    db.connection.execute(
        """
        INSERT INTO market_snapshots(
          id,captured_at,symbol,capture_status,session_code,position_state_json,
          data_availability_json,event_observation_ids_json,snapshot_digest,archive_key,
          market_data_source
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            "snapshot-1",
            context.isoformat(),
            "XAUUSD",
            "complete",
            "ny",
            None,
            '{"request_kind":"scheduled_capture","request_ledger_status":"succeeded"}',
            "[]",
            "a" * 64,
            "snapshots/snapshot-1.json",
            "twelve_data",
        ),
    )
    db.connection.commit()

    current = await collect_data_health(
        db,
        now=now,
        capture_enabled=True,
        market_data_source="twelve_data",
        scheduler="direct-cron",
    )
    assert current.status == "fresh"

    first_id = await record_data_health(db, current)
    second_id = await record_data_health(db, current)
    assert first_id != second_id
    count = db.connection.execute("SELECT COUNT(*) FROM aidy_data_health_events").fetchone()[0]
    assert count == 2

    history = await recent_data_health_events(db, limit=10)
    assert len(history) == 2
    assert history[0]["status"] == "fresh"
    assert history[0]["alert"] is False
    assert history[0]["checks"]["market_capture"]["required"] is True


def test_phase_a_migration_and_production_entry_are_point_in_time_safe() -> None:
    migration = (ROOT / "migrations/d1/0017_aidy_data_health_events.sql").read_text(
        encoding="utf-8"
    )
    entry = (ROOT / "src/provider_entry.py").read_text(encoding="utf-8")
    assert "aidy_data_health_events" in migration
    assert "observed_at_utc" in migration
    assert "checks_json" in migration
    assert 'path == "/provider/data-health"' in entry
    assert '"scheduler": "direct-cron"' in entry
    assert "collect_and_record_data_health" in entry
    # Cloudflare's Python scheduled ABI passes env=None in production; bindings are on self.env.
    assert 'await _record_health_best_effort(self.env, scheduler="direct-cron")' in entry
    assert 'await _record_health_best_effort(self.env, scheduler="queue-consumer")' in entry
    assert 'await _record_health_best_effort(env, scheduler="direct-cron")' not in entry
