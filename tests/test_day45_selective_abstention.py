from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta

import pytest

from aidy.selective_abstention import (
    MIN_EFFECTIVE_TEST_N,
    SelectiveAbstentionError,
    build_chronological_split,
    calibrate_split_conformal,
    day45_manifest,
    evaluate_j9,
    evaluate_j10,
    fit_deterministic_baseline,
    predict_baseline_risk,
    run_shadow_selective_experiment,
    score_shadow_position,
)

BASE = datetime(2026, 1, 1, tzinfo=UTC)


def _split():
    return build_chronological_split(
        fit_start=BASE,
        fit_end=BASE + timedelta(days=30),
        calibration_start=BASE + timedelta(days=30),
        calibration_end=BASE + timedelta(days=60),
        test_start=BASE + timedelta(days=60),
        test_end=BASE + timedelta(days=90),
    )


def _rows(count_per_window: int = 30):
    rows = []
    for window_index, start_day in enumerate((0, 30, 60)):
        for index in range(count_per_window):
            high = index % 2 == 1
            rows.append(
                {
                    "episode_id": f"w{window_index}-e{index:03d}",
                    "as_of_utc": (BASE + timedelta(days=start_day, hours=index)).isoformat(),
                    "risk_signal": "1" if high else "0",
                    "volatility_instability": "0.9" if high else "0.1",
                    "adverse_outcome": high,
                }
            )
    return rows


def test_split_requires_strict_chronological_nonoverlap() -> None:
    split = _split()
    assert split["fit"]["end_utc"] == split["calibration"]["start_utc"]
    assert split["calibration"]["end_utc"] == split["test"]["start_utc"]
    assert split["test_outcomes_available_to_fit"] is False

    with pytest.raises(SelectiveAbstentionError, match="chronological and non-overlapping"):
        build_chronological_split(
            fit_start=BASE,
            fit_end=BASE + timedelta(days=40),
            calibration_start=BASE + timedelta(days=30),
            calibration_end=BASE + timedelta(days=60),
            test_start=BASE + timedelta(days=60),
            test_end=BASE + timedelta(days=90),
        )


def test_model_confidence_cannot_be_a_baseline_feature() -> None:
    with pytest.raises(SelectiveAbstentionError, match="Model confidence"):
        fit_deterministic_baseline(
            _rows()[:30],
            feature_names=("model_confidence",),
        )


def test_baseline_is_deterministic_and_order_independent() -> None:
    fit_rows = _rows()[:30]
    first = fit_deterministic_baseline(fit_rows, feature_names=("risk_signal",))
    second = fit_deterministic_baseline(
        list(reversed(copy.deepcopy(fit_rows))),
        feature_names=("risk_signal",),
    )
    assert first == second
    assert first["model_confidence_used"] is False
    assert first["fit_effective_n"] == 30


def test_baseline_prediction_tracks_fitted_risk_signal() -> None:
    baseline = fit_deterministic_baseline(_rows()[:30], feature_names=("risk_signal",))
    low = predict_baseline_risk({"risk_signal": "0"}, baseline)
    high = predict_baseline_risk({"risk_signal": "1"}, baseline)
    assert low < high
    assert low == 0
    assert high == 1


def test_calibration_is_separate_and_records_no_test_outcome_use() -> None:
    rows = _rows()
    baseline = fit_deterministic_baseline(rows[:30], feature_names=("risk_signal",))
    calibration = calibrate_split_conformal(
        rows[30:60],
        baseline=baseline,
        alpha="0.2",
    )
    assert calibration["calibration_effective_n"] == 30
    assert calibration["test_outcomes_used"] is False
    assert calibration["qhat"] == "0.000000"


def test_shadow_position_never_blocks_master_trader_or_publication() -> None:
    rows = _rows()
    baseline = fit_deterministic_baseline(rows[:30], feature_names=("risk_signal",))
    calibration = calibrate_split_conformal(rows[30:60], baseline=baseline)
    low = score_shadow_position(
        rows[60],
        baseline=baseline,
        calibration=calibration,
        risk_ceiling="0.45",
    )
    high = score_shadow_position(
        rows[61],
        baseline=baseline,
        calibration=calibration,
        risk_ceiling="0.45",
    )
    assert low["shadow_position"] == "accept"
    assert high["shadow_position"] == "reject"
    assert low["master_trader_block_allowed"] is False
    assert low["publication_block_allowed"] is False


def test_end_to_end_experiment_reports_raw_and_effective_n() -> None:
    rows = _rows()
    rows.append(copy.deepcopy(rows[-1]))
    result = run_shadow_selective_experiment(
        rows,
        split=_split(),
        feature_names=("risk_signal",),
        random_identity="day45-j9-frozen-random-v1",
    )
    assert result["raw_n"]["test"] == 31
    assert result["effective_n"]["test"] == 30
    assert result["risk_coverage"]["raw_test_n"] == 31
    assert result["risk_coverage"]["effective_test_n"] == 30
    assert result["risk_coverage"]["sample_size_basis"] == "episode_independent_effective_n"


def test_test_outcome_changes_cannot_change_fit_or_calibration() -> None:
    first_rows = _rows()
    second_rows = copy.deepcopy(first_rows)
    for row in second_rows[60:]:
        row["adverse_outcome"] = not row["adverse_outcome"]

    first = run_shadow_selective_experiment(
        first_rows,
        split=_split(),
        feature_names=("risk_signal",),
        random_identity="day45-j9-frozen-random-v1",
    )
    second = run_shadow_selective_experiment(
        second_rows,
        split=_split(),
        feature_names=("risk_signal",),
        random_identity="day45-j9-frozen-random-v1",
    )
    assert first["baseline"] == second["baseline"]
    assert first["calibration"] == second["calibration"]


def test_conflicting_duplicate_episode_fails_closed() -> None:
    rows = _rows()
    duplicate = copy.deepcopy(rows[0])
    duplicate["adverse_outcome"] = not duplicate["adverse_outcome"]
    with pytest.raises(SelectiveAbstentionError, match="Conflicting duplicate"):
        run_shadow_selective_experiment(
            rows + [duplicate],
            split=_split(),
            feature_names=("risk_signal",),
            random_identity="day45-j9-frozen-random-v1",
        )


def test_same_episode_cannot_cross_split_boundaries() -> None:
    rows = _rows()
    crossed = copy.deepcopy(rows[0])
    crossed["as_of_utc"] = (BASE + timedelta(days=61)).isoformat()
    with pytest.raises(SelectiveAbstentionError, match="crosses fit/calibration/test"):
        run_shadow_selective_experiment(
            rows + [crossed],
            split=_split(),
            feature_names=("risk_signal",),
            random_identity="day45-j9-frozen-random-v1",
        )


def test_j9_uses_matched_coverage_random_baseline_on_same_episode_pool() -> None:
    rows = _rows()[60:]
    selected = [row["episode_id"] for row in rows if row["risk_signal"] == "0"]
    result = evaluate_j9(
        rows,
        selected_episode_ids=selected,
        raw_test_n=len(rows),
        random_identity="day45-j9-frozen-random-v1",
    )
    assert result["effective_test_n"] == 30
    assert result["effective_selected_n"] == 15
    assert result["matched_random_coverage_identical"] is True
    assert result["matched_random_uses_same_independent_episode_pool"] is True
    assert result["promotion_authorized"] is False


def test_j9_insufficient_sample_cannot_support_conclusion() -> None:
    rows = _rows(count_per_window=8)[16:]
    result = evaluate_j9(
        rows,
        selected_episode_ids=[rows[0]["episode_id"]],
        raw_test_n=len(rows),
        random_identity="day45-j9-small",
    )
    assert len(rows) < MIN_EFFECTIVE_TEST_N
    assert result["result_state"] == "insufficient"


def test_j10_uses_fixed_volatility_threshold_and_episode_n() -> None:
    rows = _rows()[60:]
    selected = [row["episode_id"] for row in rows if row["risk_signal"] == "0"]
    result = evaluate_j10(
        rows,
        selected_episode_ids=selected,
        raw_test_n=len(rows),
    )
    assert result["volatility_threshold"] == "0.500000"
    assert result["threshold_frozen_before_test"] is True
    assert result["groups"]["low"]["effective_n"] == 15
    assert result["groups"]["high"]["effective_n"] == 15
    assert result["groups"]["low"]["acceptance_rate"] == "1.000000"
    assert result["groups"]["high"]["acceptance_rate"] == "0.000000"
    assert result["result_state"] == "conditioning_present"
    assert result["trading_gate_created"] is False


def test_j10_cannot_use_confidence_as_instability_proxy() -> None:
    with pytest.raises(SelectiveAbstentionError, match="Model confidence"):
        evaluate_j10(
            _rows()[60:],
            selected_episode_ids=[],
            raw_test_n=30,
            volatility_field="model_confidence",
        )


def test_risk_coverage_grid_is_frozen_and_not_optimized_on_test() -> None:
    result = run_shadow_selective_experiment(
        _rows(),
        split=_split(),
        feature_names=("risk_signal",),
        random_identity="day45-j9-frozen-random-v1",
    )
    report = result["risk_coverage"]
    assert report["risk_grid_frozen_before_test"] is True
    assert report["risk_coverage_tuning_on_test_allowed"] is False
    assert report["recommended_threshold"] is None
    assert len(report["points"]) == 5


def test_end_to_end_layer_remains_shadow_only_even_when_j9_is_non_null() -> None:
    result = run_shadow_selective_experiment(
        _rows(),
        split=_split(),
        feature_names=("risk_signal",),
        random_identity="day45-j9-frozen-random-v1",
    )
    assert result["j9"]["result_state"] in {"selective_lower_risk", "null_or_worse"}
    assert result["shadow_only"] is True
    assert result["master_trader_gate_created"] is False
    assert result["publication_gate_created"] is False
    assert result["automatic_promotion_allowed"] is False
    assert result["formal_forward_evidence_created"] is False


def test_manifest_freezes_day45_architecture_boundaries() -> None:
    manifest = day45_manifest()
    assert manifest["fit_calibration_test_chronological_nonoverlap_required"] is True
    assert manifest["test_untouched_until_evaluation_required"] is True
    assert manifest["episode_independent_effective_n_required"] is True
    assert manifest["matched_coverage_random_baseline_required"] is True
    assert manifest["model_confidence_as_gate_allowed"] is False
    assert manifest["shadow_output_can_block_master_trader"] is False
    assert manifest["shadow_output_can_block_publication"] is False
    assert manifest["automatic_promotion_allowed"] is False
    assert manifest["owner_approved_later_architecture_decision_required"] is True
