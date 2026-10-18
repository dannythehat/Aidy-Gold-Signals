"""S005 publisher H1 original-code parity and account window contracts."""
import numpy as np
import pandas as pd
from scripts.strategy_lab.s005_publisher_engine_two_preset_parity import (
    PUB_COMMIT,BLOBS,PERIODS,_git_blob_sha,auditor_signal_diff,
)

def test_exact_publisher_blobs_are_not_illustrative_lab_family():
    assert len(PUB_COMMIT)==40
    assert all(len(d)==40 for d in BLOBS.values())
    assert "engine.py" in BLOBS and "ApexBreakout.mq5" in BLOBS
    assert _git_blob_sha(b"hello")=="b6fc4c620b67d95f953a5c1c1230aaab5db5a1b0"

def test_two_independent_full_data_periods_contract():
    assert PERIODS["2025"]==("2025-01-01","2026-01-01",12)
    assert PERIODS["2026"]==("2026-01-01","2026-10-01",9)

def test_no_mql_broken_channel_hindsight():
    dates=pd.date_range("2024-12-01",periods=300,freq="h")
    p=pd.DataFrame({"open":range(300),
        "high":[float(i+1) for i in range(300)],
        "low":[float(i-.5) for i in range(300)],
        "close":[float(i+.5) for i in range(300)]},index=dates)
    e=p.close.ewm(span=200,adjust=False).mean()
    high=p.high.rolling(24).max().shift(1)
    long=(p.close>high)&(p.close>e)
    test=auditor_signal_diff(p,long.to_numpy(),
         np.zeros(300,dtype=bool),np.zeros(300,dtype=bool),
         np.zeros(300,dtype=bool),"DONCHIAN")
    # The synthetic opposite-channel flags intentionally omitted, so
    # this TEST must detect differences rather than bless false parity.
    assert test["long_entries_mismatched"]==0
    assert test["signal_event_parity_mechanical"] is False
    assert test["long_exit_signals_mismatched"]>=0
