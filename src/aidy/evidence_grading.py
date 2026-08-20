from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from hashlib import sha256
from typing import Any

from aidy.analogue_retrieval import (
    ANALOGUE_RETRIEVAL_VERSION,
    SIMILARITY_FEATURE_VERSION,
)

EVIDENCE_GRADE_VERSION = "aidy_evidence_grade_v1"
EVIDENCE_REPORT_VERSION = "aidy_analogue_evidence_report_v1"
EVIDENCE_STATISTIC_VERSION = "aidy_evidence_statistic_v1"
EVIDENCE_DIGEST_ALGORITHM = "sha256"

GRADE_INSUFFICIENT = "insufficient"
GRADE_EXPLORATORY = "exploratory"
GRADE_MODERATE = "moderate_evidence"
GRADE_ESTABLISHED = "established_dataset"

GRADE_ORDER = (
    GRADE_INSUFFICIENT,
    GRADE_EXPLORATORY,
    GRADE_MODERATE,
    GRADE_ESTABLISHED,
)
GRADE_LABELS = {
    GRADE_INSUFFICIENT: "INSUFFICIENT",
    GRADE_EXPLORATORY: "EXPLORATORY",
    GRADE_MODERATE: "MODERATE EVIDENCE",
    GRADE_ESTABLISHED: "ESTABLISHED DATASET",
}

QUALITY_SCORES = {
    "strong": Decimal("1.00"),
    "moderate": Decimal("0.80"),
    "limited": Decimal("0.60"),
    "insufficient": Decimal("0.00"),
}

_GRADE_RULES: dict[str, dict[str, Decimal | int]] = {
    GRADE_EXPLORATORY: {
        "min_n": 10,
        "min_mean_similarity": Decimal("0.72"),
        "min_p25_similarity": Decimal("0.68"),
        "min_mean_component_coverage": Decimal("0.65"),
        "min_mean_input_quality": Decimal("0.65"),
        "min_move_240_complete_ratio": Decimal("0.80"),
        "min_temporal_span_days": Decimal(7),
        "min_unique_calendar_days": 4,
        "max_newest_case_age_days": Decimal(365),
        "max_calendar_day_share": Decimal("0.50"),
    },
    GRADE_MODERATE: {
        "min_n": 30,
        "min_mean_similarity": Decimal("0.78"),
        "min_p25_similarity": Decimal("0.72"),
        "min_mean_component_coverage": Decimal("0.75"),
        "min_mean_input_quality": Decimal("0.75"),
        "min_move_240_complete_ratio": Decimal("0.90"),
        "min_temporal_span_days": Decimal(30),
        "min_unique_calendar_days": 12,
        "min_unique_calendar_months": 2,
        "max_newest_case_age_days": Decimal(180),
        "max_calendar_day_share": Decimal("0.20"),
        "max_calendar_month_share": Decimal("0.80"),
    },
    GRADE_ESTABLISHED: {
        "min_n": 100,
        "min_mean_similarity": Decimal("0.82"),
        "min_p25_similarity": Decimal("0.76"),
        "min_mean_component_coverage": Decimal("0.82"),
        "min_mean_input_quality": Decimal("0.85"),
        "min_move_240_complete_ratio": Decimal("0.95"),
        "min_temporal_span_days": Decimal(180),
        "min_unique_calendar_days": 45,
        "min_unique_calendar_months": 6,
        "max_newest_case_age_days": Decimal(90),
        "max_calendar_day_share": Decimal("0.10"),
        "max_calendar_month_share": Decimal("0.30"),
    },
}


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value: object) -> str:
    return sha256(_canonical_json(value).encode()).hexdigest()


def _utc(value: datetime | str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"Invalid evidence timestamp: {value}") from exc
    else:
        raise TypeError("Evidence timestamps must be timezone-aware datetime or ISO-8601 text.")
    if parsed.tzinfo is None:
        raise ValueError("Evidence timestamps must be timezone-aware.")
    return parsed.astimezone(UTC)


def _decimal(value: Any, *, name: str) -> Decimal:
    if value is None or isinstance(value, bool):
        raise TypeError(f"{name} must be a finite decimal.")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{name} must be a finite decimal.") from exc
    if not parsed.is_finite():
        raise ValueError(f"{name} must be a finite decimal.")
    return parsed


def _score(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP))


def _ratio(numerator: int, denominator: int) -> Decimal:
    return Decimal(0) if denominator <= 0 else Decimal(numerator) / Decimal(denominator)


def _mean(values: list[Decimal]) -> Decimal:
    return Decimal(0) if not values else sum(values, Decimal(0)) / Decimal(len(values))


def _p25(values: list[Decimal]) -> Decimal:
    if not values:
        return Decimal(0)
    ordered = sorted(values)
    index = (len(ordered) - 1) * 25 // 100
    return ordered[index]


def _retrieval_digest(retrieval: Mapping[str, Any]) -> str:
    body = dict(retrieval)
    body.pop("retrieval_digest", None)
    return _digest(body)


def _selection_digest(query_id: str, matches: list[Mapping[str, Any]]) -> str:
    selection = [
        {
            "rank": item["rank"],
            "case_id": item["case_id"],
            "similarity_score": item["similarity"]["similarity_score"],
            "component_coverage": item["similarity"]["component_coverage"],
        }
        for item in matches
    ]
    return _digest({"query_id": query_id, "selection": selection})


def _similarity_digest(similarity: Mapping[str, Any]) -> str:
    body = dict(similarity)
    body.pop("score_digest", None)
    return _digest(body)


def _move_label(match: Mapping[str, Any], horizon: int) -> Mapping[str, Any] | None:
    future = match.get("future_evaluation")
    if not isinstance(future, Mapping):
        return None
    bundle = future.get("move_bundle")
    if not isinstance(bundle, Mapping):
        return None
    labels = bundle.get("labels")
    if not isinstance(labels, list):
        return None
    for label in labels:
        if isinstance(label, Mapping) and int(label.get("horizon_minutes", -1)) == horizon:
            return label
    return None


def _trade_outcome(match: Mapping[str, Any], horizon: int) -> Mapping[str, Any] | None:
    future = match.get("future_evaluation")
    if not isinstance(future, Mapping):
        return None
    bundle = future.get("trade_outcome_bundle")
    if not isinstance(bundle, Mapping):
        return None
    outcomes = bundle.get("outcomes")
    if not isinstance(outcomes, list):
        return None
    for outcome in outcomes:
        if isinstance(outcome, Mapping) and int(outcome.get("horizon_minutes", -1)) == horizon:
            return outcome
    return None


def _move_240_complete(match: Mapping[str, Any]) -> bool:
    label = _move_label(match, 240)
    return bool(
        isinstance(label, Mapping)
        and label.get("coverage_state") == "complete"
        and str(label.get("path_class") or "unknown") != "unknown"
    )


def _validate_match(match: Mapping[str, Any], *, query_as_of: datetime) -> None:
    case_id = str(match.get("case_id") or "")
    if not case_id:
        raise ValueError("Evidence match requires case_id.")
    if int(match.get("rank", 0)) <= 0:
        raise ValueError("Evidence match requires a positive rank.")
    if _utc(str(match.get("as_of_utc") or "")) >= query_as_of:
        raise ValueError("Evidence match must precede the query timestamp.")
    if match.get("outcome_available_by_query_time") is not True:
        raise ValueError("Evidence grading requires outcomes already knowable by query time.")
    if match.get("outcome_used_for_similarity") is not False:
        raise ValueError("Evidence grading refuses matches whose outcome affected similarity.")

    similarity = match.get("similarity")
    if not isinstance(similarity, Mapping):
        raise TypeError("Evidence match requires a similarity object.")
    if similarity.get("similarity_feature_version") != SIMILARITY_FEATURE_VERSION:
        raise ValueError("Evidence match uses an unsupported similarity version.")
    supplied = str(similarity.get("score_digest") or "")
    if not supplied or supplied != _similarity_digest(similarity):
        raise ValueError("Evidence similarity score digest does not match contents.")
    score = _decimal(similarity.get("similarity_score"), name="similarity_score")
    coverage = _decimal(similarity.get("component_coverage"), name="component_coverage")
    if not Decimal(0) <= score <= Decimal(1):
        raise ValueError("Evidence similarity score must be between 0 and 1.")
    if not Decimal(0) <= coverage <= Decimal(1):
        raise ValueError("Evidence component coverage must be between 0 and 1.")

    quality = str(match.get("data_quality_grade") or "")
    if quality not in QUALITY_SCORES:
        raise ValueError(f"Unsupported Day 16 data quality grade: {quality}")


def _validate_retrieval(retrieval: Mapping[str, Any]) -> tuple[datetime, list[Mapping[str, Any]]]:
    if retrieval.get("retrieval_version") != ANALOGUE_RETRIEVAL_VERSION:
        raise ValueError("Evidence grading requires aidy_historical_analogue_retrieval_v1.")
    if retrieval.get("similarity_feature_version") != SIMILARITY_FEATURE_VERSION:
        raise ValueError("Evidence grading requires aidy_gold_similarity_features_v1.")
    if retrieval.get("outcomes_used_for_selection") is not False:
        raise ValueError("Evidence grading requires outcome-free analogue selection.")
    if retrieval.get("probability_claims_included") is not False:
        raise ValueError("Day 17 retrieval must not contain probability claims.")
    supplied = str(retrieval.get("retrieval_digest") or "")
    if not supplied or supplied != _retrieval_digest(retrieval):
        raise ValueError("Day 17 retrieval digest does not match contents.")

    query_id = str(retrieval.get("query_id") or "")
    if not query_id:
        raise ValueError("Evidence grading requires a Day 17 query_id.")
    query_as_of = _utc(str(retrieval.get("query_as_of_utc") or ""))
    raw_matches = retrieval.get("matches")
    if not isinstance(raw_matches, list):
        raise TypeError("Day 17 retrieval matches must be a list.")
    matches: list[Mapping[str, Any]] = []
    for match in raw_matches:
        if not isinstance(match, Mapping):
            raise TypeError("Day 17 retrieval matches must be objects.")
        _validate_match(match, query_as_of=query_as_of)
        matches.append(match)

    if int(retrieval.get("returned_match_count", -1)) != len(matches):
        raise ValueError("Day 17 returned_match_count does not match matches.")
    expected_ranks = list(range(1, len(matches) + 1))
    if [int(item["rank"]) for item in matches] != expected_ranks:
        raise ValueError("Day 17 match ranks must be contiguous and ordered.")
    if str(retrieval.get("selection_digest") or "") != _selection_digest(query_id, matches):
        raise ValueError("Day 17 selection digest does not match returned matches.")
    return query_as_of, matches


def evidence_grade_manifest() -> dict[str, Any]:
    manifest = {
        "evidence_grade_version": EVIDENCE_GRADE_VERSION,
        "evidence_report_version": EVIDENCE_REPORT_VERSION,
        "evidence_statistic_version": EVIDENCE_STATISTIC_VERSION,
        "source_retrieval_version": ANALOGUE_RETRIEVAL_VERSION,
        "source_similarity_feature_version": SIMILARITY_FEATURE_VERSION,
        "grade_order": list(GRADE_ORDER),
        "grade_labels": dict(GRADE_LABELS),
        "quality_scores": {key: str(value) for key, value in QUALITY_SCORES.items()},
        "grade_rules": {
            grade: {key: str(value) for key, value in rules.items()}
            for grade, rules in _GRADE_RULES.items()
        },
        "threshold_basis": "fixed_v1_conservative_not_outcome_optimized",
        "grading_applied_after_analogue_selection": True,
        "outcome_values_used_for_dataset_grade": False,
        "low_n_probability_wording_barred": True,
        "low_n_decision_weight_barred": True,
    }
    manifest["manifest_digest"] = _digest(manifest)
    return manifest


def _evidence_metrics(
    matches: Iterable[Mapping[str, Any]], *, query_as_of: datetime
) -> dict[str, Any]:
    items = list(matches)
    n = len(items)
    if not items:
        return {
            "n": 0,
            "mean_similarity": "0.000000",
            "p25_similarity": "0.000000",
            "mean_component_coverage": "0.000000",
            "mean_input_quality": "0.000000",
            "move_240_complete_ratio": "0.000000",
            "temporal_span_days": "0.000000",
            "unique_calendar_days": 0,
            "unique_calendar_months": 0,
            "newest_case_age_days": None,
            "max_calendar_day_share": "0.000000",
            "max_calendar_month_share": "0.000000",
            "provenance_counts": {},
            "quality_counts": {},
        }

    stamps = [_utc(str(item["as_of_utc"])) for item in items]
    similarities = [
        _decimal(item["similarity"]["similarity_score"], name="similarity_score")
        for item in items
    ]
    coverages = [
        _decimal(item["similarity"]["component_coverage"], name="component_coverage")
        for item in items
    ]
    qualities = [QUALITY_SCORES[str(item["data_quality_grade"])] for item in items]
    day_counts = Counter(stamp.date().isoformat() for stamp in stamps)
    month_counts = Counter(stamp.strftime("%Y-%m") for stamp in stamps)
    newest = max(stamps)
    oldest = min(stamps)
    seconds_per_day = Decimal(86400)
    span_days = Decimal(str((newest - oldest).total_seconds())) / seconds_per_day
    newest_age = Decimal(str((query_as_of - newest).total_seconds())) / seconds_per_day

    return {
        "n": n,
        "mean_similarity": _score(_mean(similarities)),
        "p25_similarity": _score(_p25(similarities)),
        "mean_component_coverage": _score(_mean(coverages)),
        "mean_input_quality": _score(_mean(qualities)),
        "move_240_complete_ratio": _score(
            _ratio(sum(_move_240_complete(item) for item in items), n)
        ),
        "temporal_span_days": _score(span_days),
        "unique_calendar_days": len(day_counts),
        "unique_calendar_months": len(month_counts),
        "newest_case_age_days": _score(newest_age),
        "max_calendar_day_share": _score(
            Decimal(max(day_counts.values())) / Decimal(n)
        ),
        "max_calendar_month_share": _score(
            Decimal(max(month_counts.values())) / Decimal(n)
        ),
        "provenance_counts": dict(
            sorted(
                Counter(
                    str(item.get("provenance_class") or "unknown") for item in items
                ).items()
            )
        ),
        "quality_counts": dict(
            sorted(Counter(str(item["data_quality_grade"]) for item in items).items())
        ),
    }


def _rule_metric_key(key: str) -> str:
    if key.startswith("min_"):
        return key.removeprefix("min_")
    if key in {"max_calendar_day_share", "max_calendar_month_share"}:
        return key
    if key.startswith("max_"):
        return key.removeprefix("max_")
    raise RuntimeError(f"Unsupported evidence rule: {key}")


def _rule_satisfied(key: str, threshold: Decimal | int, metrics: Mapping[str, Any]) -> bool:
    metric_key = _rule_metric_key(key)
    observed = metrics.get(metric_key)
    if observed is None:
        return False
    if key.startswith("min_"):
        if isinstance(threshold, int):
            return int(observed) >= threshold
        return _decimal(observed, name=metric_key) >= threshold
    if isinstance(threshold, int):
        return int(observed) <= threshold
    return _decimal(observed, name=metric_key) <= threshold


def _blockers(grade: str, metrics: Mapping[str, Any]) -> list[str]:
    rules = _GRADE_RULES[grade]
    return [
        f"{key}:{metrics.get(_rule_metric_key(key))}:required={threshold}"
        for key, threshold in rules.items()
        if not _rule_satisfied(key, threshold, metrics)
    ]


def grade_evidence(
    matches: Iterable[Mapping[str, Any]], *, query_as_of: datetime | str
) -> dict[str, Any]:
    query_time = _utc(query_as_of)
    items = list(matches)
    for item in items:
        _validate_match(item, query_as_of=query_time)
    metrics = _evidence_metrics(items, query_as_of=query_time)

    grade = GRADE_INSUFFICIENT
    for candidate in (GRADE_ESTABLISHED, GRADE_MODERATE, GRADE_EXPLORATORY):
        if not _blockers(candidate, metrics):
            grade = candidate
            break

    index = GRADE_ORDER.index(grade)
    next_grade = GRADE_ORDER[index + 1] if index + 1 < len(GRADE_ORDER) else None
    result = {
        "evidence_grade_version": EVIDENCE_GRADE_VERSION,
        "grade": grade,
        "grade_label": GRADE_LABELS[grade],
        "n": metrics["n"],
        "metrics": metrics,
        "probability_like_wording_allowed": grade in {GRADE_MODERATE, GRADE_ESTABLISHED},
        "decision_weight_allowed": grade == GRADE_ESTABLISHED,
        "standalone_trade_decision_allowed": False,
        "causal_claims_allowed": False,
        "next_grade": next_grade,
        "next_grade_blockers": [] if next_grade is None else _blockers(next_grade, metrics),
        "outcome_values_used_for_grade": False,
    }
    result["grade_digest"] = _digest(result)
    return result


def _category_statistic(
    *,
    name: str,
    observations: list[tuple[Mapping[str, Any], str]],
    query_as_of: datetime,
    total_retrieved: int,
) -> dict[str, Any]:
    matches = [item[0] for item in observations]
    counts = Counter(item[1] for item in observations)
    grade = grade_evidence(matches, query_as_of=query_as_of)
    rates_allowed = bool(grade["probability_like_wording_allowed"])
    rates = (
        {
            key: _score(Decimal(value) / Decimal(len(observations)))
            for key, value in sorted(counts.items())
        }
        if observations and rates_allowed
        else None
    )
    statistic = {
        "statistic_version": EVIDENCE_STATISTIC_VERSION,
        "name": name,
        "kind": "categorical_distribution",
        "n": len(observations),
        "retrieved_n": total_retrieved,
        "grade": grade["grade"],
        "grade_label": grade["grade_label"],
        "grade_digest": grade["grade_digest"],
        "counts": dict(sorted(counts.items())),
        "rates": rates,
        "probability_like_wording_allowed": rates_allowed,
        "decision_weight_allowed": bool(grade["decision_weight_allowed"]),
        "standalone_trade_decision_allowed": False,
        "causal_claims_allowed": False,
    }
    statistic["statistic_digest"] = _digest(statistic)
    return statistic


def _move_statistic(
    matches: list[Mapping[str, Any]], *, query_as_of: datetime, horizon: int
) -> dict[str, Any]:
    observations: list[tuple[Mapping[str, Any], str]] = []
    for match in matches:
        label = _move_label(match, horizon)
        if (
            isinstance(label, Mapping)
            and label.get("coverage_state") == "complete"
            and str(label.get("path_class") or "unknown") != "unknown"
        ):
            observations.append((match, str(label["path_class"])))
    return _category_statistic(
        name=f"move_path_class_{horizon}m",
        observations=observations,
        query_as_of=query_as_of,
        total_retrieved=len(matches),
    )


def _trade_statistic(
    matches: list[Mapping[str, Any]], *, query_as_of: datetime, horizon: int
) -> dict[str, Any]:
    observations: list[tuple[Mapping[str, Any], str]] = []
    for match in matches:
        outcome = _trade_outcome(match, horizon)
        if (
            isinstance(outcome, Mapping)
            and outcome.get("coverage_state") == "complete"
            and str(outcome.get("outcome_state") or "unknown") != "unknown"
        ):
            observations.append((match, str(outcome["outcome_state"])))
    return _category_statistic(
        name=f"trade_outcome_state_{horizon}m",
        observations=observations,
        query_as_of=query_as_of,
        total_retrieved=len(matches),
    )


def compute_evidence_report_digest(report: Mapping[str, Any]) -> str:
    body = dict(report)
    body.pop("report_digest", None)
    return _digest(body)


def verify_evidence_report_digest(report: Mapping[str, Any]) -> bool:
    supplied = str(report.get("report_digest") or "")
    return bool(supplied) and supplied == compute_evidence_report_digest(report)


def build_evidence_report(*, retrieval: Mapping[str, Any]) -> dict[str, Any]:
    query_as_of, matches = _validate_retrieval(retrieval)
    dataset_grade = grade_evidence(matches, query_as_of=query_as_of)
    statistics = [
        _move_statistic(matches, query_as_of=query_as_of, horizon=horizon)
        for horizon in (15, 60, 240)
    ]
    statistics.extend(
        _trade_statistic(matches, query_as_of=query_as_of, horizon=horizon)
        for horizon in (15, 60, 240)
    )
    report = {
        "evidence_report_version": EVIDENCE_REPORT_VERSION,
        "evidence_grade_version": EVIDENCE_GRADE_VERSION,
        "source_retrieval_version": retrieval["retrieval_version"],
        "source_similarity_feature_version": retrieval["similarity_feature_version"],
        "query_id": retrieval["query_id"],
        "query_as_of_utc": retrieval["query_as_of_utc"],
        "source_retrieval_digest": retrieval["retrieval_digest"],
        "source_selection_digest": retrieval["selection_digest"],
        "retrieval_evidence_state": retrieval["evidence_state"],
        "retrieved_match_count": len(matches),
        "dataset_grade": dataset_grade,
        "statistics": statistics,
        "grading_applied_after_analogue_selection": True,
        "selection_mutated_by_grading": False,
        "outcomes_used_for_analogue_selection": False,
        "outcome_values_used_for_dataset_grade": False,
        "probability_like_wording_allowed": dataset_grade["probability_like_wording_allowed"],
        "decision_weight_allowed": dataset_grade["decision_weight_allowed"],
        "standalone_trade_decision_allowed": False,
        "causal_claims_allowed": False,
    }
    report["report_digest"] = compute_evidence_report_digest(report)
    return report
