from __future__ import annotations

import json
from pathlib import Path

import pytest

from aidy.research_ledger_anchor import (
    GENESIS_RECORD_DIGEST,
    verify_anchor,
    verify_ledger_against_anchor,
)

ANCHOR_PATH = Path(
    "evidence/research_ledger/anchors/day53-step0-repository-checkpoint.json"
)


def _anchor() -> dict:
    return json.loads(ANCHOR_PATH.read_text(encoding="utf-8"))


def _genesis_row() -> dict:
    return {
        "sequence": 0,
        "record_digest": GENESIS_RECORD_DIGEST,
        "record_type": "governance_genesis",
        "payload_json": "{}",
    }


def test_repository_checkpoint_is_self_authenticating() -> None:
    assert verify_anchor(_anchor())


def test_repository_checkpoint_accepts_seeded_genesis() -> None:
    result = verify_ledger_against_anchor([_genesis_row()], anchor=_anchor())
    assert result["state"] == "consistent_with_repository_anchor"
    assert result["anchored_sequence"] == 0
    assert result["raw_attempted_trials"] == 0


def test_repository_checkpoint_detects_missing_or_rewritten_genesis() -> None:
    with pytest.raises(ValueError, match="empty"):
        verify_ledger_against_anchor([], anchor=_anchor())

    rewritten = _genesis_row()
    rewritten["record_digest"] = "0" * 64
    with pytest.raises(ValueError, match="anchored digest mismatch"):
        verify_ledger_against_anchor([rewritten], anchor=_anchor())


def test_repository_checkpoint_detects_trial_count_rollback() -> None:
    anchor = _anchor()
    anchor["raw_attempted_trials_floor"] = 1
    anchor.pop("anchor_digest")
    # Deliberately invalid after mutation: an anchor cannot be weakened in memory.
    with pytest.raises(ValueError, match="anchor is invalid"):
        verify_ledger_against_anchor([_genesis_row()], anchor=anchor)
