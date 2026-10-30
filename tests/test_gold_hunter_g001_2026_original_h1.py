"""Synthetic provenance, daily-causality and chronology checks, not real profits."""
import numpy as np
import pandas as pd
import pytest
from scripts.gold_hunter_g001_2026_original_h1 import feature_extension

def make_daily():
    prev=pd.bdate_range("2025-01-01",periods=260,tz="UTC")
    next_=pd.bdate_range("2026-01-01",periods=180,tz="UTC")
    def days(idx,offset):
        n=len(idx)
        close=1900+offset+np.arange(n)*2.+8*np.sin(np.arange(n)/7)
        return pd.DataFrame({
            "first_utc":idx, "bid_o":close-.5, "ask_o":close-.1,
            "high":close+3,"low":close-3,"close":close,
            "m1_count":[1200]*n},index=idx)
    return days(prev,0),days(next_,600)

def test_2026_indicators_use_past_2025_warmup():
    older,new=make_daily()
    d=feature_extension(older,new)
    assert len(d)==440
    assert d.loc[new.index[0],"sma200"]>0
    assert d.loc[new.index[0],"atr14"]>0
    assert d.loc[new.index[0],"momentum"]==pytest.approx(
        (d.loc[new.index[0],"close"]-d.loc[d.index[-21],"close"])/d.loc[new.index[0],"atr14"])

def test_future_original_quote_mutation_does_not_change_previous_signals():
    older,new=make_daily()
    d=feature_extension(older,new)
    mutant=new.copy()
    mutant.loc[mutant.index[150]:,"close"]+=2000
    mutant.loc[mutant.index[150]:,"high"]+=2000
    revised=feature_extension(older,mutant)
    np.testing.assert_array_equal(d.loc[d.index[:395],"setup"].to_numpy(),
                                  revised.loc[revised.index[:395],"setup"].to_numpy())

def test_overlapping_source_year_must_fail():
    old,new=make_daily()
    with pytest.raises(ValueError,match="overlap"):
        feature_extension(old,old.iloc[-10:])
