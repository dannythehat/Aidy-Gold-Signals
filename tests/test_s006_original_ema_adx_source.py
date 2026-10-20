"""S006 original author EMA 9/120: independent source proof and safety."""
import numpy as np

from scripts.strategy_lab.s006_publisher_ema_adx_original_h1_real_spot import (
    AUTHOR,BLOBS,VARIANTS,ENGINE,gitblob,signal_independent,
)


def test_public_source_and_scope_pin_preclude_s005_mql_preset_relabelling():
    assert len(AUTHOR)==40
    assert len(BLOBS)==5
    assert len(VARIANTS)==3
    assert VARIANTS["EMA_9_120_ADX_0_SOURCE_LEADERBOARD"]=={
        "fast":9,"slow":120,"adx_min":0}
    assert VARIANTS["EMA_9_120_ADX_20_SOURCE_GRID"]["adx_min"]==20
    assert VARIANTS["EMA_9_120_ADX_25_SOURCE_GRID"]["adx_min"]==25
    assert ENGINE["sl_atr"]==2.
    assert ENGINE["trail_atr"]==3.5
    assert ENGINE["tp_atr"]==0.
    assert ENGINE["risk_pct"]==1.
    assert ENGINE["start_equity"]==10000.


def test_github_source_blob_sha_is_full_git_blob_not_payload_hash():
    assert gitblob(b"test content")=="08cf6101416f0ce0dda3c80e627f333854c4085c"
    assert BLOBS["strategies.py"]=="9abe69680df34064923e01236cbf9b77d486c682"


def test_closed_bar_entry_crosses_have_no_future_bar_leak():
    # EMA9/120 needs enough history for stable slow mean, and no cross
    # means no source trade. Freeze all values until last bar and
    # perturb future bar: old crossover flags must not change.
    c=np.array([110.-i*.01 for i in range(180)]+[108.2+i*.17 for i in range(120)],float)
    h=c+0.5;l=c-.5
    a,b=signal_independent(c,h,l,9,120,14,0)
    x=c.copy();x[-1]+=300.
    ax,bx=signal_independent(x,x+.5,x-.5,9,120,14,0)
    assert np.array_equal(a[:-1],ax[:-1])
    assert np.array_equal(b[:-1],bx[:-1])
    assert bool(a.any()) and not bool((a&b).any())


def test_adx20_vs_adx25_filter_uses_wilder_closed_bar(monkeypatch):
    import types,sys
    module=types.SimpleNamespace(adx=lambda h,l,c,n: np.array([19.,20.,24.9,25.,30.]))
    monkeypatch.setitem(sys.modules,"strategies",module)
    c=np.array([3.,2.,1.,2.,3.]);h=c+.5;l=c-.5
    a,b=signal_independent(c,h,l,2,3,14,20)
    d,e=signal_independent(c,h,l,2,3,14,25)
    assert len(a)==5 and len(d)==5
    assert np.all(~d | a)
    assert np.all(~e | b)


def test_initial_source_params_no_optimisation_on_2025_2026():
    assert all(x["fast"]==9 and x["slow"]==120 for x in VARIANTS.values())
    assert [x["adx_min"] for x in VARIANTS.values()]==[0,20,25]
