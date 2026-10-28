"""Gold Hunter isolated research tests; no broker calls, no claimed edge."""
import math

import pandas as pd
import pytest

from gold_hunter.bible_engine import (
    FAMILIES, Parameters, _confirmed_swings, _higher_frames,
    candidates_at, classify_pattern, research_backtest, validate_h1,
)


def historical_fixture(n=1500):
    times = pd.date_range('2025-01-06', periods=n, freq='h', tz='UTC')
    # Synthetic ONLY. Wave-like market, not a sourced gold price series.
    price = [3000 + .015 * j + 35 * math.sin(j / 26) for j in range(n)]
    close = [p + .5 * math.sin(j / 5) for j,p in enumerate(price)]
    return pd.DataFrame({
        'open_time_utc': [t.isoformat() for t in times],
        'open': price,
        'close': close,
        'high': [max(price[i], close[i]) + 1.8 for i in range(n)],
        'low': [min(price[i], close[i]) - 1.8 for i in range(n)],
        'm1_count': [60] * n,
    })


def test_known_pin_and_engulf_at_completed_bar_only():
    a = {'open': 102., 'high': 106., 'low': 100., 'close': 104.}
    b = {'open': 103., 'high': 104., 'low': 100., 'close': 101.}
    c = {'open': 100., 'high': 105., 'low': 99., 'close': 104.}
    found = classify_pattern([a,b,c], 1)
    assert any(k == 'ENGULF' for k,_,_ in found)
    pin = {'open': 100., 'close': 101., 'low': 94., 'high': 101.2}
    assert any(k == 'PIN' for k,_,_ in classify_pattern([a,b,pin], 1))
    assert not any(k == 'PIN' for k,_,_ in classify_pattern([a,b,pin], -1))


def test_inside_and_false_break_variants():
    mother = {'open': 102., 'high': 110., 'low': 95., 'close': 108.}
    inside = {'open': 101., 'high': 106., 'low': 97., 'close': 102.}
    breakout = {'open': 103., 'high': 112., 'low': 101., 'close': 111.}
    fakeout = {'open': 99., 'high': 105., 'low': 94., 'close': 101.}
    assert 'INSIDE' in [x[0] for x in classify_pattern([mother,inside,breakout],1)]
    assert 'FALSE_BREAK' in [x[0] for x in classify_pattern([mother,inside,fakeout],1)]


def test_input_fails_closed():
    df = historical_fixture(700)
    assert len(validate_h1(df)) == 700
    broken = df.copy()
    broken.loc[13, 'm1_count'] = 59
    with pytest.raises(ValueError):
        research_backtest(broken)
    with pytest.raises(ValueError):
        research_backtest(df, families=('NOT_BIBLE',))
    with pytest.raises(ValueError):
        research_backtest(df, cfg=Parameters(min_rr=1.7))


def test_higher_timeframe_never_uses_unclosed_future_bar():
    df = validate_h1(historical_fixture(1500))
    h4, day, week = _higher_frames(df)
    first_utc = df.iloc[1100]['open_time_utc'] + pd.Timedelta(hours=1)
    assert all(h4.loc[h4.completed_at <= first_utc].completed_at <= first_utc)
    assert all(day.loc[day.completed_at <= first_utc].completed_at <= first_utc)
    assert all(week.loc[week.completed_at <= first_utc].completed_at <= first_utc)
    a = candidates_at(df, 1100, h4, day, week, Parameters())
    mutated = df.copy()
    mutated.loc[1120, ['open', 'high', 'low', 'close']] = [9000., 9100., 8900., 9000.]
    h4b, dayb, weekb = _higher_frames(mutated)
    b = candidates_at(mutated, 1100, h4b, dayb, weekb, Parameters())
    assert a == b


def test_repeatable_ledger_and_bible_provenance():
    df = historical_fixture(900)
    first = research_backtest(df)
    second = research_backtest(df)
    assert first == second
    assert first['price_rows'] == 900
    assert first['schema'].startswith('gold_hunter.')
    assert first['status'] == 'HISTORICAL_RESEARCH_ONLY'
    assert set(first['counts_selected']) == set(FAMILIES)
    assert first['closed_trades'] == len(first['trades'])
    assert first['equity_marks'][-1]['equity_usd'] == pytest.approx(first['ending_equity_usd'], abs=.02)
    for t in first['trades']:
        assert t['family'] in FAMILIES
        assert t['bible_reference'].startswith('B ')
        assert t['estimated_rr'] >= 2
        assert t['signal_time_utc'] <= t['entry_utc']
        assert t['mode'] in ('TREND', 'RANGE')
        assert t['level_type'] in ('H4_SWING_OR_SMA21', 'H4_RANGE_BOUNDARY')
        assert t['stop'] != t['target']


def test_prefix_result_invariant_against_future_changes():
    original = historical_fixture(850)
    df = validate_h1(original)
    h4, day, week = _higher_frames(df)
    known = candidates_at(df, 700, h4, day, week, Parameters())
    changed = original.copy()
    changed.loc[805, ['open','high','low','close']] = [11000.,11010.,10990.,11000.]
    d2 = validate_h1(changed)
    hh,dd,ww = _higher_frames(d2)
    assert known == candidates_at(d2, 700, hh, dd, ww, Parameters())
def test_open_trade_at_history_end_is_censored_not_fake_closed(monkeypatch):
    import gold_hunter.bible_engine as engine
    df = historical_fixture(700)
    last_signal_bar = len(df) - 2

    def one_signal(frame, i, h4, day, week, cfg):
        if i != last_signal_bar:
            return []
        close = float(frame.iloc[i]['close'])
        return [{
            'family': 'TREND_PIN', 'bible_reference': 'B 83-99',
            'signal_time_utc': (pd.to_datetime(frame.iloc[i]['open_time_utc'])+
                                pd.Timedelta(hours=1)).isoformat(),
            'side': 1, 'mode': 'TREND', 'level': close - 2,
            'level_type': 'H4_SWING_OR_SMA21', 'pattern': 'PIN',
            'stop': close - 10, 'target': close + 50,
            'estimated_rr': 4.0, 'signal_close': close,
        }]

    monkeypatch.setattr(engine, 'candidates_at', one_signal)
    result = engine.research_backtest(df)
    assert result['closed_trades'] == 0
    assert result['unrealized_open_position']['status'] == 'CENSORED_AT_HISTORY_END_NOT_CLOSED'
    assert result['unrealized_open_position']['family'] == 'TREND_PIN'
    assert result['ending_equity_usd'] != result['realized_balance_usd']


def test_source_bound_candidate_tape_matches_uncached_and_rejects_mismatch():
    from gold_hunter.bible_engine import build_candidate_tape
    df = historical_fixture(900)
    cfg = Parameters()
    tape = build_candidate_tape(df, cfg)
    cached = research_backtest(df, cfg=cfg, candidate_tape=tape)
    uncached = research_backtest(df, cfg=cfg)
    assert cached == uncached
    modified = df.copy()
    modified.loc[500, 'close'] += 0.7
    modified.loc[500, 'high'] += 0.7
    with pytest.raises(ValueError, match='mismatch'):
        research_backtest(modified, cfg=cfg, candidate_tape=tape)
    with pytest.raises(ValueError, match='mismatch'):
        research_backtest(df, cfg=Parameters(near_level_atr=.50), candidate_tape=tape)


def test_vector_swing_matches_original_two_left_two_right_reference():
    import numpy as np
    rng = np.random.default_rng(27828)
    high = 100 + rng.integers(-8, 9, 150).astype(float)
    low = high - rng.integers(1, 5, 150)
    bars = pd.DataFrame({'high': high, 'low': low})
    a, b = _confirmed_swings(bars)
    href = []
    lref = []
    for i in range(2, len(bars) - 2):
        if high[i] > max(high[i - 2:i]) and high[i] >= max(high[i + 1:i + 3]):
            href.append(high[i])
        if low[i] < min(low[i - 2:i]) and low[i] <= min(low[i + 1:i + 3]):
            lref.append(low[i])
    assert a == href and b == lref
