"""Day39 encrypted artifact cross-runner recovery drill for synthetic tenants only."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from aidy.strategy_lab_customer_intake import RULE_FIELDS, prepare_intake
from aidy.strategy_lab_encrypted_snapshot import EncryptedSnapshot
from aidy.strategy_lab_operational_controls import OperationalControls
from aidy.strategy_lab_tenant_vault import AccessDenied, TenantVault

BACKUP = b"B" * 32  # synthetic fixtures ONLY; NEVER use with real customer data
OP = b"O" * 32
ENCRYPT = b"K" * 32
PEPPER = b"P" * 32
PROVISION = b"U" * 32
ARTIFACT = Path("artifacts/strategy_lab/day39/remote_runner_fixture.enc")
MANIFEST = Path("artifacts/strategy_lab/day39/remote_runner_manifest.json")
PARTIES = {
    "synthetic_alpha": "synthetic-example-password-alpha",
    "synthetic_beta": "synthetic-example-password-beta",
}


def make() -> None:
    path = Path("artifacts/strategy_lab/day39/synthetic_source.sqlite")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    v = TenantVault(path, encryption_key=ENCRYPT, token_pepper=PEPPER,
                    provision_key=PROVISION, clock=lambda: 1_800_000)
    rules = dict.fromkeys(RULE_FIELDS, "Independent synthetic verification")
    rules.update(market="XAUUSD", timeframe="M5")
    for username, pw in PARTIES.items():
        v.provision(admin_key=PROVISION, username=username, password=pw)
        token = v.login(username, pw)
        packet = prepare_intake(mode="paste", title="Synthetic demo",
                                value=f"Private fixture of {username}", rules=rules)
        v.submit_draft(token, packet)
    ops = OperationalControls(v, operations_key=OP)
    receipt = EncryptedSnapshot(ops, backup_key=BACKUP).create(
        operator_key=OP, destination=ARTIFACT,
    )
    assert b"Private fixture of" not in ARTIFACT.read_bytes()
    manifest = {
        "scope": "ONLY_SYNTHETIC_CI_FIXTURE_NOT_PRODUCTION_DR",
        "expected_users": 2,
        "expected_drafts": 2,
        "ciphertext_sha256": receipt["ciphertext_sha256"],
        "production_remote_restore_certified": False,
        "source_gold_strategies_backtested": 0,
    }
    MANIFEST.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
    path.unlink()
    print("Synthetic backup encrypted; no plaintext DB uploaded.")


def restore() -> None:
    m = json.loads(MANIFEST.read_text())
    assert hashlib.sha256(ARTIFACT.read_bytes()).hexdigest() == m["ciphertext_sha256"]
    path = Path("artifacts/strategy_lab/day39/independent_restore_control.sqlite")
    path.unlink(missing_ok=True)
    dummy = TenantVault(path, encryption_key=ENCRYPT, token_pepper=PEPPER,
                        provision_key=PROVISION, clock=lambda: 1_800_000)
    ops = OperationalControls(dummy, operations_key=OP)
    dest = Path("artifacts/strategy_lab/day39/independent_restored.sqlite")
    dest.unlink(missing_ok=True)
    outcome = EncryptedSnapshot(ops, backup_key=BACKUP).restore(
        operator_key=OP, source=ARTIFACT, destination=dest,
    )
    independent = TenantVault(dest, encryption_key=ENCRYPT, token_pepper=PEPPER,
                              provision_key=PROVISION, clock=lambda: 1_800_000)
    a = independent.login("synthetic_alpha", PARTIES["synthetic_alpha"])
    b = independent.login("synthetic_beta", PARTIES["synthetic_beta"])
    item_a = independent.list_drafts(a)[0]["id"]
    item_b = independent.list_drafts(b)[0]["id"]
    assert len(independent.list_drafts(a)) == len(independent.list_drafts(b)) == 1
    assert "synthetic_alpha" in independent.read_draft(a, item_a)["source"]["inert_text"]
    assert "synthetic_beta" in independent.read_draft(b, item_b)["source"]["inert_text"]
    for session, record in ((a, item_b), (b, item_a)):
        try:
            independent.read_draft(session, record)
        except AccessDenied:
            continue
        raise AssertionError("Cross-tenant restore access breached")
    audit = {
        "status": "PASS_SYNTHETIC_REMOTE_ARTIFACT_RESTORE",
        "encrypted_artifact_transport": "GITHUB_ACTIONS_SEPARATE_RUNNER",
        "ciphertext_sha256": m["ciphertext_sha256"],
        "restored_users": 2,
        "restored_private_drafts": 2,
        "cross_tenant_attacks_rejected": 2,
        "sqlite_verified": outcome["sqlite_quick_check"] == "ok",
        "production_remote_restore_certified": False,
        "actual_customer_pilot": False,
        "real_sandbox_payment": False,
        "day38_39_40_original_acceptance": "BLOCKED",
    }
    output = Path("artifacts/strategy_lab/day39/synthetic_remote_restore_result.json")
    output.write_text(json.dumps(audit, sort_keys=True, indent=2) + "\n")
    print("PASS separate GitHub runner synthetic encrypted restore; not production DR")


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in {"make", "restore"}:
        raise SystemExit("Usage: python -m scripts.strategy_lab.day39_encrypted_restore_drill make|restore")
    {"make": make, "restore": restore}[sys.argv[1]]()
