"""Day38 B11: internal capped compute entitlements, usage accounting and audit.

This module is NOT payment processing. Sandbox fixtures never activate paid
status, create an invoice or simulate a provider's financial confirmation.
Real payment proof requires an externally connected test-mode provider.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets

from aidy.strategy_lab_tenant_vault import AccessDenied, TenantVault, _canonical, _open_db

PLAN = re.compile(r"^[a-z][a-z0-9_-]{2,39}$")
HEX32 = re.compile(r"^[0-9a-f]{32}$")
MAX_CAP = 50_000
MAX_JOB_UNITS = 500
SCHEMA = "aidy.b11.compute_entitlement.v1"


class BillingRejected(ValueError):
    """Fail closed on inaccurate/unauthorised metering and entitlement state."""


class ComputeEntitlements:
    def __init__(self, vault: TenantVault, *, administrator_key: bytes,
                 scheduler_key: bytes):
        if not all(isinstance(x, bytes) and len(x) >= 32 for x in (
                administrator_key, scheduler_key)):
            raise ValueError("Two independent 32-byte service keys required")
        if (administrator_key == scheduler_key
                or administrator_key in (vault._provision, vault._pepper)
                or scheduler_key in (vault._provision, vault._pepper)):
            raise ValueError("Independent service keys required")
        self._vault = vault
        self._admin = administrator_key
        self._scheduler = scheduler_key
        with _open_db(vault._path) as con:
            con.executescript("""
            CREATE TABLE IF NOT EXISTS b11_entitlements(
                tenant_id TEXT PRIMARY KEY REFERENCES tenants(id),
                plan TEXT NOT NULL, monthly_cap INTEGER NOT NULL,
                state TEXT NOT NULL, owner_billing_exempt INTEGER NOT NULL,
                created INTEGER NOT NULL, updated INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS b11_usage(
                tenant_id TEXT NOT NULL REFERENCES tenants(id),
                period INTEGER NOT NULL,
                job_id TEXT NOT NULL, units INTEGER NOT NULL,
                sha256 TEXT NOT NULL, created INTEGER NOT NULL,
                PRIMARY KEY(tenant_id, period, job_id));
            CREATE TABLE IF NOT EXISTS b11_audit(
                id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL,
                kind TEXT NOT NULL, event_hash TEXT NOT NULL,
                created INTEGER NOT NULL);
            """)
        # State is PREVIEW_INTERNAL only. No paid status may be set by this module.

    @staticmethod
    def _secret(provided: bytes, expected: bytes) -> None:
        if not isinstance(provided, bytes) or not hmac.compare_digest(provided, expected):
            raise AccessDenied("Access denied")

    @staticmethod
    def _period(now: int) -> int:
        # UTC calendar month prevents client-local timezone changes in billing.
        from datetime import UTC, datetime

        date = datetime.fromtimestamp(now, tz=UTC)
        return date.year * 100 + date.month

    def configure_preview(self, *, admin_key: bytes, tenant_id: str, plan: str,
                          monthly_cap: int, owner_billing_exempt: bool = False) -> None:
        """Trusted prelaunch plans: always PREVIEW_INTERNAL, never paid/sandbox PASS."""
        self._secret(admin_key, self._admin)
        if (not isinstance(tenant_id, str) or not HEX32.fullmatch(tenant_id)
                or not isinstance(plan, str) or not PLAN.fullmatch(plan)
                or type(monthly_cap) is not int or not 1 <= monthly_cap <= MAX_CAP
                or type(owner_billing_exempt) is not bool):
            raise BillingRejected("Invalid internal entitlement")
        with _open_db(self._vault._path) as con:
            con.execute("BEGIN IMMEDIATE")
            if not con.execute("SELECT 1 FROM tenants WHERE id=?", (tenant_id,)).fetchone():
                raise BillingRejected("Unknown private tenant")
            now = int(self._vault._clock())
            con.execute(
                "INSERT INTO b11_entitlements VALUES(?,?,?,?,?,?,?) "
                "ON CONFLICT(tenant_id) DO UPDATE SET "
                "plan=excluded.plan, monthly_cap=excluded.monthly_cap, "
                "owner_billing_exempt=excluded.owner_billing_exempt, "
                "state='PREVIEW_INTERNAL', updated=excluded.updated",
                (tenant_id, plan, monthly_cap, "PREVIEW_INTERNAL",
                 int(owner_billing_exempt), now, now),
            )
            action = _canonical({
                "tenant": tenant_id, "plan": plan, "cap": monthly_cap,
                "billing_exempt": owner_billing_exempt, "at": now,
            })
            con.execute(
                "INSERT INTO b11_audit VALUES(?,?,?,?,?)",
                (secrets.token_hex(16), tenant_id, "PRIVATE_CONFIG",
                 hashlib.sha256(action).hexdigest(), now),
            )
            con.commit()

    def private_summary(self, token: str) -> dict:
        with _open_db(self._vault._path) as con:
            _, tenant = self._vault._principal(con, token)
            ent = con.execute(
                "SELECT plan,monthly_cap,state,owner_billing_exempt FROM "
                "b11_entitlements WHERE tenant_id=?", (tenant,),
            ).fetchone()
            if not ent:
                return {"status": "NO_ENTITLEMENT", "paid_subscription": False,
                        "compute_units": 0, "owner_billing_exempt": False}
            period = self._period(int(self._vault._clock()))
            used = con.execute(
                "SELECT COALESCE(SUM(units),0) FROM b11_usage "
                "WHERE tenant_id=? AND period=?", (tenant, period),
            ).fetchone()[0]
        return {
            "status": ent["state"], "plan": ent["plan"],
            "period_utc_yyyymm": period,
            "monthly_cap_units": ent["monthly_cap"],
            "compute_units": used,
            "compute_units_remaining": max(0, ent["monthly_cap"] - used),
            "owner_billing_exempt": bool(ent["owner_billing_exempt"]),
            "paid_subscription": False, "sandbox_payment_confirmed": False,
            "subscription_price": None, "currency_charged": None,
        }

    def record_usage(self, *, scheduler_key: bytes, customer_token: str,
                     job_id: str, units: int) -> str:
        """Atomic bounded accounting; never bills money or executes a strategy."""
        self._secret(scheduler_key, self._scheduler)
        if (not isinstance(job_id, str) or not HEX32.fullmatch(job_id)
                or type(units) is not int or not 1 <= units <= MAX_JOB_UNITS):
            raise BillingRejected("Invalid metering record")
        with _open_db(self._vault._path) as con:
            con.execute("BEGIN IMMEDIATE")
            _, tenant = self._vault._principal(con, customer_token)
            row = con.execute(
                "SELECT monthly_cap,state FROM b11_entitlements WHERE tenant_id=?",
                (tenant,),
            ).fetchone()
            if not row or row["state"] != "PREVIEW_INTERNAL":
                raise BillingRejected("Entitlement not active")
            period = self._period(int(self._vault._clock()))
            event = hashlib.sha256(_canonical({
                "schema": SCHEMA, "tenant": tenant,
                "job_id": job_id, "period": period, "units": units,
            })).hexdigest()
            prior = con.execute(
                "SELECT sha256 FROM b11_usage "
                "WHERE tenant_id=? AND period=? AND job_id=?",
                (tenant, period, job_id),
            ).fetchone()
            if prior:
                if not hmac.compare_digest(prior["sha256"], event):
                    raise BillingRejected("Conflicting job usage replay")
                return event
            used = con.execute(
                "SELECT COALESCE(SUM(units),0) FROM b11_usage "
                "WHERE tenant_id=? AND period=?", (tenant, period),
            ).fetchone()[0]
            if used + units > row["monthly_cap"]:
                raise BillingRejected("Monthly compute cap exceeded")
            con.execute("INSERT INTO b11_usage VALUES(?,?,?,?,?,?)",
                        (tenant, period, job_id, units, event,
                         int(self._vault._clock())))
            con.commit()
        return event

    def payment_state(self, token: str) -> dict:
        """Honest placeholder. Not possible to claim paid without real provider."""
        state = self.private_summary(token)
        return {
            "tenant_preview_status": state["status"],
            "provider_connected": False,
            "sandbox_charge_tested": False,
            "customer_payment_created": False,
            "paid_access_unlocked": False,
        }

    def try_mark_paid(self, *_args: object, **_kwargs: object) -> None:
        """Customer/admin cannot invent a payment without provider integration."""
        raise BillingRejected("Real provider receipt and sandbox acceptance unavailable")
