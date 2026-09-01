from __future__ import annotations

import copy
import json
import math
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from statistics import NormalDist
from typing import Any, Literal

from aidy.replay_evaluation import verify_holdout_access_record
from aidy.research_integrity import verify_trial_record, verify_trial_registry

STRATEGY_VERSION_RECORD_VERSION = "aidy_strategy_version_record_v1"
PROMOTION_POLICY_VERSION = "aidy_strategy_promotion_policy_v1"
MULTIPLE_TESTING_VERSION = "aidy_multiple_testing_control_v1"
PROMOTION_DECISION_VERSION = "aidy_strategy_promotion_decision_v1"
REGISTRY_SNAPSHOT_VERSION = "aidy_strategy_registry_snapshot_v1"
REGISTRY_EVENT_VERSION = "aidy_strategy_registry_event_v1"
ROLLBACK_RECORD_VERSION = "aidy_strategy_rollback_record_v1"
PROMOTION_MANIFEST_VERSION = "aidy_day39_strategy_promotion_manifest_v1"

REQUIRED_COMPONENTS = (
    "feature_version",
    "retrieval_version",
    "composer_version",
    "prompt_version",
    "model_version",
    "safety_version",
)
TERMINAL_TRIAL_STATES = {"passed", "null", "insufficient", "failed"}
ALLOWED_ROLLBACK_TRIGGERS = {
    "safety_regression",
    "data_integrity_failure",
    "strategy_contract_violation",
    "forced_model_api_deprecation",
    "documented_market_structure_change",
}
MetricDirection = Literal["higher", "lower"]
DecisionStatus = Literal["promote", "retain_champion", "inconclusive"]


class PromotionIntegrityError(ValueError):
    pass


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest(value: object) -> str:
    return sha256(canonical_json(value).encode()).hexdigest()


def _utc(value: datetime | str, *, name: str) -> str:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise PromotionIntegrityError(f"{name} must be timezone-aware.")
    return parsed.astimezone(UTC).isoformat()


def _text(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PromotionIntegrityError(f"{name} must be non-empty text.")
    return value.strip()


def _decimal(value: Any, *, name: str) -> Decimal:
    if isinstance(value, bool):
        raise PromotionIntegrityError(f"{name} must be numeric.")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise PromotionIntegrityError(f"{name} must be numeric.") from exc
    if not result.is_finite():
        raise PromotionIntegrityError(f"{name} must be finite.")
    return result


def _quantize(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.000001")))


def _verified_digest_record(
    record: Mapping[str, Any],
    *,
    digest_field: str,
    version_field: str,
    version_value: str,
) -> tuple[dict[str, Any], str]:
    if not isinstance(record, Mapping):
        raise PromotionIntegrityError(f"{version_field} record must be a mapping.")
    body = copy.deepcopy(dict(record))
    supplied = str(body.pop(digest_field, ""))
    if not supplied or supplied != digest(body):
        raise PromotionIntegrityError(f"{digest_field} mismatch.")
    if body.get(version_field) != version_value:
        raise PromotionIntegrityError(f"Unsupported {version_field}.")
    return body, supplied


def build_strategy_version(
    *,
    version_id: str,
    registered_at: datetime | str,
    code_head: str,
    components: Mapping[str, Any],
    config: Mapping[str, Any],
    change_hypothesis: str,
    parent_version_digest: str | None = None,
) -> dict[str, Any]:
    component_map = {str(key): value for key, value in components.items()}
    if set(component_map) != set(REQUIRED_COMPONENTS):
        raise PromotionIntegrityError(
            f"components must contain exactly {', '.join(REQUIRED_COMPONENTS)}."
        )
    normalized_components = {
        key: _text(component_map[key], name=f"components.{key}") for key in REQUIRED_COMPONENTS
    }
    if parent_version_digest is not None:
        _text(parent_version_digest, name="parent_version_digest")
    record: dict[str, Any] = {
        "version_record_version": STRATEGY_VERSION_RECORD_VERSION,
        "version_id": _text(version_id, name="version_id"),
        "registered_at_utc": _utc(registered_at, name="registered_at"),
        "code_head": _text(code_head, name="code_head"),
        "components": normalized_components,
        "component_digest": digest(normalized_components),
        "config": copy.deepcopy(dict(config)),
        "config_digest": digest(dict(config)),
        "change_hypothesis": _text(change_hypothesis, name="change_hypothesis"),
        "parent_version_digest": parent_version_digest,
        "immutable": True,
        "secret_values_included": False,
        "autonomous_mutation_allowed": False,
        "broker_side_effects_allowed": False,
        "telegram_side_effects_allowed": False,
        "super_signals_side_effects_allowed": False,
    }
    record["version_digest"] = digest(record)
    return record


def verify_strategy_version(record: Mapping[str, Any]) -> bool:
    try:
        body, _ = _verified_digest_record(
            record,
            digest_field="version_digest",
            version_field="version_record_version",
            version_value=STRATEGY_VERSION_RECORD_VERSION,
        )
        if body.get("immutable") is not True:
            return False
        if body.get("secret_values_included") is not False:
            return False
        if body.get("autonomous_mutation_allowed") is not False:
            return False
        if any(
            body.get(key) is not False
            for key in (
                "broker_side_effects_allowed",
                "telegram_side_effects_allowed",
                "super_signals_side_effects_allowed",
            )
        ):
            return False
        components = body.get("components")
        if not isinstance(components, Mapping) or set(components) != set(REQUIRED_COMPONENTS):
            return False
        if body.get("component_digest") != digest(dict(components)):
            return False
        config = body.get("config")
        if not isinstance(config, Mapping) or body.get("config_digest") != digest(dict(config)):
            return False
        _utc(body["registered_at_utc"], name="registered_at_utc")
        _text(body["version_id"], name="version_id")
        _text(body["code_head"], name="code_head")
        _text(body["change_hypothesis"], name="change_hypothesis")
        return True
    except (KeyError, TypeError, ValueError):
        return False


def build_promotion_policy(
    *,
    metric_criteria: Sequence[Mapping[str, Any]],
    safety_criteria: Sequence[Mapping[str, Any]],
    minimum_improved_metrics: int,
    dsr_min_probability: Any = "0.95",
) -> dict[str, Any]:
    if len(metric_criteria) < 3:
        raise PromotionIntegrityError("Promotion requires at least three pre-specified metrics.")
    if isinstance(minimum_improved_metrics, bool) or not isinstance(minimum_improved_metrics, int):
        raise PromotionIntegrityError("minimum_improved_metrics must be an integer.")
    if minimum_improved_metrics < 1 or minimum_improved_metrics > len(metric_criteria):
        raise PromotionIntegrityError("minimum_improved_metrics is outside the metric set.")
    if not safety_criteria:
        raise PromotionIntegrityError("At least one non-compensatory safety metric is required.")

    def normalize(rows: Sequence[Mapping[str, Any]], *, safety: bool) -> list[dict[str, Any]]:
        output = []
        seen = set()
        for index, raw in enumerate(rows):
            metric = _text(raw.get("metric"), name=f"criteria[{index}].metric")
            if metric in seen:
                raise PromotionIntegrityError(f"Duplicate criterion: {metric}")
            seen.add(metric)
            direction = raw.get("direction")
            if direction not in {"higher", "lower"}:
                raise PromotionIntegrityError(f"Unsupported direction for {metric}.")
            minimum_delta = _decimal(
                raw.get("minimum_delta", 0), name=f"criteria[{index}].minimum_delta"
            )
            if minimum_delta < 0:
                raise PromotionIntegrityError("minimum_delta cannot be negative.")
            output.append(
                {
                    "metric": metric,
                    "direction": direction,
                    "minimum_delta": _quantize(minimum_delta),
                    "safety_non_compensatory": safety,
                }
            )
        return output

    dsr_threshold = _decimal(dsr_min_probability, name="dsr_min_probability")
    if dsr_threshold <= 0 or dsr_threshold >= 1:
        raise PromotionIntegrityError("dsr_min_probability must be strictly between 0 and 1.")
    policy: dict[str, Any] = {
        "policy_version": PROMOTION_POLICY_VERSION,
        "metric_criteria": normalize(metric_criteria, safety=False),
        "safety_criteria": normalize(safety_criteria, safety=True),
        "minimum_improved_metrics": minimum_improved_metrics,
        "require_all_primary_metrics_non_degrading": True,
        "require_all_safety_metrics_non_degrading": True,
        "require_terminal_passed_trial": True,
        "require_complete_trial_count": True,
        "holdout_reuse_for_tuning_allowed": False,
        "holdout_access_record_required": True,
        "dsr_required_when_sharpe_claimed": True,
        "dsr_min_probability": _quantize(dsr_threshold),
        "owner_approval_required_for_registry_change": True,
        "autonomous_self_modification_allowed": False,
    }
    policy["policy_digest"] = digest(policy)
    return policy


def verify_promotion_policy(policy: Mapping[str, Any]) -> bool:
    try:
        body, _ = _verified_digest_record(
            policy,
            digest_field="policy_digest",
            version_field="policy_version",
            version_value=PROMOTION_POLICY_VERSION,
        )
        metrics = body["metric_criteria"]
        safety = body["safety_criteria"]
        if not isinstance(metrics, list) or len(metrics) < 3:
            return False
        if not isinstance(safety, list) or not safety:
            return False
        names = [row["metric"] for row in metrics + safety]
        if len(names) != len(set(names)):
            return False
        if body.get("require_all_primary_metrics_non_degrading") is not True:
            return False
        if body.get("require_all_safety_metrics_non_degrading") is not True:
            return False
        if body.get("holdout_reuse_for_tuning_allowed") is not False:
            return False
        if body.get("autonomous_self_modification_allowed") is not False:
            return False
        minimum = int(body["minimum_improved_metrics"])
        if minimum < 1 or minimum > len(metrics):
            return False
        threshold = _decimal(body["dsr_min_probability"], name="dsr_min_probability")
        return Decimal(0) < threshold < Decimal(1)
    except (KeyError, TypeError, ValueError):
        return False


def deflated_sharpe_ratio(
    *,
    observed_sharpe: Any,
    trial_count: int,
    observation_count: int,
    variance_across_trials: Any,
    skewness: Any = 0,
    kurtosis: Any = 3,
) -> dict[str, Any]:
    if isinstance(trial_count, bool) or not isinstance(trial_count, int) or trial_count < 1:
        raise PromotionIntegrityError("trial_count must be a positive integer.")
    if (
        isinstance(observation_count, bool)
        or not isinstance(observation_count, int)
        or observation_count < 3
    ):
        raise PromotionIntegrityError("observation_count must be an integer >= 3.")
    observed = _decimal(observed_sharpe, name="observed_sharpe")
    variance = _decimal(variance_across_trials, name="variance_across_trials")
    skew = _decimal(skewness, name="skewness")
    kurt = _decimal(kurtosis, name="kurtosis")
    if variance < 0:
        raise PromotionIntegrityError("variance_across_trials cannot be negative.")
    if kurt < 1:
        raise PromotionIntegrityError("kurtosis must be >= 1.")

    expected_max = Decimal(0)
    if trial_count > 1 and variance > 0:
        normal = NormalDist()
        gamma = Decimal("0.5772156649015329")
        n = Decimal(trial_count)
        z_a = Decimal(str(normal.inv_cdf(float(Decimal(1) - (Decimal(1) / n)))))
        z_b = Decimal(
            str(normal.inv_cdf(float(Decimal(1) - (Decimal(1) / (n * Decimal(str(math.e)))))))
        )
        expected_max = variance.sqrt() * ((Decimal(1) - gamma) * z_a + gamma * z_b)

    denominator_sq = (
        Decimal(1)
        - skew * observed
        + ((kurt - Decimal(1)) / Decimal(4)) * (observed**2)
    )
    if denominator_sq <= 0:
        raise PromotionIntegrityError("Sharpe sampling denominator is not positive.")
    z_score = (
        (observed - expected_max)
        * Decimal(observation_count - 1).sqrt()
        / denominator_sq.sqrt()
    )
    probability = Decimal(str(NormalDist().cdf(float(z_score))))
    report: dict[str, Any] = {
        "multiple_testing_version": MULTIPLE_TESTING_VERSION,
        "method": "deflated_sharpe_ratio",
        "observed_sharpe": _quantize(observed),
        "trial_count": trial_count,
        "observation_count": observation_count,
        "variance_across_trials": _quantize(variance),
        "skewness": _quantize(skew),
        "kurtosis": _quantize(kurt),
        "expected_max_sharpe_under_selection": _quantize(expected_max),
        "deflated_sharpe_z": _quantize(z_score),
        "deflated_sharpe_probability": _quantize(probability),
        "trial_count_adjustment_applied": trial_count > 1,
    }
    report["multiple_testing_digest"] = digest(report)
    return report


def verify_multiple_testing_report(report: Mapping[str, Any]) -> bool:
    try:
        body, _ = _verified_digest_record(
            report,
            digest_field="multiple_testing_digest",
            version_field="multiple_testing_version",
            version_value=MULTIPLE_TESTING_VERSION,
        )
        if body.get("method") != "deflated_sharpe_ratio":
            return False
        if int(body["trial_count"]) < 1 or int(body["observation_count"]) < 3:
            return False
        probability = _decimal(
            body["deflated_sharpe_probability"], name="deflated_sharpe_probability"
        )
        return Decimal(0) <= probability <= Decimal(1)
    except (KeyError, TypeError, ValueError):
        return False


def build_multiple_testing_control(
    trial_registry: Sequence[Mapping[str, Any]],
    *,
    sharpe_statistics: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    verify_trial_registry(trial_registry)
    terminal_counts = {state: 0 for state in sorted(TERMINAL_TRIAL_STATES)}
    preregistered = 0
    for record in trial_registry:
        state = str(record["result_state"])
        if state == "preregistered":
            preregistered += 1
        elif state in terminal_counts:
            terminal_counts[state] += 1
    if preregistered:
        raise PromotionIntegrityError("Promotion evidence cannot contain unfinished trials.")

    report: dict[str, Any] = {
        "multiple_testing_version": MULTIPLE_TESTING_VERSION,
        "method": "trial_count_only",
        "trial_count": len(trial_registry),
        "terminal_result_counts": terminal_counts,
        "failed_null_insufficient_trials_retained": all(
            state in terminal_counts for state in ("failed", "null", "insufficient")
        ),
        "complete_trial_count_required": True,
        "selection_bias_accounting_trial_count": len(trial_registry),
        "sharpe_claimed": sharpe_statistics is not None,
        "deflated_sharpe": None,
    }
    if sharpe_statistics is not None:
        dsr = deflated_sharpe_ratio(
            observed_sharpe=sharpe_statistics["observed_sharpe"],
            trial_count=len(trial_registry),
            observation_count=int(sharpe_statistics["observation_count"]),
            variance_across_trials=sharpe_statistics["variance_across_trials"],
            skewness=sharpe_statistics.get("skewness", 0),
            kurtosis=sharpe_statistics.get("kurtosis", 3),
        )
        report["method"] = "deflated_sharpe_ratio"
        report["deflated_sharpe"] = dsr
    report["multiple_testing_digest"] = digest(report)
    return report


def verify_multiple_testing_control(report: Mapping[str, Any]) -> bool:
    try:
        body, _ = _verified_digest_record(
            report,
            digest_field="multiple_testing_digest",
            version_field="multiple_testing_version",
            version_value=MULTIPLE_TESTING_VERSION,
        )
        if int(body["trial_count"]) < 1:
            return False
        counts = body["terminal_result_counts"]
        if not isinstance(counts, Mapping) or sum(int(value) for value in counts.values()) != int(
            body["trial_count"]
        ):
            return False
        dsr = body.get("deflated_sharpe")
        if body.get("sharpe_claimed"):
            return isinstance(dsr, Mapping) and verify_multiple_testing_report(dsr)
        return dsr is None and body.get("method") == "trial_count_only"
    except (KeyError, TypeError, ValueError):
        return False


def _criterion_result(
    criterion: Mapping[str, Any],
    *,
    champion: Mapping[str, Any],
    challenger: Mapping[str, Any],
) -> dict[str, Any]:
    metric = str(criterion["metric"])
    if metric not in champion or metric not in challenger:
        raise PromotionIntegrityError(f"Missing pre-specified metric: {metric}")
    baseline = _decimal(champion[metric], name=f"champion.{metric}")
    candidate = _decimal(challenger[metric], name=f"challenger.{metric}")
    direction = str(criterion["direction"])
    delta = candidate - baseline if direction == "higher" else baseline - candidate
    threshold = _decimal(criterion["minimum_delta"], name=f"{metric}.minimum_delta")
    return {
        "metric": metric,
        "direction": direction,
        "champion": _quantize(baseline),
        "challenger": _quantize(candidate),
        "signed_improvement": _quantize(delta),
        "non_degrading": delta >= 0,
        "meets_improvement_threshold": delta >= threshold,
        "minimum_delta": _quantize(threshold),
        "safety_non_compensatory": bool(criterion["safety_non_compensatory"]),
    }


def _find_trial(registry: Sequence[Mapping[str, Any]], trial_identity: str) -> Mapping[str, Any]:
    matches = [record for record in registry if record.get("trial_identity") == trial_identity]
    if len(matches) != 1:
        raise PromotionIntegrityError("Exactly one challenger trial identity is required.")
    return matches[0]


def evaluate_promotion(
    *,
    champion_version: Mapping[str, Any],
    challenger_version: Mapping[str, Any],
    policy: Mapping[str, Any],
    trial_registry: Sequence[Mapping[str, Any]],
    challenger_trial_identity: str,
    champion_metrics: Mapping[str, Any],
    challenger_metrics: Mapping[str, Any],
    champion_safety: Mapping[str, Any],
    challenger_safety: Mapping[str, Any],
    multiple_testing_control: Mapping[str, Any],
    holdout_access_record: Mapping[str, Any],
    evaluation_identity: str,
    holdout_identity: str,
    evaluated_at: datetime | str,
) -> dict[str, Any]:
    if not verify_strategy_version(champion_version):
        raise PromotionIntegrityError("Champion strategy version is invalid.")
    if not verify_strategy_version(challenger_version):
        raise PromotionIntegrityError("Challenger strategy version is invalid.")
    if champion_version["version_digest"] == challenger_version["version_digest"]:
        raise PromotionIntegrityError("Champion and challenger must be distinct immutable versions.")
    if not verify_promotion_policy(policy):
        raise PromotionIntegrityError("Promotion policy is invalid.")
    verify_trial_registry(trial_registry)
    if not verify_multiple_testing_control(multiple_testing_control):
        raise PromotionIntegrityError("Multiple-testing control is invalid.")
    if int(multiple_testing_control["trial_count"]) != len(trial_registry):
        raise PromotionIntegrityError("Multiple-testing trial count is incomplete.")
    if not verify_holdout_access_record(holdout_access_record):
        raise PromotionIntegrityError("A valid Day-37 holdout access record is required.")

    trial = _find_trial(trial_registry, challenger_trial_identity)
    if not verify_trial_record(trial):
        raise PromotionIntegrityError("Challenger trial record is invalid.")
    if trial.get("purpose") != "evaluation":
        raise PromotionIntegrityError("Promotion must be based on a preregistered evaluation trial.")
    frozen = trial.get("frozen_parameters")
    if not isinstance(frozen, Mapping):
        raise PromotionIntegrityError("Challenger trial lacks frozen parameters.")
    required_bindings = {
        "champion_version_digest": champion_version["version_digest"],
        "challenger_version_digest": challenger_version["version_digest"],
        "promotion_policy_digest": policy["policy_digest"],
        "declared_trial_count": len(trial_registry),
    }
    for key, expected in required_bindings.items():
        if frozen.get(key) != expected:
            raise PromotionIntegrityError(f"Preregistered challenger binding mismatch: {key}")
    if trial.get("evaluation_identity") != evaluation_identity:
        raise PromotionIntegrityError("Evaluation identity differs from preregistration.")
    if trial.get("holdout_identity") != holdout_identity:
        raise PromotionIntegrityError("Holdout identity differs from preregistration.")
    if holdout_access_record.get("trial_identity") != challenger_trial_identity:
        raise PromotionIntegrityError("Holdout access is not bound to the challenger trial.")
    if holdout_access_record.get("trial_digest") != trial.get("trial_digest"):
        raise PromotionIntegrityError("Holdout access trial digest mismatch.")
    if holdout_access_record.get("holdout_identity") != holdout_identity:
        raise PromotionIntegrityError("Holdout access identity mismatch.")

    primary = [
        _criterion_result(row, champion=champion_metrics, challenger=challenger_metrics)
        for row in policy["metric_criteria"]
    ]
    safety = [
        _criterion_result(row, champion=champion_safety, challenger=challenger_safety)
        for row in policy["safety_criteria"]
    ]
    all_primary_non_degrading = all(row["non_degrading"] for row in primary)
    safety_parity = all(row["non_degrading"] for row in safety)
    improved_count = sum(row["meets_improvement_threshold"] for row in primary)
    broad_improvement = all_primary_non_degrading and improved_count >= int(
        policy["minimum_improved_metrics"]
    )

    dsr_pass: bool | None = None
    if multiple_testing_control.get("sharpe_claimed"):
        dsr = multiple_testing_control.get("deflated_sharpe")
        if not isinstance(dsr, Mapping):
            raise PromotionIntegrityError("Sharpe claim requires Deflated Sharpe evidence.")
        probability = _decimal(
            dsr["deflated_sharpe_probability"], name="deflated_sharpe_probability"
        )
        dsr_pass = probability >= _decimal(
            policy["dsr_min_probability"], name="dsr_min_probability"
        )

    trial_passed = trial.get("result_state") == "passed"
    terminal_nonpass = trial.get("result_state") in {"failed", "null", "insufficient"}
    if terminal_nonpass:
        status: DecisionStatus = "inconclusive"
        reasons = [f"challenger_trial_{trial['result_state']}"]
    else:
        reasons = []
        if not trial_passed:
            reasons.append("challenger_trial_not_terminal_pass")
        if not all_primary_non_degrading:
            reasons.append("primary_metric_degradation")
        if not broad_improvement:
            reasons.append("broad_improvement_requirement_not_met")
        if not safety_parity:
            reasons.append("safety_parity_failed")
        if dsr_pass is False:
            reasons.append("deflated_sharpe_threshold_failed")
        status = "promote" if not reasons else "retain_champion"

    decision: dict[str, Any] = {
        "decision_version": PROMOTION_DECISION_VERSION,
        "evaluated_at_utc": _utc(evaluated_at, name="evaluated_at"),
        "champion_version_digest": champion_version["version_digest"],
        "challenger_version_digest": challenger_version["version_digest"],
        "policy_digest": policy["policy_digest"],
        "trial_identity": challenger_trial_identity,
        "trial_digest": trial["trial_digest"],
        "trial_result_state": trial["result_state"],
        "declared_trial_count": len(trial_registry),
        "multiple_testing_digest": multiple_testing_control["multiple_testing_digest"],
        "evaluation_identity": _text(evaluation_identity, name="evaluation_identity"),
        "holdout_identity": _text(holdout_identity, name="holdout_identity"),
        "holdout_access_digest": holdout_access_record["access_digest"],
        "primary_metric_results": primary,
        "safety_metric_results": safety,
        "primary_metrics_non_degrading": all_primary_non_degrading,
        "improved_primary_metric_count": improved_count,
        "broad_improvement_passed": broad_improvement,
        "safety_parity_passed": safety_parity,
        "deflated_sharpe_required": bool(multiple_testing_control.get("sharpe_claimed")),
        "deflated_sharpe_passed": dsr_pass,
        "status": status,
        "reasons": reasons,
        "owner_approval_still_required": True,
        "autonomous_registry_change_allowed": False,
        "predictive_edge_claimed": False,
        "broker_side_effects_allowed": False,
        "telegram_side_effects_allowed": False,
        "super_signals_side_effects_allowed": False,
    }
    decision["decision_digest"] = digest(decision)
    return decision


def verify_promotion_decision(decision: Mapping[str, Any]) -> bool:
    try:
        body, _ = _verified_digest_record(
            decision,
            digest_field="decision_digest",
            version_field="decision_version",
            version_value=PROMOTION_DECISION_VERSION,
        )
        if body.get("status") not in {"promote", "retain_champion", "inconclusive"}:
            return False
        if body.get("owner_approval_still_required") is not True:
            return False
        if body.get("autonomous_registry_change_allowed") is not False:
            return False
        if body.get("predictive_edge_claimed") is not False:
            return False
        if body.get("status") == "promote":
            if body.get("broad_improvement_passed") is not True:
                return False
            if body.get("safety_parity_passed") is not True:
                return False
            if body.get("trial_result_state") != "passed":
                return False
            if (
                body.get("deflated_sharpe_required") is True
                and body.get("deflated_sharpe_passed") is not True
            ):
                return False
        return True
    except (KeyError, TypeError, ValueError):
        return False


def build_registry_snapshot(
    *,
    versions: Iterable[Mapping[str, Any]],
    active_champion_digest: str,
    events: Sequence[Mapping[str, Any]] = (),
    previous_registry_digest: str | None = None,
) -> dict[str, Any]:
    version_rows = [copy.deepcopy(dict(item)) for item in versions]
    if not version_rows:
        raise PromotionIntegrityError("Strategy registry cannot be empty.")
    digests = []
    ids = []
    for row in version_rows:
        if not verify_strategy_version(row):
            raise PromotionIntegrityError("Registry contains an invalid strategy version.")
        digests.append(str(row["version_digest"]))
        ids.append(str(row["version_id"]))
    if len(digests) != len(set(digests)) or len(ids) != len(set(ids)):
        raise PromotionIntegrityError("Strategy versions must have unique identities and digests.")
    if active_champion_digest not in set(digests):
        raise PromotionIntegrityError("Active champion must be a registered immutable version.")

    event_rows = [copy.deepcopy(dict(item)) for item in events]
    for index, event in enumerate(event_rows, start=1):
        if not verify_registry_event(event):
            raise PromotionIntegrityError("Registry contains an invalid event.")
        if event["event_number"] != index:
            raise PromotionIntegrityError("Registry event sequence is non-monotonic.")
        if event["from_version_digest"] not in set(digests):
            raise PromotionIntegrityError("Registry event source version is not registered.")
        if event["to_version_digest"] not in set(digests):
            raise PromotionIntegrityError("Registry event target version is not registered.")
        expected_previous = None if index == 1 else event_rows[index - 2]["event_digest"]
        if event["previous_event_digest"] != expected_previous:
            raise PromotionIntegrityError("Registry event digest chain is broken.")
    derived_active = digests[0] if not event_rows else event_rows[-1]["to_version_digest"]
    if active_champion_digest != derived_active:
        raise PromotionIntegrityError("Active champion does not match the append-only event chain.")

    snapshot: dict[str, Any] = {
        "registry_snapshot_version": REGISTRY_SNAPSHOT_VERSION,
        "versions": sorted(
            version_rows, key=lambda row: (row["registered_at_utc"], row["version_id"])
        ),
        "registered_version_count": len(version_rows),
        "active_champion_digest": active_champion_digest,
        "events": event_rows,
        "event_count": len(event_rows),
        "previous_registry_digest": previous_registry_digest,
        "champion_overwrite_allowed": False,
        "version_deletion_allowed": False,
        "append_only": True,
        "autonomous_self_modification_allowed": False,
    }
    snapshot["registry_digest"] = digest(snapshot)
    return snapshot


def verify_registry_snapshot(snapshot: Mapping[str, Any]) -> bool:
    try:
        body, supplied = _verified_digest_record(
            snapshot,
            digest_field="registry_digest",
            version_field="registry_snapshot_version",
            version_value=REGISTRY_SNAPSHOT_VERSION,
        )
        rebuilt = build_registry_snapshot(
            versions=body["versions"],
            active_champion_digest=body["active_champion_digest"],
            events=body["events"],
            previous_registry_digest=body.get("previous_registry_digest"),
        )
        return rebuilt["registry_digest"] == supplied
    except (KeyError, TypeError, ValueError):
        return False


def build_promotion_event(
    *,
    registry: Mapping[str, Any],
    decision: Mapping[str, Any],
    approved_by: str,
    approved_at: datetime | str,
) -> dict[str, Any]:
    if not verify_registry_snapshot(registry):
        raise PromotionIntegrityError("A valid strategy registry is required.")
    if not verify_promotion_decision(decision) or decision.get("status") != "promote":
        raise PromotionIntegrityError("Only an accepted promotion decision can create an event.")
    if registry["active_champion_digest"] != decision["champion_version_digest"]:
        raise PromotionIntegrityError("Promotion source is not the active champion.")
    registered = {row["version_digest"] for row in registry["versions"]}
    if decision["challenger_version_digest"] not in registered:
        raise PromotionIntegrityError("Promotion target is not a registered challenger.")
    event: dict[str, Any] = {
        "event_version": REGISTRY_EVENT_VERSION,
        "event_number": len(registry["events"]) + 1,
        "event_type": "promotion",
        "from_version_digest": decision["champion_version_digest"],
        "to_version_digest": decision["challenger_version_digest"],
        "decision_digest": decision["decision_digest"],
        "approved_by": _text(approved_by, name="approved_by"),
        "approved_at_utc": _utc(approved_at, name="approved_at"),
        "previous_event_digest": registry["events"][-1]["event_digest"]
        if registry["events"]
        else None,
        "manual_approval_required": True,
        "autonomous_execution_allowed": False,
    }
    event["event_digest"] = digest(event)
    return event


def verify_registry_event(event: Mapping[str, Any]) -> bool:
    try:
        body, _ = _verified_digest_record(
            event,
            digest_field="event_digest",
            version_field="event_version",
            version_value=REGISTRY_EVENT_VERSION,
        )
        if body.get("event_type") not in {"promotion", "rollback"}:
            return False
        if int(body["event_number"]) < 1:
            return False
        if body.get("manual_approval_required") is not True:
            return False
        if body.get("autonomous_execution_allowed") is not False:
            return False
        _utc(body["approved_at_utc"], name="approved_at_utc")
        return True
    except (KeyError, TypeError, ValueError):
        return False


def apply_registry_event(
    registry: Mapping[str, Any],
    event: Mapping[str, Any],
) -> dict[str, Any]:
    if not verify_registry_snapshot(registry):
        raise PromotionIntegrityError("A valid strategy registry is required.")
    if not verify_registry_event(event):
        raise PromotionIntegrityError("A valid strategy registry event is required.")
    if event["event_number"] != len(registry["events"]) + 1:
        raise PromotionIntegrityError("Registry event number is not the next append-only sequence.")
    if event["previous_event_digest"] != (
        registry["events"][-1]["event_digest"] if registry["events"] else None
    ):
        raise PromotionIntegrityError("Registry event does not extend the current event chain.")
    if event["from_version_digest"] != registry["active_champion_digest"]:
        raise PromotionIntegrityError("Registry event source is not the active champion.")
    registered = {row["version_digest"] for row in registry["versions"]}
    if event["to_version_digest"] not in registered:
        raise PromotionIntegrityError("Registry event target is not registered.")
    return build_registry_snapshot(
        versions=registry["versions"],
        active_champion_digest=event["to_version_digest"],
        events=[*registry["events"], event],
        previous_registry_digest=registry["registry_digest"],
    )


def build_rollback_record(
    *,
    registry: Mapping[str, Any],
    rollback_to_version_digest: str,
    trigger: str,
    evidence_digest: str,
    approved_by: str,
    approved_at: datetime | str,
) -> dict[str, Any]:
    if not verify_registry_snapshot(registry):
        raise PromotionIntegrityError("A valid strategy registry is required.")
    if trigger not in ALLOWED_ROLLBACK_TRIGGERS:
        raise PromotionIntegrityError("Rollback trigger is not an allowed deterministic trigger.")
    registered = {row["version_digest"] for row in registry["versions"]}
    if rollback_to_version_digest not in registered:
        raise PromotionIntegrityError("Rollback target is not a registered strategy version.")
    if rollback_to_version_digest == registry["active_champion_digest"]:
        raise PromotionIntegrityError("Rollback target must differ from the active champion.")
    record: dict[str, Any] = {
        "rollback_version": ROLLBACK_RECORD_VERSION,
        "from_version_digest": registry["active_champion_digest"],
        "rollback_to_version_digest": rollback_to_version_digest,
        "trigger": trigger,
        "evidence_digest": _text(evidence_digest, name="evidence_digest"),
        "approved_by": _text(approved_by, name="approved_by"),
        "approved_at_utc": _utc(approved_at, name="approved_at"),
        "deterministic_target_selection": True,
        "manual_execution_required": True,
        "autonomous_execution_allowed": False,
        "performance_improvement_is_valid_rollback_trigger": False,
    }
    record["rollback_digest"] = digest(record)
    return record


def verify_rollback_record(record: Mapping[str, Any]) -> bool:
    try:
        body, _ = _verified_digest_record(
            record,
            digest_field="rollback_digest",
            version_field="rollback_version",
            version_value=ROLLBACK_RECORD_VERSION,
        )
        if body.get("trigger") not in ALLOWED_ROLLBACK_TRIGGERS:
            return False
        if body.get("deterministic_target_selection") is not True:
            return False
        if body.get("manual_execution_required") is not True:
            return False
        if body.get("autonomous_execution_allowed") is not False:
            return False
        if body.get("performance_improvement_is_valid_rollback_trigger") is not False:
            return False
        return body["from_version_digest"] != body["rollback_to_version_digest"]
    except (KeyError, TypeError, ValueError):
        return False


def build_rollback_event(
    *,
    registry: Mapping[str, Any],
    rollback_record: Mapping[str, Any],
) -> dict[str, Any]:
    if not verify_registry_snapshot(registry):
        raise PromotionIntegrityError("A valid strategy registry is required.")
    if not verify_rollback_record(rollback_record):
        raise PromotionIntegrityError("A valid rollback record is required.")
    if rollback_record["from_version_digest"] != registry["active_champion_digest"]:
        raise PromotionIntegrityError("Rollback source is not the active champion.")
    event: dict[str, Any] = {
        "event_version": REGISTRY_EVENT_VERSION,
        "event_number": len(registry["events"]) + 1,
        "event_type": "rollback",
        "from_version_digest": rollback_record["from_version_digest"],
        "to_version_digest": rollback_record["rollback_to_version_digest"],
        "decision_digest": rollback_record["rollback_digest"],
        "approved_by": rollback_record["approved_by"],
        "approved_at_utc": rollback_record["approved_at_utc"],
        "previous_event_digest": registry["events"][-1]["event_digest"]
        if registry["events"]
        else None,
        "manual_approval_required": True,
        "autonomous_execution_allowed": False,
    }
    event["event_digest"] = digest(event)
    return event


def promotion_manifest() -> dict[str, Any]:
    manifest: dict[str, Any] = {
        "manifest_version": PROMOTION_MANIFEST_VERSION,
        "strategy_version_record_version": STRATEGY_VERSION_RECORD_VERSION,
        "promotion_policy_version": PROMOTION_POLICY_VERSION,
        "promotion_decision_version": PROMOTION_DECISION_VERSION,
        "multiple_testing_version": MULTIPLE_TESTING_VERSION,
        "registry_snapshot_version": REGISTRY_SNAPSHOT_VERSION,
        "registry_event_version": REGISTRY_EVENT_VERSION,
        "rollback_record_version": ROLLBACK_RECORD_VERSION,
        "required_component_identities": list(REQUIRED_COMPONENTS),
        "day32_preregistered_trial_required": True,
        "day37_holdout_access_record_required": True,
        "complete_trial_count_required": True,
        "failed_null_insufficient_trials_retained": True,
        "deflated_sharpe_required_when_sharpe_claimed": True,
        "broad_prespecified_improvement_required": True,
        "safety_parity_non_compensatory": True,
        "champion_overwrite_allowed": False,
        "version_deletion_allowed": False,
        "rollback_is_append_only_event": True,
        "rollback_performance_shopping_allowed": False,
        "owner_approval_required_for_registry_change": True,
        "autonomous_self_modification_allowed": False,
        "predictive_edge_claimed": False,
        "broker_side_effects_allowed": False,
        "telegram_side_effects_allowed": False,
        "super_signals_side_effects_allowed": False,
    }
    manifest["manifest_digest"] = digest(manifest)
    return manifest
