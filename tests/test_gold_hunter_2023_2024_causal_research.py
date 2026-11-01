"""Synthetic unit tests for 2023/24 source bridge; NOT trading evidence."""
import numpy as np
import pandas as pd
import pytest

from scripts.gold_hunter_2023_2024_causal_research import build_h1, digest, YEARS


def sample(minutes=60):
    dt = pd.date_range("2023-01-03T10:00:00Z", periods=minutes, freq="min")
    bid = np.linspace(1850, 1851, minutes)
    return pd.DataFrame({
        "open_time_utc": dt,
        "bid_o": bid,
        "bid_h": bid + .2,
        "bid_l": bid - .2,
        "bid_c": bid + .04,
        "ask_o": bid + .35,
        "ask_h": bid + .55,
        "ask_l": bid + .15,
        "ask_c": bid + .39,
        "spread_mean": np.repeat(.35, minutes),
        "ticks": np.ones(minutes),
    })


def test_complete_60_minute_causal_hour_uses_real_ask_open():
    h = build_h1(sample())
    assert len(h) == 1
    assert h.iloc[0]["m1_count"] == 60
    assert h.iloc[0]["observed_open_spread"] == pytest.approx(.35)
    assert h.iloc[0]["observed_max_spread"] == pytest.approx(.35)
    assert h.iloc[0]["open"] == pytest.approx(1850)
    assert h.iloc[0]["observed_open_ask"] == pytest.approx(1850.35)


def test_missing_minute_rejected_without_data_repair():
    x = sample().drop(index=17)
    with pytest.raises(ValueError, match="No admissible"):
        build_h1(x)


def test_duplicate_timestamp_rejected_instead_of_using_future_correction():
    x = pd.concat([sample(), sample().iloc[[14]]], ignore_index=True)
    with pytest.raises(ValueError, match="Bad M1 chronology"):
        build_h1(x)


def test_strict_source_years_and_reproducible_digest():
    assert YEARS == (2023, 2024)
    assert digest({"a": 1, "b": 2}) == digest({"b": 2, "a": 1})
