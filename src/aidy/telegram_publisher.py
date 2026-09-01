from __future__ import annotations

import copy
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, Protocol

import httpx

from aidy.decision_ledger import verify_ex_ante_record
from aidy.master_trader_contract_v2 import validate_master_trader_decision_versioned

TELEGRAM_PUBLISHER_VERSION = "aidy_private_telegram_publisher_v1"
PUBLICATION_ENVELOPE_VERSION = "aidy_telegram_publication_envelope_v1"
PUBLICATION_RECEIPT_VERSION = "aidy_telegram_publication_receipt_v1"
DAY50_MANIFEST_VERSION = "aidy_day50_private_telegram_publisher_manifest_v1"
DEFAULT_GROUP_NAME = "AI Signal"
_ALLOWED_ACTIONS = frozenset({"new_trade", "manage_trade", "close_trade"})
_ALLOWED_SOURCE_STATE = "live_admitted"
_SAFE_CHAT_ID = re.compile(r"^-?[0-9]{5,32}$")
_SECRET_MARKERS = ("bearer ", "sk-", "-----begin private key-----")
_SECRET_KEYS = frozenset(
    {
        "api_key",
        "authorization",
        "bot_token",
        "password",
        "private_key",
        "secret",
        "telegram_bot_token",
        "token",
    }
)


class TelegramPublicationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value: object) -> str:
    return sha256(canonical_json(value).encode()).hexdigest()


def _utc(value: Any, *, name: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip())
        except ValueError as exc:
            raise TelegramPublicationError("telegram_timestamp_invalid", f"{name} is invalid.") from exc
    else:
        raise TelegramPublicationError("telegram_timestamp_invalid", f"{name} is required.")
    if parsed.tzinfo is None:
        raise TelegramPublicationError("telegram_timestamp_invalid", f"{name} must be timezone-aware.")
    return parsed.astimezone(UTC)


def _assert_safe(value: Any, *, path: str = "publication") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).strip().lower()
            if normalized in _SECRET_KEYS:
                raise TelegramPublicationError(
                    "telegram_secret_forbidden", f"Secret-bearing field is forbidden at {path}.{key}."
                )
            _assert_safe(item, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _assert_safe(item, path=f"{path}[{index}]")
    elif isinstance(value, str):
        lowered = value.casefold()
        if any(marker in lowered for marker in _SECRET_MARKERS):
            raise TelegramPublicationError(
                "telegram_secret_forbidden", f"Secret-like content is forbidden at {path}."
            )


def _group_name(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TelegramPublicationError("telegram_group_invalid", "Telegram group name is required.")
    normalized = " ".join(value.strip().split())
    if len(normalized) > 80:
        raise TelegramPublicationError("telegram_group_invalid", "Telegram group name is too long.")
    _assert_safe(normalized, path="group_name")
    return normalized


def _chat_id(value: Any) -> str:
    normalized = str(value).strip()
    if not _SAFE_CHAT_ID.fullmatch(normalized):
        raise TelegramPublicationError("telegram_chat_id_invalid", "Telegram chat_id is invalid.")
    return normalized


def _price(value: Any) -> str:
    text = str(value)
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def format_provider_message(decision: Mapping[str, Any], *, decision_id: str) -> str:
    normalized = validate_master_trader_decision_versioned(decision)
    action = normalized["action"]
    if action not in _ALLOWED_ACTIONS:
        raise TelegramPublicationError(
            "telegram_action_ineligible", "Only actionable provider instructions can be formatted."
        )
    if action == "new_trade":
        direction = "BUY" if normalized["direction"] == "long" else "SELL"
        lines = [
            "🟡 AI Signal — NEW TRADE",
            f"XAUUSD {direction} @ {_price(normalized['market_reference_price'])}",
            f"SL {_price(normalized['stop_loss'])}",
        ]
        lines.extend(
            f"TP{index} {_price(target)}" for index, target in enumerate(normalized["targets"], start=1)
        )
        lines.extend([f"Trade ID: {decision_id}", "Trade accordingly and manage risk responsibly."])
        return "\n".join(lines)

    target_id = str(normalized["target_decision_id"])
    if action == "close_trade":
        return "\n".join(
            [
                "✅ AI Signal — CLOSE TRADE",
                "XAUUSD — CLOSE FULL TRADE",
                f"Trade ID: {target_id}",
                f"Update ID: {decision_id}",
            ]
        )

    instruction = normalized["management_instruction"]
    lines = ["🔄 AI Signal — TRADE UPDATE", "XAUUSD", f"Trade ID: {target_id}"]
    if instruction in {"move_stop", "move_stop_and_targets"}:
        lines.append(f"Move SL to {_price(normalized['new_stop_loss'])}")
    if instruction in {"replace_targets", "move_stop_and_targets"}:
        lines.extend(
            f"New TP{index} {_price(target)}"
            for index, target in enumerate(normalized["new_targets"], start=1)
        )
    lines.append(f"Update ID: {decision_id}")
    return "\n".join(lines)


def build_publication_envelope(
    *,
    ex_ante_record: Mapping[str, Any],
    group_name: str = DEFAULT_GROUP_NAME,
    chat_id: str,
    source_state: str = _ALLOWED_SOURCE_STATE,
) -> dict[str, Any]:
    if not verify_ex_ante_record(ex_ante_record):
        raise TelegramPublicationError("telegram_ledger_invalid", "A verified ex-ante ledger record is required.")
    if source_state != _ALLOWED_SOURCE_STATE:
        raise TelegramPublicationError(
            "telegram_source_ineligible", "Replay, shadow and non-live source states cannot publish."
        )
    if ex_ante_record.get("cycle_disposition") != "decision_admitted":
        raise TelegramPublicationError(
            "telegram_disposition_ineligible", "Only decision_admitted ledger records can publish."
        )
    gateway = ex_ante_record.get("gateway_snapshot")
    post = ex_ante_record.get("post_model_receipt")
    decision = ex_ante_record.get("decision")
    if not isinstance(gateway, Mapping) or not isinstance(post, Mapping) or not isinstance(decision, Mapping):
        raise TelegramPublicationError("telegram_admission_invalid", "Publication admission evidence is incomplete.")
    if gateway.get("status") != "accepted" or gateway.get("publication_allowed") is not True:
        raise TelegramPublicationError("telegram_admission_invalid", "Gateway did not admit publication.")
    if post.get("status") != "passed" or post.get("decision_admitted") is not True:
        raise TelegramPublicationError("telegram_admission_invalid", "Post-model gate did not admit the decision.")
    normalized = validate_master_trader_decision_versioned(decision)
    if normalized["action"] not in _ALLOWED_ACTIONS:
        raise TelegramPublicationError(
            "telegram_action_ineligible", "no_trade and non-action states never publish."
        )
    decision_id = str(ex_ante_record["decision_id"])
    group = _group_name(group_name)
    destination = _chat_id(chat_id)
    message = format_provider_message(normalized, decision_id=decision_id)
    envelope: dict[str, Any] = {
        "envelope_version": PUBLICATION_ENVELOPE_VERSION,
        "publisher_version": TELEGRAM_PUBLISHER_VERSION,
        "publication_id": "",
        "decision_id": decision_id,
        "ex_ante_digest": ex_ante_record["ex_ante_digest"],
        "model_decision_digest": ex_ante_record["model_decision_digest"],
        "action": normalized["action"],
        "source_state": source_state,
        "group_name": group,
        "chat_id": destination,
        "message": message,
        "message_digest": digest(message),
    }
    identity = {
        "publisher_version": TELEGRAM_PUBLISHER_VERSION,
        "decision_id": decision_id,
        "ex_ante_digest": ex_ante_record["ex_ante_digest"],
        "chat_id": destination,
        "message_digest": envelope["message_digest"],
    }
    envelope["publication_id"] = f"aidy_pub_{digest(identity)[:32]}"
    _assert_safe(envelope)
    envelope["envelope_digest"] = digest(envelope)
    return envelope


def verify_publication_envelope(envelope: Mapping[str, Any]) -> bool:
    if not isinstance(envelope, Mapping):
        return False
    body = copy.deepcopy(dict(envelope))
    supplied = str(body.pop("envelope_digest", ""))
    try:
        _assert_safe(body)
        if body.get("envelope_version") != PUBLICATION_ENVELOPE_VERSION:
            return False
        if body.get("publisher_version") != TELEGRAM_PUBLISHER_VERSION:
            return False
        if body.get("source_state") != _ALLOWED_SOURCE_STATE:
            return False
        if body.get("action") not in _ALLOWED_ACTIONS:
            return False
        if body.get("message_digest") != digest(body.get("message")):
            return False
        _group_name(body.get("group_name"))
        _chat_id(body.get("chat_id"))
    except (TypeError, ValueError, TelegramPublicationError):
        return False
    return bool(supplied) and supplied == digest(body)


class TelegramTransport(Protocol):
    def send_message(self, *, chat_id: str, text: str) -> Mapping[str, Any]: ...


@dataclass
class SimulatedTelegramTransport:
    sent_at_utc: datetime
    next_message_id: int = 1

    def __post_init__(self) -> None:
        self.sent_at_utc = _utc(self.sent_at_utc, name="sent_at_utc")
        self.calls: list[dict[str, Any]] = []

    def send_message(self, *, chat_id: str, text: str) -> Mapping[str, Any]:
        destination = _chat_id(chat_id)
        _assert_safe(text, path="telegram_message")
        message_id = self.next_message_id
        self.next_message_id += 1
        self.calls.append({"chat_id": destination, "text": text, "message_id": message_id})
        return {
            "chat_id": destination,
            "message_id": message_id,
            "sent_at_utc": self.sent_at_utc.isoformat(),
            "transport": "simulated_telegram",
        }


class TelegramBotTransport:
    def __init__(self, *, bot_token: str, client: httpx.Client | None = None) -> None:
        if not isinstance(bot_token, str) or len(bot_token.strip()) < 10:
            raise TelegramPublicationError("telegram_token_invalid", "Telegram bot token is missing or invalid.")
        self._bot_token = bot_token.strip()
        self._client = client or httpx.Client(timeout=10.0)

    def __repr__(self) -> str:
        return "TelegramBotTransport(bot_token=<redacted>)"

    def send_message(self, *, chat_id: str, text: str) -> Mapping[str, Any]:
        destination = _chat_id(chat_id)
        _assert_safe(text, path="telegram_message")
        try:
            response = self._client.post(
                f"https://api.telegram.org/bot{self._bot_token}/sendMessage",
                json={"chat_id": destination, "text": text, "disable_web_page_preview": True},
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            raise TelegramPublicationError(
                "telegram_transport_failed", "Telegram send failed closed; secret-bearing provider details were suppressed."
            ) from None
        if not isinstance(payload, Mapping) or payload.get("ok") is not True:
            raise TelegramPublicationError("telegram_transport_failed", "Telegram rejected the message.")
        result = payload.get("result")
        if not isinstance(result, Mapping) or not isinstance(result.get("message_id"), int):
            raise TelegramPublicationError("telegram_transport_invalid", "Telegram response is missing message identity.")
        chat = result.get("chat")
        returned_chat_id = str(chat.get("id")) if isinstance(chat, Mapping) and chat.get("id") is not None else destination
        if returned_chat_id != destination:
            raise TelegramPublicationError("telegram_transport_invalid", "Telegram returned a different chat identity.")
        return {
            "chat_id": destination,
            "message_id": int(result["message_id"]),
            "sent_at_utc": datetime.now(UTC).isoformat(),
            "transport": "telegram_bot_api",
        }


def _receipt_digest(receipt: Mapping[str, Any]) -> str:
    body = copy.deepcopy(dict(receipt))
    body.pop("receipt_digest", None)
    return digest(body)


def verify_publication_receipt(receipt: Mapping[str, Any]) -> bool:
    if not isinstance(receipt, Mapping):
        return False
    supplied = str(receipt.get("receipt_digest") or "")
    try:
        _assert_safe(receipt)
        if receipt.get("receipt_version") != PUBLICATION_RECEIPT_VERSION:
            return False
        if receipt.get("publisher_version") != TELEGRAM_PUBLISHER_VERSION:
            return False
        if receipt.get("delivery_state") != "sent":
            return False
        if not isinstance(receipt.get("telegram_message_id"), int):
            return False
        _utc(receipt.get("sent_at_utc"), name="sent_at_utc")
    except (TypeError, ValueError, TelegramPublicationError):
        return False
    return bool(supplied) and supplied == _receipt_digest(receipt)


def publish_envelope(
    envelope: Mapping[str, Any],
    *,
    transport: TelegramTransport,
    existing_receipt: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if not verify_publication_envelope(envelope):
        raise TelegramPublicationError("telegram_envelope_invalid", "Publication envelope failed verification.")
    if existing_receipt is not None:
        if not verify_publication_receipt(existing_receipt):
            raise TelegramPublicationError("telegram_receipt_invalid", "Existing receipt failed verification.")
        if existing_receipt.get("publication_id") != envelope.get("publication_id"):
            raise TelegramPublicationError("telegram_receipt_conflict", "Existing receipt belongs to another publication.")
        if existing_receipt.get("message_digest") != envelope.get("message_digest"):
            raise TelegramPublicationError("telegram_receipt_conflict", "Existing receipt conflicts with this message.")
        return copy.deepcopy(dict(existing_receipt))

    sent = transport.send_message(chat_id=str(envelope["chat_id"]), text=str(envelope["message"]))
    if str(sent.get("chat_id")) != str(envelope["chat_id"]):
        raise TelegramPublicationError("telegram_transport_invalid", "Transport returned a different chat identity.")
    sent_at = _utc(sent.get("sent_at_utc"), name="sent_at_utc")
    receipt: dict[str, Any] = {
        "receipt_version": PUBLICATION_RECEIPT_VERSION,
        "publisher_version": TELEGRAM_PUBLISHER_VERSION,
        "publication_id": envelope["publication_id"],
        "decision_id": envelope["decision_id"],
        "ex_ante_digest": envelope["ex_ante_digest"],
        "message_digest": envelope["message_digest"],
        "group_name": envelope["group_name"],
        "chat_id": envelope["chat_id"],
        "telegram_message_id": int(sent["message_id"]),
        "transport": str(sent.get("transport") or "unknown"),
        "sent_at_utc": sent_at.isoformat(),
        "delivery_state": "sent",
    }
    _assert_safe(receipt)
    receipt["receipt_digest"] = _receipt_digest(receipt)
    return receipt


def day50_manifest() -> dict[str, Any]:
    value: dict[str, Any] = {
        "manifest_version": DAY50_MANIFEST_VERSION,
        "publisher_version": TELEGRAM_PUBLISHER_VERSION,
        "publication_envelope_version": PUBLICATION_ENVELOPE_VERSION,
        "publication_receipt_version": PUBLICATION_RECEIPT_VERSION,
        "configured_private_group_name": DEFAULT_GROUP_NAME,
        "verified_ex_ante_ledger_required": True,
        "post_model_admission_required": True,
        "eligible_actions": sorted(_ALLOWED_ACTIONS),
        "no_trade_publication_allowed": False,
        "blocked_publication_allowed": False,
        "failed_publication_allowed": False,
        "replay_publication_allowed": False,
        "shadow_publication_allowed": False,
        "idempotent_receipt_reconciliation": True,
        "simulated_transport_available": True,
        "real_transport_requires_explicit_secret_and_chat_id": True,
        "secret_values_persisted_in_receipts": False,
        "broker_dependency_allowed": False,
        "follower_dependency_allowed": False,
        "super_signals_dependency_allowed": False,
        "formal_forward_evidence_created": False,
    }
    value["manifest_digest"] = digest(value)
    return value
