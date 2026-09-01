from __future__ import annotations

import copy
import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256

import pytest

from aidy.analogue_retrieval import build_analogue_query
from aidy.analogue_retrieval_v2 import retrieve_analogues_v2
from aidy.context_composer_v2 import (
    CONTEXT_COMPOSER_VERSION_V2,
    MANDATORY_PROMPT_SECTION_ORDER,
    ContextBudgetTooSmall,
    canonical_json,
    compose_context_v2,
    context_composer_manifest_v2,
    digest,
    verify_context_dossier_v2,
)
from aidy.context_packet import compute_context_hash
from aidy.evidence_grading_v2 import build_evidence_report_v2
from aidy.feature_engine import FEATURE_DEFINITION_VERSION
from aidy.historical_backfill import RETROSPECTIVE_PROVENANCE
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

NOW = datetime(2026, 9, 1, 2, 45, tzinfo=UTC)
QUERY_TIME = datetime(2025, 1, 10, 12, tzinfo=UTC)


def _json_digest(value: object) -> str:
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def _features(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
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
    for key, value in overrides.items():
        if key.startswith("regime__"):
            payload["regime"][key.removeprefix("regime__")] = value  # type: ignore[index]
        else:
            payload[key] = value
    return payload


def _input(
    *,
    as_of: datetime,
    provenance: str,
    retrieval_eligible: bool = True,
) -> dict[str, object]:
    feature_values = _features()
    regime_labels = dict(feature_values["regime"])  # type: ignore[arg-type]
    packet: dict[str, object] = {
        "input_version": CASE_INPUT_VERSION,
        "replay_version": (
            "day35_fixture_replay_v1"
            if provenance == RETROSPECTIVE_PROVENANCE
            else None
        ),
        "symbol": "XAUUSD",
        "as_of_utc": as_of.isoformat(),
        "provenance_class": provenance,
        "pit_observed": provenance == PIT_OBSERVED_PROVENANCE,
        "retrospective_replay": provenance == RETROSPECTIVE_PROVENANCE,
        "future_derived": False,
        # Day-17 requires the input boundary to permit analogue matching. Query-level
        # insufficiency is represented independently by data_quality.retrieval_eligible.
        "analogue_match_allowed": True,
        "live_decision_input_allowed": provenance == PIT_OBSERVED_PROVENANCE,
        "feature": {
            "feature_definition_version": FEATURE_DEFINITION_VERSION,
            "feature_packet_digest": "f" * 64,
            "mode": "pit" if provenance == PIT_OBSERVED_PROVENANCE else "retrospective",
            "summary": {},
        },
        "regime": {
            (
                "regime_definition_version"
                if provenance == PIT_OBSERVED_PROVENANCE
                else "source_regime_definition_version"
            ): REGIME_DEFINITION_VERSION,
            "labels": regime_labels,
            "compound_regime_key": "fixture_regime",
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
            "quality_version": "day35_fixture_quality_v1",
            "grade": "strong" if retrieval_eligible else "insufficient",
            "retrieval_eligible": retrieval_eligible,
        },
        "analogue_features": feature_values,
        "evaluation_anchor": {
            "anchor_time_utc": as_of.isoformat(),
            "anchor_price": "2000",
            "forward_start_utc": as_of.isoformat(),
            "alignment_rule": "day35_fixture",
        },
        "provenance": {"source_provenance_class": provenance},
    }
    packet["input_digest"] = compute_case_input_digest(packet)
    return packet


def _case(*, as_of: datetime, path_class: str, outcome_state: str) -> dict[str, object]:
    boundary = _input(as_of=as_of, provenance=RETROSPECTIVE_PROVENANCE)
    case_id = _json_digest(
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
                    "path_class": path_class,
                    "path_stats": {"terminal_return_bps": "10"},
                }
            ]
        },
        "trade_outcome_bundle": {
            "outcomes": [
                {
                    "horizon_minutes": 240,
                    "coverage_state": "complete",
                    "outcome_state": outcome_state,
                }
            ]
        },
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


def _query(*, retrieval_eligible: bool = True) -> dict[str, object]:
    boundary = _input(
        as_of=QUERY_TIME,
        provenance=PIT_OBSERVED_PROVENANCE,
        retrieval_eligible=retrieval_eligible,
    )
    return build_analogue_query(
        input_boundary=boundary,
        allowed_provenance=(RETROSPECTIVE_PROVENANCE,),
        max_results=20,
    )


def _retrieval_and_report() -> tuple[dict[str, object], dict[str, object]]:
    candidates = [
        _case(
            as_of=QUERY_TIME - timedelta(days=8),
            path_class="directional_up",
            outcome_state="target_before_stop",
        ),
        _case(
            as_of=QUERY_TIME - timedelta(days=6),
            path_class="directional_down",
            outcome_state="stop_before_any_target",
        ),
        _case(
            as_of=QUERY_TIME - timedelta(days=4),
            path_class="quiet",
            outcome_state="neither",
        ),
    ]
    retrieval = retrieve_analogues_v2(query=_query(), candidate_cases=candidates)
    return retrieval, build_evidence_report_v2(retrieval=retrieval)


def _no_comparable() -> tuple[dict[str, object], dict[str, object]]:
    retrieval = retrieve_analogues_v2(query=_query(), candidate_cases=[])
    return retrieval, build_evidence_report_v2(retrieval=retrieval)


def _query_insufficient() -> tuple[dict[str, object], dict[str, object]]:
    query = _query(retrieval_eligible=False)
    assert query["query_retrieval_eligible"] is False
    retrieval = retrieve_analogues_v2(query=query, candidate_cases=[])
    return retrieval, build_evidence_report_v2(retrieval=retrieval)


def _context() -> dict[str, object]:
    context: dict[str, object] = {
        "context_packet_version": "aidy_market_context_v7_volatility_state",
        "as_of_utc": NOW.isoformat(),
        "symbol": "XAUUSD",
        "objective_only": True,
        "retrospective_history_included": False,
        "broker_follower_state_included": False,
        "source_contract_versions": {
            "pit_query": "aidy_pit_query_v1",
            "features": FEATURE_DEFINITION_VERSION,
            "setup": SETUP_DETECTOR_VERSION,
        },
        "gold": {"quote_context": {"mid": "2488.20"}},
        "market_structure": {"epoch": "epoch_fixture"},
    }
    context["context_hash"] = compute_context_hash(context)
    return context


def _aidy_state() -> dict[str, object]:
    return {
        "regime": {
            "trend_structure": "bullish_trend",
            "volatility_band": "normal",
            "session": "london_new_york_overlap",
        },
        "setup": {
            "detector_state": "single",
            "candidate_setup_ids": ["trend_momentum_long"],
        },
        "data_quality": {"state": "known", "quote_freshness": "fresh"},
    }


def _invalidation() -> dict[str, object]:
    return {
        "price_floor": "2478.00",
        "regime_must_remain": "bullish_trend",
        "event_window_clear": True,
    }


def _compose(
    *,
    retrieval: dict[str, object] | None = None,
    report: dict[str, object] | None = None,
    context: dict[str, object] | None = None,
    state: dict[str, object] | None = None,
    invalidation: dict[str, object] | None = None,
    max_bundle_bytes: int | None = None,
) -> dict[str, object]:
    if retrieval is None or report is None:
        retrieval, report = _retrieval_and_report()
    return compose_context_v2(
        context=_context() if context is None else context,
        aidy_state=_aidy_state() if state is None else state,
        retrieval=retrieval,
        evidence_report=report,
        hypothesis_direction="long",
        setup_family="trend_momentum",
        invalidation_inputs=_invalidation() if invalidation is None else invalidation,
        max_bundle_bytes=max_bundle_bytes,
    )


def _walk_keys(value: object) -> list[str]:
    keys: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            keys.append(str(key))
            keys.extend(_walk_keys(item))
    elif isinstance(value, list):
        for item in value:
            keys.extend(_walk_keys(item))
    return keys


def test_manifest_freezes_counter_first_and_no_leak_boundaries() -> None:
    manifest = context_composer_manifest_v2()
    assert manifest["composer_version"] == CONTEXT_COMPOSER_VERSION_V2
    assert manifest["counter_evidence_first"] is True
    assert manifest["same_selection_identity_for_support_and_counter"] is True
    assert manifest["same_format_schema_for_support_and_counter"] is True
    assert manifest["effective_n_mandatory"] is True
    assert manifest["evidence_grade_mandatory"] is True
    assert manifest["no_comparable_case_first_class"] is True
    assert manifest["raw_future_evaluation_allowed_in_dossier"] is False
    assert manifest["validated_aggregate_statistics_only"] is True
    assert manifest["gateway_promoted_by_day35"] is False
    assert manifest["trading_gate_created_by_day35"] is False
    assert manifest["predictive_edge_claimed"] is False
    assert manifest["super_signals_modified"] is False


def test_composer_is_deterministic_and_digest_stable() -> None:
    retrieval, report = _retrieval_and_report()
    first = _compose(retrieval=retrieval, report=report)
    second = _compose(retrieval=copy.deepcopy(retrieval), report=copy.deepcopy(report))
    assert first == second
    assert first["dossier_digest"] == second["dossier_digest"]
    assert verify_context_dossier_v2(first)


def test_counter_evidence_is_serialized_before_support() -> None:
    dossier = _compose()
    assert dossier["prompt_section_order"] == list(MANDATORY_PROMPT_SECTION_ORDER)
    assert [row["name"] for row in dossier["prompt_sections"]][:2] == [
        "counter_evidence",
        "support_evidence",
    ]


def test_support_and_counter_share_exact_selection_and_format_identity() -> None:
    dossier = _compose()
    counter = dossier["counter_evidence"]
    support = dossier["support_evidence"]
    for key in (
        "selection_digest",
        "retrieval_digest",
        "report_digest",
        "effective_n",
        "raw_n",
        "grade",
        "grade_label",
        "format_version",
    ):
        assert counter[key] == support[key]
    assert [row["statistic_name"] for row in counter["statistics"]] == [
        row["statistic_name"] for row in support["statistics"]
    ]


def test_aggregate_support_and_counter_are_visible_from_same_selection() -> None:
    dossier = _compose()
    support = next(
        row
        for row in dossier["support_evidence"]["statistics"]
        if row["statistic_name"] == "move_path_class_240m"
    )
    counter = next(
        row
        for row in dossier["counter_evidence"]["statistics"]
        if row["statistic_name"] == "move_path_class_240m"
    )
    assert support["counts"] == {"directional_up": 1}
    assert counter["counts"] == {"directional_down": 1}


def test_trade_outcome_aggregate_and_failure_profile_are_visible() -> None:
    dossier = _compose()
    support = next(
        row
        for row in dossier["support_evidence"]["statistics"]
        if row["statistic_name"] == "trade_outcome_state_240m"
    )
    counter = next(
        row
        for row in dossier["counter_evidence"]["statistics"]
        if row["statistic_name"] == "trade_outcome_state_240m"
    )
    assert support["counts"] == {"target_before_stop": 1}
    assert counter["counts"] == {"stop_before_any_target": 1}
    failure = dossier["setup_family_failure_profile"]
    assert failure["setup_family"] == "trend_momentum"
    assert failure["failure_or_nonresolution_counts"] == {
        "neither": 1,
        "stop_before_any_target": 1,
    }


def test_effective_n_grade_provenance_uncertainty_and_invalidation_are_mandatory() -> None:
    dossier = _compose()
    assert dossier["counter_evidence"]["effective_n"] == 3
    assert dossier["support_evidence"]["effective_n"] == 3
    assert dossier["uncertainty"]["effective_n"] == 3
    assert dossier["uncertainty"]["grade"] == "insufficient"
    assert "temporal_span_days" in dossier["uncertainty"]["temporal_dispersion"]
    assert dossier["provenance"]["provenance_counts"]
    assert dossier["invalidation_inputs"] == _invalidation()


def test_raw_historical_future_objects_never_enter_dossier() -> None:
    dossier = _compose()
    keys = set(_walk_keys(dossier))
    for forbidden in (
        "future_evaluation",
        "move_bundle",
        "trade_outcome_bundle",
        "mfe",
        "mae",
    ):
        assert forbidden not in keys
    assert dossier["raw_future_evaluation_included"] is False


def test_report_from_tampered_selection_is_rejected() -> None:
    retrieval, report = _retrieval_and_report()
    changed = copy.deepcopy(report)
    changed["effective_independent_n"] = 999
    changed["report_digest"] = digest(
        {key: value for key, value in changed.items() if key != "report_digest"}
    )
    with pytest.raises(ValueError, match="exactly bind"):
        _compose(retrieval=retrieval, report=changed)


def test_tampered_retrieval_digest_is_rejected() -> None:
    retrieval, report = _retrieval_and_report()
    changed = copy.deepcopy(retrieval)
    changed["returned_match_count"] = 999
    with pytest.raises(ValueError, match="retrieval digest"):
        _compose(retrieval=changed, report=report)


def test_no_comparable_case_is_honest_first_class_output() -> None:
    retrieval, report = _no_comparable()
    dossier = _compose(retrieval=retrieval, report=report)
    state = dossier["history_state"]
    assert state["state"] == "no_comparable_case"
    assert state["no_comparable_case"] is True
    assert state["comparable_history_available"] is False
    assert state["historical_signal_invented"] is False
    assert dossier["counter_evidence"]["effective_n"] == 0
    assert dossier["support_evidence"]["effective_n"] == 0


def test_query_insufficient_quality_is_honest_first_class_output() -> None:
    retrieval, report = _query_insufficient()
    dossier = _compose(retrieval=retrieval, report=report)
    assert retrieval["no_comparable_reason"] == "query_retrieval_eligible_false"
    assert dossier["history_state"]["state"] == "query_insufficient_quality"
    assert dossier["history_state"]["comparable_history_available"] is False
    assert dossier["history_state"]["historical_signal_invented"] is False
    assert dossier["uncertainty"]["effective_n"] == 0


def test_token_pressure_drops_optional_detail_not_mandatory_evidence() -> None:
    full = _compose()
    pre_final = copy.deepcopy(full)
    pre_final.pop("dossier_digest")
    pre_final.pop("trimmed_optional_sections")
    pre_final.pop("token_pressure_applied")
    pre_final_size = len(canonical_json(pre_final).encode())
    trimmed = _compose(max_bundle_bytes=pre_final_size - 1)
    assert trimmed["token_pressure_applied"] is True
    assert trimmed["trimmed_optional_sections"]
    for key in (
        "counter_evidence",
        "support_evidence",
        "uncertainty",
        "invalidation_inputs",
        "provenance",
        "gate_relaxations",
        "setup_family_failure_profile",
    ):
        assert key in trimmed
    assert trimmed["counter_evidence"]["effective_n"] == 3
    assert trimmed["support_evidence"]["grade"] == "insufficient"
    assert verify_context_dossier_v2(trimmed)


def test_budget_below_mandatory_floor_fails_instead_of_dropping_core_fields() -> None:
    with pytest.raises(ContextBudgetTooSmall, match="mandatory dossier"):
        _compose(max_bundle_bytes=1)


@pytest.mark.parametrize(
    "field",
    [
        "future_evaluation",
        "move_bundle",
        "trade_outcome_bundle",
        "realized_pnl",
        "mfe",
        "mae",
        "outcome_state",
    ],
)
def test_recursive_current_context_rejects_raw_future_fields(field: str) -> None:
    context = _context()
    context["nested"] = {"deeper": {field: "forbidden"}}
    context["context_hash"] = compute_context_hash(context)
    with pytest.raises(ValueError, match="Raw future/evaluation"):
        _compose(context=context)


@pytest.mark.parametrize(
    "field",
    ["api_key", "private_key", "chain_of_thought", "scratchpad"],
)
def test_recursive_state_rejects_secrets_and_hidden_reasoning(field: str) -> None:
    state = _aidy_state()
    state["nested"] = {"deeper": {field: "secret"}}
    with pytest.raises(ValueError, match="forbidden"):
        _compose(state=state)


@pytest.mark.parametrize(
    "field",
    [
        "account_balance",
        "broker",
        "metaapi",
        "mt5",
        "telegram",
        "vantage",
        "follower_position",
    ],
)
def test_recursive_invalidation_rejects_runtime_account_state(field: str) -> None:
    invalidation = _invalidation()
    invalidation["nested"] = {"deeper": {field: "runtime"}}
    with pytest.raises(ValueError, match="Runtime account"):
        _compose(invalidation=invalidation)


@pytest.mark.parametrize(
    "secret_value",
    ["sk-example-not-real", "Bearer example", "-----BEGIN PRIVATE KEY-----example"],
)
def test_recursive_secret_like_values_are_rejected(secret_value: str) -> None:
    state = _aidy_state()
    state["nested"] = {"value": secret_value}
    with pytest.raises(ValueError, match="Secret-like value"):
        _compose(state=state)


def test_invalid_context_hash_fails_closed() -> None:
    context = _context()
    context["context_hash"] = "0" * 64
    with pytest.raises(ValueError, match="authenticated context hash"):
        _compose(context=context)


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("objective_only", False, "objective_only"),
        ("retrospective_history_included", True, "Raw retrospective"),
        ("broker_follower_state_included", True, "Broker/follower"),
    ],
)
def test_context_boundary_flags_fail_closed(field: str, value: object, match: str) -> None:
    context = _context()
    context[field] = value
    context["context_hash"] = compute_context_hash(context)
    with pytest.raises(ValueError, match=match):
        _compose(context=context)


def test_directional_hypothesis_requires_setup_family() -> None:
    retrieval, report = _retrieval_and_report()
    with pytest.raises(ValueError, match="setup_family"):
        compose_context_v2(
            context=_context(),
            aidy_state=_aidy_state(),
            retrieval=retrieval,
            evidence_report=report,
            hypothesis_direction="long",
            setup_family=None,
            invalidation_inputs=_invalidation(),
        )


def test_short_hypothesis_reverses_directional_move_support_and_counter() -> None:
    retrieval, report = _retrieval_and_report()
    dossier = compose_context_v2(
        context=_context(),
        aidy_state=_aidy_state(),
        retrieval=retrieval,
        evidence_report=report,
        hypothesis_direction="short",
        setup_family="trend_momentum",
        invalidation_inputs=_invalidation(),
    )
    support = next(
        row
        for row in dossier["support_evidence"]["statistics"]
        if row["statistic_name"] == "move_path_class_240m"
    )
    counter = next(
        row
        for row in dossier["counter_evidence"]["statistics"]
        if row["statistic_name"] == "move_path_class_240m"
    )
    assert support["counts"] == {"directional_down": 1}
    assert counter["counts"] == {"directional_up": 1}


def test_none_hypothesis_does_not_invent_directional_move_evidence() -> None:
    retrieval, report = _retrieval_and_report()
    dossier = compose_context_v2(
        context=_context(),
        aidy_state=_aidy_state(),
        retrieval=retrieval,
        evidence_report=report,
        hypothesis_direction="none",
        setup_family=None,
        invalidation_inputs=_invalidation(),
    )
    support = next(
        row
        for row in dossier["support_evidence"]["statistics"]
        if row["statistic_name"] == "move_path_class_240m"
    )
    counter = next(
        row
        for row in dossier["counter_evidence"]["statistics"]
        if row["statistic_name"] == "move_path_class_240m"
    )
    assert support["counts"] == {}
    assert counter["counts"] == {}
    assert dossier["hypothesis"] == {"direction": "none", "setup_family": None}


def test_invalid_hypothesis_direction_is_rejected() -> None:
    retrieval, report = _retrieval_and_report()
    with pytest.raises(ValueError, match="long, short or none"):
        compose_context_v2(
            context=_context(),
            aidy_state=_aidy_state(),
            retrieval=retrieval,
            evidence_report=report,
            hypothesis_direction="maybe",
            setup_family="trend_momentum",
            invalidation_inputs=_invalidation(),
        )
