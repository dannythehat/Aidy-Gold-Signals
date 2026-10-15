"""Day32 durable PRIVATE experiment research queue.

SQLite is authoritative; job specifications are immutable and content addressed.
This module schedules OPAQUE experiments and does not execute untrusted strategy
code, simulate broker fills or assert any observed gold trading profitability.
No customer tenant connector / online distributed scheduler is claimed here.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Self

SCHEMA = "aidy.strategy_lab.private_batch_queue.v1"
SYNTHETIC = "INTERNAL_SYNTHETIC_DIAGNOSTIC_ONLY"
ZERO = "0" * 64
TIMEFRAMES = frozenset(("M1", "M5", "M15", "H1", "H4", "D1"))
ACTIVE = ("RUNNING", "QUEUED")
TERMINAL = ("SUCCEEDED", "DEAD")
MAX_INFLIGHT = 4
MAX_PER_FAMILY = 2
MAX_NONTERMINAL = 100
MAX_ATTEMPTS = 3
LEASE_MS = 60000


def _json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=True,
                      separators=(",", ":"), allow_nan=False)


def _sha(obj: Any) -> str:
    return hashlib.sha256(_json(obj).encode("utf-8")).hexdigest()


def _valid_sha(x: str) -> bool:
    return isinstance(x, str) and len(x) == 64 and all(
        c in "0123456789abcdef" for c in x
    )


def _clock(t: int) -> None:
    if type(t) is not int or t < 0 or t > 10**15:
        raise ValueError("invalid explicit monotonic test clock")


def _params(p: Any) -> None:
    if not isinstance(p, dict) or len(p) > 16:
        raise ValueError("bounded object parameters only")
    for k, v in p.items():
        if not isinstance(k, str) or not k.isidentifier() or len(k) > 40:
            raise ValueError("invalid parameter name")
        if type(v) not in (str, int, bool) or (
            type(v) is str and len(v) > 64
        ) or (type(v) is int and abs(v) > 10**9):
            raise ValueError("unsafe or unbounded parameter value")


@dataclass(frozen=True)
class Experiment:
    family_id: str
    strategy_id: str
    strategy_rules_sha256: str
    market_input_sha256: str
    timeframe: str
    parameters: dict
    source_kind: str = SYNTHETIC

    def wire(self) -> dict:
        if (not 3 <= len(self.family_id) <= 80
                or not self.family_id.replace("_", "").replace("-", "").isalnum()
                or not 3 <= len(self.strategy_id) <= 80
                or not self.strategy_id.replace("_", "").replace("-", "").isalnum()
                or not _valid_sha(self.strategy_rules_sha256)
                or not _valid_sha(self.market_input_sha256)
                or self.timeframe not in TIMEFRAMES
                or self.source_kind != SYNTHETIC):
            raise ValueError("invalid qualified private synthetic experiment identity")
        _params(self.parameters)
        return {
            "schema": SCHEMA, "family_id": self.family_id,
            "strategy_id": self.strategy_id,
            "strategy_rules_sha256": self.strategy_rules_sha256,
            "market_input_sha256": self.market_input_sha256,
            "timeframe": self.timeframe,
            "parameters": self.parameters,
            "source_kind": SYNTHETIC,
        }

    def key(self) -> str:
        return _sha(self.wire())


class ResearchQueue:
    def __init__(self, path: Path):
        if not isinstance(path, Path) or str(path) in (":memory:", ""):
            raise ValueError("durable filesystem SQLite path required")
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), timeout=10, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA busy_timeout=10000")
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=FULL")
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY,
                family_id TEXT NOT NULL,
                source_json TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('QUEUED','RUNNING','SUCCEEDED','DEAD')),
                submitted_ms INTEGER NOT NULL,
                lease_until_ms INTEGER,
                lease_owner TEXT,
                lease_token TEXT,
                attempts INTEGER NOT NULL DEFAULT 0,
                result_json TEXT,
                result_sha256 TEXT,
                last_error TEXT
            );
            CREATE INDEX IF NOT EXISTS jobs_ready ON jobs(status, submitted_ms, job_id);
            CREATE INDEX IF NOT EXISTS jobs_family ON jobs(family_id, status);
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL,
                job_id TEXT NOT NULL,
                payload TEXT NOT NULL,
                prev_sha256 TEXT NOT NULL,
                event_sha256 TEXT NOT NULL
            );
        """)
        version = self.conn.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 32):
            raise ValueError("unexpected existing queue schema version")
        if version == 0:
            self.conn.execute("PRAGMA user_version=32")

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.conn.close()

    def _event(self, action: str, job: str, payload: dict) -> None:
        last = self.conn.execute(
            "SELECT event_sha256 FROM events ORDER BY id DESC LIMIT 1"
        ).fetchone()
        prev = last[0] if last else ZERO
        content = _json(payload)
        signature = _sha({
            "prev": prev, "action": action, "job_id": job, "payload": content,
        })
        self.conn.execute(
            "INSERT INTO events(action,job_id,payload,prev_sha256,event_sha256)"
            " VALUES(?,?,?,?,?)",
            (action, job, content, prev, signature),
        )

    def verify_events(self) -> dict:
        prev = ZERO
        n = 0
        for e in self.conn.execute("SELECT * FROM events ORDER BY id"):
            if e["prev_sha256"] != prev or e["event_sha256"] != _sha({
                "prev": prev, "action": e["action"], "job_id": e["job_id"],
                "payload": e["payload"],
            }):
                raise ValueError("append-only job event hash chain tampered")
            prev = e["event_sha256"]
            n += 1
        return {"event_count": n, "chain_tip_sha256": prev}

    def submit(self, spec: Experiment, now_ms: int) -> tuple[str, bool]:
        _clock(now_ms)
        if not isinstance(spec, Experiment):
            raise TypeError("typed private experiment required")
        source = spec.wire()
        job_id = _sha(source)
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            existing = self.conn.execute(
                "SELECT source_json FROM jobs WHERE job_id=?", (job_id,)
            ).fetchone()
            if existing:
                if existing[0] != _json(source):
                    raise ValueError("SHA collision or altered previous experiment")
                self.conn.execute("COMMIT")
                return job_id, False
            slots = self.conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE status IN ('QUEUED','RUNNING')"
            ).fetchone()[0]
            if slots >= MAX_NONTERMINAL:
                raise ValueError("private experiment quota exceeded")
            self.conn.execute(
                "INSERT INTO jobs(job_id,family_id,source_json,status,submitted_ms)"
                " VALUES(?,?,?,?,?)",
                (job_id, spec.family_id, _json(source), "QUEUED", now_ms),
            )
            self._event("SUBMIT", job_id, {"source_sha256": job_id})
            self.conn.execute("COMMIT")
            return job_id, True
        except Exception:
            self.conn.execute("ROLLBACK")
            raise

    def _recover_expired(self, now_ms: int) -> None:
        rows = self.conn.execute(
            "SELECT job_id, attempts FROM jobs WHERE status='RUNNING'"
            " AND lease_until_ms<=? ORDER BY job_id",
            (now_ms,),
        ).fetchall()
        for row in rows:
            next_status = "DEAD" if row["attempts"] >= MAX_ATTEMPTS else "QUEUED"
            self.conn.execute(
                "UPDATE jobs SET status=?, lease_owner=NULL, lease_token=NULL,"
                " lease_until_ms=NULL, last_error='LEASE_EXPIRED'"
                " WHERE job_id=?",
                (next_status, row["job_id"]),
            )
            self._event("LEASE_EXPIRED", row["job_id"], {
                "status": next_status, "attempts": row["attempts"],
            })

    def claim(self, worker: str, now_ms: int) -> dict | None:
        _clock(now_ms)
        if not isinstance(worker, str) or not 3 <= len(worker) <= 40 or not worker.isidentifier():
            raise ValueError("named private worker identity required")
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            self._recover_expired(now_ms)
            active = self.conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE status='RUNNING'"
            ).fetchone()[0]
            if active >= MAX_INFLIGHT:
                self.conn.execute("COMMIT")
                return None
            ready = self.conn.execute(
                "SELECT j.job_id,j.source_json,j.family_id,j.attempts"
                " FROM jobs j WHERE j.status='QUEUED'"
                " AND (SELECT COUNT(*) FROM jobs a WHERE a.status='RUNNING'"
                "      AND a.family_id=j.family_id)<?"
                " ORDER BY j.submitted_ms,j.job_id LIMIT 1",
                (MAX_PER_FAMILY,),
            ).fetchone()
            if ready is None:
                self.conn.execute("COMMIT")
                return None
            attempt = ready["attempts"] + 1
            # Fence stale completions with unique job / attempt / worker lease.
            token = _sha({"job": ready["job_id"], "attempt": attempt,
                          "worker": worker, "at_ms": now_ms})
            self.conn.execute(
                "UPDATE jobs SET status='RUNNING', attempts=?, lease_owner=?,"
                " lease_token=?, lease_until_ms=? WHERE job_id=? AND status='QUEUED'",
                (attempt, worker, token, now_ms+LEASE_MS, ready["job_id"]),
            )
            self._event("CLAIM", ready["job_id"], {
                "attempt": attempt, "worker": worker, "until_ms": now_ms+LEASE_MS,
            })
            self.conn.execute("COMMIT")
            return {
                "job_id": ready["job_id"], "attempt": attempt,
                "worker": worker, "lease_token": token,
                "source": json.loads(ready["source_json"]),
            }
        except Exception:
            self.conn.execute("ROLLBACK")
            raise

    def _require_lease(self, job: str, token: str, now_ms: int) -> sqlite3.Row:
        _clock(now_ms)
        row = self.conn.execute("SELECT * FROM jobs WHERE job_id=?", (job,)).fetchone()
        if (row is None or row["status"] != "RUNNING"
                or row["lease_token"] != token or row["lease_until_ms"] <= now_ms):
            raise ValueError("invalid, expired or superseded worker lease")
        return row

    def finish(self, job: str, token: str, now_ms: int, result: dict) -> str:
        if not isinstance(result, dict) or set(result) != {
            "job_id", "synthetic_diagnostic_score_bps", "source_kind",
        }:
            raise ValueError("only bounded synthetic research result permitted")
        value = result["synthetic_diagnostic_score_bps"]
        if (result["job_id"] != job or result["source_kind"] != SYNTHETIC
                or type(value) is not int or not -1000 <= value <= 1000):
            raise ValueError("no fabricated original-market trading results accepted")
        encoded = _json(result)
        digest = hashlib.sha256(encoded.encode()).hexdigest()
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            self._require_lease(job, token, now_ms)
            self.conn.execute(
                "UPDATE jobs SET status='SUCCEEDED', result_json=?, result_sha256=?,"
                " lease_owner=NULL, lease_token=NULL, lease_until_ms=NULL WHERE job_id=?",
                (encoded, digest, job),
            )
            self._event("FINISH", job, {"result_sha256": digest})
            self.conn.execute("COMMIT")
            return digest
        except Exception:
            self.conn.execute("ROLLBACK")
            raise

    def fail(self, job: str, token: str, now_ms: int, failure_code: str) -> str:
        if failure_code not in {"SYNTHETIC_EXECUTION_ERROR", "SYNTHETIC_TIMEOUT"}:
            raise ValueError("bounded failure code required")
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            row = self._require_lease(job, token, now_ms)
            status = "DEAD" if row["attempts"] >= MAX_ATTEMPTS else "QUEUED"
            self.conn.execute(
                "UPDATE jobs SET status=?, lease_owner=NULL, lease_token=NULL,"
                " lease_until_ms=NULL,last_error=? WHERE job_id=?",
                (status, failure_code, job),
            )
            self._event("FAIL", job, {"status": status, "code": failure_code})
            self.conn.execute("COMMIT")
            return status
        except Exception:
            self.conn.execute("ROLLBACK")
            raise

    def counts(self) -> dict[str, int]:
        result = {"QUEUED": 0, "RUNNING": 0, "SUCCEEDED": 0, "DEAD": 0}
        for row in self.conn.execute("SELECT status,COUNT(*) n FROM jobs GROUP BY status"):
            result[row["status"]] = row["n"]
        return result

    def compare(self, family_id: str | None = None) -> list[dict]:
        sql = "SELECT * FROM jobs WHERE status='SUCCEEDED'"
        params: tuple = ()
        if family_id is not None:
            sql += " AND family_id=?"
            params = (family_id,)
        runs = []
        for row in self.conn.execute(sql, params):
            source = json.loads(row["source_json"])
            result = json.loads(row["result_json"])
            encoded = _json(result)
            if (result["job_id"] != row["job_id"]
                    or row["result_sha256"] != hashlib.sha256(encoded.encode()).hexdigest()
                    or _sha(source) != row["job_id"]
                    or source["source_kind"] != SYNTHETIC):
                raise ValueError("source/result hash changed after synthetic trial")
            runs.append({
                "job_id": row["job_id"],
                "family_id": row["family_id"],
                "strategy_id": source["strategy_id"],
                "timeframe": source["timeframe"],
                "rules_sha256": source["strategy_rules_sha256"],
                "input_sha256": source["market_input_sha256"],
                "synthetic_diagnostic_score_bps": result["synthetic_diagnostic_score_bps"],
                "result_sha256": row["result_sha256"],
                "profitability_verified": False,
                "source_kind": SYNTHETIC,
            })
        return sorted(runs, key=lambda x: (-x["synthetic_diagnostic_score_bps"], x["job_id"]))
