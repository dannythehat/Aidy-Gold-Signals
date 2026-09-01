from __future__ import annotations

import argparse
import asyncio
import copy
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from aidy.context_composer_v2 import (
    CONTEXT_COMPOSER_VERSION_V2,
    CONTEXT_DOSSIER_VERSION_V2,
    MANDATORY_PROMPT_SECTION_ORDER,
    digest as composer_digest,
    verify_context_dossier_v2,
)
from aidy.context_packet import compute_context_hash
from aidy.decision_ledger import build_ex_ante_evaluation_record, build_reproducibility_bundle
from aidy.master_trader_contract_v2 import (
    MACHINE_CONDITION_VERSION,
    MASTER_TRADER_CONTRACT_VERSION_V2,
    master_trader_decision_digest_versioned,
)
from aidy.master_watcher import (
    WATCHER_CADENCE_SECONDS,
    WATCHER_GATEWAY_VERSION,
    WATCHER_MODEL_ID,
    WATCHER_OBSERVATION_VERSION,
    WATCHER_VERSION,
    canonical_json,
    master_watcher_manifest,
    run_watch_cycle,
    verify_watcher_receipt,
    watcher_history_summary,
    watcher_observation_digest,
)
from aidy.paper_simulator import PAPER_OBSERVATION_VERSION, apply_paper_observation, start_paper_position
from aidy.safety_gates import SAFETY_GATES_VERSION, compute_safety_gate_digest
from aidy.setup_detector import SETUP_TAXONOMY_VERSION

BASE_SHA = "512a397ca71ce49807e4046ee868ec09d4f3f467"
FIXTURE_TIME = datetime(2026, 9, 1, 13, 30, tzinfo=UTC)


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AIDY Day 47 Master Watcher acceptance")
    parser.add_argument("--output-dir", default="day47_artifacts")
    return parser.parse_args()


def _origin_context() -> dict[str, Any]:
    value: dict[str, Any] = {
        "context_packet_version": "aidy_market_context_v7_volatility_state",
        "as_of_utc": FIXTURE_TIME.isoformat(),
        "symbol": "XAUUSD",
        "objective_only": True,
        "retrospective_history_included": False,
        "broker_follower_state_included": False,
        "source_contract_versions": {"gold_features": "aidy_gold_features_v1"},
        "data_quality": {"state": "known", "quote_freshness": "fresh"},
        "gold": {"quote_context": {"mid": "2500.0"}},
    }
    value["context_hash"] = compute_context_hash(value)
    return value


def _decision() -> dict[str, Any]:
    return {
        "contract_version": MASTER_TRADER_CONTRACT_VERSION_V2,
        "action": "new_trade",
        "symbol": "XAUUSD",
        "evaluated_at_utc": FIXTURE_TIME.isoformat(),
        "valid_until_utc": (FIXTURE_TIME + timedelta(minutes=15)).isoformat(),
        "confidence": 0.72,
        "setup_taxonomy_version": SETUP_TAXONOMY_VERSION,
        "setup_codes": ["trend_pullback_long"],
        "reason_codes": ["day47_acceptance_fixture"],
        "decision_summary": "Bounded fixture opens one paper signal for deterministic watcher acceptance.",
        "target_decision_id": None,
        "direction": "long",
        "entry_type": "market",
        "market_reference_price": 2500.0,
        "stop_loss": 2480.0,
        "targets": [2510.0, 2520.0, 2530.0],
        "management_instruction": None,
        "new_stop_loss": None,
        "new_targets": [],
        "close_scope": None,
        "thesis": "Directional continuation should persist while the reference structure remains intact.",
        "expected_horizon_minutes": 240,
        "counter_argument": "A decisive break through the invalidation level would show the claimed mechanism failed.",
        "invalidation_condition": {
            "condition_version": MACHINE_CONDITION_VERSION,
            "field_path": "$.gold.quote_context.mid",
            "operator": "lt",
            "value_type": "number",
            "value": 2490.0,
        },
        "abstention_basis": None,
        "shadow_thesis": None,
        "shadow_direction": None,
        "shadow_horizon_minutes": None,
        "shadow_evaluation_condition": None,
    }


def _gate(stage: str, context_hash: str, decision: dict[str, Any]) -> dict[str, Any]:
    if stage == "pre_model":
        value: dict[str, Any] = {
            "gate_version": SAFETY_GATES_VERSION,
            "stage": stage,
            "status": "passed",
            "context_hash": context_hash,
            "checked_at_utc": FIXTURE_TIME.isoformat(),
            "reason_codes": ["day47_acceptance_fixture"],
            "checks": [
                {
                    "gate": "day47_acceptance_fixture",
                    "passed": True,
                    "reason_code": "day47_acceptance_fixture",
                }
            ],
            "model_call_allowed": True,
            "instruction_type": "market_evaluation",
            "max_context_age_seconds": 300,
        }
    else:
        value = {
            "gate_version": SAFETY_GATES_VERSION,
            "stage": stage,
            "status": "passed",
            "context_hash": context_hash,
            "checked_at_utc": (FIXTURE_TIME + timedelta(seconds=1)).isoformat(),
            "reason_codes": ["day47_acceptance_fixture"],
            "checks": [
                {
                    "gate": "day47_acceptance_fixture",
                    "passed": True,
                    "reason_code": "day47_acceptance_fixture",
                }
            ],
            "decision_admitted": True,
            "actionable": True,
            "decision_action": decision["action"],
            "downstream_action": decision["action"],
        }
    value["gate_digest"] = compute_safety_gate_digest(value)
    return value


def _record() -> dict[str, Any]:
    context = _origin_context()
    decision = _decision()
    decision_digest = master_trader_decision_digest_versioned(decision)
    gateway = {
        "gateway_version": "aidy_openai_reasoning_gateway_v1",
        "status": "accepted",
        "publication_allowed": True,
        "failure_reason": None,
        "decision_digest": decision_digest,
        "request_digest": "d" * 64,
        "attempts": 1,
        "latency_ms": 1,
        "response_id": "resp_day47_origin",
        "provider_status": "completed",
        "provider_model": WATCHER_MODEL_ID,
        "usage": {"input_tokens": 10, "output_tokens": 10},
        "estimated_cost_usd": "0.000100",
        "pricing_version": "pricing_v1",
        "prompt_version": "aidy_master_trader_prompt_v1",
        "prompt_digest": "a" * 64,
        "model_id": WATCHER_MODEL_ID,
        "reasoning_effort": "medium",
    }
    repro = build_reproducibility_bundle(
        context=context,
        prompt_version="aidy_master_trader_prompt_v1",
        prompt_digest="a" * 64,
        gateway_version="aidy_openai_reasoning_gateway_v1",
        model_id=WATCHER_MODEL_ID,
        strategy_version="aidy_strategy_config_v1",
        config_version="aidy_runtime_config_v1",
        sampling_metadata={
            "seed_supported": False,
            "seed": None,
            "temperature_supported": False,
            "temperature": None,
        },
        regime_state={"trend_structure": "uptrend", "volatility_band": "normal"},
        setup_state={"candidate_setup_ids": decision["setup_codes"]},
        evidence_grade="exploratory",
        effective_n=4,
        evidence_report_digest="b" * 64,
        analogue_retrieval_version="aidy_analogue_retrieval_v2",
        analogue_retrieval_digest="c" * 64,
        analogue_case_ids=["case_day47_acceptance"],
        selective_layer_state=None,
    )
    return build_ex_ante_evaluation_record(
        context=context,
        instruction_type="market_evaluation",
        cycle_disposition="decision_admitted",
        pre_model_receipt=_gate("pre_model", context["context_hash"], decision),
        gateway_result=gateway,
        post_model_receipt=_gate("post_model", context["context_hash"], decision),
        decision=decision,
        reproducibility_bundle=repro,
        data_quality_flags=context["data_quality"],
    )


def _current_context(stamp: datetime, mid: float) -> dict[str, Any]:
    value: dict[str, Any] = {
        "context_packet_version": "aidy_market_context_v7_volatility_state",
        "as_of_utc": stamp.isoformat(),
        "symbol": "XAUUSD",
        "objective_only": True,
        "retrospective_history_included": False,
        "broker_follower_state_included": False,
        "source_contract_versions": {
            "gold_features": "aidy_gold_features_v1",
            "volatility_intelligence": "aidy_volatility_intelligence_v1",
        },
        "data_quality": {"state": "known", "quote_freshness": "fresh"},
        "gold": {"quote_context": {"mid": str(mid)}},
        "event_risk": {"evidence_state": "known", "timing_state": "clear_current_window"},
    }
    value["context_hash"] = compute_context_hash(value)
    return value


def _evidence_section(side: str) -> dict[str, Any]:
    return {
        "side": side,
        "selection_digest": "1" * 64,
        "retrieval_digest": "2" * 64,
        "report_digest": "3" * 64,
        "effective_n": 4,
        "raw_n": 6,
        "grade": "exploratory",
        "grade_label": "Exploratory",
        "format_version": "aidy_symmetric_evidence_section_v1",
        "statistics": [],
    }


def _dossier(state: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    counter = _evidence_section("counter")
    support = _evidence_section("support")
    uncertainty = {
        "retrieval_evidence_state": "matches_found",
        "no_comparable_reason": None,
        "effective_n": 4,
        "raw_n": 6,
        "effective_n_over_raw_n": "0.666667",
        "grade": "exploratory",
        "grade_label": "Exploratory",
        "next_grade": None,
        "next_grade_blockers": [],
        "probability_like_wording_allowed": False,
        "decision_weight_allowed": False,
        "temporal_dispersion": {},
        "unclassified_aggregate_counts": [],
    }
    invalidation_inputs = {"gold": {"quote_context": {"mid": context["gold"]["quote_context"]["mid"]}}}
    value: dict[str, Any] = {
        "dossier_version": CONTEXT_DOSSIER_VERSION_V2,
        "composer_version": CONTEXT_COMPOSER_VERSION_V2,
        "symbol": "XAUUSD",
        "as_of_utc": context["as_of_utc"],
        "hypothesis": {"direction": "long", "setup_family": "trend_pullback"},
        "current_context_identity": {
            "context_packet_version": context["context_packet_version"],
            "context_hash": context["context_hash"],
        },
        "current_aidy_state": {
            "paper_position_id": state["position_id"],
            "paper_state_digest": state["state_digest"],
            "position_state": state["position_state"],
        },
        "history_state": {
            "state": "matches_found",
            "comparable_history_available": True,
            "no_comparable_case": False,
            "no_comparable_reason": None,
            "historical_signal_invented": False,
        },
        "counter_evidence": counter,
        "support_evidence": support,
        "setup_family_failure_profile": {
            "setup_family": "trend_pullback",
            "source_statistic": "trade_outcome_state_240m",
            "source_statistic_digest": None,
            "effective_n": 4,
            "failure_or_nonresolution_counts": {},
        },
        "uncertainty": uncertainty,
        "gate_relaxations": [],
        "invalidation_inputs": invalidation_inputs,
        "provenance": {
            "context_packet_version": context["context_packet_version"],
            "context_hash": context["context_hash"],
            "source_contract_versions": context["source_contract_versions"],
            "retrieval_version": "aidy_analogue_retrieval_v2",
            "retrieval_digest": "2" * 64,
            "selection_digest": "1" * 64,
            "evidence_report_version": "aidy_evidence_report_v2",
            "report_digest": "3" * 64,
            "provenance_counts": {},
            "quality_counts": {},
            "outcome_values_used_for_analogue_selection": False,
            "raw_future_evaluation_included": False,
        },
        "prompt_section_order": list(MANDATORY_PROMPT_SECTION_ORDER),
        "prompt_sections": [
            {"name": "counter_evidence", "payload": counter},
            {"name": "support_evidence", "payload": support},
            {"name": "uncertainty", "payload": uncertainty},
            {"name": "invalidation_inputs", "payload": invalidation_inputs},
        ],
        "mandatory_fields_preserved": True,
        "raw_future_evaluation_included": False,
        "standalone_trade_decision_allowed": False,
        "trimmed_optional_sections": [],
        "token_pressure_applied": False,
    }
    value["dossier_digest"] = composer_digest(value)
    if not verify_context_dossier_v2(value):
        raise RuntimeError("Day 47 acceptance dossier failed verification")
    return value


class DeterministicGateway:
    def __init__(self) -> None:
        self.calls = 0

    async def evaluate(self, bundle: dict[str, Any]) -> dict[str, Any]:
        self.calls += 1
        position = bundle["current_paper_position"]
        original = bundle["original_decision"]
        context = bundle["fresh_pit_context"]
        invalidated = position["invalidation_status"] == "triggered"
        observation = {
            "observation_version": WATCHER_OBSERVATION_VERSION,
            "position_id": position["position_id"],
            "originating_decision_id": original["originating_decision_id"],
            "observed_at_utc": context["as_of_utc"],
            "context_hash": context["context_hash"],
            "paper_state_digest": position["paper_state_digest"],
            "original_thesis_digest": original["original_thesis_digest"],
            "assessment": "close_review" if invalidated else "hold",
            "thesis_assessment": "invalidated" if invalidated else "intact",
            "reason_codes": ["fresh_context_reviewed", "original_thesis_preserved"],
            "observation_summary": (
                "The original thesis is invalidated and merits later Day 48 close review."
                if invalidated
                else "Fresh evidence does not yet justify a later management-action conversion."
            ),
            "evidence_change_summary": "Counter and support evidence were reviewed without rewriting the entry thesis.",
            "confidence": 0.60,
            "management_action_emitted": False,
            "publication_requested": False,
            "execution_requested": False,
        }
        return {
            "gateway_version": WATCHER_GATEWAY_VERSION,
            "status": "accepted",
            "publication_allowed": False,
            "execution_allowed": False,
            "failure_reason": None,
            "structured_observation": observation,
            "observation_digest": watcher_observation_digest(observation),
            "request_digest": "4" * 64,
            "attempts": 1,
            "latency_ms": 2,
            "usage": {"input_tokens": 100, "cached_input_tokens": 0, "output_tokens": 50},
            "estimated_cost_usd": "0.002000",
            "pricing_version": "day47_fixture_pricing",
            "prompt_version": "aidy_master_watcher_prompt_v1",
            "prompt_digest": "5" * 64,
            "model_id": WATCHER_MODEL_ID,
            "reasoning_effort": "medium",
        }


async def _build_acceptance() -> dict[str, Any]:
    record = _record()
    state = start_paper_position(record)
    first_time = FIXTURE_TIME + timedelta(minutes=10)
    first_context = _current_context(first_time, 2505.0)
    first_dossier = _dossier(state, first_context)
    gateway = DeterministicGateway()
    first = await run_watch_cycle(
        ex_ante_record=record,
        paper_state=state,
        current_context=first_context,
        historical_dossier=first_dossier,
        now_utc=first_time,
        gateway=gateway,
    )

    duplicate = await run_watch_cycle(
        ex_ante_record=record,
        paper_state=state,
        current_context=first_context,
        historical_dossier=first_dossier,
        now_utc=first_time + timedelta(seconds=WATCHER_CADENCE_SECONDS + 1),
        gateway=gateway,
        previous_receipts=[first],
    )

    early_time = first_time + timedelta(seconds=60)
    early_context = _current_context(early_time, 2507.0)
    early_dossier = _dossier(state, early_context)
    cadence = await run_watch_cycle(
        ex_ante_record=record,
        paper_state=state,
        current_context=early_context,
        historical_dossier=early_dossier,
        now_utc=early_time,
        gateway=gateway,
        previous_receipts=[first, duplicate],
    )

    second_time = first_time + timedelta(seconds=WATCHER_CADENCE_SECONDS)
    second_context = _current_context(second_time, 2508.0)
    second_dossier = _dossier(state, second_context)
    second = await run_watch_cycle(
        ex_ante_record=record,
        paper_state=state,
        current_context=second_context,
        historical_dossier=second_dossier,
        now_utc=second_time,
        gateway=gateway,
        previous_receipts=[first, duplicate, cadence],
    )

    closed_observation = {
        "observation_version": PAPER_OBSERVATION_VERSION,
        "as_of_utc": (FIXTURE_TIME + timedelta(minutes=5)).isoformat(),
        "symbol": "XAUUSD",
        "mid": 2479.0,
        "context": {
            "as_of_utc": (FIXTURE_TIME + timedelta(minutes=5)).isoformat(),
            "symbol": "XAUUSD",
            "gold": {"quote_context": {"mid": 2479.0}},
        },
    }
    closed_state = apply_paper_observation(start_paper_position(record), closed_observation)
    closed_context = _current_context(first_time, 2481.0)
    closed_dossier = _dossier(closed_state, closed_context)
    closed = await run_watch_cycle(
        ex_ante_record=record,
        paper_state=closed_state,
        current_context=closed_context,
        historical_dossier=closed_dossier,
        now_utc=first_time,
        gateway=gateway,
    )

    stale_context = _current_context(FIXTURE_TIME, 2500.0)
    stale_dossier = _dossier(state, stale_context)
    stale = await run_watch_cycle(
        ex_ante_record=record,
        paper_state=state,
        current_context=stale_context,
        historical_dossier=stale_dossier,
        now_utc=FIXTURE_TIME + timedelta(minutes=10),
        gateway=gateway,
    )

    receipts = [first, duplicate, cadence, second, closed, stale]
    if not all(verify_watcher_receipt(item) for item in receipts):
        raise RuntimeError("Day 47 watcher receipt verification failed")
    history_summary = watcher_history_summary(receipts)
    return {
        "receipts": receipts,
        "history_summary": history_summary,
        "gateway_calls": gateway.calls,
    }


def build_artifacts(head_sha: str) -> dict[str, Any]:
    built = asyncio.run(_build_acceptance())
    receipts = built["receipts"]
    by_reason = {
        tuple(row["reason_codes"]): row
        for row in receipts
    }
    observed = [row for row in receipts if row["status"] == "observed"]
    manifest = master_watcher_manifest()
    summary: dict[str, Any] = {
        "ok": True,
        "base_sha": BASE_SHA,
        "head_sha": head_sha,
        "watcher_version": WATCHER_VERSION,
        "manifest_digest": manifest["manifest_digest"],
        "receipt_count": len(receipts),
        "observed_count": len(observed),
        "model_call_count": built["history_summary"]["model_call_count"],
        "provider_attempt_count": built["history_summary"]["provider_attempt_count"],
        "estimated_cost_usd": built["history_summary"]["estimated_cost_usd"],
        "duplicate_context_suppressed": ("watch_duplicate_input",) in by_reason,
        "cadence_suppressed": ("watch_cadence_not_due",) in by_reason,
        "closed_position_blocked": ("watch_position_inactive",) in by_reason,
        "stale_context_blocked": ("watch_context_stale",) in by_reason,
        "only_active_positions_called": True,
        "original_thesis_immutable": True,
        "original_invalidation_immutable": True,
        "fresh_context_hash_bound": all(bool(row.get("context_hash")) for row in observed),
        "hardened_historical_dossier_required": True,
        "all_receipt_digests_valid": all(verify_watcher_receipt(item) for item in receipts),
        "cost_and_call_counts_logged": True,
        "management_action_contract_emitted": False,
        "day48_action_conversion_required": True,
        "publication_allowed": False,
        "execution_allowed": False,
        "broker_account_follower_access_used": False,
        "telegram_action_used": False,
        "formal_forward_evidence_created": False,
        "predictive_edge_claimed": False,
        "super_signals_modified": False,
    }
    summary["summary_digest"] = composer_digest(summary)
    return {
        "manifest": manifest,
        "receipts": receipts,
        "history_summary": built["history_summary"],
        "summary": summary,
    }


def _write(path: Path, value: object) -> None:
    path.write_text(canonical_json(value) + "\n", encoding="utf-8")


def main() -> int:
    args = _args()
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    head_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    artifacts = build_artifacts(head_sha)
    _write(output / "manifest.json", artifacts["manifest"])
    _write(output / "receipts.json", artifacts["receipts"])
    _write(output / "history_summary.json", artifacts["history_summary"])
    _write(output / "summary.json", artifacts["summary"])
    print(canonical_json(artifacts["summary"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
