import pandas as pd
import pytest

from scripts.oracle_gold.phase05_pine_accounts import evaluate, supertrend


def bars(rows, minutes):
    x = pd.DataFrame(rows)
    x.index = pd.date_range('2024-01-02T12:00:00Z', periods=len(x), freq=f'{minutes}min')
    return x


def test_source_v6_240k_order_is_not_fabricated_into_ten_k_account():
    x = bars([{'open': 100., 'high': 101., 'low': 99., 'close': 100., 'atr': 1., 'st': 110., 'buy': True, 'sell': False, 'session': True}]*3, 5)
    result, trades, rejected = evaluate(x, 'S066', 10000., 'common_stress')
    assert trades == []
    assert result['net_marked_usd'] == 0
    assert len(rejected) == 3
    assert rejected[0]['required_margin'] == 240000


def test_source_v5_qty_uses_signal_equity_stop_distance_and_next_open_gap():
    x = bars([
        {'open': 100., 'high': 100.2, 'low': 99.8, 'close': 100., 'atr': 2., 'buy': True, 'sell': False},
        {'open': 99., 'high': 100., 'low': 95., 'close': 96., 'atr': 2., 'buy': False, 'sell': False},
    ], 60)
    result, trades, _ = evaluate(x, 'S052', 25000., 'source_declared')
    assert len(trades) == 1
    assert trades[0]['units'] == pytest.approx(250/3)
    assert trades[0]['entry_reference'] == 99.
    assert trades[0]['exit_reference'] == 97.
    assert result['closed_net_usd'] == pytest.approx(-500/3)


def test_replaced_marketable_exit_processes_at_close_without_invented_next_open():
    x = bars([
        {'open': 100., 'high': 100., 'low': 100., 'close': 100., 'atr': 1., 'st': 110., 'buy': True, 'sell': False, 'session': True},
        {'open': 80., 'high': 80., 'low': 75., 'close': 80., 'atr': 1., 'st': 90., 'buy': False, 'sell': False, 'session': True},
        {'open': 50., 'high': 50., 'low': 50., 'close': 50., 'atr': 1., 'st': 60., 'buy': False, 'sell': False, 'session': False},
    ], 5)
    result, trades, _ = evaluate(x, 'S066', 1000000., 'source_declared')
    assert len(trades) == 1
    assert trades[0]['reason'] == 'STOP_MARKETABLE_ON_CLOSE'
    assert trades[0]['exit_reference'] == 80.
    assert result['closed_net_usd'] == -48000.


def test_pine_supertrend_sign_not_silently_corrected_to_source_comments():
    x = bars([{'open': float(i), 'high': float(i+1), 'low': float(i-1), 'close': float(i)} for i in range(100, 140)], 5)
    line, direction = supertrend(x)
    assert direction[-1] == -1  # Original S066 calls this dnTrend. Preserve it.
    assert line[-1] < x.close.iloc[-1]
