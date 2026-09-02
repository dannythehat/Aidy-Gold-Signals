"""Frozen Day 53 Step 2 inheritance-qualification contract.

This module defines the experiment before the qualification result is computed.
It deliberately does not fetch market data or evaluate the contract.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from aidy.market_data_semantics import histdata_semantic_identity, twelve_data_semantic_identity
from aidy.research_trials import digest, equivalence_contract_payload, research_family_payload

STEP2_PREREGISTRATION_VERSION = "aidy_day53_step2_existing_constant_equivalence_v2"
STEP2_RESEARCH_FAMILY_ID = "day53-histdata-twelve-20-50-40-equivalence-v1"
STEP2_QUALIFICATION_ID = "day53-histdata-twelve-active-scale-sensitive-surface-v1"
STEP2_AUTHORIZATION_SCOPE = "active_scale_sensitive_20_50_40_inheritance_only"

PREREGISTRATION_REVISION: dict[str, Any] = {
    "supersedes_version": "aidy_day53_step2_existing_constant_equivalence_v1",
    "reviewed_after_repository_head_sha": "14d8e9d0e17113dec60586386b04a5538874ba96",
    "reason": (
        "Make pre-result design choices explicit: conjunctive-all decision rule, inclusive +/-5 bps "
        "threshold-region membership, exact same-UTC H1 interval pairing, and repository-manifest/"
        "ledger digest equality guard."
    ),
    "empirical_result_observed_before_revision": False,
    "empirical_scoring_performed_before_revision": False,
    "twelve_data_vendor_calls_used_by_revision": 0,
    "acceptance_threshold_values_changed": False,
    "minimum_evidence_requirements_changed": False,
    "timestamp_hash_sampling_rule_changed": False,
    "singleton_parameter_values_changed": False,
}

CONJUNCTIVE_DECISION_RULE: dict[str, Any] = {
    "combination_method": "logical_conjunction_all_mandatory_criteria",
    "composite_score_used": False,
    "rationale": (
        "Inheritance places the burden on retention: every registered mandatory decision-surface "
        "and coverage criterion must pass, so strength on one metric cannot compensate for failure "
        "on another."
    ),
    "chosen_before_result_visibility": True,
    "discretionary_override_allowed": False,
}

THRESHOLD_REGION_DEFINITION: dict[str, Any] = {
    "thresholds_bps": ["20", "50"],
    "window_bps": "5",
    "window_kind": "absolute_inclusive",
    "membership_rule": (
        "include if abs(histdata_h1_atr_14_bps - threshold_bps) <= 5 OR "
        "abs(twelve_data_h1_atr_14_bps - threshold_bps) <= 5"
    ),
    "regions_evaluated_independently": True,
    "observation_may_enter_both_regions_if_different_sources_trigger_different_thresholds": True,
    "chosen_before_result_visibility": True,
}

PREREGISTERED_PARAMETER_SPACE: dict[str, Any] = {
    "selection_origin": "preregistered_explicit",
    "search_performed": False,
    "candidate_configurations": 1,
    "volatility_low_lt_bps": "20",
    "volatility_high_gte_bps": "50",
    "h1_atr_similarity_scale_bps": "40",
    "m15_realized_vol_similarity_scale_bps": {
        "value": "30",
        "status": "excluded_legacy_v1_not_active_in_authoritative_v2",
    },
    "v2_context_frozen_not_under_test": {
        "minimum_similarity_score": "0.72",
        "minimum_component_coverage": "0.65",
        "episode_horizon_minutes": 240,
        "embargo_minutes": 240,
    },
}
PARAMETER_SPACE_DIGEST = digest(PREREGISTERED_PARAMETER_SPACE)

PRIOR_KNOWLEDGE: dict[str, Any] = {
    "criteria_are_informed_not_blind": True,
    "earlier_reconciliation_is_prior_evidence_not_qualification_sample": True,
    "median_absolute_difference_bps_approx_range": [10, 14],
    "p95_absolute_difference_bps_approx_range": [38, 57],
    "tail_max_absolute_difference_bps_approx": 97,
}

COMPARISON_POPULATION: dict[str, Any] = {
    "instrument": "XAUUSD",
    "historical_bucket_end_start_utc_inclusive": "2026-01-01T00:00:00+00:00",
    "historical_bucket_end_cutoff_utc_inclusive": "2026-08-31T23:00:00+00:00",
    "base_unit": "H1 half-open interval [start_utc,end_utc)",
    "pairing_key": "exact_same_utc_h1_interval_start_and_end",
    "calendar_pairing_policy": {
        "same_calendar_period_for_both_sources": True,
        "comparable_but_different_periods_forbidden": True,
        "pair_only_after_each_source_constructs_its_h1_bar_independently": True,
    },
    "pairing_rule": {
        "require_histdata_open_time_utc_equals_twelve_open_time_utc": True,
        "require_histdata_end_utc_equals_twelve_end_utc": True,
        "h1_end_definition": "open_time_utc + 60 minutes",
        "source_session_conventions_are_not_coerced_before_bar_construction": True,
        "constituent_minute_policy_remains_source_native": True,
        "h1_alignment_note": (
            "HistData fixed UTC-05 hourly boundaries and Twelve UTC-epoch hourly boundaries both "
            "land on UTC hour boundaries; equality is still checked, not assumed."
        ),
    },
    "source_construction": {
        "histdata": (
            "fixed EST source timestamps aggregated by source-hour; no AIDY New York session filter"
        ),
        "twelve_data": (
            "UTC vendor M1 aggregated after AIDY New York gold-session filtering with exact "
            "expected-minute completeness and UTC-epoch H1 boundaries"
        ),
    },
    "eligibility": [
        "both sources have complete input required to compute H1 ATR(14)",
        "no failed or incomplete Twelve bootstrap provenance is admitted",
        "no feature/outcome/manual-difference exclusion is permitted",
        "no imputation winsorisation or outlier trimming is permitted",
    ],
    "qualification_selector": (
        "sha256('aidy-day53-step2-v1|'+h1_bucket_end_utc) interpreted as integer modulo 4 equals 0"
    ),
    "retrieval_query_selector": (
        "within qualification set: sha256('aidy-day53-step2-v1|retrieval|'+"
        "h1_bucket_end_utc) interpreted as integer modulo 4 equals 0"
    ),
    "candidate_universe": (
        "all otherwise-eligible frozen HistData retrospective cases with as_of_utc at or before "
        "2026-08-31T23:00:00+00:00; exact case-id universe digest must be registered before scoring"
    ),
    "qualification_only_cross_source_harness": True,
    "qualification_harness_decision_input_allowed": False,
    "retrieval_isolation_rule": (
        "hold non-target query components fixed to the HistData baseline and substitute only "
        "H1 ATR(14) bps and the derived 20/50 volatility band from Twelve Data"
    ),
}
COMPARISON_POPULATION_DIGEST = digest(COMPARISON_POPULATION)

COVERAGE_REQUIREMENTS: dict[str, Any] = {
    "minimum_paired_h1_qualification_observations": 600,
    "minimum_distinct_new_york_trading_dates": 60,
    "minimum_distinct_dates_by_new_york_utc_offset": {
        "EST_minus_05_00": 20,
        "EDT_minus_04_00": 20,
    },
    "minimum_threshold_near_observations": {
        "20_bps_either_source_within_plus_minus_5_bps": 60,
        "50_bps_either_source_within_plus_minus_5_bps": 60,
    },
    "minimum_retrieval_query_count": 250,
    "minimum_queries_with_both_retrievals_non_empty": 150,
    "minimum_session_query_count_each": {
        "asia": 50,
        "london": 50,
        "new_york": 50,
    },
    "minimum_pairing_coverage_of_common_scheduled_h1_buckets": "0.95",
}

DISTRIBUTION_METRICS: list[dict[str, Any]] = [
    {
        "metric": "paired_h1_atr_14_bps_absolute_difference",
        "statistics": ["median", "p95", "maximum"],
        "role": "mandatory_reported_diagnostic_not_standalone_pass_rule",
    },
    {
        "metric": "paired_feature_availability_disagreement_rate",
        "role": "mandatory_integrity_and_coverage_metric",
    },
]

DECISION_SURFACE_METRICS: list[dict[str, Any]] = [
    {
        "metric": "volatility_band_three_class_agreement",
        "classes": ["low", "normal", "high"],
        "uncertainty": "wilson_score_95_percent",
    },
    {
        "metric": "threshold_near_band_disagreement",
        "thresholds_bps": [20, 50],
        "window_bps": 5,
        "window_membership": "inclusive_either_source",
        "uncertainty": "wilson_score_95_percent",
    },
    {
        "metric": "v2_volatility_hard_gate_boolean_agreement",
        "uncertainty": "wilson_score_95_percent",
    },
    {
        "metric": "volatility_dependent_setup_band_predicate_agreement",
        "setup_ids": [
            "low_vol_break_pressure_long",
            "low_vol_break_pressure_short",
            "high_vol_recovery_long",
            "high_vol_recovery_short",
        ],
        "note": "band predicate only; full setup eligibility is diagnostic because other inputs remain Step1.5 amber",
    },
    {
        "metric": "v2_retrieval_empty_nonempty_state_agreement",
        "uncertainty": "wilson_score_95_percent",
    },
    {
        "metric": "selected_independent_episode_set_jaccard",
        "population": "queries where at least one retrieval is non-empty",
        "empty_empty_queries": "excluded_from_jaccard_and_retained_in_state_agreement",
        "percentile_method": "nearest_rank",
    },
    {
        "metric": "top_ranked_selected_episode_agreement",
        "population": "queries where both retrievals are non-empty",
        "uncertainty": "wilson_score_95_percent",
    },
    {
        "metric": "selected_episode_count_absolute_difference_le_1_rate",
        "uncertainty": "wilson_score_95_percent",
    },
    {
        "metric": "evidence_grade_agreement",
        "uncertainty": "wilson_score_95_percent",
    },
]

PASS_CRITERIA: dict[str, Any] = {
    "all_coverage_requirements_met": True,
    "no_integrity_violation": True,
    "paired_feature_availability_agreement_rate_gte": "0.98",
    "volatility_band_three_class_agreement_rate_gte": "0.975",
    "volatility_band_agreement_wilson_95_lower_gte": "0.96",
    "threshold_near_each_band_disagreement_rate_lte": "0.125",
    "threshold_near_each_band_disagreement_wilson_95_upper_lte": "0.20",
    "v2_volatility_hard_gate_agreement_rate_gte": "0.975",
    "v2_volatility_hard_gate_agreement_wilson_95_lower_gte": "0.96",
    "volatility_setup_band_predicate_agreement_rate_gte": "0.975",
    "retrieval_empty_nonempty_state_agreement_rate_gte": "0.95",
    "retrieval_state_agreement_wilson_95_lower_gte": "0.93",
    "selected_episode_jaccard_median_gte": "0.80",
    "selected_episode_jaccard_p10_gte": "0.60",
    "top_ranked_selected_episode_agreement_rate_gte": "0.90",
    "top_rank_agreement_wilson_95_lower_gte": "0.87",
    "selected_episode_count_abs_diff_le_1_rate_gte": "0.95",
    "evidence_grade_agreement_rate_gte": "0.95",
    "evidence_grade_agreement_wilson_95_lower_gte": "0.93",
    "pass_requires_every_mandatory_criterion": True,
    "discretionary_override_allowed": False,
}

FAIL_CRITERIA: dict[str, Any] = {
    "when_coverage_is_sufficient": "fail if any mandatory PASS boundary is not satisfied",
    "inheritance_allowed": False,
    "tolerance_relaxation_after_result_allowed": False,
    "automatic_parameter_redefinition_allowed": False,
}

INSUFFICIENT_EVIDENCE_CRITERIA: dict[str, Any] = {
    "trigger_if_any_minimum_coverage_requirement_is_unmet": True,
    "trigger_if_required_source_or_candidate_universe_cannot_be_frozen": True,
    "trigger_if_required_uncertainty_statistic_cannot_be_computed": True,
    "inheritance_allowed": False,
    "default_state": True,
}

INTEGRITY_RULES: dict[str, Any] = {
    "future_outcome_or_pnl_fields_allowed": False,
    "trade_results_used": False,
    "parameter_search_allowed": False,
    "post_result_exclusion_allowed": False,
    "post_result_tolerance_change_allowed": False,
    "prior_reconciliation_counted_as_qualification_sample": False,
    "qualification_result_states": ["pass", "fail", "insufficient_evidence"],
    "invalid_run_policy": (
        "digest mismatch, changed contract, outcome leakage or result-based exclusion invalidates the run; "
        "record the attempt but do not emit an inheritance PASS"
    ),
}


def build_step2_research_family_payload() -> dict[str, Any]:
    payload = research_family_payload(
        research_family_id=STEP2_RESEARCH_FAMILY_ID,
        research_question=(
            "Does changing only the Gold market-data semantic family from HistData to Twelve Data "
            "preserve the existing active V2 20/50 volatility-band and 40-bps H1 ATR similarity "
            "decision surface sufficiently to inherit those constants without redefinition?"
        ),
        hypothesis=(
            "The frozen 20 bps, 50 bps and 40 bps constants preserve their specified decision "
            "semantics under the preregistered paired-source comparison; otherwise inheritance is blocked."
        ),
        parameter_space_digest=PARAMETER_SPACE_DIGEST,
        first_result_visible=False,
    )
    payload.update(
        {
            "preregistration_version": STEP2_PREREGISTRATION_VERSION,
            "selection_origin": "preregistered_explicit",
            "initiated_by": "human",
            "prior_knowledge": PRIOR_KNOWLEDGE,
            "decision_rule": CONJUNCTIVE_DECISION_RULE,
            "threshold_region_definition": THRESHOLD_REGION_DEFINITION,
            "preregistration_revision": PREREGISTRATION_REVISION,
            "no_parameter_search": True,
            "failure_routes_to_new_step3_rederivation_family": True,
        }
    )
    return payload


def build_step2_equivalence_contract_payload() -> dict[str, Any]:
    hist = histdata_semantic_identity()
    twelve = twelve_data_semantic_identity()
    payload = equivalence_contract_payload(
        qualification_id=STEP2_QUALIFICATION_ID,
        affected_surface="20_50_volatility_band_plus_v2_40bps_h1_atr_similarity",
        source_identity_a_digest=hist["semantic_identity_digest"],
        source_identity_b_digest=twelve["semantic_identity_digest"],
        comparison_population_digest=COMPARISON_POPULATION_DIGEST,
        minimum_paired_sample=COVERAGE_REQUIREMENTS[
            "minimum_paired_h1_qualification_observations"
        ],
        coverage_requirements=COVERAGE_REQUIREMENTS,
        distribution_metrics=DISTRIBUTION_METRICS,
        decision_surface_metrics=DECISION_SURFACE_METRICS,
        pass_criteria=PASS_CRITERIA,
        fail_criteria=FAIL_CRITERIA,
        insufficient_evidence_criteria=INSUFFICIENT_EVIDENCE_CRITERIA,
    )
    payload.update(
        {
            "preregistration_version": STEP2_PREREGISTRATION_VERSION,
            "research_family_id": STEP2_RESEARCH_FAMILY_ID,
            "parameter_space_digest": PARAMETER_SPACE_DIGEST,
            "prior_knowledge": PRIOR_KNOWLEDGE,
            "comparison_population": COMPARISON_POPULATION,
            "decision_rule": CONJUNCTIVE_DECISION_RULE,
            "threshold_region_definition": THRESHOLD_REGION_DEFINITION,
            "preregistration_revision": PREREGISTRATION_REVISION,
            "authorization_scope": STEP2_AUTHORIZATION_SCOPE,
            "cross_source_retrieval_permission_on_pass": False,
            "full_retrieval_permission_requires_later_qualification": True,
            "m15_30bps_v1_scale_qualified_by_this_contract": False,
            "integrity_rules": INTEGRITY_RULES,
        }
    )
    return payload


def step2_contract_digest() -> str:
    return digest(build_step2_equivalence_contract_payload())


def validate_step2_result_payload(result: Mapping[str, Any]) -> None:
    """Validate result binding only; empirical criterion evaluation happens in the later runner."""

    if result.get("qualification_id") != STEP2_QUALIFICATION_ID:
        raise ValueError("Step 2 result qualification_id does not match preregistration.")
    if result.get("contract_digest") != step2_contract_digest():
        raise ValueError("Step 2 result does not bind the frozen preregistration digest.")
    outcome = result.get("outcome")
    if outcome not in {"pass", "fail", "insufficient_evidence"}:
        raise ValueError("Step 2 result has an unknown outcome.")
    expected_inheritance = outcome == "pass"
    if result.get("inheritance_allowed") is not expected_inheritance:
        raise ValueError("Step 2 inheritance flag is inconsistent with its frozen outcome rule.")
    if result.get("cross_source_retrieval_permission") not in (None, False):
        raise ValueError("Step 2 cannot grant full cross-source retrieval permission.")
