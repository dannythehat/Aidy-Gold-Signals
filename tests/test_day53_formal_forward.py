from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from aidy.forward_evaluation import (
    EARLIEST_FORMAL_START_UTC,
    D1ForwardEvaluationStore,
    ForwardEvaluationError,
    build_forward_evaluation_record,
    build_forward_outcome_attachment,
    build_frozen_version_manifest,
    day53_manifest,
    digest,
)

ROOT = Path(__file__).resolve().parents[1]
START = datetime(2026, 9, 20, 0, 0, tzinfo=UTC)


class Prepared:
    def __init__(self, db: "LocalD1", sql: str, params=()) -> None:
        self.db = db
        self.sql = sql
        self.params = params

    def bind(self, *params):
        return Prepared(self.db, self.sql, params)

    async def first(self):
        row = self.db.connection.execute(self.sql, self.params).fetchone()
        return dict(row) if row is not None else None

    async def all(self):
        rows = self.db.connection.execute(self.sql, self.params).fetchall()
        return {"results": [dict(row) for row in rows]}

    async def run(self):
        self.db.connection.execute(self.sql, self.params)
        self.db.connection.commit()
        return {"success": True}


class LocalD1:
    def __init__(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        for migration in sorted((ROOT / "migrations" / "d1").glob("*.sql")):
            self.connection.executescript(migration.read_text())

    def prepare(self, sql: str) -> Prepared:
        return Prepared(self, sql)


def _components() -> dict:
    names = (
        "day52_runtime",
        "openai_gateway_v2",
        "self_consistency_v2",
        "immutable_decision_ledger",
        "selective_abstention_shadow",
        "gc_xau_shadow",
        "macro_surprise",
    )
    return {
        name: {
            "version": f"{name}_v1",
            "digest": digest({"component": name, "version": 1}),
        }
        for name in names
    }


def _manifest(*, start: datetime = START) -> dict:
    return build_frozen_version_manifest(
        accepted_code_head="a" * 40,
        earliest_start_utc=start,
        components=_components(),
    )


async def _active_store():
    store = D1ForwardEvaluationStore(LocalD1())
    prepared = await store.prepare_cohort(
        _manifest(),
        prepared_at_utc=datetime(2026, 9, 1, 16, 0, tzinfo=UTC),
    )
    active = await store.activate_cohort(
        prepared["cohort_id"],
        activated_at_utc=START,
    )
    return store, active


def _self_consistency() -> dict:
    disagreement = {
        "disagreement_version": "aidy_master_trader_disagreement_v1",
        "sample_count": 3,
        "eligible_sample_count": 3,
        "invalid_or_blocked_sample_count": 0,
        "distinct_vote_count": 1,
        "majority_count": 3,
        "majority_share": "1.000000",
        "disagreement_score": "0.000000",
        "vote_counts": {"vote": 3},
    }
    body = {
        "self_consistency_version": "aidy_master_trader_self_consistency_v2_falsifiable",
        "disagreement": disagreement,
    }
    body["self_consistency_digest"] = digest(body)
    return body


def _record(
    cohort: dict,
    *,
    suffix: str = "1",
    disposition: str = "no_trade",
    data_quality_state: str = "known_good",
    data_quality_reason_code: str | None = None,
    episode_id: str = "episode-001",
) -> dict:
    model_resolved = disposition in {"no_trade", "decision_admitted", "management_admitted"}
    return build_forward_evaluation_record(
        cohort=cohort,
        cycle_id=f"cycle-{suffix}",
        instruction_type="market_evaluation",
        evaluated_at_utc=START + timedelta(minutes=int(suffix)),
        context_hash=(suffix[-1] * 64),
        disposition=disposition,
        data_quality_state=data_quality_state,
        data_quality_reason_code=data_quality_reason_code,
        episode_id=episode_id,
        decision_id=f"decision-{suffix}" if disposition in {"no_trade", "decision_admitted"} else None,
        ex_ante_digest=(suffix[-1] * 64)
        if disposition in {"no_trade", "decision_admitted"}
        else None,
        self_consistency=_self_consistency() if model_resolved else None,
        retrieval_effective_n=7,
        gc_shadow={
            "state": "paired",
            "pair_digest": digest({"gc": suffix}),
            "gc_shadow_only": True,
            "formal_forward_evidence_eligible": False,
        },
        gc_feed_health={
            "state": "known",
            "pair_state": "paired",
            "timestamp_skew_seconds": 1,
        },
        macro_surprise={
            "surprise_capture_version": "aidy_forward_macro_surprise_v1",
            "consensus_state": "unknown",
            "surprise_state": "unknown",
            "surprise_value": None,
            "surprise_digest": digest({"macro": suffix}),
        },
        selective_shadow={
            "state": "unknown",
            "master_trader_block_allowed": False,
            "publication_block_allowed": False,
        },
    )


def test_architecture_date_floor_cannot_be_backdated() -> None:
    before = datetime(2026, 9, 19, 23, 59, 59, tzinfo=UTC)
    with pytest.raises(ForwardEvaluationError, match="20 Sep 2026"):
        _manifest(start=before)
    assert EARLIEST_FORMAL_START_UTC == "2026-09-20T00:00:00+00:00"


@pytest.mark.asyncio
async def test_cohort_can_be_prepared_now_but_not_activated_before_day53() -> None:
    store = D1ForwardEvaluationStore(LocalD1())
    prepared = await store.prepare_cohort(
        _manifest(),
        prepared_at_utc=datetime(2026, 9, 1, 16, 0, tzinfo=UTC),
    )
    assert prepared["state"] == "prepared"
    with pytest.raises(ForwardEvaluationError, match="cannot activate before"):
        await store.activate_cohort(
            prepared["cohort_id"],
            activated_at_utc=datetime(2026, 9, 19, 23, 59, 59, tzinfo=UTC),
        )
    unchanged = await store.get_cohort(prepared["cohort_id"])
    assert unchanged["state"] == "prepared"


@pytest.mark.asyncio
async def test_activation_on_day53_accepts_genuine_no_trade_and_counts_independent_n() -> None:
    store, cohort = await _active_store()
    first = _record(cohort, suffix="1", episode_id="episode-shared")
    second = _record(cohort, suffix="2", episode_id="episode-shared")
    await store.record_evaluation(first, recorded_at_utc=START + timedelta(minutes=2))
    await store.record_evaluation(second, recorded_at_utc=START + timedelta(minutes=3))
    progress = await store.cohort_progress(cohort["cohort_id"])
    assert progress["raw_evaluation_count"] == 2
    assert progress["episode_independent_n"] == 1
    assert progress["raw_no_trade_count"] == 2
    assert progress["day54_sample_gate_met"] is False
    assert progress["raw_count_can_substitute_for_effective_n"] is False


def test_data_quality_failure_cannot_be_disguised_as_no_trade() -> None:
    cohort = {
        "state": "active",
        "cohort_id": "cohort-x",
        "manifest_digest": "f" * 64,
        "activated_at_utc": START.isoformat(),
        "earliest_start_utc": START.isoformat(),
    }
    with pytest.raises(ForwardEvaluationError, match="genuine no_trade"):
        _record(
            cohort,
            suffix="1",
            disposition="no_trade",
            data_quality_state="failure",
            data_quality_reason_code="stale_quote",
        )


@pytest.mark.asyncio
async def test_data_quality_failure_is_recorded_separately_without_fake_no_trade() -> None:
    store, cohort = await _active_store()
    record = _record(
        cohort,
        suffix="3",
        disposition="pre_model_blocked",
        data_quality_state="failure",
        data_quality_reason_code="stale_quote",
        episode_id="episode-dq",
    )
    await store.record_evaluation(record, recorded_at_utc=START + timedelta(minutes=4))
    progress = await store.cohort_progress(cohort["cohort_id"])
    assert progress["data_quality_failure_count"] == 1
    assert progress["raw_no_trade_count"] == 0


def test_selective_shadow_can_never_become_a_gate() -> None:
    cohort = {
        "state": "active",
        "cohort_id": "cohort-x",
        "manifest_digest": "f" * 64,
        "activated_at_utc": START.isoformat(),
        "earliest_start_utc": START.isoformat(),
    }
    kwargs = {
        "cohort": cohort,
        "cycle_id": "cycle-gate",
        "instruction_type": "market_evaluation",
        "evaluated_at_utc": START + timedelta(minutes=1),
        "context_hash": "a" * 64,
        "disposition": "no_trade",
        "data_quality_state": "known_good",
        "data_quality_reason_code": None,
        "episode_id": "episode-gate",
        "decision_id": "decision-gate",
        "ex_ante_digest": "b" * 64,
        "self_consistency": _self_consistency(),
        "retrieval_effective_n": 0,
        "gc_shadow": {"state": "unknown"},
        "gc_feed_health": {"state": "unknown"},
        "macro_surprise": {"state": "unknown"},
        "selective_shadow": {
            "state": "reject",
            "master_trader_block_allowed": True,
            "publication_block_allowed": False,
        },
    }
    with pytest.raises(ForwardEvaluationError, match="cannot gate Master Trader"):
        build_forward_evaluation_record(**kwargs)


@pytest.mark.asyncio
async def test_valid_freeze_break_closes_cohort_and_prevents_new_evidence_or_reactivation() -> None:
    store, cohort = await _active_store()
    closed = await store.close_cohort(
        cohort["cohort_id"],
        closed_at_utc=START + timedelta(hours=1),
        reason_code="material_safety_or_data_integrity_defect",
        evidence={"finding_id": "pit-leak-001", "blocking": True},
    )
    assert closed["state"] == "closed"
    with pytest.raises(ForwardEvaluationError, match="non-active"):
        await store.record_evaluation(
            _record(cohort, suffix="4"),
            recorded_at_utc=START + timedelta(hours=1, minutes=1),
        )
    with pytest.raises(ForwardEvaluationError, match="cannot be reactivated"):
        await store.activate_cohort(
            cohort["cohort_id"],
            activated_at_utc=START + timedelta(hours=2),
        )


@pytest.mark.asyncio
async def test_performance_improvement_is_not_a_valid_freeze_break() -> None:
    store, cohort = await _active_store()
    with pytest.raises(ForwardEvaluationError, match="Invalid Day 53 freeze-break"):
        await store.close_cohort(
            cohort["cohort_id"],
            closed_at_utc=START + timedelta(hours=1),
            reason_code="performance_improvement",
            evidence={"pnl": "better"},
        )
    current = await store.get_cohort(cohort["cohort_id"])
    assert current["state"] == "active"


@pytest.mark.asyncio
async def test_no_trade_shadow_outcome_attaches_separately_and_cannot_tune_active_cohort() -> None:
    store, cohort = await _active_store()
    record = _record(cohort, suffix="5", episode_id="episode-outcome")
    await store.record_evaluation(record, recorded_at_utc=START + timedelta(minutes=6))
    attachment = build_forward_outcome_attachment(
        evaluation_record=record,
        outcome_type="no_trade_shadow",
        attached_at_utc=START + timedelta(hours=3),
        outcome_payload={"shadow_result": "missed_opportunity", "future_derived": True},
    )
    persisted = await store.attach_outcome(
        attachment,
        recorded_at_utc=START + timedelta(hours=3, minutes=1),
    )
    assert persisted["attachment_digest"] == attachment["attachment_digest"]
    assert attachment["active_cohort_tuning_allowed"] is False
    assert record["outcome_fields_present"] is False


def test_day53_manifest_keeps_paper_only_boundaries_and_300_episode_gate() -> None:
    manifest = day53_manifest()
    assert manifest["earliest_formal_start_utc"] == EARLIEST_FORMAL_START_UTC
    assert manifest["pre_day53_backfill_allowed"] is False
    assert manifest["all_evaluations_including_no_trade_ledgered"] is True
    assert manifest["data_quality_failure_distinct_from_no_trade"] is True
    assert manifest["j17_disagreement_logged"] is True
    assert manifest["j20_raw_and_episode_independent_n_logged"] is True
    assert manifest["selective_layer_remains_shadow_only"] is True
    assert manifest["performance_improvement_freeze_break_allowed"] is False
    assert manifest["day54_sample_gate_episode_independent_n"] == 300
    assert manifest["super_signals_dependency_allowed"] is False
    assert manifest["live_money_execution_allowed"] is False
