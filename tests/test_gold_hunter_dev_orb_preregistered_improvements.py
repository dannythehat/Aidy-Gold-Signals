"""Predetermined, independent Gold ORB improvements cannot look into the future."""
import copy
import pytest
from scripts.gold_hunter_dev_orb_preregistered_improvements import (
   VARIANTS,YEAR_LABELS,candidate_filter
)

def make_signal():
    return {"direction":1,"range_high_bid":2400.,"range_low_bid":2385.,
            "signal_closed_bid":2405.,"ema50_bid":2395.,"atr14_bid":10.,
            "entry_idx":100,"entry_at_utc":"2024-02-01T17:00:00+00:00"}

def test_regime_filters_known_only_at_completed_signal_close():
    x=make_signal()
    for v in VARIANTS:
        assert len(candidate_filter([x],v))==1, v
    x["signal_closed_bid"]=2402.
    assert not candidate_filter([x],"BREAK_BUFFER_025")
    assert not candidate_filter([x],"BUFFER_WIDTH_LOW")
    assert candidate_filter([x],"RANGE_WIDTH_15")
    x["range_low_bid"]=2390.
    assert not candidate_filter([x],"RANGE_WIDTH_15")
    assert candidate_filter([x],"BASE_2PCT")

def test_filter_never_reads_future_or_mutates_source():
    s=make_signal()
    old=copy.deepcopy(s)
    original=candidate_filter([s],"BREAK_BUFFER_025")
    s["future_after_fill"]=1e50
    s["next_day_gold_price"]=-1e50
    new=candidate_filter([s],"BREAK_BUFFER_025")
    assert new==original
    assert old["range_high_bid"]==2400
    assert set(YEAR_LABELS)=={
      "2022","2023","2024","2025","2026_jan_sep",
      "2025_to_2026_sep_continuous"}

def test_no_hidden_grid_allowed():
    with pytest.raises(ValueError,match="Unknown"):
        candidate_filter([make_signal()],"BEST_2025_OPTIMIZED")
