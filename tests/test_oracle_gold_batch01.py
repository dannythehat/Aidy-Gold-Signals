"""Integrity, original signal parity and adversarial publisher defect proofs."""
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from aidy.strategy_lab_s010_backtest import derive_signals
from scripts.oracle_gold.batch01 import CASES, blob, pinned_module, publisher_modules
from scripts.oracle_gold.history import load_snapshot, write_snapshot


def bars(n=600):
    rng = np.random.default_rng(83)
    close = 2000 + np.cumsum(rng.normal(0, 2, n))
    return pd.DataFrame({"open_time_utc": pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC").astype(str),
        "open": close-.2, "high": close+3, "low": close-3, "close": close, "m1_count": 60})


def test_immutable_history_rejects_rows_and_receipt_tamper(tmp_path):
    rows = bars(400).to_dict("records")
    write_snapshot(tmp_path, rows, [{"test_only": True}], "SYNTHETIC_TEST_NOT_HISTORY")
    assert load_snapshot(tmp_path)[0] == rows
    with pytest.raises(ValueError, match="already exists"):
        write_snapshot(tmp_path, rows, [], "fixture")
    file = tmp_path / "rows.json"
    file.write_text(file.read_text().replace('2000', '3000', 1) + " ")
    # Change guaranteed field, not whitespace alone.
    bad = json.loads(file.read_text())
    bad[0]["m1_count"] = 59
    file.write_text(json.dumps(bad))
    with pytest.raises(ValueError, match="tampered"):
        load_snapshot(tmp_path)


def test_snapshot_rejects_duplicate_and_partial_hours(tmp_path):
    rows = bars(10).to_dict("records")
    with pytest.raises(ValueError, match="unordered"):
        write_snapshot(tmp_path, rows+[rows[-1]], [], "fixture")
    rows[0]["m1_count"] = 59
    with pytest.raises(ValueError, match="Incomplete"):
        write_snapshot(tmp_path, rows, [], "fixture")


def test_pinned_loader_rejects_modified_executable_before_import(tmp_path):
    p = tmp_path / "unsafe.py"
    p.write_text("raise RuntimeError('must not execute')")
    with pytest.raises(ValueError, match="blob mismatch"):
        pinned_module("bad", p, "0"*40)
    assert blob(b"test content") == "08cf6101416f0ce0dda3c80e627f333854c4085c"


@pytest.fixture
def originals():
    apex, ten = os.environ.get("ORACLE_APEX_ROOT"), os.environ.get("ORACLE_S010_ROOT")
    if not apex or not ten:
        pytest.skip("Pinned publisher integration requires explicit source roots")
    return publisher_modules(Path(apex), Path(ten))


def test_original_s010_full_signal_trace_and_future_perturbation(originals):
    _, _, original = originals
    x = bars()
    expected = original.MACrossoverStrategy(12, 34, 14).calculate_indicators(x.copy(), verbose=False)
    actual = derive_signals(x)
    np.testing.assert_array_equal(expected.signal, actual.loc[expected.index, "signal"])
    changed = x.copy()
    changed.loc[500:, ["open", "high", "low", "close"]] *= 1.5
    np.testing.assert_array_equal(actual.signal[:500], derive_signals(changed).signal[:500])


def test_apex_distinct_original_signals_and_prefix_parity(originals):
    engine, strategy, _ = originals
    x = bars(900)
    o, h, l, c = [x[k].to_numpy() for k in ("open", "high", "low", "close")]
    hours = np.arange(len(c)) % 24
    at = engine.atr(h, l, c, 14)
    traces = []
    for ident, (method, params, _) in CASES.items():
        kw = dict(params)
        if ident == "S009":
            kw["atr_arr"] = at
        a = strategy.STRATEGIES[method](o, h, l, c, hours, **kw)
        shortkw = {k: (v[:450] if isinstance(v, np.ndarray) else v) for k, v in kw.items()}
        b = strategy.STRATEGIES[method](o[:450], h[:450], l[:450], c[:450], hours[:450], **shortkw)
        for aa, bb in zip(a, b):
            np.testing.assert_array_equal(aa[:450], bb)
        traces.append(tuple(v.tobytes() for v in a))
    assert len(set(traces)) == 5  # synthetic distinction, NOT OOS independence


def test_negative_publisher_entry_open_sizing_reads_future_close(originals):
    """Prove defect, preserve original. A valid causal engine would keep units equal."""
    engine, _, _ = originals
    n = 40
    o, c = np.full(n, 2000.), np.full(n, 2000.)
    h, l = np.full(n, 2010.), np.full(n, 1990.)
    at = np.ones(n)
    ls, ss, lx, sx = (np.zeros(n, bool) for _ in range(4))
    ls[19] = True
    kwargs = dict(spec=engine.SymbolSpec("XAUUSD", .45, max_leverage=1.),
                  p=engine.EngineParams(sl_atr=20), start_i=19, end_i=n)
    a = engine.simulate(o, h, l, c, np.arange(n)*3600, at, ls, ss, lx, sx, **kwargs)
    changed = c.copy()
    changed[20] = 2005.  # still inside identical OHLC; unknown at the entry open
    b = engine.simulate(o, h, l, changed, np.arange(n)*3600, at, ls, ss, lx, sx, **kwargs)
    assert a.trades[0].entry_i == b.trades[0].entry_i == 20
    assert a.trades[0].entry_px == b.trades[0].entry_px == 2000.
    assert a.trades[0].units != b.trades[0].units


def test_bigquery_provenance_nulls_fail_closed():
    from scripts.strategy_lab import s010_run_12month_history as reader
    import inspect
    sql = inspect.getsource(reader.retrieve_month)
    assert "NOT COALESCE" in sql
    assert "REGEXP_CONTAINS(source_file_sha256" in sql
    assert "source_file IS NOT NULL" in sql
