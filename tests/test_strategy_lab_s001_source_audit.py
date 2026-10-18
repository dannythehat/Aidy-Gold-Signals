"""S001 true data-source gate must never be confused with strategy P&L."""
from datetime import UTC, datetime

import pytest

from scripts.strategy_lab.s001_goldea_source_audit import make_packet, summarise


def _m15(ts="2025-01-06T11:00:00+00:00", count=15, bad=0):
    return {
        "period_utc": datetime.fromisoformat(ts),
        "open": 2600.0, "high": 2602.0, "low": 2599.0, "close": 2601.0,
        "m1_count": count, "unique_m1": count,
        "invalid_original_rows": bad, "archive_shas": ["a" * 64],
    }


def test_bounded_actual_source_coverage():
    records = []
    for i in range(101):
        ts = datetime(2025, 1, 6, 11, tzinfo=UTC)
        from datetime import timedelta
        records.append(_m15((ts + timedelta(minutes=15 * i)).isoformat()))
    result = summarise(records, "test-real-job-id", 120000)
    assert result["complete_m15"] == 101
    assert result["original_bid_m1"] == 1515
    packet = make_packet(result)
    assert packet["aidy_net_pnl_usd"] is None
    assert packet["aidy_profit_factor"] is None
    assert packet["aidy_trades"] is None
    assert packet["broker_orders"] == 0
    assert not packet["independent_alpha_qualified"]
    assert "BACKTEST_BLOCKED" in packet["status"]


@pytest.mark.parametrize("changed", [
    {"invalid_original_rows": 1},
    {"m1_count": 16},
    {"unique_m1": 12},
    {"low": -1.0},
    {"archive_shas": ["not-a-sha"]},
    {"period_utc": datetime(2025, 2, 1, tzinfo=UTC)},
])
def test_bad_source_fails_closed(changed):
    rows = [_m15()]
    rows[0].update(changed)
    with pytest.raises(ValueError):
        summarise(rows, "job", 1000)


def test_duplicate_and_missing_query_receipt_rejected():
    with pytest.raises(ValueError):
        summarise([_m15(), _m15()], "job", 100)
    with pytest.raises(ValueError):
        summarise([_m15()], "", 100)
    with pytest.raises(ValueError):
        summarise([_m15()], "job", 1_500_000_001)
