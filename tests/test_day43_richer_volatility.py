from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from aidy.richer_volatility import (
    DAY43_EXPERIMENT_PLAN_VERSION,
    EVENT_IV_KINK_VERSION,
    RICHER_VOLATILITY_VERSION,
    UNEXPLAINED_SHOCK_VERSION,
    RicherVolatilityError,
    build_event_iv_kink,
    build_richer_volatility_regime,
    build_unexplained_market_shock,
    day43_experiment_plan,
    run_day43_experiment,
)

NOW = datetime(2026, 9, 1, 10, 45, tzinfo=UTC)
EVENT = NOW + timedelta(days=2)


def _json(path: str) -> dict[str, object]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _day31_state() -> dict[str, object]:
    return _json("evidence/day31/retrospective_volatility_state.json")


def _foundation() -> dict[str, object]:
    return _json("evidence/day31/j7_j8_foundation.json")


def _split() -> dict[str, object]:
    return {
        "manifest_version": "aidy_chronological_split_manifest_v1",
        "split_digest": "a" * 64,
        "purge_required": True,
        "embargo_required": True,
        "holdout_tuning_allowed": False,
    }


def test_event_kink_remains_unavailable_without_pit_options_term_structure() -> None:
    kink = build_event_iv_kink(as_of=NOW, event_at=EVENT, observations=[])
    assert kink["version"] == EVENT_IV_KINK_VERSION
    assert kink["state"] == "unavailable_no_pit_options_term_structure"
    assert kink["kink_percentage_points"] is None
    assert kink["pit_reconstructable"] is False
    assert kink["event_outcome_used"] is False


def test_event_kink_uses_only_observations_known_before_event() -> None:
    observations = [
        {
            "observed_at_utc": (NOW - timedelta(minutes=5)).isoformat(),
            "event_at_utc": EVENT.isoformat(),
            "near_expiry_calendar_days": 7,
            "far_expiry_calendar_days": 35,
            "near_iv_annualized_percent": "28",
            "far_iv_annualized_percent": "23.5",
            "source": "approved_options_source",
            "source_identity": "fixture-pit-options-1",
            "pit_reconstructable": True,
        },
        {
            "observed_at_utc": (NOW + timedelta(minutes=5)).isoformat(),
            "event_at_utc": EVENT.isoformat(),
            "near_expiry_calendar_days": 7,
            "far_expiry_calendar_days": 35,
            "near_iv_annualized_percent": "99",
            "far_iv_annualized_percent": "1",
            "source": "future_leak",
            "source_identity": "must-not-be-used",
            "pit_reconstructable": True,
        },
    ]
    kink = build_event_iv_kink(as_of=NOW, event_at=EVENT, observations=observations)
    assert kink["state"] == "known"
    assert kink["kink_percentage_points"] == "4.5"
    assert kink["source"] == "approved_options_source"
    assert kink["source_identity"] == "fixture-pit-options-1"
    assert kink["event_outcome_used"] is False


def test_event_kink_cannot_be_built_after_event() -> None:
    with pytest.raises(RicherVolatilityError, match="before the event"):
        build_event_iv_kink(as_of=EVENT, event_at=EVENT, observations=[])


def test_unexplained_shock_is_market_only_and_deterministic() -> None:
    shock = build_unexplained_market_shock(
        as_of=NOW,
        volatility_z="3.1",
        volume_z="2.8",
        spread_z="0.5",
        cross_asset_reaction_z="-2.7",
    )
    assert shock["version"] == UNEXPLAINED_SHOCK_VERSION
    assert shock["state"] == "unexplained_market_shock"
    assert shock["trigger_count"] == 3
    assert shock["market_derived_only"] is True
    assert shock["news_or_sentiment_input_used"] is False
    assert shock["geopolitical_label_used"] is False
    assert shock["narrative_cause"] is None
    assert shock["intent_label"] is None


def test_unexplained_shock_does_not_trigger_from_one_abnormal_metric() -> None:
    shock = build_unexplained_market_shock(
        as_of=NOW,
        volatility_z="3",
        volume_z="1",
        spread_z="1",
        cross_asset_reaction_z="1",
    )
    assert shock["state"] == "normal_market_reaction"
    assert shock["trigger_count"] == 1


def test_richer_regime_reuses_day31_estimators_and_remains_shadow() -> None:
    kink = build_event_iv_kink(as_of=NOW, event_at=EVENT, observations=[])
    shock = build_unexplained_market_shock(
        as_of=NOW,
        volatility_z="3",
        volume_z="3",
        spread_z="3",
        cross_asset_reaction_z="0",
    )
    regime = build_richer_volatility_regime(
        day31_state=_day31_state(), shock_state=shock, event_kink=kink
    )
    assert regime["version"] == RICHER_VOLATILITY_VERSION
    assert regime["gvz_iv_horizon_calendar_days"] == 30
    assert regime["rv_horizons_trading_days"] == [5, 10, 21]
    assert regime["jump_estimator"] == "realized_variation_minus_bipower_variation"
    assert regime["vol_of_vol_window_trading_days"] == 21
    assert regime["redundant_volatility_estimators_added"] is False
    assert regime["cvol_state"] == "deferred_pending_gvz_evidence_and_owner_approval"
    assert regime["features_shadow_only"] is True
    assert regime["decision_input_allowed"] is False
    assert regime["trading_gate_created"] is False


def test_richer_regime_rejects_narrative_tampering() -> None:
    kink = build_event_iv_kink(as_of=NOW, event_at=EVENT, observations=[])
    shock = build_unexplained_market_shock(
        as_of=NOW,
        volatility_z="3",
        volume_z="3",
        spread_z="0",
        cross_asset_reaction_z="0",
    )
    shock["narrative_cause"] = "geopolitics"
    with pytest.raises(RicherVolatilityError, match="digest mismatch|Narrative"):
        build_richer_volatility_regime(
            day31_state=_day31_state(), shock_state=shock, event_kink=kink
        )


def test_day43_plan_binds_day31_foundation_and_freezes_promotion_rules() -> None:
    plan = day43_experiment_plan(day31_foundation=_foundation())
    assert plan["version"] == DAY43_EXPERIMENT_PLAN_VERSION
    assert plan["chronological_split_required"] is True
    assert plan["purge_required"] is True
    assert plan["embargo_required"] is True
    assert plan["episode_independence_required"] is True
    assert plan["day32_trial_registry_required"] is True
    assert plan["threshold_tuning_on_evaluation_set_allowed"] is False
    assert plan["null_or_insufficient_result_allowed"] is True
    assert plan["single_result_can_promote_gate"] is False
    assert plan["cvol_purchase_authorized"] is False


def test_j7_insufficient_is_retained_without_gate() -> None:
    rows = [
        {"independent_episode_id": "e1", "incremental_statistic": "0.2"},
        {"independent_episode_id": "e1", "incremental_statistic": "99"},
    ]
    result = run_day43_experiment(experiment="J7", rows=rows, split_binding=_split())
    assert result["effective_independent_n"] == 1
    assert result["result_state"] == "insufficient"
    assert result["null_or_insufficient_result_retained"] is True
    assert result["gate_promoted"] is False
    assert result["proposed_trading_gate"] is None


def test_j8_null_is_retained_without_predictive_claim() -> None:
    rows = [
        {"independent_episode_id": f"e{index}", "incremental_statistic": "0"}
        for index in range(30)
    ]
    result = run_day43_experiment(experiment="J8", rows=rows, split_binding=_split())
    assert result["effective_independent_n"] == 30
    assert result["result_state"] == "null"
    assert result["mean_incremental_statistic"] == "0"
    assert result["predictive_edge_claimed"] is False
    assert result["gate_promoted"] is False


def test_non_null_result_still_cannot_promote() -> None:
    rows = [
        {"independent_episode_id": f"e{index}", "incremental_statistic": "0.1"}
        for index in range(30)
    ]
    result = run_day43_experiment(experiment="J7", rows=rows, split_binding=_split())
    assert result["result_state"] == "descriptive_non_null"
    assert result["gate_promoted"] is False
    assert result["features_shadow_only"] is True
    assert result["formal_forward_evidence_created"] is False


def test_experiment_rejects_unpurged_or_holdout_tuning_contract() -> None:
    binding = _split()
    binding["purge_required"] = False
    with pytest.raises(RicherVolatilityError, match="purge"):
        run_day43_experiment(experiment="J7", rows=[], split_binding=binding)

    binding = _split()
    binding["holdout_tuning_allowed"] = True
    with pytest.raises(RicherVolatilityError, match="holdout"):
        run_day43_experiment(experiment="J8", rows=[], split_binding=binding)
