"""Day36 two-user privacy and hostile-upload acceptance (no public service)."""
import hashlib
import json
import sqlite3

import pytest

from aidy.strategy_lab_customer_intake import RULE_FIELDS, prepare_intake
from aidy.strategy_lab_tenant_vault import AccessDenied, InvalidSubmission, TenantVault

ADMIN = b"A" * 32
KEY = b"K" * 32
PEPPER = b"P" * 32


@pytest.fixture
def context(tmp_path):
    now = [1_000_000]
    vault = TenantVault(
        tmp_path / "non_web_root" / "customer.sqlite3",
        encryption_key=KEY, token_pepper=PEPPER, provision_key=ADMIN,
        clock=lambda: now[0],
    )
    ta = vault.provision(admin_key=ADMIN, username="owner_alice",
                         password="super-long-independent-password-a")
    tb = vault.provision(admin_key=ADMIN, username="owner_bob",
                         password="super-long-independent-password-b")
    a = vault.login("owner_alice", "super-long-independent-password-a")
    b = vault.login("owner_bob", "super-long-independent-password-b")
    rules = {field: "Explicit source-defined rule" for field in RULE_FIELDS}
    rules.update({"market": "XAUUSD", "timeframe": "H1"})
    draft = prepare_intake(
        mode="paste", value="Confidential original customer rule text (DO NOT SHARE)",
        title="Customer alpha model", rules=rules,
    )
    return vault, now, ta, tb, a, b, draft


def test_two_users_are_independent_tenants(context):
    vault, _, ta, tb, a, b, draft = context
    assert ta != tb
    record = vault.submit_draft(a, draft)
    assert vault.read_draft(a, record) == draft
    assert len(vault.list_drafts(a)) == 1
    assert vault.list_drafts(b) == []
    with pytest.raises(AccessDenied):
        vault.read_draft(b, record)
    with pytest.raises(AccessDenied):
        vault.delete_draft(b, record)
    assert vault.read_draft(a, record) == draft


def test_same_rules_stored_independently_and_not_shared(context):
    vault, _, _, _, a, b, draft = context
    ida = vault.submit_draft(a, draft)
    idb = vault.submit_draft(b, draft)
    assert ida != idb
    assert len(vault.list_drafts(a)) == len(vault.list_drafts(b)) == 1
    with pytest.raises(AccessDenied):
        vault.read_draft(b, ida)
    with pytest.raises(AccessDenied):
        vault.read_draft(a, idb)


def test_data_is_aes_encrypted_and_not_plaintext(context):
    vault, _, _, _, a, _, draft = context
    record = vault.submit_draft(a, draft)
    disk = vault._path.read_bytes()
    assert b"Confidential original customer rule text" not in disk
    with sqlite3.connect(vault._path) as con:
        blob = con.execute("SELECT blob FROM drafts WHERE id=?", (record,)).fetchone()[0]
        assert b"Confidential original customer rule text" not in blob
        con.execute("UPDATE drafts SET blob=? WHERE id=?", (blob[:14] + b"\x00" + blob[15:],
                                                              record))
    with pytest.raises(AccessDenied):
        vault.read_draft(a, record)


def test_session_logout_and_expiration(context):
    vault, now, _, _, a, _, draft = context
    vault.logout(a)
    with pytest.raises(AccessDenied):
        vault.submit_draft(a, draft)
    token = vault.login("owner_alice", "super-long-independent-password-a")
    now[0] += 3601
    with pytest.raises(AccessDenied):
        vault.list_drafts(token)


def test_expiry_hides_and_purges_drafts(context):
    vault, now, _, _, a, _, draft = context
    ident = vault.submit_draft(a, draft, retention_seconds=10)
    now[0] += 11
    with pytest.raises(AccessDenied):
        vault.read_draft(a, ident)
    assert vault.list_drafts(a) == []
    assert vault.purge_expired(admin_key=ADMIN)[0] == 1


def test_invalid_retention_and_admin_secret(context):
    vault, _, _, _, a, _, draft = context
    for seconds in [0, 90 * 86400 + 1, True, "42"]:
        with pytest.raises(InvalidSubmission):
            vault.submit_draft(a, draft, retention_seconds=seconds)
    with pytest.raises(AccessDenied):
        vault.purge_expired(admin_key=b"attacker")
    with pytest.raises(AccessDenied):
        vault.provision(admin_key=b"attacker", username="other_user",
                        password="anotherlongpassword")


def test_privilege_escalation_and_rehash_forbidden(context):
    vault, _, _, _, a, _, draft = context
    forged = json.loads(json.dumps(draft))
    forged["tenant_authenticated"] = True
    without_hash = {k: v for k, v in forged.items() if k != "draft_sha256"}
    forged["draft_sha256"] = hashlib.sha256(
        json.dumps(without_hash, ensure_ascii=True, sort_keys=True,
                   separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()
    with pytest.raises(InvalidSubmission):
        vault.submit_draft(a, forged)


def test_rehashed_source_field_forgery_fails(context):
    vault, _, _, _, a, _, draft = context
    forged = json.loads(json.dumps(draft))
    forged["source"]["inert_text"] = "New fake verified source"
    without_hash = {k: v for k, v in forged.items() if k != "draft_sha256"}
    forged["draft_sha256"] = hashlib.sha256(
        json.dumps(without_hash, ensure_ascii=True, sort_keys=True,
                   separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()
    with pytest.raises(InvalidSubmission):
        vault.submit_draft(a, forged)


def test_inert_uploads_and_invalid_files(context):
    vault, _, _, _, a, _, draft = context
    source = draft["source"]
    rules = draft["rules"]
    clean = prepare_intake(mode="upload", value=b"XAUUSD original UTF8 rule set",
                           filename="alpha.txt", title="Customer alpha model",
                           media_type="text/plain", rules=rules)
    ident = vault.submit_draft(a, clean)
    assert vault.read_draft(a, ident)["source"]["kind"] == "upload"
    assert source["kind"] == "paste"
    for blob in [b"MZevil", b"PK\x03\x04", b"%PDF-1.7", b"hi\x00evil"]:
        with pytest.raises(ValueError):
            prepare_intake(mode="upload", value=blob, filename="x.txt",
                           title="Customer alpha model", rules=rules)


def test_bad_records_and_tokens_are_indistinguishable(context):
    vault, _, _, _, a, b, draft = context
    ident = vault.submit_draft(a, draft)
    for token in ["fake", "", a + "x", None]:
        with pytest.raises(AccessDenied):
            vault.read_draft(token, ident)
    for key in ["../secret", "' OR 1=1 --", "f" * 32]:
        with pytest.raises(AccessDenied):
            vault.read_draft(b, key)
        with pytest.raises(AccessDenied):
            vault.delete_draft(b, key)


def test_login_rate_limit_and_password_policy(context):
    vault, now, _, _, _, _, _ = context
    for _ in range(5):
        with pytest.raises(AccessDenied):
            vault.login("owner_bob", "wrong-password")
    with pytest.raises(AccessDenied):
        vault.login("owner_bob", "super-long-independent-password-b")
    now[0] += 3601
    assert vault.login("owner_bob", "super-long-independent-password-b")
    with pytest.raises(ValueError):
        vault.provision(admin_key=ADMIN, username="short",
                        password="short")


def test_key_config_and_symlink_fail_closed(tmp_path):
    with pytest.raises(ValueError):
        TenantVault(tmp_path / "q.db", encryption_key=b"tiny",
                    token_pepper=PEPPER, provision_key=ADMIN)
    with pytest.raises(ValueError):
        TenantVault(tmp_path / "q.db", encryption_key=KEY,
                    token_pepper=KEY, provision_key=ADMIN)
    dest = tmp_path / "real"
    dest.write_bytes(b"not SQLite")
    alias = tmp_path / "alias"
    alias.symlink_to(dest)
    with pytest.raises(ValueError):
        TenantVault(alias, encryption_key=KEY,
                    token_pepper=PEPPER, provision_key=ADMIN)
