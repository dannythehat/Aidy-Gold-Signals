"""Day38 internal preview compute-meter proof; real sandbox payment deliberately blocked."""
from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

from aidy.strategy_lab_compute_entitlements import ComputeEntitlements
from aidy.strategy_lab_tenant_vault import TenantVault


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="day38-") as root:
        vault = TenantVault(
            Path(root) / "private" / "db.sqlite",
            encryption_key=b"K" * 32, token_pepper=b"P" * 32,
            provision_key=b"U" * 32, clock=lambda: 1_500_000,
        )
        ledger = ComputeEntitlements(
            vault, administrator_key=b"A" * 32, scheduler_key=b"S" * 32,
        )
        tenant = vault.provision(
            admin_key=b"U" * 32, username="internal_owner_preview",
            password="preview-owner-only-test-password",
        )
        session = vault.login("internal_owner_preview", "preview-owner-only-test-password")
        ledger.configure_preview(
            admin_key=b"A" * 32, tenant_id=tenant, plan="preview_owner",
            monthly_cap=100, owner_billing_exempt=True,
        )
        token = ledger.record_usage(
            scheduler_key=b"S" * 32, customer_token=session,
            job_id="f" * 32, units=27,
        )
        assert token == ledger.record_usage(
            scheduler_key=b"S" * 32, customer_token=session,
            job_id="f" * 32, units=27,
        )
        state = ledger.private_summary(session)
        assert state["owner_billing_exempt"] and state["compute_units"] == 27
        assert state["compute_units_remaining"] == 73
        assert not state["paid_subscription"] and state["subscription_price"] is None
        assert not ledger.payment_state(session)["sandbox_charge_tested"]
        result = {
            "day": 38,
            "status": "PARTIAL_EXTERNAL_PAYMENT_BLOCKED",
            "owner_billing_exemption_preview_test": "PASS",
            "atomic_units_metered": 27,
            "duplicate_replay_unchanged": True,
            "monthly_cap_units": 100,
            "real_provider_connected": False,
            "real_sandbox_payment": "NOT_RUN",
            "real_customer_charges": 0,
            "real_gold_strategy_tests": 0,
            "real_customer_subscription_price_set": False,
            "go_live_allowed": False,
        }
        result["digest"] = hashlib.sha256(json.dumps(
            result, sort_keys=True, separators=(",", ":"),
        ).encode()).hexdigest()
        out = Path("artifacts/strategy_lab/day38/billing_preview_acceptance.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        print("Day38 internal meter PASS; real sandbox payment NOT RUN — Day38 BLOCKED")


if __name__ == "__main__":
    main()
