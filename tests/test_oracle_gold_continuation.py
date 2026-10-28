"""Prove bounded family, source defects and immutable continuation evidence."""
import hashlib
import json
import os
from pathlib import Path

import pandas as pd
import pytest

from scripts.oracle_gold.batch01 import pinned_module
from scripts.oracle_gold.batch02 import entries, originals, outcome_summary
from scripts.oracle_gold.build_register import carry_research_records
from scripts.oracle_gold.continuation_audit import compare_s016
from scripts.oracle_gold.history import digest
from scripts.oracle_gold.record_batch02 import decode_ledger

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/"reports/gold_oracle"


def external(variable):
    value = os.environ.get(variable)
    if not value:
        pytest.skip(variable+" pinned original checkout required")
    return Path(value)


def test_s016_two_classes_are_exact_parameter_variants_not_extra_original_ids():
    root = external("ORACLE_S016_ROOT")
    evidence = compare_s016(root)
    assert evidence["classification"] == "PROVEN_WITHIN_ID_PARAMETER_VARIANTS"
    assert evidence["additional_independent_original_ids"] == 0
    assert evidence["full_program_identity_claimed"] is False


def test_s022_early_day_fallback_rewrites_earlier_entries_when_open_arrives():
    Candle, Params, run, _ = originals(external("ORACLE_SWEEP_ROOT"))
    times = pd.date_range("2024-01-02", periods=19, freq="h", tz="UTC")
    candles = [Candle(i, 100., 103. if i == 3 else 101., 99., 102. if i == 3 else 100.,
                      timestamp=t.to_pydatetime()) for i, t in enumerate(times)]
    full = run("orb", candles, Params.for_timeframe("H1"))
    morning = run("orb", candles[:10], Params.for_timeframe("H1"))
    assert any(s.entry_index == 3 for s in morning)
    assert entries(full, 10) != entries(morning, 10)
    assert all(s.entry_index >= 15 for s in full)


def test_s014_python_same_bar_sweep_and_gap_are_mutually_exclusive():
    root = external("ORACLE_S014_ROOT")
    path = root/"backtest_ict.py"
    from scripts.oracle_gold.batch01 import blob
    # The committed source receipt pins the entire original file before import.
    audit = json.loads((OUT/"continuation_source_audit.json").read_text())
    pin = next(x["git_blob"] for x in audit["cards"]["S014"]["source_refs"] if x["path"] == path.name)
    assert blob(path.read_bytes()) == pin
    m = pinned_module("oracle_original_014", path, pin)
    close = pd.Series([100.+(i % 7) for i in range(100)]).to_numpy()
    frame = pd.DataFrame({"open": close, "close": close, "high": close+2, "low": close-2},
                         index=pd.date_range("2024-01-01", periods=100, freq="h"))
    assert frame.notna().all().all()
    assert ((frame.low <= frame.close) & (frame.close <= frame.high)).all()
    assert m.backtest_ict(frame, enforce_session=False) == []
    # For i>=20, low[i]<min(prior20 lows)<=low[i-2]<=high[i-2],
    # so low[i]>high[i-2] cannot also hold. Short has the inverse contradiction.


def test_rebuilding_base_register_preserves_every_attached_experiment_and_card():
    old = {"rows": [{"id": "S001", "batch01_results": [{"net": -1}],
                     "batch02_results": [], "continuation_audit": {"status": "BLOCKED"}}]}
    rebuilt = carry_research_records([{"id": "S001", "family": "original"}], old)
    assert rebuilt[0]["batch01_results"] == [{"net": -1}]
    assert rebuilt[0]["continuation_audit"] == {"status": "BLOCKED"}
    with pytest.raises(ValueError, match="ID set"):
        carry_research_records([{"id": "S002"}], old)


def test_all216_scenarios_97_losses_and_9245_setups_reconcile_from_frozen_ledgers():
    packet = json.loads((OUT/"batch02_results_register.json").read_text())
    sha = packet.pop("sha256")
    assert digest(packet) == sha
    assert len(packet["experiments"]) == 216
    assert packet["negative_R_scenario_results_retained"] == 97
    assert packet["setup_ledger_rows"] == 9245 and packet["USD_accounts_simulated"] == 0
    assert packet["execution_qualified_ids"] == []
    ledgers = {}
    for case in packet["experiments"]:
        rows = ledgers.setdefault(case["ledger"], decode_ledger(ROOT/case["ledger"]))
        actual = outcome_summary(rows, case["illustrative_cost_per_oz_round_trip"],
                                 case["scenario"].startswith("source_EMA_filter_on/"))
        for key, value in actual.items():
            assert case[key] == value
        assert case["execution_qualified"] is False
        assert case["account_net_usd"] is None and case["account_drawdown"] is None
    assert len(ledgers) == 36 and sum(len(v) for v in ledgers.values()) == 9245
    for path, expected in packet["ledger_file_sha256"].items():
        assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest() == expected
    assert {(r["strategy_id"], r["year"]) for r in packet["model_years"] if
            not r["prefix_stable_at_tested_cuts"]} == {("S024", 2023), ("S024", 2024),
                                                     ("S024", 2025), ("S022", 2024)}


def test_continuation_cards_preserve83_ids_and_do_not_certify_partial_reviews():
    audit = json.loads((OUT/"continuation_source_audit.json").read_text())
    sha = audit.pop("sha256")
    assert digest(audit) == sha
    assert len(audit["cards"]) == 15
    assert all(not c["full_mechanics_audit"] and not c["execution_qualified"] for c in audit["cards"].values())
    reg = json.loads((OUT/"83_source_and_duplicate_audit.json").read_text())
    assert len(reg["rows"]) == 83
    assert sum(bool(r.get("continuation_audit")) for r in reg["rows"]) == 15
    assert sum(len(r.get("batch02_results", [])) for r in reg["rows"]) == 216
    from scripts.oracle_gold.batch_queue import assign
    queue = json.loads((OUT/"83_batch_assignment_register.json").read_text())
    assert assign(reg) == queue
    assert queue["original_ids"] == 83 and queue["unverified_source_waiting_ids"] == 50
