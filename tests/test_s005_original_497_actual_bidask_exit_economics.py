"""Actual BID ASK quote-side 497-cohort economics, adversarial and proven caveats."""
import pytest

from scripts.strategy_lab.s005_original_fixed_cohort_real_tick_quote_economics import (
    annotate_trade,
)


def _original(side="LONG", reason="signal"):
    islong=side=="LONG"
    orig={
        "direction":side,"reason":reason,
        "entry_price_publisher_bid_proxy":2600.0,
        "exit_price_publisher_bid_proxy":2601.0 if islong else 2599.0,
        "units_float_not_broker_lots":2.0,
        "publisher_costed_usd":1.10,
        "entry_time_utc":"2025-01-01 00:00:00Z",
        "exit_time_utc":"2025-01-01 01:00:00Z",
    }
    return orig


def _raw(side="LONG", stop=False):
    entry={"instant_epoch_us":1000000,"bid":2600.0,"ask":2600.6}
    last={"instant_epoch_us":3000000,"bid":2601.0,"ask":2601.8}
    crossed={"instant_epoch_us":2000000,"bid":2597.5,"ask":2602.5} if stop else None
    return {
       "id":"S005-DONCHIAN-2025-0000",
       "family":"DONCHIAN","year":"2025","n":0,
       "direction":side,"original_exit_reason":"sl" if stop else "signal",
       "first_original_entry_raw_tick":entry,
       "last_original_window_raw_tick":last,
       "first_true_quote_side_stop_crossing":crossed,
    }


def test_long_enters_ask_closes_bid_not_bid_bid_proxy():
    item=annotate_trade(_raw(),_original(),1)
    assert item["source_side_entry_price"]==2600.6
    assert item["source_side_exit_price"]==2601.0
    assert item["source_original_frozen_cohort_repriced_usd"]==.26
    assert item["native_broker_MT5_fill_certified"] is False


def test_short_enters_bid_closes_actual_ask():
    p=annotate_trade(_raw("SHORT"),_original("SHORT"),1)
    assert p["source_side_entry_price"]==2600.0
    assert p["source_side_exit_price"]==2601.8
    assert p["source_original_frozen_cohort_repriced_usd"]==-4.14
    assert p["exit_path"]=="LAST_TRUE_SOURCE_QUOTE_IN_ORIGINAL_H1_EXIT_WINDOW"


def test_first_real_stop_bid_preempts_later_signal_close():
    data=_raw("LONG",stop=True)
    item=annotate_trade(data,_original("LONG",reason="sl"),1)
    assert item["source_side_exit_price"]==2597.5
    assert item["exit_path"]=="FIRST_TRUE_SOURCE_STOP_QUOTE"
    assert item["raw_first_STOP_before_source_close"] is True
    assert item["source_original_frozen_cohort_repriced_usd"]==-6.74


def test_last_quote_cannot_be_earlier_than_first_real_stop():
    data=_raw("LONG",stop=True)
    data["last_original_window_raw_tick"]["instant_epoch_us"]=1000001
    with pytest.raises(ValueError,match="Stop quote after"):
        annotate_trade(data,_original("LONG",reason="sl"),1)


def test_frozen_original_author_pnl_wrong_fails_closed():
    original=_original()
    original["publisher_costed_usd"]=99
    with pytest.raises(ValueError,match="arithmetic"):
        annotate_trade(_raw(),original,1)


def test_cost_doubles_only_cost_not_source_quote_prices():
    a=annotate_trade(_raw(),_original(),1)
    b=annotate_trade(_raw(),_original(),2)
    assert a["source_side_entry_price"]==b["source_side_entry_price"]
    assert a["source_side_exit_price"]==b["source_side_exit_price"]
    assert b["source_original_frozen_cohort_repriced_usd"]<a["source_original_frozen_cohort_repriced_usd"]
