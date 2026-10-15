"""Day27 complete real-data regime inspection and replay tests."""
from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest
from test_strategy_lab_oos_protocol import sample_history

from scripts.strategy_lab.day27_real_market_regime_audit import audit_source


def test_source_evidence_contains_full_partition_and_explicit_unknown_news():
    result = audit_source(sample_history())
    assert result["status"] == "PASS"
    assert result["acceptance"] == "REGIME_ASOF_REAL_HISTDATA_BID_M5_DAY26_DEV_FOLDS"
    assert result["report"]["fully_closed_m5_available"] == 120
    assert result["report"]["evaluated_walkforward_predictions"] == 48
    assert result["report"]["sealed_holdout_decisions_consumed"] == 0
    assert all(item["news"] == "unknown_unqualified_calendar"
               for item in result["report"]["evaluated"])
    assert not result["independent_real_market_strategy_alpha_qualified"]
    assert not result["news_calendar_source_qualified"]
    assert not result["native_broker_fills_and_costs_verified"]


def test_two_independent_full_audits_identical_and_sha_sealed():
    left = audit_source(sample_history())
    right = audit_source(sample_history())
    assert left == right
    assert len(left["report"]["regime_policy_sha256"]) == 64
    assert len(left["report"]["decisions_sha256"]) == 64


def test_source_time_gap_fails_before_regime_mapping():
    original = sample_history()
    bars = list(original.bars)
    bars[60] = replace(
        bars[60], open_time_utc=bars[60].open_time_utc+timedelta(minutes=1)
    )
    with pytest.raises(ValueError, match="gapped"):
        audit_source(replace(original, bars=tuple(bars)))
