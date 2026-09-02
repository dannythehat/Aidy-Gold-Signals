from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from hashlib import sha256
from typing import Any

ANCHOR_VERSION = "aidy_research_ledger_anchor_v1"
LEDGER_VERSION = "aidy_research_ledger_v1"
GENESIS_RECORD_DIGEST = "daa8478ee4932bb5fabd83396abc29cdc38fca2e5b913fb78a0e4e2c80458406"
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA64 = re.compile(r"^[0-9a-f]{64}$")


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _digest(value: object) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def build_anchor(
    *,
    anchored_sequence: int,
    anchored_record_digest: str,
    raw_attempted_trials_floor: int,
    ledger_code_head_sha: str,
    anchor_parent_head_sha: str,
    recorded_at_utc: str,
    d1_table: str = "research_evidence_ledger",
) -> dict[str, Any]:
    if anchored_sequence < 0:
        raise ValueError("anchored_sequence must be non-negative")
    if raw_attempted_trials_floor < 0:
        raise ValueError("raw_attempted_trials_floor must be non-negative")
    if not _SHA64.fullmatch(anchored_record_digest):
        raise ValueError("anchored_record_digest must be a SHA-256 hex digest")
    if not _SHA40.fullmatch(ledger_code_head_sha):
        raise ValueError("ledger_code_head_sha must be a 40-character git SHA")
    if not _SHA40.fullmatch(anchor_parent_head_sha):
        raise ValueError("anchor_parent_head_sha must be a 40-character git SHA")
    body: dict[str, Any] = {
        "anchor_version": ANCHOR_VERSION,
        "ledger_version": LEDGER_VERSION,
        "anchor_kind": "repository_checkpoint",
        "anchored_sequence": int(anchored_sequence),
        "anchored_record_digest": anchored_record_digest,
        "genesis_record_digest": GENESIS_RECORD_DIGEST,
        "raw_attempted_trials_floor": int(raw_attempted_trials_floor),
        "ledger_code_head_sha": ledger_code_head_sha,
        "anchor_parent_head_sha": anchor_parent_head_sha,
        "recorded_at_utc": recorded_at_utc,
        "d1_table": d1_table,
    }
    body["anchor_digest"] = _digest(body)
    return body


def verify_anchor(anchor: Mapping[str, Any]) -> bool:
    body = dict(anchor)
    supplied = str(body.pop("anchor_digest", ""))
    if not _SHA64.fullmatch(supplied):
        return False
    if body.get("anchor_version") != ANCHOR_VERSION:
        return False
    if body.get("ledger_version") != LEDGER_VERSION:
        return False
    if body.get("anchor_kind") != "repository_checkpoint":
        return False
    if body.get("genesis_record_digest") != GENESIS_RECORD_DIGEST:
        return False
    try:
        sequence = int(body["anchored_sequence"])
        raw_floor = int(body["raw_attempted_trials_floor"])
    except (KeyError, TypeError, ValueError):
        return False
    if sequence < 0 or raw_floor < 0:
        return False
    if not _SHA64.fullmatch(str(body.get("anchored_record_digest") or "")):
        return False
    if not _SHA40.fullmatch(str(body.get("ledger_code_head_sha") or "")):
        return False
    if not _SHA40.fullmatch(str(body.get("anchor_parent_head_sha") or "")):
        return False
    return supplied == _digest(body)


def _row_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    row = dict(value)
    payload = row.get("payload")
    if payload is None and isinstance(row.get("payload_json"), str):
        payload = json.loads(str(row["payload_json"]))
    row["payload"] = payload if isinstance(payload, Mapping) else {}
    return row


def verify_ledger_against_anchor(
    rows: Iterable[Mapping[str, Any]], *, anchor: Mapping[str, Any]
) -> dict[str, Any]:
    if not verify_anchor(anchor):
        raise ValueError("repository ledger anchor is invalid")
    normalized = sorted((_row_mapping(row) for row in rows), key=lambda row: int(row["sequence"]))
    if not normalized:
        raise ValueError("research ledger is empty but repository anchor exists")
    by_sequence = {int(row["sequence"]): row for row in normalized}
    anchor_sequence = int(anchor["anchored_sequence"])
    if max(by_sequence) < anchor_sequence:
        raise ValueError("research ledger rollback detected: sequence behind repository anchor")
    anchored_row = by_sequence.get(anchor_sequence)
    if anchored_row is None:
        raise ValueError("research ledger rollback/rewrite detected: anchored sequence missing")
    if str(anchored_row.get("record_digest") or "") != str(anchor["anchored_record_digest"]):
        raise ValueError("research ledger rewrite detected: anchored digest mismatch")
    genesis = by_sequence.get(0)
    if genesis is None or str(genesis.get("record_digest") or "") != GENESIS_RECORD_DIGEST:
        raise ValueError("research ledger genesis mismatch")

    raw_trials = sum(
        1
        for row in normalized
        if str(row.get("record_type") or "") == "trial_started"
    )
    if raw_trials < int(anchor["raw_attempted_trials_floor"]):
        raise ValueError("research ledger rollback detected: raw trial count below repository anchor")
    return {
        "state": "consistent_with_repository_anchor",
        "latest_sequence": max(by_sequence),
        "anchored_sequence": anchor_sequence,
        "raw_attempted_trials": raw_trials,
        "raw_attempted_trials_floor": int(anchor["raw_attempted_trials_floor"]),
        "anchor_digest": anchor["anchor_digest"],
    }
