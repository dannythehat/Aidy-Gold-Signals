from __future__ import annotations

import copy
import runpy
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from aidy.publication_ledger import (
    D1PublicationLedgerStore,
    day51_manifest,
    deliver_with_ledger,
    reconstruct_exact_publication,
)
from aidy.telegram_publisher import SimulatedTelegramTransport, build_publication_envelope

ROOT = Path(__file__).resolve().parents[1]
_DAY34 = runpy.run_path(str(ROOT / "scripts" / "day34_decision_ledger_acceptance.py"))
_cycle = _DAY34["_cycle"]
NOW = datetime(2026, 9, 1, 15, 0, tzinfo=UTC)
CHAT_ID = "-1001234567890"


class Prepared:
    def __init__(self, db: "LocalD1", sql: str, params=()) -> None:
        self.db = db
        self.sql = sql
        self.params = params

    def bind(self, *params):
        return Prepared(self.db, self.sql, params)

    async def first(self):
        cursor = self.db.connection.execute(self.sql, self.params)
        row = cursor.fetchone()
        return dict(row) if row is not None else None

    async def all(self):
        cursor = self.db.connection.execute(self.sql, self.params)
        return {"results": [dict(row) for row in cursor.fetchall()]}

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


class AmbiguousFailureTransport:
    def __init__(self) -> None:
        self.calls = 0

    def send_message(self, *, chat_id: str, text: str):
        self.calls += 1
        raise RuntimeError("connection vanished after request write")


@pytest.fixture
def store() -> D1PublicationLedgerStore:
    return D1PublicationLedgerStore(LocalD1())


def _record(index: int = 0):
    return _cycle(NOW, index, "decision_admitted")


def _envelope(index: int = 0):
    return build_publication_envelope(ex_ante_record=_record(index), chat_id=CHAT_ID)


@pytest.mark.asyncio
async def test_exact_text_and_identity_are_durably_reconstructable(store) -> None:
    envelope = _envelope()
    row = await store.register_envelope(envelope, created_at_utc=NOW)
    reconstructed = reconstruct_exact_publication(row)
    assert reconstructed["publication_id"] == envelope["publication_id"]
    assert reconstructed["decision_id"] == envelope["decision_id"]
    assert reconstructed["message"] == envelope["message"]
    assert reconstructed["message_digest"] == envelope["message_digest"]
    assert row["delivery_state"] == "pending"
    assert "token" not in row["exact_message_text"].casefold()


@pytest.mark.asyncio
async def test_register_same_publication_is_idempotent_but_identity_conflict_fails(store) -> None:
    envelope = _envelope()
    first = await store.register_envelope(envelope, created_at_utc=NOW)
    second = await store.register_envelope(envelope, created_at_utc=NOW + timedelta(seconds=1))
    assert first["publication_id"] == second["publication_id"]
    assert first["created_at_utc"] == second["created_at_utc"]

    tampered = copy.deepcopy(envelope)
    tampered["message"] = tampered["message"] + "\nTAMPER"
    # Invalid envelope digest/message digest fails before storage conflict logic.
    with pytest.raises(ValueError):
        await store.register_envelope(tampered, created_at_utc=NOW)


@pytest.mark.asyncio
async def test_successful_delivery_is_exactly_once_for_normal_retry(store) -> None:
    envelope = _envelope()
    transport = SimulatedTelegramTransport(sent_at_utc=NOW)
    first = await deliver_with_ledger(envelope, store=store, transport=transport, now_utc=NOW)
    retry = await deliver_with_ledger(
        envelope,
        store=store,
        transport=transport,
        now_utc=NOW + timedelta(seconds=10),
    )
    assert first["status"] == "sent"
    assert retry["status"] == "already_sent"
    assert len(transport.calls) == 1
    delivery = await store.get_delivery(envelope["publication_id"])
    attempts = await store.list_attempts(envelope["publication_id"])
    assert delivery is not None and delivery["delivery_state"] == "sent"
    assert delivery["attempt_count"] == 1
    assert len(attempts) == 1 and attempts[0]["result_state"] == "sent"


@pytest.mark.asyncio
async def test_ambiguous_network_failure_blocks_blind_retry(store) -> None:
    envelope = _envelope()
    transport = AmbiguousFailureTransport()
    first = await deliver_with_ledger(envelope, store=store, transport=transport, now_utc=NOW)
    retry = await deliver_with_ledger(
        envelope,
        store=store,
        transport=transport,
        now_utc=NOW + timedelta(minutes=2),
    )
    assert first["status"] == "delivery_uncertain"
    assert retry["status"] == "blocked"
    assert transport.calls == 1
    delivery = await store.get_delivery(envelope["publication_id"])
    assert delivery is not None and delivery["attempt_count"] == 1


@pytest.mark.asyncio
async def test_reconciliation_confirmed_not_sent_releases_one_safe_retry(store) -> None:
    envelope = _envelope()
    ambiguous = AmbiguousFailureTransport()
    await deliver_with_ledger(envelope, store=store, transport=ambiguous, now_utc=NOW)
    reconciled = await store.reconcile(
        envelope["publication_id"],
        event_type="confirmed_not_sent",
        observed_at_utc=NOW + timedelta(minutes=1),
        reason_code="manual_channel_check_no_message",
    )
    assert reconciled["delivery_state"] == "retryable_failed"

    transport = SimulatedTelegramTransport(sent_at_utc=NOW + timedelta(minutes=2), next_message_id=55)
    sent = await deliver_with_ledger(
        envelope,
        store=store,
        transport=transport,
        now_utc=NOW + timedelta(minutes=2),
    )
    assert sent["status"] == "sent"
    assert len(transport.calls) == 1
    attempts = await store.list_attempts(envelope["publication_id"])
    assert [row["result_state"] for row in attempts] == ["delivery_uncertain", "sent"]


@pytest.mark.asyncio
async def test_reconciliation_confirmed_sent_suppresses_future_send(store) -> None:
    envelope = _envelope()
    ambiguous = AmbiguousFailureTransport()
    await deliver_with_ledger(envelope, store=store, transport=ambiguous, now_utc=NOW)
    reconciled = await store.reconcile(
        envelope["publication_id"],
        event_type="confirmed_sent",
        observed_at_utc=NOW + timedelta(minutes=1),
        reason_code="manual_channel_check_found_message",
        telegram_message_id=987,
    )
    assert reconciled["delivery_state"] == "sent"
    assert reconciled["telegram_message_id"] == 987
    transport = SimulatedTelegramTransport(sent_at_utc=NOW + timedelta(minutes=2))
    result = await deliver_with_ledger(
        envelope,
        store=store,
        transport=transport,
        now_utc=NOW + timedelta(minutes=2),
    )
    assert result["status"] == "already_sent"
    assert transport.calls == []


@pytest.mark.asyncio
async def test_active_lease_prevents_concurrent_second_attempt(store) -> None:
    envelope = _envelope()
    await store.register_envelope(envelope, created_at_utc=NOW)
    first = await store.acquire_attempt(envelope["publication_id"], attempted_at_utc=NOW)
    second = await store.acquire_attempt(
        envelope["publication_id"], attempted_at_utc=NOW + timedelta(seconds=5)
    )
    assert first.status == "acquired"
    assert second.status == "busy"
    attempts = await store.list_attempts(envelope["publication_id"])
    assert len(attempts) == 1


@pytest.mark.asyncio
async def test_delivery_operations_do_not_mutate_decision_record(store) -> None:
    record = _record()
    before = copy.deepcopy(record)
    envelope = build_publication_envelope(ex_ante_record=record, chat_id=CHAT_ID)
    transport = SimulatedTelegramTransport(sent_at_utc=NOW)
    await deliver_with_ledger(envelope, store=store, transport=transport, now_utc=NOW)
    assert record == before


def test_day51_manifest_locks_production_boundaries() -> None:
    manifest = day51_manifest()
    assert manifest["storage"] == "cloudflare_d1"
    assert manifest["decision_truth_separate_from_delivery_truth"] is True
    assert manifest["successful_retry_duplicate_send_allowed"] is False
    assert manifest["ambiguous_transport_failure_auto_retry_allowed"] is False
    assert manifest["uncertain_delivery_requires_reconciliation"] is True
    assert manifest["confirmed_not_sent_becomes_retryable"] is True
    assert manifest["confirmed_sent_suppresses_retry"] is True
    assert manifest["broker_dependency_allowed"] is False
    assert manifest["super_signals_dependency_allowed"] is False
    assert manifest["formal_forward_evidence_created"] is False
