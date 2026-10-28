"""Source-defined unit sizing, causal rules and native Pine lifecycle cases."""
import ast
import json
import os
import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from scripts.oracle_gold.pine_fixed_accounts import PINS, PROFILES, evaluate, features, rma, source


def frame(rows):
    x = pd.DataFrame(rows, columns=["open", "high", "low", "close", "atr", "buy", "sell"])
    x.index = pd.date_range("2099-01-01", periods=len(x), freq="h", tz="UTC")
    return x


def test_native_entry_bar_is_unprotected_until_next_source_close_and_gap_is_not_stop_price():
    x = frame([(100, 101, 99, 100, 2, True, False),
               (110, 120, 105, 112, 2, False, False),
               (106, 108, 105, 107, 2, False, False)])
    r = evaluate(x, "S061", "native")
    t = r["trades"][0]
    assert t["entry_reference"] == 110 and t["exit_reference"] == 106
    assert t["exit_reason"] == "STOP_GAP"
    assert t["net_excluding_unverified_funding_usd"] == pytest.approx(-4.-.011-.0106)
    assert r["closed_trades"] == 1 and r["open_positions_at_end"] == 0


def test_reversal_bracket_retains_old_average_as_original_source_does():
    x = frame([(100, 101, 99, 100, 2, True, False),
               (100, 102, 99, 100, 2, False, True),
               (101, 104, 99, 101, 2, False, False)])
    r = evaluate(x, "S061", "native")
    assert [t["exit_reason"] for t in r["trades"]] == ["SOURCE_REVERSAL", "STOP"]
    assert r["trades"][1]["entry_reference"] == 101
    assert r["trades"][1]["exit_reference"] == 103  # old avg100 +1.5ATR2


def test_source_s060_reprices_both_exits_and_does_not_silently_tighten_stop():
    x = frame([(100, 101, 99, 100, 2, True, False),
               (100, 102, 100, 101, 2, False, False),
               (101, 103, 100, 100, 4, False, False),
               (100, 103, 97, 102, 4, False, False)])
    r = evaluate(x, "S060", "native")
    assert r["open_positions_at_end"] == 1 and r["closed_trades"] == 0
    assert r["initial_capital"] == 1_000_000
    assert r["net_marked_excluding_unverified_funding_usd"] == 2.


def test_process_orders_on_close_and_no_invented_end_liquidation():
    x = frame([(100, 103, 98, 102, 2, True, False)])
    r = evaluate(x, "S058", "native")
    assert r["closed_trades"] == 0 and r["open_positions_at_end"] == 1
    assert r["open_entry_fee_usd"] == pytest.approx(.0102)
    assert r["net_marked_excluding_unverified_funding_usd"] == pytest.approx(-.0102)


def test_native_rma_uses_sma_seed_not_ewm_first_observation_seed():
    result = rma(pd.Series([1., 2., 6., 8.]), 3)
    assert result.isna().tolist() == [True, True, False, False]
    assert result.iloc[2] == 3. and result.iloc[3] == pytest.approx(3.+5./3)


def test_original_unit_quantity_and_capital_are_verified_from_compiled_source_metadata():
    pins = json.loads(PINS.read_text())
    for ident, (_tf, capital, commission, margin, on_close) in PROFILES.items():
        defaults = pins[ident]["compiled_source_defaults"]
        assert defaults["Default entry/order Qty Type"] == "fixed"
        assert defaults["Default entry/order Qty Value"] == 1
        assert defaults["Initial Capital"] == capital
        assert defaults["Commission Value"]/100 == commission
        assert defaults["Margin Long"] == margin == defaults["Margin Short"]
        assert defaults["Process orders on bar Close"] == on_close


def test_source_s061_predicate_matches_original_expressions_and_all_prefixes():
    root = os.environ.get("ORACLE_PHASE03_PINE_ROOT")
    if not root:
        pytest.skip("Pinned public source required")
    text = source("S061", Path(root))
    exprs = {name: re.search(r"^"+name+r"\s*=\s*(.+)$", text, re.MULTILINE)[1] for name in ("buySignal", "sellSignal")}
    for expr in exprs.values():
        assert all(isinstance(n, (ast.Expression, ast.BoolOp, ast.And, ast.Compare, ast.Lt, ast.Gt, ast.Name,
                                  ast.Load, ast.Subscript, ast.Constant)) for n in ast.walk(ast.parse(expr, mode="eval")))
    rng = np.random.default_rng(374)
    c = 2000+np.cumsum(rng.normal(0, .1, 4000))
    rows = pd.DataFrame({"open_time_utc": pd.date_range("2099-01-01", periods=len(c), freq="min", tz="UTC").astype(str),
                         "open": c, "high": c+.2, "low": c-.2, "close": c}).to_dict("records")
    x = features(rows, 60, "S061")
    lows = x.low.rolling(10, min_periods=1).min()
    highs = x.high.rolling(10, min_periods=1).max()
    for i in range(1, len(x)):
        b = x.iloc[i]
        env = {"low": b.low, "high": b.high, "close": b.close, "ema200": b.ema200,
               "ll": [lows.iloc[i], lows.iloc[i-1]], "hh": [highs.iloc[i], highs.iloc[i-1]]}
        assert bool(eval(compile(exprs["buySignal"], "PINNED_SOURCE_PREDICATE", "eval"), {"__builtins__": {}}, env)) == bool(b.buy)
        assert bool(eval(compile(exprs["sellSignal"], "PINNED_SOURCE_PREDICATE", "eval"), {"__builtins__": {}}, env)) == bool(b.sell)
    short = features(rows[:2000], 60, "S061")
    pd.testing.assert_frame_equal(short[["buy", "sell"]], x.loc[short.index, ["buy", "sell"]])
