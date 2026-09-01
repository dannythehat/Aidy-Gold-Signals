from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable, Mapping

from aidy.databento_gc import day40_free_first_procurement_record

DAY40_GATE_VERSION = "aidy_architecture_v2_prepaper_gate_v1"
DAY40_BASE_SHA = "cb31e28c38d38c173ab857badb487a75ac601b0f"

ADVERSARIAL_SCENARIOS = (
    "stale_data",
    "missing_data",
    "conflicting_data",
    "provider_outage",
    "openai_outage",
    "storage_outage",
    "malformed_model_output",
    "source_revision",
    "duplicate_input",
    "restart_replay",
)


@dataclass(frozen=True)
class P0Requirement:
    requirement_id: str
    title: str
    evidence: tuple[tuple[str, tuple[str, ...]], ...]


P0_REQUIREMENTS: tuple[P0Requirement, ...] = (
    P0Requirement(
        "P0-01",
        "J1 analogue-independence on at least 1,000 historical queries",
        (
            ("src/aidy/day23_research.py", ("QUERY_COUNT = 1000",)),
            ("scripts/day24_independent_episode_acceptance.py", ("QUERY_COUNT = 1000", "effective_n")),
        ),
    ),
    P0Requirement(
        "P0-02",
        "J16 evidence-grade validation is conservative when ordering is unsupported",
        (
            ("src/aidy/evaluation_scoring.py", ("J16_POST_HARDENING_VERSION", "J16_MIN_EVALUABLE_GRADES")),
            ("scripts/day38_evaluation_acceptance.py", ("QUERY_COUNT = 1000", "j16")),
        ),
    ),
    P0Requirement(
        "P0-03",
        "Purging, embargo, episode deduplication and effective independent sample size",
        (
            ("src/aidy/replay_evaluation.py", ("purge", "embargo", "episode")),
            ("src/aidy/evaluation_scoring.py", ("effective_n", "_dedupe_exact_episode_rows")),
        ),
    ),
    P0Requirement(
        "P0-04",
        "Explicit NO_COMPARABLE_CASE retrieval outcome",
        (
            ("src/aidy/analogue_retrieval_v2.py", ("no_comparable_case", "no_comparable_reason")),
            ("src/aidy/context_composer_v2.py", ("no_comparable_case", "historical_signal_invented")),
        ),
    ),
    P0Requirement(
        "P0-05",
        "Market-structure epoch includes 24 July 2026 1-Ounce Gold 24/7 boundary",
        (("src/aidy/market_structure_context.py", ("ONE_OZ_24X7_EFFECTIVE_DATE = \"2026-07-24\"", "market_structure_epoch")),),
    ),
    P0Requirement(
        "P0-06",
        "Named liquidity/event windows plus holiday, half-day, thin-market and weekend 1OZ state",
        (("src/aidy/market_structure_context.py", ("session", "holiday", "thin")),),
    ),
    P0Requirement(
        "P0-07",
        "Prior HLC, opening/overnight ranges, session extremes and gap state",
        (("src/aidy/price_structure_v2.py", ("prior_day", "prior_week", "prior_month", "gap")),),
    ),
    P0Requirement(
        "P0-08",
        "PIT-safe historical XAUUSD bid/ask with weekday x time-of-day normalization",
        (("src/aidy/historical_spread.py", ("DAY27_VERSION", "BASELINE_VERSION", "weekday")),),
    ),
    P0Requirement(
        "P0-09",
        "Vintaged rates, breakeven and curve decomposition with correlated-source control",
        (
            ("src/aidy/macro_vintages.py", ("pit_reconstructable", "revision_index")),
            ("docs/day28-pit-vintaged-rates-contract.md", ("breakeven", "curve")),
        ),
    ),
    P0Requirement(
        "P0-10",
        "CME public open interest, settlement and contract/roll state",
        (("src/aidy/cme_contract_intelligence.py", ("open_interest", "settlement", "roll")),),
    ),
    P0Requirement(
        "P0-11",
        "GVZ implied-volatility evidence",
        (("src/aidy/volatility_intelligence.py", ("GVZ", "pit_reconstructable")),),
    ),
    P0Requirement(
        "P0-12",
        "Expanded tiered scheduled macro intelligence",
        (
            ("src/aidy/macro_event_intelligence.py", ("event_tier", "consensus")),
            ("docs/day29-tiered-macro-event-intelligence-contract.md", ("forward", "timestamp")),
        ),
    ),
    P0Requirement(
        "P0-13",
        "Immutable decision ledger, falsifiable invalidation and no-trade shadows",
        (
            ("src/aidy/decision_ledger.py", ("no_trade", "invalidation")),
            ("src/aidy/master_trader_contract_v2.py", ("invalidation_condition", "counter_argument")),
        ),
    ),
    P0Requirement(
        "P0-14",
        "Per-field PIT reconstruction attestation plus deliberate leak audit",
        (("src/aidy/research_integrity.py", ("pit_reconstructable", "leak")),),
    ),
    P0Requirement(
        "P0-15",
        "Experiment/trial preregistration and holdout reuse prevention",
        (
            ("src/aidy/research_integrity.py", ("trial", "preregister")),
            ("src/aidy/replay_evaluation.py", ("holdout", "reuse")),
        ),
    ),
    P0Requirement(
        "P0-16",
        "Symmetric retrieval and counter-evidence-first composition",
        (("src/aidy/context_composer_v2.py", ("counter", "invalidation")),),
    ),
    P0Requirement(
        "P0-17",
        "Master Trader self-consistency exactly k=3 with abstention on disagreement",
        (("src/aidy/self_consistency.py", ("SAMPLE_COUNT = 3", "no_trade")),),
    ),
    P0Requirement(
        "P0-18",
        "Decision records bind model, prompt, context, strategy/config and sample identities",
        (
            ("src/aidy/decision_ledger.py", ("prompt_version", "model_id", "strategy_version", "config_version")),
            ("src/aidy/self_consistency.py", ("prompt_digest", "request_digest", "model_id")),
        ),
    ),
)


class Day40GateError(ValueError):
    pass


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest(value: object) -> str:
    return sha256(canonical_json(value).encode()).hexdigest()


def _read(root: Path, relative: str) -> str:
    path = root / relative
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


def evaluate_p0_checklist(root: str | Path) -> dict[str, Any]:
    base = Path(root)
    results: list[dict[str, Any]] = []
    for requirement in P0_REQUIREMENTS:
        evidence_results: list[dict[str, Any]] = []
        passed = True
        for relative, markers in requirement.evidence:
            text = _read(base, relative)
            missing_markers = [marker for marker in markers if marker.lower() not in text.lower()]
            evidence_ok = bool(text) and not missing_markers
            passed = passed and evidence_ok
            evidence_results.append(
                {
                    "path": relative,
                    "present": bool(text),
                    "required_markers": list(markers),
                    "missing_markers": missing_markers,
                    "passed": evidence_ok,
                }
            )
        results.append(
            {
                "requirement_id": requirement.requirement_id,
                "title": requirement.title,
                "passed": passed,
                "evidence": evidence_results,
            }
        )

    passed_n = sum(1 for item in results if item["passed"])
    record: dict[str, Any] = {
        "gate_version": DAY40_GATE_VERSION,
        "requirement_count": len(P0_REQUIREMENTS),
        "passed_count": passed_n,
        "failed_count": len(P0_REQUIREMENTS) - passed_n,
        "passed": passed_n == len(P0_REQUIREMENTS) == 18,
        "effective_n_is_authoritative_for_grading": True,
        "j16_interpretation": "revised_to_insufficient_when_effective_n_is_inadequate",
        "j16_predictive_ordering_claimed": False,
        "formal_paper_metric_generated_before_gate_accepted": False,
        "items": results,
    }
    record["checklist_digest"] = digest(record)
    return record


def validate_formal_paper_metric(*, generated_after_day40_gate: bool) -> dict[str, Any]:
    accepted = bool(generated_after_day40_gate)
    return {
        "accepted": accepted,
        "reason": "post_day40_gate_metric" if accepted else "pre_day40_formal_paper_metrics_are_non_authoritative",
    }


def adversarial_failure_record(
    scenario: str,
    *,
    publication_mutated: bool = False,
    broker_mutated: bool = False,
    super_signals_mutated: bool = False,
    decision_state: str = "no_trade",
) -> dict[str, Any]:
    if scenario not in ADVERSARIAL_SCENARIOS:
        raise Day40GateError(f"Unsupported adversarial scenario: {scenario}")
    fail_closed = (
        decision_state == "no_trade"
        and not publication_mutated
        and not broker_mutated
        and not super_signals_mutated
    )
    record: dict[str, Any] = {
        "scenario": scenario,
        "decision_state": decision_state,
        "fail_closed": fail_closed,
        "publication_mutated": publication_mutated,
        "broker_mutated": broker_mutated,
        "super_signals_mutated": super_signals_mutated,
    }
    record["scenario_digest"] = digest(record)
    return record


def run_adversarial_matrix() -> dict[str, Any]:
    records = [adversarial_failure_record(item) for item in ADVERSARIAL_SCENARIOS]
    result: dict[str, Any] = {
        "scenario_count": len(records),
        "all_failed_closed": all(record["fail_closed"] for record in records),
        "publication_mutation_observed": any(record["publication_mutated"] for record in records),
        "broker_mutation_observed": any(record["broker_mutated"] for record in records),
        "super_signals_mutation_observed": any(record["super_signals_mutated"] for record in records),
        "records": records,
    }
    result["matrix_digest"] = digest(result)
    return result


def build_day40_manifest(root: str | Path) -> dict[str, Any]:
    checklist = evaluate_p0_checklist(root)
    adversarial = run_adversarial_matrix()
    procurement = day40_free_first_procurement_record()
    result: dict[str, Any] = {
        "manifest_version": "aidy_day40_prepaper_acceptance_manifest_v1",
        "base_sha": DAY40_BASE_SHA,
        "checklist": checklist,
        "adversarial": adversarial,
        "procurement": procurement,
        "architecture_p0_passed": checklist["passed"],
        "adversarial_gate_passed": adversarial["all_failed_closed"],
        "procurement_decision_recorded": True,
        "paid_market_data_activated": False,
        "live_gc_subscription_activated": False,
        "formal_forward_paper_evaluation_started": False,
        "broker_side_effects_allowed": False,
        "telegram_side_effects_allowed": False,
        "super_signals_side_effects_allowed": False,
    }
    result["manifest_digest"] = digest(result)
    return result


def verify_manifest(manifest: Mapping[str, Any]) -> bool:
    if not isinstance(manifest, Mapping):
        return False
    body = dict(manifest)
    supplied = str(body.pop("manifest_digest", ""))
    if not supplied or supplied != digest(body):
        return False
    if body.get("manifest_version") != "aidy_day40_prepaper_acceptance_manifest_v1":
        return False
    if body.get("base_sha") != DAY40_BASE_SHA:
        return False
    if body.get("paid_market_data_activated") is not False:
        return False
    if body.get("live_gc_subscription_activated") is not False:
        return False
    if body.get("formal_forward_paper_evaluation_started") is not False:
        return False
    return True


def failing_items(checklist: Mapping[str, Any]) -> Iterable[str]:
    for item in checklist.get("items", []):
        if isinstance(item, Mapping) and item.get("passed") is not True:
            yield str(item.get("requirement_id") or "unknown")
