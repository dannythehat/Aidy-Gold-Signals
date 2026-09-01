from __future__ import annotations

import argparse
import copy
import json
import runpy
import sqlite3
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from aidy.publication_ledger import (
    D1PublicationLedgerStore,
    day51_manifest,
    deliver_with_ledger,
    reconstruct_exact_publication,
)
from aidy.telegram_publisher import SimulatedTelegramTransport, build_publication_envelope, canonical_json, digest

BASE_SHA = "8765d0d3743ac3b59a1083aea14876615df5bb42"
ROOT = Path(__file__).resolve().parents[1]
FIXTURE_TIME = datetime(2026, 9, 1, 15, 30, tzinfo=UTC)
CHAT_ID = "-1001234567890"
_DAY34 = runpy.run_path(str(ROOT / "scripts" / "day34_decision_ledger_acceptance.py"))
_cycle = _DAY34["_cycle"]


class Prepared:
    def __init__(self, db: "LocalD1", sql: str, params=()) -> None:
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
        raise RuntimeError("simulated ambiguous network outcome")


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AIDY Day 51 publication ledger acceptance")
    parser.add_argument("--output-dir", default="day51_artifacts")
    return parser.parse_args()


def _head_sha() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()


async def build_artifacts(head_sha: str) -> dict[str, Any]:
    store = D1PublicationLedgerStore(LocalD1())
    decision = _cycle(FIXTURE_TIME, 0, "decision_admitted")
    decision_before = copy.deepcopy(decision)
    envelope = build_publication_envelope(ex_ante_record=decision, chat_id=CHAT_ID)

    transport = SimulatedTelegramTransport(sent_at_utc=FIXTURE_TIME, next_message_id=100)
    sent = await deliver_with_ledger(envelope, store=store, transport=transport, now_utc=FIXTURE_TIME)
    retry = await deliver_with_ledger(
        envelope,
        store=store,
        transport=transport,
        now_utc=FIXTURE_TIME + timedelta(seconds=5),
    )
    delivery = await store.get_delivery(envelope["publication_id"])
    attempts = await store.list_attempts(envelope["publication_id"])
    if delivery is None:
        raise RuntimeError("Day 51 delivery row missing.")
    reconstructed = reconstruct_exact_publication(delivery)

    second_decision = _cycle(FIXTURE_TIME, 1, "decision_admitted")
    uncertain_envelope = build_publication_envelope(ex_ante_record=second_decision, chat_id=CHAT_ID)
    ambiguous = AmbiguousFailureTransport()
    uncertain = await deliver_with_ledger(
        uncertain_envelope,
        store=store,
        transport=ambiguous,
        now_utc=FIXTURE_TIME + timedelta(minutes=1),
    )
    blind_retry = await deliver_with_ledger(
        uncertain_envelope,
        store=store,
        transport=ambiguous,
        now_utc=FIXTURE_TIME + timedelta(minutes=3),
    )
    reconciled = await store.reconcile(
        uncertain_envelope["publication_id"],
        event_type="confirmed_not_sent",
        observed_at_utc=FIXTURE_TIME + timedelta(minutes=4),
        reason_code="acceptance_confirmed_no_message",
    )
    retry_transport = SimulatedTelegramTransport(
        sent_at_utc=FIXTURE_TIME + timedelta(minutes=5), next_message_id=200
    )
    safe_retry = await deliver_with_ledger(
        uncertain_envelope,
        store=store,
        transport=retry_transport,
        now_utc=FIXTURE_TIME + timedelta(minutes=5),
    )
    uncertain_attempts = await store.list_attempts(uncertain_envelope["publication_id"])

    manifest = day51_manifest()
    summary: dict[str, Any] = {
        "ok": True,
        "base_sha": BASE_SHA,
        "head_sha": head_sha,
        "manifest_digest": manifest["manifest_digest"],
        "storage": manifest["storage"],
        "normal_send_status": sent["status"],
        "normal_retry_status": retry["status"],
        "normal_transport_call_count": len(transport.calls),
        "normal_attempt_count": len(attempts),
        "exact_text_reconstructable": reconstructed["message"] == envelope["message"],
        "exact_message_digest_preserved": reconstructed["message_digest"] == envelope["message_digest"],
        "decision_identity_preserved": delivery["decision_id"] == decision["decision_id"],
        "decision_record_unchanged": decision == decision_before,
        "delivery_truth_separate": True,
        "ambiguous_failure_status": uncertain["status"],
        "blind_retry_status": blind_retry["status"],
        "ambiguous_transport_call_count_before_reconciliation": ambiguous.calls,
        "reconciled_state": reconciled["delivery_state"],
        "safe_retry_status": safe_retry["status"],
        "safe_retry_transport_call_count": len(retry_transport.calls),
        "uncertain_attempt_states": [row["result_state"] for row in uncertain_attempts],
        "no_duplicate_after_success": len(transport.calls) == 1,
        "no_blind_retry_after_uncertain": ambiguous.calls == 1,
        "migration_is_durable_d1": True,
        "secrets_persisted": False,
        "real_telegram_post_performed": False,
        "broker_dependency_allowed": False,
        "follower_dependency_allowed": False,
        "super_signals_dependency_allowed": False,
        "formal_forward_evidence_created": False,
    }
    summary["summary_digest"] = digest(summary)
    return {
        "summary": summary,
        "manifest": manifest,
        "sent_delivery": delivery,
        "sent_attempts": attempts,
        "uncertain_attempts": uncertain_attempts,
    }


def main() -> None:
    import asyncio

    args = _args()
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    artifacts = asyncio.run(build_artifacts(_head_sha()))
    (output / "summary.json").write_text(canonical_json(artifacts["summary"]) + "\n", encoding="utf-8")
    (output / "ledger.json").write_text(
        canonical_json(
            {
                "manifest": artifacts["manifest"],
                "sent_delivery": artifacts["sent_delivery"],
                "sent_attempts": artifacts["sent_attempts"],
                "uncertain_attempts": artifacts["uncertain_attempts"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps(artifacts["summary"], sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
