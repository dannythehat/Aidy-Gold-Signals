"""Day35 safe strategy intake: inert source and guided rule completeness only.

No uploads are executed, fetched, queued for trading or authenticated as market
performance. Browser submissions are a local PREVIEW; a future trusted server
must rerun these checks and supply tenant isolation, storage and consent.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import re
from pathlib import PurePath
from urllib.parse import urlsplit

SCHEMA = "aidy.strategy_lab.strategy_intake.v1"
MAX_SOURCE_BYTES = 65536
MAX_TITLE = 120
MAX_URL = 2048
ALLOWED_MODES = frozenset({"paste", "upload", "link", "template"})
ALLOWED_EXTENSIONS = frozenset({".txt", ".md", ".pine", ".json"})
ALLOWED_MEDIA_TYPES = frozenset({
    "text/plain", "text/markdown", "application/json",
    "application/octet-stream", "",
})
TIMEFRAMES = frozenset({"M1", "M5", "M15", "M30", "H1", "H4", "D1"})
TEMPLATES = {
    "breakout": "Breakout concept (owner must describe confirmation, entry, invalidation and risk).",
    "trend_pullback": "Trend pullback concept (define trend, retracement, entry, stop and exit).",
    "mean_reversion": "Mean reversion concept (define range, extremes, entry and risk).",
    "session_range": "Session range concept (define explicit session timezone and DST handling).",
}
RULE_FIELDS = (
    "market", "timeframe", "trade_direction", "entry_rules", "exit_rules",
    "stop_loss_rule", "take_profit_rule", "position_sizing_rule",
    "trading_session_and_timezone", "execution_and_cost_assumptions",
)
TEXT_FIELDS = frozenset(RULE_FIELDS) - {"market", "timeframe"}
HEX = re.compile(r"^[0-9a-f]{64}$")
DANGEROUS_SECRET = re.compile(
    r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"
    r"|(?i:api[_-]?key|secret[_-]?key|password|access[_-]?token)"
    r"\s*[:=]\s*[^\s]{8,}"
)
DISALLOWED_HTML = re.compile(r"(?i)<\s*/?\s*(?:script|iframe|object|embed|svg|html)\b")
BIN_SIGNATURES = (
    b"MZ", b"\x7fELF", b"%PDF", b"PK\x03\x04", b"\x1f\x8b",
    b"\x89PNG\r\n", b"\xff\xd8\xff", b"Rar!\x1a\x07",
)
HOST_RE = re.compile(r"^(?=.{4,253}$)[a-z0-9](?:[a-z0-9.-]*[a-z0-9])$")
NAME_RE = re.compile(r"^[a-zA-Z0-9 _.'()-]{3,120}$")


class IntakeRejected(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _hash(obj: object) -> str:
    return hashlib.sha256(json.dumps(
        obj, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode()).hexdigest()


def _safe_text(value: object, max_length: int, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise IntakeRejected("INVALID_TEXT_FIELD")
    text = value.strip()
    if (len(text) > max_length
            or (not allow_empty and not text)
            or any(ord(c) < 32 and c not in "\t\n\r" for c in text)
            or "\x00" in text
            or DANGEROUS_SECRET.search(text)
            or DISALLOWED_HTML.search(text)):
        raise IntakeRejected("UNSAFE_OR_MISSING_TEXT")
    return text


def _decode_text(blob: bytes) -> str:
    if not isinstance(blob, bytes) or not blob or len(blob) > MAX_SOURCE_BYTES:
        raise IntakeRejected("UNSUPPORTED_OR_OVERSIZED_FILE")
    if any(blob.startswith(header) for header in BIN_SIGNATURES):
        raise IntakeRejected("BINARY_UPLOAD_REJECTED")
    if b"\x00" in blob or b"\x1b" in blob:
        raise IntakeRejected("BINARY_UPLOAD_REJECTED")
    try:
        source = blob.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError as exc:
        raise IntakeRejected("UTF8_TEXT_REQUIRED") from exc
    _safe_text(source, MAX_SOURCE_BYTES)
    # Reject unusual control bytes even if still valid UTF-8.
    if any(ord(c) < 32 and c not in "\t\n\r" for c in source):
        raise IntakeRejected("BINARY_UPLOAD_REJECTED")
    return source


def validate_link(value: str) -> str:
    raw = _safe_text(value, MAX_URL)
    try:
        parsed = urlsplit(raw)
        port = parsed.port
        hostname = parsed.hostname
    except ValueError as exc:
        raise IntakeRejected("INVALID_SOURCE_LINK") from exc
    if (parsed.scheme != "https" or not hostname
            or parsed.username or parsed.password
            or port not in (None, 443) or parsed.fragment
            or "\\" in raw or any(x.isspace() for x in raw)
            or "@" in parsed.netloc or not HOST_RE.fullmatch(hostname)
            or hostname.lower() in {"localhost", "localhost.localdomain"}
            or hostname.lower().endswith((".local", ".internal", ".localhost"))
            or hostname.startswith("xn--")
            or any(x in parsed.query.lower() for x in (
                "token=", "key=", "secret=", "password=", "auth=", "access_token=",
            ))):
        raise IntakeRejected("INVALID_SOURCE_LINK")
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        # Never permit IP-literal target, even public; link is NOT fetched.
        raise IntakeRejected("IP_LITERAL_SOURCE_LINK_REJECTED")
    if ".." in hostname or "." not in hostname or hostname.endswith("."):
        raise IntakeRejected("INVALID_SOURCE_LINK")
    return raw


def _source(mode: str, value: str | bytes, *, filename: str = "",
            media_type: str = "") -> dict:
    if mode not in ALLOWED_MODES:
        raise IntakeRejected("UNSUPPORTED_INTAKE_MODE")
    if mode == "upload":
        name = _safe_text(filename, 180)
        if (name != PurePath(name).name or "/" in name or "\\" in name
                or name.startswith(".") or PurePath(name).suffix.lower()
                not in ALLOWED_EXTENSIONS or media_type not in ALLOWED_MEDIA_TYPES):
            raise IntakeRejected("UNSUPPORTED_UPLOAD_TYPE")
        body = _decode_text(value)
        return {"kind": mode, "source_name": name,
                "declared_media_type": media_type,
                "original_sha256": hashlib.sha256(value).hexdigest(),
                "inert_text": body, "url": None, "template_id": None}
    if not isinstance(value, str):
        raise IntakeRejected("TEXT_OR_LINK_REQUIRED")
    if mode == "link":
        url = validate_link(value)
        return {"kind": mode, "source_name": None,
                "declared_media_type": None,
                "original_sha256": hashlib.sha256(url.encode()).hexdigest(),
                "inert_text": None, "url": url, "template_id": None,
                "remote_content_fetched": False}
    if mode == "template":
        if value not in TEMPLATES:
            raise IntakeRejected("UNSUPPORTED_TEMPLATE")
        body = TEMPLATES[value]
        return {"kind": mode, "source_name": None,
                "declared_media_type": None,
                "original_sha256": hashlib.sha256(body.encode()).hexdigest(),
                "inert_text": body, "url": None, "template_id": value}
    body = _safe_text(value, MAX_SOURCE_BYTES)
    if len(body.encode()) > MAX_SOURCE_BYTES:
        raise IntakeRejected("OVERSIZED_PASTE")
    return {"kind": mode, "source_name": None,
            "declared_media_type": None,
            "original_sha256": hashlib.sha256(body.encode()).hexdigest(),
            "inert_text": body, "url": None, "template_id": None}


def prepare_intake(*, mode: str, value: str | bytes, title: str,
                   rules: dict, filename: str = "", media_type: str = "",
                   submitter_rights_declaration: bool = False) -> dict:
    """A deterministic local *draft*; never a trusted customer/owner consent.

    No IP licence, run request, trade, publication or production action is issued.
    """
    if (not isinstance(title, str) or not NAME_RE.fullmatch(title.strip())
            or type(submitter_rights_declaration) is not bool):
        raise IntakeRejected("INVALID_TITLE_OR_DECLARATION")
    if not isinstance(rules, dict) or set(rules) != set(RULE_FIELDS):
        raise IntakeRejected("RULE_SCHEMA_UNSUPPORTED")
    normalized: dict[str, str] = {}
    for key in RULE_FIELDS:
        raw = rules[key]
        if not isinstance(raw, str):
            raise IntakeRejected("INVALID_RULE_FIELD")
        text = _safe_text(raw, 2000, allow_empty=True)
        if key == "market" and text and text != "XAUUSD":
            raise IntakeRejected("UNSUPPORTED_MARKET")
        if key == "timeframe" and text and text not in TIMEFRAMES:
            raise IntakeRejected("UNSUPPORTED_TIMEFRAME")
        normalized[key] = text
    source = _source(mode, value, filename=filename, media_type=media_type)
    missing = [
        {"field": name, "guidance": guidance} for name, guidance in (
            ("market", "Confirm XAUUSD (gold) as the instrument."),
            ("timeframe", "Specify original chart timeframe, e.g. M5, H1 or H4."),
            ("trade_direction", "State long, short or both, and exact allowed conditions."),
            ("entry_rules", "Write objective entry and confirmation rules."),
            ("exit_rules", "Specify how/when each position closes."),
            ("stop_loss_rule", "State exact stop or explicitly no stop with explanation."),
            ("take_profit_rule", "State exact target or alternative exit with explanation."),
            ("position_sizing_rule", "Define risk and position size; no real-money order is created."),
            ("trading_session_and_timezone", "Describe time windows in a named timezone and DST."),
            ("execution_and_cost_assumptions", "Specify spreads, fees, slippage, order and fill rules."),
        ) if not normalized[name]
    ]
    packet = {
        "schema": SCHEMA,
        "research_engine": "AIDY",
        "future_customer_brand": "GoldThinker",
        "submission_title": title.strip(),
        "source": source,
        "rules": normalized,
        "missing_rules": missing,
        "status": "INCOMPLETE_RULES" if missing else "AWAITING_INDEPENDENT_RULE_REVIEW",
        "submitter_rights_declaration": submitter_rights_declaration,
        "actual_licence_verified": False,
        "tenant_authenticated": False,
        "trusted_server_accepted": False,
        "strategy_rules_verified": False,
        "eligible_for_production": False,
        "aidy_research_executed": False,
        "real_xauusd_profit_evaluated": False,
        "goldthinker_named_or_joinable": False,
        "paper_or_live_trading_enabled": False,
    }
    packet["draft_sha256"] = _hash(packet)
    return packet


def verify_draft(packet: dict) -> None:
    if not isinstance(packet, dict) or packet.get("schema") != SCHEMA:
        raise IntakeRejected("INVALID_DRAFT_SCHEMA")
    source = packet.get("source", {})
    if packet.get("draft_sha256") != _hash({
        k: v for k, v in packet.items() if k != "draft_sha256"
    }):
        raise IntakeRejected("DRAFT_TAMPERED")
    if (source.get("kind") not in ALLOWED_MODES
            or not HEX.fullmatch(source.get("original_sha256", ""))
            or packet["tenant_authenticated"] is not False
            or packet["trusted_server_accepted"] is not False
            or packet["eligible_for_production"] is not False
            or packet["aidy_research_executed"] is not False
            or packet["goldthinker_named_or_joinable"] is not False
            or packet["paper_or_live_trading_enabled"] is not False):
        raise IntakeRejected("UNTRUSTED_DRAFT_PRIVILEGES")
    if packet["status"] not in {"INCOMPLETE_RULES", "AWAITING_INDEPENDENT_RULE_REVIEW"}:
        raise IntakeRejected("UNSUPPORTED_DRAFT_STATUS")
