from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any

END_TO_END_RUNTIME_VERSION = "aidy_end_to_end_runtime_v1"
END_TO_END_STORE_VERSION = "aidy_end_to_end_cycle_store_v1"
ALLOWED_SOURCE_STATES = frozenset({"live_admitted", "dry_run", "private_forward", "shadow", "replay"})
ALLOWED_INSTRUCTION_TYPES = frozenset({"market_evaluation", "active_signal_management"})


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value: object) -> str:
    return sha256(canonical_json(value).encode()).hexdigest()


def _utc(value: datetime | str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        parsed = datetime.fromisoformat(value.strip())
    else:
        raise TypeError("Timestamp must be timezone-aware.")
    if parsed.tzinfo is None:
        raise ValueError("Timestamp must be timezone-aware.")
    return parsed.astimezone(UTC)


def end_to_end_cycle_id(
    *, instruction_type: str, source_state: str, subject_id: str, context_hash: str
) -> str:
    if instruction_type not in ALLOWED_INSTRUCTION_TYPES:
        raise ValueError("Unsupported instruction_type.")
    if source_state not in ALLOWED_SOURCE_STATES:
        raise ValueError("Unsupported source_state.")
    if not isinstance(subject_id, str) or not subject_id.strip():
        raise ValueError("subject_id is required.")
    if not isinstance(context_hash, str) or len(context_hash) != 64:
        raise ValueError("context_hash must be a sha256 digest.")
    identity = {
        "runtime_version": END_TO_END_RUNTIME_VERSION,
        "instruction_type": instruction_type,
        "source_state": source_state,
        "subject_id": subject_id.strip(),
        "context_hash": context_hash,
    }
    return f"aidy_e2e_{digest(identity)[:32]}"


class D1EndToEndCycleStore:
    """Durable restart journal for Day 52 orchestration.

    Trading truth remains in the immutable Day-34 ledger. This store records
    orchestration progress and exact immutable artifacts so a restart can reuse
    them instead of generating a second decision or publication.
    """

    def __init__(self, database: object) -> None:
        self._db = database

    def _stmt(self, sql: str, *params: object) -> object:
        return self._db.prepare(sql).bind(*params)

    async def _first(self, sql: str, *params: object) -> object:
        return await self._stmt(sql, *params).first()

    async def get(self, cycle_id: str) -> dict[str, Any] | None:
        row = await self._first(
            "SELECT * FROM aidy_end_to_end_cycles WHERE cycle_id=? LIMIT 1",
            cycle_id,
        )
        return dict(row) if isinstance(row, Mapping) else (dict(row) if row is not None else None)

    async def register(
        self,
        *,
        instruction_type: str,
        source_state: str,
        subject_id: str,
        context_hash: str,
        now_utc: datetime | str,
    ) -> dict[str, Any]:
        cycle_id = end_to_end_cycle_id(
            instruction_type=instruction_type,
            source_state=source_state,
            subject_id=subject_id,
            context_hash=context_hash,
        )
        stamp = _utc(now_utc).isoformat()
        await self._stmt(
            """
            INSERT INTO aidy_end_to_end_cycles (
                cycle_id,runtime_version,instruction_type,source_state,subject_id,
                context_hash,created_at_utc,updated_at_utc,cycle_state
            ) VALUES (?,?,?,?,?,?,?,?, 'registered')
            ON CONFLICT(cycle_id) DO NOTHING
            """,
            cycle_id,
            END_TO_END_RUNTIME_VERSION,
            instruction_type,
            source_state,
            subject_id,
            context_hash,
            stamp,
            stamp,
        ).run()
        row = await self.get(cycle_id)
        if row is None:
            raise RuntimeError("Failed to persist Day 52 cycle.")
        expected = {
            "runtime_version": END_TO_END_RUNTIME_VERSION,
            "instruction_type": instruction_type,
            "source_state": source_state,
            "subject_id": subject_id,
            "context_hash": context_hash,
        }
        if any(str(row.get(key)) != str(value) for key, value in expected.items()):
            raise RuntimeError("Day 52 cycle identity conflict.")
        return row

    async def _record_json_artifact(
        self,
        *,
        cycle_id: str,
        json_column: str,
        digest_column: str,
        payload: Mapping[str, Any],
        payload_digest: str,
        now_utc: datetime | str,
        extra: Mapping[str, object] | None = None,
    ) -> dict[str, Any]:
        allowed = {
            ("self_consistency_json", "self_consistency_digest"),
            ("ex_ante_json", "ex_ante_digest"),
            ("paper_state_json", "paper_state_digest"),
            ("watcher_receipt_json", "watcher_receipt_digest"),
            ("management_action_json", "management_action_digest"),
        }
        if (json_column, digest_column) not in allowed:
            raise ValueError("Unsupported Day 52 artifact slot.")
        text = canonical_json(payload)
        current = await self.get(cycle_id)
        if current is None:
            raise KeyError(f"Unknown cycle_id: {cycle_id}")
        existing_digest = current.get(digest_column)
        existing_json = current.get(json_column)
        if existing_digest is not None:
            if str(existing_digest) != payload_digest or str(existing_json) != text:
                raise RuntimeError(f"Immutable Day 52 artifact conflict in {json_column}.")
            return current

        assignments = [f"{json_column}=?", f"{digest_column}=?", "updated_at_utc=?"]
        params: list[object] = [text, payload_digest, _utc(now_utc).isoformat()]
        for key, value in (extra or {}).items():
            if key not in {"decision_id", "publication_id"}:
                raise ValueError("Unsupported Day 52 artifact identity field.")
            assignments.append(f"{key}=?")
            params.append(value)
        params.extend([cycle_id, None])
        sql = (
            f"UPDATE aidy_end_to_end_cycles SET {', '.join(assignments)} "
            f"WHERE cycle_id=? AND {digest_column} IS ?"
        )
        await self._stmt(sql, *params).run()
        row = await self.get(cycle_id)
        if row is None or str(row.get(digest_column)) != payload_digest:
            raise RuntimeError(f"Failed to settle Day 52 artifact {json_column}.")
        return row

    async def record_self_consistency(
        self, cycle_id: str, result: Mapping[str, Any], *, now_utc: datetime | str
    ) -> dict[str, Any]:
        return await self._record_json_artifact(
            cycle_id=cycle_id,
            json_column="self_consistency_json",
            digest_column="self_consistency_digest",
            payload=result,
            payload_digest=str(result["self_consistency_digest"]),
            now_utc=now_utc,
        )

    async def record_ex_ante(
        self, cycle_id: str, record: Mapping[str, Any], *, now_utc: datetime | str
    ) -> dict[str, Any]:
        return await self._record_json_artifact(
            cycle_id=cycle_id,
            json_column="ex_ante_json",
            digest_column="ex_ante_digest",
            payload=record,
            payload_digest=str(record["ex_ante_digest"]),
            now_utc=now_utc,
            extra={"decision_id": str(record["decision_id"])},
        )

    async def record_paper_state(
        self, cycle_id: str, state: Mapping[str, Any], *, now_utc: datetime | str
    ) -> dict[str, Any]:
        # Paper state may legitimately advance after observations; Day 52 entry
        # cycles record the opening snapshot only. Active management state is
        # versioned by its own Day-46/49 lifecycle contracts.
        return await self._record_json_artifact(
            cycle_id=cycle_id,
            json_column="paper_state_json",
            digest_column="paper_state_digest",
            payload=state,
            payload_digest=str(state["state_digest"]),
            now_utc=now_utc,
        )

    async def record_watcher_receipt(
        self, cycle_id: str, receipt: Mapping[str, Any], *, now_utc: datetime | str
    ) -> dict[str, Any]:
        return await self._record_json_artifact(
            cycle_id=cycle_id,
            json_column="watcher_receipt_json",
            digest_column="watcher_receipt_digest",
            payload=receipt,
            payload_digest=str(receipt["receipt_digest"]),
            now_utc=now_utc,
        )

    async def record_management_action(
        self, cycle_id: str, action: Mapping[str, Any], *, now_utc: datetime | str
    ) -> dict[str, Any]:
        return await self._record_json_artifact(
            cycle_id=cycle_id,
            json_column="management_action_json",
            digest_column="management_action_digest",
            payload=action,
            payload_digest=str(action["ledger_digest"]),
            now_utc=now_utc,
        )

    async def link_publication(
        self,
        cycle_id: str,
        publication_id: str,
        *,
        now_utc: datetime | str,
    ) -> dict[str, Any]:
        current = await self.get(cycle_id)
        if current is None:
            raise KeyError(f"Unknown cycle_id: {cycle_id}")
        existing = current.get("publication_id")
        if existing is not None and str(existing) != publication_id:
            raise RuntimeError("Day 52 publication identity conflict.")
        await self._stmt(
            """
            UPDATE aidy_end_to_end_cycles
            SET publication_id=COALESCE(publication_id,?),updated_at_utc=?
            WHERE cycle_id=?
            """,
            publication_id,
            _utc(now_utc).isoformat(),
            cycle_id,
        ).run()
        row = await self.get(cycle_id)
        if row is None or str(row.get("publication_id")) != publication_id:
            raise RuntimeError("Failed to link Day 52 publication.")
        return row

    async def mark_state(
        self,
        cycle_id: str,
        state: str,
        *,
        now_utc: datetime | str,
        error_code: str | None = None,
    ) -> dict[str, Any]:
        await self._stmt(
            """
            UPDATE aidy_end_to_end_cycles
            SET cycle_state=?,last_error_code=?,updated_at_utc=?
            WHERE cycle_id=?
            """,
            state,
            error_code,
            _utc(now_utc).isoformat(),
            cycle_id,
        ).run()
        row = await self.get(cycle_id)
        if row is None:
            raise RuntimeError("Failed to update Day 52 cycle state.")
        return row

    @staticmethod
    def decode_artifact(row: Mapping[str, Any], column: str) -> dict[str, Any] | None:
        value = row.get(column)
        if value is None:
            return None
        if not isinstance(value, str) or not value:
            raise RuntimeError(f"Invalid stored JSON in {column}.")
        decoded = json.loads(value)
        if not isinstance(decoded, dict):
            raise RuntimeError(f"Stored artifact {column} is not an object.")
        return copy.deepcopy(decoded)
