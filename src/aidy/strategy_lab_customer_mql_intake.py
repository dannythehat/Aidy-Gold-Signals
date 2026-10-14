"""Day23 customer MQL4/MQL5 source triage, not MetaTrader code execution."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from hashlib import sha256

from aidy.strategy_lab_mql_adapter import _validate_source

MAX_CUSTOMER_BYTES = 100_000
QUESTIONS = (
    "What exact condition opens a position, and is the candle fully closed?",
    "What exactly closes it: opposite signal, stop, target, time or other rule?",
    "What are the position sizing, maximum risk and simultaneous trade limits?",
    "Which symbol, chart timeframe, timezone and trading hours apply?",
    "Which broker, spreads, commissions, swaps and fill assumptions apply?",
)
FEATURES = (
    (r"\b(?:OnTick|start|OnTimer|OnTradeTransaction)\s*\(", "Event handlers require terminal timing and event-order review."),
    (r"\b(?:OrderSend|OrderClose|PositionOpen|CTrade|trade\.Buy|trade\.Sell)\b",
     "Trading/order APIs require broker-specific execution and error handling."),
    (r"\b(?:iMA|CopyBuffer|iCustom|iTime|iBarShift)\s*\(",
     "Indicator buffer shifts, seeding and handle semantics require MQL4/MQL5-specific evidence."),
    (r"\b(?:WebRequest|ShellExecute|#import|#include)\b",
     "External imports, requests or libraries are not run by AIDY."),
    (r"\b(?:OnTester|OnCalculate)\s*\(",
     "Tester/indicator callbacks require native terminal validation."),
    (r"\b(?:StopLoss|TakeProfit|slippage|MagicNumber)\b",
     "Broker-specific stop/target, slippage and order-identity rules require review."),
)


@dataclass(frozen=True)
class MqlIntake:
    schema: str
    source_sha256: str
    source_bytes: int
    original_filename: str
    declared_language: str
    status: str
    predicate_subset_supported: bool
    full_strategy_qualified: bool
    native_mt_parity_qualified: bool
    findings: tuple[str, ...]
    questions: tuple[str, ...]

    def to_json(self) -> str:
        return json.dumps({
            "schema": self.schema, "source_sha256": self.source_sha256,
            "source_bytes": self.source_bytes, "original_filename": self.original_filename,
            "declared_language": self.declared_language, "status": self.status,
            "predicate_subset_supported": self.predicate_subset_supported,
            "full_strategy_qualified": self.full_strategy_qualified,
            "native_mt_parity_qualified": self.native_mt_parity_qualified,
            "findings": list(self.findings), "questions": list(self.questions),
        }, sort_keys=True, separators=(",", ":"))


def inspect_customer_mql(source: bytes, *, filename: str) -> MqlIntake:
    if not isinstance(filename, str) or not 1 <= len(filename) <= 128 or (
        any(c in filename for c in "/\\") or
        any(ord(c) < 32 for c in filename)
    ):
        raise ValueError("MQL source filename must be a bounded safe base name")
    lowered = filename.lower()
    if lowered.endswith(".mq4"):
        lang = "mql4"
    elif lowered.endswith(".mq5"):
        lang = "mql5"
    else:
        raise ValueError("customer MQL source requires .mq4 or .mq5")
    if not isinstance(source, bytes) or not 0 < len(source) <= MAX_CUSTOMER_BYTES:
        raise ValueError("customer source must contain 1 to 100000 bytes")
    try:
        decoded = source.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("MQL customer source must be UTF-8") from exc
    if "\x00" in decoded:
        raise ValueError("binary customer source not allowed")
    digest = sha256(source).hexdigest()
    supported = False
    try:
        _validate_source(source)
        supported = True
    except ValueError:
        pass
    findings = (
        ("Pure closed EMA entry/exit predicate grammar recognised.",
         "Actual EA orders, stops, targets and risk settings are not present.")
        if supported else
        ("Source preserved. Full MQL grammar is outside the admitted safe subset.",
         *(message for regex, message in FEATURES
           if re.search(regex, decoded, flags=re.IGNORECASE)))
    )
    return MqlIntake(
        "aidy.customer_mql_intake.v1", digest, len(source), filename, lang,
        "PREDICATE_SUBSET_SUPPORTED_REVIEW_REQUIRED" if supported else
        "RULE_RECONSTRUCTION_REQUIRED", supported, False, False,
        tuple(findings), QUESTIONS,
    )
