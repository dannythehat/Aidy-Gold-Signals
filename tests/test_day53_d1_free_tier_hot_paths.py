from __future__ import annotations

import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

OLD_QUOTE = """
SELECT id,captured_at,bid,ask,mid,spread,quote_time,quote_age_seconds,
       data_availability_json,snapshot_digest
FROM market_snapshots
WHERE symbol=? AND capture_status='complete'
  AND quote_time>=? AND quote_time<?
  AND bid IS NOT NULL AND ask IS NOT NULL AND mid IS NOT NULL AND spread IS NOT NULL
  AND json_extract(data_availability_json,'$.market_data_source')=?
ORDER BY quote_time ASC,captured_at ASC,id ASC
"""

NEW_QUOTE = """
SELECT id,captured_at,bid,ask,mid,spread,quote_time,quote_age_seconds,
       data_availability_json,snapshot_digest
FROM market_snapshots
WHERE symbol=? AND market_data_source=? AND capture_status='complete'
  AND quote_time>=? AND quote_time<?
  AND bid IS NOT NULL AND ask IS NOT NULL AND mid IS NOT NULL AND spread IS NOT NULL
ORDER BY quote_time ASC,captured_at ASC,id ASC
LIMIT ?
"""

OLD_LATEST = """
SELECT c.timeframe,c.id
FROM market_candles c
WHERE c.source=? AND c.symbol=?
  AND NOT EXISTS (
    SELECT 1 FROM market_candles newer
    WHERE newer.source=c.source AND newer.symbol=c.symbol
      AND newer.timeframe=c.timeframe
      AND (
        newer.open_time_utc>c.open_time_utc OR
        (newer.open_time_utc=c.open_time_utc AND newer.revision_index>c.revision_index)
      )
  )
ORDER BY c.timeframe
"""

NEW_LATEST = """
SELECT id
FROM market_candles
WHERE source=? AND symbol=? AND timeframe=?
ORDER BY open_time_utc DESC,revision_index DESC
LIMIT 1
"""


def _plan(db: sqlite3.Connection, sql: str, params: tuple[object, ...]) -> str:
    rows = db.execute("EXPLAIN QUERY PLAN " + sql, params).fetchall()
    return " | ".join(str(row[3]) for row in rows)


def test_migration_backfills_source_and_changes_both_hot_query_plans() -> None:
    db = sqlite3.connect(":memory:")
    db.executescript((ROOT / "migrations/d1/0001_aidy_ops.sql").read_text(encoding="utf-8"))
    availability = json.dumps({"market_data_source": "argentapi"})
    db.execute(
        """INSERT INTO market_snapshots(
        id,captured_at,symbol,capture_status,bid,ask,mid,spread,quote_time,quote_age_seconds,
        session_code,position_state_json,data_availability_json,event_observation_ids_json,
        latest_m1_id,latest_m5_id,latest_m15_id,latest_h1_id,latest_h4_id,latest_d1_id,
        snapshot_digest,archive_key) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            "snap-1","2026-09-02T12:00:10+00:00","XAUUSD","complete","3499","3501","3500","2",
            "2026-09-02T12:00:00+00:00",10.0,"new_york",None,availability,"[]",None,None,None,None,None,None,
            "a" * 64,"gold/snapshots/test.json",
        ),
    )
    db.execute(
        """INSERT INTO market_candles(
        id,symbol,timeframe,open_time_utc,broker_open_time,open,high,low,close,tick_volume,spread,volume,
        source,revision_index,payload_digest,first_observed_at,archive_key)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            "candle-1","XAUUSD","1m","2026-09-02T12:00:00+00:00",None,"1","1","1","1",1,"0",None,
            "argentapi_quote_rollup_v1",1,"b" * 64,"2026-09-02T12:01:00+00:00","gold/candles/test.json",
        ),
    )
    db.commit()

    old_quote_plan = _plan(
        db,
        OLD_QUOTE,
        ("XAUUSD","2026-09-02T11:00:00+00:00","2026-09-02T13:00:00+00:00","argentapi"),
    )
    old_latest_plan = _plan(db, OLD_LATEST, ("argentapi_quote_rollup_v1","XAUUSD"))
    assert "CORRELATED SCALAR SUBQUERY" in old_latest_plan
    assert "ix_market_snapshots_quote_history" not in old_quote_plan

    db.executescript(
        (ROOT / "migrations/d1/0012_live_gold_free_tier_read_budget.sql").read_text(encoding="utf-8")
    )
    assert db.execute("SELECT market_data_source FROM market_snapshots WHERE id='snap-1'").fetchone()[0] == "argentapi"

    new_quote_plan = _plan(
        db,
        NEW_QUOTE,
        ("XAUUSD","argentapi","2026-09-02T11:00:00+00:00","2026-09-02T13:00:00+00:00",3001),
    )
    new_latest_plan = _plan(
        db,
        NEW_LATEST,
        ("argentapi_quote_rollup_v1","XAUUSD","1m"),
    )
    assert "ix_market_snapshots_quote_history" in new_quote_plan
    assert "ix_market_candles_source_symbol_timeframe_latest" in new_latest_plan
    assert "CORRELATED SCALAR SUBQUERY" not in new_latest_plan


def test_live_gold_storage_has_no_json_source_predicate_or_not_exists_latest_scan() -> None:
    text = (ROOT / "src/aidy/live_gold_storage.py").read_text(encoding="utf-8")
    assert "json_extract(data_availability_json,'$.market_data_source')" not in text
    assert "NOT EXISTS" not in text
    assert "market_data_source=?" in text
    assert "LIMIT ?" in text


def test_recorder_skips_quote_history_for_already_materialized_closed_bucket() -> None:
    text = (ROOT / "src/aidy/live_gold_recorder.py").read_text(encoding="utf-8")
    marker = "existing_id = await self._quote_history.candle_id_for_bucket"
    assert marker in text
    assert text.index(marker) < text.index("rows = await self._quote_history.quote_observations", text.index(marker))
    assert "closed_bucket_already_materialized" in text


def test_continuity_store_reads_are_hard_bounded() -> None:
    reference = (ROOT / "src/aidy/reference_continuity.py").read_text(encoding="utf-8")
    full = (ROOT / "src/aidy/continuity_auditor.py").read_text(encoding="utf-8")
    for text in (reference, full):
        assert "capped at 24 hours" in text
        assert "LIMIT ?" in text
        assert "row bound exceeded" in text


def test_archive_hot_prune_is_bounded_and_archive_gated() -> None:
    text = (ROOT / "src/aidy/cloudflare_storage.py").read_text(encoding="utf-8")
    assert "prune_archived_hot_data" in text
    assert "status='archived'" in text
    assert "hot_pruned_at IS NULL" in text
    assert "LIMIT ?" in text
    assert "DELETE FROM market_snapshots" in text
    assert "DELETE FROM market_candles" in text
