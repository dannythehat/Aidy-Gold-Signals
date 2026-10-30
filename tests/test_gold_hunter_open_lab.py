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
        assert all(t["risk_usd"]<=t["equity_at_entry"]*.005+1e-6 for t in result["trades"])
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


def test_causal_spread_v2_never_uses_future_hour_high_spread_to_admit_short():
    """An intrahour future spread must not decide a short at the hour's open."""
    from gold_hunter.open_strategy_lab import replay_causal_v2

    def case(future_spread):
        clock = pd.date_range("2024-01-02 10:00:00", periods=3, freq="h", tz="UTC")
        return pd.DataFrame({
            "open_time_utc": clock,
            "open": [100., 100., 99.8],
            "high": [100.5, 100.5, 100.],
            "low": [99.5, 99., 99.],
            "close": [100., 99.8, 99.7],
            "observed_open_ask": [100.4, 100.4, 100.2],
            "observed_open_spread": [.4, .4, .4],
            "observed_max_spread": [.4, future_spread, .4],
        })

    signal = {
        "system": "DONCHIAN_TREND",
        "side": -1,
        "signal_bar_index": 0,
        "signal_utc": "2024-01-02T11:00:00+00:00",
        "stop": 102.,
        "target": 94.,
        "source": "synthetic causality regression only",
    }
    tape = ((signal,), (), ())
    settings = Settings(observed_quote_mode=True)
    before = replay(case(.4), tape, ("DONCHIAN_TREND",), settings)
    legacy_future = replay(case(3.), tape, ("DONCHIAN_TREND",), settings)
    assert before["selected_counts"] == {"DONCHIAN_TREND": 1}
    assert legacy_future["selected_counts"] == {}  # documented v0 lookahead issue

    v2_before = replay_causal_v2(case(.4), tape, ("DONCHIAN_TREND",), settings)
    v2_future = replay_causal_v2(case(3.), tape, ("DONCHIAN_TREND",), settings)
    assert v2_before["selected_counts"] == v2_future["selected_counts"]
    assert v2_before["selected_counts"] == {"DONCHIAN_TREND": 1}
    assert v2_future["research_model_revision"] == "v2_causal_open_spread_at_entry"
    assert "research_model_revision" not in before  # preserve original ledger contract

    with pytest.raises(ValueError, match="source-verified observed ASK"):
        replay_causal_v2(case(.4), tape, ("DONCHIAN_TREND",), Settings())
