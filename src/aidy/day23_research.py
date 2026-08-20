from __future__ import annotations

import json
import math
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from hashlib import sha256
from statistics import median
from typing import Any

DAY23_RESEARCH_VERSION = "aidy_day23_architecture_v2_baseline_v1"
DAY23_MANIFEST_VERSION = "aidy_day23_frozen_query_manifest_v1"
DAY23_J1_VERSION = "aidy_day23_j1_analogue_independence_v1"
DAY23_J16_VERSION = "aidy_day23_j16_descriptive_baseline_v1"

BASELINE_SHA = "4bc7269ee05f5596ac6555279e97e98556be9b96"
QUERY_COUNT = 1000
QUERY_START_UTC = "2025-03-01T00:00:00+00:00"
CONTEXT_LOOKBACK_DAYS = 45
EPISODE_HORIZON_MINUTES = 240
CANDIDATE_LIMIT = 2000
MAX_RESULTS = 200
MIN_SIMILARITY = Decimal("0.72")
MIN_COMPONENT_COVERAGE = Decimal("0.65")
STOP_WORK_THRESHOLD = Decimal("0.50")
RECOVERY_INDEPENDENCE_THRESHOLD = Decimal("0.70")
RECOVERY_MIN_DISTINCT_EPISODES = 10

GRADE_ORDER = (
    "insufficient",
    "exploratory",
    "moderate_evidence",
    "established_dataset",
)
NOT_GRADED = "not_graded"


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value: object) -> str:
    return sha256(canonical_json(value).encode()).hexdigest()


def _utc(value: datetime | str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError("Day 23 timestamps must be timezone-aware.")
    return parsed.astimezone(UTC)


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value))
    except (ValueError, ArithmeticError):
        return None
    return parsed if parsed.is_finite() else None


def _text(value: Decimal | None, places: str = "0.000000") -> str | None:
    if value is None:
        return None
    return str(value.quantize(Decimal(places), rounding=ROUND_HALF_UP))


def _quantile(values: Sequence[Decimal], q: Decimal) -> Decimal | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = q * Decimal(len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - Decimal(lower)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _distribution(values: Iterable[Any]) -> dict[str, str | int | None]:
    parsed = [value for raw in values if (value := _decimal(raw)) is not None]
    return {
        "n": len(parsed),
        "min": _text(min(parsed)) if parsed else None,
        "p10": _text(_quantile(parsed, Decimal("0.10"))),
        "p25": _text(_quantile(parsed, Decimal("0.25"))),
        "median": _text(_quantile(parsed, Decimal("0.50"))),
        "p75": _text(_quantile(parsed, Decimal("0.75"))),
        "p90": _text(_quantile(parsed, Decimal("0.90"))),
        "max": _text(max(parsed)) if parsed else None,
    }


def preregistration() -> dict[str, Any]:
    value = {
        "research_version": DAY23_RESEARCH_VERSION,
        "baseline_sha": BASELINE_SHA,
        "query_count": QUERY_COUNT,
        "query_start_utc": QUERY_START_UTC,
        "query_anchor_rule": (
            "first_1000_chronological_actual_histdata_XAUUSD_M1_hourly_closed_anchors_"
            "at_or_after_query_start_no_removal"
        ),
        "context_lookback_days": CONTEXT_LOOKBACK_DAYS,
        "candidate_limit": CANDIDATE_LIMIT,
        "max_results": MAX_RESULTS,
        "min_similarity_score": str(MIN_SIMILARITY),
        "min_component_coverage": str(MIN_COMPONENT_COVERAGE),
        "retrieval_tuning_allowed": False,
        "query_removal_allowed": False,
        "episode_definition": (
            "connected_components_of_overlapping_240m_future_evaluation_windows;_"
            "strict_non_overlap_starts_new_episode"
        ),
        "episode_horizon_minutes": EPISODE_HORIZON_MINUTES,
        "effective_n_definition": "kish_equivalent_episode_count_raw_n_squared_over_sum_episode_n_squared",
        "independence_ratio_denominator": "selected_raw_n_after_existing_day17_thresholds",
        "stop_work_median_population": "queries_with_selected_raw_n_gt_0_only",
        "coverage_population": "all_1000_frozen_queries",
        "stop_work_threshold": str(STOP_WORK_THRESHOLD),
        "recovery_exit_independence_threshold": str(RECOVERY_INDEPENDENCE_THRESHOLD),
        "recovery_exit_min_distinct_episodes": RECOVERY_MIN_DISTINCT_EPISODES,
        "no_comparable_case_definition": "day17_no_sufficient_similarity_with_selected_raw_n_zero",
        "j16_role": "descriptive_baseline_only",
        "j16_validation_clearance_allowed": False,
        "authoritative_j16_retest_day": 38,
        "j16_primary_dispersion": "240m_terminal_return_bps_population_stddev",
        "j16_secondary_dispersion": [
            "240m_terminal_return_bps_iqr",
            "240m_terminal_return_bps_median_absolute_deviation",
            "240m_path_class_normalized_entropy",
        ],
    }
    value["preregistration_digest"] = digest(value)
    return value


def freeze_query_manifest(queries: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if len(queries) != QUERY_COUNT:
        raise ValueError(f"Day 23 requires exactly {QUERY_COUNT} frozen queries.")
    query_ids = [str(query.get("query_id") or "") for query in queries]
    if any(not query_id for query_id in query_ids):
        raise ValueError("Every frozen Day 23 query requires a query_id.")
    if len(set(query_ids)) != len(query_ids):
        raise ValueError("Frozen Day 23 query IDs must be unique.")
    body = {
        "manifest_version": DAY23_MANIFEST_VERSION,
        "preregistration": preregistration(),
        "queries": [dict(query) for query in queries],
    }
    return {
        **body,
        "manifest_digest": digest(body),
    }


def _similarity_values(matches: Sequence[Mapping[str, Any]]) -> list[Decimal]:
    values: list[Decimal] = []
    for match in matches:
        similarity = match.get("similarity")
        if not isinstance(similarity, Mapping):
            continue
        parsed = _decimal(similarity.get("similarity_score"))
        if parsed is not None:
            values.append(parsed)
    return values


def _component_coverage_values(matches: Sequence[Mapping[str, Any]]) -> list[Decimal]:
    values: list[Decimal] = []
    for match in matches:
        similarity = match.get("similarity")
        if not isinstance(similarity, Mapping):
            continue
        parsed = _decimal(similarity.get("component_coverage"))
        if parsed is not None:
            values.append(parsed)
    return values


def episode_independence_diagnostics(
    matches: Sequence[Mapping[str, Any]],
    *,
    episode_horizon_minutes: int = EPISODE_HORIZON_MINUTES,
) -> dict[str, Any]:
    items = sorted(matches, key=lambda item: (_utc(str(item["as_of_utc"])), str(item["case_id"])))
    raw_n = len(items)
    if raw_n == 0:
        return {
            "j1_version": DAY23_J1_VERSION,
            "raw_n": 0,
            "selected_raw_n": 0,
            "effective_n": "0.000000",
            "effective_n_over_raw_n": None,
            "distinct_independent_episodes": 0,
            "episode_concentration_hhi": None,
            "max_episode_share": None,
            "same_episode_pair_share": None,
            "overlapping_240m_pair_share": None,
            "overlapping_240m_case_share": None,
            "temporal_span_hours": None,
            "distinct_months": 0,
            "months": [],
            "similarity": _distribution([]),
            "component_coverage": _distribution([]),
            "near_top_similarity_share_within_0_01": None,
            "episodes": [],
        }

    horizon = timedelta(minutes=episode_horizon_minutes)

    def episode_window(item: Mapping[str, Any]) -> tuple[datetime, datetime]:
        label = _move_240(item)
        if label is not None:
            anchor = label.get("anchor_time_utc")
            horizon_end = label.get("horizon_end_utc")
            if anchor is not None and horizon_end is not None:
                return _utc(str(anchor)), _utc(str(horizon_end))
        stamp = _utc(str(item["as_of_utc"]))
        return stamp, stamp + horizon

    items = sorted(items, key=lambda item: (episode_window(item)[0], str(item["case_id"])))
    episodes: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for item in items:
        stamp, item_end = episode_window(item)
        if current is None or stamp >= current["window_end"]:
            current = {
                "window_start": stamp,
                "window_end": item_end,
                "members": [],
            }
            episodes.append(current)
        else:
            current["window_end"] = max(current["window_end"], item_end)
        current["members"].append(item)

    episode_counts = [len(episode["members"]) for episode in episodes]
    sum_squares = sum(count * count for count in episode_counts)
    effective_n = Decimal(raw_n * raw_n) / Decimal(sum_squares)
    ratio = effective_n / Decimal(raw_n)
    shares = [Decimal(count) / Decimal(raw_n) for count in episode_counts]
    hhi = sum((share * share for share in shares), Decimal(0))

    pair_total = raw_n * (raw_n - 1) // 2
    same_episode_pairs = sum(count * (count - 1) // 2 for count in episode_counts)
    overlap_pairs = 0
    overlap_case_ids: set[str] = set()
    for left_index, left in enumerate(items):
        _, left_end = episode_window(left)
        for right in items[left_index + 1 :]:
            right_start, _ = episode_window(right)
            if right_start >= left_end:
                break
            overlap_pairs += 1
            overlap_case_ids.add(str(left["case_id"]))
            overlap_case_ids.add(str(right["case_id"]))

    stamps = [episode_window(item)[0] for item in items]
    span_hours = Decimal(str((max(stamps) - min(stamps)).total_seconds())) / Decimal(3600)
    months = sorted({stamp.strftime("%Y-%m") for stamp in stamps})
    similarities = _similarity_values(items)
    coverages = _component_coverage_values(items)
    top_similarity = max(similarities) if similarities else None
    near_top = (
        Decimal(sum(value >= top_similarity - Decimal("0.01") for value in similarities))
        / Decimal(len(similarities))
        if top_similarity is not None and similarities
        else None
    )

    episode_payload = []
    for episode in episodes:
        member_ids = [str(item["case_id"]) for item in episode["members"]]
        episode_body = {
            "window_start_utc": episode["window_start"].isoformat(),
            "window_end_utc": episode["window_end"].isoformat(),
            "n": len(member_ids),
            "case_ids": member_ids,
        }
        episode_payload.append({**episode_body, "episode_id": digest(episode_body)})

    return {
        "j1_version": DAY23_J1_VERSION,
        "raw_n": raw_n,
        "selected_raw_n": raw_n,
        "effective_n": _text(effective_n),
        "effective_n_over_raw_n": _text(ratio),
        "distinct_independent_episodes": len(episodes),
        "episode_concentration_hhi": _text(hhi),
        "max_episode_share": _text(max(shares)),
        "same_episode_pair_share": (
            _text(Decimal(same_episode_pairs) / Decimal(pair_total)) if pair_total else "0.000000"
        ),
        "overlapping_240m_pair_share": (
            _text(Decimal(overlap_pairs) / Decimal(pair_total)) if pair_total else "0.000000"
        ),
        "overlapping_240m_case_share": _text(Decimal(len(overlap_case_ids)) / Decimal(raw_n)),
        "temporal_span_hours": _text(span_hours),
        "distinct_months": len(months),
        "months": months,
        "similarity": _distribution(similarities),
        "component_coverage": _distribution(coverages),
        "near_top_similarity_share_within_0_01": _text(near_top),
        "episodes": episode_payload,
    }


def _move_240(match: Mapping[str, Any]) -> Mapping[str, Any] | None:
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
        if (
            isinstance(label, Mapping)
            and int(label.get("horizon_minutes", -1)) == EPISODE_HORIZON_MINUTES
            and label.get("coverage_state") == "complete"
        ):
            return label
    return None


def realized_dispersion(matches: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    returns: list[Decimal] = []
    path_classes: list[str] = []
    case_ids: list[str] = []
    for match in matches:
        label = _move_240(match)
        if label is None:
            continue
        path_stats = label.get("path_stats")
        if not isinstance(path_stats, Mapping):
            continue
        terminal_return = _decimal(path_stats.get("terminal_return_bps"))
        if terminal_return is None:
            continue
        returns.append(terminal_return)
        path_classes.append(str(label.get("path_class") or "unknown"))
        case_ids.append(str(match["case_id"]))

    n = len(returns)
    if n == 0:
        return {
            "j16_version": DAY23_J16_VERSION,
            "outcome_n_240m": 0,
            "terminal_return_stddev_bps": None,
            "terminal_return_iqr_bps": None,
            "terminal_return_mad_bps": None,
            "mean_abs_terminal_return_bps": None,
            "path_class_normalized_entropy": None,
            "unique_path_classes": 0,
            "outcome_case_ids": [],
        }

    mean_return = sum(returns, Decimal(0)) / Decimal(n)
    variance = sum(((value - mean_return) ** 2 for value in returns), Decimal(0)) / Decimal(n)
    stddev = variance.sqrt()
    q25 = _quantile(returns, Decimal("0.25"))
    q75 = _quantile(returns, Decimal("0.75"))
    med = Decimal(str(median(returns)))
    deviations = [abs(value - med) for value in returns]
    mad = Decimal(str(median(deviations)))
    mean_abs = sum((abs(value) for value in returns), Decimal(0)) / Decimal(n)

    counts = Counter(path_classes)
    if len(counts) <= 1:
        entropy = Decimal(0)
    else:
        entropy_float = -sum(
            (count / n) * math.log(count / n) for count in counts.values() if count > 0
        ) / math.log(len(counts))
        entropy = Decimal(str(entropy_float))

    return {
        "j16_version": DAY23_J16_VERSION,
        "outcome_n_240m": n,
        "terminal_return_stddev_bps": _text(stddev),
        "terminal_return_iqr_bps": _text(q75 - q25) if q25 is not None and q75 is not None else None,
        "terminal_return_mad_bps": _text(mad),
        "mean_abs_terminal_return_bps": _text(mean_abs),
        "path_class_normalized_entropy": _text(entropy),
        "unique_path_classes": len(counts),
        "path_class_counts": dict(sorted(counts.items())),
        "outcome_case_ids": case_ids,
    }


def summarize_j1(query_results: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if len(query_results) != QUERY_COUNT:
        raise ValueError(f"J1 summary requires all {QUERY_COUNT} frozen query results.")
    comparable = [row for row in query_results if int(row.get("selected_raw_n", 0)) > 0]
    ratios = [row.get("effective_n_over_raw_n") for row in comparable]
    ratio_distribution = _distribution(ratios)
    median_ratio = _decimal(ratio_distribution["median"])
    stop_evaluable = median_ratio is not None
    stop_work = bool(stop_evaluable and median_ratio < STOP_WORK_THRESHOLD)

    no_comparable_count = sum(bool(row.get("no_comparable_case")) for row in query_results)
    insufficient_count = sum(
        str(row.get("retrieval_evidence_state")) == "query_insufficient_quality"
        for row in query_results
    )
    n_all = Decimal(len(query_results))
    no_comparable_rate = Decimal(no_comparable_count) / n_all
    coverage_classification = (
        "coverage_limited"
        if no_comparable_rate > Decimal("0.75")
        else "low_coverage_accepted"
        if no_comparable_rate > Decimal("0.50")
        else "not_coverage_limited"
    )

    return {
        "j1_version": DAY23_J1_VERSION,
        "query_count": len(query_results),
        "comparable_query_count": len(comparable),
        "no_comparable_case_count": no_comparable_count,
        "no_comparable_case_rate": _text(no_comparable_rate),
        "query_insufficient_quality_count": insufficient_count,
        "query_insufficient_quality_rate": _text(Decimal(insufficient_count) / n_all),
        "effective_n_over_raw_n_distribution": ratio_distribution,
        "median_effective_n_over_raw_n": _text(median_ratio),
        "candidate_raw_n_distribution": _distribution(
            row.get("candidate_raw_n") for row in query_results
        ),
        "selected_raw_n_distribution": _distribution(
            row.get("selected_raw_n") for row in query_results
        ),
        "effective_n_distribution": _distribution(row.get("effective_n") for row in comparable),
        "distinct_independent_episodes_distribution": _distribution(
            row.get("distinct_independent_episodes") for row in comparable
        ),
        "episode_concentration_hhi_distribution": _distribution(
            row.get("episode_concentration_hhi") for row in comparable
        ),
        "stop_work_threshold": str(STOP_WORK_THRESHOLD),
        "stop_work_threshold_evaluable": stop_evaluable,
        "stop_work_fired": stop_work,
        "coverage_classification": coverage_classification,
        "normal_roadmap_progression_allowed": bool(stop_evaluable and not stop_work),
        "schedule_pressure_override_allowed": False,
    }


def _rankdata(values: Sequence[float]) -> list[float]:
    indexed = sorted(enumerate(values), key=lambda pair: pair[1])
    ranks = [0.0] * len(values)
    cursor = 0
    while cursor < len(indexed):
        end = cursor + 1
        while end < len(indexed) and indexed[end][1] == indexed[cursor][1]:
            end += 1
        average_rank = (cursor + 1 + end) / 2.0
        for index, _ in indexed[cursor:end]:
            ranks[index] = average_rank
        cursor = end
    return ranks


def _pearson(left: Sequence[float], right: Sequence[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    mean_left = sum(left) / len(left)
    mean_right = sum(right) / len(right)
    numerator = sum((x - mean_left) * (y - mean_right) for x, y in zip(left, right, strict=True))
    denominator = math.sqrt(
        sum((x - mean_left) ** 2 for x in left)
        * sum((y - mean_right) ** 2 for y in right)
    )
    return None if denominator == 0 else numerator / denominator


def _spearman(left: Sequence[float], right: Sequence[float]) -> float | None:
    if len(left) < 2:
        return None
    return _pearson(_rankdata(left), _rankdata(right))


def summarize_j16(query_results: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if len(query_results) != QUERY_COUNT:
        raise ValueError(f"J16 summary requires all {QUERY_COUNT} frozen query results.")

    by_grade: dict[str, list[Mapping[str, Any]]] = {
        grade: [] for grade in (*GRADE_ORDER, NOT_GRADED)
    }
    for row in query_results:
        grade = str(row.get("dataset_grade") or NOT_GRADED)
        if grade not in by_grade:
            raise ValueError(f"Unexpected Day 18 evidence grade: {grade}")
        by_grade[grade].append(row)

    grade_summary: dict[str, Any] = {}
    for grade in (*GRADE_ORDER, NOT_GRADED):
        rows = by_grade[grade]
        grade_summary[grade] = {
            "query_count": len(rows),
            "outcome_evaluable_query_count": sum(
                int(row.get("outcome_n_240m", 0)) >= 2 for row in rows
            ),
            "terminal_return_stddev_bps": _distribution(
                row.get("terminal_return_stddev_bps") for row in rows
            ),
            "terminal_return_iqr_bps": _distribution(
                row.get("terminal_return_iqr_bps") for row in rows
            ),
            "terminal_return_mad_bps": _distribution(
                row.get("terminal_return_mad_bps") for row in rows
            ),
            "path_class_normalized_entropy": _distribution(
                row.get("path_class_normalized_entropy") for row in rows
            ),
        }

    grade_rank_values: list[float] = []
    dispersion_values: list[float] = []
    for row in query_results:
        stddev = _decimal(row.get("terminal_return_stddev_bps"))
        grade = str(row.get("dataset_grade") or NOT_GRADED)
        if grade == NOT_GRADED or stddev is None or int(row.get("outcome_n_240m", 0)) < 2:
            continue
        grade_rank_values.append(float(GRADE_ORDER.index(grade)))
        dispersion_values.append(float(stddev))
    spearman = _spearman(grade_rank_values, dispersion_values)

    observed_grades = [grade for grade in GRADE_ORDER if by_grade[grade]]
    observed_grade_medians: list[Decimal] = []
    monotonic_possible = True
    for grade in observed_grades:
        grade_median = _decimal(grade_summary[grade]["terminal_return_stddev_bps"]["median"])
        if grade_median is None:
            monotonic_possible = False
            break
        observed_grade_medians.append(grade_median)
    monotonic_nonincreasing = (
        all(
            observed_grade_medians[index] <= observed_grade_medians[index - 1]
            for index in range(1, len(observed_grade_medians))
        )
        if monotonic_possible and len(observed_grade_medians) >= 2
        else None
    )

    return {
        "j16_version": DAY23_J16_VERSION,
        "descriptive_baseline_only": True,
        "validation_clearance": False,
        "authoritative_retest_day": 38,
        "query_count": len(query_results),
        "observed_grades": observed_grades,
        "observed_grade_count": len(observed_grades),
        "not_graded_query_count": len(by_grade[NOT_GRADED]),
        "grade_summary": grade_summary,
        "spearman_grade_rank_vs_terminal_return_stddev": (
            None if spearman is None else f"{spearman:.6f}"
        ),
        "monotonic_nonincreasing_median_terminal_return_stddev": monotonic_nonincreasing,
        "inference_permitted": False,
        "p_values_reported": False,
        "dependence_caveat": (
            "baseline_queries_and_analogue_cases_are_not_episode_independent;_"
            "correlated_cases_can_make_grade_ordering_look_predictive"
        ),
    }
