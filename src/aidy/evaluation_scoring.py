from __future__ import annotations

import copy
import json
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation, localcontext
from hashlib import sha256
from statistics import median
from typing import Any

from aidy.setup_detector import SETUP_DEFINITIONS, SETUP_TAXONOMY_VERSION, taxonomy_manifest

EVALUATION_SCORER_VERSION = "aidy_judgement_evaluation_scorer_v1"
J16_POST_HARDENING_VERSION = "aidy_j16_post_hardening_grade_validity_v1"
RISK_COVERAGE_VERSION = "aidy_episode_risk_coverage_v1"
J21_SETUP_DIFFERENTIATION_VERSION = "aidy_j21_setup_taxonomy_differentiation_v1"
HUMAN_CALIBRATION_VERSION = "aidy_human_grader_calibration_v1"
EVALUATION_MANIFEST_VERSION = "aidy_day38_evaluation_manifest_v1"

EPISODE_HORIZON_MINUTES = 240
J16_MIN_EFFECTIVE_N_PER_GRADE = 10
J16_MIN_TEMPORAL_SPAN_DAYS = Decimal(30)
J16_MIN_EVALUABLE_GRADES = 2
J21_MIN_EFFECTIVE_N_PER_SETUP = 10
J21_MIN_SUFFICIENT_SETUPS = 2
J21_MIN_CONTROL_STRATUM_N = 2
J21_PRACTICAL_EFFECT_THRESHOLD = Decimal("0.25")

GRADE_ORDER = (
    "insufficient",
    "exploratory",
    "moderate_evidence",
    "established_dataset",
)
REQUIRED_SCORE_DIMENSIONS = (
    "grounding",
    "schema_safety",
    "setup_direction_consistency",
    "factual_accuracy",
    "restraint_no_trade",
    "stability_disagreement",
    "thesis_invalidation",
    "outcome_dispersion",
)
OBJECTIVE_METHOD = "deterministic"
SUBJECTIVE_METHOD = "human_calibrated_subjective"
_ALLOWED_METHODS = {OBJECTIVE_METHOD, SUBJECTIVE_METHOD}


class EvaluationIntegrityError(ValueError):
    pass


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest(value: object) -> str:
    return sha256(canonical_json(value).encode()).hexdigest()


def _utc(value: datetime | str, *, name: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip())
        except ValueError as exc:
            raise EvaluationIntegrityError(
                f"{name} must be timezone-aware ISO-8601 text."
            ) from exc
    else:
        raise TypeError(f"{name} must be a timezone-aware datetime or ISO-8601 string.")
    if parsed.tzinfo is None:
        raise EvaluationIntegrityError(f"{name} must be timezone-aware.")
    return parsed.astimezone(UTC)


def _decimal(value: Any, *, name: str) -> Decimal:
    if value is None or isinstance(value, bool):
        raise EvaluationIntegrityError(f"{name} must be a finite number.")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise EvaluationIntegrityError(f"{name} must be a finite number.") from exc
    if not parsed.is_finite():
        raise EvaluationIntegrityError(f"{name} must be a finite number.")
    return parsed


def _q(value: Decimal | None, places: str = "0.000000") -> str | None:
    if value is None:
        return None
    return str(value.quantize(Decimal(places)))


def _median(values: Sequence[Decimal]) -> Decimal | None:
    return Decimal(str(median(values))) if values else None


def _population_stddev(values: Sequence[Decimal]) -> Decimal | None:
    if not values:
        return None
    mean = sum(values, Decimal(0)) / Decimal(len(values))
    variance = sum(
        ((item - mean) ** 2 for item in values), Decimal(0)
    ) / Decimal(len(values))
    return variance.sqrt()


def _rank(values: Sequence[Decimal]) -> list[Decimal]:
    ordered = sorted(enumerate(values), key=lambda item: (item[1], item[0]))
    ranks = [Decimal(0)] * len(values)
    index = 0
    while index < len(ordered):
        stop = index + 1
        while stop < len(ordered) and ordered[stop][1] == ordered[index][1]:
            stop += 1
        average = (Decimal(index + 1) + Decimal(stop)) / Decimal(2)
        for position in range(index, stop):
            ranks[ordered[position][0]] = average
        index = stop
    return ranks


def _pearson(left: Sequence[Decimal], right: Sequence[Decimal]) -> Decimal | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    mean_left = sum(left, Decimal(0)) / Decimal(len(left))
    mean_right = sum(right, Decimal(0)) / Decimal(len(right))
    num = sum(
        (
            (a - mean_left) * (b - mean_right)
            for a, b in zip(left, right, strict=True)
        ),
        Decimal(0),
    )
    den_left = sum(((a - mean_left) ** 2 for a in left), Decimal(0))
    den_right = sum(((b - mean_right) ** 2 for b in right), Decimal(0))
    if den_left == 0 or den_right == 0:
        return None
    with localcontext() as ctx:
        ctx.prec = 34
        return num / (den_left * den_right).sqrt()


def _spearman(left: Sequence[Decimal], right: Sequence[Decimal]) -> Decimal | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    return _pearson(_rank(left), _rank(right))


def _dedupe_exact_episode_rows(
    rows: Iterable[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    raw = []
    by_episode: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(rows):
        if not isinstance(item, Mapping):
            raise TypeError(f"rows[{index}] must be a mapping.")
        row = copy.deepcopy(dict(item))
        episode_id = str(row.get("episode_id") or "").strip()
        if not episode_id:
            raise EvaluationIntegrityError("Every evaluation row requires episode_id.")
        raw.append(row)
        existing = by_episode.get(episode_id)
        if existing is not None and canonical_json(existing) != canonical_json(row):
            raise EvaluationIntegrityError(f"Conflicting duplicate episode row: {episode_id}")
        by_episode[episode_id] = row
    return [by_episode[key] for key in sorted(by_episode)], len(raw)


def build_human_calibration_record(
    *,
    dimension: str,
    calibration_identity: str,
    human_reviewed_n: int,
    reviewer_protocol_digest: str,
    agreement_rate: Any,
    accepted: bool,
) -> dict[str, Any]:
    if dimension not in REQUIRED_SCORE_DIMENSIONS:
        raise EvaluationIntegrityError("Calibration dimension is unsupported.")
    if (
        isinstance(human_reviewed_n, bool)
        or not isinstance(human_reviewed_n, int)
        or human_reviewed_n <= 0
    ):
        raise EvaluationIntegrityError("human_reviewed_n must be a positive integer.")
    agreement = _decimal(agreement_rate, name="agreement_rate")
    if agreement < 0 or agreement > 1:
        raise EvaluationIntegrityError("agreement_rate must be between 0 and 1.")
    identity = str(calibration_identity).strip()
    protocol = str(reviewer_protocol_digest).strip()
    if not identity or not protocol:
        raise EvaluationIntegrityError(
            "Calibration identity and reviewer protocol digest are required."
        )
    if not isinstance(accepted, bool):
        raise EvaluationIntegrityError("accepted must be boolean.")
    record: dict[str, Any] = {
        "calibration_version": HUMAN_CALIBRATION_VERSION,
        "dimension": dimension,
        "calibration_identity": identity,
        "human_reviewed_n": human_reviewed_n,
        "reviewer_protocol_digest": protocol,
        "agreement_rate": _q(agreement),
        "accepted": accepted,
        "human_review_required": True,
    }
    record["calibration_digest"] = digest(record)
    return record


def verify_human_calibration_record(record: Mapping[str, Any]) -> bool:
    if not isinstance(record, Mapping):
        return False
    body = copy.deepcopy(dict(record))
    supplied = str(body.pop("calibration_digest", ""))
    try:
        if body.get("calibration_version") != HUMAN_CALIBRATION_VERSION:
            return False
        if body.get("dimension") not in REQUIRED_SCORE_DIMENSIONS:
            return False
        if body.get("human_review_required") is not True:
            return False
        if (
            not isinstance(body.get("human_reviewed_n"), int)
            or int(body["human_reviewed_n"]) <= 0
        ):
            return False
        agreement = _decimal(body.get("agreement_rate"), name="agreement_rate")
        if agreement < 0 or agreement > 1:
            return False
    except (KeyError, TypeError, ValueError):
        return False
    return bool(supplied) and supplied == digest(body)


def build_judgement_score(
    *,
    decision_id: str,
    episode_id: str,
    components: Mapping[str, Mapping[str, Any]],
    raw_n: int,
    effective_n: int,
    calibration_records: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    if set(components) != set(REQUIRED_SCORE_DIMENSIONS):
        missing = sorted(set(REQUIRED_SCORE_DIMENSIONS) - set(components))
        extra = sorted(set(components) - set(REQUIRED_SCORE_DIMENSIONS))
        raise EvaluationIntegrityError(
            f"Score dimensions must be exact; missing={missing}, extra={extra}."
        )
    if isinstance(raw_n, bool) or not isinstance(raw_n, int) or raw_n <= 0:
        raise EvaluationIntegrityError("raw_n must be a positive integer.")
    if (
        isinstance(effective_n, bool)
        or not isinstance(effective_n, int)
        or effective_n <= 0
        or effective_n > raw_n
    ):
        raise EvaluationIntegrityError(
            "effective_n must be a positive integer no greater than raw_n."
        )

    calibrations: dict[str, dict[str, Any]] = {}
    for item in calibration_records:
        if not verify_human_calibration_record(item):
            raise EvaluationIntegrityError("Invalid human calibration record.")
        dimension = str(item["dimension"])
        if dimension in calibrations:
            raise EvaluationIntegrityError(
                f"Duplicate calibration for dimension: {dimension}"
            )
        calibrations[dimension] = copy.deepcopy(dict(item))

    normalized: dict[str, Any] = {}
    subjective_dimensions: list[str] = []
    scores: list[Decimal] = []
    for dimension in REQUIRED_SCORE_DIMENSIONS:
        component = components[dimension]
        if not isinstance(component, Mapping):
            raise TypeError(f"components.{dimension} must be a mapping.")
        method = str(component.get("method") or "")
        if method not in _ALLOWED_METHODS:
            raise EvaluationIntegrityError(
                f"Unsupported scoring method for {dimension}."
            )
        score = _decimal(component.get("score"), name=f"components.{dimension}.score")
        if score < 0 or score > 1:
            raise EvaluationIntegrityError(
                f"components.{dimension}.score must be between 0 and 1."
            )
        passed = component.get("passed")
        if passed is not None and not isinstance(passed, bool):
            raise EvaluationIntegrityError(
                f"components.{dimension}.passed must be boolean or null."
            )
        if method == SUBJECTIVE_METHOD:
            subjective_dimensions.append(dimension)
            calibration = calibrations.get(dimension)
            if calibration is None or calibration.get("accepted") is not True:
                raise EvaluationIntegrityError(
                    f"Subjective scorer {dimension} requires an accepted human "
                    "calibration record."
                )
        normalized[dimension] = {
            "score": _q(score),
            "method": method,
            "passed": passed,
            "evidence_digest": str(component.get("evidence_digest") or ""),
            "calibration_digest": (
                None
                if method == OBJECTIVE_METHOD
                else calibrations[dimension]["calibration_digest"]
            ),
        }
        scores.append(score)

    gate_pass = all(
        normalized[gate]["passed"] is True for gate in ("grounding", "schema_safety")
    )
    mean_score = sum(scores, Decimal(0)) / Decimal(len(scores))
    result: dict[str, Any] = {
        "scorer_version": EVALUATION_SCORER_VERSION,
        "decision_id": str(decision_id),
        "episode_id": str(episode_id),
        "dimensions": normalized,
        "raw_n": raw_n,
        "effective_n": effective_n,
        "sample_size_basis": "episode_independent_effective_n",
        "mean_dimension_score": _q(mean_score),
        "non_compensatory_gate_pass": gate_pass,
        "quality_claim_allowed": gate_pass,
        "good_outcome_can_offset_grounding_failure": False,
        "good_outcome_can_offset_safety_failure": False,
        "subjective_dimensions": sorted(subjective_dimensions),
        "subjective_grader_authoritative_without_human_calibration": False,
    }
    result["score_digest"] = digest(result)
    return result


def _greedy_temporal_episode_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    horizon_minutes: int = EPISODE_HORIZON_MINUTES,
) -> tuple[list[dict[str, Any]], int]:
    if (
        isinstance(horizon_minutes, bool)
        or not isinstance(horizon_minutes, int)
        or horizon_minutes <= 0
    ):
        raise EvaluationIntegrityError("horizon_minutes must be a positive integer.")
    ordered = []
    for index, raw in enumerate(rows):
        if not isinstance(raw, Mapping):
            raise TypeError(f"rows[{index}] must be a mapping.")
        row = copy.deepcopy(dict(raw))
        stamp = _utc(row.get("as_of_utc"), name=f"rows[{index}].as_of_utc")
        identity = str(
            row.get("row_id") or row.get("query_id") or row.get("case_id") or ""
        ).strip()
        if not identity:
            raise EvaluationIntegrityError(
                "Temporal evaluation rows require row_id, query_id or case_id."
            )
        row["_stamp"] = stamp
        row["_identity"] = identity
        ordered.append(row)
    ordered.sort(key=lambda row: (row["_stamp"], row["_identity"]))

    selected: list[dict[str, Any]] = []
    next_allowed: datetime | None = None
    for row in ordered:
        stamp = row["_stamp"]
        if next_allowed is not None and stamp < next_allowed:
            continue
        clean = {key: value for key, value in row.items() if not key.startswith("_")}
        episode_basis = {
            "anchor_utc": stamp.isoformat(),
            "horizon_minutes": horizon_minutes,
            "identity": row["_identity"],
        }
        clean["evaluation_episode_id"] = digest(episode_basis)
        selected.append(clean)
        next_allowed = stamp + timedelta(minutes=horizon_minutes)
    return selected, len(ordered)


def _span_days(rows: Sequence[Mapping[str, Any]]) -> Decimal:
    if len(rows) < 2:
        return Decimal(0)
    stamps = [_utc(row["as_of_utc"], name="as_of_utc") for row in rows]
    return Decimal(str((max(stamps) - min(stamps)).total_seconds())) / Decimal(86400)


def build_j16_grade_validity_report(
    rows: Iterable[Mapping[str, Any]],
    *,
    evaluation_set_identity: str,
) -> dict[str, Any]:
    materialized = [copy.deepcopy(dict(row)) for row in rows]
    selected, raw_n = _greedy_temporal_episode_rows(materialized)
    raw_grade_counts: dict[str, int] = {grade: 0 for grade in GRADE_ORDER}
    for row in materialized:
        grade = str(row.get("dataset_grade") or "")
        if grade not in raw_grade_counts:
            raise EvaluationIntegrityError(f"Unsupported evidence grade in J16: {grade}")
        raw_grade_counts[grade] += 1
    grade_rows: dict[str, list[dict[str, Any]]] = {
        grade: [] for grade in GRADE_ORDER
    }
    for row in selected:
        grade = str(row.get("dataset_grade") or "")
        effective_n = int(row.get("effective_n", 0))
        if effective_n < 0:
            raise EvaluationIntegrityError("J16 query effective_n cannot be negative.")
        metric = row.get("terminal_return_stddev_bps")
        if metric is not None:
            _decimal(metric, name="terminal_return_stddev_bps")
        grade_rows[grade].append(row)

    summary: dict[str, Any] = {}
    evaluable_grades: list[str] = []
    correlation_grade: list[Decimal] = []
    correlation_dispersion: list[Decimal] = []
    medians_by_grade: list[tuple[str, Decimal]] = []

    for grade in GRADE_ORDER:
        items = grade_rows[grade]
        dispersion = [
            _decimal(item["terminal_return_stddev_bps"], name="terminal_return_stddev_bps")
            for item in items
            if item.get("terminal_return_stddev_bps") is not None
        ]
        evidence_effective = [int(item.get("effective_n", 0)) for item in items]
        span = _span_days(items)
        independent_n = len(items)
        sufficient = (
            independent_n >= J16_MIN_EFFECTIVE_N_PER_GRADE
            and span >= J16_MIN_TEMPORAL_SPAN_DAYS
            and len(dispersion) >= J16_MIN_EFFECTIVE_N_PER_GRADE
        )
        median_dispersion = _median(dispersion)
        if sufficient and median_dispersion is not None:
            evaluable_grades.append(grade)
            medians_by_grade.append((grade, median_dispersion))
            rank_value = Decimal(GRADE_ORDER.index(grade))
            for value in dispersion:
                correlation_grade.append(rank_value)
                correlation_dispersion.append(value)
        summary[grade] = {
            "raw_query_n": raw_grade_counts[grade],
            "effective_independent_query_n": independent_n,
            "median_retrieval_effective_n": (
                _q(_median([Decimal(value) for value in evidence_effective]))
                if evidence_effective
                else None
            ),
            "temporal_span_days": _q(span),
            "outcome_dispersion_n": len(dispersion),
            "median_terminal_return_stddev_bps": _q(median_dispersion),
            "median_terminal_return_iqr_bps": _q(
                _median(
                    [
                        _decimal(
                            item["terminal_return_iqr_bps"],
                            name="terminal_return_iqr_bps",
                        )
                        for item in items
                        if item.get("terminal_return_iqr_bps") is not None
                    ]
                )
            ),
            "median_terminal_return_mad_bps": _q(
                _median(
                    [
                        _decimal(
                            item["terminal_return_mad_bps"],
                            name="terminal_return_mad_bps",
                        )
                        for item in items
                        if item.get("terminal_return_mad_bps") is not None
                    ]
                )
            ),
            "sufficient_for_grade_validity_test": sufficient,
        }

    spearman = _spearman(correlation_grade, correlation_dispersion)
    monotonic = None
    if len(medians_by_grade) >= J16_MIN_EVALUABLE_GRADES:
        monotonic = all(
            medians_by_grade[index][1] <= medians_by_grade[index - 1][1]
            for index in range(1, len(medians_by_grade))
        )

    if len(evaluable_grades) < J16_MIN_EVALUABLE_GRADES:
        status = "inconclusive"
    elif monotonic is True and spearman is not None and spearman < 0:
        status = "pass"
    else:
        status = "null"

    result: dict[str, Any] = {
        "j16_version": J16_POST_HARDENING_VERSION,
        "evaluation_set_identity": str(evaluation_set_identity),
        "raw_query_n": raw_n,
        "effective_independent_query_n": len(selected),
        "query_episode_policy": "greedy_chronological_nonoverlap_240m_outcome_blind",
        "per_grade": summary,
        "evaluable_grades": evaluable_grades,
        "evaluable_grade_count": len(evaluable_grades),
        "minimum_effective_n_per_grade": J16_MIN_EFFECTIVE_N_PER_GRADE,
        "minimum_temporal_span_days": _q(J16_MIN_TEMPORAL_SPAN_DAYS),
        "spearman_grade_rank_vs_terminal_return_stddev": _q(spearman),
        "monotonic_nonincreasing_grade_median_dispersion": monotonic,
        "status": status,
        "null_result_retained": status == "null",
        "inconclusive_result_retained": status == "inconclusive",
        "day23_baseline_is_authoritative": False,
        "post_hardening_j16_is_authoritative": True,
        "predictive_edge_claimed": False,
    }
    result["j16_digest"] = digest(result)
    return result


def build_risk_coverage_report(
    rows: Iterable[Mapping[str, Any]],
    *,
    evaluation_set_identity: str,
    threshold_grid: Sequence[Any],
    threshold_grid_source: str,
) -> dict[str, Any]:
    unique, raw_n = _dedupe_exact_episode_rows(rows)
    thresholds = [_decimal(value, name="threshold_grid") for value in threshold_grid]
    if not thresholds or thresholds != sorted(set(thresholds)):
        raise EvaluationIntegrityError(
            "threshold_grid must be non-empty, unique and ascending."
        )
    if any(value < 0 or value > 1 for value in thresholds):
        raise EvaluationIntegrityError("threshold_grid values must be between 0 and 1.")
    source = str(threshold_grid_source).strip()
    if not source or ("eval" in source.lower() and "tuned" in source.lower()):
        raise EvaluationIntegrityError(
            "Risk-coverage threshold grid cannot be evaluation-tuned."
        )

    normalized: list[tuple[Decimal, bool, str]] = []
    for row in unique:
        confidence = _decimal(row.get("confidence"), name="confidence")
        if confidence < 0 or confidence > 1:
            raise EvaluationIntegrityError("confidence must be between 0 and 1.")
        adverse = row.get("adverse_outcome")
        if not isinstance(adverse, bool):
            raise EvaluationIntegrityError("adverse_outcome must be boolean.")
        normalized.append((confidence, adverse, str(row["episode_id"])))

    points = []
    denominator = len(normalized)
    for threshold in thresholds:
        selected = [item for item in normalized if item[0] >= threshold]
        selected_n = len(selected)
        adverse_n = sum(item[1] for item in selected)
        points.append(
            {
                "threshold": _q(threshold),
                "effective_selected_n": selected_n,
                "coverage": (
                    _q(Decimal(selected_n) / Decimal(denominator))
                    if denominator
                    else None
                ),
                "adverse_n": adverse_n,
                "adverse_rate": (
                    _q(Decimal(adverse_n) / Decimal(selected_n))
                    if selected_n
                    else None
                ),
            }
        )

    result: dict[str, Any] = {
        "risk_coverage_version": RISK_COVERAGE_VERSION,
        "evaluation_set_identity": str(evaluation_set_identity),
        "raw_n": raw_n,
        "effective_n": len(unique),
        "sample_size_basis": "deduplicated_episode_n",
        "threshold_grid": [_q(value) for value in thresholds],
        "threshold_grid_source": source,
        "threshold_grid_frozen_before_evaluation": True,
        "threshold_grid_digest": digest([_q(value) for value in thresholds]),
        "points": points,
        "recommended_threshold": None,
        "evaluation_set_tuning_allowed": False,
    }
    result["risk_coverage_digest"] = digest(result)
    return result


def _setup_directions() -> dict[str, str]:
    return {str(item["setup_id"]): str(item["direction"]) for item in SETUP_DEFINITIONS}


def build_j21_setup_differentiation_report(
    rows: Iterable[Mapping[str, Any]],
    *,
    evaluation_set_identity: str,
) -> dict[str, Any]:
    directions = _setup_directions()
    expected_ids = set(directions)
    if len(expected_ids) != 20 or taxonomy_manifest()["setup_count"] != 20:
        raise EvaluationIntegrityError("J21 requires the frozen 20-variant setup taxonomy.")

    prepared: list[dict[str, Any]] = []
    raw_n = 0
    for index, raw in enumerate(rows):
        if not isinstance(raw, Mapping):
            raise TypeError(f"rows[{index}] must be a mapping.")
        raw_n += 1
        row = copy.deepcopy(dict(raw))
        setup_id = str(row.get("setup_id") or "")
        if setup_id not in expected_ids:
            raise EvaluationIntegrityError(f"Unknown or non-frozen setup_id: {setup_id}")
        if str(row.get("taxonomy_version") or "") != SETUP_TAXONOMY_VERSION:
            raise EvaluationIntegrityError("J21 setup taxonomy version drifted.")
        direction = str(row.get("direction") or directions[setup_id])
        if direction != directions[setup_id]:
            raise EvaluationIntegrityError(f"Setup direction drift for {setup_id}.")
        outcome = _decimal(row.get("terminal_return_bps"), name="terminal_return_bps")
        row["direction"] = direction
        row["directional_terminal_return_bps"] = (
            outcome if direction == "long" else -outcome
        )
        prepared.append(row)

    selected, _ = _greedy_temporal_episode_rows(prepared)
    strata: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in selected:
        regime = str(row.get("regime") or "unknown")
        session = str(row.get("session") or "unknown")
        strata[(regime, session)].append(row)

    controlled: list[dict[str, Any]] = []
    for stratum, items in sorted(strata.items()):
        if len(items) < J21_MIN_CONTROL_STRATUM_N:
            continue
        mean = sum(
            (item["directional_terminal_return_bps"] for item in items), Decimal(0)
        ) / Decimal(len(items))
        for item in items:
            controlled.append(
                {
                    **item,
                    "control_stratum": f"{stratum[0]}|session={stratum[1]}",
                    "controlled_outcome_bps": item[
                        "directional_terminal_return_bps"
                    ]
                    - mean,
                }
            )

    per_setup: dict[str, Any] = {}
    sufficient_ids: list[str] = []
    controlled_values_by_setup: dict[str, list[Decimal]] = {}
    for setup_id in sorted(expected_ids):
        raw_setup_n = sum(1 for row in prepared if row["setup_id"] == setup_id)
        selected_setup = [row for row in selected if row["setup_id"] == setup_id]
        controlled_values = [
            row["controlled_outcome_bps"]
            for row in controlled
            if row["setup_id"] == setup_id
        ]
        controlled_values_by_setup[setup_id] = controlled_values
        effective_n = len(selected_setup)
        control_n = len(controlled_values)
        sufficient = (
            effective_n >= J21_MIN_EFFECTIVE_N_PER_SETUP
            and control_n >= J21_MIN_EFFECTIVE_N_PER_SETUP
        )
        if sufficient:
            sufficient_ids.append(setup_id)
        per_setup[setup_id] = {
            "raw_n": raw_setup_n,
            "effective_independent_n": effective_n,
            "controlled_effective_n": control_n,
            "controlled_mean_outcome_bps": (
                _q(sum(controlled_values, Decimal(0)) / Decimal(control_n))
                if control_n
                else None
            ),
            "controlled_outcome_stddev_bps": _q(
                _population_stddev(controlled_values)
            ),
            "state": "sufficient" if sufficient else "inconclusive",
        }

    all_sufficient_values = [
        value
        for setup_id in sufficient_ids
        for value in controlled_values_by_setup[setup_id]
    ]
    pooled_stddev = _population_stddev(all_sufficient_values)
    sufficient_means = [
        sum(controlled_values_by_setup[setup_id], Decimal(0))
        / Decimal(len(controlled_values_by_setup[setup_id]))
        for setup_id in sufficient_ids
    ]
    standardized_span = None
    if len(sufficient_means) >= 2 and pooled_stddev is not None and pooled_stddev > 0:
        standardized_span = (
            max(sufficient_means) - min(sufficient_means)
        ) / pooled_stddev

    if len(sufficient_ids) < J21_MIN_SUFFICIENT_SETUPS:
        status = "inconclusive"
    elif (
        standardized_span is not None
        and standardized_span >= J21_PRACTICAL_EFFECT_THRESHOLD
    ):
        status = "differentiated"
    else:
        status = "null"

    result: dict[str, Any] = {
        "j21_version": J21_SETUP_DIFFERENTIATION_VERSION,
        "evaluation_set_identity": str(evaluation_set_identity),
        "taxonomy_version": SETUP_TAXONOMY_VERSION,
        "taxonomy_digest": taxonomy_manifest()["taxonomy_digest"],
        "setup_variant_count": len(expected_ids),
        "raw_case_n": raw_n,
        "effective_independent_case_n": len(selected),
        "episode_policy": "greedy_chronological_nonoverlap_240m_outcome_blind",
        "control_factors": ["regime", "session"],
        "control_method": "within_regime_session_mean_residualization",
        "minimum_control_stratum_n": J21_MIN_CONTROL_STRATUM_N,
        "minimum_effective_n_per_setup": J21_MIN_EFFECTIVE_N_PER_SETUP,
        "practical_effect_threshold_standardized_span": _q(
            J21_PRACTICAL_EFFECT_THRESHOLD
        ),
        "per_setup": per_setup,
        "sufficient_setup_ids": sufficient_ids,
        "sufficient_setup_count": len(sufficient_ids),
        "pooled_controlled_stddev_bps": _q(pooled_stddev),
        "standardized_controlled_mean_span": _q(standardized_span),
        "status": status,
        "null_result_retained": status == "null",
        "inconclusive_result_retained": status == "inconclusive",
        "taxonomy_expansion_allowed": False,
        "automatic_taxonomy_consolidation_allowed": False,
        "null_is_evidence_for_later_consolidation_review": status == "null",
        "outcomes_used_to_define_setup_labels": False,
        "predictive_edge_claimed": False,
    }
    result["j21_digest"] = digest(result)
    return result


def evaluation_manifest() -> dict[str, Any]:
    manifest: dict[str, Any] = {
        "manifest_version": EVALUATION_MANIFEST_VERSION,
        "scorer_version": EVALUATION_SCORER_VERSION,
        "j16_version": J16_POST_HARDENING_VERSION,
        "risk_coverage_version": RISK_COVERAGE_VERSION,
        "j21_version": J21_SETUP_DIFFERENTIATION_VERSION,
        "required_score_dimensions": list(REQUIRED_SCORE_DIMENSIONS),
        "safety_and_grounding_non_compensatory": True,
        "raw_n_and_effective_n_required": True,
        "subjective_grader_requires_human_calibration": True,
        "day23_j16_authoritative": False,
        "post_hardening_j16_authoritative": True,
        "risk_coverage_episode_deduplicated": True,
        "risk_coverage_evaluation_tuning_allowed": False,
        "j21_setup_variant_count": 20,
        "j21_controls": ["regime", "session"],
        "j21_null_accepted": True,
        "j21_inconclusive_accepted": True,
        "taxonomy_expansion_from_j21_allowed": False,
        "predictive_edge_claimed": False,
        "telegram_side_effects_allowed": False,
        "broker_side_effects_allowed": False,
        "super_signals_side_effects_allowed": False,
    }
    manifest["manifest_digest"] = digest(manifest)
    return manifest
