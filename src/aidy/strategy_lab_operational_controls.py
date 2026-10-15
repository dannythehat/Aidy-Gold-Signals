"""Day39 internal safety interlocks, audit events and local restore verification.

No legal or operational clearance is invented. This is not a live deployment
and cannot authorise payments, customer strategy execution or broker orders.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import sqlite3
from pathlib import Path

from aidy.strategy_lab_tenant_vault import AccessDenied, TenantVault, _canonical, _open_db

INCIDENT_LEVELS = frozenset({"INFO", "WARNING", "CRITICAL"})
ALLOWED_STATES = frozenset({"SAFE_HALT", "PRIVATE_RESEARCH_PAUSED"})
REQUIRED_EXTERNAL_GATES = (
    "all_12_stage_owner_signoffs",
    "real_payment_sandbox",
    "hosted_two_customer_penetration_test",
    "data_source_commercial_rights",
    "customer_contracts_privacy_regulatory_review",
    "encrypted_remote_restore_drill",
    "real_monthly_cloud_budget_alerts",
    "real_support_and_incident_notification",
    "consenting_user_pilot",
)


class OperationsRejected(ValueError):
    """Unsafe or insufficiently evidenced release rejected."""


class OperationalControls:
    """Server-side emergency safe halt, without any live service coupling."""

    def __init__(self, vault: TenantVault, *, operations_key: bytes):
        if not isinstance(operations_key, bytes) or len(operations_key) < 32:
            raise ValueError("Independent operational key required")
        if operations_key in (vault._pepper, vault._provision):
            raise ValueError("Shared identity keys prohibited")
        self._vault = vault
        self._key = operations_key
        with _open_db(vault._path) as con:
            con.executescript("""
            CREATE TABLE IF NOT EXISTS b11_operational_mode(
                id INTEGER PRIMARY KEY CHECK(id=1),
                state TEXT NOT NULL, updated INTEGER NOT NULL);
            INSERT OR IGNORE INTO b11_operational_mode VALUES(1,'SAFE_HALT',0);
            CREATE TABLE IF NOT EXISTS b11_operational_incidents(
                id TEXT PRIMARY KEY, level TEXT NOT NULL,
                event_digest TEXT NOT NULL, observed INTEGER NOT NULL,
                source_tag TEXT NOT NULL, state_after TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS b11_incidents_time
                ON b11_operational_incidents(observed,id);
            """)

    def _operator(self, key: bytes) -> None:
        if not isinstance(key, bytes) or not hmac.compare_digest(key, self._key):
            raise AccessDenied("Access denied")

    def incident(self, *, operator_key: bytes, level: str,
                 source_tag: str, summary: str) -> str:
        self._operator(operator_key)
        if (level not in INCIDENT_LEVELS
                or not isinstance(source_tag, str)
                or not re.fullmatch(r"[a-z][a-z0-9_.-]{2,63}", source_tag)
                or not isinstance(summary, str)
                or not 5 <= len(summary) <= 500
                or any(w in summary.lower() for w in (
                    "password=", "api_key=", "private key", "bearer ", "token=",
                ))):
            raise OperationsRejected("Unsafe incident evidence")
        now = int(self._vault._clock())
        identifier = secrets.token_hex(16)
        digest = hashlib.sha256(_canonical({
            "level": level, "source_tag": source_tag,
            "summary": summary, "timestamp": now, "id": identifier,
        })).hexdigest()
        with _open_db(self._vault._path) as con:
            con.execute("BEGIN IMMEDIATE")
            con.execute(
                "UPDATE b11_operational_mode SET state='SAFE_HALT',updated=? WHERE id=1",
                (now,),
            )
            con.execute(
                "INSERT INTO b11_operational_incidents VALUES(?,?,?,?,?,?)",
                (identifier, level, digest, now, source_tag, "SAFE_HALT"),
            )
            con.commit()
        return identifier

    def internal_state(self, *, operator_key: bytes) -> dict:
        self._operator(operator_key)
        with _open_db(self._vault._path) as con:
            row = con.execute("SELECT state,updated FROM b11_operational_mode "
                              "WHERE id=1").fetchone()
            count = con.execute("SELECT COUNT(*) FROM b11_operational_incidents").fetchone()[0]
        return {
            "private_mode": row["state"], "updated": row["updated"],
            "incident_records": count, "live_execution_allowed": False,
            "customer_checkout_allowed": False, "broker_orders_allowed": False,
        }

    def try_enable_public_launch(self, *_args: object, **_kwargs: object) -> None:
        """AIDY cannot self-certify missing legally material external facts."""
        raise OperationsRejected("External evidence + explicit owner go/no-go required")

    def launch_blockers(self, *, operator_key: bytes) -> dict:
        self._operator(operator_key)
        return {
            "status": "BLOCKED_EXTERIOR_EVIDENCE",
            "owner_public_launch_approved": False,
            "documented_external_gates_missing": list(REQUIRED_EXTERNAL_GATES),
            "live_server_deployed": False,
            "validity_of_economic_edges_claimed": False,
            "real_world_operational_recovery_certified": False,
            "private_mode": self.internal_state(operator_key=operator_key)["private_mode"],
        }

    def local_sqlite_backup(self, *, operator_key: bytes, backup_path: Path) -> dict:
        """Actual, isolated SQLite copy + count/digest integrity; not remote disaster recovery."""
        self._operator(operator_key)
        dest = Path(backup_path)
        if dest.exists() or dest.is_symlink():
            raise OperationsRejected("Backup destination already exists")
        dest.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if dest.parent.is_symlink():
            raise OperationsRejected("Backup directory symlink forbidden")
        with sqlite3.connect(self._vault._path) as source, sqlite3.connect(dest) as target:
            source.backup(target)
        digest = hashlib.sha256(dest.read_bytes()).hexdigest()
        with sqlite3.connect(dest) as con:
            status = con.execute("PRAGMA quick_check").fetchone()[0]
            original = con.execute("SELECT COUNT(*) FROM drafts").fetchone()[0]
            if status != "ok":
                raise OperationsRejected("Backup integrity failed")
        return {
            "scope": "ISOLATED_SQLITE_COPY_ONLY",
            "quick_check": status,
            "draft_count": original,
            "local_backup_sha256": digest,
            "remote_backup_restored": False,
            "encrypted_remote_key_recovery_proven": False,
        }
