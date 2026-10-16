"""Day38 fixture-only signed webhook tests. Nothing contacts a real provider."""
import hashlib
import hmac
import json
import sqlite3

import pytest

from aidy.strategy_lab_sandbox_payment_intake import (
    SandboxPaymentIntake,
    WebhookRejected,
)

SECRET = b"whsec_fake_test_signature_fixture_only_123456789"
OPERATOR = b"Y" * 32
T1 = "a" * 32
T2 = "b" * 32
S1 = "cs_test_123456789Abc"
S2 = "cs_test_987654321Abc"


def encode(*, tenant=T1, session=S1, event="evt_abc123456789", **changes):
    payload = {
        "id": event, "object": "event", "type": "checkout.session.completed",
        "livemode": False,
        "data": {"object": {
            "id": session, "object": "checkout.session", "livemode": False,
            "metadata": {"tenant_id": tenant}, "mode": "subscription",
            "payment_status": "paid",
        }},
    }
    for path, value in changes.items():
        if path.startswith("session_"):
            payload["data"]["object"][path[8:]] = value
        else:
            payload[path] = value
    return json.dumps(payload, sort_keys=True).encode()


def sign(raw, timestamp=10_000):
    digest = hmac.new(
        SECRET, str(timestamp).encode() + b"." + raw, hashlib.sha256
    ).hexdigest()
    return f"t={timestamp},v1={digest}"


@pytest.fixture
def env(tmp_path):
    path = tmp_path / "tenants.sqlite"
    with sqlite3.connect(path) as con:
        con.execute("CREATE TABLE tenants (id TEXT PRIMARY KEY)")
        con.executemany("INSERT INTO tenants VALUES(?)", [(T1,), (T2,)])
    intake = SandboxPaymentIntake(
        path, webhook_secret=SECRET, operator_key=OPERATOR,
        enabled=True, clock=lambda: 10_000,
    )
    intake.register_expected_session(
        operator_key=OPERATOR, tenant_id=T1, session_id=S1
    )
    return intake, path


def test_signed_test_event_is_recorded_but_never_unlocks_money(env):
    intake, path = env
    raw = encode()
    a = intake.record_signed_test_event(raw_body=raw, signature_header=sign(raw))
    b = intake.record_signed_test_event(raw_body=raw, signature_header=sign(raw))
    assert a == b
    assert a["status"] == "SIGNED_TEST_EVENT_UNRECONCILED"
    assert a["paid_access_unlocked"] is False
    assert a["actual_provider_delivery_verified"] is False
    assert a["original_day38_passed"] is False
    with sqlite3.connect(path) as con:
        assert con.execute(
            "SELECT count(*) FROM b11_test_webhook_receipts"
        ).fetchone()[0] == 1


@pytest.mark.parametrize("raw,header", [
    (encode(), "t=10000,v1=" + "0" * 64),
    (encode(), "t=10000,v0=" + "0" * 64),
    (encode(), "t=10000,v1=nope"),
    (encode(), "t=10000,t=10000,v1=" + "0" * 64),
    (encode(), ""),
    (encode(), "t=oops,v1=" + "0" * 64),
])
def test_rejects_forged_signatures(env, raw, header):
    with pytest.raises(WebhookRejected):
        env[0].record_signed_test_event(raw_body=raw, signature_header=header)


@pytest.mark.parametrize("stamp", [9_699, 10_301, 9_000, 11_000])
def test_stale_future_replayed_timestamps_rejected(env, stamp):
    raw = encode()
    with pytest.raises(WebhookRejected):
        env[0].record_signed_test_event(
            raw_body=raw, signature_header=sign(raw, stamp)
        )


@pytest.mark.parametrize("kw", [
    {"livemode": True},
    {"session_livemode": True},
    {"type": "customer.subscription.created"},
    {"session_payment_status": "unpaid"},
    {"session_mode": "setup"},
    {"session_object": "payment_intent"},
])
def test_rejects_even_signed_wrong_event_shapes(env, kw):
    raw = encode(**kw)
    with pytest.raises(WebhookRejected):
        env[0].record_signed_test_event(raw_body=raw, signature_header=sign(raw))


def test_cross_tenant_sessions_and_unregistered_events_are_denied(env):
    intake, path = env
    raw = encode(tenant=T2)
    with pytest.raises(WebhookRejected):
        intake.record_signed_test_event(raw_body=raw, signature_header=sign(raw))
    with pytest.raises(WebhookRejected):
        intake.register_expected_session(
            operator_key=OPERATOR, tenant_id=T2, session_id=S1
        )
    raw = encode(session=S2)
    with pytest.raises(WebhookRejected):
        intake.record_signed_test_event(raw_body=raw, signature_header=sign(raw))
    with sqlite3.connect(path) as con:
        assert con.execute(
            "SELECT count(*) FROM b11_test_webhook_receipts"
        ).fetchone()[0] == 0


def test_event_id_conflicts_and_second_completion_rejected(env):
    intake, _ = env
    raw = encode()
    intake.record_signed_test_event(raw_body=raw, signature_header=sign(raw))
    modified = encode(other="text")
    with pytest.raises(WebhookRejected):
        intake.record_signed_test_event(
            raw_body=modified, signature_header=sign(modified)
        )
    different = encode(event="evt_different001")
    with pytest.raises(WebhookRejected):
        intake.record_signed_test_event(
            raw_body=different, signature_header=sign(different)
        )


def test_intake_disabled_by_default_and_requires_operator(env):
    _intake, path = env
    disabled = SandboxPaymentIntake(
        path, webhook_secret=SECRET, operator_key=OPERATOR
    )
    raw = encode()
    with pytest.raises(WebhookRejected):
        disabled.record_signed_test_event(
            raw_body=raw, signature_header=sign(raw)
        )
    with pytest.raises(WebhookRejected):
        disabled.register_expected_session(
            operator_key=OPERATOR, tenant_id=T1, session_id=S2
        )
    with pytest.raises(WebhookRejected):
        env[0].register_expected_session(
            operator_key=b"Z" * 32, tenant_id=T1, session_id=S2
        )


def test_rejects_live_checkout_and_invalid_session_registration(env):
    intake, path = env
    for session in ("cs_live_123456789", "cs_test_no", "../../etc/passwd"):
        with pytest.raises(WebhookRejected):
            intake.register_expected_session(
                operator_key=OPERATOR, tenant_id=T1, session_id=session
            )
    with pytest.raises(WebhookRejected):
        intake.register_expected_session(
            operator_key=OPERATOR, tenant_id="f" * 32, session_id=S2
        )
    with pytest.raises(ValueError):
        SandboxPaymentIntake(
            path, webhook_secret=OPERATOR, operator_key=OPERATOR
        )


def test_raw_bytes_preserved_reject_duplicate_json_and_size_limits(env):
    intake, _ = env
    raw = encode()
    tampered = raw + b" "
    with pytest.raises(WebhookRejected):
        intake.record_signed_test_event(
            raw_body=tampered, signature_header=sign(raw)
        )
    duplicate = raw.replace(
        b'"object": "event"',
        b'"object": "event", "object": "event"',
    )
    with pytest.raises(WebhookRejected):
        intake.record_signed_test_event(
            raw_body=duplicate, signature_header=sign(duplicate)
        )
    for bad in (b"", b"x" * (129 * 1024), "not bytes"):
        with pytest.raises(WebhookRejected):
            intake.record_signed_test_event(
                raw_body=bad, signature_header="invalid"
            )
