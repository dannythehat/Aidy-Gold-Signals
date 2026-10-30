"""Synthetic-only integrity for external academic intraday gold hypothesis."""
import pandas as pd
import pytest

from scripts.gold_hunter_web_session_drift_research import replay, GROUPS


def quotes():
    times = pd.date_range("2023-01-03T00:00:00Z", periods=48, freq="h")
    values = []
    for t in times:
        drift = 5 if t.hour >= 8 else 0
        values.append(2000 + drift + (2 if t.hour >= 20 else 0))
    return pd.DataFrame({
        "open": values, "high": [x+.6 for x in values],
        "low": [x-.6 for x in values], "close": values,
        "ask_o": [x+.4 for x in values],
        "ask_h": [x+1 for x in values],
        "ask_l": [x-.2 for x in values],
        "ask_c": [x+.4 for x in values],
    }, index=times)


def test_premarked_session_mechanics_and_quote_side():
    df = quotes()
    east = replay(df, GROUPS["EAST_LONG_00_08_UTC"], .05, 0)
    assert east["closed_trades"] == 2
    assert east["realized_net_usd"] == pytest.approx(2 * (5-.4-.1), abs=.01)
    assert all(t["exit_utc"][11:13] == "08" for t in east["trades"])
    assert east["no_stop_or_native_broker_execution"] is True


def test_later_future_hours_do_not_change_earlier_trade():
    df = quotes()
    before = replay(df, GROUPS["EAST_LONG_00_08_UTC"], .05, 0)
    changed = df.copy()
    changed.loc[changed.index[-1], "open"] += 200
    changed.loc[changed.index[-1], "ask_o"] += 200
    after = replay(changed, GROUPS["EAST_LONG_00_08_UTC"], .05, 0)
    assert before["trades"] == after["trades"]


def test_missing_exit_keeps_trade_and_charges_late_actual_gap():
    df = quotes().drop(pd.Timestamp("2023-01-03T08:00:00Z"))
    out = replay(df, GROUPS["EAST_LONG_00_08_UTC"], .25, .14)
    assert out["misses"]["late_exit"] == 1
    assert out["trades"][0]["exit_delay_minutes"] == 60.0


def test_pair_is_single_account_with_nonoverlap():
    both = replay(quotes(), GROUPS["EAST_AND_WEST_IN_ONE_ACCOUNT"], .25, .14)
    assert both["closed_trades"] == 4
    for i in range(1, len(both["trades"])):
        assert both["trades"][i]["entry_utc"] >= both["trades"][i-1]["exit_utc"]
