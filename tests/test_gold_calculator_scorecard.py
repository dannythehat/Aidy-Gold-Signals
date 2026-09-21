from __future__ import annotations

import json
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_calculator_scorecard_view_is_readable_and_joined_to_outcomes() -> None:
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript(
        """
        CREATE TABLE aidy_gold_cycle_views (
            cycle_view_id TEXT PRIMARY KEY,
            window_start_utc TEXT NOT NULL,
            window_end_utc TEXT NOT NULL,
            decided_at_utc TEXT NOT NULL,
            session_code TEXT NOT NULL,
            observed_state TEXT NOT NULL,
            view_direction TEXT NOT NULL,
            evidence_json TEXT NOT NULL
        );
        CREATE TABLE aidy_gold_cycle_marker_results (
            cycle_view_id TEXT NOT NULL,
            marker_id TEXT NOT NULL,
            marker_score INTEGER NOT NULL,
            marker_correct INTEGER
        );
        CREATE TABLE aidy_gold_cycle_outcomes (
            cycle_view_id TEXT PRIMARY KEY,
            realised_direction TEXT NOT NULL,
            return_bps TEXT,
            resolved_at_utc TEXT
        );
        """
    )
    migration = (
        ROOT / "migrations" / "d1" / "0026_gold_calculator_scorecard.sql"
    ).read_text(encoding="utf-8")
    db.executescript(migration)

    evidence = {
        "all_directional_reasons": [
            {
                "marker_id": "marker_h1",
                "surface": "gold_h1_structure",
                "observation": "H1 completed-bar close path is bearish",
                "vote": "bearish",
                "base_weight": "2.000000",
                "learned_multiplier": "1.125000",
                "effective_weight": "2.250000",
                "selected_score_scope": "session_liquidity",
                "selected_score_scope_key": "session_liquidity_x",
                "selected_score_context": (
                    "liquidity=low_side_reclaim | liquidity_intensity=low | "
                    "session=asia | session_phase=late_gt240m"
                ),
                "selected_score_sample_n": 8,
                "selected_score_net": 5,
                "selected_score_accuracy": "0.750000",
            }
        ]
    }
    db.execute(
        """
        INSERT INTO aidy_gold_cycle_views (
            cycle_view_id,window_start_utc,window_end_utc,decided_at_utc,
            session_code,observed_state,view_direction,evidence_json
        ) VALUES (?,?,?,?,?,?,?,?)
        """,
        (
            "cycle_1",
            "2026-09-21T07:00:00+00:00",
            "2026-09-21T07:15:00+00:00",
            "2026-09-21T06:58:00+00:00",
            "asia",
            "bearish",
            "bearish",
            json.dumps(evidence),
        ),
    )
    db.execute(
        """
        INSERT INTO aidy_gold_cycle_marker_results (
            cycle_view_id,marker_id,marker_score,marker_correct
        ) VALUES ('cycle_1','marker_h1',2,1)
        """
    )
    db.execute(
        """
        INSERT INTO aidy_gold_cycle_outcomes (
            cycle_view_id,realised_direction,return_bps,resolved_at_utc
        ) VALUES ('cycle_1','bearish','-6.2','2026-09-21T07:16:00+00:00')
        """
    )

    row = db.execute(
        "SELECT * FROM aidy_gold_calculator_scorecard_v1"
    ).fetchone()
    assert row is not None
    assert row["surface"] == "gold_h1_structure"
    assert row["vote"] == "bearish"
    assert row["sample_n"] == 8
    assert row["net_score"] == 5
    assert row["learned_multiplier"] == "1.125000"
    assert row["effective_weight"] == "2.250000"
    assert "liquidity_intensity=low" in row["readable_condition"]
    assert row["marker_score"] == 2
    assert row["marker_correct"] == 1
    assert row["realised_direction"] == "bearish"
    assert row["return_bps"] == "-6.2"


def test_calculator_scorecard_defaults_old_cycles_to_bootstrap_prior() -> None:
    migration = (
        ROOT / "migrations" / "d1" / "0026_gold_calculator_scorecard.sql"
    ).read_text(encoding="utf-8")
    assert "COALESCE(" in migration
    assert "'bootstrap_prior'" in migration
    assert "aidy_gold_calculator_scorecard_v1" in migration
