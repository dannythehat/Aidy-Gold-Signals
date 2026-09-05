from __future__ import annotations

import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _plan(db: sqlite3.Connection, sql: str, params: tuple[object, ...]) -> str:
    return " | ".join(str(row[3]) for row in db.execute("EXPLAIN QUERY PLAN " + sql, params))


def test_twelve_hot_path_migration_supports_ledger_window_and_quota_ranges() -> None:
    db = sqlite3.connect(":memory:")
    db.executescript(
        """
        CREATE TABLE twelve_data_request_ledger (
          id TEXT PRIMARY KEY, requested_at_utc TEXT NOT NULL, completed_at_utc TEXT,
          request_kind TEXT NOT NULL, status TEXT NOT NULL, outputsize INTEGER,
          internal_accounted_credits INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE twelve_data_bootstrap_requests (
          bootstrap_id TEXT NOT NULL, window_index INTEGER NOT NULL,
          request_ledger_id TEXT NOT NULL, window_start_utc TEXT NOT NULL,
          window_end_utc TEXT NOT NULL, state TEXT NOT NULL,
          PRIMARY KEY (bootstrap_id,window_index)
        );
        CREATE TABLE market_candles (
          id TEXT PRIMARY KEY, source TEXT NOT NULL, symbol TEXT NOT NULL, timeframe TEXT NOT NULL,
          open_time_utc TEXT NOT NULL, first_observed_at TEXT NOT NULL, revision_index INTEGER NOT NULL
        );
        CREATE TABLE market_snapshots(id TEXT PRIMARY KEY);
        CREATE TABLE archive_outbox(id TEXT PRIMARY KEY);
        """
    )
    migration = (ROOT / "migrations/d1/0013_twelve_private_forward_read_budget.sql").read_text(
        encoding="utf-8"
    )
    # 0013 contains only indexes over the three hot-path tables used by this focused schema.
    for statement in migration.split(";"):
        if "archive_outbox" in statement or "market_snapshots" in statement:
            continue
        if statement.strip():
            db.execute(statement)

    bootstrap_plan = _plan(
        db,
        "SELECT 1 FROM twelve_data_bootstrap_requests WHERE request_ledger_id=? AND state='succeeded' AND ?>=window_start_utc AND ?<window_end_utc LIMIT 1",
        ("r1", "2026-09-05T00:00:00+00:00", "2026-09-05T00:00:00+00:00"),
    )
    quota_plan = _plan(
        db,
        "SELECT COALESCE(SUM(internal_accounted_credits),0) FROM twelve_data_request_ledger WHERE requested_at_utc>=? AND requested_at_utc<=?",
        ("2026-09-05T00:00:00+00:00", "2026-09-05T23:59:59+00:00"),
    )
    m1_plan = _plan(
        db,
        "SELECT id FROM market_candles WHERE source=? AND symbol=? AND timeframe=? AND open_time_utc>=? AND open_time_utc<? AND first_observed_at<=? ORDER BY open_time_utc,revision_index LIMIT 3501",
        (
            "twelve_data_vendor_m1_v1", "XAUUSD", "1m",
            "2026-09-03T00:00:00+00:00", "2026-09-05T00:00:00+00:00",
            "2026-09-05T00:00:00+00:00",
        ),
    )
    assert "idx_twelve_data_bootstrap_requests_by_ledger_window" in bootstrap_plan
    assert "idx_twelve_data_request_ledger_requested_at_credits" in quota_plan
    assert "idx_market_candles_twelve_private_forward_m1" in m1_plan


def test_private_forward_m1_query_is_two_sided_and_hard_bounded() -> None:
    text = (ROOT / "src/aidy/private_forward_context.py").read_text(encoding="utf-8")
    assert "open_time_utc>=? AND open_time_utc<? AND first_observed_at<=?" in text
    assert "_MAX_PRIVATE_FORWARD_M1_ROWS = 3500" in text
    assert "Private-forward M1 row bound exceeded." in text
    assert "LIMIT ?" in text


def test_twelve_quota_scan_is_index_range_bounded() -> None:
    text = (ROOT / "src/aidy/twelve_data_storage.py").read_text(encoding="utf-8")
    assert text.count("WHERE requested_at_utc>=? AND requested_at_utc<=?") >= 2
    assert "SUM(CASE WHEN requested_at_utc>=?" not in text


def test_twelve_latest_aggregate_lookup_has_no_correlated_antijoin() -> None:
    text = (ROOT / "src/aidy/twelve_data_storage.py").read_text(encoding="utf-8")
    start = text.index("async def latest_candle_ids")
    section = text[start:start + 2500]
    assert "NOT EXISTS" not in section
    assert "ORDER BY open_time_utc DESC,revision_index DESC LIMIT 1" in section
