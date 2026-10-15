"""Day36: private, non-hosted B10 authentication and encrypted tenant draft vault.

This is an isolated *library*, not a public API deployment. No submitted code
is executed/fetched and nothing has a route to AIDY production or brokerage.
Every client operation derives tenant identity from a server-issued session.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Callable

from aidy.strategy_lab_customer_intake import prepare_intake, verify_draft

IDENTITY = re.compile(r"^[a-z][a-z0-9_.-]{2,59}$")
SCHEMA = "aidy.strategy_lab.tenant_vault.v1"
MAX_DRAFT_BYTES = 150_000
MAX_SESSION_SECONDS = 3600
MAX_RETENTION_SECONDS = 90 * 86400


class AccessDenied(PermissionError):
    """Fail-closed generic failure; never reveal another tenant's existence."""


class InvalidSubmission(ValueError):
    """Untrusted source validation failed."""


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


@contextmanager
def _open_db(path: Path):
    con = sqlite3.connect(str(path), timeout=5, isolation_level=None)
    try:
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        yield con
    finally:
        con.close()


class TenantVault:
    """Trusted-server boundary with no network or user-supplied Python execution."""

    def __init__(self, db_path: Path, *, encryption_key: bytes, token_pepper: bytes,
                 provision_key: bytes, clock: Callable[[], float] = time.time):
        # Keys are required from a trusted secret manager, not stored in SQLite.
        if not all(isinstance(v, bytes) and len(v) >= 32 for v in (
                encryption_key, token_pepper, provision_key)):
            raise ValueError("32-byte independent secrets required")
        if len(encryption_key) not in (16, 24, 32):
            raise ValueError("AES-GCM key must be 16/24/32 bytes")
        if len({encryption_key, token_pepper, provision_key}) != 3:
            raise ValueError("Separate encryption, token and provision keys required")
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        self._aes = AESGCM(encryption_key)
        self._pepper = token_pepper
        self._provision = provision_key
        self._clock = clock
        self._path = Path(db_path)
        self._path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self._path.is_symlink():
            raise ValueError("SQLite path must not be a symlink")
        with _open_db(self._path) as con:
            con.executescript("""
            CREATE TABLE IF NOT EXISTS tenants(
                id TEXT PRIMARY KEY, created INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS users(
                id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL REFERENCES tenants(id),
                username TEXT NOT NULL UNIQUE, salt BLOB NOT NULL,
                password_hash BLOB NOT NULL, created INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS sessions(
                token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
                expires INTEGER NOT NULL, revoked INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS attempts(
                username TEXT PRIMARY KEY, failures INTEGER NOT NULL,
                locked_until INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS drafts(
                id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL REFERENCES tenants(id),
                user_id TEXT NOT NULL REFERENCES users(id), created INTEGER NOT NULL,
                expires INTEGER NOT NULL, source_sha256 TEXT NOT NULL,
                blob BLOB NOT NULL, payload_sha256 TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS drafts_tenant_expiry ON drafts(tenant_id,expires);
            """)
        if os.name == "posix":
            os.chmod(self._path, 0o600)

    def provision(self, *, admin_key: bytes, username: str,
                  password: str, tenant_id: str | None = None) -> str:
        """Trusted administrative provisioning only. Never bind as public endpoint."""
        if not isinstance(admin_key, bytes) or not hmac.compare_digest(
                admin_key, self._provision):
            raise AccessDenied("Access denied")
        if not isinstance(username, str) or not IDENTITY.fullmatch(username):
            raise ValueError("Invalid username")
        if not isinstance(password, str) or len(password) < 12 or len(password) > 256:
            raise ValueError("Password policy rejected")
        tenant = tenant_id or uuid.uuid4().hex
        if not re.fullmatch(r"[0-9a-f]{32}", tenant):
            raise ValueError("Invalid tenant identifier")
        salt = secrets.token_bytes(16)
        verifier = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
        now = int(self._clock())
        with _open_db(self._path) as con:
            try:
                con.execute("BEGIN IMMEDIATE")
                con.execute("INSERT OR IGNORE INTO tenants VALUES(?,?)", (tenant, now))
                con.execute("INSERT INTO users VALUES(?,?,?,?,?,?)",
                            (uuid.uuid4().hex, tenant, username, salt, verifier, now))
                con.commit()
            except sqlite3.IntegrityError as exc:
                con.rollback()
                raise ValueError("Account cannot be provisioned") from exc
        return tenant

    def login(self, username: str, password: str) -> str:
        if not isinstance(username, str) or not IDENTITY.fullmatch(username):
            raise AccessDenied("Invalid credentials")
        if not isinstance(password, str) or len(password) > 256:
            raise AccessDenied("Invalid credentials")
        now = int(self._clock())
        with _open_db(self._path) as con:
            row = con.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
            attempts = con.execute("SELECT failures,locked_until FROM attempts WHERE username=?",
                                   (username,)).fetchone()
            if attempts and attempts["locked_until"] > now:
                raise AccessDenied("Invalid credentials")
            # Dummy scrypt prevents absent accounts receiving a cheap code path.
            salt = row["salt"] if row else b"\x00" * 16
            expected = row["password_hash"] if row else b"\x00" * 64
            derived = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
            if not row or not hmac.compare_digest(derived, expected):
                failures = (attempts["failures"] if attempts else 0) + 1
                delay = min(3600, 60 * (2 ** min(failures - 5, 5))) if failures >= 5 else 0
                con.execute("INSERT INTO attempts VALUES(?,?,?) ON CONFLICT(username) "
                            "DO UPDATE SET failures=excluded.failures,"
                            "locked_until=excluded.locked_until",
                            (username, failures, now + delay))
                raise AccessDenied("Invalid credentials")
            con.execute("DELETE FROM attempts WHERE username=?", (username,))
            token = secrets.token_urlsafe(32)
            con.execute("INSERT INTO sessions VALUES(?,?,?,0)",
                        (self._token_hash(token), row["id"], now + MAX_SESSION_SECONDS))
        return token

    def _token_hash(self, token: str) -> str:
        if not isinstance(token, str) or not 20 <= len(token) <= 120:
            raise AccessDenied("Access denied")
        return hmac.new(self._pepper, token.encode(), hashlib.sha256).hexdigest()

    def _principal(self, con: sqlite3.Connection, token: str) -> tuple[str, str]:
        row = con.execute(
            "SELECT u.id AS user_id,u.tenant_id FROM sessions s "
            "JOIN users u ON u.id=s.user_id "
            "WHERE s.token_hash=? AND s.revoked=0 AND s.expires>?",
            (self._token_hash(token), int(self._clock())),
        ).fetchone()
        if row is None:
            raise AccessDenied("Access denied")
        return row["user_id"], row["tenant_id"]

    def logout(self, token: str) -> None:
        with _open_db(self._path) as con:
            self._principal(con, token)
            con.execute("UPDATE sessions SET revoked=1 WHERE token_hash=?",
                        (self._token_hash(token),))

    @staticmethod
    def _revalidate_draft(draft: object) -> dict:
        if not isinstance(draft, dict):
            raise InvalidSubmission("Draft must be a JSON object")
        try:
            verify_draft(draft)
            source = draft["source"]
            mode = source["kind"]
            if mode == "upload":
                value = source["inert_text"].encode("utf-8")
            elif mode == "link":
                value = source["url"]
            elif mode == "template":
                value = source["template_id"]
            else:
                value = source["inert_text"]
            trusted = prepare_intake(
                mode=mode, value=value, title=draft["submission_title"],
                rules=draft["rules"], filename=source.get("source_name") or "",
                media_type=source.get("declared_media_type") or "",
                submitter_rights_declaration=draft["submitter_rights_declaration"],
            )
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise InvalidSubmission("Draft source not independently valid") from exc
        if _canonical(trusted) != _canonical(draft):
            raise InvalidSubmission("Draft is not original source revalidation")
        return trusted

    def submit_draft(self, token: str, draft: object, *,
                     retention_seconds: int = 30 * 86400) -> str:
        if type(retention_seconds) is not int or not 1 <= retention_seconds <= MAX_RETENTION_SECONDS:
            raise InvalidSubmission("Retention limit exceeded")
        validated = self._revalidate_draft(draft)
        plaintext = _canonical(validated)
        if len(plaintext) > MAX_DRAFT_BYTES:
            raise InvalidSubmission("Oversized draft")
        with _open_db(self._path) as con:
            user_id, tenant = self._principal(con, token)
            record_id = uuid.uuid4().hex
            aad = f"{SCHEMA}|{tenant}|{record_id}".encode()
            nonce = secrets.token_bytes(12)
            encrypted = nonce + self._aes.encrypt(nonce, plaintext, aad)
            now = int(self._clock())
            con.execute("INSERT INTO drafts VALUES(?,?,?,?,?,?,?,?)", (
                record_id, tenant, user_id, now, now + retention_seconds,
                validated["source"]["original_sha256"], encrypted,
                hashlib.sha256(plaintext).hexdigest(),
            ))
        return record_id

    def read_draft(self, token: str, record_id: str) -> dict:
        if not isinstance(record_id, str) or not re.fullmatch(r"[0-9a-f]{32}", record_id):
            raise AccessDenied("Access denied")
        with _open_db(self._path) as con:
            _, tenant = self._principal(con, token)
            row = con.execute(
                "SELECT blob,payload_sha256 FROM drafts "
                "WHERE id=? AND tenant_id=? AND expires>?",
                (record_id, tenant, int(self._clock())),
            ).fetchone()
        if row is None:
            raise AccessDenied("Access denied")
        aad = f"{SCHEMA}|{tenant}|{record_id}".encode()
        from cryptography.exceptions import InvalidTag

        try:
            raw = self._aes.decrypt(row["blob"][:12], row["blob"][12:], aad)
        except (InvalidTag, ValueError) as exc:
            # Never expose AES error details or another tenant's record.
            raise AccessDenied("Access denied") from exc
        if not hmac.compare_digest(hashlib.sha256(raw).hexdigest(), row["payload_sha256"]):
            raise AccessDenied("Access denied")
        return json.loads(raw)

    def list_drafts(self, token: str) -> list[dict]:
        with _open_db(self._path) as con:
            _, tenant = self._principal(con, token)
            rows = con.execute(
                "SELECT id,created,expires FROM drafts "
                "WHERE tenant_id=? AND expires>? ORDER BY created,id",
                (tenant, int(self._clock())),
            ).fetchall()
        return [dict(r) for r in rows]

    def delete_draft(self, token: str, record_id: str) -> None:
        if not isinstance(record_id, str) or not re.fullmatch(r"[0-9a-f]{32}", record_id):
            raise AccessDenied("Access denied")
        with _open_db(self._path) as con:
            _, tenant = self._principal(con, token)
            cursor = con.execute("DELETE FROM drafts WHERE tenant_id=? AND id=?",
                                 (tenant, record_id))
            if cursor.rowcount != 1:
                raise AccessDenied("Access denied")

    def purge_expired(self, *, admin_key: bytes) -> tuple[int, int]:
        if not isinstance(admin_key, bytes) or not hmac.compare_digest(
                admin_key, self._provision):
            raise AccessDenied("Access denied")
        now = int(self._clock())
        with _open_db(self._path) as con:
            deleted = con.execute("DELETE FROM drafts WHERE expires<=?", (now,)).rowcount
            sessions = con.execute(
                "DELETE FROM sessions WHERE expires<=? OR revoked=1", (now,)
            ).rowcount
        # SQLite deletes are logical; secure erasure of underlying backup/WAL
        # requires separately managed disk encryption and retention controls.
        return deleted, sessions
