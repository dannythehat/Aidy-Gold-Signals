from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

from aidy import master_trader_contract as v1
from aidy.master_trader_contract_v2 import (
    MACHINE_CONDITION_VERSION,
    MASTER_TRADER_CONTRACT_VERSION_V2,
    evaluate_machine_condition,
    master_trader_contract_manifest_v2,
    master_trader_decision_digest_v2,
    master_trader_json_schema_v2,
    validate_master_trader_decision_v2,
    validate_master_trader_decision_versioned,
)
from aidy.setup_detector import SETUP_TAXONOMY_VERSION

BASE_SHA = "f1ea576be6c1ab57bf8f05845a2eab6bba8b055e"


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="day33_artifacts")
    return parser.parse_args()


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _condition(
    path: str,
    operator: str,
    value_type: str,
    value: object,
) -> dict[str, object]:
    return {
        "condition_version": MACHINE_CONDITION_VERSION,
        "field_path": path,
        "operator": operator,
        "value_type": value_type,
        "value": value,
    }


def _v1_record() -> dict[str, object]:
    return {
        "contract_version": v1.MASTER_TRADER_CONTRACT_VERSION,
        "action": "no_trade",
        "symbol": "XAUUSD",
        "evaluated_at_utc": "2026-09-01T01:00:00+00:00",
        "valid_until_utc": "2026-09-01T01:15:00+00:00",
        "confidence": 0.55,
        "setup_taxonomy_version": SETUP_TAXONOMY_VERSION,
        "setup_codes": [],
        "reason_codes": ["evidence_insufficient"],
        "decision_summary": "The accepted evidence remains insufficient for an actionable trade.",
        "target_decision_id": None,
        "direction": None,
        "entry_type": None,
        "market_reference_price": None,
        "stop_loss": None,
        "targets": [],
        "management_instruction": None,
        "new_stop_loss": None,
        "new_targets": [],
        "close_scope": None,
    }


def _base(action: str) -> dict[str, object]:
    record = _v1_record()
    record.update(
        {
            "contract_version": MASTER_TRADER_CONTRACT_VERSION_V2,
            "action": action,
            "thesis": None,
            "expected_horizon_minutes": None,
            "counter_argument": "Contrary evidence could still overturn the selected decision before expiry.",
            "invalidation_condition": None,
            "abstention_basis": None,
            "shadow_thesis": None,
            "shadow_direction": None,
            "shadow_horizon_minutes": None,
            "shadow_evaluation_condition": None,
        }
    )
    return record


def _new_trade() -> dict[str, object]:
    record = _base("new_trade")
    record.update(
        {
            "confidence": 0.72,
            "setup_codes": ["trend_pullback_long"],
            "reason_codes": ["trend_pullback_confirmed"],
            "decision_summary": "A confirmed long pullback setup supports a bounded market-entry decision.",
            "direction": "long",
            "entry_type": "market",
            "market_reference_price": 2500.0,
            "stop_loss": 2480.0,
            "targets": [2520.0, 2540.0],
            "thesis": "The accepted pullback should resume the higher-timeframe uptrend during the next session.",
            "expected_horizon_minutes": 240,
            "counter_argument": "A break below the pullback low would show that sellers regained control instead.",
            "invalidation_condition": _condition(
                "$.gold.quote_context.mid", "lt", "number", 2490.0
            ),
        }
    )
    return record


def _manage_trade() -> dict[str, object]:
    record = _base("manage_trade")
    record.update(
        {
            "reason_codes": ["structure_advanced"],
            "decision_summary": "Advanced structure justifies a defensive stop adjustment without changing size.",
            "target_decision_id": "aidy_dec_12345678",
            "management_instruction": "move_stop",
            "new_stop_loss": 2505.0,
            "thesis": "Holding above reclaimed structure should preserve the original long thesis while reducing downside.",
            "expected_horizon_minutes": 120,
            "counter_argument": "A volatility expansion could revisit the old stop region while the broader thesis survives.",
            "invalidation_condition": _condition(
                "$.gold.quote_context.mid", "lt", "number", 2500.0
            ),
        }
    )
    return record


def _close_trade() -> dict[str, object]:
    record = _base("close_trade")
    record.update(
        {
            "reason_codes": ["thesis_invalidated"],
            "decision_summary": "The pre-registered thesis invalidation has occurred and requires a full close.",
            "target_decision_id": "aidy_dec_12345678",
            "close_scope": "full",
            "thesis": "The original directional mechanism has failed and should not receive additional recovery time.",
            "expected_horizon_minutes": 30,
            "counter_argument": "The break may be a temporary liquidity sweep that reverses immediately after closure.",
            "invalidation_condition": _condition(
                "$.price_structure_context.reclaim_state", "eq", "text", "reclaimed"
            ),
        }
    )
    return record


def _no_trade() -> dict[str, object]:
    record = _base("no_trade")
    record.update(
        {
            "reason_codes": ["evidence_conflicted"],
            "decision_summary": "Conflicting evidence does not justify paying for directional exposure yet.",
            "counter_argument": "The long setup may resolve before all conflicts clear and leave opportunity behind.",
            "abstention_basis": "Trend evidence is constructive but current volatility and structure remain conflicted.",
            "shadow_thesis": "A reclaim of nearby structure would make the long continuation hypothesis testable without entry.",
            "shadow_direction": "long",
            "shadow_horizon_minutes": 240,
            "shadow_evaluation_condition": _condition(
                "$.price_structure_context.reclaim_state", "eq", "text", "reclaimed"
            ),
        }
    )
    return record


def build_artifacts(head_sha: str) -> dict[str, Any]:
    old = _v1_record()
    old_v1 = v1.validate_master_trader_decision(old)
    old_versioned = validate_master_trader_decision_versioned(old)
    if old_v1 != old_versioned:
        raise RuntimeError("Day 33 versioned reader changed a Day 20 V1 record.")
    if "thesis" in old_versioned:
        raise RuntimeError("Day 33 silently upgraded a V1 record.")

    decisions = {
        "new_trade": _new_trade(),
        "manage_trade": _manage_trade(),
        "close_trade": _close_trade(),
        "no_trade": _no_trade(),
    }
    normalized: dict[str, Any] = {}
    digests: dict[str, str] = {}
    for action, decision in decisions.items():
        result = validate_master_trader_decision_v2(decision)
        if result["action"] != action:
            raise RuntimeError(f"Day 33 action changed during validation: {action}")
        normalized[action] = result
        digests[action] = master_trader_decision_digest_v2(result)

    if len(set(digests.values())) != len(digests):
        raise RuntimeError("Day 33 representative decision digests must be distinct.")

    context = {
        "gold": {"quote_context": {"mid": 2488.0}},
        "price_structure_context": {"reclaim_state": "not_reclaimed"},
    }
    invalidation_result = evaluate_machine_condition(
        normalized["new_trade"]["invalidation_condition"], context
    )
    shadow_result = evaluate_machine_condition(
        normalized["no_trade"]["shadow_evaluation_condition"], context
    )
    unknown_result = evaluate_machine_condition(
        normalized["new_trade"]["invalidation_condition"], {"gold": {}}
    )
    if invalidation_result is not True or shadow_result is not False or unknown_result is not None:
        raise RuntimeError("Day 33 machine-condition evaluation semantics drifted.")

    schema = master_trader_json_schema_v2()
    if schema.get("additionalProperties") is not False:
        raise RuntimeError("Day 33 V2 schema must reject additional properties.")
    if set(schema["required"]) != set(schema["properties"]):
        raise RuntimeError("Day 33 V2 schema must require every declared field.")

    manifest = master_trader_contract_manifest_v2()
    if manifest["v1_records_version_readable"] is not True:
        raise RuntimeError("Day 33 V1 compatibility is not declared.")
    if manifest["v1_silent_upgrade_allowed"] is not False:
        raise RuntimeError("Day 33 must forbid silent V1 upgrades.")
    if manifest["gateway_promoted_by_day33"] is not False:
        raise RuntimeError("Day 33 must not silently promote the gateway.")

    summary = {
        "ok": True,
        "base_sha": BASE_SHA,
        "head_sha": head_sha,
        "contract_version": MASTER_TRADER_CONTRACT_VERSION_V2,
        "v1_contract_version": v1.MASTER_TRADER_CONTRACT_VERSION,
        "v1_record_readable": True,
        "v1_record_silently_upgraded": False,
        "representative_actions": sorted(normalized),
        "representative_decision_digests": digests,
        "machine_condition_true_proven": True,
        "machine_condition_false_proven": True,
        "machine_condition_unknown_proven": True,
        "counter_argument_required_for_all_actions": True,
        "actionable_invalidation_required": True,
        "no_trade_shadow_evaluation_required": True,
        "hidden_reasoning_trace_stored": False,
        "confidence_controls_position_size": False,
        "gateway_promoted_by_day33": False,
        "predictive_edge_claimed": False,
        "trading_gate_created": False,
        "accepted_prior_modules_modified": False,
        "super_signals_modified": False,
        "manifest_digest": manifest["manifest_digest"],
    }
    return {
        "manifest": manifest,
        "schema": schema,
        "representative_decisions": normalized,
        "summary": summary,
    }


def _write(path: Path, value: object) -> None:
    path.write_text(_canonical_json(value) + "\n", encoding="utf-8")


def main() -> None:
    args = _args()
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    head_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    artifacts = build_artifacts(head_sha)
    _write(output / "contract_manifest.json", artifacts["manifest"])
    _write(output / "structured_output_schema.json", artifacts["schema"])
    _write(output / "representative_decisions.json", artifacts["representative_decisions"])
    _write(output / "summary.json", artifacts["summary"])
    print(_canonical_json(artifacts["summary"]))


if __name__ == "__main__":
    main()
