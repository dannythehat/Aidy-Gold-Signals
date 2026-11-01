"""Observed original XAUUSD quote evidence, not an invented mid-price."""
import pandas as pd
import pytest

from gold_hunter.bible_engine import Parameters, research_backtest, validate_h1
from test_bible_engine import historical_fixture


def test_observed_quote_required_and_preserved():
    data = historical_fixture(700)
    cfg = Parameters(quote_model="observed_open_conservative_h1")
    with pytest.raises(ValueError, match="requires original"):
        research_backtest(data, cfg=cfg)
    data["observed_open_spread"] = .8
    data["observed_open_ask"] = data["open"] + .8
    data["observed_max_spread"] = 2.3
    cleaned = validate_h1(data)
    assert "observed_open_ask" in cleaned
    assert cleaned.iloc[-1]["observed_open_ask"] == pytest.approx(
        data.iloc[-1]["open"] + .8)
    result = research_backtest(data, cfg=cfg)
    assert result["data_basis"].startswith("H1_OBSERVED_ORIGINAL")
    corrupted = data.copy()
    corrupted.loc[15, "observed_open_ask"] -= 2
    with pytest.raises(ValueError, match="geometry invalid"):
        validate_h1(corrupted)


def test_observed_quote_tape_is_attested_and_not_forward_looking():
    from gold_hunter.bible_engine import build_candidate_tape, candidates_at, _higher_frames
    data = historical_fixture(800)
    data["observed_open_spread"] = .8
    data["observed_open_ask"] = data["open"] + .8
    data["observed_max_spread"] = 2.3
    cfg = Parameters(quote_model="observed_open_conservative_h1")
    tape = build_candidate_tape(data, cfg)
    original = research_backtest(data, cfg=cfg, candidate_tape=tape)
    direct = research_backtest(data, cfg=cfg)
    assert original == direct
    future = data.copy()
    future.loc[799, "observed_open_ask"] += 4
    future.loc[799, "observed_open_spread"] += 4
    future.loc[799, "observed_max_spread"] += 4
    with pytest.raises(ValueError, match="mismatch"):
        research_backtest(future, cfg=cfg, candidate_tape=tape)
    clean1, clean2 = validate_h1(data), validate_h1(future)
    h1, d1, w1 = _higher_frames(clean1)
    h2, d2, w2 = _higher_frames(clean2)
    assert candidates_at(clean1, 750, h1, d1, w1, cfg) == (
        candidates_at(clean2, 750, h2, d2, w2, cfg))
