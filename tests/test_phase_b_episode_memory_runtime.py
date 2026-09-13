from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from aidy.episode_memory_runtime import (
    _context_reference_price,
    _enriched_episode_payload,
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


def test_episode_memory_preserves_setup_regime_and_confidence_without_future_fields() -> None:
    record = _no_trade_record()
    record.update(
        {
            "evaluation_id": "aidy_eval_fixture",
            "decision_id": "aidy_dec_fixture",
            "ex_ante_digest": "a" * 64,
            "evaluated_at_utc": "2026-09-10T12:00:30+00:00",
            "context_hash": "b" * 64,
            "cycle_disposition": "no_trade",
            "data_quality_flags": {"state": "known_good"},
            "reproducibility_bundle": {
                "evidence_grade": "exploratory",
                "effective_n": 14,
                "strategy_version": "strategy-v1",
                "config_version": "config-v1",
                "model_id": "model-v1",
                "analogue_case_ids": ["case-a", "case-b"],
                "regime_state": {"trend_structure": "uptrend", "volatility_band": "normal"},
                "setup_state": {"candidate_setup_ids": ["trend_pullback_long"]},
                "selective_layer_state": {"state": "shadow_only"},
                "analogue_retrieval_version": "retrieval-v1",
                "analogue_retrieval_digest": "c" * 64,
            },
        }
    )
    record["decision"].update(
        {
            "confidence": 0.71,
            "setup_codes": ["trend_pullback_long"],
            "reason_codes": ["evidence_insufficient"],
            "decision_summary": "AIDY abstained while retaining a falsifiable bullish shadow.",
            "valid_until_utc": "2026-09-10T12:15:30+00:00",
            "entry_type": None,
        }
    )
    payload = _enriched_episode_payload(
        cycle={"cycle_id": "cycle-1", "source_state": "private_forward"},
        ex_ante=record,
        forward={"record_id": "fwd-1", "cohort_id": "cohort-1"},
    )
    assert payload["decision"]["confidence"] == 0.71
    assert payload["decision"]["setup_codes"] == ["trend_pullback_long"]
    assert payload["evidence"]["regime_state"]["trend_structure"] == "uptrend"
    assert payload["evidence"]["setup_state"]["candidate_setup_ids"] == ["trend_pullback_long"]
    assert payload["context_summary"]["market_mid"] == "4375.250000"
    assert payload["future_outcome_fields_present"] is False
    assert payload["hidden_reasoning_stored"] is False


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
