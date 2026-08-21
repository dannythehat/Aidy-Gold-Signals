from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from hashlib import sha256
from typing import Any

from aidy.analogue_retrieval_v2 import (
    ANALOGUE_RETRIEVAL_VERSION_V2,
    SIMILARITY_FEATURE_VERSION_V2,
    verify_retrieval_digest_v2,
)

EVIDENCE_GRADE_VERSION_V2 = "aidy_evidence_grade_v2_effective_independent_n"
EVIDENCE_REPORT_VERSION_V2 = "aidy_analogue_evidence_report_v2_independent_episodes"
EVIDENCE_STATISTIC_VERSION_V2 = "aidy_evidence_statistic_v2_independent_episodes"

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

# Day 18 rule magnitudes are retained. The sample-size semantic is deliberately
# changed from raw match count to effective independent episode count.
_GRADE_RULES: dict[str, dict[str, Decimal | int]] = {
    GRADE_EXPLORATORY: {
        "min_effective_n": 10,
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
        "min_effective_n": 30,
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
        "min_effective_n": 100,
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
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError("Day 24 evidence timestamps must be timezone-aware.")
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


def _mean(values: list[Decimal]) -> Decimal:
    return Decimal(0) if not values else sum(values, Decimal(0)) / Decimal(len(values))


def _p25(values: list[Decimal]) -> Decimal:
    if not values:
        return Decimal(0)
    ordered = sorted(values)
    return ordered[(len(ordered) - 1) * 25 // 100]


def _move_label(match: Mapping[str, Any], horizon: int) -> Mapping[str, Any] | None:
    future = match.get("future_evaluation")
    bundle = future.get("move_bundle") if isinstance(future, Mapping) else None
    labels = bundle.get("labels") if isinstance(bundle, Mapping) else None
    if not isinstance(labels, list):
        return None
    return next(
        (
            item
            for item in labels
            if isinstance(item, Mapping) and int(item.get("horizon_minutes", -1)) == horizon
        ),
        None,
    )


def _trade_outcome(match: Mapping[str, Any], horizon: int) -> Mapping[str, Any] | None:
    future = match.get("future_evaluation")
    bundle = future.get("trade_outcome_bundle") if isinstance(future, Mapping) else None
    outcomes = bundle.get("outcomes") if isinstance(bundle, Mapping) else None
    if not isinstance(outcomes, list):
        return None
    return next(
        (
            item
            for item in outcomes
            if isinstance(item, Mapping) and int(item.get("horizon_minutes", -1)) == horizon
        ),
        None,
    )


def _similarity_digest(similarity: Mapping[str, Any]) -> str:
    body = dict(similarity)
    body.pop("score_digest", None)
    return _digest(body)


def _selection_digest(query_id: str, matches: list[Mapping[str, Any]]) -> str:
    body = {
        "query_id": query_id,
        "selection": [
            {
                "rank": item["rank"],
                "case_id": item["case_id"],
                "episode_id": item["episode_id"],
                "similarity_score": item["similarity"]["similarity_score"],
                "component_coverage": item["similarity"]["component_coverage"],
            }
            for item in matches
        ],
    }
    return _digest(body)


def _validate_match(match: Mapping[str, Any], *, query_as_of: datetime) -> None:
    if not str(match.get("case_id") or "") or not str(match.get("episode_id") or ""):
        raise ValueError("Day 24 evidence match requires case_id and episode_id.")
    if int(match.get("rank", 0)) <= 0:
        raise ValueError("Day 24 evidence match requires positive rank.")
    if _utc(str(match.get("as_of_utc") or "")) >= query_as_of:
        raise ValueError("Day 24 evidence match must precede the query timestamp.")
    if match.get("outcome_available_by_query_time") is not True:
        raise ValueError("Day 24 evidence requires outcomes already knowable by query time.")
    if match.get("outcome_used_for_similarity") is not False:
        raise ValueError("Day 24 grading refuses outcome-valued similarity.")
    similarity = match.get("similarity")
    if not isinstance(similarity, Mapping):
        raise TypeError("Day 24 evidence match requires similarity.")
    if similarity.get("similarity_feature_version") != SIMILARITY_FEATURE_VERSION_V2:
        raise ValueError("Day 24 evidence requires v2 decorrelated similarity.")
    supplied = str(similarity.get("score_digest") or "")
    if not supplied or supplied != _similarity_digest(similarity):
        raise ValueError("Day 24 similarity digest mismatch.")
    score = _decimal(similarity.get("similarity_score"), name="similarity_score")
    coverage = _decimal(similarity.get("component_coverage"), name="component_coverage")
    if not Decimal(0) <= score <= Decimal(1) or not Decimal(0) <= coverage <= Decimal(1):
        raise ValueError("Day 24 similarity values must be within [0,1].")
    if str(match.get("data_quality_grade") or "") not in QUALITY_SCORES:
        raise ValueError("Day 24 evidence has unsupported data-quality grade.")


def _validate_retrieval(
    retrieval: Mapping[str, Any],
) -> tuple[datetime, list[Mapping[str, Any]], Mapping[str, Any]]:
    if retrieval.get("retrieval_version") != ANALOGUE_RETRIEVAL_VERSION_V2:
        raise ValueError("Day 24 grading requires v2 independent-episode retrieval.")
    if retrieval.get("similarity_feature_version") != SIMILARITY_FEATURE_VERSION_V2:
        raise ValueError("Day 24 grading requires v2 decorrelated similarity.")
    if retrieval.get("outcome_values_used_for_selection") is not False:
        raise ValueError("Day 24 grading refuses outcome-valued analogue selection.")
    if retrieval.get("probability_claims_included") is not False:
        raise ValueError("Day 24 retrieval must not contain probability claims.")
    if not verify_retrieval_digest_v2(retrieval):
        raise ValueError("Day 24 retrieval digest mismatch.")
    query_id = str(retrieval.get("query_id") or "")
    query_as_of = _utc(str(retrieval.get("query_as_of_utc") or ""))
    independence = retrieval.get("independence")
    if not query_id or not isinstance(independence, Mapping):
        raise ValueError("Day 24 retrieval identity/independence diagnostics missing.")
    raw_matches = retrieval.get("matches")
    if not isinstance(raw_matches, list):
        raise TypeError("Day 24 retrieval matches must be a list.")
    matches: list[Mapping[str, Any]] = []
    episode_ids: set[str] = set()
    for item in raw_matches:
        if not isinstance(item, Mapping):
            raise TypeError("Day 24 retrieval matches must be objects.")
        _validate_match(item, query_as_of=query_as_of)
        episode_id = str(item["episode_id"])
        if episode_id in episode_ids:
            raise ValueError("Day 24 grading refuses duplicate independent episodes.")
        episode_ids.add(episode_id)
        matches.append(item)
    if int(retrieval.get("returned_match_count", -1)) != len(matches):
        raise ValueError("Day 24 returned_match_count mismatch.")
    if int(independence.get("grading_effective_n", -1)) != len(matches):
        raise ValueError("Day 24 grading_effective_n must equal episode representatives.")
    if [int(item["rank"]) for item in matches] != list(range(1, len(matches) + 1)):
        raise ValueError("Day 24 match ranks must be contiguous.")
    if str(retrieval.get("selection_digest") or "") != _selection_digest(query_id, matches):
        raise ValueError("Day 24 selection digest mismatch.")
    return query_as_of, matches, independence


def evidence_grade_manifest_v2() -> dict[str, Any]:
    body = {
        "evidence_grade_version": EVIDENCE_GRADE_VERSION_V2,
        "evidence_report_version": EVIDENCE_REPORT_VERSION_V2,
        "source_retrieval_version": ANALOGUE_RETRIEVAL_VERSION_V2,
        "source_similarity_feature_version": SIMILARITY_FEATURE_VERSION_V2,
        "grade_order": list(GRADE_ORDER),
        "grade_rules": {
            grade: {key: str(value) for key, value in rules.items()}
            for grade, rules in _GRADE_RULES.items()
        },
        "sample_size_basis": "effective_independent_episode_n",
        "threshold_basis": "day18_magnitudes_retained_not_outcome_optimized",
        "outcome_values_used_for_dataset_grade": False,
    }
    body["manifest_digest"] = _digest(body)
    return body


def _metrics(
    matches: list[Mapping[str, Any]], *, query_as_of: datetime, raw_n: int
) -> dict[str, Any]:
    effective_n = len(matches)
    if not matches:
        return {
            "raw_n": raw_n,
            "effective_n": 0,
            "effective_n_over_raw_n": None if raw_n == 0 else "0.000000",
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
    stamps = [_utc(str(item["as_of_utc"])) for item in matches]
    similarities = [
        _decimal(item["similarity"]["similarity_score"], name="similarity_score")
        for item in matches
    ]
    coverages = [
        _decimal(item["similarity"]["component_coverage"], name="component_coverage")
        for item in matches
    ]
    qualities = [QUALITY_SCORES[str(item["data_quality_grade"])] for item in matches]
    days = Counter(stamp.date().isoformat() for stamp in stamps)
    months = Counter(stamp.strftime("%Y-%m") for stamp in stamps)
    oldest, newest = min(stamps), max(stamps)
    span = Decimal(str((newest - oldest).total_seconds())) / Decimal(86400)
    age = Decimal(str((query_as_of - newest).total_seconds())) / Decimal(86400)
    complete = 0
    for item in matches:
        label = _move_label(item, 240)
        if (
            isinstance(label, Mapping)
            and label.get("coverage_state") == "complete"
            and str(label.get("path_class") or "unknown") != "unknown"
        ):
            complete += 1
    return {
        "raw_n": raw_n,
        "effective_n": effective_n,
        "effective_n_over_raw_n": _score(Decimal(effective_n) / Decimal(raw_n)) if raw_n else None,
        "mean_similarity": _score(_mean(similarities)),
        "p25_similarity": _score(_p25(similarities)),
        "mean_component_coverage": _score(_mean(coverages)),
        "mean_input_quality": _score(_mean(qualities)),
        "move_240_complete_ratio": _score(Decimal(complete) / Decimal(effective_n)),
        "temporal_span_days": _score(span),
        "unique_calendar_days": len(days),
        "unique_calendar_months": len(months),
        "newest_case_age_days": _score(age),
        "max_calendar_day_share": _score(Decimal(max(days.values())) / Decimal(effective_n)),
        "max_calendar_month_share": _score(Decimal(max(months.values())) / Decimal(effective_n)),
        "provenance_counts": dict(
            sorted(Counter(str(item.get("provenance_class") or "unknown") for item in matches).items())
        ),
        "quality_counts": dict(
            sorted(Counter(str(item["data_quality_grade"]) for item in matches).items())
        ),
    }


def _metric_key(rule: str) -> str:
    if rule.startswith("min_"):
        return rule.removeprefix("min_")
    if rule in {"max_calendar_day_share", "max_calendar_month_share"}:
        return rule
    if rule.startswith("max_"):
        return rule.removeprefix("max_")
    raise RuntimeError(f"Unsupported Day 24 evidence rule: {rule}")


def _satisfied(rule: str, threshold: Decimal | int, metrics: Mapping[str, Any]) -> bool:
    key = _metric_key(rule)
    observed = metrics.get(key)
    if observed is None:
        return False
    if rule.startswith("min_"):
        return int(observed) >= threshold if isinstance(threshold, int) else _decimal(observed, name=key) >= threshold
    return int(observed) <= threshold if isinstance(threshold, int) else _decimal(observed, name=key) <= threshold


def _blockers(grade: str, metrics: Mapping[str, Any]) -> list[str]:
    return [
        f"{rule}:{metrics.get(_metric_key(rule))}:required={threshold}"
        for rule, threshold in _GRADE_RULES[grade].items()
        if not _satisfied(rule, threshold, metrics)
    ]


def grade_evidence_v2(
    matches: Iterable[Mapping[str, Any]], *, query_as_of: datetime | str, raw_n: int
) -> dict[str, Any]:
    query_time = _utc(query_as_of)
    items = list(matches)
    for item in items:
        _validate_match(item, query_as_of=query_time)
    metrics = _metrics(items, query_as_of=query_time, raw_n=raw_n)
    grade = GRADE_INSUFFICIENT
    for candidate in (GRADE_ESTABLISHED, GRADE_MODERATE, GRADE_EXPLORATORY):
        if not _blockers(candidate, metrics):
            grade = candidate
            break
    index = GRADE_ORDER.index(grade)
    next_grade = GRADE_ORDER[index + 1] if index + 1 < len(GRADE_ORDER) else None
    result = {
        "evidence_grade_version": EVIDENCE_GRADE_VERSION_V2,
        "grade": grade,
        "grade_label": GRADE_LABELS[grade],
        "raw_n": raw_n,
        "effective_n": metrics["effective_n"],
        "n": metrics["effective_n"],
        "sample_size_basis": "effective_independent_episode_n",
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
    *, name: str, observations: list[tuple[Mapping[str, Any], str]], query_as_of: datetime
) -> dict[str, Any]:
    matches = [item[0] for item in observations]
    counts = Counter(item[1] for item in observations)
    grade = grade_evidence_v2(matches, query_as_of=query_as_of, raw_n=len(matches))
    rates_allowed = bool(grade["probability_like_wording_allowed"])
    rates = (
        {
            key: _score(Decimal(value) / Decimal(len(observations)))
            for key, value in sorted(counts.items())
        }
        if observations and rates_allowed
        else None
    )
    result = {
        "statistic_version": EVIDENCE_STATISTIC_VERSION_V2,
        "name": name,
        "kind": "categorical_distribution",
        "effective_n": len(matches),
        "grade": grade["grade"],
        "grade_digest": grade["grade_digest"],
        "counts": dict(sorted(counts.items())),
        "rates": rates,
        "probability_like_wording_allowed": rates_allowed,
        "decision_weight_allowed": bool(grade["decision_weight_allowed"]),
    }
    result["statistic_digest"] = _digest(result)
    return result


def _statistics(matches: list[Mapping[str, Any]], *, query_as_of: datetime) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for horizon in (15, 60, 240):
        move_obs: list[tuple[Mapping[str, Any], str]] = []
        trade_obs: list[tuple[Mapping[str, Any], str]] = []
        for item in matches:
            label = _move_label(item, horizon)
            if (
                isinstance(label, Mapping)
                and label.get("coverage_state") == "complete"
                and str(label.get("path_class") or "unknown") != "unknown"
            ):
                move_obs.append((item, str(label["path_class"])))
            outcome = _trade_outcome(item, horizon)
            if (
                isinstance(outcome, Mapping)
                and outcome.get("coverage_state") == "complete"
                and str(outcome.get("outcome_state") or "unknown") != "unknown"
            ):
                trade_obs.append((item, str(outcome["outcome_state"])))
        result.append(
            _category_statistic(
                name=f"move_path_class_{horizon}m",
                observations=move_obs,
                query_as_of=query_as_of,
            )
        )
        result.append(
            _category_statistic(
                name=f"trade_outcome_state_{horizon}m",
                observations=trade_obs,
                query_as_of=query_as_of,
            )
        )
    return result


def compute_evidence_report_digest_v2(report: Mapping[str, Any]) -> str:
    body = dict(report)
    body.pop("report_digest", None)
    return _digest(body)


def build_evidence_report_v2(*, retrieval: Mapping[str, Any]) -> dict[str, Any]:
    query_as_of, matches, independence = _validate_retrieval(retrieval)
    raw_n = int(independence["pre_dedup_raw_n"])
    dataset_grade = grade_evidence_v2(matches, query_as_of=query_as_of, raw_n=raw_n)
    report = {
        "evidence_report_version": EVIDENCE_REPORT_VERSION_V2,
        "evidence_grade_version": EVIDENCE_GRADE_VERSION_V2,
        "source_retrieval_version": retrieval["retrieval_version"],
        "source_similarity_feature_version": retrieval["similarity_feature_version"],
        "query_id": retrieval["query_id"],
        "query_as_of_utc": retrieval["query_as_of_utc"],
        "source_retrieval_digest": retrieval["retrieval_digest"],
        "source_selection_digest": retrieval["selection_digest"],
        "retrieval_evidence_state": retrieval["evidence_state"],
        "pre_dedup_raw_n": raw_n,
        "retrieved_match_count": len(matches),
        "effective_independent_n": int(independence["grading_effective_n"]),
        "dataset_grade": dataset_grade,
        "statistics": _statistics(matches, query_as_of=query_as_of),
        "grading_applied_after_episode_deduplicated_analogue_selection": True,
        "sample_size_basis": "effective_independent_episode_n",
        "selection_mutated_by_grading": False,
        "outcome_values_used_for_analogue_selection": False,
        "outcome_values_used_for_dataset_grade": False,
        "probability_like_wording_allowed": dataset_grade["probability_like_wording_allowed"],
        "decision_weight_allowed": dataset_grade["decision_weight_allowed"],
        "standalone_trade_decision_allowed": False,
        "causal_claims_allowed": False,
    }
    report["report_digest"] = compute_evidence_report_digest_v2(report)
    return report
