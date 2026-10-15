"""Day39 encrypted SQLite snapshot and restoration for isolated synthetic lab data.

The complete plaintext database is held in memory and never written as a
temporary backup file. This is a bounded local restore primitive, not certified
production remote disaster recovery, key escrow, licence verification or a
hosted customer database migration.
"""
from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from aidy.strategy_lab_operational_controls import OperationalControls, OperationsRejected
from aidy.strategy_lab_tenant_vault import AccessDenied, TenantVault

MAGIC = b"AIDY-SQLITE-SNAPSHOT-V1\n"
AAD = b"AIDY|DAY39|ENCRYPTED_SNAPSHOT|V1"
MAX_BACKUP_SIZE = 16 * 1024 * 1024


def _safe_new_path(destination: Path) -> Path:
    dest = Path(destination)
    if dest.exists() or dest.is_symlink():
        raise OperationsRejected("Destination must be a new private file")
    dest.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if dest.parent.is_symlink():
        raise OperationsRejected("Private directory symlink forbidden")
    return dest


def _new_file(dest: Path, payload: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(dest, flags, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
    except BaseException:
        dest.unlink(missing_ok=True)
        raise


class EncryptedSnapshot:
    def __init__(self, controls: OperationalControls, *, backup_key: bytes):
        if not isinstance(backup_key, bytes) or len(backup_key) != 32:
            raise ValueError("Independent AES-256 backup key required")
        if backup_key in (
            controls._key, controls._vault._pepper,
            controls._vault._provision,
        ):
            raise ValueError("Backup key cannot reuse operational or identity secrets")
        self._controls = controls
        self._cipher = AESGCM(backup_key)

    def create(self, *, operator_key: bytes, destination: Path) -> dict:
        self._controls._operator(operator_key)
        dest = _safe_new_path(destination)
        with sqlite3.connect(self._controls._vault._path) as source:
            with sqlite3.connect(":memory:") as memory:
                source.backup(memory)
                if memory.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise OperationsRejected("SQLite memory snapshot integrity failed")
                plaintext = memory.serialize()
        if not 1 <= len(plaintext) <= MAX_BACKUP_SIZE:
            raise OperationsRejected("Snapshot requires separately reviewed streaming backup")
        nonce = secrets.token_bytes(12)
        encrypted = MAGIC + nonce + self._cipher.encrypt(nonce, plaintext, AAD)
        _new_file(dest, encrypted)
        return {
            "status": "ENCRYPTED_LOCAL_SNAPSHOT",
            "ciphertext_sha256": hashlib.sha256(encrypted).hexdigest(),
            "ciphertext_bytes": len(encrypted),
            "plain_database_bytes": len(plaintext),
            "external_cloud_storage_confirmed": False,
            "production_remote_restore_certified": False,
        }

    def restore(self, *, operator_key: bytes, source: Path,
                destination: Path) -> dict:
        self._controls._operator(operator_key)
        target = _safe_new_path(destination)
        blob = Path(source).read_bytes()
        if (not blob.startswith(MAGIC)
                or not len(MAGIC) + 12 + 16 < len(blob)
                or len(blob) > MAX_BACKUP_SIZE + 1024):
            raise OperationsRejected("Invalid encrypted snapshot")
        nonce = blob[len(MAGIC):len(MAGIC) + 12]
        try:
            raw = self._cipher.decrypt(nonce, blob[len(MAGIC) + 12:], AAD)
        except (ValueError, InvalidTag) as exc:
            raise AccessDenied("Snapshot cannot be authenticated") from exc
        if not 1 <= len(raw) <= MAX_BACKUP_SIZE:
            raise OperationsRejected("Snapshot exceeds reviewed safe limit")
        with sqlite3.connect(":memory:") as memory:
            try:
                memory.deserialize(raw)
                if memory.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise OperationsRejected("Restored snapshot failed integrity")
                if not memory.execute("SELECT 1 FROM sqlite_master WHERE name='drafts'").fetchone():
                    raise OperationsRejected("Expected strategy draft table missing")
                fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
                os.close(fd)
                try:
                    with sqlite3.connect(target) as output:
                        memory.backup(output)
                except BaseException:
                    target.unlink(missing_ok=True)
                    raise
            except (sqlite3.Error, ValueError) as exc:
                target.unlink(missing_ok=True)
                raise OperationsRejected("Invalid SQLite backup content") from exc
        return {
            "status": "RESTORED_TO_ISOLATED_LOCAL_DATABASE",
            "ciphertext_sha256": hashlib.sha256(blob).hexdigest(),
            "sqlite_quick_check": "ok",
            "production_remote_restore_certified": False,
        }
