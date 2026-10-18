"""S002 original author's economic win-label and fail-closed capital tests."""
import pandas as pd

from scripts.strategy_lab.s002_original_source_two_period_screen import (
    PERIODS, RULES, author_daily_bias_and_levels, simulate,
    true_price_and_costs,
)


def sample(year="2025"):
    timestamps=pd.to_datetime([
        f"{year}-01-06 15:00:00",
        f"{year}-01-06 15:15:00",
        f"{year}-01-07 15:00:00",
        f"{year}-01-07 15:15:00",
        f"{year}-01-07 15:30:00",
        f"{year}-01-07 15:45:00",
    ])
    # Prior day OPEN-CLOSE positive => publisher labels next day bullish.
    opening=[100.,100.,98.,99.,98.5,98.5]
    ending=[99.,99.,98.,99.,98.5,98.5]
    return pd.DataFrame({
        "open":opening,"close":ending,
        "high":[101.,101.,98.5,99.5,99.,99.],
        "low":[99.,99.,97.5,98.5,98.,98.],
        "observed_open_ask":[x+.4 for x in opening],
        "observed_open_spread":[.4]*6,
    },index=timestamps)


def test_author_labels_real_losing_trade_win():
    source,days=author_daily_bias_and_levels(sample())
    assert bool(days.loc[pd.Timestamp("2025-01-07").date(),"prev_bullish"])
    r=simulate(source,days,"2025","source_literal")
    assert r["trades"]>=1
    x=r["trade_ledger"][0]
    assert x["source_label"]=="WIN"
    assert x["entry_bid"]==99.
    assert x["exit_bid"]==98.5
    assert x["net_usd"]<0
    assert r["source_WIN_but_nonpositive_net_trades"]>=1
    assert r["starting_usd"]==10000
    assert r["ending_usd"]<10000


def test_next_year_independent_10k_and_not_a_protective_stop():
    src,days=author_daily_bias_and_levels(sample("2026"))
    r=simulate(src,days,"2026","source_literal")
    assert r["starting_usd"]==10000
    assert r["net_usd"]<0
    assert RULES["protective_stop_price_in_author_code"] is None
    assert len(r["monthly"])==PERIODS["2026"][2]


def test_source_bid_ask_costs_count_once_and_stress_worsens():
    df=sample()
    p=df.iloc[3]
    x=df.iloc[4]
    base=true_price_and_costs(p,x,1)
    stress=true_price_and_costs(p,x,1,slippage_mult=2,spread_mult=2)
    assert base["gross_usd"]==-.5
    assert abs(base["observed_spread_cost_usd"]-.4)<.00001
    assert abs(base["commission_usd"]-.07)<.00001
    assert stress["net_usd"]<base["net_usd"]


def test_source_bullish_definition_reverses_readme():
    src,summary=author_daily_bias_and_levels(sample())
    assert summary.loc[pd.Timestamp("2025-01-06").date(),"code_bias_sum"]>0
    assert summary.loc[pd.Timestamp("2025-01-06").date(),"author_bullish"]
    assert not (src.loc[pd.Timestamp("2025-01-06 15:00"),"close"]>
                src.loc[pd.Timestamp("2025-01-06 15:00"),"open"])
