"""Causal and ledger tests; NO broker or original quote data required."""
from datetime import UTC
import numpy as np
import pandas as pd
import pytest

from scripts.gold_hunter_web_ichimoku_ckcpdi_research import (
    LICENSE_BLOB, OUNCES, SOURCE_BLOB, carry_usd, indicators, replay, wilder,
)


def raw(n=180):
    idx = pd.date_range("2024-02-01 07:30", periods=n, freq="30min", tz="UTC")
    c = np.linspace(2000, 2020, n) + np.sin(np.arange(n)/4)*2
    return pd.DataFrame({
        "bid_o": c, "bid_h": c+2, "bid_l": c-2, "bid_c": c+.1,
        "ask_o": c+.2, "ask_h": c+2.2, "ask_l": c-1.8, "ask_c": c+.3,
    }, index=idx)


def signals():
    idx = pd.date_range("2024-02-01 07:30", periods=5, freq="30min", tz="UTC")
    return pd.DataFrame({
        "bid_o": [100, 100, 100, 100, 101],
        "bid_c": [100, 100, 100, 101, 101],
        "ask_o": [100.2, 100.2, 100.2, 100.2, 101.2],
        "ask_c": [100.2, 100.2, 100.2, 101.2, 101.2],
        "ck_delta": [-1, 1, 1, -1, -1],
        "di_delta": [1, 1, 1, 1, 1],
        "cp_up": [False, True, True, False, False],
        "cp_down": [False, False, False, True, True],
    }, index=idx)


def test_upstream_original_licence_and_default_0p10_lot():
    assert SOURCE_BLOB == "7b9837c47a80928d21b6bee3e7b813d805c3e7e0"
    assert LICENSE_BLOB == "7874e8fc5b21f333b241466dbf0f0abc308d553b"
    assert OUNCES == 10


def test_wilder_sma_seed_not_future():
    x = wilder(pd.Series([1.0]*30), 14)
    assert x.iloc[:13].isna().all()
    assert np.allclose(x.iloc[13:].to_numpy(), 1)


def test_ichimoku_prefix_unchanged_if_future_prices_mutated():
    b = raw()
    a = indicators(b)
    b2 = b.copy()
    for field in ("bid_o", "bid_h", "bid_l", "bid_c"):
        b2.loc[b2.index[120]:, field] += 5000
    altered = indicators(b2)
    pd.testing.assert_frame_equal(
        a[["ck_delta", "cp_up", "cp_down", "pdi", "mdi"]].iloc[:119],
        altered[["ck_delta", "cp_up", "cp_down", "pdi", "mdi"]].iloc[:119],
    )


def test_26_bar_chikou_is_past_kijun_not_future():
    b = raw()
    a = indicators(b)
    i = 100
    k = (b["bid_h"].iloc[i-26-25:i-26+1].max()
         + b["bid_l"].iloc[i-26-25:i-26+1].min())/2
    assert a["ck_delta"].iloc[i] == pytest.approx(b["bid_c"].iloc[i]-k)


def test_causal_next_bar_entry_and_new_ck_forced_exit():
    x = signals()
    r = replay(x, slip=0, commission=0, annual_carry=0)
    assert r["closed_trades"] == 1
    assert r["trades"][0]["entry_utc"] == x.index[2].isoformat()
    assert r["trades"][0]["exit_utc"] == x.index[4].isoformat()
    assert r["trades"][0]["reason"] == "NEW_CK_CROSS"
    assert r["realized_net_usd"] == 8
    assert r["broker_orders"] == 0


def test_costs_reduce_same_trades_and_cash_ledger_reconciles():
    x = signals()
    base = replay(x, slip=0, commission=0, annual_carry=0)
    stress = replay(x, slip=.25, commission=.14, annual_carry=.09)
    assert base["closed_trades"] == stress["closed_trades"] == 1
    assert stress["realized_net_usd"] < base["realized_net_usd"]
    assert stress["marked_net_usd"] == stress["realized_net_usd"]
    assert stress["open_position_censored"] is False


def test_hypothetical_carry_is_not_broker_swap():
    t0 = pd.Timestamp("2024-01-01T00:00:00Z")
    t1 = t0+pd.Timedelta(days=365)
    assert carry_usd(100, 10, .09, t0, t1) == pytest.approx(90)
    with pytest.raises(ValueError):
        carry_usd(100, 10, .09, t1, t0)


def test_duplicate_or_reverse_timestamp_rejected():
    x = signals()
    with pytest.raises(ValueError):
        replay(x.iloc[::-1])
    with pytest.raises(ValueError):
        replay(pd.concat([x, x.iloc[[-1]]]))
