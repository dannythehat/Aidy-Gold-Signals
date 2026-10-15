"""Scoped two-user B10 privacy proof; no real customer source or hosted API."""
from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

from aidy.strategy_lab_customer_intake import RULE_FIELDS, prepare_intake
from aidy.strategy_lab_tenant_vault import AccessDenied, TenantVault


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="aidy-day36-") as root:
        path = Path(root) / "quarantine" / "tenants.sqlite3"
        secret = b"A" * 32
        vault = TenantVault(
            path, encryption_key=b"K" * 32, token_pepper=b"P" * 32,
            provision_key=secret, clock=lambda: 1_000_000,
        )
        alice = vault.provision(
            admin_key=secret, username="synthetic_alice",
            password="example-only-password-alice",
        )
        bob = vault.provision(
            admin_key=secret, username="synthetic_bob",
            password="example-only-password-bob",
        )
        a = vault.login("synthetic_alice", "example-only-password-alice")
        b = vault.login("synthetic_bob", "example-only-password-bob")
        rules = dict.fromkeys(RULE_FIELDS, "Synthetic documented demo clause")
        rules.update(market="XAUUSD", timeframe="H1")
        draft = prepare_intake(
            mode="paste", title="Synthetic nontrade submission",
            rules=rules, value="Confidential synthetic strategy phrase",
        )
        identifier = vault.submit_draft(a, draft, retention_seconds=1800)
        assert vault.read_draft(a, identifier) == draft
        assert vault.list_drafts(b) == []
        rejected = 0
        for attack in (lambda: vault.read_draft(b, identifier),
                       lambda: vault.delete_draft(b, identifier),
                       lambda: vault.list_drafts("forged-token"),
                       lambda: vault.purge_expired(admin_key=b"attacker")):
            try:
                attack()
            except AccessDenied:
                rejected += 1
        assert rejected == 4
        assert b"Confidential synthetic strategy phrase" not in path.read_bytes()
        vault.delete_draft(a, identifier)
        assert vault.list_drafts(a) == []
        packet = {
            "status": "SCOPED_SYNTHETIC_PASS",
            "day": 36,
            "schema": "aidy.strategy_lab.day36.tenant_acceptance.v1",
            "tenants_created": 2,
            "tenant_identities_distinct": alice != bob,
            "adversarial_access_checks_rejected": rejected,
            "private_draft_round_trip": True,
            "client_source_executed": False,
            "authenticated_public_server_deployed": False,
            "real_strategy_backtests_executed": 0,
            "goldthinker_paper_or_live_orders": 0,
            "storage_notes": "Encrypted SQLite; backup/WAL crypto-erasure not certified.",
        }
        digest = hashlib.sha256(json.dumps(
            packet, sort_keys=True, separators=(",", ":"),
        ).encode()).hexdigest()
        packet["acceptance_sha256"] = digest
        output = Path("artifacts/strategy_lab/day36/tenant_acceptance.json")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(packet, sort_keys=True, indent=2) + "\n")
        print(f"Day36 scoped private two-user acceptance: {packet['status']} {digest}")


if __name__ == "__main__":
    main()
