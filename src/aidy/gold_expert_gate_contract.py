"""Build 2: standard contract for AIDY Gold expert gates.

The contract is intentionally generic. It does not implement any expert's market logic.
It makes every future mini-brain auditable, PIT-safe and machine-scoreable before the
specialist gate builds begin.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from hashlib import sha256
from typing import Any

from aidy.gold_cycle_environment import verify_cycle_environment
from aidy.gold_environment_contract import assert_no_hindsight_fields

#: The version the builder emits. v2 scores neutral subcalculator votes; v1 did not.
#: The rule is part of the packet's meaning, so changing it without a new version left
#: 1,785 stored v1 packets unverifiable and wedged the shadow loop for five hours.
EXPERT_GATE_CONTRACT_VERSION = "aidy_gold_expert_gate_contract_v2"

#: Packets written before neutral votes became scoreable. Still verifiable, still
#: scored, never rewritten - their calculator_digest seals `scoreable`, so amending a
#: stored packet to match a newer rule would mean breaking the seal that makes it
#: evidence. The packet declares its rule; verification honours it.
LEGACY_EXPERT_GATE_CONTRACT_VERSION = "aidy_gold_expert_gate_contract_v1"

SUPPORTED_EXPERT_GATE_CONTRACT_VERSIONS = frozenset(
    {EXPERT_GATE_CONTRACT_VERSION, LEGACY_EXPERT_GATE_CONTRACT_VERSION}
)

GATE_MODES = frozenset({"directional", "context_only"})
GATE_CONCLUSIONS = frozenset(
    {"bullish", "bearish", "neutral", "context_only", "abstain", "unknown"}
)
EVIDENCE_STATES = frozenset({"known", "unknown", "unavailable"})
SUBCALCULATOR_STATES = frozenset({"known", "unknown", "unavailable", "insufficient"})
SUBCALCULATOR_ROLES = frozenset({"directional", "context_only"})
DIRECTIONAL_VOTES = frozenset({"bullish", "bearish", "neutral", "abstain", "unknown"})
DEPENDENCY_FAMILIES = frozenset(
    {
        "structure",
        "momentum",
        "location",
        "liquidity",
        "volatility",
        "session_participation",
        "event",
        "rates_usd",
        "cross_market",
        "futures_microstructure",
        "news_mechanism",
        "analogue",
        "data_quality",
    }
)

_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9_.-]{1,95}$")


def _utc(value: datetime | str) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError("expert-gate timestamps must be timezone-aware")
    return parsed.astimezone(UTC)


def _normalise(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _normalise(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalise(item) for item in value]
    if isinstance(value, datetime):
        return _utc(value).isoformat()
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("expert-gate values must be finite")
        return format(value, "f")
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("expert-gate values must be finite")
        return value
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise TypeError(f"unsupported expert-gate value type: {type(value).__name__}")


def _canonical_json(value: object) -> str:
    return json.dumps(
        _normalise(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _digest(value: object) -> str:
    return sha256(_canonical_json(value).encode()).hexdigest()


def _identifier(value: Any, *, field: str) -> str:
    result = str(value or "").strip().lower()
    if not _IDENTIFIER.fullmatch(result):
        raise ValueError(f"{field} must be a stable lowercase identifier")
    return result


def _probability(value: Any, *, field: str, required: bool) -> str | None:
    if value is None:
        if required:
            raise ValueError(f"{field} is required")
        return None
    if isinstance(value, bool):
        raise TypeError(f"{field} must be between 0 and 1")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field} must be between 0 and 1") from exc
    if not parsed.is_finite() or parsed < 0 or parsed > 1:
        raise ValueError(f"{field} must be between 0 and 1")
    return format(parsed.quantize(Decimal("0.000001"), rounding=ROUND_HALF_EVEN), "f")


def _value_kind(value: Any, *, state: str) -> str:
    if state != "known":
        return "unknown"
    if isinstance(value, bool):
        return "categorical"
    if isinstance(value, (int, float, Decimal)):
        return "numeric"
    if isinstance(value, str):
        return "categorical"
    return "structured"


def _normalise_evidence(
    *,
    items: Sequence[Mapping[str, Any]],
    as_of: datetime,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(items):
        assert_no_hindsight_fields(raw, path=f"evidence_inputs[{index}]")
        evidence_id = _identifier(raw.get("evidence_id"), field="evidence_id")
        if evidence_id in seen:
            raise ValueError(f"duplicate evidence_id: {evidence_id}")
        seen.add(evidence_id)

        source = str(raw.get("source") or "").strip()
        path = str(raw.get("path") or "").strip()
        if not source or not path:
            raise ValueError(f"evidence {evidence_id} requires source and path")

        state = str(raw.get("state") or "").strip().lower()
        if state not in EVIDENCE_STATES:
            raise ValueError(f"evidence {evidence_id} has invalid state: {state}")

        observed = _utc(raw.get("observed_at_utc"))
        if observed > as_of:
            raise ValueError(
                f"evidence {evidence_id} was observed after the gate as-of timestamp"
            )

        value = _normalise(raw.get("value"))
        if state == "known" and (value is None or value == ""):
            raise ValueError(f"known evidence {evidence_id} requires a value")

        item = {
            "evidence_id": evidence_id,
            "source": source,
            "path": path,
            "observed_at_utc": observed.isoformat(),
            "state": state,
            "value_kind": _value_kind(value, state=state),
            "value": value,
        }
        provenance = raw.get("provenance")
        if provenance is not None:
            item["provenance"] = _normalise(provenance)
        item["value_digest"] = _digest(
            {
                "source": source,
                "path": path,
                "observed_at_utc": observed.isoformat(),
                "state": state,
                "value": value,
                "provenance": item.get("provenance"),
            }
        )
        result.append(item)
    return result


def _normalise_subcalculators(
    *,
    items: Sequence[Mapping[str, Any]],
    evidence_by_id: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()

    for index, raw in enumerate(items):
        assert_no_hindsight_fields(raw, path=f"subcalculators[{index}]")
        calculator_id = _identifier(
            raw.get("calculator_id"), field="calculator_id"
        )
        if calculator_id in seen:
            raise ValueError(f"duplicate calculator_id: {calculator_id}")
        seen.add(calculator_id)

        version = str(raw.get("version") or "").strip()
        if not version:
            raise ValueError(f"subcalculator {calculator_id} requires version")

        role = str(raw.get("role") or "").strip().lower()
        if role not in SUBCALCULATOR_ROLES:
            raise ValueError(f"subcalculator {calculator_id} has invalid role: {role}")

        dependency_family = str(
            raw.get("dependency_family") or ""
        ).strip().lower()
        if dependency_family not in DEPENDENCY_FAMILIES:
            raise ValueError(
                f"subcalculator {calculator_id} has invalid dependency_family"
            )

        state = str(raw.get("state") or "").strip().lower()
        if state not in SUBCALCULATOR_STATES:
            raise ValueError(f"subcalculator {calculator_id} has invalid state: {state}")

        vote = str(raw.get("vote") or "").strip().lower()
        if role == "context_only":
            expected = "context_only" if state == "known" else "unknown"
            if vote != expected:
                raise ValueError(
                    f"context-only subcalculator {calculator_id} must vote {expected}"
                )
        elif state == "known":
            if vote not in DIRECTIONAL_VOTES - {"unknown"}:
                raise ValueError(
                    f"known directional subcalculator {calculator_id} has invalid vote"
                )
        elif vote != "unknown":
            raise ValueError(
                f"missing directional subcalculator {calculator_id} must vote unknown"
            )

        refs = [
            _identifier(ref, field="evidence_ref")
            for ref in (raw.get("evidence_refs") or [])
        ]
        if not refs:
            raise ValueError(f"subcalculator {calculator_id} requires evidence_refs")
        if len(refs) != len(set(refs)):
            raise ValueError(
                f"subcalculator {calculator_id} has duplicate evidence_refs"
            )
        missing = [ref for ref in refs if ref not in evidence_by_id]
        if missing:
            raise ValueError(
                f"subcalculator {calculator_id} references unknown evidence: {missing}"
            )

        if state == "known" and not any(
            evidence_by_id[ref].get("state") == "known" for ref in refs
        ):
            raise ValueError(
                f"known subcalculator {calculator_id} has no known evidence input"
            )

        observation = _normalise(raw.get("observation") or {})
        if not isinstance(observation, Mapping) or not observation:
            raise ValueError(
                f"subcalculator {calculator_id} requires an observation payload"
            )
        assert_no_hindsight_fields(
            observation,
            path=f"subcalculators[{index}].observation",
        )

        explanation = str(raw.get("explanation") or "").strip()
        if not explanation:
            raise ValueError(
                f"subcalculator {calculator_id} requires a readable explanation"
            )

        scoreable = subcalculator_is_scoreable(role=role, state=state, vote=vote)
        strength = _probability(
            raw.get("strength"),
            field=f"subcalculator {calculator_id} strength",
            required=subcalculator_strength_required(role=role, state=state, vote=vote),
        )
        if raw.get("strength") is None:
            strength = None

        item = {
            "calculator_id": calculator_id,
            "version": version,
            "role": role,
            "dependency_family": dependency_family,
            "state": state,
            "vote": vote,
            "strength": strength,
            "scoreable": scoreable,
            "evidence_refs": refs,
            "observation": observation,
            "explanation": explanation,
        }
        item["calculator_digest"] = _digest(item)
        result.append(item)

    return result


def _normalise_explanation_parts(
    *,
    parts: Sequence[Mapping[str, Any]],
    evidence_ids: set[str],
    calculator_ids: set[str],
    field: str,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index, raw in enumerate(parts):
        text = str(raw.get("text") or "").strip()
        if not text:
            raise ValueError(f"{field}[{index}] requires text")
        refs = [str(ref or "").strip() for ref in (raw.get("source_refs") or [])]
        if not refs:
            raise ValueError(f"{field}[{index}] requires source_refs")

        for ref in refs:
            if ref.startswith("evidence:"):
                identifier = ref.split(":", 1)[1]
                if identifier not in evidence_ids:
                    raise ValueError(f"{field}[{index}] has unknown source ref: {ref}")
            elif ref.startswith("calc:"):
                identifier = ref.split(":", 1)[1]
                if identifier not in calculator_ids:
                    raise ValueError(f"{field}[{index}] has unknown source ref: {ref}")
            else:
                raise ValueError(
                    f"{field}[{index}] source refs must use evidence: or calc:"
                )
        result.append({"text": text, "source_refs": refs})
    return result


#: Votes that commit to a side. Distinct from DIRECTIONAL_VOTES at the top of this
#: module, which is the set of votes a directional subcalculator may legally cast.
COMMITTED_DIRECTION_VOTES = frozenset({"bullish", "bearish"})
#: Votes that can be checked against a realised outcome, neutral included.
SCOREABLE_VOTES = frozenset({"bullish", "bearish", "neutral"})


def subcalculator_is_scoreable(
    *,
    role: str,
    state: str,
    vote: str,
    contract_version: str = EXPERT_GATE_CONTRACT_VERSION,
) -> bool:
    """Can this subcalculator vote be checked against a realised outcome?

    `contract_version` is the rule the packet was built under, and it defaults to the
    current one so building always uses the newest rule. Verification passes the
    packet's own declared version, because a stored packet must be judged by the rule
    in force when it was written - not the rule that happens to be deployed now.

    A neutral vote is a falsifiable claim - "no meaningful move" - and the rest of
    the system already treats it as one: `score_directional_outcome` accepts
    neutral, and the meta layer has always scored its own neutral decisions
    (`gold_expert_shadow`, scoreable=frozen_direction in {bullish, bearish,
    neutral}). Only this contract disagreed, so every neutral subcalculator vote
    was thrown away instead of becoming evidence.

    Measured on 2026-09-23: directional experts voted neutral 30.0 per cent of the
    time into a market that is neutral 10.2 per cent of the time, and none of it
    was scored. With abstain that left 64 per cent of expert output invisible to
    the trust engine, in a system whose entire scored evidence base at gate_global
    was 240 calls.

    Scoring neutral does not improve accuracy - the directional deficit is a flat
    -14 points against the majority baseline at every move size - but it turns the
    scarcest resource here, labelled evidence, from discarded into usable, and it
    lets trust finally see an over-neutral expert.
    """
    if role != "directional" or state != "known":
        return False
    if contract_version == LEGACY_EXPERT_GATE_CONTRACT_VERSION:
        return vote in COMMITTED_DIRECTION_VOTES
    return vote in SCOREABLE_VOTES


def subcalculator_strength_required(*, role: str, state: str, vote: str) -> bool:
    """Strength is required for a directional vote only.

    Experts deliberately emit ``strength=None`` beside a neutral vote, so tying
    this to scoreability would raise on every neutral subcalculator and take the
    whole shadow loop down with it.
    """
    return (
        role == "directional"
        and state == "known"
        and vote in COMMITTED_DIRECTION_VOTES
    )


def _validate_conclusion(
    *,
    gate_mode: str,
    conclusion: str,
    conviction: str | None,
    subcalculators: Sequence[Mapping[str, Any]],
) -> bool:
    known = [item for item in subcalculators if item.get("state") == "known"]
    scoreable = [item for item in subcalculators if item.get("scoreable") is True]

    if gate_mode == "context_only":
        if conclusion != "context_only":
            raise ValueError("context-only gate cannot emit a directional conclusion")
        if conviction is not None:
            raise ValueError("context-only gate cannot emit directional conviction")
        return False

    if conclusion == "context_only":
        raise ValueError("directional gate cannot conclude context_only")

    if not known:
        if conclusion != "unknown":
            raise ValueError("gate with no known subcalculators must conclude unknown")
        if conviction is not None:
            raise ValueError("unknown gate conclusion cannot carry conviction")
        return False

    if conclusion in {"bullish", "bearish"}:
        if not any(item.get("vote") == conclusion for item in scoreable):
            raise ValueError(
                "directional gate conclusion requires a matching scoreable subcalculator"
            )
        if conviction is None:
            raise ValueError("directional gate conclusion requires internal_conviction")
        return True

    if conclusion == "neutral":
        if not any(
            item.get("role") == "directional"
            and item.get("state") == "known"
            and item.get("vote") == "neutral"
            for item in subcalculators
        ):
            raise ValueError(
                "neutral gate conclusion requires a known neutral subcalculator"
            )
        return False

    if conclusion == "abstain":
        if not any(
            item.get("role") == "directional" and item.get("state") == "known"
            for item in subcalculators
        ):
            raise ValueError("abstain requires known directional evidence")
        if conviction is not None:
            raise ValueError("abstain conclusion cannot carry conviction")
        return False

    if conclusion == "unknown":
        if conviction is not None:
            raise ValueError("unknown gate conclusion cannot carry conviction")
        return False

    raise ValueError(f"invalid gate conclusion: {conclusion}")


def build_expert_gate_packet(
    *,
    gate_id: str,
    gate_version: str,
    gate_mode: str,
    dependency_family: str,
    target_horizon_minutes: int,
    as_of_utc: datetime | str,
    global_environment: Mapping[str, Any],
    mini_environment: Mapping[str, Any],
    evidence_inputs: Sequence[Mapping[str, Any]],
    subcalculators: Sequence[Mapping[str, Any]],
    conclusion: str,
    internal_conviction: Any = None,
    explanation_parts: Sequence[Mapping[str, Any]],
    contradictions: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Build one immutable expert-gate packet from PIT-safe evidence."""

    gate_id = _identifier(gate_id, field="gate_id")
    gate_version = str(gate_version or "").strip()
    if not gate_version:
        raise ValueError("gate_version is required")

    gate_mode = str(gate_mode or "").strip().lower()
    if gate_mode not in GATE_MODES:
        raise ValueError(f"invalid gate_mode: {gate_mode}")

    dependency_family = str(dependency_family or "").strip().lower()
    if dependency_family not in DEPENDENCY_FAMILIES:
        raise ValueError("invalid gate dependency_family")

    if (
        isinstance(target_horizon_minutes, bool)
        or not isinstance(target_horizon_minutes, int)
        or target_horizon_minutes <= 0
    ):
        raise ValueError("target_horizon_minutes must be a positive integer")

    as_of = _utc(as_of_utc)
    if not verify_cycle_environment(global_environment):
        raise ValueError("global_environment must be a verified cycle environment")
    assert_no_hindsight_fields(global_environment, path="global_environment")

    exact = global_environment.get("exact_facts")
    exact = exact if isinstance(exact, Mapping) else {}
    environment_as_of = _utc(exact.get("as_of_utc"))
    if environment_as_of != as_of:
        raise ValueError("gate as-of must match the frozen global environment as-of")

    mini = _normalise(mini_environment)
    if not isinstance(mini, Mapping) or not mini:
        raise ValueError("mini_environment must contain gate-specific dimensions")
    assert_no_hindsight_fields(mini, path="mini_environment")

    evidence = _normalise_evidence(items=evidence_inputs, as_of=as_of)
    evidence_by_id = {item["evidence_id"]: item for item in evidence}

    calculators = _normalise_subcalculators(
        items=subcalculators,
        evidence_by_id=evidence_by_id,
    )
    calculator_ids = {item["calculator_id"] for item in calculators}

    explanation = _normalise_explanation_parts(
        parts=explanation_parts,
        evidence_ids=set(evidence_by_id),
        calculator_ids=calculator_ids,
        field="explanation_parts",
    )
    if not explanation:
        raise ValueError("expert gate requires at least one explanation part")

    contradiction_rows = _normalise_explanation_parts(
        parts=contradictions,
        evidence_ids=set(evidence_by_id),
        calculator_ids=calculator_ids,
        field="contradictions",
    )

    conclusion = str(conclusion or "").strip().lower()
    if conclusion not in GATE_CONCLUSIONS:
        raise ValueError(f"invalid gate conclusion: {conclusion}")

    conviction = _probability(
        internal_conviction,
        field="internal_conviction",
        required=False,
    )
    gate_scoreable = _validate_conclusion(
        gate_mode=gate_mode,
        conclusion=conclusion,
        conviction=conviction,
        subcalculators=calculators,
    )

    dimensions = global_environment.get("learning_dimensions")
    dimensions = dimensions if isinstance(dimensions, Mapping) else {}
    environment_contract = global_environment.get("environment_contract")
    environment_contract = (
        environment_contract if isinstance(environment_contract, Mapping) else {}
    )

    mini_identity = {
        "gate_id": gate_id,
        "global_environment_digest": global_environment["environment_digest"],
        "dimensions": mini,
    }
    mini_digest = _digest(mini_identity)
    packet: dict[str, Any] = {
        "contract_version": EXPERT_GATE_CONTRACT_VERSION,
        "gate_id": gate_id,
        "gate_version": gate_version,
        "gate_mode": gate_mode,
        "dependency_family": dependency_family,
        "target_horizon_minutes": target_horizon_minutes,
        "as_of_utc": as_of.isoformat(),
        "global_environment_ref": {
            "environment_version": global_environment["environment_version"],
            "environment_key": global_environment["environment_key"],
            "environment_digest": global_environment["environment_digest"],
            "environment_schema_version": environment_contract.get("schema_version"),
            "dimension_registry_digest": environment_contract.get(
                "dimension_registry_digest"
            ),
            "dimension_count": environment_contract.get("dimension_count"),
        },
        "global_environment_dimensions": _normalise(dimensions),
        "mini_environment": {
            "dimensions": mini,
            "mini_environment_key": "minienv_" + mini_digest[:28],
            "mini_environment_digest": mini_digest,
            "inherits_global_environment": True,
        },
        "evidence_inputs": evidence,
        "subcalculators": calculators,
        "conclusion": conclusion,
        "internal_conviction": conviction,
        "gate_scoreable": gate_scoreable,
        "contradictions": contradiction_rows,
        "explanation_parts": explanation,
        "readable_explanation": " ".join(part["text"] for part in explanation),
        "historical_reliability": {
            "state": "not_attached_until_build_3",
            "separate_from_internal_conviction": True,
        },
        "no_hindsight_attestation": {
            "future_values_used": False,
            "global_environment_verified": True,
            "all_evidence_observed_by_as_of": True,
            "outcome_fields_rejected": True,
        },
        "research_only": True,
        "live_money_execution_allowed": False,
    }
    packet["packet_digest"] = _digest(packet)
    return packet


def verify_expert_gate_packet(value: Mapping[str, Any]) -> bool:
    """Verify packet integrity and the Build-2 safety/traceability invariants."""

    try:
        body = _normalise(dict(value))
        supplied = str(body.pop("packet_digest", ""))
        if not supplied or supplied != _digest(body):
            return False
        packet_contract_version = str(body.get("contract_version") or "")
        if packet_contract_version not in SUPPORTED_EXPERT_GATE_CONTRACT_VERSIONS:
            return False
        if body.get("research_only") is not True:
            return False
        if body.get("live_money_execution_allowed") is not False:
            return False

        assert_no_hindsight_fields(body, path="expert_gate_packet")

        _identifier(body.get("gate_id"), field="gate_id")
        if not str(body.get("gate_version") or "").strip():
            return False
        gate_mode = str(body.get("gate_mode") or "")
        if gate_mode not in GATE_MODES:
            return False
        horizon = body.get("target_horizon_minutes")
        if isinstance(horizon, bool) or not isinstance(horizon, int) or horizon <= 0:
            return False
        if str(body.get("conclusion") or "") not in GATE_CONCLUSIONS:
            return False
        dependency_family = str(body.get("dependency_family") or "")
        if dependency_family not in DEPENDENCY_FAMILIES:
            return False

        as_of = _utc(body.get("as_of_utc"))
        global_ref = body.get("global_environment_ref")
        if not isinstance(global_ref, Mapping):
            return False
        if not str(global_ref.get("environment_digest") or ""):
            return False
        if int(global_ref.get("dimension_count") or 0) <= 0:
            return False

        mini = body.get("mini_environment")
        if not isinstance(mini, Mapping):
            return False
        dimensions = mini.get("dimensions")
        if not isinstance(dimensions, Mapping) or not dimensions:
            return False
        mini_identity = {
            "gate_id": body.get("gate_id"),
            "global_environment_digest": global_ref.get("environment_digest"),
            "dimensions": dimensions,
        }
        expected_mini_digest = _digest(mini_identity)
        if mini.get("mini_environment_digest") != expected_mini_digest:
            return False
        if mini.get("mini_environment_key") != (
            "minienv_" + expected_mini_digest[:28]
        ):
            return False
        if mini.get("inherits_global_environment") is not True:
            return False

        evidence = body.get("evidence_inputs")
        calculators = body.get("subcalculators")
        if not isinstance(evidence, list) or not isinstance(calculators, list):
            return False

        evidence_by_id: dict[str, Mapping[str, Any]] = {}
        for item in evidence:
            if not isinstance(item, Mapping):
                return False
            evidence_id = _identifier(item.get("evidence_id"), field="evidence_id")
            if evidence_id in evidence_by_id:
                return False
            if not str(item.get("source") or "").strip():
                return False
            if not str(item.get("path") or "").strip():
                return False
            state = str(item.get("state") or "").strip().lower()
            if state not in EVIDENCE_STATES:
                return False
            observed = _utc(item.get("observed_at_utc"))
            if observed > as_of:
                return False
            value = item.get("value")
            if state == "known" and (value is None or value == ""):
                return False
            if item.get("value_kind") != _value_kind(value, state=state):
                return False
            expected_value_digest = _digest(
                {
                    "source": item.get("source"),
                    "path": item.get("path"),
                    "observed_at_utc": observed.isoformat(),
                    "state": item.get("state"),
                    "value": item.get("value"),
                    "provenance": item.get("provenance"),
                }
            )
            if item.get("value_digest") != expected_value_digest:
                return False
            evidence_by_id[evidence_id] = item

        calculator_by_id: dict[str, Mapping[str, Any]] = {}
        for item in calculators:
            if not isinstance(item, Mapping):
                return False
            calculator_id = _identifier(
                item.get("calculator_id"), field="calculator_id"
            )
            if calculator_id in calculator_by_id:
                return False
            if not str(item.get("version") or "").strip():
                return False
            role = str(item.get("role") or "").strip().lower()
            if role not in SUBCALCULATOR_ROLES:
                return False
            calc_family = str(item.get("dependency_family") or "").strip().lower()
            if calc_family not in DEPENDENCY_FAMILIES:
                return False
            state = str(item.get("state") or "").strip().lower()
            if state not in SUBCALCULATOR_STATES:
                return False
            vote = str(item.get("vote") or "").strip().lower()
            if role == "context_only":
                expected_vote = "context_only" if state == "known" else "unknown"
                if vote != expected_vote:
                    return False
            elif state == "known":
                if vote not in DIRECTIONAL_VOTES - {"unknown"}:
                    return False
            elif vote != "unknown":
                return False

            refs = item.get("evidence_refs")
            if not isinstance(refs, list) or not refs:
                return False
            if len(refs) != len(set(refs)):
                return False
            if any(ref not in evidence_by_id for ref in refs):
                return False
            if state == "known" and not any(
                evidence_by_id[ref].get("state") == "known" for ref in refs
            ):
                return False
            observation = item.get("observation")
            if not isinstance(observation, Mapping) or not observation:
                return False
            if not str(item.get("explanation") or "").strip():
                return False
            expected_scoreable = subcalculator_is_scoreable(
                role=role,
                state=state,
                vote=vote,
                contract_version=packet_contract_version,
            )
            if item.get("scoreable") is not expected_scoreable:
                return False
            strength = item.get("strength")
            if subcalculator_strength_required(role=role, state=state, vote=vote):
                _probability(
                    strength,
                    field=f"subcalculator {calculator_id} strength",
                    required=True,
                )
            elif strength is not None:
                _probability(
                    strength,
                    field=f"subcalculator {calculator_id} strength",
                    required=False,
                )
            raw = dict(item)
            supplied_calculator_digest = str(raw.pop("calculator_digest", ""))
            if not supplied_calculator_digest or supplied_calculator_digest != _digest(raw):
                return False
            calculator_by_id[calculator_id] = item

        for field in ("explanation_parts", "contradictions"):
            parts = body.get(field)
            if not isinstance(parts, list):
                return False
            for part in parts:
                if not isinstance(part, Mapping) or not str(part.get("text") or "").strip():
                    return False
                refs = part.get("source_refs")
                if not isinstance(refs, list) or not refs:
                    return False
                for ref in refs:
                    if str(ref).startswith("evidence:"):
                        if str(ref).split(":", 1)[1] not in evidence_by_id:
                            return False
                    elif str(ref).startswith("calc:"):
                        if str(ref).split(":", 1)[1] not in calculator_by_id:
                            return False
                    else:
                        return False

        if not body.get("explanation_parts"):
            return False
        expected_readable = " ".join(
            str(part["text"]) for part in body["explanation_parts"]
        )
        if body.get("readable_explanation") != expected_readable:
            return False

        conviction = body.get("internal_conviction")
        gate_scoreable = _validate_conclusion(
            gate_mode=gate_mode,
            conclusion=str(body.get("conclusion") or ""),
            conviction=str(conviction) if conviction is not None else None,
            subcalculators=calculators,
        )
        if body.get("gate_scoreable") is not gate_scoreable:
            return False

        attestation = body.get("no_hindsight_attestation")
        if not isinstance(attestation, Mapping):
            return False
        if attestation.get("future_values_used") is not False:
            return False
        if attestation.get("global_environment_verified") is not True:
            return False
        if attestation.get("all_evidence_observed_by_as_of") is not True:
            return False
        if attestation.get("outcome_fields_rejected") is not True:
            return False

        historical = body.get("historical_reliability")
        if not isinstance(historical, Mapping):
            return False
        if historical.get("state") != "not_attached_until_build_3":
            return False
        if historical.get("separate_from_internal_conviction") is not True:
            return False
    except (KeyError, TypeError, ValueError):
        return False

    return True


__all__ = [
    "DEPENDENCY_FAMILIES",
    "EXPERT_GATE_CONTRACT_VERSION",
    "GATE_CONCLUSIONS",
    "GATE_MODES",
    "LEGACY_EXPERT_GATE_CONTRACT_VERSION",
    "SUPPORTED_EXPERT_GATE_CONTRACT_VERSIONS",
    "build_expert_gate_packet",
    "verify_expert_gate_packet",
]
