from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from aidy.analogue_retrieval_v2 import similarity_manifest_v2
from aidy.day53_step2_preregistration import (
    COMPARISON_POPULATION,
    COVERAGE_REQUIREMENTS,
    PARAMETER_SPACE_DIGEST,
    PASS_CRITERIA,
    PREREGISTERED_PARAMETER_SPACE,
    PRIOR_KNOWLEDGE,
    STEP2_AUTHORIZATION_SCOPE,
    STEP2_QUALIFICATION_ID,
    build_step2_equivalence_contract_payload,
    build_step2_research_family_payload,
    step2_contract_digest,
    validate_step2_result_payload,
)
from aidy.market_data_semantics import (
    EQUIVALENCE_CONTRACT_RECORD_TYPE,
    QUALIFICATION_RESULT_RECORD_TYPE,
    accepted_market_data_equivalences,
    histdata_semantic_identity,
    twelve_data_semantic_identity,
)
from aidy.regime_classifier import VOLATILITY_HIGH_GTE_BPS, VOLATILITY_LOW_LT_BPS
from aidy.research_trials import (
    build_record,
    digest,
    governance_genesis_payload,
    qualification_result_payload,
)

SHA40 = "a" * 40


def test_preregistered_parameter_space_is_singleton_and_matches_live_constants() -> None:
    assert PREREGISTERED_PARAMETER_SPACE["candidate_configurations"] == 1
    assert PREREGISTERED_PARAMETER_SPACE["search_performed"] is False
    assert PREREGISTERED_PARAMETER_SPACE["volatility_low_lt_bps"] == "20"
    assert PREREGISTERED_PARAMETER_SPACE["volatility_high_gte_bps"] == "50"
    assert PREREGISTERED_PARAMETER_SPACE["h1_atr_similarity_scale_bps"] == "40"
    assert str(VOLATILITY_LOW_LT_BPS) == "20"
    assert str(VOLATILITY_HIGH_GTE_BPS) == "50"

    manifest = similarity_manifest_v2()
    h1_atr = next(item for item in manifest["components"] if item["name"] == "h1_atr")
    assert h1_atr["numeric_scale"] == "40"
    assert "m15_realized_vol_20_bps" in manifest[
        "deliberately_excluded_redundant_soft_votes"
    ]
    assert PREREGISTERED_PARAMETER_SPACE["m15_realized_vol_similarity_scale_bps"] == {
        "value": "30",
        "status": "excluded_legacy_v1_not_active_in_authoritative_v2",
    }


def test_preregistration_discloses_prior_reconciliation_and_no_blind_claim() -> None:
    assert PRIOR_KNOWLEDGE["criteria_are_informed_not_blind"] is True
    assert PRIOR_KNOWLEDGE["median_absolute_difference_bps_approx_range"] == [10, 14]
    assert PRIOR_KNOWLEDGE["p95_absolute_difference_bps_approx_range"] == [38, 57]
    assert PRIOR_KNOWLEDGE["tail_max_absolute_difference_bps_approx"] == 97
    assert PRIOR_KNOWLEDGE[
        "earlier_reconciliation_is_prior_evidence_not_qualification_sample"
    ] is True


def test_population_and_minimum_coverage_are_frozen_before_results() -> None:
    assert COMPARISON_POPULATION["historical_bucket_end_start_utc_inclusive"] == (
        "2026-01-01T00:00:00+00:00"
    )
    assert COMPARISON_POPULATION["historical_bucket_end_cutoff_utc_inclusive"] == (
        "2026-08-31T23:00:00+00:00"
    )
    assert "modulo 4 equals 0" in COMPARISON_POPULATION["qualification_selector"]
    assert COMPARISON_POPULATION["qualification_harness_decision_input_allowed"] is False
    assert COVERAGE_REQUIREMENTS["minimum_paired_h1_qualification_observations"] == 600
    assert COVERAGE_REQUIREMENTS["minimum_retrieval_query_count"] == 250
    assert COVERAGE_REQUIREMENTS["minimum_queries_with_both_retrievals_non_empty"] == 150
    assert COVERAGE_REQUIREMENTS["minimum_threshold_near_observations"] == {
        "20_bps_either_source_within_plus_minus_5_bps": 60,
        "50_bps_either_source_within_plus_minus_5_bps": 60,
    }


def test_pass_boundaries_are_exact_and_non_discretionary() -> None:
    assert PASS_CRITERIA["volatility_band_three_class_agreement_rate_gte"] == "0.975"
    assert PASS_CRITERIA["volatility_band_agreement_wilson_95_lower_gte"] == "0.96"
    assert PASS_CRITERIA["threshold_near_each_band_disagreement_rate_lte"] == "0.125"
    assert PASS_CRITERIA[
        "threshold_near_each_band_disagreement_wilson_95_upper_lte"
    ] == "0.20"
    assert PASS_CRITERIA["v2_volatility_hard_gate_agreement_rate_gte"] == "0.975"
    assert PASS_CRITERIA["retrieval_empty_nonempty_state_agreement_rate_gte"] == "0.95"
    assert PASS_CRITERIA["selected_episode_jaccard_median_gte"] == "0.80"
    assert PASS_CRITERIA["selected_episode_jaccard_p10_gte"] == "0.60"
    assert PASS_CRITERIA["top_ranked_selected_episode_agreement_rate_gte"] == "0.90"
    assert PASS_CRITERIA["selected_episode_count_abs_diff_le_1_rate_gte"] == "0.95"
    assert PASS_CRITERIA["evidence_grade_agreement_rate_gte"] == "0.95"
    assert PASS_CRITERIA["pass_requires_every_mandatory_criterion"] is True
    assert PASS_CRITERIA["discretionary_override_allowed"] is False


def test_contract_binds_exact_source_pair_and_partial_authorization_scope() -> None:
    contract = build_step2_equivalence_contract_payload()
    family = build_step2_research_family_payload()
    hist = histdata_semantic_identity()
    twelve = twelve_data_semantic_identity()

    assert family["parameter_space_digest"] == PARAMETER_SPACE_DIGEST
    assert family["selection_origin"] == "preregistered_explicit"
    assert family["registered_before_first_result"] is True
    assert contract["qualification_id"] == STEP2_QUALIFICATION_ID
    assert contract["source_identity_a_digest"] == hist["semantic_identity_digest"]
    assert contract["source_identity_b_digest"] == twelve["semantic_identity_digest"]
    assert contract["authorization_scope"] == STEP2_AUTHORIZATION_SCOPE
    assert contract["cross_source_retrieval_permission_on_pass"] is False
    assert contract["full_retrieval_permission_requires_later_qualification"] is True
    assert contract["m15_30bps_v1_scale_qualified_by_this_contract"] is False
    assert step2_contract_digest() == digest(contract)


def test_step2_pass_still_cannot_unlock_full_cross_source_retrieval() -> None:
    start = datetime(2026, 9, 2, 8, 30, tzinfo=UTC)
    genesis = build_record(
        sequence=0,
        previous_digest=None,
        record_type="governance_genesis",
        recorded_at=start,
        code_head_sha=SHA40,
        initiated_by="human",
        payload=governance_genesis_payload(),
    )
    contract = build_step2_equivalence_contract_payload()
    contract_record = build_record(
        sequence=1,
        previous_digest=genesis["record_digest"],
        record_type=EQUIVALENCE_CONTRACT_RECORD_TYPE,
        recorded_at=start + timedelta(minutes=1),
        code_head_sha=SHA40,
        initiated_by="human",
        payload=contract,
    )
    result = qualification_result_payload(
        qualification_id=STEP2_QUALIFICATION_ID,
        contract_digest=step2_contract_digest(),
        outcome="pass",
        evidence_digest="b" * 64,
    )
    validate_step2_result_payload(result)
    result_record = build_record(
        sequence=2,
        previous_digest=contract_record["record_digest"],
        record_type=QUALIFICATION_RESULT_RECORD_TYPE,
        recorded_at=start + timedelta(minutes=2),
        code_head_sha=SHA40,
        initiated_by="registered_search_engine",
        payload=result,
    )
    assert accepted_market_data_equivalences([genesis, contract_record, result_record]) == {}


def test_fail_and_insufficient_results_cannot_claim_inheritance() -> None:
    for outcome in ("fail", "insufficient_evidence"):
        payload = qualification_result_payload(
            qualification_id=STEP2_QUALIFICATION_ID,
            contract_digest=step2_contract_digest(),
            outcome=outcome,
            evidence_digest="c" * 64,
        )
        assert payload["inheritance_allowed"] is False
        validate_step2_result_payload(payload)


def test_step2_result_cannot_smuggle_full_retrieval_permission() -> None:
    payload = qualification_result_payload(
        qualification_id=STEP2_QUALIFICATION_ID,
        contract_digest=step2_contract_digest(),
        outcome="pass",
        evidence_digest="d" * 64,
    )
    payload["cross_source_retrieval_permission"] = True
    with pytest.raises(ValueError, match="cannot grant full cross-source retrieval permission"):
        validate_step2_result_payload(payload)
