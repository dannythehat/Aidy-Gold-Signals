from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from aidy.context_packet import compute_context_hash
from aidy.decision_ledger import (
    CYCLE_DISPOSITIONS,
    DECISION_LEDGER_VERSION,
    EX_ANTE_RECORD_VERSION,
    OUTCOME_ATTACHMENT_VERSION,
    build_ex_ante_evaluation_record,
    build_outcome_attachment,
    build_reproducibility_bundle,
    canonical_json,
    decision_ledger_manifest,
    reconstruct_non_secret_decision_bundle,
    reconcile_ex_ante_record,
    reconcile_outcome_attachment,
    verify_ex_ante_record,
    verify_outcome_attachment,
    verify_reproducibility_bundle,
)
from aidy.master_trader_contract import MASTER_TRADER_CONTRACT_VERSION
from aidy.master_trader_contract_v2 import (
    MACHINE_CONDITION_VERSION,
    MASTER_TRADER_CONTRACT_VERSION_V2,
    master_trader_decision_digest_versioned,
)
from aidy.safety_gates import SAFETY_GATES_VERSION, compute_safety_gate_digest
from aidy.setup_detector import SETUP_TAXONOMY_VERSION

NOW = datetime(2026, 9, 1, 2, 30, tzinfo=UTC)


def _context() -> dict[str, object]:
    value: dict[str, object] = {
        "context_packet_version": "aidy_market_context_v7_volatility_state",
        "as_of_utc": NOW.isoformat(),
        "symbol": "XAUUSD",
        "objective_only": True,
        "retrospective_history_included": False,
        "broker_follower_state_included": False,
        "source_contract_versions": {
            "pit_query": "aidy_pit_query_v1",
            "gold_features": "aidy_gold_features_v1",
        },
        "data_quality": {
            "state": "known",
            "unknown_is_not_absent": True,
            "quote_freshness": "fresh",
        },
        "gold": {"quote_context": {"mid": "2488.20"}},
    }
    value["context_hash"] = compute_context_hash(value)
    return value


def _gate(stage: str, *, passed: bool, context_hash: str) -> dict[str, object]:
    value: dict[str, object] = {
        "gate_version": SAFETY_GATES_VERSION,
        "stage": stage,
        "status": "passed" if passed else "blocked",
        "context_hash": context_hash,
        "checked_at_utc": NOW.isoformat(),
        "reason_codes": [f"{stage}_{'allowed' if passed else 'blocked'}"],
        "checks": [{"gate": "fixture", "passed": passed, "reason_code": "fixture"}],
    }
    if stage == "pre_model":
        value["model_call_allowed"] = passed
        value["instruction_type"] = "market_evaluation"
        value["max_context_age_seconds"] = 300
    else:
        value["decision_admitted"] = passed
        value["actionable"] = False
        value["decision_action"] = None
        value["downstream_action"] = None
    value["gate_digest"] = compute_safety_gate_digest(value)
    return value


def _base_v1(action: str) -> dict[str, object]:
    return {
        "contract_version": MASTER_TRADER_CONTRACT_VERSION,
        "action": action,
        "symbol": "XAUUSD",
        "evaluated_at_utc": NOW.isoformat(),
        "valid_until_utc": (NOW + timedelta(minutes=15)).isoformat(),
        "confidence": 0.75,
        "setup_taxonomy_version": SETUP_TAXONOMY_VERSION,
        "setup_codes": [],
        "reason_codes": ["evidence_supportive"],
        "decision_summary": "Accepted bounded evidence supports this decision.",
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


def _no_trade_v1() -> dict[str, object]:
    value = _base_v1("no_trade")
    value["reason_codes"] = ["evidence_insufficient"]
    return value


def _new_trade_v1() -> dict[str, object]:
    value = _base_v1("new_trade")
    value.update(
        {
            "setup_codes": ["trend_pullback_long"],
            "direction": "long",
            "entry_type": "market",
            "market_reference_price": 2488.2,
            "stop_loss": 2478.0,
            "targets": [2498.0, 2508.0],
        }
    )
    return value


def _condition(path: str = "$.gold.quote_context.mid") -> dict[str, object]:
    return {
        "condition_version": MACHINE_CONDITION_VERSION,
        "field_path": path,
        "operator": "lte",
        "value_type": "number",
        "value": 2478.0,
    }


def _v2_no_trade() -> dict[str, object]:
    value = _no_trade_v1()
    value["contract_version"] = MASTER_TRADER_CONTRACT_VERSION_V2
    value.update(
        {
            "thesis": None,
            "expected_horizon_minutes": None,
            "counter_argument": "A clean continuation could still emerge after the current uncertainty clears.",
            "invalidation_condition": None,
            "abstention_basis": "Evidence quality is incomplete and does not justify taking exposure now.",
            "shadow_thesis": "A sustained break higher would support the bullish continuation hypothesis without exposure.",
            "shadow_direction": "long",
            "shadow_horizon_minutes": 120,
            "shadow_evaluation_condition": {
                "condition_version": MACHINE_CONDITION_VERSION,
                "field_path": "$.gold.quote_context.mid",
                "operator": "gte",
                "value_type": "number",
                "value": 2500.0,
            },
        }
    )
    return value


def _repro(context: dict[str, object], *, prompt: str | None = "aidy_master_trader_prompt_v1") -> dict[str, object]:
    return build_reproducibility_bundle(
        context=context,
        prompt_version=prompt,
        prompt_digest=None if prompt is None else "a" * 64,
        gateway_version=None if prompt is None else "aidy_openai_reasoning_gateway_v1",
        model_id=None if prompt is None else "gpt-5.6-sol",
        strategy_version="aidy_strategy_config_v1",
        config_version="aidy_runtime_config_v1",
        sampling_metadata={
            "seed_supported": False,
            "seed": None,
            "temperature_supported": False,
            "temperature": None,
        },
        regime_state={"trend_structure": "uptrend", "volatility_band": "normal"},
        setup_state={"candidate_setup_ids": ["trend_pullback_long"]},
        evidence_grade="exploratory",
        effective_n=7,
        evidence_report_digest="b" * 64,
        analogue_retrieval_version="aidy_analogue_retrieval_v2",
        analogue_retrieval_digest="c" * 64,
        analogue_case_ids=["case_20260801", "case_20260714"],
        selective_layer_state=None,
    )


def _gateway(decision: dict[str, object] | None, *, accepted: bool = True) -> dict[str, object]:
    return {
        "gateway_version": "aidy_openai_reasoning_gateway_v1",
        "status": "accepted" if accepted else "failed_closed",
        "publication_allowed": accepted,
        "failure_reason": None if accepted else "api_transport_error",
        "structured_decision": decision,
        "decision_digest": None if decision is None else master_trader_decision_digest_versioned(decision),
        "request_digest": "d" * 64,
        "attempts": 1,
        "latency_ms": 10,
        "response_id": "resp_1234",
        "provider_status": "completed" if accepted else None,
        "provider_model": "gpt-5.6-sol",
        "usage": {"input_tokens": 100, "output_tokens": 50},
        "estimated_cost_usd": "0.001000",
        "pricing_version": "pricing_v1",
        "prompt_version": "aidy_master_trader_prompt_v1",
        "prompt_digest": "a" * 64,
        "model_id": "gpt-5.6-sol",
        "reasoning_effort": "medium",
    }


def _record(disposition: str, *, decision: dict[str, object] | None = None) -> dict[str, object]:
    context = _context()
    pre = _gate("pre_model", passed=disposition != "pre_model_blocked", context_hash=str(context["context_hash"]))
    if disposition == "pre_model_blocked":
        gateway = None
        post = None
        repro = _repro(context, prompt=None)
    elif disposition == "model_failed":
        gateway = _gateway(None, accepted=False)
        post = None
        repro = _repro(context)
    else:
        if decision is None:
            decision = _no_trade_v1() if disposition == "no_trade" else _new_trade_v1()
        gateway = _gateway(decision)
        post = _gate("post_model", passed=disposition in {"no_trade", "decision_admitted"}, context_hash=str(context["context_hash"]))
        post["decision_action"] = decision["action"]
        post["actionable"] = disposition == "decision_admitted"
        post["downstream_action"] = "no_action" if disposition == "no_trade" else decision["action"] if disposition == "decision_admitted" else None
        post["gate_digest"] = compute_safety_gate_digest(post)
        repro = _repro(context)
    return build_ex_ante_evaluation_record(
        context=context,
        instruction_type="market_evaluation",
        cycle_disposition=disposition,
        pre_model_receipt=pre,
        gateway_result=gateway,
        post_model_receipt=post,
        decision=decision,
        reproducibility_bundle=repro,
        data_quality_flags=context["data_quality"],
    )


def test_manifest_freezes_non_mutation_and_separation_boundaries():
    manifest = decision_ledger_manifest()
    assert manifest["ledger_version"] == DECISION_LEDGER_VERSION
    assert manifest["ex_ante_mutation_allowed"] is False
    assert manifest["outcome_attachment_mutates_ex_ante"] is False
    assert manifest["future_outcomes_allowed_in_ex_ante"] is False
    assert manifest["hidden_reasoning_stored"] is False
    assert manifest["secrets_stored"] is False
    assert manifest["gateway_promoted_by_day34"] is False
    assert manifest["trading_gate_created_by_day34"] is False


@pytest.mark.parametrize("disposition", CYCLE_DISPOSITIONS)
def test_every_cycle_disposition_is_a_first_class_immutable_record(disposition: str):
    record = _record(disposition)
    assert record["record_version"] == EX_ANTE_RECORD_VERSION
    assert record["cycle_disposition"] == disposition
    assert str(record["evaluation_id"]).startswith("aidy_eval_")
    assert str(record["decision_id"]).startswith("aidy_dec_")
    assert verify_ex_ante_record(record)


def test_no_trade_and_actionable_decisions_remain_distinct():
    no_trade = _record("no_trade")
    action = _record("decision_admitted")
    assert no_trade["decision"]["action"] == "no_trade"
    assert action["decision"]["action"] == "new_trade"
    assert no_trade["cycle_disposition"] != action["cycle_disposition"]


def test_v2_falsifiable_metadata_is_retained_without_gateway_promotion():
    record = _record("post_model_blocked", decision=_v2_no_trade())
    falsifiable = record["falsifiable_thesis"]
    assert falsifiable["counter_argument"]
    assert falsifiable["abstention_basis"]
    assert falsifiable["shadow_thesis"]
    assert falsifiable["shadow_evaluation_condition"]["condition_version"] == MACHINE_CONDITION_VERSION
    assert decision_ledger_manifest()["gateway_promoted_by_day34"] is False


def test_v1_record_has_no_invented_v2_thesis():
    record = _record("no_trade")
    assert record["decision"]["contract_version"] == MASTER_TRADER_CONTRACT_VERSION
    assert record["falsifiable_thesis"] is None


def test_context_snapshot_and_hash_round_trip_exactly():
    record = _record("no_trade")
    assert record["context_snapshot"] == _context()
    assert record["context_hash"] == record["context_snapshot"]["context_hash"]


def test_reproducibility_bundle_preserves_exact_ranked_analogue_ids():
    record = _record("no_trade")
    assert record["reproducibility_bundle"]["analogue_case_ids"] == [
        "case_20260801",
        "case_20260714",
    ]
    assert record["reproducibility_bundle"]["effective_n"] == 7
    assert record["reproducibility_bundle"]["evidence_grade"] == "exploratory"


def test_reproducibility_bundle_rejects_duplicate_analogue_ids():
    context = _context()
    with pytest.raises(ValueError, match="duplicates"):
        build_reproducibility_bundle(
            context=context,
            prompt_version=None,
            prompt_digest=None,
            gateway_version=None,
            model_id=None,
            strategy_version="strategy_v1",
            config_version="config_v1",
            sampling_metadata={"seed_supported": False, "seed": None, "temperature_supported": False, "temperature": None},
            regime_state=None,
            setup_state=None,
            evidence_grade=None,
            effective_n=None,
            evidence_report_digest=None,
            analogue_retrieval_version=None,
            analogue_retrieval_digest=None,
            analogue_case_ids=["case_1", "case_1"],
        )


def test_reproducibility_bundle_digest_detects_tampering():
    bundle = _repro(_context())
    assert verify_reproducibility_bundle(bundle)
    bundle["effective_n"] = 99
    assert not verify_reproducibility_bundle(bundle)


def test_sampling_unsupported_fields_must_stay_null():
    context = _context()
    with pytest.raises(ValueError, match="seed must be null"):
        build_reproducibility_bundle(
            context=context,
            prompt_version=None,
            prompt_digest=None,
            gateway_version=None,
            model_id=None,
            strategy_version="strategy_v1",
            config_version="config_v1",
            sampling_metadata={"seed_supported": False, "seed": 7, "temperature_supported": False, "temperature": None},
            regime_state=None,
            setup_state=None,
            evidence_grade=None,
            effective_n=None,
            evidence_report_digest=None,
            analogue_retrieval_version=None,
            analogue_retrieval_digest=None,
        )


def test_duplicate_identical_evaluation_is_idempotent():
    first = _record("no_trade")
    second = deepcopy(first)
    assert reconcile_ex_ante_record(first, second) == first


def test_ex_ante_mutation_fails_closed():
    first = _record("no_trade")
    changed = deepcopy(first)
    changed["data_quality_flags"]["quote_freshness"] = "stale"
    changed.pop("ex_ante_digest")
    from aidy.decision_ledger import digest

    changed["ex_ante_digest"] = digest(changed)
    with pytest.raises(ValueError, match="mutation"):
        reconcile_ex_ante_record(first, changed)


def test_ex_ante_digest_tamper_is_detected():
    record = _record("no_trade")
    record["context_snapshot"]["symbol"] = "EURUSD"
    assert not verify_ex_ante_record(record)


@pytest.mark.parametrize("field", ["future_evaluation", "realized_pnl", "mfe", "outcome_state"])
def test_future_outcome_fields_are_forbidden_in_ex_ante_context(field: str):
    context = _context()
    context[field] = "future"
    context["context_hash"] = compute_context_hash(context)
    repro = _repro(context)
    pre = _gate("pre_model", passed=False, context_hash=str(context["context_hash"]))
    with pytest.raises(ValueError, match="Future/outcome"):
        build_ex_ante_evaluation_record(
            context=context,
            instruction_type="market_evaluation",
            cycle_disposition="pre_model_blocked",
            pre_model_receipt=pre,
            gateway_result=None,
            post_model_receipt=None,
            decision=None,
            reproducibility_bundle=repro,
            data_quality_flags=context["data_quality"],
        )


@pytest.mark.parametrize("field", ["api_key", "private_key", "chain_of_thought", "scratchpad"])
def test_secrets_and_hidden_reasoning_are_forbidden_in_ex_ante_metadata(field: str):
    context = _context()
    context["data_quality"][field] = "secret"
    context["context_hash"] = compute_context_hash(context)
    with pytest.raises(ValueError, match="forbidden"):
        _repro(context)


def test_invalid_context_hash_is_rejected():
    context = _context()
    context["context_hash"] = "0" * 64
    with pytest.raises(ValueError, match="Context hash"):
        _repro(context)


def test_model_failed_cannot_smuggle_decision_state():
    context = _context()
    pre = _gate("pre_model", passed=True, context_hash=str(context["context_hash"]))
    with pytest.raises(ValueError, match="model_failed"):
        build_ex_ante_evaluation_record(
            context=context,
            instruction_type="market_evaluation",
            cycle_disposition="model_failed",
            pre_model_receipt=pre,
            gateway_result=_gateway(None, accepted=False),
            post_model_receipt=None,
            decision=_no_trade_v1(),
            reproducibility_bundle=_repro(context),
            data_quality_flags=context["data_quality"],
        )


def test_pre_model_blocked_cannot_smuggle_gateway_state():
    context = _context()
    pre = _gate("pre_model", passed=False, context_hash=str(context["context_hash"]))
    with pytest.raises(ValueError, match="cannot contain"):
        build_ex_ante_evaluation_record(
            context=context,
            instruction_type="market_evaluation",
            cycle_disposition="pre_model_blocked",
            pre_model_receipt=pre,
            gateway_result=_gateway(None, accepted=False),
            post_model_receipt=None,
            decision=None,
            reproducibility_bundle=_repro(context),
            data_quality_flags=context["data_quality"],
        )


def test_reconstructed_bundle_contains_exact_non_secret_inputs_and_no_outcome():
    record = _record("no_trade")
    bundle = reconstruct_non_secret_decision_bundle(record)
    assert bundle["evaluation_id"] == record["evaluation_id"]
    assert bundle["context_snapshot"] == record["context_snapshot"]
    assert bundle["reproducibility_bundle"] == record["reproducibility_bundle"]
    assert "outcome_payload" not in canonical_json(bundle)


def test_shadow_outcome_attaches_only_to_no_trade_and_is_structurally_separate():
    record = _record("no_trade")
    original = deepcopy(record)
    attachment = build_outcome_attachment(
        ex_ante_record=record,
        attachment_type="shadow_outcome",
        attached_at_utc=NOW + timedelta(hours=2),
        outcome_contract_version="aidy_no_trade_shadow_outcome_v1",
        outcome_identity="shadow_case_001",
        outcome_payload={"path_class": "up", "mfe": "12.4", "mae": "3.1"},
    )
    assert attachment["attachment_version"] == OUTCOME_ATTACHMENT_VERSION
    assert attachment["ex_ante_digest"] == record["ex_ante_digest"]
    assert record == original
    assert verify_outcome_attachment(attachment)


def test_trade_outcome_attaches_only_to_actionable_admitted_decision():
    record = _record("decision_admitted")
    attachment = build_outcome_attachment(
        ex_ante_record=record,
        attachment_type="trade_outcome",
        attached_at_utc=NOW + timedelta(hours=4),
        outcome_contract_version="aidy_trade_outcome_v1",
        outcome_identity="trade_case_001",
        outcome_payload={"outcome_state": "target_hit", "realized_pnl": "1.2R"},
    )
    assert verify_outcome_attachment(attachment)


def test_shadow_outcome_rejected_for_actionable_decision():
    with pytest.raises(ValueError, match="no_trade"):
        build_outcome_attachment(
            ex_ante_record=_record("decision_admitted"),
            attachment_type="shadow_outcome",
            attached_at_utc=NOW + timedelta(hours=1),
            outcome_contract_version="shadow_v1",
            outcome_identity="shadow_001",
            outcome_payload={"outcome_state": "flat"},
        )


def test_trade_outcome_rejected_for_blocked_cycle():
    with pytest.raises(ValueError, match="admitted actionable"):
        build_outcome_attachment(
            ex_ante_record=_record("model_failed"),
            attachment_type="trade_outcome",
            attached_at_utc=NOW + timedelta(hours=1),
            outcome_contract_version="trade_v1",
            outcome_identity="trade_001",
            outcome_payload={"outcome_state": "unknown"},
        )


def test_outcome_attachment_must_be_later_than_evaluation():
    with pytest.raises(ValueError, match="after"):
        build_outcome_attachment(
            ex_ante_record=_record("no_trade"),
            attachment_type="shadow_outcome",
            attached_at_utc=NOW,
            outcome_contract_version="shadow_v1",
            outcome_identity="shadow_001",
            outcome_payload={"outcome_state": "flat"},
        )


def test_duplicate_identical_outcome_attachment_is_idempotent():
    record = _record("no_trade")
    attachment = build_outcome_attachment(
        ex_ante_record=record,
        attachment_type="shadow_outcome",
        attached_at_utc=NOW + timedelta(hours=1),
        outcome_contract_version="shadow_v1",
        outcome_identity="shadow_001",
        outcome_payload={"outcome_state": "up"},
    )
    assert reconcile_outcome_attachment(attachment, deepcopy(attachment)) == attachment


def test_conflicting_outcome_attachment_fails_closed():
    record = _record("no_trade")
    first = build_outcome_attachment(
        ex_ante_record=record,
        attachment_type="shadow_outcome",
        attached_at_utc=NOW + timedelta(hours=1),
        outcome_contract_version="shadow_v1",
        outcome_identity="shadow_001",
        outcome_payload={"outcome_state": "up"},
    )
    changed = deepcopy(first)
    changed["outcome_payload"]["outcome_state"] = "down"
    changed.pop("attachment_digest")
    from aidy.decision_ledger import digest

    changed["attachment_digest"] = digest(changed)
    with pytest.raises(ValueError, match="Conflicting"):
        reconcile_outcome_attachment(first, changed)


def test_outcome_payload_still_rejects_secrets_and_hidden_reasoning():
    record = _record("no_trade")
    with pytest.raises(ValueError, match="Secret-bearing"):
        build_outcome_attachment(
            ex_ante_record=record,
            attachment_type="shadow_outcome",
            attached_at_utc=NOW + timedelta(hours=1),
            outcome_contract_version="shadow_v1",
            outcome_identity="shadow_001",
            outcome_payload={"api_key": "sk-secret", "outcome_state": "up"},
        )
