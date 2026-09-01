from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from aidy.forward_evaluation import (
    EARLIEST_FORMAL_START_UTC,
    ForwardEvaluationError,
    build_forward_evaluation_record,
    build_frozen_version_manifest,
    digest,
)
from aidy.forward_start_amendment import (
    AMENDMENT_EFFECTIVE_UTC,
    DAY54_MINIMUM_EPISODE_INDEPENDENT_N,
    FORMER_PLANNING_START_UTC,
    D1ImmediateForwardEvaluationStore,
    amended_cohort_id_for_manifest,
    build_amended_frozen_version_manifest,
    day53_immediate_start_manifest,
    verify_amended_frozen_version_manifest,
)

ROOT = Path(__file__).resolve().parents[1]
AMENDMENT = datetime.fromisoformat(AMENDMENT_EFFECTIVE_UTC)
ACTIVATION = AMENDMENT + timedelta(minutes=30)


class Prepared:
    def __init__(self, db: LocalD1, sql: str, params=()) -> None:
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


def _manifest(*, start: datetime = AMENDMENT) -> dict:
    return build_amended_frozen_version_manifest(
        accepted_code_head="b" * 40,
        earliest_start_utc=start,
        components=_components(),
    )


def _self_consistency() -> dict:
    disagreement = {
        "sample_count": 3,
        "eligible_sample_count": 3,
        "distinct_vote_count": 1,
        "majority_count": 3,
        "majority_share": "1.000000",
        "disagreement_score": "0.000000",
    }
    body = {"disagreement": disagreement}
    body["self_consistency_digest"] = digest(body)
    return body


def _record(cohort: dict, *, suffix: str, disposition: str, episode_id: str) -> dict:
    model_resolved = disposition in {
        "self_consistency_abstain",
        "no_trade",
        "decision_admitted",
        "management_admitted",
    }
    data_quality = "failure" if disposition == "pre_model_blocked" else "known_good"
    return build_forward_evaluation_record(
        cohort=cohort,
        cycle_id=f"cycle-{suffix}",
        instruction_type="market_evaluation",
        evaluated_at_utc=ACTIVATION + timedelta(minutes=int(suffix)),
        context_hash=(suffix[-1] * 64),
        disposition=disposition,
        data_quality_state=data_quality,
        data_quality_reason_code="missing_genuine_ohlc_or_spread"
        if data_quality == "failure"
        else None,
        episode_id=episode_id,
        decision_id=f"decision-{suffix}" if disposition in {"no_trade", "decision_admitted"} else None,
        ex_ante_digest=(suffix[-1] * 64)
        if disposition in {"no_trade", "decision_admitted"}
        else None,
        self_consistency=_self_consistency() if model_resolved else None,
        retrieval_effective_n=0,
        gc_shadow={"state": "unknown", "gc_shadow_only": True},
        gc_feed_health={"state": "unknown"},
        macro_surprise={"state": "unknown"},
        selective_shadow={
            "state": "unknown",
            "master_trader_block_allowed": False,
            "publication_block_allowed": False,
        },
    )


async def _active_store():
    store = D1ImmediateForwardEvaluationStore(LocalD1())
    prepared = await store.prepare_cohort(_manifest(), prepared_at_utc=AMENDMENT + timedelta(minutes=1))
    active = await store.activate_cohort(prepared["cohort_id"], activated_at_utc=ACTIVATION)
    return store, active


def test_old_day53_floor_remains_historically_reproducible() -> None:
    assert EARLIEST_FORMAL_START_UTC == FORMER_PLANNING_START_UTC
    old = build_frozen_version_manifest(
        accepted_code_head="a" * 40,
        earliest_start_utc=FORMER_PLANNING_START_UTC,
        components=_components(),
    )
    assert old["earliest_start_utc"] == FORMER_PLANNING_START_UTC
    assert old["manifest_version"] == "aidy_day53_frozen_version_manifest_v1"


def test_amended_manifest_is_distinct_and_cannot_backdate_before_amendment() -> None:
    amended = _manifest()
    assert verify_amended_frozen_version_manifest(amended)
    assert amended["manifest_version"] != "aidy_day53_frozen_version_manifest_v1"
    assert amended["former_planning_floor_superseded_before_forward_outcomes"] is True
    assert amended["formal_forward_outcomes_existed_before_amendment"] is False
    assert amended["pre_activation_backfill_allowed"] is False
    with pytest.raises(ForwardEvaluationError, match="cannot precede"):
        _manifest(start=AMENDMENT - timedelta(seconds=1))


@pytest.mark.asyncio
async def test_cohort_can_activate_immediately_after_amendment() -> None:
    store = D1ImmediateForwardEvaluationStore(LocalD1())
    manifest = _manifest()
    prepared = await store.prepare_cohort(manifest, prepared_at_utc=AMENDMENT + timedelta(minutes=1))
    assert prepared["cohort_id"] == amended_cohort_id_for_manifest(manifest)
    assert prepared["state"] == "prepared"
    active = await store.activate_cohort(prepared["cohort_id"], activated_at_utc=ACTIVATION)
    assert active["state"] == "active"
    assert datetime.fromisoformat(active["activated_at_utc"]) == ACTIVATION


@pytest.mark.asyncio
async def test_actual_activation_timestamp_prevents_backfill() -> None:
    _, cohort = await _active_store()
    with pytest.raises(ForwardEvaluationError, match="predates"):
        build_forward_evaluation_record(
            cohort=cohort,
            cycle_id="cycle-backfill",
            instruction_type="market_evaluation",
            evaluated_at_utc=ACTIVATION - timedelta(seconds=1),
            context_hash="a" * 64,
            disposition="pre_model_blocked",
            data_quality_state="failure",
            data_quality_reason_code="missing_genuine_ohlc_or_spread",
            episode_id="episode-backfill",
            decision_id=None,
            ex_ante_digest=None,
            self_consistency=None,
            retrieval_effective_n=0,
            gc_shadow={"state": "unknown"},
            gc_feed_health={"state": "unknown"},
            macro_surprise={"state": "unknown"},
            selective_shadow={"state": "unknown"},
        )


@pytest.mark.asyncio
async def test_blocked_cycles_do_not_advance_day54_decision_sample_gate() -> None:
    store, cohort = await _active_store()
    for index in range(1, 6):
        record = _record(
            cohort,
            suffix=str(index),
            disposition="pre_model_blocked",
            episode_id=f"blocked-episode-{index}",
        )
        await store.record_evaluation(record, recorded_at_utc=ACTIVATION + timedelta(minutes=10 + index))
    progress = await store.cohort_progress(cohort["cohort_id"])
    assert progress["raw_evaluation_count"] == 5
    assert progress["all_evaluation_episode_n"] == 5
    assert progress["model_resolved_episode_independent_n"] == 0
    assert progress["day54_sample_gate_met"] is False
    assert progress["blocked_or_failed_cycles_can_satisfy_day54_gate"] is False


@pytest.mark.asyncio
async def test_model_resolved_episode_n_is_deduplicated_and_is_the_day54_gate_basis() -> None:
    store, cohort = await _active_store()
    for suffix, episode in (("1", "episode-a"), ("2", "episode-a"), ("3", "episode-b")):
        record = _record(cohort, suffix=suffix, disposition="no_trade", episode_id=episode)
        await store.record_evaluation(record, recorded_at_utc=ACTIVATION + timedelta(minutes=20 + int(suffix)))
    progress = await store.cohort_progress(cohort["cohort_id"])
    assert progress["raw_no_trade_count"] == 3
    assert progress["model_resolved_episode_independent_n"] == 2
    assert progress["episode_independent_n"] == 2
    assert progress["day54_sample_gate_episode_independent_n"] == DAY54_MINIMUM_EPISODE_INDEPENDENT_N
    assert progress["raw_count_can_substitute_for_effective_n"] is False


@pytest.mark.asyncio
async def test_performance_still_cannot_break_the_amended_freeze() -> None:
    store, cohort = await _active_store()
    with pytest.raises(ForwardEvaluationError, match="Invalid Day 53 freeze-break"):
        await store.close_cohort(
            cohort["cohort_id"],
            closed_at_utc=ACTIVATION + timedelta(hours=1),
            reason_code="performance_improvement",
            evidence={"pnl": "bad"},
        )


def test_amendment_manifest_retains_all_hard_boundaries() -> None:
    manifest = day53_immediate_start_manifest()
    assert manifest["immediate_start_allowed_after_exact_head_merge"] is True
    assert manifest["formal_forward_outcomes_existed_before_amendment"] is False
    assert manifest["pre_activation_backfill_allowed"] is False
    assert manifest["day54_sample_gate_episode_independent_n"] == 300
    assert manifest["day54_gate_uses_model_resolved_episodes_only"] is True
    assert manifest["blocked_cycles_count_as_model_resolved_episodes"] is False
    assert manifest["selective_layer_remains_shadow_only"] is True
    assert manifest["gc_remains_shadow_only"] is True
    assert manifest["performance_improvement_freeze_break_allowed"] is False
    assert manifest["super_signals_dependency_allowed"] is False
    assert manifest["broker_or_account_state_allowed"] is False
    assert manifest["follower_state_allowed"] is False
    assert manifest["live_money_execution_allowed"] is False
