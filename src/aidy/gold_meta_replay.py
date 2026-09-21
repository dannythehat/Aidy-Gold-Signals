"""Build 23: chronological replay, ablation and untouched holdout for AIDY Gold.

This module evaluates frozen Build-22-style decision states against outcomes that
became available later. It deliberately separates decision_state from outcome,
freezes the variant policy before evaluation, derives gate recommendations from
validation only, and forbids holdout-driven tuning.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from hashlib import sha256
from typing import Any

from aidy.gold_environment_contract import assert_no_hindsight_fields
from aidy.gold_meta_direction import (
    MIN_DIRECTIONAL_WEIGHT,
    NEUTRAL_MARGIN_RATIO,
    STRONG_CONTRADICTION_RATIO,
)

META_REPLAY_DATASET_VERSION = "aidy_gold_meta_replay_dataset_v1"
META_REPLAY_SPLIT_VERSION = "aidy_gold_meta_replay_split_v1"
META_REPLAY_POLICY_VERSION = "aidy_gold_meta_replay_policy_v1"
META_REPLAY_REPORT_VERSION = "aidy_gold_meta_replay_report_v1"

_SPLITS = ("development", "validation", "holdout")
_DIRECTIONS = {"bullish", "bearish", "neutral", "abstain"}
_SCORE_LARGE_MOVE_BPS = Decimal("5")


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value: object) -> str:
    return sha256(_canonical_json(value).encode()).hexdigest()


def _utc(value: datetime | str, *, name: str) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return parsed.astimezone(UTC)


def _decimal(
    value: Any,
    *,
    name: str,
    default: Decimal | None = None,
) -> Decimal:
    if value is None and default is not None:
        return default
    if isinstance(value, bool):
        raise TypeError(f"{name} must be numeric")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not parsed.is_finite():
        raise ValueError(f"{name} must be finite")
    return parsed


def _fmt(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_EVEN), "f")


def _direction(value: Any, *, allow_abstain: bool = True) -> str:
    text = str(value or "").strip().lower()
    allowed = _DIRECTIONS if allow_abstain else _DIRECTIONS - {"abstain"}
    if text not in allowed:
        raise ValueError(f"unsupported direction: {text}")
    return text


def build_meta_replay_dataset(
    rows: Sequence[Mapping[str, Any]],
    *,
    dataset_version: str,
    source_snapshot_identity: str,
    code_head: str,
) -> dict[str, Any]:
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in rows:
        case_id = str(raw.get("case_id") or "").strip()
        if not case_id or case_id in seen:
            raise ValueError("replay case_id values must be unique and non-empty")
        seen.add(case_id)
        as_of = _utc(str(raw.get("as_of_utc")), name=f"{case_id}.as_of_utc")
        available = _utc(
            str(raw.get("outcome_available_at_utc")),
            name=f"{case_id}.outcome_available_at_utc",
        )
        if available <= as_of:
            raise ValueError("replay outcome must become available after decision as-of")
        input_digest = str(raw.get("input_digest") or "").strip()
        if not input_digest:
            raise ValueError("replay case requires input_digest")
        environment_label = str(raw.get("environment_label") or "unknown").strip()

        decision_state = raw.get("decision_state")
        outcome = raw.get("outcome")
        if not isinstance(decision_state, Mapping):
            raise TypeError("replay decision_state must be a mapping")
        if not isinstance(outcome, Mapping):
            raise TypeError("replay outcome must be a mapping")
        assert_no_hindsight_fields(decision_state, path=f"replay.{case_id}.decision_state")
        if decision_state.get("future_values_used") is not False:
            raise ValueError("replay decision_state must explicitly be pre-outcome")

        legacy = _direction(decision_state.get("legacy_direction"))
        gates = decision_state.get("gates")
        if not isinstance(gates, Mapping):
            raise TypeError("replay decision_state.gates must be a mapping")
        normalized_gates: dict[str, dict[str, Any]] = {}
        for gate_id, gate in sorted(gates.items()):
            if not isinstance(gate, Mapping):
                raise TypeError("replay gate state must be a mapping")
            conclusion = _direction(gate.get("conclusion"))
            authority = _decimal(
                gate.get("authority_weight"),
                name=f"{gate_id}.authority_weight",
                default=Decimal(0),
            )
            raw_authority = _decimal(
                gate.get("raw_authority_weight"),
                name=f"{gate_id}.raw_authority_weight",
                default=authority,
            )
            if authority < 0 or raw_authority < 0:
                raise ValueError("gate authority weights cannot be negative")
            classification = str(gate.get("classification") or "reduced_trust")
            if classification not in {"high_trust", "reduced_trust", "unavailable"}:
                raise ValueError("unsupported gate classification")
            normalized_gates[str(gate_id)] = {
                "conclusion": conclusion,
                "authority_weight": _fmt(authority),
                "raw_authority_weight": _fmt(raw_authority),
                "classification": classification,
                "gate_mode": str(gate.get("gate_mode") or "directional"),
            }

        variant_confidences = decision_state.get("variant_confidences")
        variant_confidences = (
            dict(variant_confidences) if isinstance(variant_confidences, Mapping) else {}
        )
        for key, value in variant_confidences.items():
            confidence = _decimal(value, name=f"variant_confidences.{key}")
            if not Decimal(0) <= confidence <= Decimal(1):
                raise ValueError("variant confidence must be between 0 and 1")
            variant_confidences[key] = _fmt(confidence)

        realised_direction = _direction(outcome.get("direction"), allow_abstain=False)
        realised_return = _decimal(
            outcome.get("return_bps"),
            name=f"{case_id}.outcome.return_bps",
        )
        if outcome.get("evaluation_only") is not True:
            raise ValueError("replay outcome must be evaluation_only")

        row = {
            "case_id": case_id,
            "input_digest": input_digest,
            "as_of_utc": as_of.isoformat(),
            "outcome_available_at_utc": available.isoformat(),
            "environment_label": environment_label,
            "decision_state": {
                "legacy_direction": legacy,
                "gates": normalized_gates,
                "variant_confidences": dict(sorted(variant_confidences.items())),
                "future_values_used": False,
                "source_version": str(
                    decision_state.get("source_version") or "unknown"
                ),
            },
            "outcome": {
                "direction": realised_direction,
                "return_bps": _fmt(realised_return),
                "evaluation_only": True,
            },
        }
        row["case_digest"] = _digest(row)
        normalized.append(row)

    if not normalized:
        raise ValueError("replay dataset cannot be empty")
    normalized.sort(key=lambda item: (item["as_of_utc"], item["case_id"]))
    body = {
        "manifest_version": META_REPLAY_DATASET_VERSION,
        "dataset_version": str(dataset_version),
        "source_snapshot_identity": str(source_snapshot_identity),
        "code_head": str(code_head),
        "case_count": len(normalized),
        "cases": normalized,
        "first_as_of_utc": normalized[0]["as_of_utc"],
        "last_as_of_utc": normalized[-1]["as_of_utc"],
        "decision_outcome_separation_enforced": True,
        "immutable": True,
    }
    body["dataset_digest"] = _digest(body)
    return body


def verify_meta_replay_dataset(value: Mapping[str, Any]) -> bool:
    body = dict(value)
    supplied = str(body.pop("dataset_digest", ""))
    try:
        rows = body["cases"]
        if body.get("manifest_version") != META_REPLAY_DATASET_VERSION:
            return False
        if body.get("immutable") is not True:
            return False
        if body.get("decision_outcome_separation_enforced") is not True:
            return False
        if not isinstance(rows, list) or body.get("case_count") != len(rows) or not rows:
            return False
        ordered = sorted(rows, key=lambda item: (item["as_of_utc"], item["case_id"]))
        if rows != ordered:
            return False
        ids = [str(item["case_id"]) for item in rows]
        if len(ids) != len(set(ids)):
            return False
        for row in rows:
            row_body = dict(row)
            row_digest = str(row_body.pop("case_digest", ""))
            if row_digest != _digest(row_body):
                return False
            assert_no_hindsight_fields(
                row["decision_state"],
                path=f"verify.{row['case_id']}.decision_state",
            )
            if _utc(
                row["outcome_available_at_utc"],
                name="outcome_available_at_utc",
            ) <= _utc(row["as_of_utc"], name="as_of_utc"):
                return False
    except (KeyError, TypeError, ValueError):
        return False
    return bool(supplied) and supplied == _digest(body)


def build_meta_replay_split(
    dataset: Mapping[str, Any],
    *,
    development_end: datetime | str,
    validation_end: datetime | str,
    holdout_end: datetime | str,
    purge_minutes: int,
    embargo_minutes: int,
    holdout_identity: str,
) -> dict[str, Any]:
    if not verify_meta_replay_dataset(dataset):
        raise ValueError("Build 23 requires a verified replay dataset")
    development_end_dt = _utc(development_end, name="development_end")
    validation_end_dt = _utc(validation_end, name="validation_end")
    holdout_end_dt = _utc(holdout_end, name="holdout_end")
    if not development_end_dt < validation_end_dt < holdout_end_dt:
        raise ValueError("replay split boundaries must be strictly increasing")
    if purge_minutes < 0 or embargo_minutes < 0:
        raise ValueError("purge and embargo minutes must be non-negative")

    nominal: dict[str, list[dict[str, Any]]] = {name: [] for name in _SPLITS}
    unused: list[str] = []
    for row in dataset["cases"]:
        as_of = _utc(row["as_of_utc"], name="case.as_of_utc")
        if as_of <= development_end_dt:
            nominal["development"].append(row)
        elif as_of <= validation_end_dt:
            nominal["validation"].append(row)
        elif as_of <= holdout_end_dt:
            nominal["holdout"].append(row)
        else:
            unused.append(str(row["case_id"]))

    retained = {
        name: [str(row["case_id"]) for row in rows]
        for name, rows in nominal.items()
    }
    purged: dict[str, list[str]] = {}
    for prior, boundary, label in (
        ("development", development_end_dt, "development_before_validation"),
        ("validation", validation_end_dt, "validation_before_holdout"),
    ):
        cutoff = boundary - timedelta(minutes=purge_minutes)
        ids = [
            str(row["case_id"])
            for row in nominal[prior]
            if _utc(
                row["outcome_available_at_utc"],
                name="outcome_available_at_utc",
            ) > cutoff
        ]
        purged[label] = ids
        retained[prior] = [case_id for case_id in retained[prior] if case_id not in set(ids)]

    embargoed: dict[str, list[str]] = {"validation": [], "holdout": []}
    for split_name, boundary in (
        ("validation", development_end_dt),
        ("holdout", validation_end_dt),
    ):
        threshold = boundary + timedelta(minutes=embargo_minutes)
        ids = [
            str(row["case_id"])
            for row in nominal[split_name]
            if _utc(row["as_of_utc"], name="case.as_of_utc") <= threshold
        ]
        embargoed[split_name] = ids
        retained[split_name] = [
            case_id for case_id in retained[split_name] if case_id not in set(ids)
        ]

    body = {
        "manifest_version": META_REPLAY_SPLIT_VERSION,
        "dataset_digest": str(dataset["dataset_digest"]),
        "boundaries": {
            "development_end": development_end_dt.isoformat(),
            "validation_end": validation_end_dt.isoformat(),
            "holdout_end": holdout_end_dt.isoformat(),
        },
        "purge_minutes": int(purge_minutes),
        "embargo_minutes": int(embargo_minutes),
        "splits": retained,
        "purged_from_prior": purged,
        "embargoed_from_split_start": embargoed,
        "unused_case_ids": unused,
        "holdout_identity": str(holdout_identity),
        "holdout_tuning_allowed": False,
        "holdout_recommendation_updates_allowed": False,
    }
    body["split_digest"] = _digest(body)
    return body


def verify_meta_replay_split(
    value: Mapping[str, Any],
    dataset: Mapping[str, Any],
) -> bool:
    body = dict(value)
    supplied = str(body.pop("split_digest", ""))
    try:
        if body.get("manifest_version") != META_REPLAY_SPLIT_VERSION:
            return False
        if body.get("dataset_digest") != dataset.get("dataset_digest"):
            return False
        if body.get("holdout_tuning_allowed") is not False:
            return False
        if body.get("holdout_recommendation_updates_allowed") is not False:
            return False
        all_ids: list[str] = []
        for name in _SPLITS:
            ids = list(body["splits"][name])
            if len(ids) != len(set(ids)):
                return False
            all_ids.extend(ids)
        if len(all_ids) != len(set(all_ids)):
            return False
        dataset_ids = {str(row["case_id"]) for row in dataset["cases"]}
        if not set(all_ids).issubset(dataset_ids):
            return False
    except (KeyError, TypeError, ValueError):
        return False
    return bool(supplied) and supplied == _digest(body)


def build_meta_replay_policy(gate_ids: Sequence[str]) -> dict[str, Any]:
    gates = sorted({str(item).strip() for item in gate_ids if str(item).strip()})
    if not gates:
        raise ValueError("Build 23 replay policy requires at least one gate")
    variants = [
        "legacy_simple_15m",
        "full_system_dependency_on",
        "full_system_dependency_off",
        *(f"gate_only:{gate_id}" for gate_id in gates),
        *(f"full_minus:{gate_id}" for gate_id in gates),
    ]
    body = {
        "policy_version": META_REPLAY_POLICY_VERSION,
        "gate_ids": gates,
        "variants": variants,
        "min_directional_weight": _fmt(MIN_DIRECTIONAL_WEIGHT),
        "neutral_margin_ratio": _fmt(NEUTRAL_MARGIN_RATIO),
        "strong_contradiction_ratio": _fmt(STRONG_CONTRADICTION_RATIO),
        "large_move_bps": _fmt(_SCORE_LARGE_MOVE_BPS),
        "recommendations_derived_from": "validation_only",
        "development_can_promote_gate": False,
        "holdout_can_tune_or_promote": False,
        "dependency_ablation_required": True,
    }
    body["policy_digest"] = _digest(body)
    return body


def verify_meta_replay_policy(value: Mapping[str, Any]) -> bool:
    body = dict(value)
    supplied = str(body.pop("policy_digest", ""))
    return (
        bool(supplied)
        and supplied == _digest(body)
        and body.get("policy_version") == META_REPLAY_POLICY_VERSION
        and body.get("recommendations_derived_from") == "validation_only"
        and body.get("development_can_promote_gate") is False
        and body.get("holdout_can_tune_or_promote") is False
    )


def _aggregate_gates(
    gates: Mapping[str, Mapping[str, Any]],
    *,
    weight_key: str,
    include_gate_ids: set[str] | None = None,
) -> str:
    bullish = Decimal(0)
    bearish = Decimal(0)
    neutral = Decimal(0)
    high_bull = False
    high_bear = False
    for gate_id, gate in gates.items():
        if include_gate_ids is not None and gate_id not in include_gate_ids:
            continue
        if str(gate.get("gate_mode") or "directional") != "directional":
            continue
        if str(gate.get("classification") or "") == "unavailable":
            continue
        conclusion = _direction(gate.get("conclusion"))
        weight = _decimal(gate.get(weight_key), name=f"{gate_id}.{weight_key}", default=Decimal(0))
        if weight <= 0:
            continue
        if conclusion == "bullish":
            bullish += weight
            high_bull = high_bull or str(gate.get("classification")) == "high_trust"
        elif conclusion == "bearish":
            bearish += weight
            high_bear = high_bear or str(gate.get("classification")) == "high_trust"
        elif conclusion == "neutral":
            neutral += weight

    directional_total = bullish + bearish
    if directional_total < MIN_DIRECTIONAL_WEIGHT:
        return "abstain"
    contradiction_ratio = (
        Decimal(0)
        if directional_total == 0
        else min(bullish, bearish) / directional_total
    )
    if contradiction_ratio >= STRONG_CONTRADICTION_RATIO or (high_bull and high_bear):
        return "abstain"
    if neutral >= max(bullish, bearish) and neutral > 0:
        return "neutral"
    signed = bullish - bearish
    margin_ratio = Decimal(0) if directional_total == 0 else abs(signed) / directional_total
    if margin_ratio < NEUTRAL_MARGIN_RATIO:
        return "neutral"
    if signed > 0:
        return "bullish"
    if signed < 0:
        return "bearish"
    return "neutral"


def _variant_prediction(
    row: Mapping[str, Any],
    *,
    variant: str,
    policy: Mapping[str, Any],
) -> str:
    decision = row["decision_state"]
    gates = decision["gates"]
    if variant == "legacy_simple_15m":
        return _direction(decision["legacy_direction"])
    if variant == "full_system_dependency_on":
        return _aggregate_gates(gates, weight_key="authority_weight")
    if variant == "full_system_dependency_off":
        return _aggregate_gates(gates, weight_key="raw_authority_weight")
    if variant.startswith("gate_only:"):
        gate_id = variant.split(":", 1)[1]
        return _aggregate_gates(
            gates,
            weight_key="authority_weight",
            include_gate_ids={gate_id},
        )
    if variant.startswith("full_minus:"):
        excluded = variant.split(":", 1)[1]
        included = set(policy["gate_ids"]) - {excluded}
        return _aggregate_gates(
            gates,
            weight_key="authority_weight",
            include_gate_ids=included,
        )
    raise ValueError(f"unsupported replay variant: {variant}")


def _case_score(prediction: str, outcome: str, return_bps: Decimal) -> int:
    if prediction == "abstain":
        return 0
    impact = 2 if abs(return_bps) >= _SCORE_LARGE_MOVE_BPS else 1
    return impact if prediction == outcome else -impact


def _metrics(
    rows: Sequence[Mapping[str, Any]],
    *,
    variant: str,
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    total_n = len(rows)
    covered_n = 0
    correct_n = 0
    net_score = 0
    class_counts: dict[str, dict[str, int]] = defaultdict(
        lambda: {"covered_n": 0, "correct_n": 0}
    )
    brier_values: list[Decimal] = []
    predictions: list[tuple[str, str, bool]] = []

    for row in rows:
        prediction = _variant_prediction(row, variant=variant, policy=policy)
        outcome = _direction(row["outcome"]["direction"], allow_abstain=False)
        return_bps = _decimal(row["outcome"]["return_bps"], name="outcome.return_bps")
        correct = prediction == outcome
        net_score += _case_score(prediction, outcome, return_bps)
        if prediction != "abstain":
            covered_n += 1
            correct_n += int(correct)
            class_counts[outcome]["covered_n"] += 1
            class_counts[outcome]["correct_n"] += int(correct)
        predictions.append((prediction, outcome, correct))

        confidence = row["decision_state"]["variant_confidences"].get(variant)
        if (
            confidence is not None
            and prediction in {"bullish", "bearish"}
            and outcome in {"bullish", "bearish"}
        ):
            conf = _decimal(confidence, name="variant_confidence")
            p_bull = conf if prediction == "bullish" else Decimal(1) - conf
            y = Decimal(1) if outcome == "bullish" else Decimal(0)
            brier_values.append((p_bull - y) ** 2)

    accuracy = Decimal(correct_n) / Decimal(covered_n) if covered_n else None
    coverage = Decimal(covered_n) / Decimal(total_n) if total_n else Decimal(0)
    score_mean = Decimal(net_score) / Decimal(total_n) if total_n else Decimal(0)
    brier = (
        sum(brier_values, Decimal(0)) / Decimal(len(brier_values))
        if brier_values
        else None
    )

    class_metrics = {}
    for name in sorted(class_counts):
        counts = class_counts[name]
        class_metrics[name] = {
            **counts,
            "accuracy": (
                _fmt(
                    Decimal(counts["correct_n"]) / Decimal(counts["covered_n"])
                )
                if counts["covered_n"]
                else None
            ),
        }

    midpoint = total_n // 2
    halves = [rows[:midpoint], rows[midpoint:]] if total_n >= 4 else [[], []]
    half_accuracies: list[Decimal | None] = []
    for half in halves:
        half_covered = 0
        half_correct = 0
        for row in half:
            pred = _variant_prediction(row, variant=variant, policy=policy)
            if pred == "abstain":
                continue
            half_covered += 1
            half_correct += int(pred == row["outcome"]["direction"])
        half_accuracies.append(
            Decimal(half_correct) / Decimal(half_covered) if half_covered else None
        )
    stability_gap = (
        abs(half_accuracies[0] - half_accuracies[1])
        if half_accuracies[0] is not None and half_accuracies[1] is not None
        else None
    )

    by_environment: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        by_environment[str(row["environment_label"])].append(row)
    environment_metrics = {}
    for label, env_rows in sorted(by_environment.items()):
        env_covered = 0
        env_correct = 0
        env_score = 0
        for row in env_rows:
            pred = _variant_prediction(row, variant=variant, policy=policy)
            outcome = row["outcome"]["direction"]
            return_bps = _decimal(row["outcome"]["return_bps"], name="outcome.return_bps")
            env_score += _case_score(pred, outcome, return_bps)
            if pred != "abstain":
                env_covered += 1
                env_correct += int(pred == outcome)
        environment_metrics[label] = {
            "sample_n": len(env_rows),
            "covered_n": env_covered,
            "accuracy": (
                _fmt(Decimal(env_correct) / Decimal(env_covered))
                if env_covered
                else None
            ),
            "net_score": env_score,
        }

    return {
        "sample_n": total_n,
        "covered_n": covered_n,
        "abstain_n": total_n - covered_n,
        "coverage": _fmt(coverage),
        "correct_n": correct_n,
        "accuracy": _fmt(accuracy),
        "net_score": net_score,
        "score_mean": _fmt(score_mean),
        "brier": _fmt(brier),
        "brier_sample_n": len(brier_values),
        "directional_accuracy_by_class": class_metrics,
        "performance_by_environment": environment_metrics,
        "stability_first_half_accuracy": _fmt(half_accuracies[0]),
        "stability_second_half_accuracy": _fmt(half_accuracies[1]),
        "stability_accuracy_gap": _fmt(stability_gap),
    }


def _validation_recommendations(
    validation_metrics: Mapping[str, Mapping[str, Any]],
    *,
    gate_ids: Sequence[str],
) -> dict[str, Any]:
    full = validation_metrics["full_system_dependency_on"]
    full_accuracy = _decimal(full.get("accuracy"), name="full.accuracy", default=Decimal(0))
    full_score = _decimal(full.get("score_mean"), name="full.score_mean", default=Decimal(0))
    gates: dict[str, dict[str, Any]] = {}
    for gate_id in gate_ids:
        minus = validation_metrics[f"full_minus:{gate_id}"]
        minus_accuracy = _decimal(
            minus.get("accuracy"),
            name=f"minus.{gate_id}.accuracy",
            default=Decimal(0),
        )
        minus_score = _decimal(
            minus.get("score_mean"),
            name=f"minus.{gate_id}.score_mean",
            default=Decimal(0),
        )
        delta_accuracy = full_accuracy - minus_accuracy
        delta_score = full_score - minus_score
        recommendation = (
            "prune_or_downweight"
            if delta_accuracy <= 0 and delta_score <= 0
            else "retain_candidate"
        )
        gates[gate_id] = {
            "recommendation": recommendation,
            "validation_delta_accuracy": _fmt(delta_accuracy),
            "validation_delta_score_mean": _fmt(delta_score),
            "development_metrics_used_for_recommendation": False,
            "holdout_metrics_used_for_recommendation": False,
        }

    dep_on = validation_metrics["full_system_dependency_on"]
    dep_off = validation_metrics["full_system_dependency_off"]
    dep_on_acc = _decimal(dep_on.get("accuracy"), name="dep_on.accuracy", default=Decimal(0))
    dep_off_acc = _decimal(dep_off.get("accuracy"), name="dep_off.accuracy", default=Decimal(0))
    dep_on_score = _decimal(dep_on.get("score_mean"), name="dep_on.score_mean", default=Decimal(0))
    dep_off_score = _decimal(dep_off.get("score_mean"), name="dep_off.score_mean", default=Decimal(0))
    dependency = {
        "recommendation": (
            "retain_dependency_penalty"
            if dep_on_acc > dep_off_acc or dep_on_score > dep_off_score
            else "dependency_penalty_not_proven_incremental"
        ),
        "validation_delta_accuracy": _fmt(dep_on_acc - dep_off_acc),
        "validation_delta_score_mean": _fmt(dep_on_score - dep_off_score),
        "holdout_metrics_used_for_recommendation": False,
    }
    return {
        "gate_recommendations": gates,
        "dependency_recommendation": dependency,
        "recommendations_derived_from": "validation_only",
        "in_sample_development_promotion_allowed": False,
        "holdout_recommendation_updates_allowed": False,
    }


def build_meta_replay_report(
    *,
    dataset: Mapping[str, Any],
    split_manifest: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    if not verify_meta_replay_dataset(dataset):
        raise ValueError("Build 23 requires a verified replay dataset")
    if not verify_meta_replay_split(split_manifest, dataset):
        raise ValueError("Build 23 requires a verified chronological split")
    if not verify_meta_replay_policy(policy):
        raise ValueError("Build 23 requires a frozen replay policy")

    by_id = {str(row["case_id"]): row for row in dataset["cases"]}
    split_metrics: dict[str, dict[str, Any]] = {}
    for split_name in _SPLITS:
        rows = [by_id[case_id] for case_id in split_manifest["splits"][split_name]]
        split_metrics[split_name] = {
            variant: _metrics(rows, variant=variant, policy=policy)
            for variant in policy["variants"]
        }

    recommendations = _validation_recommendations(
        split_metrics["validation"],
        gate_ids=policy["gate_ids"],
    )
    legacy_holdout = split_metrics["holdout"]["legacy_simple_15m"]
    full_holdout = split_metrics["holdout"]["full_system_dependency_on"]
    legacy_acc = _decimal(
        legacy_holdout.get("accuracy"),
        name="legacy_holdout.accuracy",
        default=Decimal(0),
    )
    full_acc = _decimal(
        full_holdout.get("accuracy"),
        name="full_holdout.accuracy",
        default=Decimal(0),
    )
    legacy_score = _decimal(
        legacy_holdout.get("score_mean"),
        name="legacy_holdout.score_mean",
        default=Decimal(0),
    )
    full_score = _decimal(
        full_holdout.get("score_mean"),
        name="full_holdout.score_mean",
        default=Decimal(0),
    )
    holdout_comparison = {
        "full_minus_legacy_accuracy": _fmt(full_acc - legacy_acc),
        "full_minus_legacy_score_mean": _fmt(full_score - legacy_score),
        "holdout_used_for_tuning": False,
        "holdout_can_change_gate_recommendations": False,
        "empirical_edge_claimed": False,
    }

    body = {
        "report_version": META_REPLAY_REPORT_VERSION,
        "dataset_digest": str(dataset["dataset_digest"]),
        "split_digest": str(split_manifest["split_digest"]),
        "policy_digest": str(policy["policy_digest"]),
        "split_metrics": split_metrics,
        "validation_recommendations": recommendations,
        "untouched_holdout_comparison": holdout_comparison,
        "comparisons_present": {
            "legacy_simple_15m": True,
            "each_gate_alone": True,
            "full_system": True,
            "full_minus_each_gate": True,
            "with_without_dependency_penalty": True,
        },
        "metrics_present": {
            "directional_accuracy_by_class": True,
            "plus_minus_impact_score": True,
            "brier_where_available": True,
            "coverage_abstention": True,
            "performance_by_environment": True,
            "stability_across_time": True,
            "incremental_contribution": True,
            "sample_n": True,
        },
        "development_used_for_gate_promotion": False,
        "holdout_tuning_allowed": False,
        "holdout_recommendation_updates_allowed": False,
        "results_reproducible_from_versioned_inputs": True,
        "fixture_or_historical_source_must_be_disclosed": True,
        "future_values_used_for_prediction": False,
        "formal_forward_evidence_created": False,
        "live_money_execution_allowed": False,
    }
    body["report_digest"] = _digest(body)
    return body


def verify_meta_replay_report(value: Mapping[str, Any]) -> bool:
    body = dict(value)
    supplied = str(body.pop("report_digest", ""))
    return (
        bool(supplied)
        and supplied == _digest(body)
        and body.get("report_version") == META_REPLAY_REPORT_VERSION
        and body.get("development_used_for_gate_promotion") is False
        and body.get("holdout_tuning_allowed") is False
        and body.get("holdout_recommendation_updates_allowed") is False
        and body.get("results_reproducible_from_versioned_inputs") is True
        and body.get("future_values_used_for_prediction") is False
        and body.get("live_money_execution_allowed") is False
    )


__all__ = [
    "META_REPLAY_DATASET_VERSION",
    "META_REPLAY_POLICY_VERSION",
    "META_REPLAY_REPORT_VERSION",
    "META_REPLAY_SPLIT_VERSION",
    "build_meta_replay_dataset",
    "build_meta_replay_policy",
    "build_meta_replay_report",
    "build_meta_replay_split",
    "verify_meta_replay_dataset",
    "verify_meta_replay_policy",
    "verify_meta_replay_report",
    "verify_meta_replay_split",
]
