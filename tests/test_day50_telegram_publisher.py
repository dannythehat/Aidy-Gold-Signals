from __future__ import annotations

import runpy
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from aidy.telegram_publisher import (
    DEFAULT_GROUP_NAME,
    SimulatedTelegramTransport,
    TelegramBotTransport,
    TelegramPublicationError,
    build_publication_envelope,
    day50_manifest,
    format_provider_message,
    publish_envelope,
    verify_publication_envelope,
    verify_publication_receipt,
)

_DAY34 = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "scripts" / "day34_decision_ledger_acceptance.py")
)
_base_decision = _DAY34["_base_decision"]
_cycle = _DAY34["_cycle"]

NOW = datetime(2026, 9, 1, 14, 15, tzinfo=UTC)
CHAT_ID = "-1001234567890"
OTHER_CHAT_ID = "-1001234567891"


def _admitted_record():
    return _cycle(NOW, 0, "decision_admitted")


def _manage_decision() -> dict:
    value = _base_decision("manage_trade", NOW)
    value.update(
        {
            "target_decision_id": "aidy_dec_12345678",
            "management_instruction": "move_stop_and_targets",
            "new_stop_loss": 2492.0,
            "new_targets": [2510.0, 2520.0],
        }
    )
    return value


def _close_decision() -> dict:
    value = _base_decision("close_trade", NOW)
    value.update(
        {
            "target_decision_id": "aidy_dec_12345678",
            "close_scope": "full",
        }
    )
    return value


def test_admitted_new_trade_builds_verified_ai_signal_envelope() -> None:
    record = _admitted_record()
    envelope = build_publication_envelope(ex_ante_record=record, chat_id=CHAT_ID)
    assert verify_publication_envelope(envelope)
    assert envelope["group_name"] == "AI Signal"
    assert envelope["decision_id"] == record["decision_id"]
    assert envelope["action"] == "new_trade"
    assert "AI Signal — NEW TRADE" in envelope["message"]
    assert "XAUUSD BUY" in envelope["message"]
    assert record["decision_id"] in envelope["message"]
    assert "confidence" not in envelope["message"].casefold()
    assert "thesis" not in envelope["message"].casefold()


@pytest.mark.parametrize("disposition", ["pre_model_blocked", "model_failed", "post_model_blocked", "no_trade"])
def test_non_admitted_cycles_never_publish(disposition: str) -> None:
    record = _cycle(NOW, 1, disposition)
    with pytest.raises(TelegramPublicationError):
        build_publication_envelope(ex_ante_record=record, chat_id=CHAT_ID)


@pytest.mark.parametrize("source_state", ["replay", "shadow", "historical", "failed"])
def test_replay_shadow_and_non_live_states_never_publish(source_state: str) -> None:
    with pytest.raises(TelegramPublicationError, match="Replay, shadow"):
        build_publication_envelope(
            ex_ante_record=_admitted_record(),
            chat_id=CHAT_ID,
            source_state=source_state,
        )


def test_manage_message_is_deterministic_provider_instruction() -> None:
    message = format_provider_message(_manage_decision(), decision_id="aidy_dec_update123")
    expected = (
        "🔄 AI Signal — TRADE UPDATE\n"
        "XAUUSD\n"
        "Trade ID: aidy_dec_12345678\n"
        "Move SL to 2492\n"
        "New TP1 2510\n"
        "New TP2 2520\n"
        "Update ID: aidy_dec_update123"
    )
    assert message == expected


def test_close_message_is_deterministic_provider_instruction() -> None:
    message = format_provider_message(_close_decision(), decision_id="aidy_dec_close123")
    expected = (
        "✅ AI Signal — CLOSE TRADE\n"
        "XAUUSD — CLOSE FULL TRADE\n"
        "Trade ID: aidy_dec_12345678\n"
        "Update ID: aidy_dec_close123"
    )
    assert message == expected


def test_simulated_send_and_retry_are_idempotent() -> None:
    envelope = build_publication_envelope(ex_ante_record=_admitted_record(), chat_id=CHAT_ID)
    transport = SimulatedTelegramTransport(sent_at_utc=NOW)
    first = publish_envelope(envelope, transport=transport)
    second = publish_envelope(envelope, transport=transport, existing_receipt=first)
    assert first == second
    assert len(transport.calls) == 1
    assert verify_publication_receipt(first)
    assert first["publication_id"] == envelope["publication_id"]


def test_receipt_from_other_publication_fails_closed() -> None:
    record = _admitted_record()
    first_envelope = build_publication_envelope(ex_ante_record=record, chat_id=CHAT_ID)
    second_envelope = build_publication_envelope(ex_ante_record=record, chat_id=OTHER_CHAT_ID)
    transport = SimulatedTelegramTransport(sent_at_utc=NOW)
    second_receipt = publish_envelope(second_envelope, transport=transport)
    with pytest.raises(TelegramPublicationError, match="another publication"):
        publish_envelope(
            first_envelope,
            transport=transport,
            existing_receipt=second_receipt,
        )
    assert len(transport.calls) == 1


def test_real_transport_redacts_token_on_http_failure() -> None:
    token = "123456789:VERY_SECRET_TELEGRAM_TOKEN"

    def handler(request: httpx.Request) -> httpx.Response:
        assert token in str(request.url)
        return httpx.Response(500, json={"ok": False})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    transport = TelegramBotTransport(bot_token=token, client=client)
    assert token not in repr(transport)
    with pytest.raises(TelegramPublicationError) as captured:
        transport.send_message(chat_id=CHAT_ID, text="safe test")
    assert token not in str(captured.value)


def test_manifest_locks_private_group_and_boundaries() -> None:
    manifest = day50_manifest()
    assert manifest["configured_private_group_name"] == DEFAULT_GROUP_NAME == "AI Signal"
    assert manifest["eligible_actions"] == ["close_trade", "manage_trade", "new_trade"]
    assert manifest["no_trade_publication_allowed"] is False
    assert manifest["blocked_publication_allowed"] is False
    assert manifest["failed_publication_allowed"] is False
    assert manifest["replay_publication_allowed"] is False
    assert manifest["shadow_publication_allowed"] is False
    assert manifest["simulated_transport_available"] is True
    assert manifest["broker_dependency_allowed"] is False
    assert manifest["super_signals_dependency_allowed"] is False
    assert manifest["formal_forward_evidence_created"] is False
