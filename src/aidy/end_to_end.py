from __future__ import annotations

import copy
from collections.abc import Iterable, Mapping
from typing import Any

from aidy.context_composer_v2 import compose_context_v2, verify_context_dossier_v2
from aidy.decision_ledger import (
    build_ex_ante_evaluation_record,
    build_reproducibility_bundle,
    verify_ex_ante_record,
)
from aidy.end_to_end_store import END_TO_END_RUNTIME_VERSION, D1EndToEndCycleStore, digest
from aidy.management_contract_v2 import (
    build_management_action_record,
    verify_management_action_record,
)
from aidy.master_trader_contract_v2 import validate_master_trader_decision_versioned
from aidy.master_watcher import run_watch_cycle, verify_watcher_receipt
from aidy.paper_management_runtime import apply_management_to_paper_state
from aidy.paper_simulator import start_paper_position, verify_paper_state
from aidy.pit_reconstruction import normalize_as_of
from aidy.publication_ledger import D1PublicationLedgerStore, deliver_with_ledger
from aidy.safety_gates import DEFAULT_MAX_CONTEXT_AGE_SECONDS, evaluate_pre_model_safety
from aidy.self_consistency_ledger_v2 import (
    build_self_consistency_selective_layer_state_v2,
)
from aidy.self_consistency_v2 import (
    run_master_trader_self_consistency_v2,
    verify_self_consistency_result_v2,
)
from aidy.telegram_publisher import build_publication_envelope

DAY52_RESULT_VERSION = "aidy_end_to_end_result_v1"
DAY52_STRATEGY_VERSION = "aidy_architecture_v2_day52"


def _result(**values: Any) -> dict[str, Any]:
    payload = {
        "result_version": DAY52_RESULT_VERSION,
        "runtime_version": END_TO_END_RUNTIME_VERSION,
        "formal_forward_evidence": False,
        "broker_state_used": False,
        "follower_state_used": False,
        "super_signals_used": False,
        **values,
    }
    payload["result_digest"] = digest(payload)
    return payload


def _selected_case_ids(retrieval: Mapping[str, Any]) -> list[str]:
    matches = retrieval.get("matches")
    if not isinstance(matches, list):
        return []
    result: list[str] = []
    for item in matches:
        if isinstance(item, Mapping) and item.get("case_id") is not None:
            result.append(str(item["case_id"]))
    return result


def _representative_sample(self_consistency: Mapping[str, Any]) -> Mapping[str, Any] | None:
    consensus = self_consistency.get("consensus")
    receipts = self_consistency.get("sample_receipts")
    if not isinstance(consensus, Mapping) or not isinstance(receipts, list):
        return None
    index = consensus.get("representative_sample_index")
    if isinstance(index, bool) or not isinstance(index, int) or not 1 <= index <= len(receipts):
        return None
    sample = receipts[index - 1]
    return sample if isinstance(sample, Mapping) else None


def _gateway_snapshot_from_sample(sample: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "gateway_version": sample.get("gateway_version"),
        "status": sample.get("gateway_status"),
        "publication_allowed": sample.get("publication_allowed"),
        "failure_reason": sample.get("gateway_failure_reason"),
        "decision_digest": sample.get("decision_digest"),
        "request_digest": sample.get("request_digest"),
        "attempts": sample.get("attempts"),
        "latency_ms": sample.get("latency_ms"),
        "response_id": sample.get("response_id"),
        "provider_status": sample.get("provider_status"),
        "provider_model": sample.get("provider_model"),
        "usage": copy.deepcopy(sample.get("usage")),
        "estimated_cost_usd": sample.get("estimated_cost_usd"),
        "pricing_version": sample.get("pricing_version"),
        "prompt_version": sample.get("prompt_version"),
        "prompt_digest": sample.get("prompt_digest"),
        "model_id": sample.get("model_id"),
        "reasoning_effort": sample.get("reasoning_effort"),
    }


def _reproducibility(
    *,
    context: Mapping[str, Any],
    retrieval: Mapping[str, Any],
    evidence_report: Mapping[str, Any],
    setup_detection: Mapping[str, Any] | None,
    self_consistency: Mapping[str, Any],
    sample: Mapping[str, Any],
) -> dict[str, Any]:
    grade = evidence_report.get("dataset_grade")
    grade = grade if isinstance(grade, Mapping) else {}
    regime = context.get("regime")
    regime_state = copy.deepcopy(dict(regime)) if isinstance(regime, Mapping) else None
    selective = build_self_consistency_selective_layer_state_v2(self_consistency)
    return build_reproducibility_bundle(
        context=context,
        prompt_version=str(sample.get("prompt_version") or "") or None,
        prompt_digest=str(sample.get("prompt_digest") or "") or None,
        gateway_version=str(sample.get("gateway_version") or "") or None,
        model_id=str(sample.get("model_id") or "") or None,
        strategy_version=DAY52_STRATEGY_VERSION,
        config_version=str(self_consistency["frozen_config_digest"]),
        sampling_metadata={
            "seed_supported": False,
            "seed": None,
            "temperature_supported": False,
            "temperature": None,
        },
        regime_state=regime_state,
        setup_state=None if setup_detection is None else copy.deepcopy(dict(setup_detection)),
        evidence_grade=None if grade.get("grade") is None else str(grade.get("grade")),
        effective_n=int(evidence_report.get("effective_independent_n") or 0),
        evidence_report_digest=str(evidence_report.get("report_digest") or "") or None,
        analogue_retrieval_version=str(retrieval.get("retrieval_version") or "") or None,
        analogue_retrieval_digest=str(retrieval.get("retrieval_digest") or "") or None,
        analogue_case_ids=_selected_case_ids(retrieval),
        selective_layer_state=selective,
    )


def _build_ex_ante_from_consensus(
    *,
    context: Mapping[str, Any],
    instruction_type: str,
    pre_model_receipt: Mapping[str, Any],
    self_consistency: Mapping[str, Any],
    retrieval: Mapping[str, Any],
    evidence_report: Mapping[str, Any],
    setup_detection: Mapping[str, Any] | None,
) -> dict[str, Any]:
    sample = _representative_sample(self_consistency)
    consensus = self_consistency.get("consensus")
    if sample is None or not isinstance(consensus, Mapping):
        raise ValueError("No representative self-consistency decision exists.")
    raw = consensus.get("representative_decision")
    if not isinstance(raw, Mapping):
        raise TypeError("Representative decision is missing.")
    decision = validate_master_trader_decision_versioned(raw)
    gateway = _gateway_snapshot_from_sample(sample)
    post = sample.get("post_model_receipt")
    if not isinstance(post, Mapping):
        raise TypeError("Representative post-model receipt is missing.")
    repro = _reproducibility(
        context=context,
        retrieval=retrieval,
        evidence_report=evidence_report,
        setup_detection=setup_detection,
        self_consistency=self_consistency,
        sample=sample,
    )
    quality = context.get("data_quality")
    if not isinstance(quality, Mapping):
        raise TypeError("Current context has no data_quality mapping.")
    disposition = "no_trade" if decision["action"] == "no_trade" else "decision_admitted"
    record = build_ex_ante_evaluation_record(
        context=context,
        instruction_type=instruction_type,
        cycle_disposition=disposition,
        pre_model_receipt=pre_model_receipt,
        gateway_result=gateway,
        post_model_receipt=post,
        decision=decision,
        reproducibility_bundle=repro,
        data_quality_flags=quality,
    )
    if not verify_ex_ante_record(record):
        raise RuntimeError("Day 52 produced an invalid immutable ex-ante record.")
    return record


def _resume_is_fresh(record: Mapping[str, Any], context: Mapping[str, Any], now_utc: Any) -> bool:
    if record.get("context_hash") != context.get("context_hash"):
        return False
    try:
        now = normalize_as_of(now_utc)
        as_of = normalize_as_of(context.get("as_of_utc"))
        decision = record.get("decision")
        if not isinstance(decision, Mapping):
            return False
        valid_until = normalize_as_of(decision.get("valid_until_utc"))
    except (TypeError, ValueError):
        return False
    age = (now - as_of).total_seconds()
    return 0 <= age <= DEFAULT_MAX_CONTEXT_AGE_SECONDS and valid_until > now


async def _publish_record(
    *,
    cycle_id: str,
    record: Mapping[str, Any],
    context: Mapping[str, Any],
    source_state: str,
    publish_enabled: bool,
    chat_id: str,
    now_utc: Any,
    cycle_store: D1EndToEndCycleStore,
    publication_store: D1PublicationLedgerStore,
    transport: Any,
) -> dict[str, Any]:
    if source_state != "live_admitted" or not publish_enabled:
        await cycle_store.mark_state(cycle_id, "decision_admitted", now_utc=now_utc)
        return _result(
            cycle_id=cycle_id,
            status="decision_admitted_not_published",
            decision_id=record["decision_id"],
            publication_id=None,
            transport_called=False,
        )
    if not _resume_is_fresh(record, context, now_utc):
        await cycle_store.mark_state(
            cycle_id,
            "failed_closed",
            now_utc=now_utc,
            error_code="day52_publication_context_stale_or_expired",
        )
        return _result(
            cycle_id=cycle_id,
            status="failed_closed",
            reason_code="day52_publication_context_stale_or_expired",
            decision_id=record["decision_id"],
            publication_id=None,
            transport_called=False,
        )
    envelope = build_publication_envelope(
        ex_ante_record=record,
        chat_id=chat_id,
        source_state="live_admitted",
    )
    await cycle_store.link_publication(
        cycle_id,
        str(envelope["publication_id"]),
        now_utc=now_utc,
    )
    await cycle_store.mark_state(cycle_id, "publication_pending", now_utc=now_utc)
    delivery = await deliver_with_ledger(
        envelope,
        store=publication_store,
        transport=transport,
        now_utc=normalize_as_of(now_utc),
    )
    status = str(delivery["status"])
    if status in {"sent", "already_sent"}:
        await cycle_store.mark_state(cycle_id, "publication_sent", now_utc=now_utc)
    elif status in {"delivery_uncertain", "blocked"}:
        await cycle_store.mark_state(
            cycle_id,
            "publication_uncertain",
            now_utc=now_utc,
            error_code=str(delivery.get("error_code") or "delivery_uncertain"),
        )
    else:
        await cycle_store.mark_state(
            cycle_id,
            "failed_closed",
            now_utc=now_utc,
            error_code=str(delivery.get("error_code") or status),
        )
    return _result(
        cycle_id=cycle_id,
        status=status,
        decision_id=record["decision_id"],
        publication_id=envelope["publication_id"],
        message_digest=envelope["message_digest"],
        transport_called=bool(delivery.get("transport_called")),
        delivery_state=(delivery.get("delivery") or {}).get("delivery_state")
        if isinstance(delivery.get("delivery"), Mapping)
        else None,
    )


async def run_market_evaluation_cycle(
    *,
    context: Mapping[str, Any],
    aidy_state: Mapping[str, Any],
    retrieval: Mapping[str, Any],
    evidence_report: Mapping[str, Any],
    hypothesis_direction: str,
    setup_family: str | None,
    invalidation_inputs: Mapping[str, Any],
    setup_detection: Mapping[str, Any] | None,
    now_utc: Any,
    gateway: Any,
    cycle_store: D1EndToEndCycleStore,
    publication_store: D1PublicationLedgerStore,
    transport: Any,
    chat_id: str,
    source_state: str = "dry_run",
    publish_enabled: bool = False,
    seen_context_hashes: Iterable[str] = (),
) -> dict[str, Any]:
    context_hash = str(context.get("context_hash") or "")
    row = await cycle_store.register(
        instruction_type="market_evaluation",
        source_state=source_state,
        subject_id="market",
        context_hash=context_hash,
        now_utc=now_utc,
    )
    cycle_id = str(row["cycle_id"])

    existing = cycle_store.decode_artifact(row, "ex_ante_json")
    if existing is not None:
        if not verify_ex_ante_record(existing):
            await cycle_store.mark_state(
                cycle_id,
                "failed_closed",
                now_utc=now_utc,
                error_code="day52_stored_ex_ante_invalid",
            )
            return _result(
                cycle_id=cycle_id,
                status="failed_closed",
                reason_code="day52_stored_ex_ante_invalid",
            )
        decision = existing.get("decision")
        if isinstance(decision, Mapping) and decision.get("action") == "no_trade":
            return _result(
                cycle_id=cycle_id,
                status="no_trade",
                decision_id=existing["decision_id"],
                restarted=True,
                transport_called=False,
            )
        if row.get("cycle_state") == "publication_sent":
            return _result(
                cycle_id=cycle_id,
                status="already_sent",
                decision_id=existing["decision_id"],
                publication_id=row.get("publication_id"),
                restarted=True,
                transport_called=False,
            )
        if row.get("cycle_state") == "publication_uncertain":
            return _result(
                cycle_id=cycle_id,
                status="delivery_uncertain",
                decision_id=existing["decision_id"],
                publication_id=row.get("publication_id"),
                restarted=True,
                transport_called=False,
            )
        return await _publish_record(
            cycle_id=cycle_id,
            record=existing,
            context=context,
            source_state=source_state,
            publish_enabled=publish_enabled,
            chat_id=chat_id,
            now_utc=now_utc,
            cycle_store=cycle_store,
            publication_store=publication_store,
            transport=transport,
        )

    pre = evaluate_pre_model_safety(
        context,
        now_utc=now_utc,
        instruction_type="market_evaluation",
        seen_context_hashes=seen_context_hashes,
    )
    if pre["status"] != "passed":
        await cycle_store.mark_state(
            cycle_id,
            "pre_model_blocked",
            now_utc=now_utc,
            error_code=str(pre["reason_codes"][0]),
        )
        return _result(
            cycle_id=cycle_id,
            status="pre_model_blocked",
            reason_codes=copy.deepcopy(pre["reason_codes"]),
            model_call_count=0,
            transport_called=False,
        )

    dossier = compose_context_v2(
        context=context,
        aidy_state=aidy_state,
        retrieval=retrieval,
        evidence_report=evidence_report,
        hypothesis_direction=hypothesis_direction,
        setup_family=setup_family,
        invalidation_inputs=invalidation_inputs,
    )
    if not verify_context_dossier_v2(dossier):
        raise RuntimeError("Day 52 Context Composer V2 dossier failed verification.")
    sc = await run_master_trader_self_consistency_v2(
        gateway=gateway,
        evidence_bundle=dossier,
        context=context,
        pre_model_receipt=pre,
        now_utc=now_utc,
        setup_detection=setup_detection,
    )
    if not verify_self_consistency_result_v2(sc):
        raise RuntimeError("Day 52 V2 self-consistency result failed verification.")
    await cycle_store.record_self_consistency(cycle_id, sc, now_utc=now_utc)
    consensus = sc["consensus"]
    if consensus["status"] != "consensus" or consensus["representative_decision"] is None:
        await cycle_store.mark_state(cycle_id, "self_consistency_abstain", now_utc=now_utc)
        return _result(
            cycle_id=cycle_id,
            status="self_consistency_abstain",
            reason_code=consensus["reason_code"],
            model_call_count=3,
            transport_called=False,
        )

    record = _build_ex_ante_from_consensus(
        context=context,
        instruction_type="market_evaluation",
        pre_model_receipt=pre,
        self_consistency=sc,
        retrieval=retrieval,
        evidence_report=evidence_report,
        setup_detection=setup_detection,
    )
    await cycle_store.record_ex_ante(cycle_id, record, now_utc=now_utc)
    decision = record["decision"]
    if decision["action"] == "no_trade":
        await cycle_store.mark_state(cycle_id, "no_trade", now_utc=now_utc)
        return _result(
            cycle_id=cycle_id,
            status="no_trade",
            decision_id=record["decision_id"],
            model_call_count=3,
            transport_called=False,
        )
    if decision["action"] != "new_trade":
        await cycle_store.mark_state(
            cycle_id,
            "failed_closed",
            now_utc=now_utc,
            error_code="day52_market_action_not_new_trade",
        )
        return _result(
            cycle_id=cycle_id,
            status="failed_closed",
            reason_code="day52_market_action_not_new_trade",
            decision_id=record["decision_id"],
            transport_called=False,
        )

    paper = start_paper_position(record)
    await cycle_store.record_paper_state(cycle_id, paper, now_utc=now_utc)
    await cycle_store.mark_state(cycle_id, "paper_open", now_utc=now_utc)
    publication = await _publish_record(
        cycle_id=cycle_id,
        record=record,
        context=context,
        source_state=source_state,
        publish_enabled=publish_enabled,
        chat_id=chat_id,
        now_utc=now_utc,
        cycle_store=cycle_store,
        publication_store=publication_store,
        transport=transport,
    )
    publication["paper_state"] = paper
    publication["model_call_count"] = 3
    publication["result_digest"] = digest(
        {key: value for key, value in publication.items() if key != "result_digest"}
    )
    return publication


def _management_evidence_bundle(
    *,
    origin_ex_ante: Mapping[str, Any],
    paper_state: Mapping[str, Any],
    context: Mapping[str, Any],
    watcher_receipt: Mapping[str, Any],
    dossier: Mapping[str, Any],
) -> dict[str, Any]:
    origin = origin_ex_ante["decision"]
    observation = watcher_receipt["observation"]
    bundle = {
        "dossier_version": "aidy_management_runtime_bundle_v1",
        "instruction_type": "active_signal_management",
        "originating_decision": {
            "decision_id": origin_ex_ante["decision_id"],
            "direction": origin["direction"],
            "setup_codes": copy.deepcopy(origin["setup_codes"]),
            "thesis": origin["thesis"],
            "expected_horizon_minutes": origin["expected_horizon_minutes"],
            "counter_argument": origin["counter_argument"],
            "invalidation_condition": copy.deepcopy(origin["invalidation_condition"]),
        },
        "current_paper_position": {
            "position_id": paper_state["position_id"],
            "state_digest": paper_state["state_digest"],
            "position_state": paper_state["position_state"],
            "stop_loss": paper_state["stop_loss"],
            "targets": copy.deepcopy(paper_state["targets"]),
            "remaining_target_indices": copy.deepcopy(paper_state["remaining_target_indices"]),
        },
        "watcher_observation": copy.deepcopy(dict(observation)),
        "current_context": copy.deepcopy(dict(context)),
        "historical_dossier": copy.deepcopy(dict(dossier)),
        "boundaries": {
            "paper_only": True,
            "exact_target_decision_id_required": True,
            "original_thesis_mutation_allowed": False,
            "account_sizing_allowed": False,
            "execution_allowed": False,
        },
    }
    bundle["bundle_digest"] = digest(bundle)
    return bundle


async def run_management_cycle(
    *,
    origin_ex_ante: Mapping[str, Any],
    paper_state: Mapping[str, Any],
    context: Mapping[str, Any],
    retrieval: Mapping[str, Any],
    evidence_report: Mapping[str, Any],
    setup_family: str | None,
    invalidation_inputs: Mapping[str, Any],
    now_utc: Any,
    watcher_gateway: Any,
    management_gateway: Any,
    cycle_store: D1EndToEndCycleStore,
    publication_store: D1PublicationLedgerStore,
    transport: Any,
    chat_id: str,
    source_state: str = "dry_run",
    publish_enabled: bool = False,
    previous_watcher_receipts: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    if not verify_ex_ante_record(origin_ex_ante):
        raise ValueError("Management cycle requires a verified originating ex-ante record.")
    if not verify_paper_state(paper_state):
        raise ValueError("Management cycle requires a verified active paper state.")
    context_hash = str(context.get("context_hash") or "")
    subject_id = str(paper_state["position_id"])
    row = await cycle_store.register(
        instruction_type="active_signal_management",
        source_state=source_state,
        subject_id=subject_id,
        context_hash=context_hash,
        now_utc=now_utc,
    )
    cycle_id = str(row["cycle_id"])

    existing = cycle_store.decode_artifact(row, "ex_ante_json")
    if existing is not None:
        if row.get("cycle_state") == "publication_sent":
            return _result(
                cycle_id=cycle_id,
                status="already_sent",
                decision_id=existing["decision_id"],
                publication_id=row.get("publication_id"),
                restarted=True,
                transport_called=False,
            )
        if row.get("cycle_state") == "publication_uncertain":
            return _result(
                cycle_id=cycle_id,
                status="delivery_uncertain",
                decision_id=existing["decision_id"],
                publication_id=row.get("publication_id"),
                restarted=True,
                transport_called=False,
            )
        decision = existing.get("decision")
        if isinstance(decision, Mapping) and decision.get("action") == "no_trade":
            return _result(
                cycle_id=cycle_id,
                status="no_trade",
                decision_id=existing["decision_id"],
                restarted=True,
                transport_called=False,
            )
        return await _publish_record(
            cycle_id=cycle_id,
            record=existing,
            context=context,
            source_state=source_state,
            publish_enabled=publish_enabled,
            chat_id=chat_id,
            now_utc=now_utc,
            cycle_store=cycle_store,
            publication_store=publication_store,
            transport=transport,
        )

    origin_decision = origin_ex_ante["decision"]
    watcher_state = {
        "paper_position_id": paper_state["position_id"],
        "paper_state_digest": paper_state["state_digest"],
    }
    watcher_dossier = compose_context_v2(
        context=context,
        aidy_state=watcher_state,
        retrieval=retrieval,
        evidence_report=evidence_report,
        hypothesis_direction=str(origin_decision["direction"]),
        setup_family=setup_family,
        invalidation_inputs=invalidation_inputs,
    )
    watcher = await run_watch_cycle(
        ex_ante_record=origin_ex_ante,
        paper_state=paper_state,
        current_context=context,
        historical_dossier=watcher_dossier,
        now_utc=now_utc,
        gateway=watcher_gateway,
        previous_receipts=previous_watcher_receipts,
    )
    if not verify_watcher_receipt(watcher):
        raise RuntimeError("Day 52 watcher receipt failed verification.")
    await cycle_store.record_watcher_receipt(cycle_id, watcher, now_utc=now_utc)
    if watcher["status"] != "observed":
        await cycle_store.mark_state(cycle_id, "watcher_no_action", now_utc=now_utc)
        return _result(
            cycle_id=cycle_id,
            status="watcher_no_action",
            watcher_status=watcher["status"],
            watcher_reason_codes=copy.deepcopy(watcher["reason_codes"]),
            management_model_call_count=0,
            transport_called=False,
        )
    observation = watcher["observation"]
    if observation["assessment"] == "hold":
        await cycle_store.mark_state(cycle_id, "watcher_no_action", now_utc=now_utc)
        return _result(
            cycle_id=cycle_id,
            status="watcher_hold",
            watcher_receipt_digest=watcher["receipt_digest"],
            management_model_call_count=0,
            transport_called=False,
        )

    pre = evaluate_pre_model_safety(
        context,
        now_utc=now_utc,
        instruction_type="active_signal_management",
    )
    if pre["status"] != "passed":
        await cycle_store.mark_state(
            cycle_id,
            "pre_model_blocked",
            now_utc=now_utc,
            error_code=str(pre["reason_codes"][0]),
        )
        return _result(
            cycle_id=cycle_id,
            status="pre_model_blocked",
            reason_codes=copy.deepcopy(pre["reason_codes"]),
            management_model_call_count=0,
            transport_called=False,
        )

    management_bundle = _management_evidence_bundle(
        origin_ex_ante=origin_ex_ante,
        paper_state=paper_state,
        context=context,
        watcher_receipt=watcher,
        dossier=watcher_dossier,
    )
    sc = await run_master_trader_self_consistency_v2(
        gateway=management_gateway,
        evidence_bundle=management_bundle,
        context=context,
        pre_model_receipt=pre,
        now_utc=now_utc,
        setup_detection=None,
    )
    await cycle_store.record_self_consistency(cycle_id, sc, now_utc=now_utc)
    consensus = sc["consensus"]
    if consensus["status"] != "consensus" or consensus["representative_decision"] is None:
        await cycle_store.mark_state(cycle_id, "self_consistency_abstain", now_utc=now_utc)
        return _result(
            cycle_id=cycle_id,
            status="self_consistency_abstain",
            reason_code=consensus["reason_code"],
            management_model_call_count=3,
            transport_called=False,
        )

    decision = validate_master_trader_decision_versioned(consensus["representative_decision"])
    if decision["action"] == "no_trade":
        management_record = _build_ex_ante_from_consensus(
            context=context,
            instruction_type="active_signal_management",
            pre_model_receipt=pre,
            self_consistency=sc,
            retrieval=retrieval,
            evidence_report=evidence_report,
            setup_detection=None,
        )
        await cycle_store.record_ex_ante(cycle_id, management_record, now_utc=now_utc)
        await cycle_store.mark_state(cycle_id, "no_trade", now_utc=now_utc)
        return _result(
            cycle_id=cycle_id,
            status="no_trade",
            decision_id=management_record["decision_id"],
            management_model_call_count=3,
            transport_called=False,
        )

    action_record = build_management_action_record(
        decision=decision,
        watcher_receipt=watcher,
        ex_ante_record=origin_ex_ante,
        paper_state=paper_state,
        current_context=context,
    )
    if not verify_management_action_record(action_record):
        raise RuntimeError("Day 52 management action failed Day-48 verification.")
    await cycle_store.record_management_action(cycle_id, action_record, now_utc=now_utc)

    management_record = _build_ex_ante_from_consensus(
        context=context,
        instruction_type="active_signal_management",
        pre_model_receipt=pre,
        self_consistency=sc,
        retrieval=retrieval,
        evidence_report=evidence_report,
        setup_detection=None,
    )
    await cycle_store.record_ex_ante(cycle_id, management_record, now_utc=now_utc)
    await cycle_store.mark_state(cycle_id, "management_admitted", now_utc=now_utc)

    quote = context.get("gold")
    quote = quote.get("quote_context") if isinstance(quote, Mapping) else None
    current_mid = quote.get("mid") if isinstance(quote, Mapping) else None
    next_state = apply_management_to_paper_state(
        paper_state,
        action_record,
        observed_at_utc=now_utc,
        current_mid=current_mid,
    )
    publication = await _publish_record(
        cycle_id=cycle_id,
        record=management_record,
        context=context,
        source_state=source_state,
        publish_enabled=publish_enabled,
        chat_id=chat_id,
        now_utc=now_utc,
        cycle_store=cycle_store,
        publication_store=publication_store,
        transport=transport,
    )
    publication["management_action_id"] = action_record["management_action_id"]
    publication["management_action_digest"] = action_record["ledger_digest"]
    publication["next_paper_state"] = next_state
    publication["watcher_receipt_digest"] = watcher["receipt_digest"]
    publication["management_model_call_count"] = 3
    publication["result_digest"] = digest(
        {key: value for key, value in publication.items() if key != "result_digest"}
    )
    return publication


def day52_runtime_manifest() -> dict[str, Any]:
    manifest: dict[str, Any] = {
        "manifest_version": "aidy_day52_end_to_end_manifest_v1",
        "runtime_version": END_TO_END_RUNTIME_VERSION,
        "market_path": [
            "pit_context",
            "context_composer_v2",
            "k3_master_trader_v2",
            "deterministic_safety",
            "immutable_ex_ante_ledger",
            "paper_simulator",
            "telegram_envelope",
            "durable_publication_ledger",
        ],
        "management_path": [
            "fresh_pit_context",
            "context_composer_v2",
            "master_watcher",
            "k3_master_trader_v2",
            "day48_management_validation",
            "immutable_management_ex_ante_ledger",
            "paper_management_runtime",
            "telegram_envelope",
            "durable_publication_ledger",
        ],
        "restart_reuses_exact_ex_ante_record": True,
        "restart_reuses_exact_publication_identity": True,
        "shadow_replay_can_publish": False,
        "no_trade_can_publish": False,
        "self_consistency_abstain_creates_fake_no_trade": False,
        "stale_resume_can_publish": False,
        "broker_or_account_state_allowed": False,
        "follower_state_allowed": False,
        "super_signals_dependency_allowed": False,
        "formal_forward_evidence_created": False,
        "day53_automatically_started": False,
    }
    manifest["manifest_digest"] = digest(manifest)
    return manifest