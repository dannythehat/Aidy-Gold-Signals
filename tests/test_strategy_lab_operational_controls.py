"""Day39 smoke assertions for isolated launch readiness contract."""

from aidy.strategy_lab_operational_controls import REQUIRED_EXTERNAL_GATES


def test_external_checks_remain_required():
    assert "real_payment_sandbox" in REQUIRED_EXTERNAL_GATES
    assert "consenting_user_pilot" in REQUIRED_EXTERNAL_GATES
    assert len(REQUIRED_EXTERNAL_GATES) == 9
