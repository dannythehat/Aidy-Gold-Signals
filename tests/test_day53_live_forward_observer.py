from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from aidy.forward_evaluation import digest
from aidy.forward_live_observer import (
    FORWARD_OBSERVATION_INTERVAL_SECONDS,
    day53_live_forward_manifest,
    live_forward_status,
    observe_private_forward_snapshot,
)
from aidy.forward_start_amendment import (
    D1ImmediateForwardEvaluationStore,
    build_amended_frozen_version_manifest,
)

ROOT = Path(__file__).resolve().parents[1]
ACTIVATED = datetime(2026, 9, 1, 16, 35, tzinfo=UTC)
SCHEDULED = datetime(2026, 9, 1, 16, 40, tzinfo=UTC)
OBSERVED = SCHEDULED + timedelta(seconds=4)


class Prepared:
    def __init__(self, db: LocalD1, sql: str, params=()) -> None:
        self.db = db
        self.sql = sql
        self.params = params

    def bind(self, *params):
        return Prepared(self.db, self.sql, params)

    async def first(self):
        row = self.db.connection.execute(self.sql, self.params).fetchone()
        return dict(row) if row is not None else None

    async def all(self):
        rows = self.db.connection.execute(self.sql, self.params).fetchall()
        return {"results": [dict(row) for row in rows]}

    async def run(self):
        self.db.connection.execute(self.sql, self.params)
        self.db.connection.commit()
        return {"success": True}


class LocalD1:
    def __init__(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        for migration in sorted((ROOT / "migrations" / "d1").glob("*.sql")):
            self.connection.executescript(migration.read_text())

    def prepare(self, sql: str) -> Prepared:
        return Prepared(self, sql)


def _components() -> dict:
    names = (
        "day52_runtime",
        "openai_gateway_v2",
        "self_consistency_v2",
        "immutable_decision_ledger",
        "selective_abstention_shadow",
        "gc_xau_shadow",
        "macro_surprise",
    )
    return {
        name: {
            "version": f"{name}_v1",
            "digest": digest({"component": name, "version": 1}),
        }
        for name in names
    }


async def _active_store() -> tuple[D1ImmediateForwardEvaluationStore, dict]:
    d1 = LocalD1()
    store = D1ImmediateForwardEvaluationStore(d1)
    manifest = build_amended_frozen_version_manifest(
        accepted_code_head="c" * 40,
        earliest_start_utc=ACTIVATED,
        components=_components(),
    )
    prepared = await store.prepare_cohort(manifest, prepared_at_utc=ACTIVATED)
    active = await store.activate_cohort(
        prepared["cohort_id"],
        activated_at_utc=ACTIVATED,
    )
    return store, active


def _insert_snapshot(
    d1: LocalD1,
    *,
    snapshot_id: str,
    captured_at: datetime,
    bid: str | None = None,
    ask: str | None = None,
    spread: str | None = None,
    with_ohlc: bool = False,
) -> None:
    candle_id = "candle-known" if with_ohlc else None
    payload = {
        "id": snapshot_id,
        "captured_at": captured_at.isoformat(),
        "symbol": "XAUUSD",
        "capture_status": "complete",
        "bid": bid,
        "ask": ask,
        "mid": "3500.00",
        "spread": spread,
        "quote_time": (captured_at - timedelta(seconds=1)).isoformat(),
        "quote_age_seconds": 1.0,
        "session_code": "NY",
        "position_state_json": None,
        "data_availability_json": json.dumps(
            {
                "quote": "available",
                "price_type": "indicative_mid",
                "spread_advisory_state": "unavailable",
            },
            sort_keys=True,
        ),
        "event_observation_ids_json": "[]",
        "latest_m1_id": candle_id,
        "latest_m5_id": candle_id,
        "latest_m15_id": candle_id,
        "latest_h1_id": candle_id,
        "latest_h4_id": candle_id,
        "latest_d1_id": candle_id,
        "snapshot_digest": digest({"snapshot": snapshot_id}),
        "archive_key": f"snapshots/{snapshot_id}.json",
    }
    columns = tuple(payload)
    placeholders = ",".join("?" for _ in columns)
    d1.connection.execute(
        f"INSERT INTO market_snapshots ({','.join(columns)}) VALUES ({placeholders})",
        tuple(payload[name] for name in columns),
    )
    d1.connection.commit()


@pytest.mark.asyncio
async def test_live_observer_records_mid_only_feed_as_pre_model_block() -> None:
    store, cohort = await _active_store()
    d1 = store._db
    captured = SCHEDULED + timedelta(seconds=2)
    _insert_snapshot(d1, snapshot_id="snapshot-mid-only", captured_at=captured)

    result = await observe_private_forward_snapshot(
        d1=d1,
        scheduled_at=SCHEDULED,
        snapshot_id="snapshot-mid-only",
        clock=lambda: OBSERVED,
    )

    assert result.status == "recorded"
    assert result.disposition == "pre_model_blocked"
    assert result.reason_code == "missing_genuine_live_ohlc"
    row = d1.connection.execute(
        "SELECT record_json FROM aidy_forward_evaluations WHERE record_id=?",
        (result.record_id,),
    ).fetchone()
    record = json.loads(row["record_json"])
    assert datetime.fromisoformat(record["evaluated_at_utc"]) >= captured
    assert record["data_quality_state"] == "failure"
    assert record["self_consistency_digest"] is None
    progress = await store.cohort_progress(cohort["cohort_id"])
    assert progress["raw_evaluation_count"] == 1
    assert progress["model_resolved_episode_independent_n"] == 0
    assert progress["day54_sample_gate_met"] is False


@pytest.mark.asyncio
async def test_duplicate_same_five_minute_bucket_is_idempotent() -> None:
    store, cohort = await _active_store()
    d1 = store._db
    _insert_snapshot(
        d1,
        snapshot_id="snapshot-duplicate",
        captured_at=SCHEDULED + timedelta(seconds=1),
    )
    first = await observe_private_forward_snapshot(
        d1=d1,
        scheduled_at=SCHEDULED,
        snapshot_id="snapshot-duplicate",
        clock=lambda: OBSERVED,
    )
    second = await observe_private_forward_snapshot(
        d1=d1,
        scheduled_at=SCHEDULED + timedelta(seconds=30),
        snapshot_id="snapshot-duplicate",
        clock=lambda: OBSERVED + timedelta(seconds=30),
    )
    assert first.status == "recorded"
    assert second.status == "already_recorded"
    assert second.record_id == first.record_id
    count = d1.connection.execute(
        "SELECT COUNT(*) AS n FROM aidy_forward_evaluations WHERE cohort_id=?",
        (cohort["cohort_id"],),
    ).fetchone()["n"]
    assert count == 1


@pytest.mark.asyncio
async def test_non_due_minute_does_not_create_forward_record() -> None:
    store, cohort = await _active_store()
    d1 = store._db
    not_due = SCHEDULED + timedelta(minutes=1)
    _insert_snapshot(d1, snapshot_id="snapshot-not-due", captured_at=not_due)
    result = await observe_private_forward_snapshot(
        d1=d1,
        scheduled_at=not_due,
        snapshot_id="snapshot-not-due",
        clock=lambda: not_due + timedelta(seconds=2),
    )
    assert result.status == "not_due"
    count = d1.connection.execute(
        "SELECT COUNT(*) AS n FROM aidy_forward_evaluations WHERE cohort_id=?",
        (cohort["cohort_id"],),
    ).fetchone()["n"]
    assert count == 0


@pytest.mark.asyncio
async def test_snapshot_before_activation_never_backfills() -> None:
    store, cohort = await _active_store()
    d1 = store._db
    _insert_snapshot(
        d1,
        snapshot_id="snapshot-before-activation",
        captured_at=ACTIVATED - timedelta(seconds=1),
    )
    result = await observe_private_forward_snapshot(
        d1=d1,
        scheduled_at=SCHEDULED,
        snapshot_id="snapshot-before-activation",
        clock=lambda: OBSERVED,
    )
    assert result.status == "snapshot_predates_activation"
    assert result.cohort_id == cohort["cohort_id"]


@pytest.mark.asyncio
async def test_decision_grade_snapshot_still_fails_closed_until_adapter_is_enabled() -> None:
    store, _ = await _active_store()
    d1 = store._db
    _insert_snapshot(
        d1,
        snapshot_id="snapshot-decision-grade",
        captured_at=SCHEDULED + timedelta(seconds=1),
        bid="3499.90",
        ask="3500.10",
        spread="0.20",
        with_ohlc=True,
    )
    result = await observe_private_forward_snapshot(
        d1=d1,
        scheduled_at=SCHEDULED,
        snapshot_id="snapshot-decision-grade",
        clock=lambda: OBSERVED,
    )
    assert result.status == "recorded"
    assert result.disposition == "failed_closed"
    assert result.reason_code == "production_decision_context_adapter_not_enabled"


@pytest.mark.asyncio
async def test_status_exposes_active_cohort_and_noninflated_progress() -> None:
    store, cohort = await _active_store()
    d1 = store._db
    _insert_snapshot(
        d1,
        snapshot_id="snapshot-status",
        captured_at=SCHEDULED + timedelta(seconds=1),
    )
    await observe_private_forward_snapshot(
        d1=d1,
        scheduled_at=SCHEDULED,
        snapshot_id="snapshot-status",
        clock=lambda: OBSERVED,
    )
    status = await live_forward_status(d1)
    assert status["active"] is True
    assert status["cohort_id"] == cohort["cohort_id"]
    assert status["progress"]["raw_evaluation_count"] == 1
    assert status["progress"]["model_resolved_episode_independent_n"] == 0
    assert status["openai_called_for_pre_model_block"] is False
    assert status["telegram_publication_enabled"] is False


def test_live_forward_manifest_preserves_boundaries_and_five_minute_cadence() -> None:
    manifest = day53_live_forward_manifest()
    assert manifest["observation_interval_seconds"] == FORWARD_OBSERVATION_INTERVAL_SECONDS == 300
    assert manifest["missing_live_ohlc_fails_pre_model"] is True
    assert manifest["missing_spread_is_advisory"] is True
    assert manifest["observed_out_of_tolerance_spread_fails_pre_model"] is True
    assert manifest["blocked_cycles_count_toward_day54_model_resolved_n"] is False
    assert manifest["decision_adapter_enabled_by_this_change"] is False
    assert manifest["openai_called_for_pre_model_block"] is False
    assert manifest["telegram_publication_enabled"] is False
    assert manifest["super_signals_dependency_allowed"] is False
    assert manifest["broker_or_account_state_allowed"] is False
    assert manifest["live_money_execution_allowed"] is False


def test_worker_entry_requires_explicit_forward_flag_and_exposes_status_endpoint() -> None:
    source = (ROOT / "src" / "entry.py").read_text(encoding="utf-8")
    assert "AIDY_FORMAL_FORWARD_ENABLED" in source
    assert 'url.path == "/day53/forward-status"' in source
    assert "observe_private_forward_snapshot" in source
    assert "capture_retry_requested" in source
    assert "message.ack()" in source
