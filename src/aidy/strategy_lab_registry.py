"""AIDY Strategy Lab Day10: isolated SQLite versioned strategy/source registry.

Append-only ordinary-application protection and content-addressed read checks.
SQLite is NOT tamper-proof against a privileged database/file-system administrator.
No broker, production AIDY service, network or untrusted-code execution.
"""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from aidy.strategy_lab_rule_validator import assess_rule_completeness
from aidy.strategy_lab_spec import StrategySpec

REGISTRY_VERSION = "aidy.strategy_registry.v1"
RULE_FIELDS = ("market", "warmup_closed_bars", "indicators", "long", "short",
               "sessions", "sizing", "portfolio", "execution")
REQUIRED_TRIGGERS = frozenset({
    "versions_no_update", "versions_no_delete",
    "source_snapshots_no_update", "source_snapshots_no_delete",
})


class RegistryIntegrityError(ValueError):
    """A stored record or version chain fails self-integrity verification."""


class RegistryConflictError(ValueError):
    """A version ID already exists with different bytes, or revisions skip."""


@dataclass(frozen=True, slots=True)
class VersionRecord:
    strategy_id: str
    revision: int
    version_id: str
    spec_sha256: str
    rules_sha256: str
    original_source_sha256: str
    previous_version_sha256: str | None
    author: str
    source_snapshot_ref: str
    canonical_spec_json: str

    def to_wire(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "revision": self.revision,
            "version_id": self.version_id,
            "spec_sha256": self.spec_sha256,
            "rules_sha256": self.rules_sha256,
            "original_source_sha256": self.original_source_sha256,
            "previous_version_sha256": self.previous_version_sha256,
            "author": self.author,
            "source_snapshot_ref": self.source_snapshot_ref,
            "canonical_spec_json": self.canonical_spec_json,
        }


def _digest(data: bytes) -> str:
    return sha256(data).hexdigest()


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _version_identity(strategy_id: str, revision: int, spec_hash: str,
                      rules_hash: str, source_hash: str, previous: str | None) -> str:
    payload = _canonical({
        "registry_version": REGISTRY_VERSION, "strategy_id": strategy_id,
        "revision": revision, "spec_sha256": spec_hash,
        "rules_sha256": rules_hash, "original_source_sha256": source_hash,
        "previous_version_sha256": previous,
    })
    return "aidy-v1-" + _digest(payload.encode("utf-8"))


def _create_record(spec: StrategySpec, previous: str | None) -> VersionRecord:
    wire = spec.to_wire()
    canonical = spec.to_json()
    spec_hash = _digest(canonical.encode("utf-8"))
    rules_hash = _digest(
        b"aidy.strategy_rules.v1\x00"
        + _canonical({k: wire[k] for k in RULE_FIELDS}).encode("utf-8")
    )
    source_hash = spec.origin.source_sha256
    return VersionRecord(
        spec.strategy_id, spec.revision,
        _version_identity(spec.strategy_id, spec.revision,
                          spec_hash, rules_hash, source_hash, previous),
        spec_hash, rules_hash, source_hash, previous,
        spec.origin.author, spec.origin.source_snapshot_ref or "", canonical,
    )


@contextmanager
def _connection(path: Path) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(str(path), timeout=20)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=20000")
        yield conn
    finally:
        conn.close()


class StrategyRegistry:
    """Local research registry. Call initialize() once, then register/read.

    The owner may later move the same schema and frozen identifiers into a
    tenant-isolated transactional store; this initial real backend is SQLite.
    """

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with _connection(self.db_path) as conn, conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS source_snapshots (
                    source_sha256 TEXT PRIMARY KEY NOT NULL,
                    original_bytes BLOB NOT NULL CHECK(length(original_bytes) > 0)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS versions (
                    strategy_id TEXT NOT NULL,
                    revision INTEGER NOT NULL CHECK(revision >= 1),
                    version_id TEXT UNIQUE NOT NULL,
                    spec_sha256 TEXT NOT NULL,
                    rules_sha256 TEXT NOT NULL,
                    original_source_sha256 TEXT NOT NULL
                        REFERENCES source_snapshots(source_sha256),
                    previous_version_sha256 TEXT,
                    author TEXT NOT NULL,
                    source_snapshot_ref TEXT NOT NULL,
                    canonical_spec_json TEXT NOT NULL,
                    PRIMARY KEY(strategy_id, revision)
                )
            """)
            for table in ("versions", "source_snapshots"):
                for operation in ("UPDATE", "DELETE"):
                    name = f"{table}_no_{operation.lower()}"
                    conn.execute(f"""
                        CREATE TRIGGER IF NOT EXISTS {name}
                        BEFORE {operation} ON {table}
                        BEGIN
                            SELECT RAISE(ABORT, 'append-only research registry');
                        END
                    """)
            self._check_guards(conn)

    @staticmethod
    def _check_guards(conn: sqlite3.Connection) -> None:
        actual = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger'"
        )}
        if not REQUIRED_TRIGGERS.issubset(actual):
            raise RegistryIntegrityError("append-only registry guards are missing")

    @staticmethod
    def _verify_row(conn: sqlite3.Connection, row: sqlite3.Row) -> VersionRecord:
        try:
            raw = row["canonical_spec_json"]
            spec = StrategySpec.from_json(raw)
            if spec.to_json() != raw:
                raise RegistryIntegrityError("stored specification is not canonical")
            record = _create_record(spec, row["previous_version_sha256"])
            for key, expected in record.to_wire().items():
                if row[key] != expected:
                    raise RegistryIntegrityError(f"stored record mismatch: {key}")
            source = conn.execute(
                "SELECT original_bytes FROM source_snapshots WHERE source_sha256=?",
                (record.original_source_sha256,),
            ).fetchone()
            if source is None or _digest(source["original_bytes"]) != record.original_source_sha256:
                raise RegistryIntegrityError("original source bytes changed or missing")
            assessment = assess_rule_completeness(
                spec, source_snapshot=source["original_bytes"]
            )
            if not assessment.ready_for_later_reproduction:
                raise RegistryIntegrityError("stored rule admission no longer validates")
            return record
        except (TypeError, KeyError, AttributeError, ValueError) as exc:
            if isinstance(exc, RegistryIntegrityError):
                raise
            raise RegistryIntegrityError("stored strategy/source has invalid structure") from exc

    @classmethod
    def _verified_history(cls, conn: sqlite3.Connection,
                          strategy_id: str) -> tuple[VersionRecord, ...]:
        rows = conn.execute("""
            SELECT * FROM versions WHERE strategy_id=? ORDER BY revision ASC
        """, (strategy_id,)).fetchall()
        records: list[VersionRecord] = []
        for row in rows:
            record = cls._verify_row(conn, row)
            if record.revision != len(records) + 1:
                raise RegistryIntegrityError("noncontiguous version history")
            expected_previous = records[-1].version_id if records else None
            if record.previous_version_sha256 != expected_previous:
                raise RegistryIntegrityError("previous-version chain mismatch")
            records.append(record)
        return tuple(records)

    def register(self, spec: StrategySpec, source_bytes: bytes) -> VersionRecord:
        """Atomically persist a byte-qualified complete spec or exact idempotent repeat."""
        if not isinstance(source_bytes, bytes) or not source_bytes:
            raise ValueError("original source snapshot must be nonempty bytes")
        assessment = assess_rule_completeness(spec, source_snapshot=source_bytes)
        if not assessment.ready_for_later_reproduction:
            raise ValueError(
                "incomplete/unqualified strategy: "
                + ",".join(sorted({i.code for i in assessment.issues}))
            )
        # Canonical conversion additionally checks for unchecked direct dataclasses.
        spec = StrategySpec.from_json(spec.to_json())
        with _connection(self.db_path) as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                self._check_guards(conn)
                history = self._verified_history(conn, spec.strategy_id)
                expected_prev = history[-1].version_id if history else None
                record = _create_record(spec, expected_prev)
                if spec.revision <= len(history):
                    existing = history[spec.revision - 1]
                    if existing != record:
                        raise RegistryConflictError(
                            "strategy revision already exists with different rule/source bytes"
                        )
                    conn.commit()
                    return existing
                if spec.revision != len(history) + 1:
                    raise RegistryConflictError("revision must start at 1 and increase by exactly 1")
                source_sha = _digest(source_bytes)
                if source_sha != record.original_source_sha256:
                    raise RegistryIntegrityError("source hash drift before write")
                existing_source = conn.execute(
                    "SELECT original_bytes FROM source_snapshots WHERE source_sha256=?",
                    (source_sha,),
                ).fetchone()
                if existing_source is not None:
                    if existing_source["original_bytes"] != source_bytes:
                        raise RegistryIntegrityError("colliding or altered source content")
                else:
                    conn.execute(
                        "INSERT INTO source_snapshots(source_sha256, original_bytes) VALUES (?,?)",
                        (source_sha, source_bytes),
                    )
                conn.execute("""
                    INSERT INTO versions (
                        strategy_id, revision, version_id, spec_sha256, rules_sha256,
                        original_source_sha256, previous_version_sha256, author,
                        source_snapshot_ref, canonical_spec_json
                    ) VALUES (?,?,?,?,?,?,?,?,?,?)
                """, tuple(record.to_wire()[name] for name in (
                    "strategy_id", "revision", "version_id", "spec_sha256",
                    "rules_sha256", "original_source_sha256", "previous_version_sha256",
                    "author", "source_snapshot_ref", "canonical_spec_json"
                )))
                conn.commit()
                return record
            except BaseException:
                conn.rollback()
                raise

    def versions(self, strategy_id: str) -> tuple[VersionRecord, ...]:
        with _connection(self.db_path) as conn:
            self._check_guards(conn)
            return self._verified_history(conn, strategy_id)

    def source_bytes(self, strategy_id: str, revision: int) -> bytes:
        versions = self.versions(strategy_id)
        if not 1 <= revision <= len(versions):
            raise KeyError("strategy revision unavailable")
        record = versions[revision - 1]
        with _connection(self.db_path) as conn:
            self._check_guards(conn)
            row = conn.execute(
                "SELECT original_bytes FROM source_snapshots WHERE source_sha256=?",
                (record.original_source_sha256,),
            ).fetchone()
            if row is None or _digest(row["original_bytes"]) != record.original_source_sha256:
                raise RegistryIntegrityError("original source snapshot integrity failed")
            return bytes(row["original_bytes"])

    def verify_all(self) -> tuple[VersionRecord, ...]:
        """Verify every stored strategy, original bytes and contiguous revision chain."""
        with _connection(self.db_path) as conn:
            self._check_guards(conn)
            keys = [r["strategy_id"] for r in conn.execute(
                "SELECT DISTINCT strategy_id FROM versions ORDER BY strategy_id"
            )]
            result: list[VersionRecord] = []
            for strategy_id in keys:
                result.extend(self._verified_history(conn, strategy_id))
            orphaned = conn.execute("""
                SELECT COUNT(*) n FROM source_snapshots s
                WHERE NOT EXISTS (
                    SELECT 1 FROM versions v
                    WHERE v.original_source_sha256 = s.source_sha256
                )
            """).fetchone()["n"]
            if orphaned:
                raise RegistryIntegrityError("orphaned source snapshot found")
            return tuple(result)
