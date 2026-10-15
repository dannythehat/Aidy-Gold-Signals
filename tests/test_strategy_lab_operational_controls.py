"""Day39 smoke assertions for isolated launch readiness contract."""

from aidy.strategy_lab_operational_controls import REQUIRED_EXTERNAL_GATES


def test_external_checks_remain_required():
    assert "real_payment_sandbox" in REQUIRED_EXTERNAL_GATES
    assert "consenting_user_pilot" in REQUIRED_EXTERNAL_GATES
    assert len(REQUIRED_EXTERNAL_GATES) == 9


import pytest

from aidy.strategy_lab_customer_intake import RULE_FIELDS, prepare_intake
from aidy.strategy_lab_operational_controls import OperationalControls, OperationsRejected
from aidy.strategy_lab_tenant_vault import AccessDenied, TenantVault


def test_actual_local_restore_and_launch_interlock(tmp_path):
    vault = TenantVault(
        tmp_path / "data" / "source.sqlite",
        encryption_key=b"K" * 32, token_pepper=b"P" * 32,
        provision_key=b"U" * 32, clock=lambda: 1_500_000,
    )
    vault.provision(
        admin_key=b"U" * 32, username="demo_user",
        password="example-long-string-for-unit-tests",
    )
    token = vault.login("demo_user", "example-long-string-for-unit-tests")
    fields = dict.fromkeys(RULE_FIELDS, "Synthetic test rule")
    fields.update(market="XAUUSD", timeframe="H1")
    original = prepare_intake(
        mode="paste", title="Synthetic demo",
        value="Private synthetic source", rules=fields,
    )
    identifier = vault.submit_draft(token, original)
    ops = OperationalControls(vault, operations_key=b"O" * 32)
    assert ops.internal_state(operator_key=b"O" * 32)["private_mode"] == "SAFE_HALT"
    with pytest.raises(OperationsRejected):
        ops.try_enable_public_launch()
    with pytest.raises(AccessDenied):
        ops.internal_state(operator_key=b"invalid")
    event = ops.incident(
        operator_key=b"O" * 32, level="WARNING", source_tag="local_demo",
        summary="Synthetic readiness test incident",
    )
    assert len(event) == 32
    destination = tmp_path / "backup" / "copy.sqlite"
    details = ops.local_sqlite_backup(operator_key=b"O" * 32, backup_path=destination)
    assert details["quick_check"] == "ok" and details["draft_count"] == 1
    assert details["remote_backup_restored"] is False
    restored = TenantVault(
        destination, encryption_key=b"K" * 32,
        token_pepper=b"P" * 32, provision_key=b"U" * 32,
        clock=lambda: 1_500_000,
    )
    assert restored.read_draft(token, identifier) == original
    assert "data_source_commercial_rights" in ops.launch_blockers(
        operator_key=b"O" * 32,
    )["documented_external_gates_missing"]
