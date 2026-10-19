"""S005 independent source quote, cost and evidence safeguards."""
import math

import pandas as pd

from scripts.strategy_lab.s005_all497_source_cost_regime_robustness import (
    _annotate_one,
    _resample_months,
    _signed_summary,
    _source_monthly_values,
)


def _bar():
    idx=pd.date_range("2025-01-01 00:00:00",periods=2,freq="15min")
    return pd.DataFrame({
       "open":[2600.,2601.],"observed_open_ask":[2600.65,2601.4],
       "observed_open_spread":[.65,.4]
    },index=idx)


def test_long_original_pnl_dollars_proved_and_quote_spread_separate():
    record={
       "entry_time_utc":"2025-01-01 00:00:00Z",
       "exit_time_utc":"2025-01-01 00:15:00Z",
       "entry_price_publisher_bid_proxy":2600.0,
       "exit_price_publisher_bid_proxy":2601.0,
       "units_float_not_broker_lots":5.0,
       "publisher_costed_usd":2.75,
       "direction":"LONG","reason":"signal"
    }
    trend=pd.Series([4.0],index=[pd.Timestamp("2025-01-01 00:00:00")])
    r=_annotate_one(record,_bar(),trend,"2025","DONCHIAN",0)
    assert r["independent_recalculated_publisher_net_usd"]==2.75
    assert r["real_histdata_entry_ask"]==2600.65
    assert r["real_entry_spread_exceeds_publishers_ENTIRE_0p45_cost"]
    assert math.isclose(r["entry_spread_quote_proxy_adjusted_net_usd"],.4)
    assert r["market_regime_at_entry"]=="PREVIOUS_24_COMPLETE_H1_RISING"
    assert r["quote_proxy_is_NOT_verified_MQL5_trade_fill"]


def test_short_explicitly_disclaims_exit_ask_not_entry_proxy():
    record={
       "entry_time_utc":"2025-01-01 00:00:00Z",
       "exit_time_utc":"2025-01-01 00:15:00Z",
       "entry_price_publisher_bid_proxy":2600.,
       "exit_price_publisher_bid_proxy":2599.,
       "units_float_not_broker_lots":2.,
       "publisher_costed_usd":1.10,
       "direction":"SHORT","reason":"sl"
    }
    r=_annotate_one(record,_bar(),pd.Series(dtype=float),
                       "2025","DONCHIAN",0)
    assert r["short_spread_caveat"]=="SHORT_PAY_SPREAD_AT_EXIT_NOT_ENTRY"
    assert r["market_regime_at_entry"]=="UNKNOWN_WARMUP"


def test_corrupt_publisher_profit_fail_closed():
    row={
       "entry_time_utc":"2025-01-01 00:00:00Z",
       "exit_time_utc":"2025-01-01 00:15:00Z",
       "entry_price_publisher_bid_proxy":2600.,
       "exit_price_publisher_bid_proxy":2601.,
       "units_float_not_broker_lots":5.,
       "publisher_costed_usd":999.,
       "direction":"LONG","reason":"signal"
    }
    import pytest
    with pytest.raises(ValueError,match="DOES NOT RECONCILE"):
        _annotate_one(row,_bar(),pd.Series(dtype=float),"2025","DONCHIAN",0)


def test_full_12_and_9_source_months_no_synthetic_profits():
    rows=[{"exit_time_utc":"2025-01-03 11:00:00Z",
       "publisher_costed_usd":100.},
      {"exit_time_utc":"2025-03-03 11:00:00Z",
       "publisher_costed_usd":-50.}]
    values=_source_monthly_values(rows,"2025")
    assert len(values)==12 and sum(values)==50
    assert values[1]==0
    assert len(_source_monthly_values([], "2026"))==9
    a=_resample_months(values,"2025","DONCHIAN")
    b=_resample_months(values,"2025","DONCHIAN")
    assert a==b and a["proof_is_independent_OOS"] is False
    assert a["month_blocks_nonindependent"]
    assert a["q025_usd"]<=a["q975_usd"]


def test_trend_buckets_are_descriptive_and_preserve_original_trade_count():
    rows=[{"direction":"LONG","publisher_costed_usd":5.},
      {"direction":"LONG","publisher_costed_usd":-2.},
      {"direction":"SHORT","publisher_costed_usd":-3.}]
    x=_signed_summary(rows,"direction")
    assert x["LONG"]["trades"]==2 and x["LONG"]["net_usd"]==3.
    assert x["SHORT"]["trades"]==1 and x["SHORT"]["net_usd"]==-3.
    assert len(x)==2
