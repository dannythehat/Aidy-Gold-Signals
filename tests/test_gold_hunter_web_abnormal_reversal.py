"""Synthetic tests only; all performance claims require authenticated AIDY CI."""
import numpy as np
import pandas as pd
import pytest

from scripts.gold_hunter_web_abnormal_reversal import (
    MODES, qualified_days, run_mode,
)


def fixture():
    frames = []
    days = pd.bdate_range("2023-01-02", periods=84, tz="UTC")
    for i, date in enumerate(days):
        returns = .001*np.sin(i*1.37) if i != 66 else .06
        t = pd.date_range(date, periods=22, freq="h")
        x = np.linspace(1900, 1900*(1+returns), len(t))
        frames.append(pd.DataFrame({
            "open": x, "high": x+.8, "low": x-.8, "close": x,
            "ask_o": x+.4, "ask_h": x+1.2, "ask_l": x-.4,
            "ask_c": x+.4,
        }, index=t))
    return pd.concat(frames)


def test_no_future_data_in_event_detection():
    a = fixture()
    b = a.copy()
    last = b.index.max()
    b.loc[last, "close"] += 500
    x, y = qualified_days(a), qualified_days(b)
    assert x.iloc[:-1]["event_side"].equals(y.iloc[:-1]["event_side"])
    assert x["event_side"].iloc[66] == 1
    assert x["past_sigma"].iloc[66] > 0
    assert x["event_side"].iloc[:50].eq(0).all()


def test_reverse_previous_abnormal_is_not_future_direction():
    raw = fixture()
    day = qualified_days(raw)
    result = run_mode(raw, day, "NEXT_DAY_REVERSAL_06UTC", .25, .14)
    assert result["closed_trades"] >= 1
    assert result["max_closed_equity_drawdown_pct"] <= 0
    assert result["intratrade_drawdown_not_measured"] is True
    assert sum(t["pnl_usd"] for t in result["trades"]) == pytest.approx(
        result["realized_net_usd"], abs=.01)
    event = [x for x in result["trades"] if x["event_day"] ==
             day.index[66].strftime("%Y-%m-%d")]
    assert len(event) == 1
    assert event[0]["side"] == -1


def test_controls_are_same_event_opposite_side():
    data = fixture()
    days = qualified_days(data)
    rev = run_mode(data, days, "NEXT_DAY_REVERSAL_06UTC", .05, 0)
    momentum = run_mode(data, days, "NEXT_DAY_MOMENTUM_06UTC_CONTROL", .05, 0)
    assert rev["closed_trades"] == momentum["closed_trades"]
    assert all(a["side"] == -b["side"] for a, b in
               zip(rev["trades"], momentum["trades"]))
    assert set(MODES) == {"NEXT_DAY_REVERSAL_06UTC", "NEXT_DAY_REVERSAL_20UTC",
                          "NEXT_DAY_MOMENTUM_06UTC_CONTROL"}
