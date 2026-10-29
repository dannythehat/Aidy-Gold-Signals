import importlib.util
import os
import sys
from pathlib import Path

import pandas as pd
import pytest

from scripts.oracle_gold.phase05_execution_costs import observed
from scripts.oracle_gold.phase05_native_accounts import verify_source


@pytest.fixture
def actual_engine():
    root = os.environ.get('ORACLE_PHASE05_S083_ROOT')
    if not root:
        pytest.skip('Pinned original source required, never a fake original')
    root = Path(root)
    verify_source(root)
    spec = importlib.util.spec_from_file_location('actual_s083_cost_test', root/'src/engine.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def tape():
    idx = pd.date_range('2024-01-02T12:00Z', periods=3, freq='15min', name='ts')
    frame = pd.DataFrame({'bid_o': [100., 95., 96.], 'bid_h': [100.1, 95.2, 96.2],
        'bid_l': [99.9, 94., 95.9], 'bid_c': [100., 95., 96.],
        'ask_o': [100.2, 95.2, 96.2], 'ask_h': [100.3, 95.4, 96.4],
        'ask_l': [100.1, 94.2, 96.1], 'ask_c': [100.2, 95.2, 96.2]}, index=idx)
    signals = pd.DataFrame([{'signal_ts': idx[0]-pd.Timedelta(minutes=15), 'entry_ts': idx[0],
        'direction': 1, 'stop': 99., 'session': 'newyork', 'setup': 'rejection', 'zone_id': 1}])
    return signals, frame


def test_actual_original_engine_gap_underfill_preserved(actual_engine):
    sig, frame = tape()
    cfg = actual_engine.Config(2., .25)
    result = actual_engine.simulate(sig, frame, frame, cfg)
    assert result.exit.iloc[0] == 98.95  # Original bug remains reproducible.
    costs, equity, receipt = observed(actual_engine, sig, frame, frame, cfg, 1.44)
    assert costs.exit.iloc[0] == 94.95  # Worse genuine fixture opening BID.
    expected_size = 25/(100.25-99.)
    assert costs.units_exact.iloc[0] == pytest.approx(expected_size)
    assert costs.cash_cost_exact_usd.iloc[0] == pytest.approx(expected_size*1.44)
    assert equity.iloc[-1] == pytest.approx(10000+costs.pnl.sum())
    assert not receipt['strategy_parameters_changed']
    assert actual_engine.simulate(sig, frame, frame, cfg).equals(result)


def test_quote_cost_debit_occurs_at_entry_for_marked_drawdown(actual_engine):
    sig, frame = tape()
    cfg = actual_engine.Config(2., .25)
    base, base_eq, _ = observed(actual_engine, sig, frame, frame, cfg, 0.)
    stress, stress_eq, _ = observed(actual_engine, sig, frame, frame, cfg, 1.44)
    assert base.units_exact.iloc[0] == stress.units_exact.iloc[0]
    assert base_eq.iloc[0]-stress_eq.iloc[0] == pytest.approx(stress.cash_cost_exact_usd.iloc[0]/2)


def test_actual_source_timeout_clock_defect_is_not_hidden(actual_engine):
    sig, frame = tape()
    frame.loc[:, ['bid_h', 'ask_h']] = 100.4
    frame.loc[:, ['bid_l', 'ask_l']] = 99.9
    frame.loc[:, ['bid_o', 'bid_c', 'ask_o', 'ask_c']] = 100.1
    frame.iloc[-1, frame.columns.get_loc('bid_c')] = 100.3
    cfg = actual_engine.Config(2., .25, max_hold_bars=2)
    costs, _, _ = observed(actual_engine, sig, frame, frame, cfg, .47)
    assert costs.timeout_clock_defect.iloc[0]
    assert costs.exit.iloc[0] == 100.3  # Later close still labelled bar open.
