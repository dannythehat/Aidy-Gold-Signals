"""Build 19: Analogue / Episode Expert for AIDY Gold.

Consumes the already accepted historical analogue v1/v2/v3 stack plus movement
learning cards. Selection is strictly pre-outcome. Outcomes are read only after
selection to describe continuation/retrace distributions and counterexamples.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from hashlib import sha256
from typing import Any

from aidy.analogue_retrieval_v3 import (
    ANALOGUE_RETRIEVAL_VERSION_V3,
    verify_retrieval_digest_v3,
)
from aidy.gold_environment_contract import assert_no_hindsight_fields
from aidy.gold_expert_gate_contract import (
    build_expert_gate_packet,
    verify_expert_gate_packet,
)
from aidy.gold_expert_trust import (
    build_trust_envelope,
    build_trust_scopes,
    select_conditional_trust,
)
from aidy.gold_movement_investigator import (
    verify_gold_movement_investigation,
    verify_gold_movement_learning_card,
)
from aidy.semantic_context_composer import verify_semantic_retrieval_wrapper

ANALOGUE_EPISODE_EXPERT_VERSION = "aidy_gold_analogue_episode_expert_v1"
ANALOGUE_EPISODE_GATE_ID = "analogue_episode_expert"
ANALOGUE_EPISODE_TARGET_HORIZON_MINUTES = 15
ANALOGUE_EPISODE_SIMILARITY_VERSION = "aidy_analogue_episode_similarity_v1"

ANALOGUE_EPISODE_TRUST_REDUCED_CONTEXTS = (
    {
        "name": "analogue_state",
        "mini_dimensions": [
            "historical_retrieval_state",
            "gate_similarity_state",
            "environment_similarity_state",
        ],
        "global_dimensions": ["volatility_state"],
        "minimum_sample_n": 10,
    },
    {
        "name": "episode_distribution",
        "mini_dimensions": [
            "reference_direction",
            "continuation_state",
            "counterexample_state",
        ],
        "global_dimensions": ["session", "event_timing_state"],
        "minimum_sample_n": 8,
    },
)

_GATE_WEIGHT = Decimal("0.30")
_ENVIRONMENT_WEIGHT = Decimal("0.20")
_BASE_WEIGHT = Decimal("0.50")

_ENVIRONMENT_FIELDS = (
    "session",
    "session_phase",
    "volatility_state",
    "event_timing_state",
    "compound_regime",
)


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value: object) -> str:
    return sha256(_canonical_json(value).encode()).hexdigest()


def _utc(value: datetime | str, *, name: str) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return parsed.astimezone(UTC)


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _fmt(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return str(value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP))


def _known_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    return None if text in {"", "unknown", "unavailable", "insufficient"} else text


def build_episode_state_snapshot(
    *,
    identity: str,
    input_digest: str,
    as_of_utc: datetime | str,
    gate_states: Mapping[str, Mapping[str, Any]],
    environment: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind gate/environment state to one exact PIT input identity."""

    as_of = _utc(as_of_utc, name="as_of_utc")
    if not str(identity).strip() or not str(input_digest).strip():
        raise ValueError("episode snapshot requires identity and input_digest")
    assert_no_hindsight_fields(gate_states, path="gate_states")
    assert_no_hindsight_fields(environment, path="environment")

    normalized_gates: dict[str, dict[str, Any]] = {}
    for gate_id, raw in sorted(gate_states.items()):
        gate = dict(raw)
        observed = gate.get("observed_at_utc")
        if observed is not None and _utc(str(observed), name=f"{gate_id}.observed_at_utc") > as_of:
            raise ValueError("gate state was observed after the snapshot as-of")
        normalized_gates[str(gate_id)] = {
            "state": str(gate.get("state") or "unknown"),
            "conclusion": str(gate.get("conclusion") or "unknown"),
            "available": bool(gate.get("available", True)),
        }

    normalized_environment = {
        field: str(environment.get(field) or "unknown")
        for field in _ENVIRONMENT_FIELDS
    }
    body = {
        "snapshot_version": ANALOGUE_EPISODE_SIMILARITY_VERSION,
        "identity": str(identity),
        "input_digest": str(input_digest),
        "as_of_utc": as_of.isoformat(),
        "gate_states": normalized_gates,
        "environment": normalized_environment,
        "future_values_used": False,
        "outcome_fields_used": False,
    }
    body["snapshot_digest"] = _digest(body)
    return body


def verify_episode_state_snapshot(value: Mapping[str, Any]) -> bool:
    body = dict(value)
    supplied = str(body.pop("snapshot_digest", ""))
    return (
        bool(supplied)
        and supplied == _digest(body)
        and body.get("snapshot_version") == ANALOGUE_EPISODE_SIMILARITY_VERSION
        and body.get("future_values_used") is False
        and body.get("outcome_fields_used") is False
    )


def _gate_similarity(
    query: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> tuple[Decimal | None, int]:
    q = query.get("gate_states")
    c = candidate.get("gate_states")
    if not isinstance(q, Mapping) or not isinstance(c, Mapping):
        return None, 0
    common = sorted(set(q) & set(c))
    compared = 0
    earned = Decimal(0)
    for gate_id in common:
        qrow = q[gate_id]
        crow = c[gate_id]
        if not isinstance(qrow, Mapping) or not isinstance(crow, Mapping):
            continue
        if not qrow.get("available") or not crow.get("available"):
            continue
        q_conclusion = _known_text(qrow.get("conclusion"))
        c_conclusion = _known_text(crow.get("conclusion"))
        q_state = _known_text(qrow.get("state"))
        c_state = _known_text(crow.get("state"))
        if q_conclusion is None or c_conclusion is None:
            continue
        compared += 1
        if q_conclusion == c_conclusion:
            earned += Decimal("0.75")
        if q_state is not None and c_state is not None and q_state == c_state:
            earned += Decimal("0.25")
    return (earned / Decimal(compared), compared) if compared else (None, 0)


def _environment_similarity(
    query: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> tuple[Decimal | None, int]:
    q = query.get("environment")
    c = candidate.get("environment")
    if not isinstance(q, Mapping) or not isinstance(c, Mapping):
        return None, 0
    compared = 0
    matched = 0
    for field in _ENVIRONMENT_FIELDS:
        left = _known_text(q.get(field))
        right = _known_text(c.get(field))
        if left is None or right is None:
            continue
        compared += 1
        matched += int(left == right)
    return (
        Decimal(matched) / Decimal(compared),
        compared,
    ) if compared else (None, 0)


def score_episode_state_similarity(
    *,
    base_similarity: Any,
    query_snapshot: Mapping[str, Any],
    candidate_snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    if not verify_episode_state_snapshot(query_snapshot):
        raise ValueError("invalid query episode-state snapshot")
    if not verify_episode_state_snapshot(candidate_snapshot):
        raise ValueError("invalid candidate episode-state snapshot")

    base = _decimal(base_similarity)
    if base is None or base < 0 or base > 1:
        raise ValueError("base similarity must be between 0 and 1")
    gate, gate_n = _gate_similarity(query_snapshot, candidate_snapshot)
    env, env_n = _environment_similarity(query_snapshot, candidate_snapshot)

    weighted = base * _BASE_WEIGHT
    weight = _BASE_WEIGHT
    if gate is not None:
        weighted += gate * _GATE_WEIGHT
        weight += _GATE_WEIGHT
    if env is not None:
        weighted += env * _ENVIRONMENT_WEIGHT
        weight += _ENVIRONMENT_WEIGHT
    combined = weighted / weight

    result = {
        "similarity_version": ANALOGUE_EPISODE_SIMILARITY_VERSION,
        "base_similarity": _fmt(base),
        "gate_state_similarity": _fmt(gate),
        "gate_components_compared": gate_n,
        "environment_similarity": _fmt(env),
        "environment_components_compared": env_n,
        "combined_similarity": _fmt(combined),
        "weights": {
            "base": _fmt(_BASE_WEIGHT),
            "gate_state": _fmt(_GATE_WEIGHT),
            "environment": _fmt(_ENVIRONMENT_WEIGHT),
        },
        "outcomes_used_for_similarity": False,
        "future_values_used": False,
    }
    result["score_digest"] = _digest(result)
    return result


def _source_case_id(
    *,
    retrieval_v3: Mapping[str, Any],
    derived_case_id: str,
) -> str:
    mapping = retrieval_v3.get("derived_to_source_case_ids")
    if not isinstance(mapping, Mapping):
        raise TypeError("Build 19 requires v3 derived/source case mapping")
    source = str(mapping.get(derived_case_id) or "")
    if not source:
        raise ValueError("Build 19 could not bind derived analogue to source case")
    return source


def _terminal_return_bps(match: Mapping[str, Any]) -> Decimal | None:
    future = match.get("future_evaluation")
    if not isinstance(future, Mapping):
        return None
    bundle = future.get("move_bundle")
    if not isinstance(bundle, Mapping):
        return None
    labels = bundle.get("labels")
    if not isinstance(labels, list):
        return None
    for row in labels:
        if not isinstance(row, Mapping):
            continue
        if int(row.get("horizon_minutes") or -1) != 240:
            continue
        if row.get("coverage_state") != "complete":
            continue
        stats = row.get("path_stats")
        if not isinstance(stats, Mapping):
            continue
        return _decimal(stats.get("terminal_return_bps"))
    return None


def _outcome_class(reference_direction: str, value: Decimal | None) -> str:
    if value is None or reference_direction not in {"bullish", "bearish"}:
        return "unknown"
    if value == 0:
        return "flat"
    same = value > 0 if reference_direction == "bullish" else value < 0
    return "continuation" if same else "retrace"


def rerank_independent_analogues(
    *,
    historical_retrieval_v3: Mapping[str, Any],
    query_snapshot: Mapping[str, Any],
    candidate_snapshots_by_source_case_id: Mapping[str, Mapping[str, Any]],
    reference_direction: str,
    max_results: int = 8,
) -> dict[str, Any]:
    """Re-rank already-independent v3 representatives using only frozen state."""

    if not verify_retrieval_digest_v3(historical_retrieval_v3):
        raise ValueError("Build 19 requires a verified v3 historical retrieval")
    if historical_retrieval_v3.get("outcome_values_used_for_selection") is not False:
        raise ValueError("v3 retrieval used outcome values for selection")
    retrieval = historical_retrieval_v3.get("retrieval")
    if not isinstance(retrieval, Mapping):
        raise TypeError("v3 retrieval payload missing delegated retrieval")
    if retrieval.get("outcome_values_used_for_selection") is not False:
        raise ValueError("delegated retrieval used outcomes for selection")

    reference_direction = str(reference_direction or "unknown").lower()
    if reference_direction not in {"bullish", "bearish", "unknown"}:
        raise ValueError("reference_direction must be bullish, bearish or unknown")

    ranked: list[dict[str, Any]] = []
    for match in retrieval.get("matches") or []:
        if not isinstance(match, Mapping):
            continue
        derived_case_id = str(match.get("case_id") or "")
        source_case_id = _source_case_id(
            retrieval_v3=historical_retrieval_v3,
            derived_case_id=derived_case_id,
        )
        snapshot = candidate_snapshots_by_source_case_id.get(source_case_id)
        if not isinstance(snapshot, Mapping):
            continue
        if str(snapshot.get("identity") or "") != source_case_id:
            raise ValueError("candidate state snapshot identity mismatch")
        if str(snapshot.get("input_digest") or "") != str(match.get("input_digest") or ""):
            raise ValueError("candidate state snapshot input digest mismatch")
        score = score_episode_state_similarity(
            base_similarity=match.get("similarity", {}).get("similarity_score"),
            query_snapshot=query_snapshot,
            candidate_snapshot=snapshot,
        )
        ranked.append(
            {
                "source_case_id": source_case_id,
                "derived_case_id": derived_case_id,
                "episode_id": match.get("episode_id"),
                "episode_member_count": match.get("episode_member_count"),
                "as_of_utc": match.get("as_of_utc"),
                "state_similarity": score,
                "future_evaluation": match.get("future_evaluation"),
                "outcome_used_for_similarity": False,
            }
        )

    ranked.sort(
        key=lambda item: (
            -Decimal(str(item["state_similarity"]["combined_similarity"])),
            str(item["source_case_id"]),
        )
    )
    selected = ranked[: max(1, min(int(max_results), 20))]
    counts: Counter[str] = Counter()
    support: list[dict[str, Any]] = []
    counterexamples: list[dict[str, Any]] = []
    for rank, item in enumerate(selected, start=1):
        item["rank"] = rank
        terminal = _terminal_return_bps(item)
        outcome_class = _outcome_class(reference_direction, terminal)
        item["post_selection_outcome"] = {
            "class": outcome_class,
            "terminal_return_240m_bps": _fmt(terminal),
            "used_for_selection": False,
        }
        counts[outcome_class] += 1
        if outcome_class == "continuation":
            support.append(item)
        elif outcome_class == "retrace":
            counterexamples.append(item)

    total = len(selected)
    distribution = {
        "sample_n": total,
        "continuation_n": counts["continuation"],
        "retrace_n": counts["retrace"],
        "flat_n": counts["flat"],
        "unknown_n": counts["unknown"],
        "continuation_rate": (
            _fmt(Decimal(counts["continuation"]) / Decimal(total)) if total else None
        ),
        "retrace_rate": (
            _fmt(Decimal(counts["retrace"]) / Decimal(total)) if total else None
        ),
        "outcomes_read_only_after_selection": True,
    }
    return {
        "state": "matches_found" if selected else "no_comparable_case",
        "source_retrieval_version": ANALOGUE_RETRIEVAL_VERSION_V3,
        "candidate_independent_episode_n": len(ranked),
        "selected_episode_n": total,
        "matches": selected,
        "supporting_analogues": support,
        "counterexample_analogues": counterexamples,
        "distribution": distribution,
        "duplicate_episodes_already_collapsed_by_v2": True,
        "outcomes_used_for_similarity": False,
        "counterexamples_preserved": True,
        "future_values_used_for_selection": False,
    }


def retrieve_movement_episode_analogues(
    *,
    investigation: Mapping[str, Any],
    learning_cards: Sequence[Mapping[str, Any]],
    as_of_utc: datetime | str,
    limit: int = 8,
) -> dict[str, Any]:
    """Stateless Build-19 wrapper over movement episode memory."""

    if not verify_gold_movement_investigation(investigation):
        raise ValueError("Build 19 requires a verified movement investigation")
    as_of = _utc(as_of_utc, name="as_of_utc")
    current_direction = str(investigation.get("move_direction") or "unknown")
    current_triggers = {str(item) for item in investigation.get("triggered_by") or []}
    leading = investigation.get("leading_mechanism")
    leading = leading if isinstance(leading, Mapping) else {}
    current_mechanism = str(leading.get("mechanism") or "unknown")
    current_attribution = str(investigation.get("attribution_state") or "unknown")

    deduped: dict[str, Mapping[str, Any]] = {}
    for card in learning_cards:
        if not verify_gold_movement_learning_card(card):
            raise ValueError("invalid movement learning card")
        available = _utc(str(card.get("available_at_utc")), name="card.available_at_utc")
        trigger = _utc(str(card.get("trigger_at_utc")), name="card.trigger_at_utc")
        if available > as_of or trigger >= as_of:
            continue
        key = str(card.get("investigation_digest") or card.get("learning_card_digest") or "")
        if key and key not in deduped:
            deduped[key] = card

    ranked: list[tuple[Decimal, Mapping[str, Any]]] = []
    for card in deduped.values():
        score = Decimal(0)
        if str(card.get("initial_move_direction") or "") == current_direction:
            score += Decimal(2)
        card_triggers = {str(item) for item in card.get("triggered_by") or []}
        union = current_triggers | card_triggers
        if union:
            score += Decimal(2) * Decimal(len(current_triggers & card_triggers)) / Decimal(
                len(union)
            )
        card_leading = card.get("leading_mechanism")
        card_leading = card_leading if isinstance(card_leading, Mapping) else {}
        if (
            current_mechanism != "unknown"
            and str(card_leading.get("mechanism") or "") == current_mechanism
        ):
            score += Decimal(3)
        if str(card.get("attribution_state") or "") == current_attribution:
            score += Decimal(1)
        ranked.append((score, card))

    ranked.sort(
        key=lambda item: (
            -item[0],
            str(item[1].get("learning_card_digest") or ""),
        )
    )
    selected = ranked[: max(1, min(int(limit), 20))]
    counts: Counter[str] = Counter()
    analogues: list[dict[str, Any]] = []
    for score, card in selected:
        path_class = str(card.get("path_class") or "insufficient_forward_path")
        counts[path_class] += 1
        analogues.append(
            {
                "learning_card_digest": card.get("learning_card_digest"),
                "investigation_digest": card.get("investigation_digest"),
                "available_at_utc": card.get("available_at_utc"),
                "path_class": path_class,
                "forward_path": card.get("forward_path"),
                "similarity_score": _fmt(score),
                "outcome_used_for_similarity": False,
            }
        )
    return {
        "state": "matches_found" if analogues else "no_comparable_episode",
        "candidate_episode_n": len(ranked),
        "selected_episode_n": len(analogues),
        "path_class_counts": dict(sorted(counts.items())),
        "analogues": analogues,
        "duplicates_collapsed": len(deduped) < len(learning_cards),
        "counterexamples_preserved": True,
        "outcomes_used_for_similarity": False,
        "future_values_used_for_selection": False,
    }


def summarise_chronological_holdout(
    rows: Sequence[Mapping[str, Any]],
    *,
    split_binding: Mapping[str, Any],
) -> dict[str, Any]:
    if split_binding.get("manifest_version") != "aidy_chronological_split_manifest_v1":
        raise ValueError("Build 19 requires chronological split manifest v1")
    if split_binding.get("purge_required") is not True:
        raise ValueError("Build 19 holdout requires purge")
    if split_binding.get("embargo_required") is not True:
        raise ValueError("Build 19 holdout requires embargo")
    if split_binding.get("holdout_tuning_allowed") is not False:
        raise ValueError("Build 19 forbids holdout tuning")

    holdout = [
        row
        for row in rows
        if str(row.get("split") or "") == "holdout"
        and str(row.get("independent_episode_id") or "")
    ]
    ids = {str(row["independent_episode_id"]) for row in holdout}
    return {
        "state": "known" if ids else "insufficient",
        "holdout_independent_episode_n": len(ids),
        "purge_required": True,
        "embargo_required": True,
        "holdout_tuning_allowed": False,
        "development_rows_used_for_holdout_score": False,
        "validation_rows_used_for_holdout_score": False,
        "chronological_holdout_only": True,
        "outcomes_used_for_similarity": False,
    }


def _context_calculator(
    *,
    calculator_id: str,
    evidence_ref: str,
    known: bool,
    observation: Mapping[str, Any],
    explanation: str,
) -> dict[str, Any]:
    return {
        "calculator_id": calculator_id,
        "version": f"{calculator_id}_v1",
        "role": "context_only",
        "dependency_family": "analogue",
        "state": "known" if known else "insufficient",
        "vote": "context_only" if known else "unknown",
        "evidence_refs": [evidence_ref],
        "observation": dict(observation),
        "explanation": explanation,
    }


def _subject_keys(packet: Mapping[str, Any]) -> list[str]:
    return [
        f"gate:{packet['gate_id']}",
        *(f"subcalculator:{item['calculator_id']}" for item in packet["subcalculators"]),
    ]


def build_analogue_episode_expert(
    *,
    global_environment: Mapping[str, Any],
    historical_retrieval_v3: Mapping[str, Any],
    query_snapshot: Mapping[str, Any],
    candidate_snapshots_by_source_case_id: Mapping[str, Mapping[str, Any]],
    reference_direction: str,
    movement_investigation: Mapping[str, Any] | None = None,
    movement_learning_cards: Sequence[Mapping[str, Any]] = (),
    semantic_retrieval: Mapping[str, Any] | None = None,
    trust_score_rows_by_subject: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
) -> dict[str, Any]:
    exact = global_environment.get("exact_facts")
    exact = exact if isinstance(exact, Mapping) else {}
    as_of = _utc(str(exact.get("as_of_utc")), name="environment.as_of_utc")
    if not verify_episode_state_snapshot(query_snapshot):
        raise ValueError("Build 19 requires a verified query state snapshot")
    if _utc(str(query_snapshot["as_of_utc"]), name="query_snapshot.as_of_utc") != as_of:
        raise ValueError("query state snapshot must share the frozen expert as-of")

    historical = rerank_independent_analogues(
        historical_retrieval_v3=historical_retrieval_v3,
        query_snapshot=query_snapshot,
        candidate_snapshots_by_source_case_id=candidate_snapshots_by_source_case_id,
        reference_direction=reference_direction,
    )
    semantic = (
        dict(semantic_retrieval)
        if semantic_retrieval is not None
        and verify_semantic_retrieval_wrapper(semantic_retrieval)
        else None
    )
    if semantic_retrieval is not None and semantic is None:
        raise ValueError("Build 19 received an invalid semantic analogue retrieval")

    movement = (
        retrieve_movement_episode_analogues(
            investigation=movement_investigation,
            learning_cards=movement_learning_cards,
            as_of_utc=as_of,
        )
        if movement_investigation is not None
        else {
            "state": "unknown_not_supplied",
            "candidate_episode_n": 0,
            "selected_episode_n": 0,
            "analogues": [],
            "counterexamples_preserved": True,
            "outcomes_used_for_similarity": False,
            "future_values_used_for_selection": False,
        }
    )

    historical_context = {
        "state": historical["state"],
        "candidate_independent_episode_n": historical["candidate_independent_episode_n"],
        "selected_episode_n": historical["selected_episode_n"],
        "distribution": historical["distribution"],
        "selected_case_ids": [
            item["source_case_id"] for item in historical["matches"]
        ],
        "supporting_case_ids": [
            item["source_case_id"] for item in historical["supporting_analogues"]
        ],
        "counterexample_case_ids": [
            item["source_case_id"] for item in historical["counterexample_analogues"]
        ],
        "state_similarity": [
            {
                "source_case_id": item["source_case_id"],
                "score": item["state_similarity"],
            }
            for item in historical["matches"]
        ],
        "counterexamples_preserved": True,
        "outcomes_used_for_similarity": False,
        "future_values_used_for_selection": False,
    }
    movement_context = {
        "state": movement["state"],
        "candidate_episode_n": movement["candidate_episode_n"],
        "selected_episode_n": movement["selected_episode_n"],
        "path_class_counts": dict(movement.get("path_class_counts") or {}),
        "selected_card_digests": [
            item["learning_card_digest"]
            for item in movement.get("analogues") or []
        ],
        "counterexamples_preserved": True,
        "outcomes_used_for_similarity": False,
        "future_values_used_for_selection": False,
    }

    evidence_inputs = [
        {
            "evidence_id": "analogue_historical_retrieval",
            "source": "aidy_historical_analogue_retrieval_v3_structural_epoch",
            "path": "analogue_episode.historical_retrieval",
            "observed_at_utc": as_of,
            "state": "known" if historical["state"] == "matches_found" else "unknown",
            "value": historical_context,
            "provenance": {
                "v1_v2_v3_stack_reused": True,
                "duplicate_episode_collapse": True,
                "future_values_used_for_selection": False,
            },
        },
        {
            "evidence_id": "analogue_query_state_snapshot",
            "source": ANALOGUE_EPISODE_SIMILARITY_VERSION,
            "path": "analogue_episode.query_state",
            "observed_at_utc": as_of,
            "state": "known",
            "value": dict(query_snapshot),
            "provenance": {
                "exact_input_binding": True,
                "outcome_fields_used": False,
                "future_values_used": False,
            },
        },
        {
            "evidence_id": "analogue_semantic_retrieval",
            "source": "aidy_semantic_analogue_retrieval_v1",
            "path": "analogue_episode.semantic_retrieval",
            "observed_at_utc": as_of,
            "state": "known" if semantic is not None else "unknown",
            "value": (
                {
                    "semantic_retrieval_digest": semantic.get(
                        "semantic_retrieval_digest"
                    ),
                    "semantic_compatible_candidate_count": semantic.get(
                        "semantic_compatible_candidate_count"
                    ),
                    "cross_source_comparison_without_ledger_proven_pass_allowed": semantic.get(
                        "cross_source_comparison_without_ledger_proven_pass_allowed"
                    ),
                }
                if semantic is not None
                else {"state": "not_supplied"}
            ),
            "provenance": {
                "semantic_identity_boundary_reused": True,
                "cross_source_requires_qualified_equivalence": True,
                "future_values_used": False,
            },
        },
        {
            "evidence_id": "analogue_movement_episode_memory",
            "source": "aidy_gold_movement_memory_v1",
            "path": "analogue_episode.movement_memory",
            "observed_at_utc": as_of,
            "state": "known" if movement["state"] == "matches_found" else "unknown",
            "value": movement_context,
            "provenance": {
                "learning_cards_available_by_as_of_only": True,
                "outcomes_used_for_similarity": False,
                "future_values_used": False,
            },
        },
    ]

    calculators = [
        _context_calculator(
            calculator_id="analogue_historical_episode_retrieval",
            evidence_ref="analogue_historical_retrieval",
            known=historical["state"] == "matches_found",
            observation=historical_context,
            explanation=(
                "Historical v1/v2/v3 analogue representatives are re-ranked only "
                "with frozen gate-state and environment similarity. Outcomes are "
                "read after selection to describe continuation/retrace."
            ),
        ),
        _context_calculator(
            calculator_id="analogue_semantic_boundary",
            evidence_ref="analogue_semantic_retrieval",
            known=semantic is not None,
            observation=(
                {
                    "semantic_compatible_candidate_count": semantic.get(
                        "semantic_compatible_candidate_count"
                    ),
                    "cross_source_unqualified_allowed": semantic.get(
                        "cross_source_comparison_without_ledger_proven_pass_allowed"
                    ),
                }
                if semantic is not None
                else {"state": "not_supplied"}
            ),
            explanation=(
                "Existing semantic analogue work is accepted only when its "
                "semantic retrieval wrapper verifies; unqualified cross-source "
                "inheritance remains blocked."
            ),
        ),
        _context_calculator(
            calculator_id="analogue_movement_episode_memory",
            evidence_ref="analogue_movement_episode_memory",
            known=movement["state"] == "matches_found",
            observation=movement_context,
            explanation=(
                "Prior movement learning cards are eligible only after their own "
                "available-at timestamp; path outcomes never enter similarity."
            ),
        ),
        _context_calculator(
            calculator_id="analogue_pit_binding",
            evidence_ref="analogue_query_state_snapshot",
            known=True,
            observation={
                "query_snapshot_digest": query_snapshot["snapshot_digest"],
                "future_values_used": False,
                "outcome_fields_used": False,
            },
            explanation=(
                "Build 19 binds state similarity to exact PIT input identity and "
                "rejects future/outcome fields in the similarity snapshot."
            ),
        ),
    ]

    dimensions = global_environment["learning_dimensions"]
    distribution = historical["distribution"]
    mini_environment = {
        "session": dimensions["session"],
        "session_phase": dimensions["session_phase"],
        "volatility_state": dimensions["volatility_state"],
        "event_timing_state": dimensions["event_timing_state"],
        "historical_retrieval_state": historical["state"],
        "gate_similarity_state": (
            "known"
            if any(
                item["state_similarity"]["gate_state_similarity"] is not None
                for item in historical["matches"]
            )
            else "unknown"
        ),
        "environment_similarity_state": (
            "known"
            if any(
                item["state_similarity"]["environment_similarity"] is not None
                for item in historical["matches"]
            )
            else "unknown"
        ),
        "reference_direction": str(reference_direction),
        "continuation_state": (
            "present" if distribution["continuation_n"] else "absent"
        ),
        "counterexample_state": (
            "present" if distribution["retrace_n"] else "absent"
        ),
    }

    packet = build_expert_gate_packet(
        gate_id=ANALOGUE_EPISODE_GATE_ID,
        gate_version=ANALOGUE_EPISODE_EXPERT_VERSION,
        gate_mode="context_only",
        dependency_family="analogue",
        target_horizon_minutes=ANALOGUE_EPISODE_TARGET_HORIZON_MINUTES,
        as_of_utc=as_of,
        global_environment=global_environment,
        mini_environment=mini_environment,
        evidence_inputs=evidence_inputs,
        subcalculators=calculators,
        conclusion="context_only",
        internal_conviction=None,
        explanation_parts=(
            {
                "text": (
                    f"Historical analogue state={historical['state']} with "
                    f"{historical['selected_episode_n']} independent episodes; "
                    f"movement-memory state={movement['state']}."
                ),
                "source_refs": [
                    "calc:analogue_historical_episode_retrieval",
                    "calc:analogue_semantic_boundary",
                    "calc:analogue_movement_episode_memory",
                ],
            },
            {
                "text": (
                    "Similarity is outcome-blind. Supporting examples and "
                    "counterexamples are both retained after selection."
                ),
                "source_refs": ["calc:analogue_pit_binding"],
            },
        ),
        contradictions=(),
    )
    if not verify_expert_gate_packet(packet):
        raise ValueError("constructed Build 19 packet failed Build-2 verification")

    scopes = build_trust_scopes(
        packet=packet,
        reduced_contexts=ANALOGUE_EPISODE_TRUST_REDUCED_CONTEXTS,
    )
    rows_by_subject = trust_score_rows_by_subject or {}
    profiles = {
        key: select_conditional_trust(
            score_rows=rows_by_subject.get(key, ()),
            scopes=scopes,
        )
        for key in _subject_keys(packet)
    }
    trust = build_trust_envelope(packet=packet, profiles_by_subject=profiles)

    return {
        "expert_version": ANALOGUE_EPISODE_EXPERT_VERSION,
        "expert_packet": packet,
        "historical_analogues": historical,
        "movement_analogues": movement,
        "semantic_retrieval_state": "known" if semantic is not None else "unknown",
        "trust_scopes": scopes,
        "trust_envelope": trust,
        "counterexamples_preserved": True,
        "duplicate_episodes_collapsed": True,
        "exact_pit_state_binding": True,
        "outcomes_used_for_similarity": False,
        "future_values_used": False,
        "formal_forward_evidence_created": False,
        "live_money_execution_allowed": False,
    }


__all__ = [
    "ANALOGUE_EPISODE_EXPERT_VERSION",
    "ANALOGUE_EPISODE_GATE_ID",
    "ANALOGUE_EPISODE_SIMILARITY_VERSION",
    "ANALOGUE_EPISODE_TRUST_REDUCED_CONTEXTS",
    "build_analogue_episode_expert",
    "build_episode_state_snapshot",
    "rerank_independent_analogues",
    "retrieve_movement_episode_analogues",
    "score_episode_state_similarity",
    "summarise_chronological_holdout",
    "verify_episode_state_snapshot",
]
