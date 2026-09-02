from __future__ import annotations

from datetime import UTC, datetime

from aidy.feature_engine import FEATURE_DEFINITION_VERSION
from aidy.historical_cases import CASE_INPUT_VERSION, compute_case_input_digest
from aidy.market_data_semantics import histdata_semantic_identity, twelve_data_semantic_identity
from aidy.regime_classifier import REGIME_DEFINITION_VERSION
from aidy.semantic_analogue_retrieval import (
    SEMANTIC_ANALOGUE_QUERY_VERSION,
    SEMANTIC_ANALOGUE_RETRIEVAL_VERSION,
    build_semantic_analogue_query,
    retrieve_semantic_analogues_v2,
)
from aidy.setup_detector import SETUP_DETECTOR_VERSION, SETUP_TAXONOMY_VERSION
from aidy.twelve_launch_policy import STEP2_OUTCOME, twelve_launch_policy_manifest


def _semantic_pit_input() -> dict:
    identity = twelve_data_semantic_identity()
    value = {
        "input_version": CASE_INPUT_VERSION,
        "symbol": "XAUUSD",
        "as_of_utc": datetime(2026, 9, 2, 7, 0, tzinfo=UTC).isoformat(),
        "provenance_class": "pit_observed",
        "future_derived": False,
        "analogue_match_allowed": True,
        "feature": {"feature_definition_version": FEATURE_DEFINITION_VERSION},
        "regime": {"regime_definition_version": REGIME_DEFINITION_VERSION},
        "setup": {
            "taxonomy_version": SETUP_TAXONOMY_VERSION,
            "detector_version": SETUP_DETECTOR_VERSION,
        },
        "data_quality": {"grade": "strong", "retrieval_eligible": True},
        "analogue_features": {
            "regime": {
                "trend_structure": "bullish_trend",
                "volatility_band": "normal",
                "session": "london",
                "event_timing": "clear_current_window",
            },
            "h1_atr_14_bps": "35",
            "m15_range_position_20": "0.5",
            "candidate_setup_ids": [],
        },
        "market_data_semantic_identity": identity,
        "market_data_semantic_identity_digest": identity["semantic_identity_digest"],
    }
    value["input_digest"] = compute_case_input_digest(value)
    return value


def test_twelve_query_blocks_histdata_candidate_before_legacy_retrieval() -> None:
    query = build_semantic_analogue_query(input_boundary=_semantic_pit_input())
    hist = histdata_semantic_identity()
    fake_legacy_case = {
        "case_id": "legacy-histdata-case",
        "input_boundary": {
            "market_data_semantic_identity": hist,
            "market_data_semantic_identity_digest": hist["semantic_identity_digest"],
        },
    }
    result = retrieve_semantic_analogues_v2(
        query=query,
        candidate_cases=[fake_legacy_case],
    )
    assert result["candidate_count_before_semantic_gate"] == 1
    assert result["semantic_compatible_candidate_count"] == 0
    assert result["semantic_exclusion_counts"] == {
        "market_data_semantic_identity_incompatible": 1
    }
    assert result["base_retrieval"]["candidate_count"] == 0
    assert result["accepted_equivalence_ledger_record_digests"] == []
    assert result["cross_source_comparison_without_ledger_proven_pass_allowed"] is False


def test_candidate_without_identity_is_blocked_before_legacy_retrieval() -> None:
    query = build_semantic_analogue_query(input_boundary=_semantic_pit_input())
    result = retrieve_semantic_analogues_v2(
        query=query,
        candidate_cases=[{"case_id": "unqualified", "input_boundary": {}}],
    )
    assert result["semantic_compatible_candidate_count"] == 0
    assert result["semantic_exclusion_counts"] == {
        "candidate_semantic_identity_missing_or_invalid": 1
    }
    assert result["base_retrieval"]["candidate_count"] == 0


def test_private_forward_launch_keeps_unqualified_cross_source_inheritance_blocked() -> None:
    manifest = twelve_launch_policy_manifest()
    assert SEMANTIC_ANALOGUE_QUERY_VERSION == "aidy_semantic_analogue_query_v1"
    assert SEMANTIC_ANALOGUE_RETRIEVAL_VERSION == "aidy_semantic_analogue_retrieval_v1"
    assert STEP2_OUTCOME == "insufficient_evidence"
    assert manifest["step2_outcome"] == "insufficient_evidence"
    assert manifest["cross_source_analogue_permission"] is False
    assert manifest["no_comparable_case_allowed"] is True
    assert manifest["volatility_band_masked_unknown"] is True
    assert manifest["public_publication_enabled"] is False
    assert manifest["live_money_execution_allowed"] is False
