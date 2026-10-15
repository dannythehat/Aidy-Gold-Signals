"""Day39 encrypted restore and Day40 evidence-forgery adversarial acceptance."""
import sqlite3

import pytest

from aidy.strategy_lab_customer_intake import RULE_FIELDS, prepare_intake
from aidy.strategy_lab_encrypted_snapshot import EncryptedSnapshot, OperationsRejected
from aidy.strategy_lab_launch_gate import GATES, evaluate_launch
from aidy.strategy_lab_operational_controls import OperationalControls
from aidy.strategy_lab_tenant_vault import AccessDenied, TenantVault

OP = b"O" * 32
BACKUP = b"B" * 32
P = b"P" * 32
K = b"K" * 32
U = b"U" * 32


@pytest.fixture
def real_isolated_drafts(tmp_path):
    vault = TenantVault(
        tmp_path / "private" / "source.db",
        encryption_key=K, token_pepper=P,
        provision_key=U, clock=lambda: 1_800_000,
    )
    rights = dict.fromkeys(RULE_FIELDS, "Synthetic test scenario only")
    rights.update(market="XAUUSD", timeframe="M5")
    packets = []
    for name in ("synthetic_one", "synthetic_two"):
        vault.provision(admin_key=U, username=name,
                        password="test-credentials-not-deployed-" + name)
        token = vault.login(name, "test-credentials-not-deployed-" + name)
        packet = prepare_intake(
            mode="paste", title="Isolated sample",
            rules=rights, value="Confidential synthetic data for " + name,
        )
        ident = vault.submit_draft(token, packet)
        packets.append((token, ident, packet))
    ops = OperationalControls(vault, operations_key=OP)
    return vault, ops, packets, tmp_path


def test_genuine_encrypted_backup_and_restore_two_private_tenants(real_isolated_drafts):
    vault, ops, packets, tmp_path = real_isolated_drafts
    service = EncryptedSnapshot(ops, backup_key=BACKUP)
    bundle = tmp_path / "separate" / "private.backup"
    receipt = service.create(operator_key=OP, destination=bundle)
    assert receipt["status"] == "ENCRYPTED_LOCAL_SNAPSHOT"
    assert receipt["external_cloud_storage_confirmed"] is False
    assert b"Confidential synthetic data" not in bundle.read_bytes()
    restored_file = tmp_path / "recovered" / "data.db"
    status = service.restore(operator_key=OP, source=bundle, destination=restored_file)
    assert status["sqlite_quick_check"] == "ok"
    assert status["production_remote_restore_certified"] is False
    restored_vault = TenantVault(
        restored_file, encryption_key=K, token_pepper=P,
        provision_key=U, clock=lambda: 1_800_000,
    )
    for token, ident, packet in packets:
        assert restored_vault.read_draft(token, ident) == packet
    assert vault.list_drafts(packets[0][0]) == restored_vault.list_drafts(packets[0][0])
    with pytest.raises(AccessDenied):
        restored_vault.read_draft(packets[0][0], packets[1][1])


def test_tamper_and_wrong_backup_key_do_not_create_plaintext_file(real_isolated_drafts):
    _, ops, _, tmp_path = real_isolated_drafts
    service = EncryptedSnapshot(ops, backup_key=BACKUP)
    source = tmp_path / "private" / "copy.snapshot"
    service.create(operator_key=OP, destination=source)
    forged = tmp_path / "private" / "forged.snapshot"
    content = source.read_bytes()
    forged.write_bytes(content[:-20] + b"x" * 20)
    bad_restore = tmp_path / "restore" / "bad.db"
    with pytest.raises(AccessDenied):
        service.restore(operator_key=OP, source=forged, destination=bad_restore)
    assert not bad_restore.exists()
    other = EncryptedSnapshot(ops, backup_key=b"C" * 32)
    with pytest.raises(AccessDenied):
        other.restore(operator_key=OP, source=source, destination=bad_restore)
    assert not bad_restore.exists()


def test_existing_destination_never_overwritten(real_isolated_drafts):
    _, ops, _, root = real_isolated_drafts
    service = EncryptedSnapshot(ops, backup_key=BACKUP)
    snap = root / "locked" / "backup.bin"
    service.create(operator_key=OP, destination=snap)
    with pytest.raises(OperationsRejected):
        service.create(operator_key=OP, destination=snap)
    output = root / "locked" / "existing.sqlite"
    output.write_text("do not overwrite")
    with pytest.raises(OperationsRejected):
        service.restore(operator_key=OP, source=snap, destination=output)
    assert output.read_text() == "do not overwrite"


def test_backup_operator_secret_and_key_reuse_denied(real_isolated_drafts):
    _, ops, _, root = real_isolated_drafts
    with pytest.raises(ValueError):
        EncryptedSnapshot(ops, backup_key=OP)
    with pytest.raises(ValueError):
        EncryptedSnapshot(ops, backup_key=P)
    with pytest.raises(ValueError):
        EncryptedSnapshot(ops, backup_key=b"short")
    service = EncryptedSnapshot(ops, backup_key=BACKUP)
    with pytest.raises(AccessDenied):
        service.create(operator_key=b"wrong", destination=root / "x.backup")
    assert not (root / "x.backup").exists()


def test_untrusted_true_booleans_cannot_certify_actual_external_payment_and_pilot():
    claims = dict.fromkeys(GATES, True)
    result = evaluate_launch(claims)
    assert result["status"] == "NO_GO"
    assert result["verified_external_evidence_count"] == 0
    assert "consenting_real_two_user_pilot" in result["unverified_assertions"]
    assert "day38_actual_payment_sandbox" in result["unverified_assertions"]
    assert result["automated_trade_or_public_launch_authority"] is False


def test_backup_file_ciphertext_not_sqlite_and_restored_database_valid(real_isolated_drafts):
    _, ops, _, root = real_isolated_drafts
    service = EncryptedSnapshot(ops, backup_key=BACKUP)
    artifact = root / "storage" / "encrypted.bin"
    service.create(operator_key=OP, destination=artifact)
    assert not artifact.read_bytes().startswith(b"SQLite format 3")
    restored = root / "storage" / "restored.db"
    service.restore(operator_key=OP, source=artifact, destination=restored)
    with sqlite3.connect(restored) as db:
        assert db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert db.execute("SELECT COUNT(*) FROM drafts").fetchone()[0] == 2
