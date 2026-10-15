"""Day26 leakage, embargo, trial registration, tampering and holdout sealing tests."""
from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from aidy.strategy_lab_history_reader import ClosedBar, ReadResult
from aidy.strategy_lab_oos_protocol import MODEL_SHA256, OOSPolicy, SealedOOS
from aidy.strategy_lab_oos_trial_registry import TrialRegistry


def sample_history() -> ReadResult:
    start = datetime(2025, 1, 6, 11, tzinfo=UTC)
    closes = [
        Decimal(2650) + Decimal(i) / 10 + Decimal((i % 12)-6) / 4
        for i in range(120)
    ]
    bars = tuple(ClosedBar(
        start + i*timedelta(minutes=5),
        start + (i+1)*timedelta(minutes=5),
        close, close+Decimal(1), close-Decimal(1), close,
    ) for i, close in enumerate(closes))
    return ReadResult(bars, 600, "b"*64, ("a"*64,))


def test_exact_folds_have_no_future_features_or_unmatured_training_labels():
    study = SealedOOS(sample_history())
    review = study.review_development()
    dev = study.development()
    assert len(dev) == 94
    assert review.sealed_holdout_size == 20
    assert review.excluded_boundary_bars == 4
    assert review.holdout_first_utc == "2025-01-06T19:15:00Z"
    assert len(review.folds) >= 3
    assert review.model_sha256 == MODEL_SHA256
    for fold in review.folds:
        assert fold.train_count >= 32
        assert fold.train_last_outcome_available_utc <= fold.embargo_cutoff_utc
        assert fold.embargo_cutoff_utc < fold.validation_first_decision_utc
        assert fold.train_last_decision_utc < fold.validation_first_decision_utc
        assert fold.validation_count == 12
        assert fold.correct_signs <= fold.validation_count
    assert max(s.decision_at_utc for s in dev) < review.holdout_first_utc
    assert max(s.outcome_available_at_utc for s in dev) < review.holdout_first_utc
    assert review.fold_evidence_sha256 == study.review_development().fold_evidence_sha256


def test_sealed_trial_must_register_then_freeze_then_reveal_exactly_once(tmp_path):
    study = SealedOOS(sample_history())
    path = tmp_path/"oos_trials.sqlite3"
    journal = TrialRegistry(path)
    assert not path.exists()
    journal.register(trial_key="first_trial", family="ema_family", study=study)
    with pytest.raises(ValueError, match="frozen"):
        journal.reveal_once("first_trial", study)
    tip = journal.freeze("first_trial", study)
    assert len(tip) == 64
    with pytest.raises(ValueError, match="already frozen"):
        journal.freeze("first_trial", study)
    output = journal.reveal_once("first_trial", study)
    assert output["holdout_count"] == 20
    assert output["holdout_start_utc"] == study.review_development().holdout_first_utc
    assert output["holdout_labels_sha256"] == study.holdout_sha256
    assert output["broker_cost_net_return_verified"] is False
    assert output["independent_out_of_sample_alpha_qualified"] is False
    assert 0 <= output["holdout_correct_signs"] <= 20
    with pytest.raises(ValueError, match="unspent"):
        journal.reveal_once("first_trial", study)
    record = journal.audit()
    assert record["event_count"] == 3
    assert record["completed_holdout_reveals"] == 1
    assert len(record["chain_tip_sha256"]) == 64
    assert record["chain_tip_sha256"] == output["registered_one_time_reveal_sha256"]


def test_trial_cannot_restart_same_family_with_different_name(tmp_path):
    r = TrialRegistry(tmp_path/"family.db")
    study = SealedOOS(sample_history())
    r.register(trial_key="candidate_a", family="one_hypothesis", study=study)
    with pytest.raises(sqlite3.IntegrityError):
        r.register(trial_key="candidate_b", family="one_hypothesis", study=study)
    assert r.audit()["event_count"] == 1


def test_different_registered_family_is_allowed_but_not_marked_independent(tmp_path):
    registry = TrialRegistry(tmp_path/"family.db")
    study = SealedOOS(sample_history())
    registry.register(trial_key="candidate_a", family="family_a", study=study)
    registry.register(trial_key="candidate_b", family="family_b", study=study)
    assert registry.audit()["event_count"] == 2


def test_trial_fingerprint_change_blocks_freeze_or_reveal(tmp_path):
    path = tmp_path/"immutable.db"
    registry = TrialRegistry(path)
    study = SealedOOS(sample_history())
    registry.register(trial_key="trial_x", family="study_group", study=study)
    changed = sample_history()
    modified = list(changed.bars)
    modified[100] = replace(modified[100], close=modified[100].close + 1)
    differing = SealedOOS(replace(changed, bars=tuple(modified), input_digest="c"*64))
    with pytest.raises(ValueError, match="frozen trial"):
        registry.freeze("trial_x", differing)
    registry.freeze("trial_x", study)
    with pytest.raises(ValueError, match="frozen trial"):
        registry.reveal_once("trial_x", differing)
    assert registry.audit()["completed_holdout_reveals"] == 0


@pytest.mark.parametrize(("field","value"), [
    ("pit_eligible", True), ("provenance","future"), ("native_m1_rows",599),
    ("input_digest","x"), ("source_archive_hashes", ()), 
])
def test_invalid_source_identity_and_point_in_time_claims_fail(field, value):
    h = sample_history()
    with pytest.raises(ValueError, match="unqualified"):
        SealedOOS(replace(h, **{field:value}))


def test_source_continuity_and_future_unclosed_or_bad_basis_blocked():
    h = sample_history()
    changes = [
        replace(h.bars[15], available_at_utc=h.bars[15].open_time_utc),
        replace(h.bars[15], open_time_utc=h.bars[15].open_time_utc+timedelta(minutes=1)),
        replace(h.bars[15], price_basis="ask"),
        replace(h.bars[15], close=Decimal("NaN")),
    ]
    for bar in changes:
        bars = list(h.bars)
        bars[15] = bar
        with pytest.raises(ValueError):
            SealedOOS(replace(h, bars=tuple(bars)))


@pytest.mark.parametrize("policy", [
    OOSPolicy(embargo_bars=1), OOSPolicy(forward_label_horizon=1),
    OOSPolicy(sealed_holdout_length=5),
    OOSPolicy(minimum_training=10),
    OOSPolicy(validation_length=0),
    OOSPolicy(embargo_bars=True),
])
def test_policy_downgrade_is_denied(policy):
    with pytest.raises(ValueError, match="policy"):
        SealedOOS(sample_history(), policy)


def test_too_small_sample_never_pretends_to_have_holdout():
    h = sample_history()
    with pytest.raises(ValueError, match="unqualified"):
        SealedOOS(replace(h, bars=h.bars[:90], native_m1_rows=450))


def test_registry_refuses_rewriting_events_and_reservations(tmp_path):
    study=SealedOOS(sample_history())
    r=TrialRegistry(tmp_path/"append.db")
    r.register(trial_key="trial_z",family="family_z",study=study)
    with sqlite3.connect(r.path) as db:
        with pytest.raises(sqlite3.DatabaseError, match="append only"):
            db.execute("UPDATE trial_events SET kind='reveal' WHERE seq=1")
        with pytest.raises(sqlite3.DatabaseError, match="append only"):
            db.execute("DELETE FROM trial_family_reservations")
    assert r.audit()["event_count"] == 1


def test_hash_chain_detects_database_tampering_even_after_triggers_removed(tmp_path):
    study=SealedOOS(sample_history())
    r=TrialRegistry(tmp_path/"tamper.db")
    r.register(trial_key="trial_z",family="family_z",study=study)
    with sqlite3.connect(r.path) as db:
        db.execute("DROP TRIGGER no_update_trial_events")
        db.execute("UPDATE trial_events SET payload_json='{}' WHERE seq=1")
        db.commit()
    with pytest.raises(ValueError, match="SHA256"):
        r.audit()


def test_bogus_registered_model_or_policy_cannot_be_adopted(tmp_path):
    r=TrialRegistry(tmp_path/"lock.db")
    source=SealedOOS(sample_history())
    r.register(trial_key="trial_z",family="fixed",study=source)
    mutated=SealedOOS(sample_history(),OOSPolicy(validation_length=10))
    with pytest.raises(ValueError, match="frozen trial"):
        r.freeze("trial_z", mutated)


def test_invalid_ids_are_denied(tmp_path):
    r=TrialRegistry(tmp_path/"bad.db")
    for name in ("../injected","a","a b","", "a"*81):
        with pytest.raises(ValueError):
            r.register(trial_key=name,family="safe",study=SealedOOS(sample_history()))
    assert not r.path.exists()
