from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from hashlib import sha256
from typing import Any

from aidy.analogue_retrieval_v2 import (
    ANALOGUE_RETRIEVAL_VERSION_V2,
    verify_retrieval_digest_v2,
)
from aidy.context_packet import compute_context_hash
from aidy.evidence_grading_v2 import (
    EVIDENCE_REPORT_VERSION_V2,
    build_evidence_report_v2,
    compute_evidence_report_digest_v2,
)

CONTEXT_COMPOSER_VERSION_V2 = "aidy_context_composer_v2_symmetric_counter_first"
CONTEXT_DOSSIER_VERSION_V2 = "aidy_master_trader_context_dossier_v2"
COMPOSER_MANIFEST_VERSION = "aidy_context_composer_manifest_v2"
DIGEST_ALGORITHM = "sha256"

HYPOTHESIS_DIRECTIONS = ("long", "short", "none")
MANDATORY_PROMPT_SECTION_ORDER = (
    "counter_evidence",
    "support_evidence",
    "uncertainty",
    "invalidation_inputs",
)

_SECRET_KEYS = frozenset(
    {
        "api_key",
        "authorization",
        "client_secret",
        "cloudflare_api_token",
        "metaapi_token",
        "password",
        "private_key",
        "secret",
        "service_account_json",
        "telegram_bot_token",
    }
)
_RUNTIME_ACCOUNT_KEYS = frozenset(
    {
        "account",
        "account_balance",
        "account_equity",
        "broker",
        "broker_account",
        "equity",
        "follower",
        "follower_position",
        "leverage",
        "metaapi",
        "mt5",
        "position_size",
        "telegram",
        "vantage",
    }
)
_HIDDEN_REASONING_KEYS = frozenset(
    {
        "analysis",
        "chain_of_thought",
        "chainofthought",
        "hidden_reasoning",
        "reasoning_trace",
        "scratchpad",
        "thoughts",
    }
)
_RAW_FUTURE_KEYS = frozenset(
    {
        "counterfactual_digest",
        "future_evaluation",
        "future_return",
        "future_returns",
        "horizon_assessments",
        "mae",
        "mfe",
        "move_bundle",
        "outcome",
        "outcome_label",
        "outcome_state",
        "outcomes",
        "path_class",
        "pnl",
        "primary_classification",
        "realized_pnl",
        "shadow_outcome",
        "stop_hit",
        "target_hit",
        "trade_outcome_bundle",
    }
)
_SECRET_MARKERS = ("sk-", "bearer ", "-----begin private key-----")

_MOVE_SUPPORT = {
    "long": frozenset({"directional_up"}),
    "short": frozenset({"directional_down"}),
    "none": frozenset(),
}
_MOVE_COUNTER = {
    "long": frozenset({"directional_down"}),
    "short": frozenset({"directional_up"}),
    "none": frozenset(),
}
_TRADE_SUPPORT = frozenset({"target_only", "target_before_stop"})
_TRADE_COUNTER = frozenset({"stop_only", "stop_before_any_target"})

_OPTIONAL_TRIM_ORDER = (
    "optional_similarity_detail",
    "optional_state_detail",
    "optional_statistics_detail",
)


class ContextBudgetTooSmall(ValueError):
    """Raised when the requested budget cannot hold the mandatory dossier."""


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value: object) -> str:
    return sha256(canonical_json(value).encode()).hexdigest()


def _assert_safe_current(value: Any, *, path: str) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).strip().lower()
            if normalized in _SECRET_KEYS:
                raise ValueError(f"Secret-bearing field is forbidden at {path}.{key}.")
            if normalized in _RUNTIME_ACCOUNT_KEYS:
                raise ValueError(f"Runtime account field is forbidden at {path}.{key}.")
            if normalized in _HIDDEN_REASONING_KEYS:
                raise ValueError(f"Hidden reasoning field is forbidden at {path}.{key}.")
            if normalized in _RAW_FUTURE_KEYS:
                raise ValueError(f"Raw future/evaluation field is forbidden at {path}.{key}.")
            if normalized == "future_derived" and item is not False:
                raise ValueError(f"Future-derived current input is forbidden at {path}.{key}.")
            if normalized == "evaluation_only" and item is not False:
                raise ValueError(f"Evaluation-only current input is forbidden at {path}.{key}.")
            _assert_safe_current(item, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _assert_safe_current(item, path=f"{path}[{index}]")
    elif isinstance(value, str):
        lowered = value.strip().lower()
        if any(marker in lowered for marker in _SECRET_MARKERS):
            raise ValueError(f"Secret-like value is forbidden at {path}.")


def _context_snapshot(context: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(context, Mapping):
        raise TypeError("context must be a mapping.")
    snapshot = copy.deepcopy(dict(context))
    _assert_safe_current(snapshot, path="context")
    supplied = str(snapshot.get("context_hash") or "")
    if not supplied or supplied != compute_context_hash(snapshot):
        raise ValueError("Context Composer V2 requires a valid authenticated context hash.")
    if snapshot.get("objective_only") is not True:
        raise ValueError("Context Composer V2 requires objective_only current context.")
    if snapshot.get("retrospective_history_included") is not False:
        raise ValueError("Raw retrospective history is forbidden in current context.")
    if snapshot.get("broker_follower_state_included") is not False:
        raise ValueError("Broker/follower state is forbidden in current context.")
    return snapshot


def _validated_history(
    *, retrieval: Mapping[str, Any], evidence_report: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(retrieval, Mapping) or not isinstance(evidence_report, Mapping):
        raise TypeError("retrieval and evidence_report must be mappings.")
    retrieval_snapshot = copy.deepcopy(dict(retrieval))
    report_snapshot = copy.deepcopy(dict(evidence_report))
    if retrieval_snapshot.get("retrieval_version") != ANALOGUE_RETRIEVAL_VERSION_V2:
        raise ValueError("Context Composer V2 requires Day-24 independent-episode retrieval.")
    if not verify_retrieval_digest_v2(retrieval_snapshot):
        raise ValueError("Day-24 retrieval digest is invalid.")
    if report_snapshot.get("evidence_report_version") != EVIDENCE_REPORT_VERSION_V2:
        raise ValueError("Context Composer V2 requires Day-24 V2 evidence report.")
    supplied_report_digest = str(report_snapshot.get("report_digest") or "")
    if supplied_report_digest != compute_evidence_report_digest_v2(report_snapshot):
        raise ValueError("Day-24 evidence report digest is invalid.")
    rebuilt = build_evidence_report_v2(retrieval=retrieval_snapshot)
    if canonical_json(rebuilt) != canonical_json(report_snapshot):
        raise ValueError("Evidence report does not exactly bind the supplied retrieval.")
    if report_snapshot.get("source_retrieval_digest") != retrieval_snapshot.get(
        "retrieval_digest"
    ):
        raise ValueError("Evidence report retrieval identity mismatch.")
    if report_snapshot.get("source_selection_digest") != retrieval_snapshot.get(
        "selection_digest"
    ):
        raise ValueError("Evidence report selection identity mismatch.")
    return retrieval_snapshot, report_snapshot


def _hypothesis(value: str, setup_family: str | None) -> tuple[str, str | None]:
    direction = str(value).strip().lower()
    if direction not in HYPOTHESIS_DIRECTIONS:
        raise ValueError("hypothesis_direction must be long, short or none.")
    family = None if setup_family is None else str(setup_family).strip()
    if family == "":
        family = None
    if direction != "none" and family is None:
        raise ValueError("Directional hypothesis requires setup_family.")
    return direction, family


def _subset_counts(
    counts: Mapping[str, Any], *, labels: frozenset[str]
) -> dict[str, int]:
    result: dict[str, int] = {}
    for key, raw in sorted(counts.items()):
        if str(key) in labels:
            result[str(key)] = int(raw)
    return result


def _subset_rates(
    rates: Mapping[str, Any] | None, *, labels: frozenset[str]
) -> dict[str, Any] | None:
    if rates is None:
        return None
    return {str(key): rates[key] for key in sorted(rates) if str(key) in labels}


def _classifiers(statistic_name: str, direction: str) -> tuple[frozenset[str], frozenset[str]]:
    if statistic_name.startswith("move_path_class_"):
        return _MOVE_SUPPORT[direction], _MOVE_COUNTER[direction]
    if statistic_name.startswith("trade_outcome_state_"):
        return _TRADE_SUPPORT, _TRADE_COUNTER
    return frozenset(), frozenset()


def _symmetrical_evidence(
    *, report: Mapping[str, Any], direction: str, side: str
) -> list[dict[str, Any]]:
    if side not in {"support", "counter"}:
        raise ValueError("side must be support or counter.")
    rows: list[dict[str, Any]] = []
    for statistic in report["statistics"]:
        name = str(statistic["name"])
        support_labels, counter_labels = _classifiers(name, direction)
        labels = support_labels if side == "support" else counter_labels
        counts = statistic.get("counts")
        if not isinstance(counts, Mapping):
            raise TypeError("Day-24 statistic counts are malformed.")
        rates = statistic.get("rates")
        rates_map = rates if isinstance(rates, Mapping) else None
        rows.append(
            {
                "statistic_name": name,
                "statistic_digest": statistic["statistic_digest"],
                "effective_n": int(statistic["effective_n"]),
                "grade": statistic["grade"],
                "counts": _subset_counts(counts, labels=labels),
                "rates": _subset_rates(rates_map, labels=labels),
            }
        )
    return rows


def _uncertainty_counts(
    *, report: Mapping[str, Any], direction: str
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for statistic in report["statistics"]:
        name = str(statistic["name"])
        support_labels, counter_labels = _classifiers(name, direction)
        classified = support_labels | counter_labels
        counts = statistic.get("counts")
        if not isinstance(counts, Mapping):
            raise TypeError("Day-24 statistic counts are malformed.")
        rows.append(
            {
                "statistic_name": name,
                "unclassified_counts": {
                    str(key): int(raw)
                    for key, raw in sorted(counts.items())
                    if str(key) not in classified
                },
            }
        )
    return rows


def _evidence_section(
    *,
    side: str,
    rows: list[dict[str, Any]],
    retrieval: Mapping[str, Any],
    report: Mapping[str, Any],
) -> dict[str, Any]:
    grade = report["dataset_grade"]
    return {
        "side": side,
        "selection_digest": retrieval["selection_digest"],
        "retrieval_digest": retrieval["retrieval_digest"],
        "report_digest": report["report_digest"],
        "effective_n": int(report["effective_independent_n"]),
        "raw_n": int(report["pre_dedup_raw_n"]),
        "grade": grade["grade"],
        "grade_label": grade["grade_label"],
        "format_version": "aidy_symmetric_evidence_section_v1",
        "statistics": rows,
    }


def _failure_profile(
    *, report: Mapping[str, Any], setup_family: str | None
) -> dict[str, Any]:
    target = next(
        (
            item
            for item in report["statistics"]
            if item["name"] == "trade_outcome_state_240m"
        ),
        None,
    )
    if target is None:
        counts: dict[str, int] = {}
        effective_n = 0
        statistic_digest = None
    else:
        source_counts = target.get("counts")
        if not isinstance(source_counts, Mapping):
            raise ValueError("240m trade-outcome statistic counts are malformed.")
        failure_labels = _TRADE_COUNTER | frozenset({"neither", "same_minute_ambiguous"})
        counts = _subset_counts(source_counts, labels=failure_labels)
        effective_n = int(target["effective_n"])
        statistic_digest = target["statistic_digest"]
    return {
        "setup_family": setup_family,
        "source_statistic": "trade_outcome_state_240m",
        "source_statistic_digest": statistic_digest,
        "effective_n": effective_n,
        "failure_or_nonresolution_counts": counts,
    }


def _uncertainty(
    *, retrieval: Mapping[str, Any], report: Mapping[str, Any], direction: str
) -> dict[str, Any]:
    grade = report["dataset_grade"]
    metrics = grade["metrics"]
    return {
        "retrieval_evidence_state": retrieval["evidence_state"],
        "no_comparable_reason": retrieval.get("no_comparable_reason"),
        "effective_n": int(report["effective_independent_n"]),
        "raw_n": int(report["pre_dedup_raw_n"]),
        "effective_n_over_raw_n": metrics.get("effective_n_over_raw_n"),
        "grade": grade["grade"],
        "grade_label": grade["grade_label"],
        "next_grade": grade.get("next_grade"),
        "next_grade_blockers": list(grade.get("next_grade_blockers") or []),
        "probability_like_wording_allowed": bool(
            report["probability_like_wording_allowed"]
        ),
        "decision_weight_allowed": bool(report["decision_weight_allowed"]),
        "temporal_dispersion": {
            "temporal_span_days": metrics.get("temporal_span_days"),
            "unique_calendar_days": metrics.get("unique_calendar_days"),
            "unique_calendar_months": metrics.get("unique_calendar_months"),
            "newest_case_age_days": metrics.get("newest_case_age_days"),
            "max_calendar_day_share": metrics.get("max_calendar_day_share"),
            "max_calendar_month_share": metrics.get("max_calendar_month_share"),
        },
        "unclassified_aggregate_counts": _uncertainty_counts(
            report=report, direction=direction
        ),
    }


def _provenance(
    *, context: Mapping[str, Any], retrieval: Mapping[str, Any], report: Mapping[str, Any]
) -> dict[str, Any]:
    metrics = report["dataset_grade"]["metrics"]
    return {
        "context_packet_version": context["context_packet_version"],
        "context_hash": context["context_hash"],
        "source_contract_versions": copy.deepcopy(
            dict(context.get("source_contract_versions") or {})
        ),
        "retrieval_version": retrieval["retrieval_version"],
        "retrieval_digest": retrieval["retrieval_digest"],
        "selection_digest": retrieval["selection_digest"],
        "evidence_report_version": report["evidence_report_version"],
        "report_digest": report["report_digest"],
        "provenance_counts": copy.deepcopy(metrics.get("provenance_counts") or {}),
        "quality_counts": copy.deepcopy(metrics.get("quality_counts") or {}),
        "outcome_values_used_for_analogue_selection": False,
        "raw_future_evaluation_included": False,
    }


def _historical_state(
    *, retrieval: Mapping[str, Any], report: Mapping[str, Any]
) -> dict[str, Any]:
    state = str(retrieval["evidence_state"])
    comparable = state == "matches_found" and int(report["effective_independent_n"]) > 0
    return {
        "state": state,
        "comparable_history_available": comparable,
        "no_comparable_case": state == "no_comparable_case",
        "no_comparable_reason": retrieval.get("no_comparable_reason"),
        "historical_signal_invented": False,
    }


def _mandatory_bundle(
    *,
    context: Mapping[str, Any],
    aidy_state: Mapping[str, Any],
    retrieval: Mapping[str, Any],
    report: Mapping[str, Any],
    direction: str,
    setup_family: str | None,
    invalidation_inputs: Mapping[str, Any],
) -> dict[str, Any]:
    support_rows = _symmetrical_evidence(report=report, direction=direction, side="support")
    counter_rows = _symmetrical_evidence(report=report, direction=direction, side="counter")
    counter = _evidence_section(
        side="counter", rows=counter_rows, retrieval=retrieval, report=report
    )
    support = _evidence_section(
        side="support", rows=support_rows, retrieval=retrieval, report=report
    )
    uncertainty = _uncertainty(retrieval=retrieval, report=report, direction=direction)
    bundle = {
        "dossier_version": CONTEXT_DOSSIER_VERSION_V2,
        "composer_version": CONTEXT_COMPOSER_VERSION_V2,
        "symbol": context.get("symbol"),
        "as_of_utc": context.get("as_of_utc"),
        "hypothesis": {
            "direction": direction,
            "setup_family": setup_family,
        },
        "current_context_identity": {
            "context_packet_version": context["context_packet_version"],
            "context_hash": context["context_hash"],
        },
        "current_aidy_state": copy.deepcopy(dict(aidy_state)),
        "history_state": _historical_state(retrieval=retrieval, report=report),
        "counter_evidence": counter,
        "support_evidence": support,
        "setup_family_failure_profile": _failure_profile(
            report=report, setup_family=setup_family
        ),
        "uncertainty": uncertainty,
        "gate_relaxations": copy.deepcopy(list(retrieval.get("gate_relaxations") or [])),
        "invalidation_inputs": copy.deepcopy(dict(invalidation_inputs)),
        "provenance": _provenance(context=context, retrieval=retrieval, report=report),
        "prompt_section_order": list(MANDATORY_PROMPT_SECTION_ORDER),
        "prompt_sections": [
            {"name": "counter_evidence", "payload": counter},
            {"name": "support_evidence", "payload": support},
            {"name": "uncertainty", "payload": uncertainty},
            {
                "name": "invalidation_inputs",
                "payload": copy.deepcopy(dict(invalidation_inputs)),
            },
        ],
        "mandatory_fields_preserved": True,
        "raw_future_evaluation_included": False,
        "standalone_trade_decision_allowed": False,
    }
    return bundle


def _optional_detail(
    *,
    context: Mapping[str, Any],
    aidy_state: Mapping[str, Any],
    retrieval: Mapping[str, Any],
    report: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "optional_similarity_detail": {
            "candidate_count": retrieval.get("candidate_count"),
            "eligible_candidate_count": retrieval.get("eligible_candidate_count"),
            "hard_gate_pass_count": retrieval.get("hard_gate_pass_count"),
            "sufficient_match_count": retrieval.get("sufficient_match_count"),
            "returned_match_count": retrieval.get("returned_match_count"),
            "exclusion_counts": copy.deepcopy(retrieval.get("exclusion_counts") or {}),
        },
        "optional_state_detail": {
            "source_contract_versions": copy.deepcopy(
                dict(context.get("source_contract_versions") or {})
            ),
            "aidy_state_keys": sorted(str(key) for key in aidy_state),
        },
        "optional_statistics_detail": copy.deepcopy(list(report["statistics"])),
    }


def _apply_budget(
    mandatory: dict[str, Any], optional: dict[str, Any], max_bundle_bytes: int | None
) -> tuple[dict[str, Any], list[str]]:
    result = copy.deepcopy(mandatory)
    result.update(copy.deepcopy(optional))
    trimmed: list[str] = []
    if max_bundle_bytes is None:
        return result, trimmed
    if isinstance(max_bundle_bytes, bool) or not isinstance(max_bundle_bytes, int):
        raise TypeError("max_bundle_bytes must be an integer or null.")
    mandatory_size = len(canonical_json(mandatory).encode())
    if max_bundle_bytes < mandatory_size:
        raise ContextBudgetTooSmall(
            f"Budget {max_bundle_bytes} bytes cannot hold mandatory dossier ({mandatory_size} bytes)."
        )
    for key in _OPTIONAL_TRIM_ORDER:
        if len(canonical_json(result).encode()) <= max_bundle_bytes:
            break
        result.pop(key, None)
        trimmed.append(key)
    if len(canonical_json(result).encode()) > max_bundle_bytes:
        raise ContextBudgetTooSmall("Budget cannot hold mandatory dossier after optional trimming.")
    return result, trimmed


def compose_context_v2(
    *,
    context: Mapping[str, Any],
    aidy_state: Mapping[str, Any],
    retrieval: Mapping[str, Any],
    evidence_report: Mapping[str, Any],
    hypothesis_direction: str,
    setup_family: str | None,
    invalidation_inputs: Mapping[str, Any],
    max_bundle_bytes: int | None = None,
) -> dict[str, Any]:
    """Build the deterministic Day-35 counter-evidence-first model dossier."""

    current = _context_snapshot(context)
    if not isinstance(aidy_state, Mapping) or not isinstance(invalidation_inputs, Mapping):
        raise TypeError("aidy_state and invalidation_inputs must be mappings.")
    state = copy.deepcopy(dict(aidy_state))
    invalidation = copy.deepcopy(dict(invalidation_inputs))
    _assert_safe_current(state, path="aidy_state")
    _assert_safe_current(invalidation, path="invalidation_inputs")
    history, report = _validated_history(
        retrieval=retrieval, evidence_report=evidence_report
    )
    direction, family = _hypothesis(hypothesis_direction, setup_family)
    effective_n = int(report["effective_independent_n"])
    grade = report.get("dataset_grade")
    if not isinstance(grade, Mapping) or "grade" not in grade:
        raise ValueError("Day-24 evidence grade is mandatory.")
    if effective_n != int(grade.get("effective_n", -1)):
        raise ValueError("effective_n identity mismatch between report and grade.")
    if effective_n != int(history["independence"]["grading_effective_n"]):
        raise ValueError("effective_n identity mismatch between retrieval and report.")

    mandatory = _mandatory_bundle(
        context=current,
        aidy_state=state,
        retrieval=history,
        report=report,
        direction=direction,
        setup_family=family,
        invalidation_inputs=invalidation,
    )
    optional = _optional_detail(
        context=current,
        aidy_state=state,
        retrieval=history,
        report=report,
    )
    composed, trimmed = _apply_budget(mandatory, optional, max_bundle_bytes)
    composed["trimmed_optional_sections"] = trimmed
    composed["token_pressure_applied"] = bool(trimmed)
    _assert_safe_current(composed, path="composed_dossier")
    composed["dossier_digest"] = digest(composed)
    return composed


def verify_context_dossier_v2(dossier: Mapping[str, Any]) -> bool:
    if not isinstance(dossier, Mapping):
        return False
    supplied = str(dossier.get("dossier_digest") or "")
    body = copy.deepcopy(dict(dossier))
    body.pop("dossier_digest", None)
    try:
        _assert_safe_current(body, path="composed_dossier")
        if body.get("composer_version") != CONTEXT_COMPOSER_VERSION_V2:
            return False
        if body.get("dossier_version") != CONTEXT_DOSSIER_VERSION_V2:
            return False
        if body.get("prompt_section_order") != list(MANDATORY_PROMPT_SECTION_ORDER):
            return False
        sections = body.get("prompt_sections")
        if not isinstance(sections, list):
            return False
        if [item.get("name") for item in sections if isinstance(item, Mapping)] != list(
            MANDATORY_PROMPT_SECTION_ORDER
        ):
            return False
        counter = body.get("counter_evidence")
        support = body.get("support_evidence")
        if not isinstance(counter, Mapping) or not isinstance(support, Mapping):
            return False
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
            if counter.get(key) != support.get(key):
                return False
        if body.get("raw_future_evaluation_included") is not False:
            return False
    except (TypeError, ValueError):
        return False
    return bool(supplied) and supplied == digest(body)


def context_composer_manifest_v2() -> dict[str, Any]:
    manifest = {
        "manifest_version": COMPOSER_MANIFEST_VERSION,
        "composer_version": CONTEXT_COMPOSER_VERSION_V2,
        "dossier_version": CONTEXT_DOSSIER_VERSION_V2,
        "source_retrieval_version": ANALOGUE_RETRIEVAL_VERSION_V2,
        "source_evidence_report_version": EVIDENCE_REPORT_VERSION_V2,
        "digest_algorithm": DIGEST_ALGORITHM,
        "counter_evidence_first": True,
        "same_selection_identity_for_support_and_counter": True,
        "same_format_schema_for_support_and_counter": True,
        "effective_n_mandatory": True,
        "evidence_grade_mandatory": True,
        "no_comparable_case_first_class": True,
        "raw_future_evaluation_allowed_in_dossier": False,
        "validated_aggregate_statistics_only": True,
        "mandatory_fields_trimmable": False,
        "secrets_allowed": False,
        "runtime_account_state_allowed": False,
        "hidden_reasoning_allowed": False,
        "gateway_promoted_by_day35": False,
        "trading_gate_created_by_day35": False,
        "predictive_edge_claimed": False,
        "super_signals_modified": False,
    }
    manifest["manifest_digest"] = digest(manifest)
    return manifest
