"""Day26 offline regression on independent test source and one-time holdout chain."""
from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest
from test_strategy_lab_oos_protocol import sample_history

from scripts.strategy_lab.day26_sealed_oos_real_history import audit


def test_complete_registered_history_oos_has_fixed_folds_and_single_reveal():
    proof=audit(sample_history())
    assert proof["status"]=="PASS"
    assert proof["native_m1_count"]==600
    assert proof["closed_m5_count"]==120
    assert len(proof["development"]["folds"])>=3
    assert proof["development"]["excluded_boundary_bars"]==4
    assert proof["development"]["sealed_holdout_size"]==20
    assert proof["one_time_reveal"]["holdout_count"]==20
    assert proof["prefreeze_access_denied"]
    assert proof["second_holdout_reveal_denied"]
    assert proof["trial_ledger"]["event_count"]==3
    assert proof["trial_ledger"]["completed_holdout_reveals"]==1
    assert not proof["broker_costs_or_alpha_qualified"]
    assert not proof["real_bid_ask_trade_fills_tested"]


def test_two_fresh_independent_journal_reproductions_match():
    first=audit(sample_history())
    next_run=audit(sample_history())
    assert first==next_run
    assert first["trial_ledger"]["chain_tip_sha256"] == (
        first["one_time_reveal"]["registered_one_time_reveal_sha256"]
    )


def test_genuine_source_reader_inconsistency_stops_oos_path():
    before=sample_history()
    bars=list(before.bars)
    bars[70]=replace(bars[70],available_at_utc=bars[70].available_at_utc+timedelta(minutes=1))
    with pytest.raises(ValueError,match="gapped"):
        audit(replace(before,bars=tuple(bars)))
