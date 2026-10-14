"""Offline controls for Day23 real historical MQL entry/exit parity runner."""
from __future__ import annotations

from dataclasses import replace

import pytest

from scripts.strategy_lab.day23_real_mql_audit import audit_read_only_history
from test_strategy_lab_day22_real_history import example_read


def test_mql4_mql5_same_closed_bar_internal_entry_and_exit():
    result = audit_read_only_history(example_read())
    assert result["status"] == "PASS"
    assert result["native_m1_count"] == 450
    assert result["closed_m5_count"] == 90
    assert result["oracle_entry_signals_utc"]
    assert result["source_results"]["mql4"]["entry_signals_utc"] == (
        result["source_results"]["mql5"]["entry_signals_utc"]
    )
    assert result["source_results"]["mql4"]["opposite_cross_exit_signals_utc"] == (
        result["source_results"]["mql5"]["opposite_cross_exit_signals_utc"]
    )
    assert not result["native_mt4_mt5_compiler_or_terminal_parity_verified"]
    assert not result["trade_or_full_stop_target_exit_parity_verified"]
    assert not result["broker_orders_executed"]
    assert not result["customer_metatrader_login_required"]


@pytest.mark.parametrize("field,invalid", [
    ("native_m1_rows", 1),
    ("source_archive_hashes", ()),
    ("input_digest", "wrong"),
    ("pit_eligible", True),
    ("provenance", "future_research"),
])
def test_historical_origin_fail_closed(field, invalid):
    history = example_read()
    with pytest.raises(ValueError, match="qualified"):
        audit_read_only_history(replace(history, **{field: invalid}))


def test_mql_history_invalid_bar_or_unavailable_close_rejected():
    history = example_read()
    bar = list(history.bars)
    bar[10] = replace(bar[10], available_at_utc=bar[10].open_time_utc)
    with pytest.raises(ValueError, match="continuous"):
        audit_read_only_history(replace(history, bars=tuple(bar)))


def test_truncated_real_history_rejected():
    history = example_read()
    with pytest.raises(ValueError, match="qualified"):
        audit_read_only_history(replace(history, bars=history.bars[:30], native_m1_rows=150))
