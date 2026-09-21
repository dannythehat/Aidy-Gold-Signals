from __future__ import annotations

from datetime import UTC, datetime, timedelta
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = spec_from_file_location(
    "seed_gold_cycle_history",
    ROOT / "scripts" / "seed_gold_cycle_history.py",
)
assert SPEC is not None and SPEC.loader is not None
MODULE = module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

SOURCE_PROVENANCE = MODULE.SOURCE_PROVENANCE
build_historical_cycle_rows = MODULE.build_historical_cycle_rows
write_d1_sql = MODULE.write_d1_sql


def _bar(opened: datetime, open_price: str, close_price: str) -> dict[str, object]:
    return {
        "open_time_utc": opened,
        "open": open_price,
        "close": close_price,
    }


def test_historical_cycle_rows_preserve_sequence_next_state_and_duration() -> None:
    start = datetime(2025, 6, 3, 6, 0, tzinfo=UTC)
    rows = [
        _bar(start + timedelta(minutes=0), "4300", "4302"),
        _bar(start + timedelta(minutes=15), "4302", "4304"),
        _bar(start + timedelta(minutes=30), "4304", "4303.8"),
        _bar(start + timedelta(minutes=45), "4303.8", "4301"),
        _bar(start + timedelta(minutes=60), "4301", "4298"),
    ]

    cycles = build_historical_cycle_rows(rows)

    assert len(cycles) == 4
    assert cycles[0]["observed_state"] == "bullish"
    assert cycles[0]["next_state"] == "bullish"
    assert cycles[0]["state_run_length_windows"] == 2
    assert cycles[1]["prior_sequence_signature"] == "bullish>bullish"
    assert cycles[2]["observed_state"] == "neutral"
    assert cycles[2]["next_state"] == "bearish"
    assert cycles[3]["next_state"] == "bearish"
    assert all(row["source_provenance"] == SOURCE_PROVENANCE for row in cycles)
    assert all(row["pit_eligible"] == 0 for row in cycles)
    assert all(row["research_only"] == 1 for row in cycles)
    assert all(row["live_money_execution_allowed"] == 0 for row in cycles)


def test_historical_cycle_builder_does_not_bridge_large_market_gap() -> None:
    start = datetime(2025, 6, 3, 20, 45, tzinfo=UTC)
    rows = [
        _bar(start, "4300", "4302"),
        _bar(start + timedelta(hours=2), "4302", "4304"),
    ]

    assert build_historical_cycle_rows(rows) == []


def test_seed_sql_is_idempotent_and_cannot_promote_history(tmp_path: Path) -> None:
    start = datetime(2025, 6, 3, 6, 0, tzinfo=UTC)
    cycles = build_historical_cycle_rows(
        [
            _bar(start, "4300", "4302"),
            _bar(start + timedelta(minutes=15), "4302", "4301"),
        ]
    )
    destination = tmp_path / "seed.sql"
    write_d1_sql(cycles, destination)
    sql = destination.read_text(encoding="utf-8")

    assert "INSERT OR IGNORE INTO aidy_gold_cycle_historical" in sql
    assert "'retrospective_history'" in sql
    assert ",0,1,0)" in sql
    assert "UPDATE " not in sql
    assert "BEGIN TRANSACTION" not in sql
    assert "COMMIT;" not in sql
    assert "aidy_gold_cycle_views" not in sql
    assert "aidy_gold_cycle_outcomes" not in sql
