from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from hashlib import sha256
from typing import Any

PIT_INTEGRITY_VERSION = "aidy_pit_integrity_adversarial_v1"
PIT_INTEGRITY_DIGEST_ALGORITHM = "sha256"

_ATTACKS: tuple[tuple[str, str, str], ...] = (
    (
        "future_candle_revision",
        "day6_pit",
        "Later candle revisions cannot be selected before first_observed_at.",
    ),
    (
        "future_macro_revision",
        "day6_day10_macro",
        "Later macro revisions cannot alter an earlier as-of view.",
    ),
    (
        "future_snapshot",
        "day6_day7_quote",
        "Snapshots captured after T remain unavailable at T.",
    ),
    (
        "future_cross_market_observation",
        "day9_cross_market",
        "Cross-market facts first observed after T remain unavailable at T.",
    ),
    (
        "retrospective_candle_in_pit_features",
        "day7_features",
        "Retrospective-only research candles cannot enter PIT features.",
    ),
    (
        "future_snapshot_in_pit_features",
        "day7_features",
        "A quote snapshot captured after the feature as-of time is rejected.",
    ),
    (
        "rehashed_future_field_in_feature_packet",
        "day10_context",
        "Rehashed future/outcome fields cannot enter objective context.",
    ),
    (
        "rehashed_retrospective_lineage_in_feature_packet",
        "day10_context",
        "Rehashed retrospective lineage cannot masquerade as PIT context evidence.",
    ),
    (
        "future_signal_lifecycle",
        "day10_context",
        "Future lifecycle timestamps cannot enter objective context.",
    ),
    (
        "rehashed_hindsight_in_regime_context",
        "day11_regime",
        "Rehashed future outcomes in Day 10 context cannot enter regime classification.",
    ),
    (
        "future_evaluation_as_decision_state",
        "day10_day12_14_boundary",
        "Evaluation-only records cannot be injected into AIDY signal lifecycle state.",
    ),
    (
        "rehashed_hindsight_in_setup_context",
        "day15_setup",
        "Rehashed future/outcome fields cannot enter setup detection.",
    ),
    (
        "mismatched_regime_provenance",
        "day15_setup",
        "A setup detector rejects a regime not derived from the supplied context.",
    ),
    (
        "future_field_in_case_input",
        "day16_cases",
        "Future/outcome fields cannot enter the historical case input boundary after rehashing.",
    ),
    (
        "candidate_at_or_after_query",
        "day17_retrieval",
        "An analogue candidate at or after query time is excluded.",
    ),
    (
        "outcome_not_yet_available",
        "day17_retrieval",
        "A candidate outcome unavailable at query time is excluded.",
    ),
    (
        "outcome_changes_similarity",
        "day17_retrieval",
        "Changing future outcomes cannot alter analogue similarity or selection.",
    ),
    (
        "tampered_selection_or_outcome_similarity",
        "day18_grading",
        "Evidence grading rejects tampered selection and outcome-influenced similarity.",
    ),
)


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value: object) -> str:
    return sha256(_canonical_json(value).encode()).hexdigest()


def attack_catalogue() -> list[dict[str, str]]:
    return [
        {
            "attack_id": attack_id,
            "boundary": boundary,
            "expected_guard": expected_guard,
        }
        for attack_id, boundary, expected_guard in _ATTACKS
    ]


def integrity_manifest() -> dict[str, Any]:
    manifest: dict[str, Any] = {
        "pit_integrity_version": PIT_INTEGRITY_VERSION,
        "digest_algorithm": PIT_INTEGRITY_DIGEST_ALGORITHM,
        "attack_count": len(_ATTACKS),
        "attacks": attack_catalogue(),
        "required_result": "all_attacks_blocked",
        "hindsight_tolerance": "zero",
    }
    manifest["manifest_digest"] = _digest(manifest)
    return manifest


def build_integrity_report(
    *,
    blocked_attack_ids: Iterable[str],
    evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    expected = [attack_id for attack_id, _, _ in _ATTACKS]
    supplied = sorted({str(value) for value in blocked_attack_ids})
    unknown = sorted(set(supplied) - set(expected))
    if unknown:
        raise ValueError(f"Unknown PIT-integrity attack IDs: {unknown}")
    missing = sorted(set(expected) - set(supplied))
    report: dict[str, Any] = {
        "pit_integrity_version": PIT_INTEGRITY_VERSION,
        "digest_algorithm": PIT_INTEGRITY_DIGEST_ALGORITHM,
        "attack_count": len(expected),
        "blocked_attack_count": len(supplied),
        "blocked_attack_ids": supplied,
        "unresolved_attack_ids": missing,
        "all_attacks_blocked": not missing,
        "decision_context_future_access_allowed": False,
        "retrospective_data_may_masquerade_as_pit": False,
        "outcomes_may_affect_similarity": False,
        "evidence": dict(evidence or {}),
    }
    report["report_digest"] = _digest(report)
    return report
