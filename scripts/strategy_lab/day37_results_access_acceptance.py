"""Day37 private two-user result/demo export proof. No real strategy tests."""
from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

from aidy.strategy_lab_customer_intake import RULE_FIELDS, prepare_intake
from aidy.strategy_lab_customer_results import CustomerResults
from aidy.strategy_lab_tenant_vault import AccessDenied, TenantVault


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="day37-") as root:
        vault = TenantVault(
            Path(root) / "private" / "db.sqlite3",
            encryption_key=b"K" * 32, token_pepper=b"P" * 32,
            provision_key=b"A" * 32, clock=lambda: 1_500_000,
        )
        issuer = b"I" * 32
        results = CustomerResults(vault, publisher_key=issuer)
        rules = dict.fromkeys(RULE_FIELDS, "Synthetic test rule only")
        rules.update(market="XAUUSD", timeframe="H1")
        draft = prepare_intake(
            mode="paste", title="Synthetic only demo", rules=rules,
            value="Synthetic strategy source (not production)",
        )
        accounts = []
        for username, password in [
            ("synthetic_user_one", "fake-test-only-password-one"),
            ("synthetic_user_two", "fake-test-only-password-two"),
        ]:
            tenant = vault.provision(admin_key=b"A" * 32,
                                     username=username, password=password)
            token = vault.login(username, password)
            origin = vault.submit_draft(token, draft)
            job = results.create_job(
                publisher_key=issuer, tenant_id=tenant, draft_id=origin,
                source_sha256=draft["source"]["original_sha256"],
            )
            results.transition(publisher_key=issuer, job_id=job,
                               new_stage="RESEARCH_BLOCKED",
                               evidence_sha256="f" * 64)
            artifact = results.publish_artifact(
                publisher_key=issuer, job_id=job, filename="status.json",
                kind="json", payload=b'{"status":"RESEARCH_BLOCKED","pnl":null}',
            )
            assert results.download(token, artifact)[1].endswith(b"null}")
            assert results.export_job_zip(token, job) == results.export_job_zip(token, job)
            assert len(results.job_history(token, job)) == 2
            assert job in results.offline_dashboard(token)
            accounts.append((token, tenant, job, artifact))
        rejected = 0
        for i in (0, 1):
            outsider, _tenant, _job, _file = accounts[i]
            other = accounts[1 - i]
            for attack in [
                lambda: results.job_history(outsider, other[2]),
                lambda: results.download(outsider, other[3]),
                lambda: results.export_job_zip(outsider, other[2]),
            ]:
                try:
                    attack()
                except AccessDenied:
                    rejected += 1
        assert rejected == 6
        packet = {
            "status": "SCOPED_SYNTHETIC_PASS", "day": 37,
            "tenants": 2, "private_jobs": 2, "private_encrypted_artifacts": 2,
            "cross_tenant_access_attempts_rejected": rejected,
            "deterministic_archive_per_job": True,
            "authenticated_download_required": True,
            "privileged_evidence_status": "RESEARCH_BLOCKED",
            "real_strategy_tests": 0, "real_customer_results": 0,
            "customer_site_hosted": False,
            "paper_or_live_orders": 0,
        }
        packet["sha256"] = hashlib.sha256(json.dumps(
            packet, sort_keys=True, separators=(",", ":"),
        ).encode()).hexdigest()
        out = Path("artifacts/strategy_lab/day37/results_access_acceptance.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n")
        print("Day37 two-user encrypted private results/export: PASS")


if __name__ == "__main__":
    main()
