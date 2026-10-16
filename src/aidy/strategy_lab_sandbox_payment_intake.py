"""Optional signed Stripe test-mode checkout event intake; never authorises billing.

Not an active provider connection, settlement checker, checkout creator or
subscription service. Every event remains unverified by the provider API.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable

TENANT_ID = re.compile(r"[0-9a-f]{32}\Z")
TEST_SESSION = re.compile(r"cs_test_[A-Za-z0-9]{8,150}\Z")
EVENT_ID = re.compile(r"evt_[A-Za-z0-9]{8,150}\Z")
SIGNATURE = re.compile(r"[0-9a-f]{64}\Z")
MAX_BODY = 128 * 1024
SCHEMA = "aidy.b11.signed_test_checkout_intake.v1"


class WebhookRejected(ValueError):
    """Malformed, untrusted or improperly scoped test event."""


def _strict_object(pairs: list[tuple[str, object]]) -> dict:
    output = {}
    for key, value in pairs:
        if key in output:
            raise WebhookRejected("Duplicate JSON key")
        output[key] = value
    return output


class SandboxPaymentIntake:
    """Operator-registered, test-mode, signed receipt journal; never grants paid access."""

    def __init__(
        self,
        database: Path,
        *,
        webhook_secret: bytes,
        operator_key: bytes,
        enabled: bool = False,
        clock: Callable[[], int] = lambda: int(time.time()),
    ):
        if not isinstance(database, Path):
            raise ValueError("Expected existing tenant SQLite database path")
        if (
            not isinstance(webhook_secret, bytes)
            or len(webhook_secret) < 24
            or not isinstance(operator_key, bytes)
            or len(operator_key) < 32
            or hmac.compare_digest(webhook_secret, operator_key)
            or type(enabled) is not bool
        ):
            raise ValueError("Independent endpoint and operator secrets required")
        if not database.is_file():
            raise ValueError("Tenant database must already exist")
        self._path = database
        self._secret = webhook_secret
        self._operator = operator_key
        self._enabled = enabled
        self._clock = clock
        with self._db() as con:
            if not con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='tenants'"
            ).fetchone():
                raise ValueError("Existing private tenant registry required")
            con.executescript("""
                CREATE TABLE IF NOT EXISTS b11_test_checkout_intents (
                    session_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL REFERENCES tenants(id),
                    registered_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS b11_test_webhook_receipts (
                    event_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES b11_test_checkout_intents(session_id),
                    tenant_id TEXT NOT NULL REFERENCES tenants(id),
                    body_sha256 TEXT NOT NULL,
                    received_at INTEGER NOT NULL,
                    status TEXT NOT NULL CHECK (status='SIGNED_TEST_EVENT_UNRECONCILED')
                );
                CREATE UNIQUE INDEX IF NOT EXISTS b11_test_one_completion_per_session
                    ON b11_test_webhook_receipts(session_id);
            """)

    @contextmanager
    def _db(self):
        con = sqlite3.connect(self._path, timeout=10.0)
        try:
            con.row_factory = sqlite3.Row
            con.execute("PRAGMA foreign_keys=ON")
            con.execute("PRAGMA busy_timeout=10000")
            with con:
                yield con
        finally:
            con.close()

    def register_expected_session(
        self, *, operator_key: bytes, tenant_id: str, session_id: str
    ) -> None:
        """Bind an externally created test session to a real tenant, with no charge."""
        if not isinstance(operator_key, bytes) or not hmac.compare_digest(
            operator_key, self._operator
        ):
            raise WebhookRejected("Operator authorisation required")
        if not self._enabled:
            raise WebhookRejected("Sandbox intake disabled")
        if (
            not isinstance(tenant_id, str)
            or not TENANT_ID.fullmatch(tenant_id)
            or not isinstance(session_id, str)
            or not TEST_SESSION.fullmatch(session_id)
        ):
            raise WebhookRejected("Only scoped existing test sessions supported")
        with self._db() as con:
            con.execute("BEGIN IMMEDIATE")
            if not con.execute("SELECT 1 FROM tenants WHERE id=?", (tenant_id,)).fetchone():
                raise WebhookRejected("Unknown tenant")
            old = con.execute(
                "SELECT tenant_id FROM b11_test_checkout_intents WHERE session_id=?",
                (session_id,),
            ).fetchone()
            if old and old["tenant_id"] != tenant_id:
                raise WebhookRejected("Checkout belongs to a different tenant")
            if not old:
                con.execute(
                    "INSERT INTO b11_test_checkout_intents VALUES(?,?,?)",
                    (session_id, tenant_id, int(self._clock())),
                )

    def _verify_signature(self, raw: bytes, header: str) -> None:
        if not isinstance(header, str) or len(header) > 2048:
            raise WebhookRejected("Invalid signature header")
        parts = [
            part.strip().split("=", 1)
            for part in header.split(",")
            if "=" in part
        ]
        stamps = [v for k, v in parts if k == "t"]
        sigs = [v for k, v in parts if k == "v1" and SIGNATURE.fullmatch(v)]
        if len(stamps) != 1 or not stamps[0].isdigit() or not sigs:
            raise WebhookRejected("Missing valid v1 Stripe-style signature")
        stamp = int(stamps[0])
        if abs(int(self._clock()) - stamp) > 300:
            raise WebhookRejected("Webhook timestamp outside tolerance")
        expected = hmac.new(
            self._secret, str(stamp).encode() + b"." + raw, hashlib.sha256
        ).hexdigest()
        if not any(hmac.compare_digest(s, expected) for s in sigs):
            raise WebhookRejected("Webhook signature mismatch")

    def record_signed_test_event(
        self, *, raw_body: bytes, signature_header: str
    ) -> dict:
        """Record a signed fixture/prospective sandbox event, never grant access."""
        if not self._enabled:
            raise WebhookRejected("Sandbox intake disabled")
        if not isinstance(raw_body, bytes) or not 0 < len(raw_body) <= MAX_BODY:
            raise WebhookRejected("Invalid raw webhook body")
        self._verify_signature(raw_body, signature_header)
        try:
            event = json.loads(
                raw_body.decode("utf-8"), object_pairs_hook=_strict_object
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WebhookRejected("Malformed event JSON") from exc
        if not isinstance(event, dict):
            raise WebhookRejected("Event must be an object")
        data = event.get("data")
        obj = data.get("object") if isinstance(data, dict) else None
        if not isinstance(obj, dict):
            raise WebhookRejected("Missing Checkout Session object")
        session_id = obj.get("id")
        metadata = obj.get("metadata")
        tenant_id = metadata.get("tenant_id") if isinstance(metadata, dict) else None
        event_id = event.get("id")
        if (
            not isinstance(event_id, str)
            or not EVENT_ID.fullmatch(event_id)
            or not isinstance(session_id, str)
            or not TEST_SESSION.fullmatch(session_id)
            or not isinstance(tenant_id, str)
            or not TENANT_ID.fullmatch(tenant_id)
            or event.get("object") != "event"
            or event.get("type") != "checkout.session.completed"
            or event.get("livemode") is not False
            or obj.get("object") != "checkout.session"
            or obj.get("livemode") is not False
            or obj.get("mode") not in ("payment", "subscription")
            or obj.get("payment_status") != "paid"
        ):
            raise WebhookRejected("Not a paid, correctly scoped test checkout completion")
        digest = hashlib.sha256(raw_body).hexdigest()
        with self._db() as con:
            con.execute("BEGIN IMMEDIATE")
            expected = con.execute(
                "SELECT tenant_id FROM b11_test_checkout_intents WHERE session_id=?",
                (session_id,),
            ).fetchone()
            if not expected or expected["tenant_id"] != tenant_id:
                raise WebhookRejected("Checkout session not registered for this tenant")
            prior = con.execute(
                "SELECT session_id,tenant_id,body_sha256 "
                "FROM b11_test_webhook_receipts WHERE event_id=?",
                (event_id,),
            ).fetchone()
            if prior:
                if (
                    prior["body_sha256"] != digest
                    or prior["tenant_id"] != tenant_id
                    or prior["session_id"] != session_id
                ):
                    raise WebhookRejected("Conflicting event-id replay")
            else:
                previous_session = con.execute(
                    "SELECT event_id FROM b11_test_webhook_receipts WHERE session_id=?",
                    (session_id,),
                ).fetchone()
                if previous_session:
                    raise WebhookRejected("Different completion already recorded")
                con.execute(
                    "INSERT INTO b11_test_webhook_receipts VALUES(?,?,?,?,?,?)",
                    (
                        event_id,
                        session_id,
                        tenant_id,
                        digest,
                        int(self._clock()),
                        "SIGNED_TEST_EVENT_UNRECONCILED",
                    ),
                )
        return {
            "schema": SCHEMA,
            "event_id": event_id,
            "session_id": session_id,
            "tenant_id": tenant_id,
            "sha256": digest,
            "status": "SIGNED_TEST_EVENT_UNRECONCILED",
            "actual_provider_delivery_verified": False,
            "provider_api_reconciliation_verified": False,
            "paid_access_unlocked": False,
            "original_day38_passed": False,
            "public_launch_allowed": False,
        }
