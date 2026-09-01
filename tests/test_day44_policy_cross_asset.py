from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from aidy.policy_cross_asset import (
    MIN_INDEPENDENT_EVALUATION_N,
    PROHIBITED_GOLD_PROXIES,
    SERIES_BROAD_USD,
    SERIES_ES,
    SERIES_EURUSD,
    SERIES_GC,
    SERIES_REAL10Y,
    SERIES_SI,
    SERIES_SR3,
    SERIES_USDJPY,
    SERIES_VIX,
    SERIES_ZN,
    SERIES_ZQ,
    Day44Error,
    build_gold_silver_state,
    build_observation,
    build_policy_path_state,
    build_risk_state,
    build_usd_composition_state,
    day44_experiment_plan,
    day44_manifest,
    day44_source_contracts,
    real_yield_policy_after_j12,
    run_day44_experiment,
    verify_observation,
    verify_source_contract,
)

NOW = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)
SHA = "a" * 64


def _obs(series: str, value: str, *, minutes: int = 0, retrospective: bool = False):
    observed = NOW + timedelta(minutes=minutes)
    return build_observation(
        series_id=series,
        value=value,
        observed_at=observed,
        first_observed_at=observed + timedelta(seconds=5),
        source_snapshot_digest=SHA,
        provenance_class="retrospective_history" if retrospective else "first_observed_capture",
        pit_reconstructable=True,
    )


def _split() -> dict[str, object]:
    return {
        "split_digest": "b" * 64,
        "purge_required": True,
        "embargo_required": True,
        "cpcv_pre_holdout_only": True,
        "holdout_tuning_allowed": False,
    }


def test_all_required_series_have_explicit_source_timestamp_and_pit_contracts() -> None:
    contracts = day44_source_contracts()
    required = {
        SERIES_ZQ,
        SERIES_SR3,
        SERIES_ZN,
        SERIES_GC,
        SERIES_SI,
        SERIES_EURUSD,
        SERIES_USDJPY,
        SERIES_VIX,
        SERIES_ES,
        SERIES_BROAD_USD,
        SERIES_REAL10Y,
    }
    assert set(contracts) == required
    assert all(verify_source_contract(item) for item in contracts.values())
    assert all(item["pit_attestation_required"] is True for item in contracts.values())
    assert all(item["timestamp_semantics"] for item in contracts.values())
    assert all(item["mandatory_for_trade"] is False for item in contracts.values())


def test_source_contract_digest_tampering_is_rejected() -> None:
    contract = dict(day44_source_contracts()[SERIES_ZN])
    contract["source_locator"] = "fake"
    assert not verify_source_contract(contract)


def test_first_observed_pit_observation_can_be_decision_eligible_but_not_mandatory() -> None:
    record = _obs(SERIES_EURUSD, "1.17")
    assert verify_observation(record)
    assert record["decision_input_allowed"] is True
    assert record["evaluation_only"] is False
    assert record["mandatory_for_trade"] is False


def test_retrospective_history_never_masquerades_as_live_decision_input() -> None:
    record = _obs(SERIES_ZN, "115.25", retrospective=True)
    assert verify_observation(record)
    assert record["pit_reconstructable"] is True
    assert record["decision_input_allowed"] is False
    assert record["evaluation_only"] is True


def test_first_observed_time_cannot_precede_observation() -> None:
    with pytest.raises(Day44Error, match="cannot precede"):
        build_observation(
            series_id=SERIES_VIX,
            value="18",
            observed_at=NOW,
            first_observed_at=NOW - timedelta(seconds=1),
            source_snapshot_digest=SHA,
            provenance_class="first_observed_capture",
            pit_reconstructable=True,
        )


def test_observation_digest_tampering_is_rejected() -> None:
    record = _obs(SERIES_ES, "6500")
    record["value"] = "1"
    assert not verify_observation(record)


def test_policy_path_zq_sr3_are_one_family_not_two_votes() -> None:
    state = build_policy_path_state(zq=_obs(SERIES_ZQ, "95.75"), sr3=_obs(SERIES_SR3, "96.10"))
    assert state["zq_implied_average_policy_rate_percent"] == "4.25"
    assert state["sr3_implied_contract_rate_percent"] == "3.9"
    assert state["independent_confirmation_units"] == 1
    assert state["components_not_independent"] is True


def test_gold_silver_ratio_requires_clock_alignment() -> None:
    state = build_gold_silver_state(
        gold=_obs(SERIES_GC, "3500"),
        silver=_obs(SERIES_SI, "35", minutes=16),
    )
    assert state["state"] == "unknown_clock_mismatch"
    assert state["gold_silver_ratio"] is None


def test_gold_silver_ratio_is_mechanical_and_shadow_only() -> None:
    state = build_gold_silver_state(
        gold=_obs(SERIES_GC, "3500"),
        silver=_obs(SERIES_SI, "35", minutes=5),
    )
    assert state["state"] == "known"
    assert state["gold_silver_ratio"] == "100"
    assert state["j11_required_before_incremental_use"] is True
    assert state["mandatory_for_trade"] is False


def test_usd_composition_preserves_broad_dollar_as_baseline_not_vote() -> None:
    state = build_usd_composition_state(
        broad_usd=_obs(SERIES_BROAD_USD, "120"),
        eurusd=_obs(SERIES_EURUSD, "1.18"),
        usdjpy=_obs(SERIES_USDJPY, "145"),
    )
    assert state["state"] == "known"
    assert state["broad_usd_is_baseline_not_a_vote"] is True
    assert state["j14_tests_incremental_composition_only"] is True
    assert state["mandatory_for_trade"] is False


def test_vix_es_are_risk_context_not_gold_proxies() -> None:
    state = build_risk_state(vix=_obs(SERIES_VIX, "20"), es=_obs(SERIES_ES, "6500"))
    assert state["state"] == "known"
    assert state["risk_state_is_context_not_gold_proxy"] is True
    assert state["mandatory_for_trade"] is False
    assert state["predictive_edge_claimed"] is False


def test_experiment_plan_freezes_j11_to_j14_without_correlation_mining() -> None:
    plan = day44_experiment_plan()
    assert {key for key in plan if key in {"j11", "j12", "j13", "j14"}} == {
        "j11",
        "j12",
        "j13",
        "j14",
    }
    assert plan["correlation_mining_allowed"] is False
    assert plan["multiple_unregistered_predictor_search_allowed"] is False
    assert plan["threshold_tuning_on_evaluation_set_allowed"] is False
    assert plan["single_result_can_promote_mandatory_feature"] is False


def test_experiments_fail_closed_when_independent_n_is_insufficient() -> None:
    for experiment in ("J11", "J12", "J13", "J14"):
        result = run_day44_experiment(experiment=experiment, rows=[], split_binding=_split())
        assert result["result_state"] == "insufficient"
        assert result["effective_independent_n"] == 0
        assert result["mandatory_feature_promoted"] is False
        assert result["trading_gate_created"] is False


def test_experiment_rejects_missing_purge_or_duplicate_episode() -> None:
    bad = dict(_split())
    bad["purge_required"] = False
    with pytest.raises(Day44Error, match="purge/embargo"):
        run_day44_experiment(experiment="J11", rows=[], split_binding=bad)
    rows = [
        {"episode_id": "e1", "precious_incremental_effect": "0.1"},
        {"episode_id": "e1", "precious_incremental_effect": "0.2"},
    ]
    with pytest.raises(Day44Error, match="Duplicate independent episode"):
        run_day44_experiment(experiment="J11", rows=rows, split_binding=_split())


def test_sufficient_null_j12_demotes_directional_use_without_promoting_gate() -> None:
    rows = []
    for index in range(MIN_INDEPENDENT_EVALUATION_N):
        rows.append(
            {
                "episode_id": f"e{index}",
                "regime": "calm" if index < MIN_INDEPENDENT_EVALUATION_N // 2 else "volatile",
                "real_yield_directional_effect": "0.001",
            }
        )
    result = run_day44_experiment(experiment="J12", rows=rows, split_binding=_split())
    assert result["result_state"] == "null"
    policy = real_yield_policy_after_j12(result)
    assert policy["directional_use_demoted"] is True
    assert policy["directional_use_promoted"] is False
    assert policy["rates_independent_confirmation_units"] == 1


def test_insufficient_j12_does_not_demote_or_promote() -> None:
    result = run_day44_experiment(experiment="J12", rows=[], split_binding=_split())
    policy = real_yield_policy_after_j12(result)
    assert policy["directional_use_demoted"] is False
    assert policy["directional_use_promoted"] is False
    assert policy["directional_influence"] == "provisional_unvalidated_j12"


def test_non_null_shadow_result_cannot_make_feature_mandatory() -> None:
    rows = [
        {"episode_id": f"e{index}", "usd_composition_incremental_effect": "0.2"}
        for index in range(MIN_INDEPENDENT_EVALUATION_N)
    ]
    result = run_day44_experiment(experiment="J14", rows=rows, split_binding=_split())
    assert result["result_state"] == "descriptive_non_null"
    assert result["mandatory_feature_promoted"] is False
    assert result["predictive_edge_claimed"] is False


def test_manifest_enforces_no_bad_gold_proxies_and_no_rate_double_counting() -> None:
    manifest = day44_manifest()
    assert tuple(manifest["prohibited_gold_proxies"]) == PROHIBITED_GOLD_PROXIES
    assert manifest["rates_independent_confirmation_units"] == 1
    assert manifest["rates_decomposition_components_not_independent"] is True
    assert manifest["cross_asset_features_mandatory"] == []
    assert manifest["correlation_mining_allowed"] is False
    assert manifest["formal_forward_evidence_created"] is False
    assert manifest["paid_live_market_data_activation_performed"] is False
    assert manifest["super_signals_modified"] is False
