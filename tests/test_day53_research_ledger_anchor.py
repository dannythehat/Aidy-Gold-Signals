from __future__ import annotations

import json
from pathlib import Path

import pytest

from aidy.research_ledger_anchor import (
    GENESIS_RECORD_DIGEST,
    verify_anchor,
    verify_ledger_against_anchor,
)

STEP0_ANCHOR_PATH = Path(
    "evidence/research_ledger/anchors/day53-step0-repository-checkpoint.json"
)
STEP2_ANCHOR_PATH = Path(
    "evidence/research_ledger/anchors/day53-step2-preregistration-checkpoint.json"
)
STEP2_LEDGER_HEAD_DIGEST = (
    "e161e21f108404302bbdada89c2af0ba3110cddfb05aba76077ee15f04ed4ea9"
)


def _anchor(path: Path = STEP0_ANCHOR_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _genesis_row() -> dict:
    return {
        "sequence": 0,
        "record_digest": GENESIS_RECORD_DIGEST,
        "record_type": "governance_genesis",
        "payload_json": "{}",
    }


def _step2_head_row(*, record_digest: str = STEP2_LEDGER_HEAD_DIGEST) -> dict:
    return {
        "sequence": 2,
        "record_digest": record_digest,
        "record_type": "market_data_equivalence_contract_registered",
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


def test_step2_repository_checkpoint_is_self_authenticating() -> None:
    anchor = _anchor(STEP2_ANCHOR_PATH)
    assert verify_anchor(anchor)
    assert anchor["anchored_sequence"] == 2
    assert anchor["anchored_record_digest"] == STEP2_LEDGER_HEAD_DIGEST
    assert anchor["raw_attempted_trials_floor"] == 0
    assert anchor["ledger_code_head_sha"] == "6689aa954cb5f3dd2f97f980846c9168437aabe4"
    assert anchor["anchor_parent_head_sha"] == "547c5e0105dbb87cf97f7d8a48e6775876fd5429"


def test_step2_repository_checkpoint_detects_rollback_or_rewrite() -> None:
    anchor = _anchor(STEP2_ANCHOR_PATH)

    with pytest.raises(ValueError, match="sequence behind repository anchor"):
        verify_ledger_against_anchor([_genesis_row()], anchor=anchor)

    with pytest.raises(ValueError, match="anchored sequence missing"):
        verify_ledger_against_anchor(
            [
                _genesis_row(),
                {
                    "sequence": 3,
                    "record_digest": "3" * 64,
                    "record_type": "other",
                    "payload_json": "{}",
                },
            ],
            anchor=anchor,
        )

    with pytest.raises(ValueError, match="anchored digest mismatch"):
        verify_ledger_against_anchor(
            [_genesis_row(), _step2_head_row(record_digest="0" * 64)],
            anchor=anchor,
        )

    result = verify_ledger_against_anchor(
        [_genesis_row(), _step2_head_row()],
        anchor=anchor,
    )
    assert result["state"] == "consistent_with_repository_anchor"
    assert result["anchored_sequence"] == 2
    assert result["raw_attempted_trials"] == 0
