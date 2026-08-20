from __future__ import annotations

from aidy.day23_research import (
    QUERY_COUNT,
    episode_independence_diagnostics,
    freeze_query_manifest,
    realized_dispersion,
    summarize_j1,
    summarize_j16,
)


def _match(case_id: str, stamp: str, terminal: str = "1", path: str = "directional_up") -> dict:
    return {
        "case_id": case_id,
        "as_of_utc": stamp,
        "similarity": {"similarity_score": "0.90", "component_coverage": "0.80"},
        "future_evaluation": {
            "move_bundle": {
                "labels": [
                    {
                        "horizon_minutes": 240,
                        "coverage_state": "complete",
                        "path_class": path,
                        "path_stats": {"terminal_return_bps": terminal},
                    }
                ]
            }
        },
    }


def test_episode_independence_uses_connected_overlapping_windows() -> None:
    result = episode_independence_diagnostics(
        [
            _match("a", "2025-01-01T00:00:00+00:00"),
            _match("b", "2025-01-01T01:00:00+00:00"),
            _match("c", "2025-01-01T03:00:00+00:00"),
            _match("d", "2025-01-01T08:00:00+00:00"),
        ]
    )
    assert result["distinct_independent_episodes"] == 2
    assert result["effective_n"] == "1.600000"
    assert result["effective_n_over_raw_n"] == "0.400000"
    assert result["max_episode_share"] == "0.750000"


def test_non_overlapping_matches_are_fully_independent_by_episode_rule() -> None:
    result = episode_independence_diagnostics(
        [
            _match("a", "2025-01-01T00:00:00+00:00"),
            _match("b", "2025-01-01T04:00:00+00:00"),
            _match("c", "2025-01-01T08:00:00+00:00"),
        ]
    )
    assert result["distinct_independent_episodes"] == 3
    assert result["effective_n"] == "3.000000"
    assert result["effective_n_over_raw_n"] == "1.000000"


def test_realized_dispersion_is_numeric_and_descriptive() -> None:
    result = realized_dispersion(
        [
            _match("a", "2025-01-01T00:00:00+00:00", "-10", "directional_down"),
            _match("b", "2025-01-02T00:00:00+00:00", "0", "quiet"),
            _match("c", "2025-01-03T00:00:00+00:00", "10", "directional_up"),
        ]
    )
    assert result["outcome_n_240m"] == 3
    assert result["terminal_return_stddev_bps"] == "8.164966"
    assert result["terminal_return_iqr_bps"] == "10.000000"
    assert result["terminal_return_mad_bps"] == "10.000000"
    assert result["unique_path_classes"] == 3


def test_frozen_manifest_rejects_missing_queries() -> None:
    try:
        freeze_query_manifest([{"query_id": "x"}])
    except ValueError as exc:
        assert "exactly 1000" in str(exc)
    else:
        raise AssertionError("Expected incomplete manifest to fail.")


def test_j1_median_excludes_no_comparable_cases_but_reports_coverage() -> None:
    rows = []
    for index in range(QUERY_COUNT):
        if index < 600:
            rows.append(
                {
                    "selected_raw_n": 0,
                    "effective_n_over_raw_n": None,
                    "effective_n": "0",
                    "candidate_raw_n": 10,
                    "distinct_independent_episodes": 0,
                    "episode_concentration_hhi": None,
                    "no_comparable_case": True,
                    "retrieval_evidence_state": "no_sufficient_similarity",
                }
            )
        else:
            rows.append(
                {
                    "selected_raw_n": 10,
                    "effective_n_over_raw_n": "0.400000",
                    "effective_n": "4",
                    "candidate_raw_n": 10,
                    "distinct_independent_episodes": 4,
                    "episode_concentration_hhi": "0.250000",
                    "no_comparable_case": False,
                    "retrieval_evidence_state": "matches_found",
                }
            )
    result = summarize_j1(rows)
    assert result["no_comparable_case_rate"] == "0.600000"
    assert result["median_effective_n_over_raw_n"] == "0.400000"
    assert result["stop_work_fired"] is True
    assert result["coverage_classification"] == "low_coverage_accepted"


def test_j16_never_grants_validation_clearance() -> None:
    rows = [
        {
            "dataset_grade": "insufficient",
            "outcome_n_240m": 3,
            "terminal_return_stddev_bps": "10",
            "terminal_return_iqr_bps": "8",
            "terminal_return_mad_bps": "5",
            "path_class_normalized_entropy": "0.8",
        }
        for _ in range(QUERY_COUNT)
    ]
    result = summarize_j16(rows)
    assert result["descriptive_baseline_only"] is True
    assert result["validation_clearance"] is False
    assert result["authoritative_retest_day"] == 38
    assert result["observed_grade_count"] == 1
