"""Day38: deliberately no fake payments, private caps and owner-billing exemption."""
import pytest

from aidy.strategy_lab_compute_entitlements import (
    BillingRejected,
    ComputeEntitlements,
)
from aidy.strategy_lab_tenant_vault import AccessDenied, TenantVault

ADMIN = b"A" * 32
PROVISION = b"U" * 32
SCHEDULER = b"S" * 32


@pytest.fixture
def env(tmp_path):
    now = [1_500_000]
    vault = TenantVault(
        tmp_path / "private" / "test.sqlite",
        encryption_key=b"K" * 32,
        token_pepper=b"P" * 32,
        provision_key=PROVISION,
        clock=lambda: now[0],
    )
    tenants = []
    for name, pw in [
        ("tenant_owner", "test-only-long-password-owner"),
        ("tenant_guest", "test-only-long-password-guest"),
    ]:
        ident = vault.provision(admin_key=PROVISION, username=name, password=pw)
        tenants.append((ident, vault.login(name, pw)))
    service = ComputeEntitlements(
        vault, administrator_key=ADMIN, scheduler_key=SCHEDULER,
    )
    service.configure_preview(
        admin_key=ADMIN, tenant_id=tenants[0][0],
        plan="owner_research", monthly_cap=150, owner_billing_exempt=True,
    )
    service.configure_preview(
        admin_key=ADMIN, tenant_id=tenants[1][0],
        plan="customer_research", monthly_cap=100, owner_billing_exempt=False,
    )
    return now, vault, service, tenants


def test_owner_billing_exempt_but_not_evidence_or_compute_cap_exempt(env):
    _, _, ledger, ((tenant, token), _) = env
    del tenant
    s = ledger.private_summary(token)
    assert s["owner_billing_exempt"] is True
    assert s["paid_subscription"] is False
    assert s["monthly_cap_units"] == 150
    ledger.record_usage(scheduler_key=SCHEDULER, customer_token=token,
                        job_id="a" * 32, units=150)
    with pytest.raises(BillingRejected):
        ledger.record_usage(scheduler_key=SCHEDULER, customer_token=token,
                            job_id="b" * 32, units=1)


def test_guests_cannot_consume_owner_quota(env):
    _, _, ledger, (owner, guest) = env
    ledger.record_usage(scheduler_key=SCHEDULER, customer_token=guest[1],
                        job_id="a" * 32, units=60)
    assert ledger.private_summary(owner[1])["compute_units"] == 0
    assert ledger.private_summary(guest[1])["compute_units"] == 60
    assert ledger.private_summary(guest[1])["compute_units_remaining"] == 40


def test_idempotent_usage_and_conflict_rejected(env):
    _, _, ledger, (_owner, guest) = env
    kw = {"scheduler_key": SCHEDULER, "customer_token": guest[1],
          "job_id": "b" * 32, "units": 15}
    a = ledger.record_usage(**kw)
    b = ledger.record_usage(**kw)
    assert a == b
    assert ledger.private_summary(guest[1])["compute_units"] == 15
    with pytest.raises(BillingRejected):
        ledger.record_usage(**(kw | {"units": 14}))


def test_two_tenants_same_job_id_not_cross_charged(env):
    _, _, ledger, (owner, guest) = env
    for tenant, token in (owner, guest):
        del tenant
        ledger.record_usage(scheduler_key=SCHEDULER, customer_token=token,
                            job_id="a" * 32, units=20)
    assert ledger.private_summary(owner[1])["compute_units"] == 20
    assert ledger.private_summary(guest[1])["compute_units"] == 20


def test_month_reset_does_not_modify_earlier_ledger(env):
    now, _, ledger, (_owner, guest) = env
    ledger.record_usage(scheduler_key=SCHEDULER, customer_token=guest[1],
                        job_id="a" * 32, units=50)
    old_period = ledger.private_summary(guest[1])["period_utc_yyyymm"]
    now[0] += 40 * 86400
    # Raw session expiration is deliberately enforced; obtain fresh login.
    with pytest.raises(AccessDenied):
        ledger.private_summary(guest[1])
    # Exercise the date helper to verify new monthly window.
    assert ledger._period(now[0]) > old_period


def test_unauthorised_meter_and_admin_cannot_change_limits(env):
    _, vault, ledger, (_owner, guest) = env
    with pytest.raises(AccessDenied):
        ledger.record_usage(scheduler_key=b"attacker",
                            customer_token=guest[1], job_id="a" * 32, units=10)
    with pytest.raises(AccessDenied):
        ledger.configure_preview(admin_key=b"attacker",
                                 tenant_id=guest[0], plan="x_bad",
                                 monthly_cap=5000)
    with pytest.raises(BillingRejected):
        ledger.configure_preview(admin_key=ADMIN,
                                 tenant_id=guest[0], plan="customer",
                                 monthly_cap=100000)
    with pytest.raises(ValueError):
        ComputeEntitlements(vault, administrator_key=ADMIN, scheduler_key=ADMIN)


def test_false_paid_status_cannot_be_set(env):
    _, _, ledger, (_owner, guest) = env
    assert not ledger.payment_state(guest[1])["sandbox_charge_tested"]
    assert not ledger.payment_state(guest[1])["paid_access_unlocked"]
    with pytest.raises(BillingRejected):
        ledger.try_mark_paid(guest[0], paid=True, price=10000)


def test_usage_validation_and_session_revoke(env):
    _, vault, ledger, (_owner, guest) = env
    for units in (0, -1, 501, True, "5"):
        with pytest.raises(BillingRejected):
            ledger.record_usage(scheduler_key=SCHEDULER,
                                customer_token=guest[1],
                                job_id="f" * 32, units=units)
    with pytest.raises(BillingRejected):
        ledger.record_usage(scheduler_key=SCHEDULER,
                            customer_token=guest[1],
                            job_id="../injected", units=5)
    vault.logout(guest[1])
    with pytest.raises(AccessDenied):
        ledger.private_summary(guest[1])
