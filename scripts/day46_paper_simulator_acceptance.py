from __future__ import annotations

import argparse
import copy
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from aidy.context_packet import compute_context_hash
from aidy.decision_ledger import (
    build_ex_ante_evaluation_record,
    build_reproducibility_bundle,
    verify_outcome_attachment,
)
from aidy.master_trader_contract_v2 import (
    MACHINE_CONDITION_VERSION,
    MASTER_TRADER_CONTRACT_VERSION_V2,
    master_trader_decision_digest_versioned,
)
from aidy.paper_simulator import (
    PAPER_OBSERVATION_VERSION,
    apply_paper_observation,
    build_paper_outcome_attachment,
    canonical_json,
    day46_manifest,
    digest,
    replay_paper_position,
    restore_paper_state,
    serialize_paper_state,
    start_paper_position,
    verify_paper_state,
)
from aidy.safety_gates import SAFETY_GATES_VERSION, compute_safety_gate_digest
from aidy.setup_detector import SETUP_TAXONOMY_VERSION

BASE_SHA = "0b413c23eb5b720bce227bb62ca35787855fb81d"
FIXTURE_TIME = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AIDY Day 46 paper simulator acceptance")
    parser.add_argument("--output-dir", default="day46_artifacts")
    return parser.parse_args()


def _context(index: int) -> dict[str, Any]:
    stamp = FIXTURE_TIME + timedelta(seconds=index)
    value: dict[str, Any] = {
        "context_packet_version": "aidy_market_context_v7_volatility_state",
        "as_of_utc": stamp.isoformat(),
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


def _decision(*, direction: str, evaluated_at: datetime) -> dict[str, Any]:
    long = direction == "long"
    return {
        "contract_version": MASTER_TRADER_CONTRACT_VERSION_V2,
        "action": "new_trade",
        "symbol": "XAUUSD",
        "evaluated_at_utc": evaluated_at.isoformat(),
        "valid_until_utc": (evaluated_at + timedelta(minutes=15)).isoformat(),
        "confidence": 0.71,
        "setup_taxonomy_version": SETUP_TAXONOMY_VERSION,
        "setup_codes": ["trend_pullback_long" if long else "trend_pullback_short"],
        "reason_codes": ["day46_acceptance_fixture"],
        "decision_summary": "Bounded fixture exercises the paper lifecycle without execution authority.",
        "target_decision_id": None,
        "direction": direction,
        "entry_type": "market",
        "market_reference_price": 2500.0,
        "stop_loss": 2480.0 if long else 2520.0,
        "targets": [2510.0, 2520.0, 2530.0] if long else [2490.0, 2480.0, 2470.0],
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
            "operator": "lt" if long else "gt",
            "value_type": "number",
            "value": 2490.0 if long else 2510.0,
        },
        "abstention_basis": None,
        "shadow_thesis": None,
        "shadow_direction": None,
        "shadow_horizon_minutes": None,
        "shadow_evaluation_condition": None,
    }


def _gate(
    stage: str,
    *,
    context_hash: str,
    evaluated_at: datetime,
    decision: dict[str, Any],
) -> dict[str, Any]:
    common: dict[str, Any] = {
        "gate_version": SAFETY_GATES_VERSION,
        "stage": stage,
        "status": "passed",
        "context_hash": context_hash,
        "checked_at_utc": (
            evaluated_at if stage == "pre_model" else evaluated_at + timedelta(seconds=1)
        ).isoformat(),
        "reason_codes": ["day46_acceptance_fixture"],
        "checks": [
            {
                "gate": "day46_fixture",
                "passed": True,
                "reason_code": "day46_fixture",
            }
        ],
    }
    if stage == "pre_model":
        common.update(
            {
                "model_call_allowed": True,
                "instruction_type": "market_evaluation",
                "max_context_age_seconds": 300,
            }
        )
    else:
        common.update(
            {
                "decision_admitted": True,
                "actionable": True,
                "decision_action": decision["action"],
                "downstream_action": decision["action"],
            }
        )
    common["gate_digest"] = compute_safety_gate_digest(common)
    return common


def _record(*, direction: str, index: int) -> dict[str, Any]:
    context = _context(index)
    evaluated_at = datetime.fromisoformat(str(context["as_of_utc"]))
    decision = _decision(direction=direction, evaluated_at=evaluated_at)
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
        "response_id": f"resp_day46_{index}",
        "provider_status": "completed",
        "provider_model": "gpt-5.6-sol",
        "usage": {"input_tokens": 10, "output_tokens": 10},
        "estimated_cost_usd": "0.000100",
        "pricing_version": "pricing_v1",
        "prompt_version": "aidy_master_trader_prompt_v1",
        "prompt_digest": "a" * 64,
        "model_id": "gpt-5.6-sol",
        "reasoning_effort": "medium",
    }
    repro = build_reproducibility_bundle(
        context=context,
        prompt_version="aidy_master_trader_prompt_v1",
        prompt_digest="a" * 64,
        gateway_version="aidy_openai_reasoning_gateway_v1",
        model_id="gpt-5.6-sol",
        strategy_version="aidy_strategy_config_v1",
        config_version="aidy_runtime_config_v1",
        sampling_metadata={
            "seed_supported": False,
            "seed": None,
            "temperature_supported": False,
            "temperature": None,
        },
        regime_state={"trend_structure": "known", "volatility_band": "normal"},
        setup_state={"candidate_setup_ids": decision["setup_codes"]},
        evidence_grade="exploratory",
        effective_n=4,
        evidence_report_digest="b" * 64,
        analogue_retrieval_version="aidy_analogue_retrieval_v2",
        analogue_retrieval_digest="c" * 64,
        analogue_case_ids=[f"case_day46_{index}"],
        selective_layer_state=None,
    )
    return build_ex_ante_evaluation_record(
        context=context,
        instruction_type="market_evaluation",
        cycle_disposition="decision_admitted",
        pre_model_receipt=_gate(
            "pre_model",
            context_hash=str(context["context_hash"]),
            evaluated_at=evaluated_at,
            decision=decision,
        ),
        gateway_result=gateway,
        post_model_receipt=_gate(
            "post_model",
            context_hash=str(context["context_hash"]),
            evaluated_at=evaluated_at,
            decision=decision,
        ),
        decision=decision,
        reproducibility_bundle=repro,
        data_quality_flags=context["data_quality"],
    )


def _observation(
    base_time: datetime,
    minutes: int,
    mid: float,
    *,
    context_mid: float | None,
) -> dict[str, Any]:
    stamp = base_time + timedelta(minutes=minutes)
    quote = {} if context_mid is None else {"mid": context_mid}
    return {
        "observation_version": PAPER_OBSERVATION_VERSION,
        "as_of_utc": stamp.isoformat(),
        "symbol": "XAUUSD",
        "mid": mid,
        "context": {
            "as_of_utc": stamp.isoformat(),
            "symbol": "XAUUSD",
            "gold": {"quote_context": quote},
        },
    }


def _run_long(record: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    base = datetime.fromisoformat(record["evaluated_at_utc"])
    observations = [
        _observation(base, 5, 2511.0, context_mid=2511.0),
        _observation(base, 10, 2505.0, context_mid=2488.0),
        _observation(base, 15, 2521.0, context_mid=2521.0),
        _observation(base, 20, 2531.0, context_mid=2531.0),
    ]
    direct = replay_paper_position(record, observations)

    restarted = start_paper_position(record)
    restarted = apply_paper_observation(restarted, observations[0])
    restarted = apply_paper_observation(restarted, observations[1])
    restored = restore_paper_state(serialize_paper_state(restarted))
    for observation in observations[2:]:
        restored = apply_paper_observation(restored, observation)
    return direct, direct == restored


def _run_short(record: dict[str, Any]) -> dict[str, Any]:
    base = datetime.fromisoformat(record["evaluated_at_utc"])
    observations = [
        _observation(base, 5, 2489.0, context_mid=2489.0),
        _observation(base, 10, 2521.0, context_mid=2512.0),
    ]
    return replay_paper_position(record, observations)


def build_artifacts(head_sha: str) -> dict[str, Any]:
    long_record = _record(direction="long", index=0)
    short_record = _record(direction="short", index=1)
    long_before = copy.deepcopy(long_record)
    short_before = copy.deepcopy(short_record)

    long_state, restart_identical = _run_long(long_record)
    short_state = _run_short(short_record)
    if not verify_paper_state(long_state) or not verify_paper_state(short_state):
        raise RuntimeError("Day 46 paper state verification failed.")

    long_attachment = build_paper_outcome_attachment(
        ex_ante_record=long_record,
        state=long_state,
        attached_at_utc=datetime.fromisoformat(long_state["closed_at_utc"])
        + timedelta(seconds=1),
    )
    short_attachment = build_paper_outcome_attachment(
        ex_ante_record=short_record,
        state=short_state,
        attached_at_utc=datetime.fromisoformat(short_state["closed_at_utc"])
        + timedelta(seconds=1),
    )
    attachments = [long_attachment, short_attachment]
    if not all(verify_outcome_attachment(item) for item in attachments):
        raise RuntimeError("Day 46 outcome attachment verification failed.")
    if long_record != long_before or short_record != short_before:
        raise RuntimeError("Day 46 mutated an ex-ante ledger record.")

    manifest = day46_manifest()
    positions = [long_state, short_state]
    summary: dict[str, Any] = {
        "ok": True,
        "base_sha": BASE_SHA,
        "head_sha": head_sha,
        "manifest_digest": manifest["manifest_digest"],
        "paper_position_count": len(positions),
        "long_final_state": long_state["position_state"],
        "long_realized_r": long_state["realized_r"],
        "long_thesis_status": long_state["invalidation"]["status"],
        "short_final_state": short_state["position_state"],
        "short_realized_r": short_state["realized_r"],
        "short_thesis_status": short_state["invalidation"]["status"],
        "restart_replay_byte_identical": restart_identical,
        "all_state_digests_valid": all(verify_paper_state(item) for item in positions),
        "outcome_attachment_count": len(attachments),
        "all_outcome_attachments_valid": all(
            verify_outcome_attachment(item) for item in attachments
        ),
        "ex_ante_records_unchanged": True,
        "economic_and_thesis_outcomes_separate": True,
        "pit_only_observation_contract": True,
        "paper_only": True,
        "execution_authority": False,
        "broker_access_used": False,
        "account_access_used": False,
        "follower_access_used": False,
        "telegram_action_used": False,
        "mt5_action_used": False,
        "formal_forward_evidence_created": False,
        "predictive_edge_claimed": False,
        "super_signals_modified": False,
    }
    summary["summary_digest"] = digest(summary)
    return {
        "manifest": manifest,
        "positions": positions,
        "attachments": attachments,
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
    _write(output / "positions.json", artifacts["positions"])
    _write(output / "attachments.json", artifacts["attachments"])
    _write(output / "summary.json", artifacts["summary"])
    print(canonical_json(artifacts["summary"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
