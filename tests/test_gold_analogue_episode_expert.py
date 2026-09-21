from __future__ import annotations

import copy
import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256

import pytest

from aidy.analogue_retrieval import build_analogue_query
from aidy.analogue_retrieval_v3 import retrieve_analogues_v3
from aidy.feature_engine import FEATURE_DEFINITION_VERSION
from aidy.gold_analogue_episode_expert import (
    ANALOGUE_EPISODE_EXPERT_VERSION,
    build_analogue_episode_expert,
    build_episode_state_snapshot,
    rerank_independent_analogues,
    score_episode_state_similarity,
    summarise_chronological_holdout,
)
from aidy.gold_cycle_environment import build_cycle_environment
from aidy.gold_expert_gate_contract import verify_expert_gate_packet
from aidy.historical_backfill import RETROSPECTIVE_PROVENANCE
from aidy.historical_case_context_v2 import enrich_historical_case_with_market_structure
from aidy.historical_cases import (
    CASE_DIGEST_ALGORITHM,
    CASE_INPUT_VERSION,
    CASE_VERSION,
    PIT_OBSERVED_PROVENANCE,
    compute_case_input_digest,
    compute_historical_case_digest,
)
from aidy.regime_classifier import REGIME_DEFINITION_VERSION
from aidy.setup_detector import SETUP_DETECTOR_VERSION, SETUP_TAXONOMY_VERSION

AS_OF = datetime(2025, 1, 20, 12, tzinfo=UTC)


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value: object) -> str:
    return sha256(_canonical_json(value).encode()).hexdigest()


def _features() -> dict[str, object]:
    return {
        "regime": {
            "trend_structure": "bullish_trend",
            "volatility_band": "normal",
            "session": "london_new_york_overlap",
            "quote_spread_condition": "fresh_quote_spread_unknown",
            "event_timing": "clear_current_window",
        },
        "m15_direction": "bullish",
        "h1_direction": "bullish",
        "h4_direction": "bullish",
        "h1_atr_14_bps": "35",
        "m15_realized_vol_20_bps": "22",
        "m15_range_position_20": "0.72",
        "m15_close_location": "0.68",
        "session_range_position": "0.66",
        "setup_detector_state": "single",
        "candidate_setup_ids": ["trend_momentum_long"],
    }


def _input(*, as_of: datetime, provenance: str) -> dict[str, object]:
    features = _features()
    labels = dict(features["regime"])  # type: ignore[arg-type]
    boundary: dict[str, object] = {
        "input_version": CASE_INPUT_VERSION,
        "replay_version": "build19_fixture_v1"
        if provenance == RETROSPECTIVE_PROVENANCE
        else None,
        "symbol": "XAUUSD",
        "as_of_utc": as_of.isoformat(),
        "provenance_class": provenance,
        "pit_observed": provenance == PIT_OBSERVED_PROVENANCE,
        "retrospective_replay": provenance == RETROSPECTIVE_PROVENANCE,
        "future_derived": False,
        "analogue_match_allowed": True,
        "live_decision_input_allowed": provenance == PIT_OBSERVED_PROVENANCE,
        "feature": {
            "feature_definition_version": FEATURE_DEFINITION_VERSION,
            "feature_packet_digest": "f" * 64,
            "mode": "pit"
            if provenance == PIT_OBSERVED_PROVENANCE
            else "retrospective",
            "summary": {},
        },
        "regime": {
            (
                "regime_definition_version"
                if provenance == PIT_OBSERVED_PROVENANCE
                else "source_regime_definition_version"
            ): REGIME_DEFINITION_VERSION,
            "labels": labels,
            "compound_regime_key": "|".join(
                f"{key}={value}" for key, value in labels.items()
            ),
        },
        "setup": {
            (
                "taxonomy_version"
                if provenance == PIT_OBSERVED_PROVENANCE
                else "source_taxonomy_version"
            ): SETUP_TAXONOMY_VERSION,
            (
                "detector_version"
                if provenance == PIT_OBSERVED_PROVENANCE
                else "source_detector_version"
            ): SETUP_DETECTOR_VERSION,
            "detector_state": "single",
            "candidate_setup_ids": ["trend_momentum_long"],
            "candidate_directions": ["long"],
            "unresolved_setup_ids": [],
        },
        "normalized_trade_spec": None,
        "data_quality": {
            "quality_version": "build19_fixture_quality_v1",
            "grade": "strong",
            "retrieval_eligible": True,
        },
        "analogue_features": features,
        "evaluation_anchor": {
            "anchor_time_utc": as_of.isoformat(),
            "anchor_price": "2000",
            "forward_start_utc": as_of.isoformat(),
            "alignment_rule": "build19_fixture",
        },
        "provenance": {"source_provenance_class": provenance},
    }
    boundary["input_digest"] = compute_case_input_digest(boundary)
    return boundary


def _case(
    *,
    as_of: datetime,
    terminal_return_bps: str,
) -> dict[str, object]:
    boundary = _input(as_of=as_of, provenance=RETROSPECTIVE_PROVENANCE)
    case_id = _digest(
        {
            "case_version": CASE_VERSION,
            "symbol": "XAUUSD",
            "as_of_utc": boundary["as_of_utc"],
            "provenance_class": RETROSPECTIVE_PROVENANCE,
            "input_digest": boundary["input_digest"],
        }
    )
    end = as_of + timedelta(minutes=240)
    future = {
        "evaluation_only": True,
        "future_derived": True,
        "pit_eligible": False,
        "decision_input_allowed": False,
        "analogue_match_allowed": False,
        "available_after_utc": end.isoformat(),
        "move_bundle": {
            "labels": [
                {
                    "horizon_minutes": 240,
                    "coverage_state": "complete",
                    "anchor_time_utc": as_of.isoformat(),
                    "horizon_end_utc": end.isoformat(),
                    "path_class": "build19_fixture",
                    "path_stats": {
                        "terminal_return_bps": terminal_return_bps,
                    },
                }
            ]
        },
        "trade_outcome_bundle": None,
        "no_trade_counterfactual": None,
        "causal_claims_included": False,
    }
    case: dict[str, object] = {
        "case_version": CASE_VERSION,
        "case_digest_algorithm": CASE_DIGEST_ALGORITHM,
        "case_id": case_id,
        "symbol": "XAUUSD",
        "as_of_utc": boundary["as_of_utc"],
        "provenance_class": RETROSPECTIVE_PROVENANCE,
        "decision_input_allowed": False,
        "analogue_query_must_use_input_boundary_only": True,
        "input_boundary": boundary,
        "future_evaluation": future,
    }
    case["case_digest"] = compute_historical_case_digest(case)
    return case


def _query() -> dict[str, object]:
    return build_analogue_query(
        input_boundary=_input(as_of=AS_OF, provenance=PIT_OBSERVED_PROVENANCE),
        allowed_provenance=(RETROSPECTIVE_PROVENANCE,),
        max_results=50,
    )


def _environment() -> dict:
    return build_cycle_environment(
        as_of_utc=AS_OF,
        target_window_start_utc=AS_OF + timedelta(minutes=15),
        session_code="london_new_york_overlap",
        observed_state="bullish",
        gold_state={
            "market_structure": {
                "timeframes": {
                    "M5": {"net_close_direction": "up", "state": "known"},
                    "M15": {"net_close_direction": "up", "state": "known"},
                    "H1": {"net_close_direction": "up", "state": "known"},
                    "H4": {"net_close_direction": "up", "state": "known"},
                    "D1": {"net_close_direction": "up", "state": "known"},
                }
            },
            "move_observation": {
                "five_minute_distribution_state": "within_recent_distribution",
                "five_minute_range_state": "normal_range",
                "windows": {
                    "5m": {"direction": "up", "return_bps": "2"},
                    "15m": {"direction": "up", "return_bps": "4"},
                    "60m": {"direction": "up", "return_bps": "6"},
                },
            },
            "volatility": {
                "state": "normal",
                "jump_continuous": {"state": "continuous_dominant"},
            },
            "scheduled_event_risk": {
                "state": "known",
                "timing_state": "outside_near_event_window",
            },
        },
        semantic_context={
            "data_quality": {
                "quote_state": "known",
                "quote_freshness": "fresh",
                "spread_state": "unknown",
            },
            "cross_market": {"series": {}},
        },
        regime={"compound_regime_key": "trend|normal"},
    )


def _gates(
    *,
    conclusion: str = "bullish",
    observed_at: datetime = AS_OF,
) -> dict[str, dict[str, object]]:
    return {
        "m15_price_structure_expert": {
            "state": "known",
            "conclusion": conclusion,
            "available": True,
            "observed_at_utc": observed_at.isoformat(),
        },
        "momentum_impulse_expert": {
            "state": "known",
            "conclusion": conclusion,
            "available": True,
            "observed_at_utc": observed_at.isoformat(),
        },
    }


def _env_state(*, session: str = "london_new_york_overlap") -> dict[str, str]:
    return {
        "session": session,
        "session_phase": "overlap",
        "volatility_state": "normal",
        "event_timing_state": "outside_near_event_window",
        "compound_regime": "trend|normal",
    }


def _query_snapshot(query: dict[str, object]) -> dict:
    return build_episode_state_snapshot(
        identity=str(query["query_id"]),
        input_digest=str(query["source_input_digest"]),
        as_of_utc=AS_OF,
        gate_states=_gates(),
        environment=_env_state(),
    )


def _candidate_snapshots(cases: list[dict[str, object]]) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for source in cases:
        enriched = enrich_historical_case_with_market_structure(case=source)
        source_id = str(source["case_id"])
        as_of = datetime.fromisoformat(str(source["as_of_utc"]))
        result[source_id] = build_episode_state_snapshot(
            identity=source_id,
            input_digest=str(enriched["input_boundary"]["input_digest"]),
            as_of_utc=as_of,
            gate_states=_gates(observed_at=as_of),
            environment=_env_state(),
        )
    return result


def _retrieval(cases: list[dict[str, object]]) -> tuple[dict, dict]:
    query = _query()
    return (
        retrieve_analogues_v3(query=query, candidate_cases=cases),
        query,
    )


def test_build19_state_snapshot_is_exact_and_outcome_free() -> None:
    query = _query()
    snapshot = _query_snapshot(query)

    assert snapshot["identity"] == query["query_id"]
    assert snapshot["input_digest"] == query["source_input_digest"]
    assert snapshot["future_values_used"] is False
    assert snapshot["outcome_fields_used"] is False
    assert snapshot["snapshot_digest"]


def test_build19_state_snapshot_rejects_outcome_injection() -> None:
    with pytest.raises(ValueError):
        build_episode_state_snapshot(
            identity="query",
            input_digest="a" * 64,
            as_of_utc=AS_OF,
            gate_states={
                "m15": {
                    "state": "known",
                    "conclusion": "bullish",
                    "outcome": "winner",
                }
            },
            environment=_env_state(),
        )


def test_build19_state_snapshot_rejects_future_gate_observation() -> None:
    with pytest.raises(ValueError, match="observed after"):
        build_episode_state_snapshot(
            identity="query",
            input_digest="a" * 64,
            as_of_utc=AS_OF,
            gate_states=_gates(observed_at=AS_OF + timedelta(seconds=1)),
            environment=_env_state(),
        )


def test_build19_gate_and_environment_similarity_are_explicit() -> None:
    query = build_episode_state_snapshot(
        identity="query",
        input_digest="q" * 64,
        as_of_utc=AS_OF,
        gate_states=_gates(),
        environment=_env_state(),
    )
    candidate = build_episode_state_snapshot(
        identity="candidate",
        input_digest="c" * 64,
        as_of_utc=AS_OF - timedelta(days=1),
        gate_states=_gates(observed_at=AS_OF - timedelta(days=1)),
        environment=_env_state(),
    )
    score = score_episode_state_similarity(
        base_similarity="0.80",
        query_snapshot=query,
        candidate_snapshot=candidate,
    )

    assert score["base_similarity"] == "0.800000"
    assert score["gate_state_similarity"] == "1.000000"
    assert score["environment_similarity"] == "1.000000"
    assert score["combined_similarity"] == "0.900000"
    assert score["outcomes_used_for_similarity"] is False


def test_build19_positive_and_counterexample_retrieval_are_symmetric() -> None:
    cases = [
        _case(
            as_of=datetime(2025, 1, 2, 0, tzinfo=UTC),
            terminal_return_bps="20",
        ),
        _case(
            as_of=datetime(2025, 1, 3, 0, tzinfo=UTC),
            terminal_return_bps="-15",
        ),
    ]
    retrieval, query = _retrieval(cases)
    result = rerank_independent_analogues(
        historical_retrieval_v3=retrieval,
        query_snapshot=_query_snapshot(query),
        candidate_snapshots_by_source_case_id=_candidate_snapshots(cases),
        reference_direction="bullish",
    )

    assert result["selected_episode_n"] == 2
    assert result["distribution"]["continuation_n"] == 1
    assert result["distribution"]["retrace_n"] == 1
    assert len(result["supporting_analogues"]) == 1
    assert len(result["counterexample_analogues"]) == 1
    assert result["counterexamples_preserved"] is True


def test_build19_future_outcome_change_cannot_change_selection_or_similarity() -> None:
    stamp = datetime(2025, 1, 2, 0, tzinfo=UTC)
    winner = _case(as_of=stamp, terminal_return_bps="100")
    loser = _case(as_of=stamp, terminal_return_bps="-100")
    query = _query()
    snapshots = _candidate_snapshots([winner])

    left = rerank_independent_analogues(
        historical_retrieval_v3=retrieve_analogues_v3(
            query=query,
            candidate_cases=[winner],
        ),
        query_snapshot=_query_snapshot(query),
        candidate_snapshots_by_source_case_id=snapshots,
        reference_direction="bullish",
    )
    right = rerank_independent_analogues(
        historical_retrieval_v3=retrieve_analogues_v3(
            query=query,
            candidate_cases=[loser],
        ),
        query_snapshot=_query_snapshot(query),
        candidate_snapshots_by_source_case_id=snapshots,
        reference_direction="bullish",
    )

    assert left["matches"][0]["source_case_id"] == right["matches"][0]["source_case_id"]
    assert left["matches"][0]["state_similarity"] == right["matches"][0]["state_similarity"]
    assert left["matches"][0]["post_selection_outcome"] != right["matches"][0]["post_selection_outcome"]


def test_build19_duplicate_overlapping_historical_cases_collapse_to_one_episode() -> None:
    first = _case(
        as_of=datetime(2025, 1, 2, 0, tzinfo=UTC),
        terminal_return_bps="20",
    )
    second = _case(
        as_of=datetime(2025, 1, 2, 1, tzinfo=UTC),
        terminal_return_bps="-10",
    )
    retrieval, query = _retrieval([first, second])
    assert retrieval["retrieval"]["independence"]["pre_dedup_raw_n"] == 2
    assert retrieval["retrieval"]["independence"]["distinct_independent_episodes"] == 1

    result = rerank_independent_analogues(
        historical_retrieval_v3=retrieval,
        query_snapshot=_query_snapshot(query),
        candidate_snapshots_by_source_case_id=_candidate_snapshots([first, second]),
        reference_direction="bullish",
    )
    assert result["selected_episode_n"] == 1
    assert result["duplicate_episodes_already_collapsed_by_v2"] is True


def test_build19_candidate_snapshot_must_bind_exact_input_digest() -> None:
    case = _case(
        as_of=datetime(2025, 1, 2, 0, tzinfo=UTC),
        terminal_return_bps="20",
    )
    retrieval, query = _retrieval([case])
    snapshots = _candidate_snapshots([case])
    snapshots[str(case["case_id"])] = {
        **snapshots[str(case["case_id"])],
        "input_digest": "0" * 64,
    }
    body = dict(snapshots[str(case["case_id"])])
    body.pop("snapshot_digest", None)
    snapshots[str(case["case_id"])]["snapshot_digest"] = _digest(body)

    with pytest.raises(ValueError, match="input digest mismatch"):
        rerank_independent_analogues(
            historical_retrieval_v3=retrieval,
            query_snapshot=_query_snapshot(query),
            candidate_snapshots_by_source_case_id=snapshots,
            reference_direction="bullish",
        )


def test_build19_chronological_holdout_ignores_dev_and_validation_rows() -> None:
    rows = [
        {"split": "development", "independent_episode_id": "dev-1"},
        {"split": "validation", "independent_episode_id": "val-1"},
        {"split": "holdout", "independent_episode_id": "hold-1"},
        {"split": "holdout", "independent_episode_id": "hold-2"},
    ]
    summary = summarise_chronological_holdout(
        rows,
        split_binding={
            "manifest_version": "aidy_chronological_split_manifest_v1",
            "purge_required": True,
            "embargo_required": True,
            "holdout_tuning_allowed": False,
        },
    )

    assert summary["holdout_independent_episode_n"] == 2
    assert summary["development_rows_used_for_holdout_score"] is False
    assert summary["validation_rows_used_for_holdout_score"] is False
    assert summary["chronological_holdout_only"] is True


def test_build19_holdout_tuning_is_rejected() -> None:
    with pytest.raises(ValueError, match="forbids holdout tuning"):
        summarise_chronological_holdout(
            [{"split": "holdout", "independent_episode_id": "h-1"}],
            split_binding={
                "manifest_version": "aidy_chronological_split_manifest_v1",
                "purge_required": True,
                "embargo_required": True,
                "holdout_tuning_allowed": True,
            },
        )


def test_build19_expert_is_context_only_and_counterexamples_are_visible() -> None:
    cases = [
        _case(
            as_of=datetime(2025, 1, 2, 0, tzinfo=UTC),
            terminal_return_bps="20",
        ),
        _case(
            as_of=datetime(2025, 1, 3, 0, tzinfo=UTC),
            terminal_return_bps="-20",
        ),
    ]
    retrieval, query = _retrieval(cases)
    result = build_analogue_episode_expert(
        global_environment=_environment(),
        historical_retrieval_v3=retrieval,
        query_snapshot=_query_snapshot(query),
        candidate_snapshots_by_source_case_id=_candidate_snapshots(cases),
        reference_direction="bullish",
    )
    packet = result["expert_packet"]

    assert result["expert_version"] == ANALOGUE_EPISODE_EXPERT_VERSION
    assert packet["gate_mode"] == "context_only"
    assert packet["conclusion"] == "context_only"
    assert packet["gate_scoreable"] is False
    assert result["historical_analogues"]["distribution"]["continuation_n"] == 1
    assert result["historical_analogues"]["distribution"]["retrace_n"] == 1
    assert result["counterexamples_preserved"] is True
    assert result["outcomes_used_for_similarity"] is False
    assert result["live_money_execution_allowed"] is False
    assert verify_expert_gate_packet(packet)


def test_build19_expert_packet_does_not_embed_future_evaluation_payloads() -> None:
    case = _case(
        as_of=datetime(2025, 1, 2, 0, tzinfo=UTC),
        terminal_return_bps="20",
    )
    retrieval, query = _retrieval([case])
    result = build_analogue_episode_expert(
        global_environment=_environment(),
        historical_retrieval_v3=retrieval,
        query_snapshot=_query_snapshot(query),
        candidate_snapshots_by_source_case_id=_candidate_snapshots([case]),
        reference_direction="bullish",
    )

    packet_text = _canonical_json(result["expert_packet"])
    assert "future_evaluation" not in packet_text
    assert "post_selection_outcome" not in packet_text
    assert result["historical_analogues"]["matches"][0]["post_selection_outcome"]


def test_build19_selection_is_deterministic_under_candidate_reordering() -> None:
    cases = [
        _case(
            as_of=datetime(2025, 1, 2, 0, tzinfo=UTC),
            terminal_return_bps="20",
        ),
        _case(
            as_of=datetime(2025, 1, 3, 0, tzinfo=UTC),
            terminal_return_bps="-15",
        ),
    ]
    query = _query()
    snapshots = _candidate_snapshots(cases)
    left = rerank_independent_analogues(
        historical_retrieval_v3=retrieve_analogues_v3(
            query=query,
            candidate_cases=cases,
        ),
        query_snapshot=_query_snapshot(query),
        candidate_snapshots_by_source_case_id=snapshots,
        reference_direction="bullish",
    )
    right = rerank_independent_analogues(
        historical_retrieval_v3=retrieve_analogues_v3(
            query=query,
            candidate_cases=list(reversed(cases)),
        ),
        query_snapshot=_query_snapshot(query),
        candidate_snapshots_by_source_case_id=snapshots,
        reference_direction="bullish",
    )

    assert [
        item["source_case_id"] for item in left["matches"]
    ] == [
        item["source_case_id"] for item in right["matches"]
    ]
    assert [
        item["state_similarity"] for item in left["matches"]
    ] == [
        item["state_similarity"] for item in right["matches"]
    ]


def test_build19_tampered_v3_retrieval_is_rejected() -> None:
    case = _case(
        as_of=datetime(2025, 1, 2, 0, tzinfo=UTC),
        terminal_return_bps="20",
    )
    retrieval, query = _retrieval([case])
    tampered = copy.deepcopy(retrieval)
    tampered["query_market_structure_epoch"] = "tampered"

    with pytest.raises(ValueError, match="verified v3"):
        rerank_independent_analogues(
            historical_retrieval_v3=tampered,
            query_snapshot=_query_snapshot(query),
            candidate_snapshots_by_source_case_id=_candidate_snapshots([case]),
            reference_direction="bullish",
        )
