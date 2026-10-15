"""Day40 no-go gate adversarial tests."""
import pytest

from aidy.strategy_lab_launch_gate import GATES, evaluate_launch


def test_existing_real_status_is_strict_no_go():
    r = evaluate_launch(dict.fromkeys(GATES, False))
    assert r["status"] == "NO_GO"
    assert len(r["missing_gates"]) == len(GATES)
    assert r["automated_trade_or_public_launch_authority"] is False


def test_empty_or_partial_gate_does_not_pass():
    for packet in ({}, {"day38_actual_payment_sandbox": True},
                   dict.fromkeys(GATES, "approved")):
        with pytest.raises(ValueError):
            evaluate_launch(packet)


def test_every_missing_gate_blocks():
    for gate in GATES:
        vals = dict.fromkeys(GATES, True)
        vals[gate] = False
        outcome = evaluate_launch(vals)
        assert outcome["status"] == "NO_GO"
        assert outcome["missing_gates"] == [gate]


def test_full_true_is_hypothetical_not_deployment_authorisation():
    r = evaluate_launch(dict.fromkeys(GATES, True))
    assert r["status"] == "NO_GO"
    assert r["verified_external_evidence_count"] == 0
    assert set(r["unverified_assertions"]) == set(GATES)
    assert r["original_40_day_program_complete"] is False
    assert r["automated_trade_or_public_launch_authority"] is False
    assert r["owner_explicit_deployment_approval_separate"] is True


def test_no_single_unverified_true_assertion_can_trigger_launch():
    for gate in GATES:
        claims = dict.fromkeys(GATES, False)
        claims[gate] = True
        decision = evaluate_launch(claims)
        assert decision["status"] == "NO_GO"
        assert decision["unverified_assertions"] == [gate]
        assert decision["trusted_external_receipt_verifier_implemented"] is False
