from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from aidy.episode_memory_runtime import (
    _context_reference_price,
    _shadow_resolution_record,
)

ROOT = Path(__file__).resolve().parents[1]


def _no_trade_record() -> dict[str, object]:
    return {
        "context_snapshot": {
            "as_of_utc": "2026-09-10T12:00:30+00:00",
            "symbol": "XAUUSD",
            "gold": {
                "quote_context": {
                    "state": "known",
                    "quote_state": "known",
                    "mid": "4375.250000",
                }
            },
        },
        "decision": {
            "action": "no_trade",
            "market_reference_price": None,
            "shadow_direction": "long",
            "shadow_horizon_minutes": 30,
        },
    }


def test_no_trade_shadow_uses_exact_ex_ante_context_mid_without_mutation() -> None:
    record = _no_trade_record()
    original = deepcopy(record)
    assert _context_reference_price(record) == "4375.250000"
    resolver = _shadow_resolution_record(record)
    assert resolver["decision"]["market_reference_price"] == "4375.250000"
    assert record == original
    assert record["decision"]["market_reference_price"] is None


def test_missing_context_mid_fails_closed_instead_of_using_future_bar() -> None:
    record = _no_trade_record()
    record["context_snapshot"]["gold"]["quote_context"].pop("mid")
    resolver = _shadow_resolution_record(record)
    assert _context_reference_price(record) is None
    assert resolver["decision"]["market_reference_price"] is None


def test_runtime_filters_only_matured_bounded_horizons_and_worker_uses_bound_env() -> None:
    runtime = (ROOT / "src/aidy/episode_memory_runtime.py").read_text(encoding="utf-8")
    entry = (ROOT / "src/provider_entry.py").read_text(encoding="utf-8")
    assert "BETWEEN 1 AND ?" in runtime
    assert "julianday(f.evaluated_at_utc)" in runtime
    assert "MAX_AUTO_RESOLUTION_HORIZON_MINUTES" in runtime
    assert "no_trade_reference_is_ex_ante_context_mid" in runtime
    assert "sync_aidy_episode_memory_runtime" in entry
    assert "_sync_episode_memory_best_effort(self.env)" in entry
    assert "_record_health_best_effort(self.env" in entry
    assert 'path == "/provider/decision-memory"' in entry
