from __future__ import annotations

import copy
import runpy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from aidy.end_to_end import run_management_cycle
from aidy.master_trader_contract_v2 import MASTER_TRADER_CONTRACT_VERSION_V2
from aidy.master_watcher import (
    WATCHER_GATEWAY_VERSION,
    WATCHER_MODEL_ID,
    WATCHER_OBSERVATION_VERSION,
    WATCHER_PROMPT_VERSION,
    WATCHER_REASONING_EFFORT,
    digest as watcher_digest,
    watcher_observation_digest,
)
from aidy.paper_simulator import verify_paper_state
from aidy.telegram_publisher import SimulatedTelegramTransport

ROOT = Path(__file__).resolve().parents[1]
MARKET = runpy.run_path(str(ROOT / "tests" / "test_day52_end_to_end.py"))
BASE = datetime(2026, 9, 1, 16, 0, tzinfo=UTC)
CHAT_ID = "-1001234567890"


class FixedWatcherGateway:
    def __init__(
        self,
        *,
        assessment: str,
        thesis_assessment: str,
        reason_code: str,
    ) -> None:
        self.assessment = assessment
        self.thesis_assessment = thesis_assessment
        self.reason_code = reason_code
        self.calls = 0

    async def evaluate(self, evidence_bundle):
        self.calls += 1
        position = evidence_bundle["current_paper_position"]
        original = evidence_bundle["original_decision"]
        context = evidence_bundle["fresh_pit_context"]
        observation = {
            "observation_version": WATCHER_OBSERVATION_VERSION,
            "position_id": position["position_id"],
            "originating_decision_id": original["originating_decision_id"],
            "observed_at_utc": context["as_of_utc"],
            "context_hash": context["context_hash"],
            "paper_state_digest": position["paper_state_digest"],
            "original_thesis_digest": original["original_thesis_digest"],
            "assessment": self.assessment,
            "thesis_assessment": self.thesis_assessment,
            "reason_codes": [self.reason_code],
            "observation_summary": "Fresh evidence produced the preregistered bounded watcher assessment.",
            "evidence_change_summary": "Current evidence changed enough to exercise the Day 52 management boundary.",
            "confidence": 0.61,
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
            "request_digest": watcher_digest(evidence_bundle),
            "attempts": 1,
            "latency_ms": 1,
            "response_id": f"resp_watch_day52_{self.calls}",
            "provider_status": "completed",
            "provider_model": WATCHER_MODEL_ID,
            "usage": {
                "input_tokens": 100,
                "cached_input_tokens": 0,
                "output_tokens": 50,
                "reasoning_tokens": 20,
                "total_tokens": 150,
            },
            "estimated_cost_usd": "0.002000",
            "pricing_version": "openai_gpt_5_6_sol_pricing_2026_08_20",
            "prompt_version": WATCHER_PROMPT_VERSION,
            "prompt_digest": "a" * 64,
            "model_id": WATCHER_MODEL_ID,
            "reasoning_effort": WATCHER_REASONING_EFFORT,
        }


def _manage_decision(origin: dict, context: dict) -> dict:
    decision = origin["decision"]
    stamp = datetime.fromisoformat(context["as_of_utc"])
    return {
        "contract_version": MASTER_TRADER_CONTRACT_VERSION_V2,
        "action": "manage_trade",
        "symbol": "XAUUSD",
        "evaluated_at_utc": stamp.isoformat(),
        "valid_until_utc": (stamp + timedelta(minutes=5)).isoformat(),
        "confidence": 0.64,
        "setup_taxonomy_version": decision["setup_taxonomy_version"],
        "setup_codes": [],
        "reason_codes": ["momentum_weakened", "thesis_weakened"],
        "decision_summary": "Fresh watcher evidence supports a risk-reducing paper stop update.",
        "target_decision_id": origin["decision_id"],
        "direction": None,
        "entry_type": None,
        "market_reference_price": None,
        "stop_loss": None,
        "targets": [],
        "management_instruction": "move_stop",
        "new_stop_loss": 2495.0,
        "new_targets": [],
        "close_scope": None,
        "thesis": decision["thesis"],
        "expected_horizon_minutes": decision["expected_horizon_minutes"],
        "counter_argument": decision["counter_argument"],
        "invalidation_condition": copy.deepcopy(decision["invalidation_condition"]),
        "abstention_basis": None,
        "shadow_thesis": None,
        "shadow_direction": None,
        "shadow_horizon_minutes": None,
        "shadow_evaluation_condition": None,
    }


def _close_decision(origin: dict, context: dict) -> dict:
    decision = origin["decision"]
    stamp = datetime.fromisoformat(context["as_of_utc"])
    return {
        "contract_version": MASTER_TRADER_CONTRACT_VERSION_V2,
        "action": "close_trade",
        "symbol": "XAUUSD",
        "evaluated_at_utc": stamp.isoformat(),
        "valid_until_utc": (stamp + timedelta(minutes=5)).isoformat(),
        "confidence": 0.78,
        "setup_taxonomy_version": decision["setup_taxonomy_version"],
        "setup_codes": [],
        "reason_codes": ["thesis_broken", "thesis_invalidated"],
        "decision_summary": "Fresh watcher evidence invalidates the original thesis and supports a paper close.",
        "target_decision_id": origin["decision_id"],
        "direction": None,
        "entry_type": None,
        "market_reference_price": None,
        "stop_loss": None,
        "targets": [],
        "management_instruction": None,
        "new_stop_loss": None,
        "new_targets": [],
        "close_scope": "full",
        "thesis": decision["thesis"],
        "expected_horizon_minutes": decision["expected_horizon_minutes"],
        "counter_argument": decision["counter_argument"],
        "invalidation_condition": copy.deepcopy(decision["invalidation_condition"]),
        "abstention_basis": None,
        "shadow_thesis": None,
        "shadow_direction": None,
        "shadow_horizon_minutes": None,
        "shadow_evaluation_condition": None,
    }


async def _origin(cycle_store, publication_store, transport):
    context = MARKET["_context"]()
    retrieval, report = MARKET["_history"]()
    gateway = MARKET["FixedGateway"]([MARKET["_new_trade"](context)])
    result = await MARKET["run_market_evaluation_cycle"](
        context=context,
        aidy_state=MARKET["_state"](),
        retrieval=retrieval,
        evidence_report=report,
        hypothesis_direction="long",
        setup_family="trend_momentum",
        invalidation_inputs=MARKET["_invalidation"](),
        setup_detection=MARKET["_detection"](context),
        now_utc=BASE + timedelta(minutes=1),
        gateway=gateway,
        cycle_store=cycle_store,
        publication_store=publication_store,
        transport=transport,
        chat_id=CHAT_ID,
        source_state="dry_run",
        publish_enabled=False,
    )
    row = await cycle_store.get(result["cycle_id"])
    assert row is not None
    origin = cycle_store.decode_artifact(row, "ex_ante_json")
    assert origin is not None
    assert result["status"] == "decision_admitted_not_published"
    assert verify_paper_state(result["paper_state"])
    return origin, result["paper_state"]


@pytest.mark.asyncio
async def test_management_move_stop_publishes_once_updates_paper_state_and_restart_is_idempotent() -> None:
    cycle_store, publication_store = MARKET["_stores"]()
    transport = SimulatedTelegramTransport(sent_at_utc=BASE + timedelta(minutes=11), next_message_id=800)
    origin, paper_state = await _origin(cycle_store, publication_store, transport)
    context = MARKET["_context"](
        as_of=BASE + timedelta(minutes=10),
        active_decision_id=origin["decision_id"],
    )
    retrieval, report = MARKET["_history"]()
    watcher = FixedWatcherGateway(
        assessment="management_review",
        thesis_assessment="weakened",
        reason_code="momentum_weakened",
    )
    management = MARKET["FixedGateway"]([_manage_decision(origin, context)])

    first = await run_management_cycle(
        origin_ex_ante=origin,
        paper_state=paper_state,
        context=context,
        retrieval=retrieval,
        evidence_report=report,
        setup_family="trend_momentum",
        invalidation_inputs=MARKET["_invalidation"](),
        now_utc=BASE + timedelta(minutes=11),
        watcher_gateway=watcher,
        management_gateway=management,
        cycle_store=cycle_store,
        publication_store=publication_store,
        transport=transport,
        chat_id=CHAT_ID,
        source_state="live_admitted",
        publish_enabled=True,
    )
    assert first["status"] == "sent"
    assert watcher.calls == 1
    assert management.calls == 3
    assert len(transport.calls) == 1
    assert first["next_paper_state"]["stop_loss"] == "2495.0"
    assert verify_paper_state(first["next_paper_state"])
    assert first["management_action_id"]
    assert first["watcher_receipt_digest"]

    second = await run_management_cycle(
        origin_ex_ante=origin,
        paper_state=paper_state,
        context=context,
        retrieval=retrieval,
        evidence_report=report,
        setup_family="trend_momentum",
        invalidation_inputs=MARKET["_invalidation"](),
        now_utc=BASE + timedelta(minutes=11, seconds=10),
        watcher_gateway=watcher,
        management_gateway=management,
        cycle_store=cycle_store,
        publication_store=publication_store,
        transport=transport,
        chat_id=CHAT_ID,
        source_state="live_admitted",
        publish_enabled=True,
    )
    assert second["status"] == "already_sent"
    assert second["decision_id"] == first["decision_id"]
    assert second["publication_id"] == first["publication_id"]
    assert watcher.calls == 1
    assert management.calls == 3
    assert len(transport.calls) == 1


@pytest.mark.asyncio
async def test_watcher_hold_never_calls_management_model_or_telegram() -> None:
    cycle_store, publication_store = MARKET["_stores"]()
    transport = SimulatedTelegramTransport(sent_at_utc=BASE + timedelta(minutes=11))
    origin, paper_state = await _origin(cycle_store, publication_store, transport)
    context = MARKET["_context"](
        as_of=BASE + timedelta(minutes=10),
        active_decision_id=origin["decision_id"],
    )
    retrieval, report = MARKET["_history"]()
    watcher = FixedWatcherGateway(
        assessment="hold",
        thesis_assessment="intact",
        reason_code="thesis_intact",
    )
    management = MARKET["FixedGateway"]([_manage_decision(origin, context)])
    result = await run_management_cycle(
        origin_ex_ante=origin,
        paper_state=paper_state,
        context=context,
        retrieval=retrieval,
        evidence_report=report,
        setup_family="trend_momentum",
        invalidation_inputs=MARKET["_invalidation"](),
        now_utc=BASE + timedelta(minutes=11),
        watcher_gateway=watcher,
        management_gateway=management,
        cycle_store=cycle_store,
        publication_store=publication_store,
        transport=transport,
        chat_id=CHAT_ID,
        source_state="live_admitted",
        publish_enabled=True,
    )
    assert result["status"] == "watcher_hold"
    assert watcher.calls == 1
    assert management.calls == 0
    assert transport.calls == []


@pytest.mark.asyncio
async def test_management_close_is_terminal_and_publishes_one_close_update() -> None:
    cycle_store, publication_store = MARKET["_stores"]()
    transport = SimulatedTelegramTransport(sent_at_utc=BASE + timedelta(minutes=11), next_message_id=900)
    origin, paper_state = await _origin(cycle_store, publication_store, transport)
    context = MARKET["_context"](
        as_of=BASE + timedelta(minutes=10),
        active_decision_id=origin["decision_id"],
    )
    retrieval, report = MARKET["_history"]()
    watcher = FixedWatcherGateway(
        assessment="close_review",
        thesis_assessment="invalidated",
        reason_code="thesis_broken",
    )
    management = MARKET["FixedGateway"]([_close_decision(origin, context)])
    result = await run_management_cycle(
        origin_ex_ante=origin,
        paper_state=paper_state,
        context=context,
        retrieval=retrieval,
        evidence_report=report,
        setup_family="trend_momentum",
        invalidation_inputs=MARKET["_invalidation"](),
        now_utc=BASE + timedelta(minutes=11),
        watcher_gateway=watcher,
        management_gateway=management,
        cycle_store=cycle_store,
        publication_store=publication_store,
        transport=transport,
        chat_id=CHAT_ID,
        source_state="live_admitted",
        publish_enabled=True,
    )
    assert result["status"] == "sent"
    assert result["next_paper_state"]["state_type"] == "terminal_management_close"
    assert result["next_paper_state"]["watcher_can_run_again"] is False
    assert result["next_paper_state"]["execution_allowed"] is False
    assert len(transport.calls) == 1
