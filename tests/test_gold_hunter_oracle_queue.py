"""No recorded source candidate can leap into paper, funded or Oracle Hub."""
import json
from pathlib import Path

import pytest

from scripts.gold_hunter_oracle_research_queue import (
    DEFAULT_SOURCE,
    EVIDENCE_RECONCILIATION,
    LIFECYCLE,
    METHODOLOGY_PRIORITY,
    _check,
    create_queue,
)


def test_all_83_original_candidates_preserved_without_fake_approval():
    q = create_queue()
    assert q["total"] == 83
    assert q["source_sha256"] and len(q["source_sha256"]) == 64
    assert len(q["queue"]) == 83
    assert {x["id"] for x in q["queue"]} == {
        f"S{i:03d}" for i in range(1, 84)
    }
    assert all(x["lifecycle"] == "DISCOVERED" for x in q["queue"])
    assert all(x["passed_research_gate"] is False
               and x["oracle_hub_admitted"] is False
               and x["latest_verified_multiyear_outcome"] is None
               for x in q["queue"])
    assert q["prequalified"] == q["paper_enabled"] == q["cent_enabled"] == 0
    assert q["oracle_hub_enabled"] == q["bot_orders_placed"] == 0
    assert len(LIFECYCLE) == len(set(LIFECYCLE))


def test_existing_aidy_verdicts_are_prioritised_not_rewritten():
    q = create_queue()
    by_id = {x["id"]: x for x in q["queue"]}
    for ident in EVIDENCE_RECONCILIATION:
        assert by_id[ident]["priority_work"] == "RECONCILE_EXISTING_AIDY_SOURCE_VERDICT_FIRST"
    for ident in METHODOLOGY_PRIORITY:
        assert by_id[ident]["priority_work"] == "AUDIT_PUBLISHED_RULES_AND_RUN_MULTYEAR_REPLAY"
    assert q["original_evidence_audit_candidates"] == len(EVIDENCE_RECONCILIATION)


def test_duplicate_or_missing_source_id_fails_closed():
    s = json.loads(DEFAULT_SOURCE.read_text(encoding="utf-8"))
    copy = [dict(x) for x in s["candidates"]]
    copy[0]["id"] = copy[1]["id"]
    with pytest.raises(ValueError, match="missing, duplicated"):
        _check(copy)
    copy = [dict(x) for x in s["candidates"][:-1]]
    with pytest.raises(ValueError, match="Expected 83"):
        _check(copy)


def test_frozen_source_schema_is_required(tmp_path: Path):
    x = json.loads(DEFAULT_SOURCE.read_text(encoding="utf-8"))
    x["schema"] = "unverified"
    path = tmp_path / "wrong.json"
    path.write_text(json.dumps(x), encoding="utf-8")
    with pytest.raises(ValueError, match="Unknown immutable"):
        create_queue(path)
