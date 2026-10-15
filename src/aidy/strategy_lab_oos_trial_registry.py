"""Day26: one-shot append-only SQLite trial registry and holdout release gate.

A frozen study cannot be amended after test reveal. The database records an
immutable SHA256 chain; original-market outcomes are research diagnostics, not
execution or broker-verified strategy performance. This software gate is NOT a
privacy/security barrier to a user who already has raw warehouse access.
"""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path

from aidy.strategy_lab_oos_protocol import SealedOOS

SAFE = re.compile(r"^[a-zA-Z0-9_-]{3,80}$")


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _digest(value: object) -> str:
    return sha256(_canonical(value).encode()).hexdigest()


def _seal_event(prev_sha: str, key: str, kind: str, payload: str) -> str:
    return _digest({"prev_sha": prev_sha, "trial_key": key,
                    "kind": kind, "payload": payload})


class TrialRegistry:
    def __init__(self, path: Path) -> None:
        if not isinstance(path, Path):
            raise ValueError("trial registry requires on-disk SQLite path")
        self.path = path

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.execute("PRAGMA foreign_keys = ON")
            db.execute("""
                CREATE TABLE IF NOT EXISTS trial_events(
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    trial_key TEXT NOT NULL,
                    kind TEXT NOT NULL CHECK(kind IN ('register','freeze','reveal')),
                    payload_json TEXT NOT NULL,
                    previous_sha256 TEXT NOT NULL,
                    event_sha256 TEXT NOT NULL UNIQUE
                )
            """)
            db.execute("""
                CREATE TABLE IF NOT EXISTS trial_family_reservations(
                    source_sha256 TEXT NOT NULL,
                    family TEXT NOT NULL,
                    trial_key TEXT PRIMARY KEY,
                    UNIQUE(source_sha256,family)
                )
            """)
            for table in ("trial_events", "trial_family_reservations"):
                for action in ("UPDATE", "DELETE"):
                    db.execute(f"""
                        CREATE TRIGGER IF NOT EXISTS no_{action.lower()}_{table}
                        BEFORE {action} ON {table}
                        BEGIN SELECT RAISE(ABORT, 'research registry append only'); END;
                    """)
            db.commit()

    @staticmethod
    def _verify(db: sqlite3.Connection) -> tuple[list[sqlite3.Row], str]:
        db.row_factory = sqlite3.Row
        rows = db.execute("SELECT * FROM trial_events ORDER BY seq").fetchall()
        previous = "0" * 64
        state: dict[str, str] = {}
        seen = set()
        for i, row in enumerate(rows, 1):
            if row["seq"] != i or row["previous_sha256"] != previous:
                raise ValueError("trial registry order/chain is corrupt")
            digest = _seal_event(previous, row["trial_key"], row["kind"],
                                 row["payload_json"])
            if digest != row["event_sha256"]:
                raise ValueError("tampered research trial event SHA256 chain")
            payload = json.loads(row["payload_json"])
            if not isinstance(payload, dict):
                raise ValueError("untrusted trial payload")
            kind, key = row["kind"], row["trial_key"]
            if kind == "register":
                if key in seen:
                    raise ValueError("duplicate registered trial")
                seen.add(key)
                state[key] = "registered"
            elif kind == "freeze":
                if state.get(key) != "registered":
                    raise ValueError("trial was not exclusively registered")
                state[key] = "frozen"
            elif kind == "reveal":
                if state.get(key) != "frozen":
                    raise ValueError("holdout revealed without one-time freeze")
                state[key] = "revealed"
            else:
                raise ValueError("unknown trial event")
            previous = digest
        reservations = db.execute(
            "SELECT trial_key,source_sha256,family FROM trial_family_reservations"
        ).fetchall()
        registered = {r["trial_key"]: json.loads(r["payload_json"]) for r in rows
                      if r["kind"] == "register"}
        if len(reservations) != len(registered):
            raise ValueError("registry reservations do not match event lineage")
        for x in reservations:
            base = registered.get(x["trial_key"])
            if (base is None or base["source_sha256"] != x["source_sha256"]
                    or base["family"] != x["family"]):
                raise ValueError("tampered trial/family reservation")
        return rows, previous

    @staticmethod
    def _append(db: sqlite3.Connection, key: str, kind: str, obj: dict) -> str:
        _, previous = TrialRegistry._verify(db)
        payload = _canonical(obj)
        digest = _seal_event(previous, key, kind, payload)
        db.execute("""
            INSERT INTO trial_events(trial_key,kind,payload_json,previous_sha256,event_sha256)
            VALUES (?,?,?,?,?)
        """, (key, kind, payload, previous, digest))
        return digest

    def register(self, *, trial_key: str, family: str, study: SealedOOS) -> str:
        if not isinstance(study, SealedOOS) or not SAFE.fullmatch(trial_key) or not SAFE.fullmatch(family):
            raise ValueError("bounded stable trial and family identifiers required")
        review = study.review_development()
        obj = {
            "schema": "aidy.oos_trial_register.v1",
            "trial_key": trial_key, "family": family,
            "source_sha256": review.source_sha256,
            "policy_sha256": review.policy_sha256,
            "model_sha256": review.model_sha256,
            "development_sha256": review.development_sha256,
            "holdout_sha256": review.holdout_sha256,
            "holdout_first_utc": review.holdout_first_utc,
            "fold_evidence_sha256": review.fold_evidence_sha256,
        }
        self.initialize()
        with sqlite3.connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            self._verify(db)
            db.execute("""
                INSERT INTO trial_family_reservations(source_sha256,family,trial_key)
                VALUES (?,?,?)
            """, (review.source_sha256, family, trial_key))
            digest = self._append(db, trial_key, "register", obj)
            db.commit()
        return digest

    def _validate_read(self, db: sqlite3.Connection, key: str, study: SealedOOS):
        rows, _ = self._verify(db)
        own = [x for x in rows if x["trial_key"] == key]
        if not own or own[0]["kind"] != "register":
            raise ValueError("unregistered trial")
        baseline = json.loads(own[0]["payload_json"])
        review = study.review_development()
        for field in ("source_sha256", "policy_sha256", "model_sha256",
                      "development_sha256", "holdout_sha256", "holdout_first_utc",
                      "fold_evidence_sha256"):
            if baseline[field] != getattr(review, field):
                raise ValueError("frozen trial source, fold, label or policy mismatch")
        return own, review

    def freeze(self, trial_key: str, study: SealedOOS) -> str:
        if not SAFE.fullmatch(trial_key):
            raise ValueError("invalid trial ID")
        with sqlite3.connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            own, review = self._validate_read(db, trial_key, study)
            if len(own) != 1:
                raise ValueError("trial already frozen/revealed")
            digest = self._append(db, trial_key, "freeze", {
                "fold_evidence_sha256": review.fold_evidence_sha256,
                "development_sha256": review.development_sha256,
                "model_sha256": review.model_sha256,
                "holdout_commit_sha256": review.holdout_sha256,
                "freeze_status": "MODEL_AND_FOLDS_LOCKED_BEFORE_HOLDOUT",
            })
            db.commit()
        return digest

    def reveal_once(self, trial_key: str, study: SealedOOS) -> dict:
        if not SAFE.fullmatch(trial_key):
            raise ValueError("invalid trial ID")
        with sqlite3.connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            own, review = self._validate_read(db, trial_key, study)
            if len(own) != 2 or [x["kind"] for x in own] != ["register", "freeze"]:
                raise ValueError("holdout requires frozen unspent precommitment")
            frozen = json.loads(own[-1]["payload_json"])
            if (frozen["holdout_commit_sha256"] != review.holdout_sha256
                    or frozen["fold_evidence_sha256"] != review.fold_evidence_sha256):
                raise ValueError("frozen holdout/fold commitment changed")
            result = study._sealed_final_result()
            if result["holdout_labels_sha256"] != review.holdout_sha256:
                raise ValueError("revealed labels differ from sealed commitment")
            digest = self._append(db, trial_key, "reveal", {
                "sealed_oos_result": result,
                "frozen_register_event_sha256": own[0]["event_sha256"],
                "frozen_model_sha256": review.model_sha256,
            })
            db.commit()
            result["registered_one_time_reveal_sha256"] = digest
            return result

    def audit(self) -> dict:
        with sqlite3.connect(self.path) as db:
            records, tip = self._verify(db)
        return {
            "schema": "aidy.oos_trial_registry.v1",
            "event_count": len(records),
            "chain_tip_sha256": tip,
            "completed_holdout_reveals": sum(r["kind"] == "reveal" for r in records),
        }
