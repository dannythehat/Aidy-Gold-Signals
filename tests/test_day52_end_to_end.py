from __future__ import annotations

import copy
import runpy
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from aidy.context_packet import CONTEXT_PACKET_VERSION, compute_context_hash
from aidy.cross_market import ENABLED_SERIES
from aidy.end_to_end import day52_runtime_manifest, run_market_evaluation_cycle
from aidy.end_to_end_store import D1EndToEndCycleStore, digest
from aidy.feature_engine import TIMEFRAMES
from aidy.master_trader_contract_v2 import (
    MACHINE_CONDITION_VERSION,
    MASTER_TRADER_CONTRACT_VERSION_V2,
    master_trader_decision_digest_versioned,
    validate_master_trader_decision_v2,
)
from aidy.openai_gateway_v2 import (
    OPENAI_GATEWAY_VERSION_V2,
    OPENAI_MODEL_ID_V2,
    OPENAI_PROMPT_VERSION_V2,
    build_openai_request_v2,
    openai_gateway_manifest_v2,
)
from aidy.publication_ledger import D1PublicationLedgerStore
from aidy.setup_detector import (
    SETUP_DETECTION_VERSION,
    SETUP_DETECTOR_VERSION,
    SETUP_TAXONOMY_VERSION,
    compute_setup_detection_digest,
    taxonomy_manifest,
)
from aidy.telegram_publisher import SimulatedTelegramTransport

ROOT = Path(__file__).resolve().parents[1]
HISTORY = runpy.run_path(str(ROOT / "tests" / "test_day35_context_composer_v2.py"))
BASE = datetime(2026, 9, 1, 16, 0, tzinfo=UTC)
CHAT_ID = "-1001234567890"


class Prepared:
    def __init__(self, db: LocalD1, sql: str, params=()) -> None:
        self.db = db
        self.sql = sql
        self.params = params

    def bind(self, *params):
        return Prepared(self.db, self.sql, params)

    async def first(self):
        row = self.db.connection.execute(self.sql, self.params).fetchone()
        return dict(row) if row is not None else None

    async def all(self):
        rows = self.db.connection.execute(self.sql, self.params).fetchall()
        return {"results": [dict(row) for row in rows]}

    async def run(self):
        self.db.connection.execute(self.sql, self.params)
        self.db.connection.commit()
        return {"success": True}


class LocalD1:
    def __init__(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        for migration in (
            "migrations/d1/0001_aidy_ops.sql",
            "migrations/d1/0002_cross_market_evidence.sql",
            "migrations/d1/0003_publication_ledger.sql",
            "migrations/d1/0004_end_to_end_cycles.sql",
        ):
            self.connection.executescript((ROOT / migration).read_text())

    def prepare(self, sql: str) -> Prepared:
        return Prepared(self, sql)

    async def batch(self, statements):
        results = []
        with self.connection:
            for statement in statements:
                cursor = self.connection.execute(statement.sql, statement.params)
                rows = cursor.fetchall() if cursor.description else []
                results.append({"success": True, "results": [dict(row) for row in rows]})
        return results


class FixedGateway:
    def __init__(self, decisions: list[dict] | None = None, *, fail: bool = False) -> None:
        self.decisions = decisions or []
        self.fail = fail
        self.calls = 0

    async def evaluate(self, evidence_bundle):
        self.calls += 1
        manifest = openai_gateway_manifest_v2()
        base = {
            "gateway_version": OPENAI_GATEWAY_VERSION_V2,
            "request_digest": digest({"bundle": evidence_bundle, "config": manifest["manifest_digest"]}),
            "attempts": 1,
            "latency_ms": 1,
            "response_id": f"resp_day52_{self.calls}",
            "provider_status": "completed",
            "provider_model": OPENAI_MODEL_ID_V2,
            "usage": {
                "input_tokens": 100,
                "cached_input_tokens": 0,
                "output_tokens": 50,
                "reasoning_tokens": 20,
                "total_tokens": 150,
            },
            "estimated_cost_usd": "0.002000",
            "pricing_version": manifest["pricing_version"],
            "prompt_version": OPENAI_PROMPT_VERSION_V2,
            "prompt_digest": manifest["prompt_digest"],
            "model_id": OPENAI_MODEL_ID_V2,
            "reasoning_effort": manifest["reasoning_effort"],
        }
        if self.fail:
            return {
                **base,
                "status": "failed_closed",
                "publication_allowed": False,
                "failure_reason": "simulated_openai_outage",
                "structured_decision": None,
                "decision_digest": None,
            }
        decision = validate_master_trader_decision_v2(
            self.decisions[(self.calls - 1) % len(self.decisions)]
        )
        return {
            **base,
            "status": "accepted",
            "publication_allowed": True,
            "failure_reason": None,
            "structured_decision": copy.deepcopy(decision),
            "decision_digest": master_trader_decision_digest_versioned(decision),
        }


def _context(*, as_of: datetime = BASE, active_decision_id: str | None = None) -> dict:
    signals = []
    if active_decision_id is not None:
        signals = [
            {
                "aidy_signal_id": f"signal:{active_decision_id}",
                "originating_decision_id": active_decision_id,
                "status": "active",
                "direction": "long",
                "entry_type": "market",
                "entry_price": "2500",
                "stop_loss": "2490",
                "targets": ["2510", "2520"],
                "opened_at_utc": BASE.isoformat(),
                "updated_at_utc": as_of.isoformat(),
            }
        ]
    packet = {
        "context_packet_version": CONTEXT_PACKET_VERSION,
        "context_hash_algorithm": "sha256",
        "as_of_utc": as_of.isoformat(),
        "symbol": "XAUUSD",
        "objective_only": True,
        "retrospective_history_included": False,
        "broker_follower_state_included": False,
        "source_contract_versions": {"day52_fixture": "v1"},
        "gold": {
            "timeframes": {timeframe: {"state": "known"} for timeframe in TIMEFRAMES},
            "quote_context": {
                "quote_state": "known",
                "quote_age_seconds": 0,
                "spread": "0.30",
                "mid": "2500.0",
            },
        },
        "session": {
            "computed_session_code": "LONDON",
            "recorded_session_code": "LONDON",
            "session_code_consistent": True,
        },
        "event_risk": {"evidence_state": "known", "timing_state": "clear_current_window"},
        "cross_market": {
            "series": {
                series_id: {"state": "known", "observation_age_days": 0}
                for series_id in ENABLED_SERIES
            }
        },
        "aidy_signal_lifecycle": {
            "evidence_state": "known",
            "lifecycle_state": "active" if signals else "none",
            "active_signals": signals,
        },
        "data_quality": {
            "quote_stale_after_seconds": 300,
            "missing_gold_timeframes": [],
            "quote_state": "known",
            "quote_age_seconds": 0,
            "quote_freshness": "fresh",
            "spread_state": "known",
            "macro_evidence_state": "known",
            "cross_market_missing_series": [],
            "cross_market_observation_age_days": {series_id: 0 for series_id in ENABLED_SERIES},
            "aidy_signal_state": "known",
            "flags": [],
        },
        "provenance": {},
    }
    packet["context_hash"] = compute_context_hash(packet)
    return packet


def _detection(context: dict) -> dict:
    packet = {
        "detection_version": SETUP_DETECTION_VERSION,
        "detector_version": SETUP_DETECTOR_VERSION,
        "taxonomy_version": SETUP_TAXONOMY_VERSION,
        "taxonomy_digest": taxonomy_manifest()["taxonomy_digest"],
        "pit_eligible": True,
        "future_derived": False,
        "decision_input_allowed": True,
        "trading_decision_made": False,
        "trade_recommendation_made": False,
        "symbol": "XAUUSD",
        "as_of_utc": context["as_of_utc"],
        "source_context_hash": context["context_hash"],
        "candidate_setup_ids": ["trend_momentum_long"],
        "candidates": [{"setup_id": "trend_momentum_long", "direction": "long"}],
    }
    packet["detection_digest"] = compute_setup_detection_digest(packet)
    return packet


def _new_trade(context: dict, *, second_target: float = 2520.0) -> dict:
    as_of = datetime.fromisoformat(context["as_of_utc"])
    return {
        "contract_version": MASTER_TRADER_CONTRACT_VERSION_V2,
        "action": "new_trade",
        "symbol": "XAUUSD",
        "evaluated_at_utc": as_of.isoformat(),
        "valid_until_utc": (as_of + timedelta(minutes=5)).isoformat(),
        "confidence": 0.72,
        "setup_taxonomy_version": SETUP_TAXONOMY_VERSION,
        "setup_codes": ["trend_momentum_long"],
        "reason_codes": ["setup_present", "day52_fixture"],
        "decision_summary": "Current independent evidence supports a bounded paper-only long candidate.",
        "target_decision_id": None,
        "direction": "long",
        "entry_type": "market",
        "market_reference_price": 2500.0,
        "stop_loss": 2490.0,
        "targets": [2510.0, second_target],
        "management_instruction": None,
        "new_stop_loss": None,
        "new_targets": [],
        "close_scope": None,
        "thesis": "Gold should continue higher while the current reference structure remains intact.",
        "expected_horizon_minutes": 120,
        "counter_argument": "A decisive loss of the reference floor would contradict the continuation thesis.",
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


def _no_trade(context: dict) -> dict:
    as_of = datetime.fromisoformat(context["as_of_utc"])
    return {
        "contract_version": MASTER_TRADER_CONTRACT_VERSION_V2,
        "action": "no_trade",
        "symbol": "XAUUSD",
        "evaluated_at_utc": as_of.isoformat(),
        "valid_until_utc": (as_of + timedelta(minutes=5)).isoformat(),
        "confidence": 0.43,
        "setup_taxonomy_version": SETUP_TAXONOMY_VERSION,
        "setup_codes": [],
        "reason_codes": ["insufficient_independent_evidence"],
        "decision_summary": "The current evidence does not earn an actionable Gold signal.",
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
        "thesis": None,
        "expected_horizon_minutes": None,
        "counter_argument": "A strong continuation could occur despite the current lack of independent evidence.",
        "invalidation_condition": None,
        "abstention_basis": "Independent evidence remains too weak for an actionable signal.",
        "shadow_thesis": "Gold may continue higher if the current structure persists.",
        "shadow_direction": "long",
        "shadow_horizon_minutes": 120,
        "shadow_evaluation_condition": {
            "condition_version": MACHINE_CONDITION_VERSION,
            "field_path": "$.gold.quote_context.mid",
            "operator": "gt",
            "value_type": "number",
            "value": 2510.0,
        },
    }


def _history():
    return HISTORY["_retrieval_and_report"]()


def _state():
    return {
        "regime": {"trend_structure": "bullish_trend", "volatility_band": "normal"},
        "setup": {"candidate_setup_ids": ["trend_momentum_long"]},
        "data_quality": {"state": "known", "quote_freshness": "fresh"},
    }


def _invalidation():
    return {"price_floor": "2490.0", "event_window_clear": True}


def _stores():
    db = LocalD1()
    return D1EndToEndCycleStore(db), D1PublicationLedgerStore(db)


@pytest.mark.asyncio
async def test_v2_market_cycle_publishes_once_and_restart_does_not_call_model_or_transport_again() -> None:
    context = _context()
    retrieval, report = _history()
    cycle_store, publication_store = _stores()
    gateway = FixedGateway([_new_trade(context)])
    transport = SimulatedTelegramTransport(sent_at_utc=BASE + timedelta(minutes=1), next_message_id=700)

    first = await run_market_evaluation_cycle(
        context=context,
        aidy_state=_state(),
        retrieval=retrieval,
        evidence_report=report,
        hypothesis_direction="long",
        setup_family="trend_momentum",
        invalidation_inputs=_invalidation(),
        setup_detection=_detection(context),
        now_utc=BASE + timedelta(minutes=1),
        gateway=gateway,
        cycle_store=cycle_store,
        publication_store=publication_store,
        transport=transport,
        chat_id=CHAT_ID,
        source_state="live_admitted",
        publish_enabled=True,
    )
    assert first["status"] == "sent"
    assert gateway.calls == 3
    assert len(transport.calls) == 1
    assert first["paper_state"]["decision_id"] == first["decision_id"]

    second = await run_market_evaluation_cycle(
        context=context,
        aidy_state=_state(),
        retrieval=retrieval,
        evidence_report=report,
        hypothesis_direction="long",
        setup_family="trend_momentum",
        invalidation_inputs=_invalidation(),
        setup_detection=_detection(context),
        now_utc=BASE + timedelta(minutes=1, seconds=10),
        gateway=gateway,
        cycle_store=cycle_store,
        publication_store=publication_store,
        transport=transport,
        chat_id=CHAT_ID,
        source_state="live_admitted",
        publish_enabled=True,
    )
    assert second["status"] == "already_sent"
    assert gateway.calls == 3
    assert len(transport.calls) == 1
    assert second["decision_id"] == first["decision_id"]
    assert second["publication_id"] == first["publication_id"]


@pytest.mark.asyncio
async def test_no_trade_is_ledgered_but_never_published() -> None:
    context = _context()
    retrieval, report = _history()
    cycle_store, publication_store = _stores()
    gateway = FixedGateway([_no_trade(context)])
    transport = SimulatedTelegramTransport(sent_at_utc=BASE + timedelta(minutes=1))
    result = await run_market_evaluation_cycle(
        context=context,
        aidy_state=_state(),
        retrieval=retrieval,
        evidence_report=report,
        hypothesis_direction="long",
        setup_family="trend_momentum",
        invalidation_inputs=_invalidation(),
        setup_detection=_detection(context),
        now_utc=BASE + timedelta(minutes=1),
        gateway=gateway,
        cycle_store=cycle_store,
        publication_store=publication_store,
        transport=transport,
        chat_id=CHAT_ID,
        source_state="live_admitted",
        publish_enabled=True,
    )
    assert result["status"] == "no_trade"
    assert gateway.calls == 3
    assert transport.calls == []
    row = await cycle_store.get(result["cycle_id"])
    assert row is not None and row["ex_ante_digest"]
    assert row["publication_id"] is None


@pytest.mark.asyncio
async def test_no_safe_majority_fails_closed_without_fabricating_no_trade_record() -> None:
    context = _context()
    retrieval, report = _history()
    cycle_store, publication_store = _stores()
    gateway = FixedGateway([_new_trade(context), _no_trade(context), _new_trade(context, second_target=2525.0)])
    transport = SimulatedTelegramTransport(sent_at_utc=BASE + timedelta(minutes=1))
    result = await run_market_evaluation_cycle(
        context=context,
        aidy_state=_state(),
        retrieval=retrieval,
        evidence_report=report,
        hypothesis_direction="long",
        setup_family="trend_momentum",
        invalidation_inputs=_invalidation(),
        setup_detection=_detection(context),
        now_utc=BASE + timedelta(minutes=1),
        gateway=gateway,
        cycle_store=cycle_store,
        publication_store=publication_store,
        transport=transport,
        chat_id=CHAT_ID,
        source_state="live_admitted",
        publish_enabled=True,
    )
    assert result["status"] == "self_consistency_abstain"
    assert transport.calls == []
    row = await cycle_store.get(result["cycle_id"])
    assert row is not None
    assert row["self_consistency_digest"]
    assert row["ex_ante_digest"] is None
    assert row["decision_id"] is None


@pytest.mark.asyncio
async def test_stale_context_blocks_before_model_or_publication() -> None:
    context = _context()
    retrieval, report = _history()
    cycle_store, publication_store = _stores()
    gateway = FixedGateway([_new_trade(context)])
    transport = SimulatedTelegramTransport(sent_at_utc=BASE + timedelta(minutes=10))
    result = await run_market_evaluation_cycle(
        context=context,
        aidy_state=_state(),
        retrieval=retrieval,
        evidence_report=report,
        hypothesis_direction="long",
        setup_family="trend_momentum",
        invalidation_inputs=_invalidation(),
        setup_detection=_detection(context),
        now_utc=BASE + timedelta(minutes=10),
        gateway=gateway,
        cycle_store=cycle_store,
        publication_store=publication_store,
        transport=transport,
        chat_id=CHAT_ID,
        source_state="live_admitted",
        publish_enabled=True,
    )
    assert result["status"] == "pre_model_blocked"
    assert gateway.calls == 0
    assert transport.calls == []


@pytest.mark.asyncio
async def test_openai_outage_fails_closed_without_publication() -> None:
    context = _context()
    retrieval, report = _history()
    cycle_store, publication_store = _stores()
    gateway = FixedGateway(fail=True)
    transport = SimulatedTelegramTransport(sent_at_utc=BASE + timedelta(minutes=1))
    result = await run_market_evaluation_cycle(
        context=context,
        aidy_state=_state(),
        retrieval=retrieval,
        evidence_report=report,
        hypothesis_direction="long",
        setup_family="trend_momentum",
        invalidation_inputs=_invalidation(),
        setup_detection=_detection(context),
        now_utc=BASE + timedelta(minutes=1),
        gateway=gateway,
        cycle_store=cycle_store,
        publication_store=publication_store,
        transport=transport,
        chat_id=CHAT_ID,
        source_state="live_admitted",
        publish_enabled=True,
    )
    assert result["status"] == "self_consistency_abstain"
    assert gateway.calls == 3
    assert transport.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("source_state", ["shadow", "replay", "dry_run", "private_forward"])
async def test_non_live_states_can_never_leak_to_telegram(source_state: str) -> None:
    context = _context()
    retrieval, report = _history()
    cycle_store, publication_store = _stores()
    gateway = FixedGateway([_new_trade(context)])
    transport = SimulatedTelegramTransport(sent_at_utc=BASE + timedelta(minutes=1))
    result = await run_market_evaluation_cycle(
        context=context,
        aidy_state=_state(),
        retrieval=retrieval,
        evidence_report=report,
        hypothesis_direction="long",
        setup_family="trend_momentum",
        invalidation_inputs=_invalidation(),
        setup_detection=_detection(context),
        now_utc=BASE + timedelta(minutes=1),
        gateway=gateway,
        cycle_store=cycle_store,
        publication_store=publication_store,
        transport=transport,
        chat_id=CHAT_ID,
        source_state=source_state,
        publish_enabled=True,
    )
    assert result["status"] == "decision_admitted_not_published"
    assert transport.calls == []


def test_v2_gateway_request_freezes_strict_falsifiable_schema() -> None:
    request = build_openai_request_v2({"safe": {"objective_only": True}})
    assert request["model"] == OPENAI_MODEL_ID_V2
    schema = request["text"]["format"]["schema"]
    for key in (
        "thesis",
        "expected_horizon_minutes",
        "counter_argument",
        "invalidation_condition",
        "abstention_basis",
        "shadow_thesis",
        "shadow_evaluation_condition",
    ):
        assert key in schema["properties"]
    assert request["store"] is False


def test_day52_manifest_does_not_start_day53_or_allow_downstream_leakage() -> None:
    manifest = day52_runtime_manifest()
    assert manifest["restart_reuses_exact_ex_ante_record"] is True
    assert manifest["shadow_replay_can_publish"] is False
    assert manifest["no_trade_can_publish"] is False
    assert manifest["broker_or_account_state_allowed"] is False
    assert manifest["super_signals_dependency_allowed"] is False
    assert manifest["formal_forward_evidence_created"] is False
    assert manifest["day53_automatically_started"] is False
