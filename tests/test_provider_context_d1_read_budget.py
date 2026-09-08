from __future__ import annotations

import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PROVIDER_CONTEXT_SQL = """
SELECT id,captured_at,symbol,capture_status,market_data_source,session_code,
       snapshot_digest,archive_key,data_availability_json
FROM market_snapshots
WHERE symbol=? AND market_data_source='twelve_data'
  AND capture_status='complete' AND captured_at<=?
  AND json_extract(data_availability_json,'$.request_kind')='scheduled_capture'
  AND json_extract(data_availability_json,'$.request_ledger_status')='succeeded'
ORDER BY captured_at DESC,id DESC
LIMIT ?
"""


def _insert_snapshot(
    db: sqlite3.Connection,
    *,
    snapshot_id: str,
    captured_at: str,
    request_kind: str,
    ledger_status: str,
) -> None:
    availability = json.dumps(
        {
            "market_data_source": "twelve_data",
            "request_kind": request_kind,
            "request_ledger_status": ledger_status,
        },
        sort_keys=True,
    )
    db.execute(
        """INSERT INTO market_snapshots(
        id,captured_at,symbol,capture_status,bid,ask,mid,spread,quote_time,quote_age_seconds,
        session_code,position_state_json,data_availability_json,event_observation_ids_json,
        latest_m1_id,latest_m5_id,latest_m15_id,latest_h1_id,latest_h4_id,latest_d1_id,
        snapshot_digest,archive_key,market_data_source) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            snapshot_id,
            captured_at,
            "XAUUSD",
            "complete",
            "3499",
            "3501",
            "3500",
            "2",
            captured_at,
            0.0,
            "new_york",
            None,
            availability,
            "[]",
            None,
            None,
            None,
            None,
            None,
            None,
            snapshot_id.ljust(64, "a")[:64],
            f"gold/snapshots/{snapshot_id}.json",
            "twelve_data",
        ),
    )


def test_provider_context_lookup_uses_scheduled_success_partial_index() -> None:
    db = sqlite3.connect(":memory:")
    db.executescript((ROOT / "migrations/d1/0001_aidy_ops.sql").read_text(encoding="utf-8"))
    db.executescript(
        (ROOT / "migrations/d1/0012_live_gold_free_tier_read_budget.sql").read_text(encoding="utf-8")
    )

    for i in range(400):
        _insert_snapshot(
            db,
            snapshot_id=f"noise-{i:03d}",
            captured_at=f"2026-09-07T12:{i % 60:02d}:{i % 60:02d}+00:00",
            request_kind="bootstrap" if i % 2 else "scheduled_capture",
            ledger_status="failed" if i % 2 == 0 else "succeeded",
        )
    _insert_snapshot(
        db,
        snapshot_id="wanted",
        captured_at="2026-09-07T11:59:00+00:00",
        request_kind="scheduled_capture",
        ledger_status="succeeded",
    )
    db.commit()

    before = " | ".join(
        row[3]
        for row in db.execute(
            "EXPLAIN QUERY PLAN " + PROVIDER_CONTEXT_SQL,
            ("XAUUSD", "2026-09-07T13:00:00+00:00", 1),
        ).fetchall()
    )
    assert "idx_market_snapshots_provider_context_scheduled_success" not in before

    db.executescript(
        (ROOT / "migrations/d1/0016_provider_context_read_budget.sql").read_text(encoding="utf-8")
    )

    after = " | ".join(
        row[3]
        for row in db.execute(
            "EXPLAIN QUERY PLAN " + PROVIDER_CONTEXT_SQL,
            ("XAUUSD", "2026-09-07T13:00:00+00:00", 1),
        ).fetchall()
    )
    assert "idx_market_snapshots_provider_context_scheduled_success" in after

    row = db.execute(
        PROVIDER_CONTEXT_SQL,
        ("XAUUSD", "2026-09-07T13:00:00+00:00", 1),
    ).fetchone()
    assert row is not None
    assert row[0] == "wanted"


def test_index_is_partial_and_does_not_change_provider_context_semantics() -> None:
    migration = (ROOT / "migrations/d1/0016_provider_context_read_budget.sql").read_text(encoding="utf-8")
    assert "CREATE INDEX IF NOT EXISTS" in migration
    assert "market_data_source = 'twelve_data'" in migration
    assert "capture_status = 'complete'" in migration
    assert "request_kind" in migration and "scheduled_capture" in migration
    assert "request_ledger_status" in migration and "succeeded" in migration
    assert "INSERT" not in migration.upper()
    assert "UPDATE" not in migration.upper()
    assert "DELETE" not in migration.upper()
