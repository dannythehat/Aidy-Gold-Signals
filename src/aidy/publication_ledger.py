from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from aidy.telegram_publisher import (
    TelegramPublicationError,
    TelegramTransport,
    digest,
    verify_publication_envelope,
)

PUBLICATION_LEDGER_VERSION = "aidy_publication_ledger_v1"
DAY51_MANIFEST_VERSION = "aidy_day51_publication_ledger_manifest_v1"
LEASE_SECONDS = 90


def _utc(value: datetime | str, *, name: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip())
        except ValueError as exc:
            raise ValueError(f"{name} must be timezone-aware ISO-8601.") from exc
    else:
        raise TypeError(f"{name} must be timezone-aware datetime/ISO-8601 text.")
    if parsed.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware.")
    return parsed.astimezone(UTC)


def _iso(value: datetime) -> str:
    return _utc(value, name="timestamp").isoformat()


def _row_value(row: object, key: str, default: object = None) -> object:
    if row is None:
        return default
    if isinstance(row, dict):
        return row.get(key, default)
    try:
        return row[key]  # type: ignore[index]
    except (KeyError, IndexError, TypeError):
        return getattr(row, key, default)


@dataclass(frozen=True)
class AttemptLease:
    status: str
    publication_id: str
    attempt_id: str | None = None
    attempt_number: int | None = None
    lease_token: str | None = None
    delivery: dict[str, Any] | None = None


class D1PublicationLedgerStore:
    """Durable Day 51 publication ledger backed by Cloudflare D1.

    This store owns delivery truth only. It never mutates or re-evaluates the
    trading decision, thesis, model output or Day 34 ex-ante ledger.
    """

    def __init__(
        self,
        database: object,
        *,
        id_factory: Callable[[str], str] | None = None,
    ) -> None:
        self._db = database
        self._id_factory = id_factory or (lambda kind: f"aidy_{kind}_{uuid4().hex}")

    def _stmt(self, sql: str, *params: object) -> object:
        return self._db.prepare(sql).bind(*params)

    async def _first(self, sql: str, *params: object) -> object:
        return await self._stmt(sql, *params).first()

    async def register_envelope(
        self,
        envelope: Mapping[str, Any],
        *,
        created_at_utc: datetime,
        correction_of_publication_id: str | None = None,
        correction_reason_code: str | None = None,
    ) -> dict[str, Any]:
        if not verify_publication_envelope(envelope):
            raise TelegramPublicationError(
                "publication_ledger_envelope_invalid",
                "Verified publication envelope required.",
            )
        created = _iso(created_at_utc)
        publication_id = str(envelope["publication_id"])
        await self._stmt(
            """
            INSERT INTO publication_deliveries (
                publication_id,decision_id,ex_ante_digest,message_digest,envelope_digest,
                group_name,chat_id,exact_message_text,source_state,action,created_at_utc,
                correction_of_publication_id,correction_reason_code
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(publication_id) DO NOTHING
            """,
            publication_id,
            str(envelope["decision_id"]),
            str(envelope["ex_ante_digest"]),
            str(envelope["message_digest"]),
            str(envelope["envelope_digest"]),
            str(envelope["group_name"]),
            str(envelope["chat_id"]),
            str(envelope["message"]),
            str(envelope["source_state"]),
            str(envelope["action"]),
            created,
            correction_of_publication_id,
            correction_reason_code,
        ).run()
        row = await self.get_delivery(publication_id)
        if row is None:
            raise RuntimeError("Publication ledger failed to persist envelope.")
        expected = {
            "decision_id": str(envelope["decision_id"]),
            "ex_ante_digest": str(envelope["ex_ante_digest"]),
            "message_digest": str(envelope["message_digest"]),
            "envelope_digest": str(envelope["envelope_digest"]),
            "chat_id": str(envelope["chat_id"]),
            "exact_message_text": str(envelope["message"]),
        }
        for key, value in expected.items():
            if str(row.get(key)) != value:
                raise TelegramPublicationError(
                    "publication_ledger_identity_conflict",
                    "Existing publication identity conflicts with the verified envelope.",
                )
        return row

    async def get_delivery(self, publication_id: str) -> dict[str, Any] | None:
        row = await self._first(
            "SELECT * FROM publication_deliveries WHERE publication_id=? LIMIT 1",
            publication_id,
        )
        return dict(row) if isinstance(row, Mapping) else (dict(row) if row is not None else None)

    async def list_attempts(self, publication_id: str) -> list[dict[str, Any]]:
        result = await self._stmt(
            "SELECT * FROM publication_attempts WHERE publication_id=? ORDER BY attempt_number",
            publication_id,
        ).all()
        rows = _row_value(result, "results", [])
        return [dict(row) for row in rows]  # type: ignore[arg-type]

    async def acquire_attempt(
        self,
        publication_id: str,
        *,
        attempted_at_utc: datetime,
        lease_seconds: int = LEASE_SECONDS,
    ) -> AttemptLease:
        attempted = _utc(attempted_at_utc, name="attempted_at_utc")
        delivery = await self.get_delivery(publication_id)
        if delivery is None:
            raise KeyError(f"Unknown publication_id: {publication_id}")
        state = str(delivery["delivery_state"])
        if state == "sent":
            return AttemptLease("already_sent", publication_id, delivery=delivery)
        if state in {"delivery_uncertain", "permanent_failed"}:
            return AttemptLease("blocked", publication_id, delivery=delivery)

        lease_token = self._id_factory("lease")
        attempt_id = self._id_factory("attempt")
        lease_until = attempted + timedelta(seconds=max(30, int(lease_seconds)))
        update = self._stmt(
            """
            UPDATE publication_deliveries
            SET attempt_count=attempt_count+1,
                delivery_state='pending',
                lease_token=?, lease_until_utc=?, last_attempt_at_utc=?, last_error_code=NULL
            WHERE publication_id=?
              AND delivery_state IN ('pending','retryable_failed')
              AND (lease_until_utc IS NULL OR lease_until_utc <= ?)
            """,
            lease_token,
            _iso(lease_until),
            _iso(attempted),
            publication_id,
            _iso(attempted),
        )
        insert = self._stmt(
            """
            INSERT INTO publication_attempts (
                attempt_id,publication_id,attempt_number,attempted_at_utc,result_state,lease_token
            )
            SELECT ?,publication_id,attempt_count,?,'started',?
            FROM publication_deliveries
            WHERE publication_id=? AND lease_token=?
            """,
            attempt_id,
            _iso(attempted),
            lease_token,
            publication_id,
            lease_token,
        )
        await self._db.batch([update, insert])
        attempt = await self._first(
            "SELECT * FROM publication_attempts WHERE attempt_id=? LIMIT 1",
            attempt_id,
        )
        if attempt is None:
            current = await self.get_delivery(publication_id)
            if current is not None and current["delivery_state"] == "sent":
                return AttemptLease("already_sent", publication_id, delivery=current)
            return AttemptLease("busy", publication_id, delivery=current)
        return AttemptLease(
            "acquired",
            publication_id,
            attempt_id=attempt_id,
            attempt_number=int(_row_value(attempt, "attempt_number", 0)),
            lease_token=lease_token,
            delivery=await self.get_delivery(publication_id),
        )

    async def record_sent(
        self,
        lease: AttemptLease,
        *,
        telegram_message_id: int,
        sent_at_utc: datetime | str,
        transport: str,
        receipt_digest: str | None = None,
    ) -> dict[str, Any]:
        if lease.status != "acquired" or not lease.attempt_id or not lease.lease_token:
            raise ValueError("An acquired attempt lease is required.")
        sent_at = _iso(_utc(sent_at_utc, name="sent_at_utc"))
        attempt_body = {
            "ledger_version": PUBLICATION_LEDGER_VERSION,
            "publication_id": lease.publication_id,
            "attempt_id": lease.attempt_id,
            "attempt_number": lease.attempt_number,
            "result_state": "sent",
            "telegram_message_id": int(telegram_message_id),
            "sent_at_utc": sent_at,
            "transport": transport,
        }
        attempt_digest = digest(attempt_body)
        update_attempt = self._stmt(
            """
            UPDATE publication_attempts
            SET completed_at_utc=?,result_state='sent',telegram_message_id=?,transport=?,attempt_digest=?
            WHERE attempt_id=? AND lease_token=? AND result_state='started'
            """,
            sent_at,
            int(telegram_message_id),
            transport,
            attempt_digest,
            lease.attempt_id,
            lease.lease_token,
        )
        update_delivery = self._stmt(
            """
            UPDATE publication_deliveries
            SET delivery_state='sent',telegram_message_id=?,sent_at_utc=?,transport=?,receipt_digest=?,
                lease_token=NULL,lease_until_utc=NULL,last_error_code=NULL
            WHERE publication_id=? AND lease_token=? AND delivery_state='pending'
            """,
            int(telegram_message_id),
            sent_at,
            transport,
            receipt_digest,
            lease.publication_id,
            lease.lease_token,
        )
        await self._db.batch([update_attempt, update_delivery])
        row = await self.get_delivery(lease.publication_id)
        if row is None or row["delivery_state"] != "sent":
            raise RuntimeError("Publication send was not durably settled.")
        return row

    async def record_failure(
        self,
        lease: AttemptLease,
        *,
        error_code: str,
        failed_at_utc: datetime,
        classification: str,
    ) -> dict[str, Any]:
        if lease.status != "acquired" or not lease.attempt_id or not lease.lease_token:
            raise ValueError("An acquired attempt lease is required.")
        if classification not in {"retryable_failed", "delivery_uncertain", "permanent_failed"}:
            raise ValueError("Unsupported failure classification.")
        failed_at = _iso(failed_at_utc)
        attempt_body = {
            "ledger_version": PUBLICATION_LEDGER_VERSION,
            "publication_id": lease.publication_id,
            "attempt_id": lease.attempt_id,
            "attempt_number": lease.attempt_number,
            "result_state": classification,
            "error_code": error_code,
            "failed_at_utc": failed_at,
        }
        update_attempt = self._stmt(
            """
            UPDATE publication_attempts
            SET completed_at_utc=?,result_state=?,error_code=?,attempt_digest=?
            WHERE attempt_id=? AND lease_token=? AND result_state='started'
            """,
            failed_at,
            classification,
            error_code,
            digest(attempt_body),
            lease.attempt_id,
            lease.lease_token,
        )
        update_delivery = self._stmt(
            """
            UPDATE publication_deliveries
            SET delivery_state=?,last_error_code=?,lease_token=NULL,lease_until_utc=NULL
            WHERE publication_id=? AND lease_token=? AND delivery_state='pending'
            """,
            classification,
            error_code,
            lease.publication_id,
            lease.lease_token,
        )
        await self._db.batch([update_attempt, update_delivery])
        row = await self.get_delivery(lease.publication_id)
        if row is None:
            raise RuntimeError("Publication failure state was not persisted.")
        return row

    async def reconcile(
        self,
        publication_id: str,
        *,
        event_type: str,
        observed_at_utc: datetime,
        reason_code: str,
        telegram_message_id: int | None = None,
    ) -> dict[str, Any]:
        allowed = {"confirmed_sent", "confirmed_not_sent", "operator_hold", "operator_release"}
        if event_type not in allowed:
            raise ValueError("Unsupported reconciliation event.")
        row = await self.get_delivery(publication_id)
        if row is None:
            raise KeyError(f"Unknown publication_id: {publication_id}")
        observed = _iso(observed_at_utc)
        event = {
            "ledger_version": PUBLICATION_LEDGER_VERSION,
            "publication_id": publication_id,
            "event_type": event_type,
            "observed_at_utc": observed,
            "reason_code": reason_code,
            "telegram_message_id": telegram_message_id,
        }
        reconciliation_id = f"aidy_recon_{digest(event)[:32]}"
        insert = self._stmt(
            """
            INSERT INTO publication_reconciliation_events (
                reconciliation_id,publication_id,observed_at_utc,event_type,reason_code,telegram_message_id,event_digest
            ) VALUES (?,?,?,?,?,?,?)
            ON CONFLICT(reconciliation_id) DO NOTHING
            """,
            reconciliation_id,
            publication_id,
            observed,
            event_type,
            reason_code,
            telegram_message_id,
            digest(event),
        )
        if event_type == "confirmed_not_sent":
            update = self._stmt(
                """
                UPDATE publication_deliveries
                SET delivery_state='retryable_failed',last_error_code='reconciled_not_sent',
                    lease_token=NULL,lease_until_utc=NULL
                WHERE publication_id=? AND delivery_state='delivery_uncertain'
                """,
                publication_id,
            )
        elif event_type == "confirmed_sent":
            if telegram_message_id is None:
                raise ValueError("confirmed_sent requires telegram_message_id.")
            update = self._stmt(
                """
                UPDATE publication_deliveries
                SET delivery_state='sent',telegram_message_id=?,sent_at_utc=COALESCE(sent_at_utc,?),
                    transport=COALESCE(transport,'reconciled'),last_error_code=NULL,
                    lease_token=NULL,lease_until_utc=NULL
                WHERE publication_id=? AND delivery_state!='sent'
                """,
                int(telegram_message_id),
                observed,
                publication_id,
            )
        elif event_type == "operator_hold":
            update = self._stmt(
                """
                UPDATE publication_deliveries
                SET delivery_state='delivery_uncertain',last_error_code='operator_hold',
                    lease_token=NULL,lease_until_utc=NULL
                WHERE publication_id=? AND delivery_state!='sent'
                """,
                publication_id,
            )
        else:
            update = self._stmt(
                """
                UPDATE publication_deliveries
                SET delivery_state='retryable_failed',last_error_code='operator_release',
                    lease_token=NULL,lease_until_utc=NULL
                WHERE publication_id=? AND delivery_state='delivery_uncertain'
                """,
                publication_id,
            )
        await self._db.batch([insert, update])
        current = await self.get_delivery(publication_id)
        if current is None:
            raise RuntimeError("Reconciliation lost publication row.")
        return current


def _failure_classification(error: TelegramPublicationError) -> str:
    if error.code in {
        "telegram_chat_id_invalid",
        "telegram_token_invalid",
        "telegram_secret_forbidden",
        "telegram_transport_invalid",
    }:
        return "permanent_failed"
    # Day 50 intentionally redacts transport internals. A transport failure can
    # be ambiguous (Telegram may have accepted the send before the connection
    # failed), so automatic resend is forbidden until reconciliation confirms
    # the first attempt did not produce a message.
    return "delivery_uncertain"


async def deliver_with_ledger(
    envelope: Mapping[str, Any],
    *,
    store: D1PublicationLedgerStore,
    transport: TelegramTransport,
    now_utc: datetime,
) -> dict[str, Any]:
    """Persist, lease, send and settle one publication without blind retries."""
    delivery = await store.register_envelope(envelope, created_at_utc=now_utc)
    if delivery["delivery_state"] == "sent":
        return {"status": "already_sent", "delivery": delivery, "transport_called": False}

    lease = await store.acquire_attempt(str(envelope["publication_id"]), attempted_at_utc=now_utc)
    if lease.status != "acquired":
        return {"status": lease.status, "delivery": lease.delivery, "transport_called": False}

    try:
        sent = transport.send_message(
            chat_id=str(envelope["chat_id"]),
            text=str(envelope["message"]),
        )
        if str(sent.get("chat_id")) != str(envelope["chat_id"]):
            raise TelegramPublicationError(
                "telegram_transport_invalid",
                "Telegram returned a different destination.",
            )
        sent_at = _utc(sent.get("sent_at_utc"), name="sent_at_utc")  # type: ignore[arg-type]
        message_id = int(sent["message_id"])
        transport_name = str(sent.get("transport") or "unknown")
    except TelegramPublicationError as exc:
        failed = await store.record_failure(
            lease,
            error_code=exc.code,
            failed_at_utc=now_utc,
            classification=_failure_classification(exc),
        )
        return {
            "status": str(failed["delivery_state"]),
            "delivery": failed,
            "transport_called": True,
            "error_code": exc.code,
        }
    except Exception:  # noqa: BLE001 - unknown transport outcomes must fail closed as uncertain
        failed = await store.record_failure(
            lease,
            error_code="telegram_transport_unknown_exception",
            failed_at_utc=now_utc,
            classification="delivery_uncertain",
        )
        return {
            "status": "delivery_uncertain",
            "delivery": failed,
            "transport_called": True,
            "error_code": "telegram_transport_unknown_exception",
        }

    settled = await store.record_sent(
        lease,
        telegram_message_id=message_id,
        sent_at_utc=sent_at,
        transport=transport_name,
    )
    return {"status": "sent", "delivery": settled, "transport_called": True}


def reconstruct_exact_publication(delivery: Mapping[str, Any]) -> dict[str, Any]:
    required = (
        "publication_id",
        "decision_id",
        "message_digest",
        "envelope_digest",
        "group_name",
        "chat_id",
        "exact_message_text",
        "action",
        "source_state",
    )
    if any(delivery.get(key) is None for key in required):
        raise ValueError("Incomplete publication delivery row.")
    message = str(delivery["exact_message_text"])
    if digest(message) != str(delivery["message_digest"]):
        raise ValueError("Stored exact publication text does not match message digest.")
    return {
        "publication_id": str(delivery["publication_id"]),
        "decision_id": str(delivery["decision_id"]),
        "group_name": str(delivery["group_name"]),
        "chat_id": str(delivery["chat_id"]),
        "action": str(delivery["action"]),
        "source_state": str(delivery["source_state"]),
        "message": message,
        "message_digest": str(delivery["message_digest"]),
        "delivery_state": str(delivery["delivery_state"]),
    }


def day51_manifest() -> dict[str, Any]:
    manifest: dict[str, Any] = {
        "manifest_version": DAY51_MANIFEST_VERSION,
        "publication_ledger_version": PUBLICATION_LEDGER_VERSION,
        "storage": "cloudflare_d1",
        "decision_truth_separate_from_delivery_truth": True,
        "exact_message_text_persisted": True,
        "secret_values_persisted": False,
        "attempts_append_only_auditable": True,
        "successful_retry_duplicate_send_allowed": False,
        "ambiguous_transport_failure_auto_retry_allowed": False,
        "uncertain_delivery_requires_reconciliation": True,
        "confirmed_not_sent_becomes_retryable": True,
        "confirmed_sent_suppresses_retry": True,
        "lease_prevents_concurrent_blind_send": True,
        "no_trade_external_publication_allowed": False,
        "broker_dependency_allowed": False,
        "follower_dependency_allowed": False,
        "super_signals_dependency_allowed": False,
        "formal_forward_evidence_created": False,
    }
    manifest["manifest_digest"] = digest(manifest)
    return manifest
