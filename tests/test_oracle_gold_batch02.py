"""Executable receipts for original source defects, without repairing strategies."""
import os
from pathlib import Path

import pandas as pd
import pytest

from scripts.oracle_gold.batch01 import pinned_module
from scripts.oracle_gold.batch02 import entries, originals, outcome_summary


def source_root(variable):
    value = os.environ.get(variable)
    if not value:
        pytest.skip(variable + " pinned original checkout required")
    return Path(value)


def test_original_s082_touch_predicate_rejects_every_valid_price_level():
    root = source_root("ORACLE_S082_ROOT")
    m = pinned_module("oracle_original_082", root/"virgin_rejection_backtest.py",
                      "d5bb631f7e67ba6d82bfab8ae47e042217c12033")
    bars = [m.Bar(str(i), 100., 100.5, 99.5, 100.) for i in range(30)]
    # Outside ranges on EITHER side must be untouched, but original OR is true.
    assert all(m.is_touched(level, bars, 1, 2) for level in (-1000., 99., 100., 101., 1000.))
    assert m.detect_signals(bars) == []
    # No finite level escapes: low<=high implies high>=level OR low<=level.
    assert all(b.low <= b.high for b in bars)


def test_original_s012_later_h1_close_rewrites_earlier_h4_bias():
    root = source_root("ORACLE_S012_ROOT")
    m = pinned_module("oracle_original_012", root/"smc_backtest/smc_backtest.py",
                      "04328b6232950022cf71f5cf02a257c63a73a7ec")
    index = pd.date_range("2024-01-01", periods=84, freq="h", tz="UTC")
    frame = pd.DataFrame({"open": 100., "high": 101., "low": 99., "close": 100.}, index=index)
    before = m.add_structure(frame)
    changed = frame.copy()
    changed.loc[index[83], ["high", "close"]] = [111., 110.]
    after = m.add_structure(changed)
    assert frame.loc[index[80]].equals(changed.loc[index[80]])
    assert before.loc[index[80], "bias"] == -1
    assert after.loc[index[80], "bias"] == 1
    assert pd.isna(after.loc[index[81], "bias"])  # join is not H1 forward-filled


def test_cost_overlay_is_r_per_setup_and_never_fabricates_account_equity():
    rows = [{"risk_distance": 2., "native_r": 2., "outcome": "win", "trend_filter_kept": True},
            {"risk_distance": .5, "native_r": -1., "outcome": "loss", "trend_filter_kept": False},
            {"risk_distance": 1., "native_r": 0., "outcome": "unresolved", "trend_filter_kept": True}]
    all_rows = outcome_summary(rows, .47, False)
    assert all_rows["cost_adjusted_total_R"] == pytest.approx(1.-.47/2-.47/.5)
    assert all_rows["closed_setups"] == 2 and all_rows["unresolved"] == 1
    assert all_rows["account_net_usd"] is None and all_rows["account_drawdown"] is None
    assert outcome_summary(rows, .47, True)["closed_setups"] == 1
    rows[0]["risk_distance"] = 0.
    with pytest.raises(ValueError, match="risk distance"):
        outcome_summary(rows, .47, False)


def test_entry_comparison_excludes_outcomes_but_retains_trigger_and_geometry():
    from types import SimpleNamespace
    a = SimpleNamespace(direction="long", entry_index=3, entry_price=100., stop_loss=99.,
                        take_profit=102., trigger_index=2, resolve_index=3, verdict="win")
    b = SimpleNamespace(**{**vars(a), "verdict": "unresolved"})
    assert entries([a], 4) == entries([b], 4)
    b.trigger_index = 4
    assert entries([a], 4) != entries([b], 4)


def test_every_sweep_module_matches_immutable_source_pin():
    root = source_root("ORACLE_SWEEP_ROOT")
    Candle, Params, run, apply_filter = originals(root)
    assert Params.for_timeframe("H1").rr == 2.
    assert Candle is not None and callable(run) and callable(apply_filter)
