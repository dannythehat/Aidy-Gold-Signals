"""Verify the new AIDY D1 indexes preserve historical result identity and PIT order."""
from __future__ import annotations

import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations/d1/0029_gold_expert_shadow_read_indexes.sql"


def test_gold_shadow_indexed_history_keeps_all_original_rows_and_order() -> None:
    db = sqlite3.connect(":memory:")
    db.executescript(
        """
        CREATE TABLE aidy_gold_expert_outcome_ledger (
          result_id TEXT, scope_key TEXT, gate_id TEXT,
          resolved_at_utc TEXT, subject_type TEXT
        );
        CREATE TABLE aidy_gold_expert_shadow_health_history (
          observed_at_utc TEXT PRIMARY KEY,
          latest_cycle_decided_at_utc TEXT
        );
        """
    )
    db.executemany(
        "INSERT INTO aidy_gold_expert_outcome_ledger VALUES (?,?,?,?,?)",
        (
            (
                f"outcome-{i:06d}", f"scope-{i % 3}", f"gate-{i % 15}",
                f"2026-09-{1 + i // 240:02d}T{i % 24:02d}:00:00+00:00",
                "gate" if i % 2 else "subcalculator",
            )
            for i in range(3000)
        ),
    )
    db.executemany(
        "INSERT INTO aidy_gold_expert_shadow_health_history VALUES (?,?)",
        (
            (f"2026-09-{1 + i // 240:02d}T{i % 24:02d}:{(i // 24) % 10:02d}:00+00:00",
             "2026-09-01T00:00:00+00:00" if i == 44 else None)
            for i in range(3000)
        ),
    )
    sql_gate = """SELECT result_id,scope_key FROM aidy_gold_expert_outcome_ledger
                  WHERE gate_id=? AND resolved_at_utc<?
                  ORDER BY resolved_at_utc,result_id,scope_key"""
    sql_heartbeat = """SELECT latest_cycle_decided_at_utc
                  FROM aidy_gold_expert_shadow_health_history
                  WHERE latest_cycle_decided_at_utc IS NOT NULL
                  ORDER BY observed_at_utc DESC LIMIT 1"""
    prior = db.execute(sql_gate, ("gate-3", "2026-09-09T00:00:00+00:00")).fetchall()
    prior_heartbeat = db.execute(sql_heartbeat).fetchone()

    db.executescript(MIGRATION.read_text(encoding="utf-8"))
    db.executescript(MIGRATION.read_text(encoding="utf-8"))
    result = db.execute(sql_gate, ("gate-3", "2026-09-09T00:00:00+00:00")).fetchall()
    latest = db.execute(sql_heartbeat).fetchone()
    assert result == prior
    assert latest == prior_heartbeat
    assert db.execute("SELECT COUNT(*) FROM aidy_gold_expert_outcome_ledger").fetchone()[0] == 3000
    assert db.execute("SELECT COUNT(*) FROM aidy_gold_expert_shadow_health_history").fetchone()[0] == 3000

    plan = [
        row[3] for row in db.execute(
            "EXPLAIN QUERY PLAN " + sql_gate,
            ("gate-3", "2026-09-09T00:00:00+00:00"),
        )
    ]
    assert any("ix_aidy_gold_expert_outcome_gate_resolved" in line for line in plan), plan
    history_plan = [row[3] for row in db.execute("EXPLAIN QUERY PLAN " + sql_heartbeat)]
    assert any("ix_aidy_gold_expert_shadow_last_frozen" in line for line in history_plan), history_plan
