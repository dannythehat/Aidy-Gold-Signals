"""Open-strategy lab integrity: synthetic fixtures are NOT performance evidence."""
import math

import pandas as pd
import pytest

from gold_hunter.open_strategy_lab import (
    SYSTEMS, Settings, indicators, signal_tape, replay, run_family_matrix,
)


def fixture(n=850):
    t = pd.date_range("2025-01-01", periods=n, freq="h", tz="UTC")
    price=[2700 + .07*i + 26*math.sin(i/23)+5*math.sin(i/6) for i in range(n)]
    close=[v+math.sin(i/3) for i,v in enumerate(price)]
    return pd.DataFrame({
        "open_time_utc":[x.isoformat() for x in t],
        "open":price,"close":close,
        "high":[max(price[i],close[i])+2 for i in range(n)],
        "low":[min(price[i],close[i])-2 for i in range(n)],
        "m1_count":[60]*n,
    })


def test_all_five_methods_and_costed_replay_repeatable():
    raw=fixture()
    outcomes=run_family_matrix(raw,Settings())
    assert set(SYSTEMS).issubset(outcomes)
    assert "ALL_FIVE" in outcomes
    for result in outcomes.values():
        assert result["closed_trades"] == len(result["trades"])
        assert result["net_marked_usd"] == round(
            result["realized_net_usd"] + (
                result["censored_open"]["modelled_unrealized_usd"]
                if result["censored_open"] else 0),2)
        assert result["max_marked_drawdown_pct"] <= 0
        assert all(t["signal_utc"]<=t["entry_utc"] for t in result["trades"])
        assert all(t["risk_usd"]<=10000*.005+1e-6 for t in result["trades"])
    assert run_family_matrix(raw,Settings())==outcomes


def test_prefix_causality_and_source_coverage():
    raw=fixture(900)
    a, signals=signal_tape(raw)
    later=raw.copy()
    later.loc[800,["open","close","high","low"]]=[8000,8000,8001,7999]
    b, signals_new=signal_tape(later)
    assert signals[:799]==signals_new[:799]
    assert a.loc[750,"prior20hi"] == b.loc[750,"prior20hi"]
    assert all(x["signal_bar_index"]==i
               for i, candidates in enumerate(signals) for x in candidates)


def test_observed_ask_is_mandatory_for_original_quote_mode():
    raw=fixture()
    base,tape=signal_tape(raw)
    with pytest.raises(ValueError,match="Original observed ASK"):
        replay(base,tape,SYSTEMS,Settings(observed_quote_mode=True))
    raw["observed_open_spread"]=.85
    raw["observed_open_ask"]=raw["open"]+.85
    raw["observed_max_spread"]=2.40
    df,signals=signal_tape(raw)
    out=replay(df,signals,SYSTEMS,Settings(observed_quote_mode=True))
    assert out["settings"]["observed_quote_mode"] is True
    assert out["source_bars"]==850
    assert out["schema"].startswith("gold_hunter.")


def test_no_future_quotes_change_closed_past_candidate():
    raw=fixture(900)
    raw["observed_open_spread"]=.65
    raw["observed_open_ask"]=raw["open"]+.65
    raw["observed_max_spread"]=1.2
    _,first=signal_tape(raw)
    changed=raw.copy()
    changed.loc[880,"observed_open_spread"]=8
    changed.loc[880,"observed_open_ask"]=changed.loc[880,"open"]+8
    changed.loc[880,"observed_max_spread"]=9
    _,second=signal_tape(changed)
    assert first[:870]==second[:870]


def test_fail_closed_unknown_strategy_and_invalid_risk():
    df,tape=signal_tape(fixture())
    with pytest.raises(ValueError):
        replay(df,tape,("INVENTED_SYSTEM",),Settings())
    with pytest.raises(ValueError):
        replay(df,tape,SYSTEMS,Settings(risk_fraction=.04))
    with pytest.raises(ValueError):
        replay(df,tape[:-2],SYSTEMS,Settings())
