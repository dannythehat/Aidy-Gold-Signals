"""Independent signed-evidence cash-carry sensitivity, with NO strategy execution."""
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.oracle_gold.phase05_independent_funding_sensitivity import (
    ROOT, SOURCE, exposure_years, audit_one, run,
)


def test_year_boundary_split_is_exact():
    first = datetime(2023, 12, 31, 12, tzinfo=timezone.utc)
    last = datetime(2024, 1, 2, 12, tzinfo=timezone.utc)
    assert exposure_years(first, last, 2) == {"2023": 1, "2024": 3}


def test_reverse_position_and_negative_ounces_rejected():
    a = datetime(2024, 1, 1, tzinfo=timezone.utc)
    b = datetime(2024, 1, 2, tzinfo=timezone.utc)
    with pytest.raises(ValueError):
        exposure_years(b, a, 1)
    with pytest.raises(ValueError):
        exposure_years(a, b, -1)


def test_s016_verified_archive_and_open_position_included():
    s = audit_one(ROOT, "S016")
    assert s["closed_trades"] == 30
    assert s["unclosed_positions_included"] == 1
    assert s["baseline_stressed_marked_usd"] == 2493.88
    assert abs(s["actual_elapsed_ounce_days"]-1764.485417) < 0.000002
    assert s["scenarios"][4]["years"]["2024"]["sensitivity_marked_usd"] < 0
    assert s["scenarios"][4]["marked_net_after_extra_cost_usd"] > 0


def test_s083_bidask_archive_reconciles_and_was_not_annual_winner():
    s = audit_one(ROOT, "S083")
    assert s["closed_trades"] == 61
    assert s["unclosed_positions_included"] == 0
    assert s["baseline_stressed_marked_usd"] == 298.10
    assert abs(s["actual_elapsed_ounce_days"]-173.535530) < 0.000002
    assert s["scenarios"][0]["positive_in_every_historical_year"] is False
    assert s["scenarios"][-1]["marked_net_after_extra_cost_usd"] < 0


def test_no_execution_promotion_and_zero_cost_equal_baseline():
    out = run()
    assert out["broker_orders"] == out["systems_newly_qualified"] == 0
    assert out["sources_verified"] is True
    assert set(out["cases"]) == {"S016", "S083"}
    for item in out["cases"].values():
        assert item["scenarios"][0]["marked_net_after_extra_cost_usd"] == item["baseline_stressed_marked_usd"]


def test_source_tampering_is_detected(tmp_path: Path, monkeypatch):
    p = tmp_path / "corrupt.zip"
    p.write_bytes(b"tampered source")
    monkeypatch.setitem(SOURCE, "S016", {"path": "corrupt.zip", "sha256": "0"*64, "key": "x"})
    with pytest.raises(ValueError, match="hash mismatch"):
        audit_one(tmp_path, "S016")
