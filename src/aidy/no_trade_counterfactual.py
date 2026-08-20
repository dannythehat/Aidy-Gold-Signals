from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Any

from aidy.bigquery_exporter import FieldSpec, TableSpec
from aidy.move_detective import build_move_bundle, verify_move_bundle_digest
from aidy.trade_outcomes import (
    build_trade_outcome_bundle,
    verify_trade_outcome_bundle_digest,
)

SETUP_EVIDENCE_VERSION = "aidy_no_trade_setup_eligibility_v1"
COUNTERFACTUAL_VERSION = "aidy_no_trade_counterfactual_v1"
COUNTERFACTUAL_DISTRIBUTION_VERSION = "aidy_no_trade_counterfactual_distribution_v1"
COUNTERFACTUAL_DIGEST_ALGORITHM = "sha256"
COUNTERFACTUAL_CONTRACT_CLASS = "research_future_no_trade_counterfactual"
SUPPORTED_SYMBOL = "XAUUSD"
HORIZONS_MINUTES = (15, 60, 240)
PRIMARY_HORIZON_MINUTES = 240

_SETUP_STATES = {"present", "absent", "ambiguous", "unknown"}
_RISK_STATES = {"valid", "invalid", "unknown", "not_applicable"}
_DIRECTIONS = {"long", "short"}
_CLASSIFICATIONS = {"good_restraint", "missed_opportunity", "indeterminate"}
_FORBIDDEN_REASON_TOKENS = (
    "future",
    "outcome",
    "mfe",
    "mae",
    "target_hit",
    "stop_hit",
    "pnl",
    "profit",
    "loss",
    "winner",
    "loser",
    "subsequent",
)
_HEX = frozenset("0123456789abcdef")
_SETUP_EVIDENCE_KEYS = {
    "evidence_version",
    "evidence_digest_algorithm",
    "symbol",
    "as_of_utc",
    "pit_eligible",
    "future_derived",
    "decision_input_allowed",
    "taxonomy_version",
    "detector_version",
    "source_context_hash",
    "source_regime_digest",
    "setup_state",
    "risk_state",
    "candidate_setup_ids",
    "direction",
    "trade_spec",
    "reason_codes",
    "evidence_digest",
}
_TRADE_SPEC_KEYS = {"entry_type", "entry", "stop_loss", "targets"}

RESEARCH_NO_TRADE_COUNTERFACTUALS = TableSpec(
    name="research_no_trade_counterfactuals",
    partition_field="decision_time_utc",
    clustering_fields=("symbol", "primary_classification", "primary_reason_code"),
    fields=(
        FieldSpec("counterfactual_digest", "STRING", "REQUIRED"),
        FieldSpec("counterfactual_version", "STRING", "REQUIRED"),
        FieldSpec("contract_class", "STRING", "REQUIRED"),
        FieldSpec("evaluation_only", "BOOLEAN", "REQUIRED"),
        FieldSpec("future_derived", "BOOLEAN", "REQUIRED"),
        FieldSpec("pit_eligible", "BOOLEAN", "REQUIRED"),
        FieldSpec("decision_input_allowed", "BOOLEAN", "REQUIRED"),
        FieldSpec("symbol", "STRING", "REQUIRED"),
        FieldSpec("decision_id", "STRING", "REQUIRED"),
        FieldSpec("decision_type", "STRING", "REQUIRED"),
        FieldSpec("decision_time_utc", "TIMESTAMP", "REQUIRED"),
        FieldSpec("anchor_price", "STRING", "REQUIRED"),
        FieldSpec("available_after_utc", "TIMESTAMP", "REQUIRED"),
        FieldSpec("primary_horizon_minutes", "INTEGER", "REQUIRED"),
        FieldSpec("primary_classification", "STRING", "REQUIRED"),
        FieldSpec("primary_reason_code", "STRING", "REQUIRED"),
        FieldSpec("setup_evidence", "JSON", "REQUIRED"),
        FieldSpec("path_bundle", "JSON", "REQUIRED"),
        FieldSpec("trade_outcome_bundle", "JSON", "NULLABLE"),
        FieldSpec("horizon_assessments", "JSON", "REQUIRED"),
    ),
)


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
            raise ValueError(f"Invalid no_trade timestamp: {value}") from exc
    else:
        raise TypeError("no_trade timestamps must be timezone-aware datetime or ISO-8601 text.")
    if parsed.tzinfo is None:
        raise ValueError("no_trade timestamps must be timezone-aware.")
    return parsed.astimezone(UTC)


def _positive_decimal(value: Any, *, name: str) -> Decimal:
    if value is None or isinstance(value, bool):
        raise TypeError(f"{name} must be a finite positive decimal.")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{name} must be a finite positive decimal.") from exc
    if not parsed.is_finite() or parsed <= 0:
        raise ValueError(f"{name} must be a finite positive decimal.")
    return parsed


def _decimal_text(value: Decimal) -> str:
    if value == 0:
        return "0"
    text = format(value.normalize(), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _version(value: Any, *, name: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise ValueError(f"{name} must be a non-empty version identifier.")
    return result


def _hex_digest(value: Any, *, name: str) -> str:
    result = str(value or "").strip().lower()
    if len(result) != 64 or any(character not in _HEX for character in result):
        raise ValueError(f"{name} must be a 64-character lowercase SHA-256 digest.")
    return result


def _string_list(values: Iterable[Any], *, name: str, allow_empty: bool) -> list[str]:
    items = sorted(
        {
            str(value).strip()
            for value in values
            if value is not None and str(value).strip()
        }
    )
    if not allow_empty and not items:
        raise ValueError(f"{name} must contain at least one non-empty identifier.")
    if any(re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", item) is None for item in items):
        raise ValueError(f"{name} values must be stable identifier slugs, not free text.")
    if name == "reason_codes":
        for item in items:
            normalized = item.lower()
            if any(token in normalized for token in _FORBIDDEN_REASON_TOKENS):
                raise ValueError("reason_codes cannot encode future/outcome information.")
    return items


def _normalize_trade_spec(
    value: Mapping[str, Any] | None,
    *,
    direction: str,
) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise TypeError("trade_spec must be an object when supplied.")
    extra = set(value) - _TRADE_SPEC_KEYS
    missing = _TRADE_SPEC_KEYS - set(value)
    if extra or missing:
        raise ValueError(
            "trade_spec must contain exactly entry_type, entry, stop_loss and targets."
        )

    entry_type = str(value.get("entry_type") or "").strip().lower()
    if entry_type != "market":
        raise ValueError("Day 14 v1 accepts market-entry candidate geometry only.")

    entry = _positive_decimal(value.get("entry"), name="trade_spec.entry")
    stop_loss = _positive_decimal(value.get("stop_loss"), name="trade_spec.stop_loss")
    raw_targets = value.get("targets")
    if not isinstance(raw_targets, (list, tuple)):
        raise TypeError("trade_spec.targets must be a list.")
    targets = tuple(
        _positive_decimal(target, name="trade_spec.target") for target in raw_targets
    )
    if not 1 <= len(targets) <= 3:
        raise ValueError("trade_spec requires between one and three targets.")
    if len(set(targets)) != len(targets):
        raise ValueError("trade_spec targets must be unique.")

    if direction == "long":
        if stop_loss >= entry:
            raise ValueError("Long candidate stop_loss must be below entry.")
        if any(target <= entry for target in targets):
            raise ValueError("Long candidate targets must be above entry.")
        if list(targets) != sorted(targets):
            raise ValueError("Long candidate targets must be strictly increasing.")
    elif direction == "short":
        if stop_loss <= entry:
            raise ValueError("Short candidate stop_loss must be above entry.")
        if any(target >= entry for target in targets):
            raise ValueError("Short candidate targets must be below entry.")
        if list(targets) != sorted(targets, reverse=True):
            raise ValueError("Short candidate targets must be strictly decreasing.")
    else:
        raise ValueError("trade_spec requires a long or short setup direction.")

    return {
        "entry_type": "market",
        "entry": _decimal_text(entry),
        "stop_loss": _decimal_text(stop_loss),
        "targets": [_decimal_text(target) for target in targets],
    }


def compute_setup_evidence_digest(evidence: Mapping[str, Any]) -> str:
    body = dict(evidence)
    body.pop("evidence_digest", None)
    return _digest(body)


def verify_setup_evidence_digest(evidence: Mapping[str, Any]) -> bool:
    supplied = str(evidence.get("evidence_digest") or "")
    return bool(supplied) and supplied == compute_setup_evidence_digest(evidence)


def build_setup_eligibility_evidence(
    *,
    as_of: datetime | str,
    taxonomy_version: str,
    detector_version: str,
    source_context_hash: str,
    source_regime_digest: str,
    setup_state: str,
    risk_state: str,
    candidate_setup_ids: Iterable[str] = (),
    direction: str | None = None,
    trade_spec: Mapping[str, Any] | None = None,
    reason_codes: Iterable[str] = (),
) -> dict[str, Any]:
    """Build the Day 14 adapter contract; this does not detect setups."""

    as_of_utc = _utc(as_of)
    normalized_setup = str(setup_state).strip().lower()
    normalized_risk = str(risk_state).strip().lower()
    normalized_direction = None if direction is None else str(direction).strip().lower()
    if normalized_setup not in _SETUP_STATES:
        raise ValueError("setup_state must be present, absent, ambiguous or unknown.")
    if normalized_risk not in _RISK_STATES:
        raise ValueError("risk_state must be valid, invalid, unknown or not_applicable.")
    setup_ids = _string_list(
        candidate_setup_ids,
        name="candidate_setup_ids",
        allow_empty=normalized_setup in {"absent", "unknown"},
    )
    reasons = _string_list(reason_codes, name="reason_codes", allow_empty=False)

    if normalized_setup == "present":
        if normalized_direction not in _DIRECTIONS:
            raise ValueError("A present setup requires a long or short direction.")
        if normalized_risk == "not_applicable":
            raise ValueError("A present setup cannot use risk_state=not_applicable.")
    elif normalized_setup == "absent":
        if (
            normalized_direction is not None
            or normalized_risk != "not_applicable"
            or trade_spec is not None
        ):
            raise ValueError(
                "An absent setup has no direction/trade_spec and risk is not_applicable."
            )
    elif normalized_setup == "ambiguous":
        if len(setup_ids) < 2:
            raise ValueError("An ambiguous setup requires at least two candidate setup IDs.")
        if (
            normalized_direction is not None
            or normalized_risk != "unknown"
            or trade_spec is not None
        ):
            raise ValueError("An ambiguous setup must keep direction/risk/trade_spec unresolved.")
    else:
        if (
            normalized_direction is not None
            or normalized_risk != "unknown"
            or trade_spec is not None
        ):
            raise ValueError("An unknown setup must keep direction/risk/trade_spec unresolved.")

    normalized_spec = _normalize_trade_spec(
        trade_spec,
        direction=normalized_direction or "",
    )
    if normalized_setup == "present" and normalized_risk == "valid" and normalized_spec is None:
        raise ValueError("A present setup with valid risk requires market-entry trade_spec.")
    if normalized_setup == "present" and normalized_risk != "valid" and normalized_spec is not None:
        raise ValueError("trade_spec is allowed only when setup is present and risk is valid.")

    evidence: dict[str, Any] = {
        "evidence_version": SETUP_EVIDENCE_VERSION,
        "evidence_digest_algorithm": COUNTERFACTUAL_DIGEST_ALGORITHM,
        "symbol": SUPPORTED_SYMBOL,
        "as_of_utc": as_of_utc.isoformat(),
        "pit_eligible": True,
        "future_derived": False,
        "decision_input_allowed": True,
        "taxonomy_version": _version(taxonomy_version, name="taxonomy_version"),
        "detector_version": _version(detector_version, name="detector_version"),
        "source_context_hash": _hex_digest(source_context_hash, name="source_context_hash"),
        "source_regime_digest": _hex_digest(source_regime_digest, name="source_regime_digest"),
        "setup_state": normalized_setup,
        "risk_state": normalized_risk,
        "candidate_setup_ids": setup_ids,
        "direction": normalized_direction,
        "trade_spec": normalized_spec,
        "reason_codes": reasons,
    }
    evidence["evidence_digest"] = compute_setup_evidence_digest(evidence)
    return evidence


def _validate_setup_evidence(
    evidence: Mapping[str, Any],
    *,
    decision_time: datetime,
    anchor_price: Decimal,
) -> dict[str, Any]:
    if not isinstance(evidence, Mapping):
        raise TypeError("setup_evidence must be an object.")
    if set(evidence) != _SETUP_EVIDENCE_KEYS:
        raise ValueError("setup_evidence contains unsupported or missing fields.")
    if evidence.get("evidence_version") != SETUP_EVIDENCE_VERSION:
        raise ValueError("Unsupported setup eligibility evidence version.")
    if evidence.get("evidence_digest_algorithm") != COUNTERFACTUAL_DIGEST_ALGORITHM:
        raise ValueError("Unsupported setup evidence digest algorithm.")
    if not verify_setup_evidence_digest(evidence):
        raise ValueError("setup_evidence digest does not match its contents.")
    if (
        evidence.get("pit_eligible") is not True
        or evidence.get("future_derived") is not False
        or evidence.get("decision_input_allowed") is not True
    ):
        raise ValueError("setup_evidence must be PIT-safe decision-time evidence.")
    if evidence.get("symbol") != SUPPORTED_SYMBOL:
        raise ValueError(f"Day 14 supports only {SUPPORTED_SYMBOL}.")
    if _utc(evidence.get("as_of_utc")) != decision_time:
        raise ValueError("setup_evidence as_of_utc must exactly match the no_trade decision time.")

    normalized = build_setup_eligibility_evidence(
        as_of=evidence["as_of_utc"],
        taxonomy_version=str(evidence["taxonomy_version"]),
        detector_version=str(evidence["detector_version"]),
        source_context_hash=str(evidence["source_context_hash"]),
        source_regime_digest=str(evidence["source_regime_digest"]),
        setup_state=str(evidence["setup_state"]),
        risk_state=str(evidence["risk_state"]),
        candidate_setup_ids=list(evidence["candidate_setup_ids"]),
        direction=None if evidence["direction"] is None else str(evidence["direction"]),
        trade_spec=evidence["trade_spec"],
        reason_codes=list(evidence["reason_codes"]),
    )
    if normalized != dict(evidence):
        raise ValueError("setup_evidence is not in canonical Day 14 form.")

    if evidence["setup_state"] == "present" and evidence["risk_state"] == "valid":
        trade_spec = evidence["trade_spec"]
        if not isinstance(trade_spec, Mapping):
            raise TypeError("Valid setup risk evidence requires trade_spec.")
        entry = _positive_decimal(trade_spec.get("entry"), name="trade_spec.entry")
        if entry != anchor_price:
            raise ValueError("Day 14 v1 market-entry trade_spec.entry must equal anchor_price.")
    return normalized


def _assessment_without_trade(setup_evidence: Mapping[str, Any]) -> tuple[str, str]:
    setup_state = str(setup_evidence["setup_state"])
    risk_state = str(setup_evidence["risk_state"])
    if setup_state == "absent":
        return "good_restraint", "no_valid_setup_at_decision"
    if setup_state == "ambiguous":
        return "indeterminate", "setup_evidence_ambiguous"
    if setup_state == "unknown":
        return "indeterminate", "setup_evidence_unknown"
    if risk_state == "invalid":
        return "good_restraint", "risk_invalid_at_decision"
    if risk_state == "unknown":
        return "indeterminate", "risk_evidence_unknown"
    raise ValueError("Trade outcome evidence is required for a present setup with valid risk.")


def _assessment_from_trade_outcome(outcome: Mapping[str, Any]) -> tuple[str, str]:
    if outcome.get("coverage_state") != "complete":
        return "indeterminate", "future_outcome_incomplete"
    state = str(outcome.get("outcome_state") or "unknown")
    if state in {"target_before_stop", "target_only"}:
        return "missed_opportunity", "valid_setup_target_before_stop"
    if state in {"stop_before_any_target", "stop_only"}:
        return "good_restraint", "valid_setup_stop_before_target"
    if state == "same_bar_order_unknown":
        return "indeterminate", "stop_target_same_bar_order_unknown"
    if state == "neither":
        return "indeterminate", "valid_setup_no_decisive_level_outcome"
    return "indeterminate", "future_outcome_unknown"


def compute_no_trade_counterfactual_digest(record: Mapping[str, Any]) -> str:
    body = dict(record)
    body.pop("counterfactual_digest", None)
    return _digest(body)


def verify_no_trade_counterfactual_digest(record: Mapping[str, Any]) -> bool:
    supplied = str(record.get("counterfactual_digest") or "")
    return bool(supplied) and supplied == compute_no_trade_counterfactual_digest(record)


def build_no_trade_counterfactual(
    *,
    decision_id: str,
    decision_time: datetime | str,
    anchor_price: Any,
    setup_evidence: Mapping[str, Any],
    research_rows: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Evaluate one no_trade decision without allowing future price to create setup validity."""

    identifier = str(decision_id or "").strip()
    if not identifier:
        raise ValueError("decision_id must be non-empty.")
    as_of = _utc(decision_time)
    anchor = _positive_decimal(anchor_price, name="anchor_price")
    canonical_setup = _validate_setup_evidence(
        setup_evidence,
        decision_time=as_of,
        anchor_price=anchor,
    )
    raw_rows = list(research_rows)
    path_bundle = build_move_bundle(
        anchor_time=as_of,
        anchor_price=anchor,
        research_rows=raw_rows,
        horizons_minutes=HORIZONS_MINUTES,
    )
    if not verify_move_bundle_digest(path_bundle):
        raise ValueError("Day 12 path bundle digest failed verification.")

    trade_bundle: dict[str, Any] | None = None
    if canonical_setup["setup_state"] == "present" and canonical_setup["risk_state"] == "valid":
        trade_spec = canonical_setup["trade_spec"]
        if not isinstance(trade_spec, Mapping):
            raise TypeError("Valid setup risk evidence requires trade_spec.")
        trade_bundle = build_trade_outcome_bundle(
            anchor_time=as_of,
            direction=str(canonical_setup["direction"]),
            entry=trade_spec["entry"],
            stop_loss=trade_spec["stop_loss"],
            targets=list(trade_spec["targets"]),
            research_rows=raw_rows,
            horizons_minutes=HORIZONS_MINUTES,
        )
        if not verify_trade_outcome_bundle_digest(trade_bundle):
            raise ValueError("Day 13 trade outcome bundle digest failed verification.")

    path_by_horizon = {
        int(label["horizon_minutes"]): label for label in path_bundle["labels"]
    }
    outcome_by_horizon = (
        {}
        if trade_bundle is None
        else {
            int(outcome["horizon_minutes"]): outcome
            for outcome in trade_bundle["outcomes"]
        }
    )

    assessments: list[dict[str, Any]] = []
    for horizon in HORIZONS_MINUTES:
        path_label = path_by_horizon[horizon]
        if trade_bundle is None:
            classification, reason_code = _assessment_without_trade(canonical_setup)
            outcome_digest = None
            outcome_state = None
        else:
            outcome = outcome_by_horizon[horizon]
            classification, reason_code = _assessment_from_trade_outcome(outcome)
            outcome_digest = outcome["outcome_digest"]
            outcome_state = outcome["outcome_state"]
        assessments.append(
            {
                "horizon_minutes": horizon,
                "classification": classification,
                "reason_code": reason_code,
                "path_coverage_state": path_label["coverage_state"],
                "path_class": path_label["path_class"],
                "move_label_digest": path_label["label_digest"],
                "trade_outcome_digest": outcome_digest,
                "trade_outcome_state": outcome_state,
                "directional_movement_alone_sufficient": False,
            }
        )

    primary = next(
        assessment
        for assessment in assessments
        if assessment["horizon_minutes"] == PRIMARY_HORIZON_MINUTES
    )
    record: dict[str, Any] = {
        "counterfactual_version": COUNTERFACTUAL_VERSION,
        "counterfactual_digest_algorithm": COUNTERFACTUAL_DIGEST_ALGORITHM,
        "contract_class": COUNTERFACTUAL_CONTRACT_CLASS,
        "evaluation_only": True,
        "future_derived": True,
        "pit_eligible": False,
        "decision_input_allowed": False,
        "realized_pnl_included": False,
        "outcome_causality_included": False,
        "directional_movement_alone_sufficient": False,
        "symbol": SUPPORTED_SYMBOL,
        "decision_id": identifier,
        "decision_type": "no_trade",
        "decision_time_utc": as_of.isoformat(),
        "anchor_price": _decimal_text(anchor),
        "available_after_utc": path_bundle["available_after_utc"],
        "primary_horizon_minutes": PRIMARY_HORIZON_MINUTES,
        "primary_classification": primary["classification"],
        "primary_reason_code": primary["reason_code"],
        "setup_evidence": canonical_setup,
        "path_bundle": path_bundle,
        "trade_outcome_bundle": trade_bundle,
        "horizon_assessments": assessments,
    }
    record["counterfactual_digest"] = compute_no_trade_counterfactual_digest(record)
    return record


def no_trade_counterfactual_storage_row(record: Mapping[str, Any]) -> dict[str, object]:
    if not verify_no_trade_counterfactual_digest(record):
        raise ValueError("Storage accepts only valid Day 14 no_trade counterfactuals.")
    if (
        record.get("evaluation_only") is not True
        or record.get("future_derived") is not True
        or record.get("pit_eligible") is not False
        or record.get("decision_input_allowed") is not False
    ):
        raise ValueError("Counterfactual storage requires the future-only research boundary.")
    return {field.name: record[field.name] for field in RESEARCH_NO_TRADE_COUNTERFACTUALS.fields}


def no_trade_counterfactual_distribution(
    records: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    items = list(records)
    for item in items:
        if not verify_no_trade_counterfactual_digest(item):
            raise ValueError("Distribution received an invalid Day 14 counterfactual digest.")
        if item.get("evaluation_only") is not True or item.get("pit_eligible") is not False:
            raise ValueError("Distribution accepts evaluation-only counterfactual records.")

    for item in items:
        if str(item["primary_classification"]) not in _CLASSIFICATIONS:
            raise ValueError("Counterfactual contains an unsupported primary classification.")

    primary_counts = Counter(str(item["primary_classification"]) for item in items)
    reason_counts = Counter(str(item["primary_reason_code"]) for item in items)
    horizon_counts: dict[str, Counter[str]] = {
        str(horizon): Counter() for horizon in HORIZONS_MINUTES
    }
    for item in items:
        for assessment in item["horizon_assessments"]:
            horizon_counts[str(assessment["horizon_minutes"])][
                str(assessment["classification"])
            ] += 1

    result = {
        "distribution_version": COUNTERFACTUAL_DISTRIBUTION_VERSION,
        "counterfactual_version": COUNTERFACTUAL_VERSION,
        "evaluation_only": True,
        "future_derived": True,
        "pit_eligible": False,
        "record_count": len(items),
        "primary_classification_counts": dict(sorted(primary_counts.items())),
        "primary_reason_counts": dict(sorted(reason_counts.items())),
        "classification_counts_by_horizon": {
            horizon: dict(sorted(counts.items()))
            for horizon, counts in sorted(horizon_counts.items(), key=lambda item: int(item[0]))
        },
        "missed_opportunity_requires_valid_setup_and_risk": True,
        "directional_movement_alone_sufficient": False,
        "outcome_causality_included": False,
    }
    result["distribution_digest"] = _digest(result)
    return result
