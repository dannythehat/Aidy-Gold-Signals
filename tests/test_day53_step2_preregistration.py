from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from aidy.analogue_retrieval_v2 import similarity_manifest_v2
from aidy.day53_step2_preregistration import (
    COMPARISON_POPULATION,
    CONJUNCTIVE_DECISION_RULE,
    COVERAGE_REQUIREMENTS,
    PARAMETER_SPACE_DIGEST,
    PASS_CRITERIA,
    PREREGISTERED_PARAMETER_SPACE,
    PREREGISTRATION_REVISION,
    PRIOR_KNOWLEDGE,
    STEP2_AUTHORIZATION_SCOPE,
    STEP2_QUALIFICATION_ID,
    THRESHOLD_REGION_DEFINITION,
    build_step2_equivalence_contract_payload,
    build_step2_research_family_payload,
    step2_contract_digest,
    validate_step2_result_payload,
)
from aidy.day53_step2_qualification_guard import (
    assert_exact_h1_pair,
    assert_repository_preregistration_manifest,
    assert_step2_scoring_prerequisites,
    in_frozen_threshold_region,
)
from aidy.historical_backfill import _source_bucket_start
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
from aidy.twelve_data_market import latest_completed_bucket

SHA40 = "a" * 40
MANIFEST_PATH = Path("evidence/research_ledger/day53-step2-equivalence-preregistration.json")


def _manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _valid_preregistration_chain() -> list[dict]:
    start = datetime(2026, 9, 2, 9, 0, tzinfo=UTC)
    genesis = build_record(
        sequence=0,
        previous_digest=None,
        record_type="governance_genesis",
        recorded_at=start,
        code_head_sha=SHA40,
        initiated_by="human",
        payload=governance_genesis_payload(),
    )
    family = build_record(
        sequence=1,
        previous_digest=genesis["record_digest"],
        record_type="research_family_registered",
        recorded_at=start + timedelta(minutes=1),
        code_head_sha=SHA40,
        initiated_by="human",
        payload=build_step2_research_family_payload(),
    )
    contract = build_record(
        sequence=2,
        previous_digest=family["record_digest"],
        record_type=EQUIVALENCE_CONTRACT_RECORD_TYPE,
        recorded_at=start + timedelta(minutes=2),
        code_head_sha=SHA40,
        initiated_by="human",
        payload=build_step2_equivalence_contract_payload(),
    )
    return [genesis, family, contract]


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


def test_v2_revision_is_pre_result_and_does_not_move_numeric_or_sampling_boundaries() -> None:
    assert PREREGISTRATION_REVISION["empirical_result_observed_before_revision"] is False
    assert PREREGISTRATION_REVISION["empirical_scoring_performed_before_revision"] is False
    assert PREREGISTRATION_REVISION["twelve_data_vendor_calls_used_by_revision"] == 0
    assert PREREGISTRATION_REVISION["acceptance_threshold_values_changed"] is False
    assert PREREGISTRATION_REVISION["minimum_evidence_requirements_changed"] is False
    assert PREREGISTRATION_REVISION["timestamp_hash_sampling_rule_changed"] is False
    assert PREREGISTRATION_REVISION["singleton_parameter_values_changed"] is False


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


def test_pass_is_explicitly_conjunctive_not_a_composite_score() -> None:
    assert CONJUNCTIVE_DECISION_RULE["combination_method"] == (
        "logical_conjunction_all_mandatory_criteria"
    )
    assert CONJUNCTIVE_DECISION_RULE["composite_score_used"] is False
    assert CONJUNCTIVE_DECISION_RULE["chosen_before_result_visibility"] is True
    assert "burden on retention" in CONJUNCTIVE_DECISION_RULE["rationale"]
    assert PASS_CRITERIA["pass_requires_every_mandatory_criterion"] is True
    assert PASS_CRITERIA["discretionary_override_allowed"] is False
    contract = build_step2_equivalence_contract_payload()
    assert contract["decision_rule"] == CONJUNCTIVE_DECISION_RULE


def test_threshold_region_is_exact_inclusive_plus_minus_five_for_either_source() -> None:
    assert THRESHOLD_REGION_DEFINITION["window_bps"] == "5"
    assert THRESHOLD_REGION_DEFINITION["window_kind"] == "absolute_inclusive"
    assert "<= 5 OR" in THRESHOLD_REGION_DEFINITION["membership_rule"]
    assert in_frozen_threshold_region(
        histdata_h1_atr_14_bps="25", twelve_data_h1_atr_14_bps="100", threshold_bps="20"
    )
    assert in_frozen_threshold_region(
        histdata_h1_atr_14_bps="1", twelve_data_h1_atr_14_bps="45", threshold_bps="50"
    )
    assert not in_frozen_threshold_region(
        histdata_h1_atr_14_bps="25.000001",
        twelve_data_h1_atr_14_bps="25.000001",
        threshold_bps="20",
    )
    assert in_frozen_threshold_region(
        histdata_h1_atr_14_bps="20", twelve_data_h1_atr_14_bps="50", threshold_bps="20"
    )
    assert in_frozen_threshold_region(
        histdata_h1_atr_14_bps="20", twelve_data_h1_atr_14_bps="50", threshold_bps="50"
    )
    with pytest.raises(ValueError, match="only for 20 bps and 50 bps"):
        in_frozen_threshold_region(
            histdata_h1_atr_14_bps="30", twelve_data_h1_atr_14_bps="30", threshold_bps="30"
        )


def test_h1_pairing_is_same_exact_utc_interval_not_comparable_different_periods() -> None:
    policy = COMPARISON_POPULATION["calendar_pairing_policy"]
    rule = COMPARISON_POPULATION["pairing_rule"]
    assert policy["same_calendar_period_for_both_sources"] is True
    assert policy["comparable_but_different_periods_forbidden"] is True
    assert rule["require_histdata_open_time_utc_equals_twelve_open_time_utc"] is True
    assert rule["require_histdata_end_utc_equals_twelve_end_utc"] is True

    fixed_est = timezone(timedelta(hours=-5))
    for source_time in (
        datetime(2026, 1, 15, 10, 23, tzinfo=fixed_est),
        datetime(2026, 7, 15, 10, 23, tzinfo=fixed_est),
    ):
        hist_start = _source_bucket_start(source_time, "H1").astimezone(UTC)
        hist_end = hist_start + timedelta(hours=1)
        twelve_start, twelve_end = latest_completed_bucket(
            hist_end + timedelta(minutes=1), "1h"
        )
        proof = assert_exact_h1_pair(
            histdata_start_utc=hist_start,
            histdata_end_utc=hist_end,
            twelve_start_utc=twelve_start,
            twelve_end_utc=twelve_end,
        )
        assert proof["state"] == "exact_same_utc_h1_interval"

    with pytest.raises(ValueError, match="exact matching UTC start and end"):
        assert_exact_h1_pair(
            histdata_start_utc=datetime(2026, 1, 2, 10, tzinfo=UTC),
            histdata_end_utc=datetime(2026, 1, 2, 11, tzinfo=UTC),
            twelve_start_utc=datetime(2026, 1, 2, 11, tzinfo=UTC),
            twelve_end_utc=datetime(2026, 1, 2, 12, tzinfo=UTC),
        )


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


def test_repository_manifest_digests_match_checked_out_preregistration_code() -> None:
    manifest = _manifest()
    result = assert_repository_preregistration_manifest(manifest)
    assert result["contract_digest"] == step2_contract_digest()
    assert result["research_family_digest"] == digest(build_step2_research_family_payload())


def test_scoring_guard_requires_identical_repository_and_ledger_preregistration() -> None:
    result = assert_step2_scoring_prerequisites(
        manifest=_manifest(), research_ledger_records=_valid_preregistration_chain()
    )
    assert result["state"] == "step2_scoring_prerequisites_satisfied"
    assert result["research_family_sequence"] == 1
    assert result["equivalence_contract_sequence"] == 2
    assert result["contract_digest"] == step2_contract_digest()


def test_scoring_guard_fails_loudly_on_manifest_or_valid_ledger_contract_divergence() -> None:
    bad_manifest = _manifest()
    bad_manifest["equivalence_contract_digest_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="manifest contract digest"):
        assert_step2_scoring_prerequisites(
            manifest=bad_manifest, research_ledger_records=_valid_preregistration_chain()
        )

    chain = _valid_preregistration_chain()
    mutated_contract = build_step2_equivalence_contract_payload()
    mutated_contract["authorization_scope"] = "unexpected_scope"
    replacement = build_record(
        sequence=2,
        previous_digest=chain[1]["record_digest"],
        record_type=EQUIVALENCE_CONTRACT_RECORD_TYPE,
        recorded_at=datetime(2026, 9, 2, 9, 2, tzinfo=UTC),
        code_head_sha=SHA40,
        initiated_by="human",
        payload=mutated_contract,
    )
    divergent_chain = [chain[0], chain[1], replacement]
    with pytest.raises(ValueError, match="D1 equivalence-contract digest"):
        assert_step2_scoring_prerequisites(
            manifest=_manifest(), research_ledger_records=divergent_chain
        )


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
