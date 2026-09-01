from __future__ import annotations

import copy
import json
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from hashlib import sha256
from typing import Any

SELECTIVE_LAYER_VERSION = "aidy_shadow_selective_abstention_v1"
BASELINE_VERSION = "aidy_deterministic_risk_baseline_v1"
CALIBRATION_VERSION = "aidy_split_conformal_calibration_v1"
SPLIT_VERSION = "aidy_day45_chronological_split_v1"
J9_VERSION = "aidy_j9_selective_vs_random_v1"
J10_VERSION = "aidy_j10_volatility_instability_abstention_v1"
RISK_COVERAGE_VERSION = "aidy_day45_conformal_risk_coverage_v1"
MANIFEST_VERSION = "aidy_day45_selective_abstention_manifest_v1"

DEFAULT_ALPHA = Decimal("0.20")
DEFAULT_RISK_CEILING = Decimal("0.45")
DEFAULT_RISK_GRID = tuple(Decimal(value) for value in ("0.20", "0.30", "0.40", "0.50", "0.60"))
MIN_EFFECTIVE_TEST_N = 30
MIN_EFFECTIVE_SUBGROUP_N = 10
PROHIBITED_FEATURE_TOKENS = ("confidence", "model_confidence", "llm_confidence")


class SelectiveAbstentionError(ValueError):
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
            raise SelectiveAbstentionError(
                f"{name} must be timezone-aware ISO-8601 text."
            ) from exc
    else:
        raise TypeError(f"{name} must be a timezone-aware datetime or ISO-8601 string.")
    if parsed.tzinfo is None:
        raise SelectiveAbstentionError(f"{name} must be timezone-aware.")
    return parsed.astimezone(UTC)


def _decimal(value: Any, *, name: str) -> Decimal:
    if value is None or isinstance(value, bool):
        raise SelectiveAbstentionError(f"{name} must be a finite number.")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise SelectiveAbstentionError(f"{name} must be a finite number.") from exc
    if not result.is_finite():
        raise SelectiveAbstentionError(f"{name} must be a finite number.")
    return result


def _q(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return str(value.quantize(Decimal("0.000000")))


def _unit(value: Any, *, name: str) -> Decimal:
    result = _decimal(value, name=name)
    if result < 0 or result > 1:
        raise SelectiveAbstentionError(f"{name} must be between 0 and 1.")
    return result


def _clip(value: Decimal) -> Decimal:
    return min(Decimal(1), max(Decimal(0), value))


def _validate_feature_names(feature_names: Sequence[str]) -> tuple[str, ...]:
    normalized = tuple(str(item).strip() for item in feature_names)
    if not normalized or any(not item for item in normalized):
        raise SelectiveAbstentionError("At least one non-empty baseline feature is required.")
    if len(normalized) != len(set(normalized)):
        raise SelectiveAbstentionError("Baseline feature names must be unique.")
    for name in normalized:
        lowered = name.lower()
        if any(token in lowered for token in PROHIBITED_FEATURE_TOKENS):
            raise SelectiveAbstentionError(
                "Model confidence cannot be used by the Day 45 selective layer."
            )
    return normalized


def build_chronological_split(
    *,
    fit_start: datetime | str,
    fit_end: datetime | str,
    calibration_start: datetime | str,
    calibration_end: datetime | str,
    test_start: datetime | str,
    test_end: datetime | str,
) -> dict[str, Any]:
    values = {
        "fit_start": _utc(fit_start, name="fit_start"),
        "fit_end": _utc(fit_end, name="fit_end"),
        "calibration_start": _utc(calibration_start, name="calibration_start"),
        "calibration_end": _utc(calibration_end, name="calibration_end"),
        "test_start": _utc(test_start, name="test_start"),
        "test_end": _utc(test_end, name="test_end"),
    }
    if not (
        values["fit_start"] < values["fit_end"] <= values["calibration_start"]
        < values["calibration_end"] <= values["test_start"] < values["test_end"]
    ):
        raise SelectiveAbstentionError(
            "Fit, calibration and test windows must be chronological and non-overlapping."
        )
    result: dict[str, Any] = {
        "split_version": SPLIT_VERSION,
        "window_semantics": "half_open_start_inclusive_end_exclusive",
        "fit": {
            "start_utc": values["fit_start"].isoformat(),
            "end_utc": values["fit_end"].isoformat(),
        },
        "calibration": {
            "start_utc": values["calibration_start"].isoformat(),
            "end_utc": values["calibration_end"].isoformat(),
        },
        "test": {
            "start_utc": values["test_start"].isoformat(),
            "end_utc": values["test_end"].isoformat(),
        },
        "chronological_nonoverlap_required": True,
        "test_outcomes_available_to_fit": False,
        "test_outcomes_available_to_calibration": False,
    }
    result["split_digest"] = digest(result)
    return result


def _window_name(row_time: datetime, split: Mapping[str, Any]) -> str | None:
    for name in ("fit", "calibration", "test"):
        window = split[name]
        start = _utc(window["start_utc"], name=f"{name}.start_utc")
        end = _utc(window["end_utc"], name=f"{name}.end_utc")
        if start <= row_time < end:
            return name
    return None


def _partition_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    split: Mapping[str, Any],
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, int]]:
    partitions = {"fit": [], "calibration": [], "test": []}
    raw_counts = {"fit": 0, "calibration": 0, "test": 0}
    seen: dict[str, dict[str, Any]] = {}
    seen_window: dict[str, str] = {}

    for index, raw in enumerate(rows):
        if not isinstance(raw, Mapping):
            raise TypeError(f"rows[{index}] must be a mapping.")
        row = copy.deepcopy(dict(raw))
        episode_id = str(row.get("episode_id") or "").strip()
        if not episode_id:
            raise SelectiveAbstentionError("Every row requires episode_id.")
        as_of = _utc(row.get("as_of_utc"), name=f"rows[{index}].as_of_utc")
        window = _window_name(as_of, split)
        if window is None:
            continue
        raw_counts[window] += 1
        existing_window = seen_window.get(episode_id)
        if existing_window is not None and existing_window != window:
            raise SelectiveAbstentionError(
                f"Episode {episode_id} crosses fit/calibration/test boundaries."
            )
        existing = seen.get(episode_id)
        if existing is not None:
            if canonical_json(existing) != canonical_json(row):
                raise SelectiveAbstentionError(
                    f"Conflicting duplicate independent episode: {episode_id}"
                )
            continue
        seen[episode_id] = row
        seen_window[episode_id] = window
        partitions[window].append(row)

    for name in partitions:
        partitions[name].sort(
            key=lambda row: (_utc(row["as_of_utc"], name="as_of_utc"), str(row["episode_id"]))
        )
    return partitions, raw_counts


def fit_deterministic_baseline(
    rows: Iterable[Mapping[str, Any]],
    *,
    feature_names: Sequence[str],
) -> dict[str, Any]:
    features = _validate_feature_names(feature_names)
    prepared: list[tuple[list[Decimal], Decimal, str]] = []
    seen: set[str] = set()
    for index, raw in enumerate(rows):
        if not isinstance(raw, Mapping):
            raise TypeError(f"rows[{index}] must be a mapping.")
        episode_id = str(raw.get("episode_id") or "").strip()
        if not episode_id or episode_id in seen:
            raise SelectiveAbstentionError("Fit rows require unique non-empty episode_id values.")
        seen.add(episode_id)
        adverse = raw.get("adverse_outcome")
        if not isinstance(adverse, bool):
            raise SelectiveAbstentionError("Fit rows require boolean adverse_outcome.")
        values = [_unit(raw.get(name), name=name) for name in features]
        prepared.append((values, Decimal(int(adverse)), episode_id))
    if len(prepared) < 2:
        raise SelectiveAbstentionError("At least two independent fit episodes are required.")

    n = Decimal(len(prepared))
    base_rate = sum((item[1] for item in prepared), Decimal(0)) / n
    feature_means: list[Decimal] = []
    slopes: list[Decimal] = []
    for position, _ in enumerate(features):
        values = [item[0][position] for item in prepared]
        mean_x = sum(values, Decimal(0)) / n
        feature_means.append(mean_x)
        variance = sum(((value - mean_x) ** 2 for value in values), Decimal(0))
        if variance == 0:
            slopes.append(Decimal(0))
            continue
        covariance = sum(
            (
                (item[0][position] - mean_x) * (item[1] - base_rate)
                for item in prepared
            ),
            Decimal(0),
        )
        slopes.append(covariance / variance)

    result: dict[str, Any] = {
        "baseline_version": BASELINE_VERSION,
        "feature_names": list(features),
        "fit_effective_n": len(prepared),
        "fit_episode_ids": sorted(seen),
        "base_adverse_rate": _q(base_rate),
        "feature_means": {
            name: _q(feature_means[index]) for index, name in enumerate(features)
        },
        "feature_slopes": {
            name: _q(slopes[index]) for index, name in enumerate(features)
        },
        "prediction_formula": "base_rate + mean(feature_slope*(x-feature_mean))",
        "model_confidence_used": False,
        "outcome_field": "adverse_outcome",
    }
    result["baseline_digest"] = digest(result)
    return result


def predict_baseline_risk(
    row: Mapping[str, Any],
    baseline: Mapping[str, Any],
) -> Decimal:
    features = _validate_feature_names(baseline.get("feature_names", ()))
    base = _unit(baseline.get("base_adverse_rate"), name="base_adverse_rate")
    contributions = []
    for name in features:
        value = _unit(row.get(name), name=name)
        mean = _unit(baseline["feature_means"][name], name=f"feature_means.{name}")
        slope = _decimal(baseline["feature_slopes"][name], name=f"feature_slopes.{name}")
        contributions.append(slope * (value - mean))
    adjustment = sum(contributions, Decimal(0)) / Decimal(len(contributions))
    return _clip(base + adjustment)


def _conformal_quantile(scores: Sequence[Decimal], alpha: Decimal) -> Decimal:
    if not scores:
        raise SelectiveAbstentionError("Calibration requires at least one score.")
    if alpha <= 0 or alpha >= 1:
        raise SelectiveAbstentionError("alpha must be strictly between 0 and 1.")
    ordered = sorted(scores)
    rank_value = (Decimal(len(ordered) + 1) * (Decimal(1) - alpha)).to_integral_value(
        rounding=ROUND_CEILING
    )
    rank = min(len(ordered), max(1, int(rank_value)))
    return ordered[rank - 1]


def calibrate_split_conformal(
    rows: Iterable[Mapping[str, Any]],
    *,
    baseline: Mapping[str, Any],
    alpha: Any = DEFAULT_ALPHA,
) -> dict[str, Any]:
    alpha_value = _decimal(alpha, name="alpha")
    seen: set[str] = set()
    scores: list[Decimal] = []
    episode_ids: list[str] = []
    for index, raw in enumerate(rows):
        if not isinstance(raw, Mapping):
            raise TypeError(f"rows[{index}] must be a mapping.")
        episode_id = str(raw.get("episode_id") or "").strip()
        if not episode_id or episode_id in seen:
            raise SelectiveAbstentionError(
                "Calibration rows require unique non-empty episode_id values."
            )
        seen.add(episode_id)
        adverse = raw.get("adverse_outcome")
        if not isinstance(adverse, bool):
            raise SelectiveAbstentionError("Calibration rows require boolean adverse_outcome.")
        predicted = predict_baseline_risk(raw, baseline)
        observed = Decimal(int(adverse))
        scores.append(abs(observed - predicted))
        episode_ids.append(episode_id)
    qhat = _conformal_quantile(scores, alpha_value)
    result: dict[str, Any] = {
        "calibration_version": CALIBRATION_VERSION,
        "baseline_digest": str(baseline.get("baseline_digest") or ""),
        "alpha": _q(alpha_value),
        "calibration_effective_n": len(scores),
        "calibration_episode_ids": sorted(episode_ids),
        "nonconformity": "absolute_binary_residual",
        "finite_sample_quantile_method": "ceil((n+1)*(1-alpha))",
        "qhat": _q(qhat),
        "test_outcomes_used": False,
    }
    result["calibration_digest"] = digest(result)
    return result


def score_shadow_position(
    row: Mapping[str, Any],
    *,
    baseline: Mapping[str, Any],
    calibration: Mapping[str, Any],
    risk_ceiling: Any = DEFAULT_RISK_CEILING,
) -> dict[str, Any]:
    ceiling = _unit(risk_ceiling, name="risk_ceiling")
    predicted = predict_baseline_risk(row, baseline)
    qhat = _unit(calibration.get("qhat"), name="qhat")
    lower = _clip(predicted - qhat)
    upper = _clip(predicted + qhat)
    position = "accept" if upper <= ceiling else "reject"
    result: dict[str, Any] = {
        "selective_layer_version": SELECTIVE_LAYER_VERSION,
        "episode_id": str(row.get("episode_id") or ""),
        "baseline_digest": str(baseline.get("baseline_digest") or ""),
        "calibration_digest": str(calibration.get("calibration_digest") or ""),
        "predicted_adverse_risk": _q(predicted),
        "conformal_lower_risk": _q(lower),
        "conformal_upper_risk": _q(upper),
        "risk_ceiling": _q(ceiling),
        "shadow_position": position,
        "master_trader_block_allowed": False,
        "publication_block_allowed": False,
        "model_confidence_used": False,
    }
    result["position_digest"] = digest(result)
    return result


def _adverse_rate(rows: Sequence[Mapping[str, Any]]) -> Decimal | None:
    if not rows:
        return None
    adverse_n = sum(1 for row in rows if row["adverse_outcome"] is True)
    return Decimal(adverse_n) / Decimal(len(rows))


def build_shadow_risk_coverage(
    scored_test_rows: Sequence[Mapping[str, Any]],
    *,
    raw_test_n: int,
    risk_grid: Sequence[Any] = DEFAULT_RISK_GRID,
) -> dict[str, Any]:
    grid = [_unit(value, name="risk_grid") for value in risk_grid]
    if not grid or grid != sorted(set(grid)):
        raise SelectiveAbstentionError("risk_grid must be non-empty, unique and ascending.")
    points = []
    for ceiling in grid:
        selected = [
            row
            for row in scored_test_rows
            if _unit(row["conformal_upper_risk"], name="conformal_upper_risk") <= ceiling
        ]
        adverse_rate = _adverse_rate(selected)
        points.append(
            {
                "risk_ceiling": _q(ceiling),
                "effective_selected_n": len(selected),
                "coverage": (
                    _q(Decimal(len(selected)) / Decimal(len(scored_test_rows)))
                    if scored_test_rows
                    else None
                ),
                "adverse_rate": _q(adverse_rate),
            }
        )
    result: dict[str, Any] = {
        "risk_coverage_version": RISK_COVERAGE_VERSION,
        "raw_test_n": raw_test_n,
        "effective_test_n": len(scored_test_rows),
        "sample_size_basis": "episode_independent_effective_n",
        "risk_grid": [_q(value) for value in grid],
        "risk_grid_frozen_before_test": True,
        "risk_coverage_tuning_on_test_allowed": False,
        "points": points,
        "recommended_threshold": None,
    }
    result["risk_coverage_digest"] = digest(result)
    return result


def _matched_random_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    selected_n: int,
    random_identity: str,
) -> list[Mapping[str, Any]]:
    ranked = sorted(
        rows,
        key=lambda row: (
            sha256(f"{random_identity}|{row['episode_id']}".encode()).hexdigest(),
            str(row["episode_id"]),
        ),
    )
    return ranked[:selected_n]


def evaluate_j9(
    test_rows: Sequence[Mapping[str, Any]],
    *,
    selected_episode_ids: Sequence[str],
    raw_test_n: int,
    random_identity: str,
) -> dict[str, Any]:
    selected_ids = set(selected_episode_ids)
    selective = [row for row in test_rows if str(row["episode_id"]) in selected_ids]
    random_rows = _matched_random_rows(
        test_rows, selected_n=len(selective), random_identity=random_identity
    )
    selective_rate = _adverse_rate(selective)
    random_rate = _adverse_rate(random_rows)
    sufficient = (
        len(test_rows) >= MIN_EFFECTIVE_TEST_N
        and len(selective) >= MIN_EFFECTIVE_SUBGROUP_N
    )
    if not sufficient:
        state = "insufficient"
    elif selective_rate is not None and random_rate is not None and selective_rate < random_rate:
        state = "selective_lower_risk"
    else:
        state = "null_or_worse"
    result: dict[str, Any] = {
        "j9_version": J9_VERSION,
        "raw_test_n": raw_test_n,
        "effective_test_n": len(test_rows),
        "effective_selected_n": len(selective),
        "coverage": (
            _q(Decimal(len(selective)) / Decimal(len(test_rows))) if test_rows else None
        ),
        "selective_adverse_rate": _q(selective_rate),
        "matched_random_adverse_rate": _q(random_rate),
        "matched_random_uses_same_independent_episode_pool": True,
        "matched_random_coverage_identical": len(random_rows) == len(selective),
        "random_identity": random_identity,
        "minimum_effective_test_n": MIN_EFFECTIVE_TEST_N,
        "result_state": state,
        "promotion_authorized": False,
    }
    result["j9_digest"] = digest(result)
    return result


def evaluate_j10(
    test_rows: Sequence[Mapping[str, Any]],
    *,
    selected_episode_ids: Sequence[str],
    raw_test_n: int,
    volatility_field: str = "volatility_instability",
) -> dict[str, Any]:
    if "confidence" in volatility_field.lower():
        raise SelectiveAbstentionError("Model confidence cannot define volatility instability.")
    selected_ids = set(selected_episode_ids)
    groups: dict[str, list[Mapping[str, Any]]] = {"low": [], "high": []}
    for row in test_rows:
        instability = _unit(row.get(volatility_field), name=volatility_field)
        groups["high" if instability >= Decimal("0.5") else "low"].append(row)

    summary: dict[str, Any] = {}
    sufficient = True
    for name in ("low", "high"):
        items = groups[name]
        accepted = [row for row in items if str(row["episode_id"]) in selected_ids]
        adverse_rate = _adverse_rate(items)
        accepted_adverse_rate = _adverse_rate(accepted)
        reject_n = len(items) - len(accepted)
        summary[name] = {
            "effective_n": len(items),
            "accepted_effective_n": len(accepted),
            "rejected_effective_n": reject_n,
            "acceptance_rate": (
                _q(Decimal(len(accepted)) / Decimal(len(items))) if items else None
            ),
            "adverse_rate": _q(adverse_rate),
            "accepted_adverse_rate": _q(accepted_adverse_rate),
        }
        sufficient = sufficient and len(items) >= MIN_EFFECTIVE_SUBGROUP_N

    if not sufficient or len(test_rows) < MIN_EFFECTIVE_TEST_N:
        state = "insufficient"
    else:
        low_accept = _decimal(summary["low"]["acceptance_rate"], name="low.acceptance_rate")
        high_accept = _decimal(summary["high"]["acceptance_rate"], name="high.acceptance_rate")
        state = (
            "conditioning_present"
            if high_accept < low_accept
            else "null_no_instability_conditioning"
        )

    result: dict[str, Any] = {
        "j10_version": J10_VERSION,
        "raw_test_n": raw_test_n,
        "effective_test_n": len(test_rows),
        "volatility_field": volatility_field,
        "volatility_threshold": "0.500000",
        "threshold_frozen_before_test": True,
        "groups": summary,
        "minimum_effective_test_n": MIN_EFFECTIVE_TEST_N,
        "minimum_effective_subgroup_n": MIN_EFFECTIVE_SUBGROUP_N,
        "result_state": state,
        "trading_gate_created": False,
    }
    result["j10_digest"] = digest(result)
    return result


def run_shadow_selective_experiment(
    rows: Iterable[Mapping[str, Any]],
    *,
    split: Mapping[str, Any],
    feature_names: Sequence[str],
    alpha: Any = DEFAULT_ALPHA,
    risk_ceiling: Any = DEFAULT_RISK_CEILING,
    risk_grid: Sequence[Any] = DEFAULT_RISK_GRID,
    random_identity: str,
) -> dict[str, Any]:
    partitions, raw_counts = _partition_rows(rows, split=split)
    baseline = fit_deterministic_baseline(partitions["fit"], feature_names=feature_names)
    calibration = calibrate_split_conformal(
        partitions["calibration"], baseline=baseline, alpha=alpha
    )

    scored = []
    test_rows = []
    selected_ids = []
    for row in partitions["test"]:
        adverse = row.get("adverse_outcome")
        if not isinstance(adverse, bool):
            raise SelectiveAbstentionError("Test rows require boolean adverse_outcome.")
        position = score_shadow_position(
            row,
            baseline=baseline,
            calibration=calibration,
            risk_ceiling=risk_ceiling,
        )
        enriched = copy.deepcopy(row)
        enriched["conformal_upper_risk"] = position["conformal_upper_risk"]
        scored.append({**position, "adverse_outcome": adverse})
        test_rows.append(enriched)
        if position["shadow_position"] == "accept":
            selected_ids.append(str(row["episode_id"]))

    risk_coverage = build_shadow_risk_coverage(
        scored, raw_test_n=raw_counts["test"], risk_grid=risk_grid
    )
    j9 = evaluate_j9(
        test_rows,
        selected_episode_ids=selected_ids,
        raw_test_n=raw_counts["test"],
        random_identity=random_identity,
    )
    j10 = evaluate_j10(
        test_rows,
        selected_episode_ids=selected_ids,
        raw_test_n=raw_counts["test"],
    )

    result: dict[str, Any] = {
        "selective_layer_version": SELECTIVE_LAYER_VERSION,
        "split_digest": str(split.get("split_digest") or ""),
        "feature_names": list(_validate_feature_names(feature_names)),
        "raw_n": raw_counts,
        "effective_n": {name: len(partitions[name]) for name in partitions},
        "baseline": baseline,
        "calibration": calibration,
        "test_positions": scored,
        "risk_coverage": risk_coverage,
        "j9": j9,
        "j10": j10,
        "shadow_only": True,
        "master_trader_gate_created": False,
        "publication_gate_created": False,
        "model_confidence_used": False,
        "automatic_promotion_allowed": False,
        "owner_approved_later_architecture_decision_required": True,
        "formal_forward_evidence_created": False,
    }
    result["experiment_digest"] = digest(result)
    return result


def day45_manifest() -> dict[str, Any]:
    result: dict[str, Any] = {
        "manifest_version": MANIFEST_VERSION,
        "layer_version": SELECTIVE_LAYER_VERSION,
        "baseline_version": BASELINE_VERSION,
        "calibration_version": CALIBRATION_VERSION,
        "split_version": SPLIT_VERSION,
        "j9_version": J9_VERSION,
        "j10_version": J10_VERSION,
        "fit_calibration_test_chronological_nonoverlap_required": True,
        "test_untouched_until_evaluation_required": True,
        "episode_independent_effective_n_required": True,
        "matched_coverage_random_baseline_required": True,
        "risk_coverage_tuning_on_test_allowed": False,
        "model_confidence_as_gate_allowed": False,
        "shadow_output_can_block_master_trader": False,
        "shadow_output_can_block_publication": False,
        "automatic_promotion_allowed": False,
        "owner_approved_later_architecture_decision_required": True,
        "formal_forward_evidence_created": False,
        "minimum_effective_test_n_before_conclusion": MIN_EFFECTIVE_TEST_N,
        "minimum_effective_subgroup_n_before_conclusion": MIN_EFFECTIVE_SUBGROUP_N,
    }
    result["manifest_digest"] = digest(result)
    return result
