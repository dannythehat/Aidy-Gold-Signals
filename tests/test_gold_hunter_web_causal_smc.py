"""Synthetic causal contract only, not gold performance evidence."""
import math

import pandas as pd
import pytest

from gold_hunter.open_strategy_lab import Settings, replay_causal_v2
from scripts.gold_hunter_web_causal_smc import (
    GROUPS, make_tape, SCORE8, STRICT12,
)


def fixture(n=800):
    clock=pd.date_range("2023-01-01T00:00:00Z",periods=n,freq="h")
    price=[1850+math.sin(i/19)*12 + i*.09 for i in range(n)]
    close=[p+math.sin(i/3) for i,p in enumerate(price)]
    return pd.DataFrame({
        "open_time_utc":clock, "open":price,
        "high":[max(close[i],price[i])+1 for i in range(n)],
        "low":[min(close[i],price[i])-1 for i in range(n)],
        "close":close,"m1_count":[60]*n,
        "observed_open_ask":[p+.4 for p in price],
        "observed_open_spread":[.4]*n,
        "observed_max_spread":[.6]*n,
    })


def test_pinned_source_h4_and_day_causality_on_truncated_history():
    raw=fixture()
    left,a,_=make_tape(raw)
    right,b,_=make_tape(raw.iloc[:710].copy())
    assert left.iloc[700]["open_time_utc"] == right.iloc[700]["open_time_utc"]
    for name in GROUPS:
        assert a[name][:705] == b[name][:705]


def test_true_fvg_strict_not_source_broken_low_low_rule():
    raw=fixture()
    df,tape,signals=make_tape(raw)
    assert len(df)==800
    assert len(tape[SCORE8])==800
    assert len(tape[STRICT12])==800
    assert signals["signals_by_family"][STRICT12] <= signals["signals_by_family"][SCORE8]
    assert signals["closed_h4_nonzero"]>0


def test_causal_execution_and_reconciliation():
    raw=fixture()
    df,tapes,_=make_tape(raw)
    for name,arms in GROUPS.items():
        x=replay_causal_v2(df,tapes[name],arms,Settings(observed_quote_mode=True))
        assert x["closed_trades"] == len(x["trades"])
        assert x["research_model_revision"] == "v2_causal_open_spread_at_entry"
        assert sum(t["pnl_usd"] for t in x["trades"]) == pytest.approx(
            x["realized_net_usd"], abs=.01)
