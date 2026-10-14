"""Day10 genuine SQLite persistence, idempotency, version-chain and tamper tests."""
from __future__ import annotations

import copy
import json
import sqlite3
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest

from aidy.strategy_lab_registry import (
    RegistryConflictError,
    RegistryIntegrityError,
    StrategyRegistry,
)
from aidy.strategy_lab_spec import StrategySpec

FIXTURES = Path(__file__).parents[1] / "research" / "strategy_lab" / "fixtures"
SOURCE = (FIXTURES / "day09_internal_source_rules.txt").read_bytes()


def wire():
    data = json.loads((FIXTURES / "strategy_spec_v1_sample.json").read_text())
    data["origin"]["source_sha256"] = sha256(SOURCE).hexdigest()
    data["origin"]["source_snapshot_ref"] = (
        "research/strategy_lab/fixtures/day09_internal_source_rules.txt"
    )
    return data


def registry(tmp_path):
    target = StrategyRegistry(tmp_path / "research" / "strategy_versions.sqlite3")
    target.initialize()
    return target


def second_revision(data=None):
    data = copy.deepcopy(data or wire())
    data["revision"] = 2
    data["long"]["exit"]["stop_loss"]["value"] = "130"
    revised_source = SOURCE.replace(b"120 broker-defined ticks", b"130 broker-defined ticks")
    assert revised_source != SOURCE
    data["origin"]["source_sha256"] = sha256(revised_source).hexdigest()
    data["origin"]["source_snapshot_ref"] = "research/strategy_lab/fixtures/internal_revision2.txt"
    return StrategySpec.from_wire(data), revised_source


def test_real_sqlite_roundtrip_after_reopen(tmp_path):
    book = registry(tmp_path)
    spec = StrategySpec.from_wire(wire())
    record = book.register(spec, SOURCE)
    assert record.strategy_id == "sample_ema_cross"
    assert record.revision == 1
    assert record.original_source_sha256 == sha256(SOURCE).hexdigest()
    assert record.canonical_spec_json == spec.to_json()
    assert len(record.rules_sha256) == 64
    assert record.version_id.startswith("aidy-v1-")
    assert book.db_path.is_file()
    reopened = StrategyRegistry(book.db_path)
    assert reopened.versions("sample_ema_cross") == (record,)
    assert reopened.source_bytes("sample_ema_cross", 1) == SOURCE
    assert reopened.verify_all() == (record,)


def test_idempotent_exact_repeat_does_not_create_second_revision(tmp_path):
    book = registry(tmp_path)
    spec = StrategySpec.from_wire(wire())
    first = book.register(spec, SOURCE)
    second = book.register(spec, SOURCE)
    assert first == second
    assert len(book.verify_all()) == 1
    with sqlite3.connect(book.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM source_snapshots").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM versions").fetchone()[0] == 1


def test_changed_rule_requires_next_revision_and_records_immutable_chain(tmp_path):
    book = registry(tmp_path)
    base = book.register(StrategySpec.from_wire(wire()), SOURCE)
    modified, revised_source = second_revision()
    updated = book.register(modified, revised_source)
    assert updated.spec_sha256 != base.spec_sha256
    assert updated.rules_sha256 != base.rules_sha256
    assert updated.version_id != base.version_id
    assert updated.previous_version_sha256 == base.version_id
    assert book.verify_all() == (base, updated)
    assert StrategyRegistry(book.db_path).source_bytes(modified.strategy_id, 2) == revised_source


def test_changed_revision_metadata_preserves_rule_digest_but_versions_change(tmp_path):
    book = registry(tmp_path)
    first = book.register(StrategySpec.from_wire(wire()), SOURCE)
    next_data = wire()
    next_data["revision"] = 2
    next_data["origin"]["interpretation_notes"].append("Additional internal metadata")
    next_data["origin"]["author"] = "AIDY Strategy Lab source fixture amended"
    next_record = book.register(StrategySpec.from_wire(next_data), SOURCE)
    assert first.rules_sha256 == next_record.rules_sha256
    assert first.spec_sha256 != next_record.spec_sha256
    assert first.version_id != next_record.version_id
    assert next_record.previous_version_sha256 == first.version_id


def test_unversioned_rule_edits_cannot_overwrite_saved_revision(tmp_path):
    book = registry(tmp_path)
    first = book.register(StrategySpec.from_wire(wire()), SOURCE)
    changed = wire()
    changed["title"] = "Reworded after release"
    with pytest.raises(RegistryConflictError):
        book.register(StrategySpec.from_wire(changed), SOURCE)
    assert book.verify_all() == (first,)


@pytest.mark.parametrize("revision", [0, 3, 99])
def test_revisions_cannot_skip_a_number_or_start_at_non_one(tmp_path, revision):
    book = registry(tmp_path)
    data = wire()
    data["revision"] = revision
    if revision == 0:
        with pytest.raises(ValueError):
            StrategySpec.from_wire(data)
    else:
        with pytest.raises(RegistryConflictError):
            book.register(StrategySpec.from_wire(data), SOURCE)
    assert book.verify_all() == ()


def test_revisions_cannot_skip_after_one(tmp_path):
    book = registry(tmp_path)
    first = book.register(StrategySpec.from_wire(wire()), SOURCE)
    data = wire()
    data["revision"] = 3
    with pytest.raises(RegistryConflictError):
        book.register(StrategySpec.from_wire(data), SOURCE)
    assert book.verify_all() == (first,)


def test_incomplete_strategy_never_persists_source_or_revision(tmp_path):
    book = registry(tmp_path)
    data = wire()
    data["long"]["exit"]["stop_loss"] = None
    with pytest.raises(ValueError, match="MISSING_PROTECTIVE_STOP"):
        book.register(StrategySpec.from_wire(data), SOURCE)
    assert book.verify_all() == ()
    with sqlite3.connect(book.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM source_snapshots").fetchone()[0] == 0


def test_changed_source_cannot_be_mislabeled_with_old_digest(tmp_path):
    book = registry(tmp_path)
    with pytest.raises(ValueError, match="SOURCE_HASH_MISMATCH"):
        book.register(StrategySpec.from_wire(wire()), b"modified original source")
    assert book.verify_all() == ()


def test_direct_update_and_delete_are_denied_by_sqlite_triggers(tmp_path):
    book = registry(tmp_path)
    book.register(StrategySpec.from_wire(wire()), SOURCE)
    with sqlite3.connect(book.db_path) as conn:
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            conn.execute("UPDATE versions SET author='changed'")
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            conn.execute("DELETE FROM source_snapshots")
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            conn.execute("UPDATE source_snapshots SET original_bytes=?", (b"tampered",))
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            conn.execute("DELETE FROM versions")
    assert len(book.verify_all()) == 1


def test_dropped_guard_rejected_before_register_or_read(tmp_path):
    book = registry(tmp_path)
    book.register(StrategySpec.from_wire(wire()), SOURCE)
    with sqlite3.connect(book.db_path) as conn:
        conn.execute("DROP TRIGGER versions_no_update")
    with pytest.raises(RegistryIntegrityError, match="guards"):
        book.verify_all()
    with pytest.raises(RegistryIntegrityError, match="guards"):
        book.register(StrategySpec.from_wire(wire()), SOURCE)


def test_altered_canonical_record_detected_even_after_guard_repair(tmp_path):
    book = registry(tmp_path)
    book.register(StrategySpec.from_wire(wire()), SOURCE)
    with sqlite3.connect(book.db_path) as conn:
        conn.execute("DROP TRIGGER versions_no_update")
        conn.execute(
            "UPDATE versions SET canonical_spec_json = ? WHERE revision=1",
            ('{"strategy_id":"forged"}',),
        )
    book.initialize()
    with pytest.raises(RegistryIntegrityError):
        book.verify_all()


def test_altered_raw_source_detected_after_guard_repair(tmp_path):
    book = registry(tmp_path)
    book.register(StrategySpec.from_wire(wire()), SOURCE)
    with sqlite3.connect(book.db_path) as conn:
        conn.execute("DROP TRIGGER source_snapshots_no_update")
        conn.execute("UPDATE source_snapshots SET original_bytes=?", (b"forged",))
    book.initialize()
    with pytest.raises(RegistryIntegrityError, match="source bytes"):
        book.source_bytes("sample_ema_cross", 1)


def test_altered_previous_link_detected_after_guard_repair(tmp_path):
    book = registry(tmp_path)
    book.register(StrategySpec.from_wire(wire()), SOURCE)
    second, revised_source = second_revision()
    book.register(second, revised_source)
    with sqlite3.connect(book.db_path) as conn:
        conn.execute("DROP TRIGGER versions_no_update")
        conn.execute(
            "UPDATE versions SET previous_version_sha256 = NULL WHERE revision=2"
        )
    book.initialize()
    with pytest.raises(RegistryIntegrityError):
        book.verify_all()


def test_multiple_strategies_and_separate_version_sequences(tmp_path):
    book = registry(tmp_path)
    left = book.register(StrategySpec.from_wire(wire()), SOURCE)
    data = wire()
    data["strategy_id"] = "other_gold_strategy"
    right = book.register(StrategySpec.from_wire(data), SOURCE)
    assert left.rules_sha256 == right.rules_sha256
    assert left.version_id != right.version_id
    assert len(book.verify_all()) == 2
    with sqlite3.connect(book.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM source_snapshots").fetchone()[0] == 1


def test_direct_invalid_dataclass_bypasses_neither_parser_nor_registry(tmp_path):
    book = registry(tmp_path)
    spec = StrategySpec.from_wire(wire())
    invalid = replace(spec, warmup_closed_bars=-1)
    with pytest.raises(ValueError):
        book.register(invalid, SOURCE)
    assert book.verify_all() == ()


def test_registry_requires_real_sqlite_initialization(tmp_path):
    book = StrategyRegistry(tmp_path / "missing_directory" / "missing.sqlite3")
    with pytest.raises(sqlite3.OperationalError):
        book.versions("sample_ema_cross")
    assert not book.db_path.exists()
