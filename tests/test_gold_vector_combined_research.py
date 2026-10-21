"""GOLD VECTOR AND requires both prior-close filters, one source strategy only."""
import numpy as np
import pandas as pd

from scripts.strategy_lab.gold_vector_combined_research import (
    COSTS, MONTHS, PERIODS, VARIANTS, causal_context, signals_for_variant,
)


def fixture():
    # 4 uninterrupted UTC days, fully aligned H1/H4 context
    idx=pd.date_range("2023-01-01",periods=120,freq="h").tz_localize(None)
    h1=pd.DataFrame({"close":np.arange(120,dtype=float)+1700.},index=idx)
    id4=pd.date_range("2023-01-01",periods=30,freq="4h").tz_localize(None)
    h4=pd.DataFrame({"close":np.arange(30,dtype=float)+1700.},index=id4)
    return h1,h4


def test_timing_of_complete_h4_matters_and_no_future_leak():
    h1,h4=fixture()
    path, momentum=causal_context(h1,h4)
    assert len(path)==120
    assert len(momentum)==120
    assert np.isnan(path[23])
    assert path[24]==1.0
    assert np.isnan(momentum[0])
    assert momentum[100]==6.
    # Altering a H4 bar that is not yet complete at signal close must not
    # affect the feature value at that H1 timestamp.
    x=h4.copy()
    x.iloc[25,x.columns.get_loc("close")]=-20000.0
    _,momentum_changed=causal_context(h1,x)
    assert momentum_changed[98] == momentum[98]  # 98th H1 hour ends before H4 25 closes


def test_causal_path_efficiency_no_hindsight_dependence():
    h1,h4=fixture()
    p,m=causal_context(h1,h4)
    copy=h1.copy()
    copy.loc[copy.index[-1],"close"]=-10000.
    p2,m2=causal_context(copy,h4)
    assert np.array_equal(p[:-1],p2[:-1],equal_nan=True)
    assert np.array_equal(m,m2,equal_nan=True)


def test_exits_immutable_and_combined_requires_both_conditions():
    h1,h4=fixture()
    p,m=causal_context(h1,h4)
    l=np.ones(120,dtype=bool)
    s=np.ones(120,dtype=bool)
    lx=np.arange(120)%2==0
    sx=np.arange(120)%3==0
    base=(l,s,lx,sx)
    for label in VARIANTS:
        x=signals_for_variant(base,p,m,label)
        assert np.array_equal(lx,x[2]) and np.array_equal(sx,x[3])
        assert not np.shares_memory(x[2],lx)
        assert not np.shares_memory(x[3],sx)
    a=signals_for_variant(base,p,m,"A_H1_PATH_EFFICIENCY_0P30")
    assert not a[0][23] and a[0][24]
    b=signals_for_variant(base,p,m,"B_H4_SIX_BAR_MOMENTUM_AGREES")
    assert b[0][100] and not b[1][100]
    assert COSTS == (0.45,0.90)
    assert len(MONTHS["2023_2024"])==25
    assert len(MONTHS["2025_2026"])==22
    assert PERIODS["2026_JAN_SEP"][2]=="2026-10-01"

def test_gold_vector_is_intersection_not_capital_sleeves():
    h1,h4=fixture()
    path,momentum=causal_context(h1,h4)
    long0=np.ones(len(h1),dtype=bool)
    short0=np.ones(len(h1),dtype=bool)
    longexit=np.arange(len(h1))%3==0
    shortexit=np.arange(len(h1))%4==0
    original=(long0,short0,longexit,shortexit)
    a=signals_for_variant(original,path,momentum,"A_H1_PATH_EFFICIENCY_0P30")
    b=signals_for_variant(original,path,momentum,"B_H4_SIX_BAR_MOMENTUM_AGREES")
    combined=signals_for_variant(original,path,momentum,"GOLD_VECTOR_H1_PATH_AND_H4_CONFIRM")
    assert np.array_equal(combined[0],a[0]&b[0])
    assert np.array_equal(combined[1],a[1]&b[1])
    assert np.array_equal(combined[2],longexit)
    assert np.array_equal(combined[3],shortexit)
    assert not combined[0][23] and combined[0][100]
    assert not combined[1][100]
    h4_changed=h4.copy()
    h4_changed.iloc[25,h4_changed.columns.get_loc("close")]=-20000.0
    _,updated=causal_context(h1,h4_changed)
    latest=signals_for_variant(original,path,updated,"GOLD_VECTOR_H1_PATH_AND_H4_CONFIRM")
    assert np.array_equal(combined[0][:98],latest[0][:98])
    assert np.array_equal(combined[1][:98],latest[1][:98])
    assert VARIANTS[-1]=="GOLD_VECTOR_H1_PATH_AND_H4_CONFIRM"
