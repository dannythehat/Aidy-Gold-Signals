from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_manifest_is_frozen_to_exactly_56_unique_windows() -> None:
    rows = json.loads(
        (ROOT / "calibration" / "day11_reconciliation_windows.json").read_text(encoding="utf-8")
    )
    assert len(rows) == 56
    assert len({row["window_id"] for row in rows}) == 56
    assert all(row["from"] < row["to"] for row in rows)


def test_calibration_schema_is_structurally_separate_from_live_market_tables() -> None:
    migration = (
        ROOT / "migrations" / "d1" / "0015_day11_calibration_backfill.sql"
    ).read_text(encoding="utf-8")
    assert "provider_calibration_backfill_windows" in migration
    assert "provider_calibration_m1_backfill" in migration
    assert "source_kind = 'calibration_backfill'" in migration
    assert "source_provider = 'twelve_data'" in migration
    assert "pit_eligible = 0" in migration
    assert "research_only = 1" in migration
    assert "live_money_execution_allowed = 0" in migration
    assert "market_candles" not in migration


def test_backfill_generator_uses_only_twelve_and_never_synthesizes() -> None:
    source = (ROOT / "scripts" / "day11_calibration_backfill.py").read_text(encoding="utf-8")
    assert "TwelveDataOhlcGateway" in source
    assert 'SOURCE_PROVIDER = "twelve_data"' in source
    assert 'SOURCE_KIND = "calibration_backfill"' in source
    assert "EXPECTED_WINDOWS = 56" in source
    assert '"INCOMPLETE"' in source
    assert "interpol" in source.lower() or "synth" in source.lower()
    assert "market_candles" in source  # only in the explicit never-write safety docstring
    assert "INSERT INTO market_candles" not in source


def test_calibration_endpoint_reads_only_calibration_tables_and_flags() -> None:
    source = (ROOT / "src" / "aidy" / "provider_calibration_api.py").read_text(
        encoding="utf-8"
    )
    assert "provider_calibration_backfill_windows" in source
    assert "provider_calibration_m1_backfill" in source
    assert "source_kind='calibration_backfill'" in source
    assert "source_provider='twelve_data'" in source
    assert "pit_eligible=0" in source
    assert "research_only=1" in source
    assert "live_money_execution_allowed=0" in source
    assert "market_candles" in source  # only in the explicit never-read safety docstring
    assert "FROM market_candles" not in source
    assert "INSERT " not in source
    assert "UPDATE " not in source
    assert "DELETE " not in source


def test_live_market_endpoint_remains_unchanged_and_pit_admitted() -> None:
    live = (ROOT / "src" / "aidy" / "provider_market_api.py").read_text(encoding="utf-8")
    assert "FROM twelve_data_decision_admitted_m1_v1" in live
    assert "first_observed_at<=?" in live
    assert "provider_calibration_m1_backfill" not in live


def test_worker_routes_calibration_separately_from_live_market() -> None:
    wrapper = (ROOT / "src" / "provider_entry.py").read_text(encoding="utf-8")
    assert 'path == "/market/ohlc"' in wrapper
    assert 'path == "/calibration/market/ohlc"' in wrapper
    assert "calibration_market_ohlc_response" in wrapper
