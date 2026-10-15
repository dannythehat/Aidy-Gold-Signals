"""Day37: authenticated customer research history, versions and downloads."""
import hashlib
import io
import sqlite3
import zipfile

import pytest

from aidy.strategy_lab_customer_intake import RULE_FIELDS, prepare_intake
from aidy.strategy_lab_customer_results import CustomerResults, ResultRejected
from aidy.strategy_lab_tenant_vault import AccessDenied, TenantVault

K = b"K" * 32
P = b"P" * 32
A = b"A" * 32
ISSUER = b"I" * 32
PROOF = "a" * 64


@pytest.fixture
def clients(tmp_path):
    vault = TenantVault(tmp_path / "private" / "db.sqlite",
                        encryption_key=K, token_pepper=P, provision_key=A,
                        clock=lambda: 1_500_000)
    t1 = vault.provision(admin_key=A, username="customer_one",
                         password="this-is-a-fake-password-one")
    t2 = vault.provision(admin_key=A, username="customer_two",
                         password="this-is-a-fake-password-two")
    a = vault.login("customer_one", "this-is-a-fake-password-one")
    b = vault.login("customer_two", "this-is-a-fake-password-two")
    rules = dict.fromkeys(RULE_FIELDS, "Synthetic rule for acceptance only")
    rules["market"] = "XAUUSD"
    rules["timeframe"] = "H1"
    draft = prepare_intake(mode="paste", value="Synthetic customer source with no trading",
                           title="Private demo", rules=rules)
    da = vault.submit_draft(a, draft)
    db = vault.submit_draft(b, draft)
    svc = CustomerResults(vault, publisher_key=ISSUER)
    return vault, svc, (a, t1, da), (b, t2, db), draft


def _job(svc, actor, draft):
    token, tenant, record = actor
    del token
    return svc.create_job(publisher_key=ISSUER, tenant_id=tenant,
                          draft_id=record,
                          source_sha256=draft["source"]["original_sha256"])


def _complete(svc, job):
    svc.transition(publisher_key=ISSUER, job_id=job, new_stage="RESEARCH_RUNNING",
                   evidence_sha256=PROOF)
    svc.transition(publisher_key=ISSUER, job_id=job,
                   new_stage="SYNTHETIC_ACCEPTANCE_ONLY", evidence_sha256="b" * 64)


def test_job_identity_private_to_each_tenant(clients):
    _, svc, actor_a, actor_b, draft = clients
    job = _job(svc, actor_a, draft)
    assert [r["id"] for r in svc.list_jobs(actor_a[0])] == [job]
    assert svc.list_jobs(actor_b[0]) == []
    with pytest.raises(AccessDenied):
        svc.job_history(actor_b[0], job)
    with pytest.raises(AccessDenied):
        svc.list_artifacts(actor_b[0], job)
    assert len(svc.job_history(actor_a[0], job)) == 1


def test_identical_source_independent_account_version_history(clients):
    _, svc, actor_a, actor_b, draft = clients
    a1 = _job(svc, actor_a, draft)
    a2 = _job(svc, actor_a, draft)
    b1 = _job(svc, actor_b, draft)
    assert [j["version"] for j in svc.list_jobs(actor_a[0])] == [1, 2]
    assert [j["version"] for j in svc.list_jobs(actor_b[0])] == [1]
    assert len({a1, a2, b1}) == 3
    with pytest.raises(AccessDenied):
        svc.job_history(actor_a[0], b1)


def test_trusted_publisher_only_and_source_origin_validation(clients):
    _, svc, actor_a, actor_b, draft = clients
    _, tenant_a, id_a = actor_a
    _, tenant_b, id_b = actor_b
    with pytest.raises(AccessDenied):
        svc.create_job(publisher_key=b"forge", tenant_id=tenant_a, draft_id=id_a,
                       source_sha256=draft["source"]["original_sha256"])
    with pytest.raises(ResultRejected):
        svc.create_job(publisher_key=ISSUER, tenant_id=tenant_a, draft_id=id_b,
                       source_sha256=draft["source"]["original_sha256"])
    with pytest.raises(ResultRejected):
        svc.create_job(publisher_key=ISSUER, tenant_id=tenant_b, draft_id=id_a,
                       source_sha256=draft["source"]["original_sha256"])
    with pytest.raises(ResultRejected):
        svc.create_job(publisher_key=ISSUER, tenant_id=tenant_a, draft_id=id_a,
                       source_sha256="0" * 64)


def test_immutable_stage_history_and_no_fabricated_success(clients):
    _, svc, actor_a, _, draft = clients
    job = _job(svc, actor_a, draft)
    with pytest.raises(ResultRejected):
        svc.transition(publisher_key=ISSUER, job_id=job,
                       new_stage="VERIFIED_PROFIT", evidence_sha256=PROOF)
    _complete(svc, job)
    history = svc.job_history(actor_a[0], job)
    assert [r["stage"] for r in history] == [
        "RESEARCH_QUEUED", "RESEARCH_RUNNING", "SYNTHETIC_ACCEPTANCE_ONLY"]
    assert len({r["event_digest"] for r in history}) == len(history)
    with pytest.raises(ResultRejected):
        svc.transition(publisher_key=ISSUER, job_id=job,
                       new_stage="RESEARCH_RUNNING", evidence_sha256=PROOF)


def test_artifact_authentic_download_and_ciphertext(clients):
    vault, svc, actor_a, actor_b, draft = clients
    job = _job(svc, actor_a, draft)
    _complete(svc, job)
    raw = b'{"kind":"synthetic_fixture","net_pnl":null}'
    ident = svc.publish_artifact(publisher_key=ISSUER, job_id=job,
                                filename="report.json", kind="json", payload=raw)
    assert svc.download(actor_a[0], ident) == ("report.json", raw)
    assert svc.list_artifacts(actor_a[0], job)[0]["payload_hash"] == hashlib.sha256(raw).hexdigest()
    with pytest.raises(AccessDenied):
        svc.download(actor_b[0], ident)
    assert raw not in vault._path.read_bytes()
    with sqlite3.connect(vault._path) as con:
        encrypted = con.execute("SELECT ciphertext FROM customer_artifacts "
                                "WHERE id=?", (ident,)).fetchone()[0]
        con.execute("UPDATE customer_artifacts SET ciphertext=? WHERE id=?",
                    (encrypted[:14] + b"\x01" + encrypted[15:], ident))
    with pytest.raises(AccessDenied):
        svc.download(actor_a[0], ident)


def test_no_reports_until_blocked_or_synthetic_trial_done(clients):
    _, svc, actor_a, _, draft = clients
    job = _job(svc, actor_a, draft)
    with pytest.raises(ResultRejected):
        svc.publish_artifact(publisher_key=ISSUER, job_id=job,
                             filename="claim.pdf", kind="pdf",
                             payload=b"%PDF-1.5\nthis-is-not-genuine")
    svc.transition(publisher_key=ISSUER, job_id=job, new_stage="RESEARCH_BLOCKED",
                   evidence_sha256=PROOF)
    ident = svc.publish_artifact(publisher_key=ISSUER, job_id=job,
                                 filename="blocked.json", kind="json",
                                 payload=b'{"status":"blocked"}')
    assert svc.download(actor_a[0], ident)[1] == b'{"status":"blocked"}'


def test_file_extension_mime_and_path_fail_closed(clients):
    _, svc, actor_a, _, draft = clients
    job = _job(svc, actor_a, draft)
    _complete(svc, job)
    for filename, kind, raw in [
        ("../foo.json", "json", b"{}"), ("fake.exe", "json", b"{}"),
        (".hidden.json", "json", b"{}"),
        ("malformed.json", "json", b"<script/>"),
        ("malformed.pdf", "pdf", b"not actually pdf"),
        ("x.zip", "zip", b"PK\x03\x04"),
    ]:
        with pytest.raises(ResultRejected):
            svc.publish_artifact(publisher_key=ISSUER, job_id=job,
                                 filename=filename, kind=kind, payload=raw)


def test_repeatable_private_zip_download_and_html(clients):
    _, svc, actor_a, actor_b, draft = clients
    job = _job(svc, actor_a, draft)
    _complete(svc, job)
    svc.publish_artifact(publisher_key=ISSUER, job_id=job,
                         filename="evidence.json", kind="json",
                         payload=b'{"status":"synthetic-only"}')
    svc.publish_artifact(publisher_key=ISSUER, job_id=job,
                         filename="ledger.csv", kind="csv",
                         payload=b"trade,pnl\nsynthetic,0\n")
    archive1 = svc.export_job_zip(actor_a[0], job)
    archive2 = svc.export_job_zip(actor_a[0], job)
    assert archive1 == archive2
    with zipfile.ZipFile(io.BytesIO(archive1)) as z:
        assert z.namelist() == ["evidence.json", "job_history.json", "ledger.csv"]
        assert z.read("ledger.csv") == b"trade,pnl\nsynthetic,0\n"
    a_page = svc.offline_dashboard(actor_a[0])
    b_page = svc.offline_dashboard(actor_b[0])
    assert job in a_page and job not in b_page
    assert "GoldThinker" in a_page
    with pytest.raises(AccessDenied):
        svc.export_job_zip(actor_b[0], job)


def test_logout_refuses_report_discovery(clients):
    vault, svc, actor_a, _, draft = clients
    _job(svc, actor_a, draft)
    vault.logout(actor_a[0])
    with pytest.raises(AccessDenied):
        svc.list_jobs(actor_a[0])
    with pytest.raises(AccessDenied):
        svc.offline_dashboard(actor_a[0])


def test_untrusted_result_cannot_be_publish_with_client_key(clients):
    _, svc, actor_a, _, draft = clients
    job = _job(svc, actor_a, draft)
    _complete(svc, job)
    with pytest.raises(AccessDenied):
        svc.publish_artifact(publisher_key=b"customer-key", job_id=job,
                             filename="fake.json", kind="json", payload=b"{}")
    with pytest.raises(ResultRejected):
        svc.publish_artifact(publisher_key=ISSUER, job_id=job,
                             filename="gigantic.json", kind="json",
                             payload=b"A" * 2_000_001)


def test_customer_result_service_separate_keys(clients):
    vault, _, _, _, _ = clients
    for k in [b"tiny", P, A]:
        with pytest.raises(ValueError):
            CustomerResults(vault, publisher_key=k)
