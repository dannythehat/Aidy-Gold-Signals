"""Pure deterministic scorer for the frozen Day 53 Step 2 equivalence experiment.

This module never fetches market data, reads D1/BigQuery, or mutates research
state. The empirical loader must hand it the complete mechanically defined
common H1 universe plus one retrieval record for every mechanically selected
retrieval-query bucket. The scorer applies the frozen timestamp selectors
itself so callers cannot pre-clean the sample based on observed values.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from decimal import ROUND_CEILING, ROUND_HALF_EVEN, Decimal, InvalidOperation, localcontext
from hashlib import sha256
from typing import Any

from aidy.day53_step2_preregistration import (
    COMPARISON_POPULATION,
    COVERAGE_REQUIREMENTS,
    PASS_CRITERIA,
    STEP2_QUALIFICATION_ID,
    step2_contract_digest,
    validate_step2_result_payload,
)
from aidy.day53_step2_qualification_guard import in_frozen_threshold_region
from aidy.market_sessions import new_york_utc_offset_hours, session_code_at
from aidy.regime_classifier import classify_volatility_band

SCORER_VERSION = "aidy_day53_step2_equivalence_scorer_v1"
QUALIFICATION_SELECTOR_PREFIX = "aidy-day53-step2-v1|"
RETRIEVAL_SELECTOR_PREFIX = "aidy-day53-step2-v1|retrieval|"
_RATE_SCALE = Decimal("0.000001")
_Z_95 = Decimal("1.959963984540054")

_FORBIDDEN_EMPIRICAL_KEYS = {
    "future_return",
    "future_returns",
    "pnl",
    "realized_pnl",
    "profit",
    "loss",
    "winner",
    "loser",
    "trade_result",
    "trade_results",
    "target_hit",
    "stop_hit",
    "mfe",
    "mae",
    "outcome",
    "outcome_label",
    "outcome_state",
}


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest(value: object) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _utc(value: datetime | str) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError("Step 2 scorer timestamps must be timezone-aware.")
    return parsed.astimezone(UTC)


def _decimal(value: object, *, label: str) -> Decimal:
    if value is None or isinstance(value, bool):
        raise ValueError(f"{label} must be a finite non-negative decimal.")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{label} must be a finite non-negative decimal.") from exc
    if not parsed.is_finite() or parsed < 0:
        raise ValueError(f"{label} must be a finite non-negative decimal.")
    return parsed


def _digest64(value: object, *, label: str) -> str:
    text = str(value or "").lower()
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise ValueError(f"{label} must be a 64-character SHA-256 digest.")
    return text


def _assert_no_outcome_fields(value: Any, *, path: str) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).strip().lower()
            if normalized in _FORBIDDEN_EMPIRICAL_KEYS:
                raise ValueError(f"Outcome/P&L field is forbidden at {path}.{key}.")
            _assert_no_outcome_fields(item, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _assert_no_outcome_fields(item, path=f"{path}[{index}]")


def _render(value: Decimal | None) -> str | None:
    if value is None:
        return None
    quantized = value.quantize(_RATE_SCALE, rounding=ROUND_HALF_EVEN)
    return format(quantized, "f")


def _rate(successes: int, total: int) -> Decimal | None:
    if total <= 0:
        return None
    return Decimal(successes) / Decimal(total)


def wilson_95(successes: int, total: int) -> tuple[Decimal | None, Decimal | None]:
    """Two-sided Wilson score 95% interval, evaluated deterministically in Decimal."""

    if total <= 0:
        return None, None
    if successes < 0 or successes > total:
        raise ValueError("Wilson successes must be between zero and total.")
    with localcontext() as ctx:
        ctx.prec = 50
        n = Decimal(total)
        p = Decimal(successes) / n
        z2 = _Z_95 * _Z_95
        denominator = Decimal(1) + z2 / n
        center = (p + z2 / (Decimal(2) * n)) / denominator
        radius = (
            _Z_95
            * ((p * (Decimal(1) - p) / n) + z2 / (Decimal(4) * n * n)).sqrt()
            / denominator
        )
        return max(Decimal(0), center - radius), min(Decimal(1), center + radius)


def nearest_rank(values: Iterable[Decimal], percentile: Decimal) -> Decimal | None:
    items = sorted(values)
    if not items:
        return None
    if not Decimal(0) < percentile <= Decimal(1):
        raise ValueError("Nearest-rank percentile must lie in (0,1].")
    rank = max(
        1,
        int((percentile * Decimal(len(items))).to_integral_value(rounding=ROUND_CEILING)),
    )
    return items[rank - 1]


def _selector(prefix: str, bucket_end_utc: datetime) -> bool:
    stamp = _utc(bucket_end_utc).isoformat()
    integer = int(sha256(f"{prefix}{stamp}".encode("utf-8")).hexdigest(), 16)
    return integer % 4 == 0


def is_qualification_bucket(bucket_end_utc: datetime | str) -> bool:
    return _selector(QUALIFICATION_SELECTOR_PREFIX, _utc(bucket_end_utc))


def is_retrieval_bucket(bucket_end_utc: datetime | str) -> bool:
    return _selector(RETRIEVAL_SELECTOR_PREFIX, _utc(bucket_end_utc))


def _common_window() -> tuple[datetime, datetime]:
    start = _utc(COMPARISON_POPULATION["historical_bucket_end_start_utc_inclusive"])
    end = _utc(COMPARISON_POPULATION["historical_bucket_end_cutoff_utc_inclusive"])
    return start, end


def structural_retrieval_session_capacity() -> dict[str, Any]:
    """Upper-bound exact-session query counts before any market values are inspected.

    Every UTC hour in the frozen population window is treated as pairable. Real
    source-native completeness can only remove timestamps, never add them, so
    these counts are strict upper bounds for the registered nested hash subset.
    """

    start, end = _common_window()
    counts = {
        "asia": 0,
        "london": 0,
        "new_york": 0,
        "london_new_york_overlap": 0,
        "off_hours": 0,
        "weekend": 0,
    }
    nested = 0
    cursor = start
    while cursor <= end:
        if is_qualification_bucket(cursor) and is_retrieval_bucket(cursor):
            nested += 1
            label = session_code_at(cursor)
            counts[label] = counts.get(label, 0) + 1
        cursor += timedelta(hours=1)

    required = COVERAGE_REQUIREMENTS["minimum_session_query_count_each"]
    blockers = {
        label: {
            "maximum_possible": counts[label],
            "required": int(required[label]),
        }
        for label in ("asia", "london", "new_york")
        if counts[label] < int(required[label])
    }
    result = {
        "population_start_utc": start.isoformat(),
        "population_end_utc": end.isoformat(),
        "assumption": "every_frozen_utc_hour_is_pairable_upper_bound",
        "nested_selector_timestamp_count": nested,
        "exact_session_label_upper_bounds": counts,
        "registered_minimum_session_query_count_each": {
            key: int(value) for key, value in required.items()
        },
        "structural_blockers": blockers,
        "market_values_inspected": False,
    }
    result["capacity_digest"] = digest(result)
    return result


def _availability(row: Mapping[str, Any], key: str) -> bool:
    value = row.get(key)
    if not isinstance(value, bool):
        raise TypeError(f"{key} must be boolean.")
    return value


def _normalize_feature_rows(
    rows: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    start, end = _common_window()
    normalized: list[dict[str, Any]] = []
    seen: set[datetime] = set()
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise TypeError("Step 2 feature observations must be objects.")
        _assert_no_outcome_fields(raw, path="feature_observation")
        bucket_end = _utc(str(raw.get("h1_bucket_end_utc") or ""))
        if not start <= bucket_end <= end:
            raise ValueError("Step 2 feature bucket lies outside the frozen comparison window.")
        if bucket_end.minute != 0 or bucket_end.second != 0 or bucket_end.microsecond != 0:
            raise ValueError("Step 2 H1 bucket end must be exactly UTC-hour aligned.")
        if bucket_end in seen:
            raise ValueError("Step 2 feature universe contains a duplicate H1 bucket end.")
        seen.add(bucket_end)
        if raw.get("mechanically_common_scheduled_h1") is not True:
            raise ValueError(
                "Scorer accepts only rows explicitly marked mechanically_common_scheduled_h1=true."
            )
        hist_available = _availability(raw, "histdata_feature_available")
        twelve_available = _availability(raw, "twelve_feature_available")
        hist_atr = (
            _decimal(raw.get("histdata_h1_atr_14_bps"), label="histdata_h1_atr_14_bps")
            if hist_available
            else None
        )
        twelve_atr = (
            _decimal(raw.get("twelve_h1_atr_14_bps"), label="twelve_h1_atr_14_bps")
            if twelve_available
            else None
        )
        if not hist_available and raw.get("histdata_h1_atr_14_bps") is not None:
            raise ValueError("Unavailable HistData feature must not carry an ATR value.")
        if not twelve_available and raw.get("twelve_h1_atr_14_bps") is not None:
            raise ValueError("Unavailable Twelve feature must not carry an ATR value.")
        normalized.append(
            {
                "h1_bucket_end_utc": bucket_end,
                "histdata_feature_available": hist_available,
                "twelve_feature_available": twelve_available,
                "histdata_h1_atr_14_bps": hist_atr,
                "twelve_h1_atr_14_bps": twelve_atr,
            }
        )
    normalized.sort(key=lambda item: item["h1_bucket_end_utc"])
    if not normalized:
        raise ValueError("Step 2 scorer requires a non-empty common scheduled H1 universe.")
    return normalized


def _normalize_retrieval_rows(
    rows: Iterable[Mapping[str, Any]],
) -> dict[datetime, dict[str, Any]]:
    result: dict[datetime, dict[str, Any]] = {}
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise TypeError("Step 2 retrieval comparisons must be objects.")
        _assert_no_outcome_fields(raw, path="retrieval_comparison")
        bucket_end = _utc(str(raw.get("h1_bucket_end_utc") or ""))
        if bucket_end in result:
            raise ValueError("Step 2 retrieval comparisons contain a duplicate H1 bucket end.")
        query_available = raw.get("query_available")
        if not isinstance(query_available, bool):
            raise TypeError("query_available must be boolean.")
        item: dict[str, Any] = {
            "h1_bucket_end_utc": bucket_end,
            "query_available": query_available,
        }
        if query_available:
            query_id = str(raw.get("query_id") or "").strip()
            if not query_id:
                raise ValueError("Available Step 2 retrieval comparison requires query_id.")
            baseline_ids = raw.get("baseline_selected_episode_ids")
            comparison_ids = raw.get("comparison_selected_episode_ids")
            if not isinstance(baseline_ids, list) or not isinstance(comparison_ids, list):
                raise TypeError("Selected episode ids must be lists.")
            baseline = [str(value) for value in baseline_ids]
            comparison = [str(value) for value in comparison_ids]
            if len(set(baseline)) != len(baseline) or len(set(comparison)) != len(comparison):
                raise ValueError("Selected episode ids must be unique within each retrieval.")
            baseline_grade = str(raw.get("baseline_evidence_grade") or "").strip()
            comparison_grade = str(raw.get("comparison_evidence_grade") or "").strip()
            if not baseline_grade or not comparison_grade:
                raise ValueError("Available retrieval comparison requires both evidence grades.")
            hard_gate_pairs = raw.get("hard_gate_boolean_pairs")
            if not isinstance(hard_gate_pairs, list):
                raise TypeError("hard_gate_boolean_pairs must be a list.")
            normalized_pairs: list[tuple[bool, bool]] = []
            for pair in hard_gate_pairs:
                if (
                    not isinstance(pair, Mapping)
                    or not isinstance(pair.get("baseline"), bool)
                    or not isinstance(pair.get("comparison"), bool)
                ):
                    raise TypeError(
                        "Each hard-gate pair requires boolean baseline and comparison values."
                    )
                normalized_pairs.append((pair["baseline"], pair["comparison"]))
            item.update(
                {
                    "query_id": query_id,
                    "baseline_selected_episode_ids": baseline,
                    "comparison_selected_episode_ids": comparison,
                    "baseline_evidence_grade": baseline_grade,
                    "comparison_evidence_grade": comparison_grade,
                    "hard_gate_boolean_pairs": normalized_pairs,
                }
            )
        result[bucket_end] = item
    return result


def _set_jaccard(left: list[str], right: list[str]) -> Decimal:
    lhs, rhs = set(left), set(right)
    union = lhs | rhs
    if not union:
        raise ValueError("Jaccard is undefined for empty/empty retrievals.")
    return Decimal(len(lhs & rhs)) / Decimal(len(union))


def _criterion(
    observed: Decimal | None,
    *,
    threshold: str,
    comparison: str,
) -> bool | None:
    if observed is None:
        return None
    bound = Decimal(threshold)
    if comparison == "gte":
        return observed >= bound
    if comparison == "lte":
        return observed <= bound
    raise RuntimeError("Unknown Step 2 criterion comparison.")


def _metric(observed: Decimal | None, passed: bool | None) -> dict[str, Any]:
    return {"observed": _render(observed), "pass": passed}


def decide_outcome(
    *,
    minimum_requirements: Mapping[str, bool],
    mandatory_criteria: Mapping[str, Mapping[str, Any]],
    required_statistics_available: bool,
    structural_blockers: Mapping[str, Any] | None = None,
) -> str:
    """Apply the frozen conjunctive outcome rule without a composite score."""

    if structural_blockers or not required_statistics_available or not all(
        minimum_requirements.values()
    ):
        return "insufficient_evidence"
    if all(item.get("pass") is True for item in mandatory_criteria.values()):
        return "pass"
    return "fail"


def structural_preflight_result() -> dict[str, Any]:
    """Return a terminal INSUFFICIENT result when frozen mechanics make coverage impossible."""

    capacity = structural_retrieval_session_capacity()
    blockers = capacity["structural_blockers"]
    if not blockers:
        return {
            "terminal": False,
            "state": "empirical_values_required",
            "qualification_id": STEP2_QUALIFICATION_ID,
            "contract_digest": step2_contract_digest(),
            "structural_capacity": capacity,
            "market_values_inspected": False,
        }

    evidence = {
        "scorer_version": SCORER_VERSION,
        "qualification_id": STEP2_QUALIFICATION_ID,
        "contract_digest": step2_contract_digest(),
        "structural_retrieval_session_capacity": capacity,
        "terminal_reason": "registered_minimum_session_query_count_is_structurally_unreachable",
        "candidate_universe_loaded": False,
        "market_values_inspected": False,
        "empirical_scoring_performed": False,
        "outcome_fields_used": False,
    }
    result = {
        "terminal": True,
        "qualification_id": STEP2_QUALIFICATION_ID,
        "contract_digest": step2_contract_digest(),
        "outcome": "insufficient_evidence",
        "inheritance_allowed": False,
        "cross_source_retrieval_permission": False,
        "evidence_digest": digest(evidence),
        "evidence": evidence,
    }
    result["result_digest"] = digest(result)
    validate_step2_result_payload(result)
    return result


def evaluate_step2_equivalence(
    *,
    common_h1_observations: Iterable[Mapping[str, Any]],
    retrieval_comparisons: Iterable[Mapping[str, Any]],
    candidate_universe_digest: str,
) -> dict[str, Any]:
    """Score exactly one frozen Step 2 run without fetching or mutating anything."""

    candidate_digest = _digest64(candidate_universe_digest, label="candidate_universe_digest")
    feature_rows = _normalize_feature_rows(common_h1_observations)
    retrieval_by_bucket = _normalize_retrieval_rows(retrieval_comparisons)

    paired_all = [
        row
        for row in feature_rows
        if row["histdata_feature_available"] and row["twelve_feature_available"]
    ]
    paired_coverage = _rate(len(paired_all), len(feature_rows))

    qualification_rows = [
        row for row in feature_rows if is_qualification_bucket(row["h1_bucket_end_utc"])
    ]
    paired_qualification = [
        row
        for row in qualification_rows
        if row["histdata_feature_available"] and row["twelve_feature_available"]
    ]
    feature_availability_agreement = _rate(
        sum(
            row["histdata_feature_available"] == row["twelve_feature_available"]
            for row in qualification_rows
        ),
        len(qualification_rows),
    )

    paired_values: list[dict[str, Any]] = []
    for row in paired_qualification:
        hist = row["histdata_h1_atr_14_bps"]
        twelve = row["twelve_h1_atr_14_bps"]
        assert isinstance(hist, Decimal) and isinstance(twelve, Decimal)
        hist_band = classify_volatility_band(hist)
        twelve_band = classify_volatility_band(twelve)
        paired_values.append(
            {
                **row,
                "hist_band": hist_band,
                "twelve_band": twelve_band,
                "abs_diff": abs(hist - twelve),
            }
        )

    band_agree_n = sum(row["hist_band"] == row["twelve_band"] for row in paired_values)
    band_agreement = _rate(band_agree_n, len(paired_values))
    band_wilson_lower, _ = wilson_95(band_agree_n, len(paired_values))

    threshold_metrics: dict[str, dict[str, Any]] = {}
    threshold_raw: dict[str, tuple[Decimal | None, Decimal | None]] = {}
    threshold_counts: dict[str, int] = {}
    for threshold in (Decimal(20), Decimal(50)):
        near = [
            row
            for row in paired_values
            if in_frozen_threshold_region(
                histdata_h1_atr_14_bps=row["histdata_h1_atr_14_bps"],
                twelve_data_h1_atr_14_bps=row["twelve_h1_atr_14_bps"],
                threshold_bps=threshold,
            )
        ]
        disagreements = sum(row["hist_band"] != row["twelve_band"] for row in near)
        disagreement_rate = _rate(disagreements, len(near))
        _, disagreement_wilson_upper = wilson_95(disagreements, len(near))
        key = str(threshold)
        threshold_counts[key] = len(near)
        threshold_raw[key] = (disagreement_rate, disagreement_wilson_upper)
        threshold_metrics[key] = {
            "observation_count": len(near),
            "disagreement_rate": _render(disagreement_rate),
            "disagreement_wilson_95_upper": _render(disagreement_wilson_upper),
        }

    setup_predicate_total = len(paired_values) * 4
    setup_predicate_agree = 0
    for row in paired_values:
        hist_band = row["hist_band"]
        twelve_band = row["twelve_band"]
        hist_predicates = (
            hist_band == "low",
            hist_band == "low",
            hist_band == "high",
            hist_band == "high",
        )
        twelve_predicates = (
            twelve_band == "low",
            twelve_band == "low",
            twelve_band == "high",
            twelve_band == "high",
        )
        setup_predicate_agree += sum(
            left == right for left, right in zip(hist_predicates, twelve_predicates, strict=True)
        )
    setup_predicate_agreement = _rate(setup_predicate_agree, setup_predicate_total)

    offsets: dict[int, set[str]] = {-5: set(), -4: set()}
    ny_dates: set[str] = set()
    for row in paired_qualification:
        stamp = row["h1_bucket_end_utc"]
        offset = new_york_utc_offset_hours(stamp)
        local = stamp + timedelta(hours=offset)
        ny_dates.add(local.date().isoformat())
        if offset in offsets:
            offsets[offset].add(local.date().isoformat())

    expected_retrieval_buckets = [
        row["h1_bucket_end_utc"]
        for row in paired_qualification
        if is_retrieval_bucket(row["h1_bucket_end_utc"])
    ]
    expected_set = set(expected_retrieval_buckets)
    unexpected = sorted(set(retrieval_by_bucket) - expected_set)
    if unexpected:
        raise ValueError("Retrieval comparison supplied for a non-preregistered query bucket.")
    missing = sorted(expected_set - set(retrieval_by_bucket))
    if missing:
        raise ValueError(
            "Every mechanically selected retrieval bucket must be represented, "
            "including unavailable queries."
        )

    available_queries = [
        retrieval_by_bucket[bucket]
        for bucket in expected_retrieval_buckets
        if retrieval_by_bucket[bucket]["query_available"]
    ]
    sessions = {"asia": 0, "london": 0, "new_york": 0}
    for item in available_queries:
        label = session_code_at(item["h1_bucket_end_utc"])
        if label in sessions:
            sessions[label] += 1

    state_agree = 0
    both_nonempty = 0
    jaccards: list[Decimal] = []
    top_agree = 0
    count_diff_le_1 = 0
    grade_agree = 0
    hard_gate_total = 0
    hard_gate_agree = 0
    for item in available_queries:
        baseline = item["baseline_selected_episode_ids"]
        comparison = item["comparison_selected_episode_ids"]
        baseline_nonempty = bool(baseline)
        comparison_nonempty = bool(comparison)
        state_agree += baseline_nonempty == comparison_nonempty
        if baseline_nonempty and comparison_nonempty:
            both_nonempty += 1
            top_agree += baseline[0] == comparison[0]
        if baseline_nonempty or comparison_nonempty:
            jaccards.append(_set_jaccard(baseline, comparison))
        count_diff_le_1 += abs(len(baseline) - len(comparison)) <= 1
        grade_agree += item["baseline_evidence_grade"] == item["comparison_evidence_grade"]
        pairs = item["hard_gate_boolean_pairs"]
        hard_gate_total += len(pairs)
        hard_gate_agree += sum(left == right for left, right in pairs)

    query_count = len(available_queries)
    state_agreement = _rate(state_agree, query_count)
    state_wilson_lower, _ = wilson_95(state_agree, query_count)
    jaccard_median = nearest_rank(jaccards, Decimal("0.50"))
    jaccard_p10 = nearest_rank(jaccards, Decimal("0.10"))
    top_agreement = _rate(top_agree, both_nonempty)
    top_wilson_lower, _ = wilson_95(top_agree, both_nonempty)
    count_diff_rate = _rate(count_diff_le_1, query_count)
    grade_agreement = _rate(grade_agree, query_count)
    grade_wilson_lower, _ = wilson_95(grade_agree, query_count)
    hard_gate_agreement = _rate(hard_gate_agree, hard_gate_total)
    hard_gate_wilson_lower, _ = wilson_95(hard_gate_agree, hard_gate_total)

    abs_differences = [row["abs_diff"] for row in paired_values]
    distribution = {
        "paired_h1_atr_14_bps_absolute_difference": {
            "median": _render(nearest_rank(abs_differences, Decimal("0.50"))),
            "p95": _render(nearest_rank(abs_differences, Decimal("0.95"))),
            "maximum": _render(max(abs_differences) if abs_differences else None),
        }
    }

    minimums = {
        "paired_h1_qualification_observations": len(paired_qualification)
        >= int(COVERAGE_REQUIREMENTS["minimum_paired_h1_qualification_observations"]),
        "distinct_new_york_trading_dates": len(ny_dates)
        >= int(COVERAGE_REQUIREMENTS["minimum_distinct_new_york_trading_dates"]),
        "distinct_est_dates": len(offsets[-5])
        >= int(
            COVERAGE_REQUIREMENTS["minimum_distinct_dates_by_new_york_utc_offset"][
                "EST_minus_05_00"
            ]
        ),
        "distinct_edt_dates": len(offsets[-4])
        >= int(
            COVERAGE_REQUIREMENTS["minimum_distinct_dates_by_new_york_utc_offset"][
                "EDT_minus_04_00"
            ]
        ),
        "near_20_observations": threshold_counts["20"]
        >= int(
            COVERAGE_REQUIREMENTS["minimum_threshold_near_observations"][
                "20_bps_either_source_within_plus_minus_5_bps"
            ]
        ),
        "near_50_observations": threshold_counts["50"]
        >= int(
            COVERAGE_REQUIREMENTS["minimum_threshold_near_observations"][
                "50_bps_either_source_within_plus_minus_5_bps"
            ]
        ),
        "retrieval_query_count": query_count
        >= int(COVERAGE_REQUIREMENTS["minimum_retrieval_query_count"]),
        "both_retrievals_non_empty": both_nonempty
        >= int(COVERAGE_REQUIREMENTS["minimum_queries_with_both_retrievals_non_empty"]),
        "asia_query_count": sessions["asia"]
        >= int(COVERAGE_REQUIREMENTS["minimum_session_query_count_each"]["asia"]),
        "london_query_count": sessions["london"]
        >= int(COVERAGE_REQUIREMENTS["minimum_session_query_count_each"]["london"]),
        "new_york_query_count": sessions["new_york"]
        >= int(COVERAGE_REQUIREMENTS["minimum_session_query_count_each"]["new_york"]),
        "paired_feature_coverage": paired_coverage
        is not None
        and paired_coverage
        >= Decimal(
            COVERAGE_REQUIREMENTS["minimum_pairing_coverage_of_common_scheduled_h1_buckets"]
        ),
    }

    criteria: dict[str, dict[str, Any]] = {}
    criteria["paired_feature_availability_agreement"] = _metric(
        feature_availability_agreement,
        _criterion(
            feature_availability_agreement,
            threshold=PASS_CRITERIA["paired_feature_availability_agreement_rate_gte"],
            comparison="gte",
        ),
    )
    criteria["volatility_band_three_class_agreement"] = _metric(
        band_agreement,
        _criterion(
            band_agreement,
            threshold=PASS_CRITERIA["volatility_band_three_class_agreement_rate_gte"],
            comparison="gte",
        ),
    )
    criteria["volatility_band_agreement_wilson_95_lower"] = _metric(
        band_wilson_lower,
        _criterion(
            band_wilson_lower,
            threshold=PASS_CRITERIA["volatility_band_agreement_wilson_95_lower_gte"],
            comparison="gte",
        ),
    )
    for threshold in ("20", "50"):
        observed_rate, observed_upper = threshold_raw[threshold]
        criteria[f"threshold_{threshold}_disagreement_rate"] = _metric(
            observed_rate,
            _criterion(
                observed_rate,
                threshold=PASS_CRITERIA["threshold_near_each_band_disagreement_rate_lte"],
                comparison="lte",
            ),
        )
        criteria[f"threshold_{threshold}_disagreement_wilson_95_upper"] = _metric(
            observed_upper,
            _criterion(
                observed_upper,
                threshold=PASS_CRITERIA[
                    "threshold_near_each_band_disagreement_wilson_95_upper_lte"
                ],
                comparison="lte",
            ),
        )
    criteria["v2_volatility_hard_gate_agreement"] = _metric(
        hard_gate_agreement,
        _criterion(
            hard_gate_agreement,
            threshold=PASS_CRITERIA["v2_volatility_hard_gate_agreement_rate_gte"],
            comparison="gte",
        ),
    )
    criteria["v2_volatility_hard_gate_agreement_wilson_95_lower"] = _metric(
        hard_gate_wilson_lower,
        _criterion(
            hard_gate_wilson_lower,
            threshold=PASS_CRITERIA["v2_volatility_hard_gate_agreement_wilson_95_lower_gte"],
            comparison="gte",
        ),
    )
    criteria["volatility_setup_band_predicate_agreement"] = _metric(
        setup_predicate_agreement,
        _criterion(
            setup_predicate_agreement,
            threshold=PASS_CRITERIA["volatility_setup_band_predicate_agreement_rate_gte"],
            comparison="gte",
        ),
    )
    criteria["retrieval_empty_nonempty_state_agreement"] = _metric(
        state_agreement,
        _criterion(
            state_agreement,
            threshold=PASS_CRITERIA["retrieval_empty_nonempty_state_agreement_rate_gte"],
            comparison="gte",
        ),
    )
    criteria["retrieval_state_agreement_wilson_95_lower"] = _metric(
        state_wilson_lower,
        _criterion(
            state_wilson_lower,
            threshold=PASS_CRITERIA["retrieval_state_agreement_wilson_95_lower_gte"],
            comparison="gte",
        ),
    )
    criteria["selected_episode_jaccard_median"] = _metric(
        jaccard_median,
        _criterion(
            jaccard_median,
            threshold=PASS_CRITERIA["selected_episode_jaccard_median_gte"],
            comparison="gte",
        ),
    )
    criteria["selected_episode_jaccard_p10"] = _metric(
        jaccard_p10,
        _criterion(
            jaccard_p10,
            threshold=PASS_CRITERIA["selected_episode_jaccard_p10_gte"],
            comparison="gte",
        ),
    )
    criteria["top_ranked_selected_episode_agreement"] = _metric(
        top_agreement,
        _criterion(
            top_agreement,
            threshold=PASS_CRITERIA["top_ranked_selected_episode_agreement_rate_gte"],
            comparison="gte",
        ),
    )
    criteria["top_rank_agreement_wilson_95_lower"] = _metric(
        top_wilson_lower,
        _criterion(
            top_wilson_lower,
            threshold=PASS_CRITERIA["top_rank_agreement_wilson_95_lower_gte"],
            comparison="gte",
        ),
    )
    criteria["selected_episode_count_abs_diff_le_1_rate"] = _metric(
        count_diff_rate,
        _criterion(
            count_diff_rate,
            threshold=PASS_CRITERIA["selected_episode_count_abs_diff_le_1_rate_gte"],
            comparison="gte",
        ),
    )
    criteria["evidence_grade_agreement"] = _metric(
        grade_agreement,
        _criterion(
            grade_agreement,
            threshold=PASS_CRITERIA["evidence_grade_agreement_rate_gte"],
            comparison="gte",
        ),
    )
    criteria["evidence_grade_agreement_wilson_95_lower"] = _metric(
        grade_wilson_lower,
        _criterion(
            grade_wilson_lower,
            threshold=PASS_CRITERIA["evidence_grade_agreement_wilson_95_lower_gte"],
            comparison="gte",
        ),
    )

    required_statistics_available = all(item["pass"] is not None for item in criteria.values())
    structural_capacity = structural_retrieval_session_capacity()
    outcome = decide_outcome(
        minimum_requirements=minimums,
        mandatory_criteria=criteria,
        required_statistics_available=required_statistics_available,
        structural_blockers=structural_capacity["structural_blockers"],
    )

    evidence = {
        "scorer_version": SCORER_VERSION,
        "structural_retrieval_session_capacity": structural_capacity,
        "qualification_id": STEP2_QUALIFICATION_ID,
        "contract_digest": step2_contract_digest(),
        "candidate_universe_digest": candidate_digest,
        "common_scheduled_h1_bucket_count": len(feature_rows),
        "paired_feature_count": len(paired_all),
        "paired_feature_coverage": _render(paired_coverage),
        "qualification_selector_bucket_count": len(qualification_rows),
        "paired_h1_qualification_observations": len(paired_qualification),
        "distinct_new_york_trading_dates": len(ny_dates),
        "distinct_est_dates": len(offsets[-5]),
        "distinct_edt_dates": len(offsets[-4]),
        "expected_retrieval_query_bucket_count": len(expected_retrieval_buckets),
        "available_retrieval_query_count": query_count,
        "queries_with_both_retrievals_non_empty": both_nonempty,
        "session_query_counts": sessions,
        "hard_gate_boolean_comparison_count": hard_gate_total,
        "threshold_regions": threshold_metrics,
        "distribution_metrics": distribution,
        "minimum_requirements": minimums,
        "required_statistics_available": required_statistics_available,
        "mandatory_criteria": criteria,
        "decision_rule": "logical_conjunction_all_mandatory_criteria",
        "composite_score_used": False,
        "outcome_fields_used": False,
    }
    evidence_digest = digest(evidence)
    result = {
        "qualification_id": STEP2_QUALIFICATION_ID,
        "contract_digest": step2_contract_digest(),
        "outcome": outcome,
        "inheritance_allowed": outcome == "pass",
        "cross_source_retrieval_permission": False,
        "evidence_digest": evidence_digest,
        "evidence": evidence,
    }
    result["result_digest"] = digest(result)
    validate_step2_result_payload(result)
    return result
