from __future__ import annotations

import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_twelve_admission_view_uses_keyed_bootstrap_probe() -> None:
    db = sqlite3.connect(":memory:")
    db.executescript(
        """
        CREATE TABLE market_candles (
          id TEXT PRIMARY KEY, source TEXT NOT NULL, symbol TEXT NOT NULL,
          timeframe TEXT NOT NULL, open_time_utc TEXT NOT NULL,
          first_observed_at TEXT NOT NULL, revision_index INTEGER NOT NULL
        );
        CREATE UNIQUE INDEX uq_market_candles_revision
        ON market_candles(source,symbol,timeframe,open_time_utc,revision_index);

        CREATE TABLE twelve_data_request_ledger (
          id TEXT PRIMARY KEY, completed_at_utc TEXT, request_kind TEXT NOT NULL,
          status TEXT NOT NULL, outputsize INTEGER
        );
        CREATE INDEX idx_twelve_data_request_ledger_completion_success
        ON twelve_data_request_ledger(completed_at_utc,status,request_kind,outputsize,id);

        CREATE TABLE twelve_data_bootstrap_requests (
          bootstrap_id TEXT NOT NULL, window_index INTEGER NOT NULL,
          request_ledger_id TEXT NOT NULL, window_start_utc TEXT NOT NULL,
          window_end_utc TEXT NOT NULL, state TEXT NOT NULL,
          PRIMARY KEY (bootstrap_id,window_index)
        );
        CREATE INDEX idx_twelve_data_bootstrap_requests_by_ledger_window
        ON twelve_data_bootstrap_requests(request_ledger_id,state,window_start_utc,window_end_utc);
        CREATE INDEX idx_twelve_data_bootstrap_requests_admission_window
        ON twelve_data_bootstrap_requests(state,window_start_utc,window_end_utc,request_ledger_id);
        """
    )
    db.executescript(
        (ROOT / "migrations/d1/0014_twelve_admission_plan.sql").read_text(encoding="utf-8")
    )
    plan = " | ".join(
        str(row[3])
        for row in db.execute(
            """
            EXPLAIN QUERY PLAN
            SELECT * FROM twelve_data_decision_admitted_m1_v1
            WHERE open_time_utc>=? AND open_time_utc<? AND first_observed_at<=?
            ORDER BY open_time_utc,revision_index LIMIT 3501
            """,
            (
                "2026-09-03T00:00:00+00:00",
                "2026-09-05T23:59:59+00:00",
                "2026-09-05T23:59:59+00:00",
            ),
        )
    )
    assert "idx_twelve_data_request_ledger_completion_success" in plan
    assert "idx_twelve_data_bootstrap_requests_by_ledger_window" in plan
    assert "SCAN twelve_data_request_ledger" not in plan
    assert "SCAN twelve_data_bootstrap_requests" not in plan


def test_admission_semantics_stay_scheduled_or_bootstrap_only() -> None:
    text = (ROOT / "migrations/d1/0014_twelve_admission_plan.sql").read_text(encoding="utf-8")
    assert "r.request_kind='scheduled_capture'" in text
    assert "r.outputsize BETWEEN 1 AND 30" in text
    assert "r.request_kind='bootstrap'" in text
    assert "b.request_ledger_id=r.id" in text
    assert "b.state='succeeded'" in text
    assert "c.open_time_utc>=b.window_start_utc" in text
    assert "c.open_time_utc<b.window_end_utc" in text
