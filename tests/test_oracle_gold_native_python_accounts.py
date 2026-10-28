"""Original strategy import/lifecycle, observed quote clock and cost reconciliation."""
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from scripts.oracle_gold.native_python_accounts import ROOT, daily, s016, statistics, verify


def data():
    index = pd.date_range("2099-01-01",periods=120,freq="D",tz="UTC")+pd.Timedelta(minutes=7)
    close = np.r_[np.linspace(100,120,50),np.linspace(120,165,40),np.linspace(165,90,30)]
    return pd.DataFrame({"open":close-.1,"high":close+1,"low":close-1,"close":close},index=index)


def source_root():
    root=os.environ.get("ORACLE_PHASE04_S016_ROOT")
    if not root:
        pytest.skip("Exact pinned original source required")
    return Path(root)


def test_original_dependencies_compile_and_source_hash_tamper_fails(tmp_path):
    root=source_root()
    evidence=verify("S016",root)
    assert len(evidence["original_python_files_compiled"]) == 4
    # Do not alter the source clone to prove fail-closed behaviour.
    pin=json.loads((ROOT/"research/gold_oracle/phase04/python_source_pins.json").read_text())["S016"]
    for name in pin["files"]:
        p=tmp_path/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes((root/name).read_bytes())
    file=tmp_path/next(iter(pin["files"]))
    file.write_bytes(file.read_bytes()+b"\n")
    with pytest.raises(ValueError,match="Original source/dependency changed"):
        verify("S016",tmp_path)


def test_original_backtrader_class_next_open_integer_quantity_and_costs_reconcile():
    root=source_root();frame=data()
    trades,equity,details=s016(frame,root,"entry20_risk1",10_000.,"common_base")
    assert trades and details["observer_final_equity_parity"]
    assert all(float(f["quantity_delta"]).is_integer() for f in details["order_fills"])
    assert all(pd.Timestamp(f["utc"]) in frame.index for f in details["order_fills"])
    assert all(pd.Timestamp(f["utc"]).minute == 7 for f in details["order_fills"])
    assert details["params"]["entry_period"]==20 and details["params"]["risk_percent"]==1.
    assert equity.iloc[-1] == pytest.approx(details["native_final_equity"])
    for fill in details["order_fills"]:
        assert fill["commission"] == pytest.approx(abs(fill["quantity_delta"])*.47/2)
    # Source defines close-based exits, not a protective ATR stop order.
    assert details["native_cash"]+details["native_open_units"]*frame.close.iloc[-1] == pytest.approx(equity.iloc[-1])


def test_original_variant_family_does_not_silently_adopt_header120_30_parameters():
    root=source_root();frame=data()
    _,_,details=s016(frame,root,"entry95_risk2",10_000.,"source_declared")
    assert details["params"]["entry_period"]==95
    assert details["params"]["exit_period"]==20
    assert details["params"]["risk_percent"]==2.
    assert details["same_family_as_other_S016_variant"] is True


def test_daily_derivative_uses_actual_first_observation_and_no_synthetic_noise_or_volume():
    frame=data();out=daily(frame)
    pd.testing.assert_frame_equal(out,frame,check_freq=False)
    assert "volume" not in out.columns


def test_marked_statistics_keep_open_equity_separate_from_closed_and_worst_month():
    index=pd.to_datetime(["2023-01-01","2023-12-31","2024-12-31","2025-12-31"],utc=True)
    eq=pd.Series([100.,90.,120.,110.],index=index)
    trades=[{"entry_utc":"2023-01-01","exit_utc":"2023-12-31","side":"LONG","net_usd":-10.}]
    r=statistics("S016","test","STANDARDISED_CAPITAL_COMPARISON",100.,"common_stress",trades,eq,{})
    assert r["net_marked_usd"]==10. and r["net_closed_usd"]==-10.
    assert r["years"][0]["net_usd"]==-10.
    assert r["minute_close_marked_drawdown_pct"]==pytest.approx(-10.)
    assert r["largest_winner_usd"]==0
