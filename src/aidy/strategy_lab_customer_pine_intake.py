"""Day22: customer-led Pine Script submission triage, no provider account required.

Accept an uploaded source document (bytes) and return precise reproduction
scope in customer-readable language. No source execution, no external network
access, no synthetic TradingView reference claims. A separately supplied
reviewed StrategySpec is required before a full trading backtest.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from hashlib import sha256

from aidy.strategy_lab_pine_adapter import _parse

VERSION = "aidy.customer_pine_triage.v1"
MAX_SOURCE_BYTES = 100_000
MAX_NAME_CHARS = 128
KNOWN_OBLIGATIONS = (
    "Specify or confirm when positions exit, including stops, targets and time limits.",
    "Specify or confirm position sizing, leverage and maximum acceptable risk.",
    "Specify or confirm market, chart timeframe, trading hours and timezone.",
    "Specify or confirm the broker/execution and transaction-cost assumptions.",
)
_BLOCKING_FEATURES = (
    ("cross_timeframe", re.compile(r"\brequest\.(?:security|security_lower_tf)\s*\("),
     "Uses data from another timeframe or symbol. We must validate the exact timing and lookahead behaviour."),
    ("lookahead", re.compile(r"\blookahead\s*=|\bbarmerge\.lookahead_on\b"),
     "Contains lookahead-sensitive calculations. We must establish point-in-time rules before testing."),
    ("intrabar", re.compile(r"\b(?:varip|calc_on_every_tick|calc_on_order_fills)\b"),
     "May react within an unfinished candle. We must confirm its intrabar execution rules."),
    ("orders_exits", re.compile(r"\bstrategy\.(?:exit|close|close_all|order|cancel|cancel_all)\s*\("),
     "Contains exit or order-management instructions requiring independent reproduction."),
    ("alerts_or_external", re.compile(r"\b(?:alert|alertcondition|request\.seed)\s*\("),
     "Contains alerts or external data that must be handled separately from backtesting."),
    ("loops_or_arrays", re.compile(r"\b(?:for|while|array\.|matrix\.|map\.)"),
     "Contains advanced programme state or iteration outside the verified signal-only subset."),
)
_VERSION = re.compile(r"(?m)^//@version=([0-9]+)\s*$")
_DECLARATION = re.compile(r"\b(strategy|indicator|library)\s*\(")
_ENTRY = re.compile(r"\bstrategy\.entry\s*\(")
_CONTROLLED_DOC_TYPE = frozenset({"pine_source_upload", "source_text_paste"})


@dataclass(frozen=True)
class CustomerPineTriage:
    schema: str
    source_sha256: str
    source_bytes: int
    submission_type: str
    supplied_filename: str | None
    pine_version: str | None
    script_type: str | None
    status: str
    signal_adapter_supported: bool
    full_strategy_reproduction_qualified: bool
    independent_tradingview_parity_verified: bool
    inspection_findings: tuple[str, ...]
    customer_questions: tuple[str, ...]
    next_action: str

    def to_wire(self) -> dict:
        return {
            "schema": self.schema,
            "source_sha256": self.source_sha256,
            "source_bytes": self.source_bytes,
            "submission_type": self.submission_type,
            "supplied_filename": self.supplied_filename,
            "pine_version": self.pine_version,
            "script_type": self.script_type,
            "status": self.status,
            "signal_adapter_supported": self.signal_adapter_supported,
            "full_strategy_reproduction_qualified": self.full_strategy_reproduction_qualified,
            "independent_tradingview_parity_verified": self.independent_tradingview_parity_verified,
            "inspection_findings": list(self.inspection_findings),
            "customer_questions": list(self.customer_questions),
            "next_action": self.next_action,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_wire(), sort_keys=True, separators=(",", ":"))


def inspect_customer_pine(
    source: bytes, *, submission_type: str = "pine_source_upload",
    filename: str | None = None,
) -> CustomerPineTriage:
    """Classify customer-supplied original bytes without relying on TradingView.

    The function reports what AIDY can actually reproduce; it neither
    executes the script nor claims original-platform/strategy performance.
    """
    if not isinstance(source, bytes) or not 0 < len(source) <= MAX_SOURCE_BYTES:
        raise ValueError("A Pine source file must contain 1 to 100,000 bytes")
    if submission_type not in _CONTROLLED_DOC_TYPE:
        raise ValueError("unsupported customer submission type")
    if filename is not None and (
        not isinstance(filename, str) or not filename.strip()
        or len(filename) > MAX_NAME_CHARS
        or "/" in filename or "\\" in filename
        or any(ord(c) < 32 for c in filename)
    ):
        raise ValueError("supplied filename must be a short base name")
    digest = sha256(source).hexdigest()
    try:
        text = source.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("source text must be UTF-8") from exc
    if "\x00" in text:
        raise ValueError("binary input cannot be Pine source")
    version = _VERSION.findall(text)
    if len(version) != 1 or not text.startswith("//@version="):
        return CustomerPineTriage(
            VERSION, digest, len(source), submission_type, filename, None, None,
            "NEEDS_SCRIPT_IDENTIFICATION", False, False, False,
            ("A single Pine Script version declaration is required at the top of the file.",),
            ("Can you supply the complete original script, including its version line?",),
            "Provide the original full script; no trading test has been run.",
        )
    declarations = _DECLARATION.findall(text)
    if len(declarations) != 1:
        return CustomerPineTriage(
            VERSION, digest, len(source), submission_type, filename, version[0], None,
            "NEEDS_SCRIPT_IDENTIFICATION", False, False, False,
            ("Exactly one strategy/indicator/library declaration is required.",),
            ("Is this the complete original strategy or only an indicator fragment?",),
            "Confirm the complete source and whether it generates orders.",
        )
    kind = declarations[0]
    matched = False
    if len(source) <= 25_000:
        try:
            _parse(source)
        except ValueError:
            matched = False
        else:
            matched = True
    if matched:
        return CustomerPineTriage(
            VERSION, digest, len(source), submission_type, filename, version[0],
            "strategy", "SIGNAL_SUBSET_SUPPORTED_REQUIRES_REVIEW",
            True, False, False,
            ("Closed-candle EMA crossover entry matches an independently tested AIDY subset.",
             "Full risk, exits, order lifecycle and costs are not contained in this source."),
            KNOWN_OBLIGATIONS,
            "AIDY needs to confirm the remaining risk and exit rules before a full strategy backtest.",
        )
    findings = [
        "The source is preserved and identified, but it is outside the verified Pine subset."
    ]
    for _, regex, explanation in _BLOCKING_FEATURES:
        if regex.search(text) is not None:
            findings.append(explanation)
    if kind == "indicator":
        findings.append("This is an indicator; buy/sell decisions and trade exits are not necessarily defined.")
    if kind == "library":
        findings.append("This is a Pine library; it does not independently define a trade strategy.")
    if kind == "strategy" and _ENTRY.search(text) is None:
        findings.append("No standard strategy.entry instruction was found; entry conditions need clarification.")
    if version[0] not in ("5", "6"):
        findings.append("This Pine version has not been calibrated in AIDY.")
    return CustomerPineTriage(
        VERSION, digest, len(source), submission_type, filename, version[0], kind,
        "RULE_RECONSTRUCTION_REQUIRED", False, False, False, tuple(findings),
        ("Which exact conditions trigger a trade, and when is the signal confirmed?",
         *KNOWN_OBLIGATIONS),
        "AIDY can review and reconstruct the submitted rules; automated testing is blocked until rules are fully confirmed.",
    )
