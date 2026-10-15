"""Day32 durable 100-job queue: reliability, quota and fail-closed adversarial tests."""
from __future__ import annotations

import sqlite3
from dataclasses import replace

import pytest

from aidy.strategy_lab_batch_queue import (
    MAX_ATTEMPTS,
    MAX_INFLIGHT,
    MAX_NONTERMINAL,
    SYNTHETIC,
    ResearchQueue,
)
from scripts.strategy_lab.day32_100_job_acceptance import exercise, outcome, spec


@pytest.fixture
def db(tmp_path):
    with ResearchQueue(tmp_path/"private_batch.sqlite") as q:
        yield q


def test_complete_100_synthetic_jobs_survive_two_restarts(tmp_path):
    proof, reports = exercise(tmp_path/"real_queue.sqlite")
    assert proof["status"] == "PASS"
    assert proof["unique_completed"] == 100
    assert proof["deduplicated_submissions"] == 20
    assert proof["overflow_blocked"]
    assert proof["stale_worker_completions_fenced"] == 4
    assert proof["synthetic_retry_recoveries"] == 6
    assert proof["number_of_trial_families"] == 10
    assert proof["observed_peak_workers"] <= 4
    assert proof["observed_peak_family_workers"] <= 2
    assert len(reports) == 100
    assert all(r["source_kind"] == SYNTHETIC for r in reports)
    assert all(r["profitability_verified"] is False for r in reports)


def test_semantically_same_parameters_independent_field_order_deduplicates(db):
    a = spec(1)
    reordered = replace(a, parameters=dict(reversed(list(a.parameters.items()))))
    x, fresh = db.submit(a, 100)
    y, again = db.submit(reordered, 200)
    assert x == y and fresh and not again
    assert db.counts()["QUEUED"] == 1


def test_new_rule_version_is_separate_experiment_not_a_duplicate(db):
    a = spec(1)
    b = replace(a, strategy_rules_sha256="a"*64)
    assert db.submit(a, 100)[0] != db.submit(b, 100)[0]


def test_source_change_and_market_timeframe_are_new_experiments(db):
    a = spec(1)
    ids = [
        db.submit(a, 1)[0],
        db.submit(replace(a, market_input_sha256="a"*64), 1)[0],
        db.submit(replace(a, timeframe="H1"), 1)[0],
    ]
    assert len(set(ids)) == 3


@pytest.mark.parametrize(("field","bad"), [
    ("strategy_rules_sha256", "not_hash"),
    ("market_input_sha256", "1"*63),
    ("timeframe", "H2"),
    ("source_kind", "REAL_COSTED_XAUUSD_PROFITS"),
    ("strategy_id", "=SPY"),
    ("family_id", "../tenant_1"),
    ("parameters", {"profit": 0.1}),
    ("parameters", {"evil": {"code": "eval()"}}),
    ("parameters", {"-unsafe": True}),
])
def test_bad_source_claims_or_unsafe_parameters_refused(db, field, bad):
    with pytest.raises(ValueError):
        db.submit(replace(spec(0), **{field: bad}), 1)
    assert sum(db.counts().values()) == 0


@pytest.mark.parametrize("t", [-1, 1.2, True, 10**16])
def test_invalid_explicit_clock_denied(db, t):
    with pytest.raises(ValueError):
        db.submit(spec(0), t)


def test_run_slots_and_family_slots_enforced_before_leasing(db):
    for i in range(10):
        db.submit(spec(i), 1)
    claimed = [db.claim(f"worker_{i}", 5) for i in range(2)]
    assert all(claimed)
    assert claimed[0]["source"]["family_id"] == "family_00"
    assert claimed[1]["source"]["family_id"] == "family_00"
    assert db.claim("worker_2", 5) is None
    assert db.counts()["RUNNING"] == 2


def test_global_worker_cap_enforced_separately_from_each_family(db):
    for i in (0, 1, 10, 11, 20):
        db.submit(spec(i), 1)
    assert all(db.claim(f"worker_{i}", 100) is not None for i in range(4))
    assert db.claim("worker_4", 100) is None
    assert db.counts()["RUNNING"] == MAX_INFLIGHT


def test_atomic_leases_across_two_independent_database_connections(tmp_path):
    location = tmp_path/"q.sqlite"
    with ResearchQueue(location) as a, ResearchQueue(location) as b:
        job, _ = a.submit(spec(0), 1)
        first = a.claim("worker_A", 2)
        assert b.claim("worker_B", 2) is None
        assert first["job_id"] == job
        with pytest.raises(ValueError, match="lease"):
            b.finish(job, "fake"*16, 2, outcome(job))
        digest = a.finish(job, first["lease_token"], 3, outcome(job))
        assert len(digest) == 64
        with pytest.raises(ValueError, match="lease"):
            b.finish(job, first["lease_token"], 4, outcome(job))
        assert b.counts()["SUCCEEDED"] == 1


def test_crash_and_restart_fences_original_worker_token(tmp_path):
    path = tmp_path/"q.sqlite"
    with ResearchQueue(path) as queue:
        queue.submit(spec(0), 1)
        old = queue.claim("old_worker", 2)
    with ResearchQueue(path) as reopened:
        new = reopened.claim("new_worker", 2+60000+1)
        assert new["job_id"] == old["job_id"]
        assert new["lease_token"] != old["lease_token"]
        with pytest.raises(ValueError, match="superseded"):
            reopened.finish(old["job_id"], old["lease_token"], 65000,
                            outcome(old["job_id"]))
        reopened.finish(new["job_id"], new["lease_token"], 65000,
                        outcome(new["job_id"]))
        assert reopened.counts()["SUCCEEDED"] == 1


def test_stale_lease_expiration_at_exact_boundary_denied(db):
    job, _ = db.submit(spec(0), 1)
    claim = db.claim("worker_0", 20)
    with pytest.raises(ValueError, match="expired"):
        db.finish(job, claim["lease_token"], 20+60000, outcome(job))


def test_three_failures_dead_letter_one_experiment(db):
    job, _ = db.submit(spec(0), 1)
    for attempt in range(MAX_ATTEMPTS):
        claim = db.claim("worker_0", 2)
        status = db.fail(job, claim["lease_token"], 3, "SYNTHETIC_TIMEOUT")
        assert status == ("DEAD" if attempt == MAX_ATTEMPTS-1 else "QUEUED")
    assert db.counts()["DEAD"] == 1
    assert db.claim("worker_0", 3) is None


def test_expired_dead_letter_after_max_attempts(db):
    job, _ = db.submit(spec(0), 1)
    t = 10
    for _ in range(MAX_ATTEMPTS):
        claim = db.claim("worker_0", t)
        assert claim["job_id"] == job
        t += 60001
    assert db.claim("recovery_worker", t) is None
    assert db.counts()["DEAD"] == 1


@pytest.mark.parametrize("result", [
    {"job_id": "bad", "synthetic_diagnostic_score_bps": 1, "source_kind": SYNTHETIC},
    {"synthetic_diagnostic_score_bps": 1, "source_kind": SYNTHETIC},
    {"job_id": "bad", "synthetic_diagnostic_score_bps": 2.5, "source_kind": SYNTHETIC},
    {"job_id": "bad", "synthetic_diagnostic_score_bps": 1001, "source_kind": SYNTHETIC},
    {"job_id": "bad", "synthetic_diagnostic_score_bps": 5, "source_kind": "REAL_TRADING_PROFIT"},
])
def test_fabricated_or_malformed_execution_result_rejected(db, result):
    job, _ = db.submit(spec(0), 1)
    claim = db.claim("worker_0", 2)
    result = {**result, "job_id": job} if result.get("job_id") == "bad" else result
    with pytest.raises(ValueError):
        db.finish(job, claim["lease_token"], 3, result)
    assert db.counts()["RUNNING"] == 1


def test_results_comparable_by_family_and_do_not_imply_real_alpha(db):
    for i in (0, 1, 10, 11):
        db.submit(spec(i), 1)
    while claim := db.claim("worker_0", 2):
        db.finish(claim["job_id"], claim["lease_token"], 3,
                  outcome(claim["job_id"]))
    all_results = db.compare()
    family_results = db.compare("family_01")
    assert len(all_results) == 4 and len(family_results) == 2
    assert all(r["family_id"] == "family_01" for r in family_results)
    assert all(not r["profitability_verified"] for r in all_results)


def test_result_hash_corruption_is_detected_before_comparison(db):
    job, _ = db.submit(spec(0), 1)
    claim = db.claim("worker_0", 2)
    db.finish(job, claim["lease_token"], 3, outcome(job))
    db.conn.execute(
        "UPDATE jobs SET result_sha256=? WHERE job_id=?", ("a"*64, job)
    )
    with pytest.raises(ValueError, match="hash"):
        db.compare()


def test_append_only_event_chain_corruption_detected(db):
    db.submit(spec(0), 1)
    assert db.verify_events()["event_count"] == 1
    db.conn.execute("UPDATE events SET payload=? WHERE id=1", ("{}",))
    with pytest.raises(ValueError, match="tampered"):
        db.verify_events()


def test_failed_invalid_finish_does_not_consume_lease(db):
    job, _ = db.submit(spec(0), 1)
    lease = db.claim("worker_0", 2)
    with pytest.raises(ValueError):
        db.finish(job, lease["lease_token"], 3, {"profit": 10000})
    assert db.counts()["RUNNING"] == 1
    db.finish(job, lease["lease_token"], 4, outcome(job))
    assert db.counts()["SUCCEEDED"] == 1


def test_100_active_slot_quota_is_bound_and_dedupe_does_not_consume(db):
    for i in range(MAX_NONTERMINAL):
        db.submit(spec(i), 1)
    assert db.submit(spec(0), 1)[1] is False
    with pytest.raises(ValueError, match="quota"):
        db.submit(spec(MAX_NONTERMINAL), 2)
    assert db.counts()["QUEUED"] == MAX_NONTERMINAL


def test_synthetic_result_is_immutable_after_first_success(db):
    job, _ = db.submit(spec(0), 1)
    lease = db.claim("worker_0", 2)
    db.finish(job, lease["lease_token"], 3, outcome(job))
    with pytest.raises(ValueError, match="lease"):
        db.finish(job, lease["lease_token"], 4, outcome(job))
    assert db.submit(spec(0), 4)[1] is False
    assert db.counts()["SUCCEEDED"] == 1


def test_malformed_schema_version_is_not_silently_migrated(tmp_path):
    path = tmp_path/"bad_version.sqlite"
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA user_version=900")
    with pytest.raises(ValueError, match="schema version"):
        ResearchQueue(path)
