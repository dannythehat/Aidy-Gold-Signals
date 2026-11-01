"""FROZEN open-lab five-method baseline plus five NEW method contract tests.

These tests use artificial prices for causality, NOT performance validation.
"""
import pandas as pd
import pytest

from gold_hunter.open_strategy_lab import (
    BASELINE_FIVE, NEW_FIVE, SYSTEMS, Settings, indicators,
    signal_tape, replay, run_family_matrix,
)
from test_gold_hunter_open_lab import fixture


def test_exactly_ten_distinct_research_methods_and_original_five_preserved():
    assert len(BASELINE_FIVE) == 5 and len(NEW_FIVE) == 5
    assert len(set(SYSTEMS)) == 10
    assert BASELINE_FIVE == SYSTEMS[:5]
    data=fixture(850)
    df,tape=signal_tape(data)
    matrix=run_family_matrix(data,Settings())
    assert set(("ALL_FIVE","ALL_TEN","FIVE_NEW")).issubset(matrix)
    assert set(NEW_FIVE).issubset(matrix)
    frozen=replay(df,tape,BASELINE_FIVE,Settings())
    assert frozen == matrix["ALL_FIVE"]
    for result in matrix.values():
        assert result["closed_trades"] == len(result["trades"])
        assert all(t["signal_utc"]<=t["entry_utc"] for t in result["trades"])


def test_prior_day_boundaries_cannot_know_current_day_high():
    df=indicators(fixture(800))
    for date,frame in df.groupby("date"):
        earlier=df.loc[df["date"] < date]
        if earlier.empty:
            assert pd.isna(frame.iloc[0]["prior_day_hi"])
        else:
            previous_day=earlier["date"].iloc[-1]
            old=earlier.loc[earlier["date"] == previous_day]
            assert frame["prior_day_hi"].eq(float(old["high"].max())).all()
            assert frame["prior_day_lo"].eq(float(old["low"].min())).all()


def test_ten_method_signals_never_change_when_only_future_prices_change():
    data=fixture(950)
    _, before=signal_tape(data)
    later=data.copy()
    later.loc[911,["open","close","high","low"]]=[8000.,8000.,8010.,7990.]
    _, after=signal_tape(later)
    assert before[:911] == after[:911]
    assert all(x["system"] in SYSTEMS and x["signal_bar_index"] == i
               for i,group in enumerate(before) for x in group)


def test_quote_and_risk_guards_unchanged_with_ten_methods():
    data=fixture(850)
    df,tape=signal_tape(data)
    with pytest.raises(ValueError):
        replay(df,tape,("FAKE_WINNING_SYSTEM",),Settings())
    with pytest.raises(ValueError):
        replay(df,tape,SYSTEMS,Settings(risk_fraction=.03))
    with pytest.raises(ValueError):
        replay(df,tape,SYSTEMS,Settings(observed_quote_mode=True))
