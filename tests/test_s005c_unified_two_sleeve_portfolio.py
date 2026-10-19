"""S005-C source-frozen TWO $5k sleeve funding and causal hybrid contracts."""
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from scripts.strategy_lab.s005c_unified_two_sleeve_portfolio import (
    ACCOUNT, SLEEVE, closed_signal_ema_mask, gate_session_signals,
    merge_portfolio,
)


def fake_result(trades, equity):
    return SimpleNamespace(trades=trades, equity=np.asarray(equity,dtype=float))


def trade(entry=0,exit=2,direction=1,units=1.0,pnl=100.):
    return SimpleNamespace(entry_i=entry,exit_i=exit,dir=direction,
      units=units,pnl=pnl,entry_px=2000.,exit_px=2100.,reason="signal")


def tape(length=4):
    ix=pd.date_range("2025-01-01",periods=length,freq="h")
    return pd.DataFrame({"close":np.full(length,2000.)},index=ix)


def test_one_master_combines_tiny_pnl_but_not_double_capital():
    d=fake_result([trade(pnl=100.)],[5000.,5030.,5100.,5100.])
    s=fake_result([trade(pnl=-50.,direction=-1)],[5000.,4990.,4950.,4950.])
    x=merge_portfolio(d,s,0,4,tape(),"S005_C_PARALLEL","2025")
    assert x["master_initial_cash_usd"]==10000.
    assert x["donchian_allocated_initial_usd"]==5000.
    assert x["session_allocated_initial_usd"]==5000.
    assert x["master_ending_marked_equity_PY_model_usd"]==10050.
    assert x["master_realized_PY_model_net_usd"]==50.
    assert x["total_trades"]==2
    assert x["opposing_gold_positions_H1_bars"]==3
    assert x["requires_hedging_ability_if_opposite_exposure"] is True
    assert x["native_account_margin_stopouts_applied"] is False


def test_one_sleeve_idle_preserves_5000_cash():
    d=fake_result([trade(pnl=100.)],[5000.,5030.,5100.,5100.])
    x=merge_portfolio(d,None,0,4,tape(),"DON_ONLY","2025")
    assert x["master_ending_marked_equity_PY_model_usd"]==10100.
    assert x["session_source_net_usd"]==0.
    assert x["total_trades"]==1
    assert x["opposing_gold_positions_H1_bars"]==0


def test_duplicated_10000_per_sleeve_not_accepted():
    d=fake_result([trade(pnl=100.)],[10000.,10030.,10100.,10100.])
    s=fake_result([trade(pnl=-50.)],[10000.,9990.,9950.,9950.])
    with pytest.raises(ValueError,match="First combined portfolio"):
        merge_portfolio(d,s,0,4,tape(),"S005_C_PARALLEL","2025")


def test_causal_session_ema_filter_keeps_exit_rules_and_no_future_dependency():
    c=np.asarray([1.,2.,4.,3.,2.,10.])
    a=np.asarray([False,True,True,False,True,False])
    b=np.asarray([False,False,False,True,False,True])
    exl=np.asarray([False,False,True,False,False,True])
    exs=np.asarray([False,True,False,False,True,False])
    originals=(a,b,exl,exs)
    (gl,gs,lx,sx),meta=gate_session_signals(originals,c)
    allowed_long,allowed_short=closed_signal_ema_mask(c)
    assert np.array_equal(gl,a&allowed_long)
    assert np.array_equal(gs,b&allowed_short)
    assert np.array_equal(lx,exl)
    assert np.array_equal(sx,exs)
    assert meta["exits_unchanged"]
    changed=c.copy()
    changed[-1]=1_000_000
    (_,_,_,_),_meta=gate_session_signals(originals,changed)
    filt_before=gate_session_signals(originals,c)[0][0][:-1]
    filt_after=gate_session_signals(originals,changed)[0][0][:-1]
    assert np.array_equal(filt_before,filt_after)
    assert ACCOUNT==2*SLEEVE==10000


def test_master_ledger_not_compatible_with_unexplained_total():
    d=fake_result([trade(pnl=100.)],[5000.,5030.,5070.,5099.])
    s=fake_result([],np.full(4,5000.))
    with pytest.raises(ValueError,match="does not reconcile"):
        merge_portfolio(d,s,0,4,tape(),"DON_ONLY","2025")
