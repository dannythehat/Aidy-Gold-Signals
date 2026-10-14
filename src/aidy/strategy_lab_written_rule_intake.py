"""Day20 fail-closed written-rule intake and restricted closed-signal parity.

Human-confirmed *field mappings*, not autonomous NLP or inferred rules.
Every material StrategySpec rules block requires a quote anchored in immutable
original written-source bytes and a value binding. Source presence alone does
not prove an author's intended semantics or original-platform parity.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from typing import Any

from aidy.strategy_lab_rule_validator import assess_rule_completeness
from aidy.strategy_lab_spec import StrategySpec

INTAKE_VERSION = "aidy.written_rule_intake.v1"

# Every material trading-rules block is covered. Fields omitted from here are
# origin source URL/snapshot pointers and canonical schema tags, which are
# separately verified against original bytes and explicit origin metadata.
RULE_BINDINGS: dict[str, tuple[str, ...]] = {
    "identity": ("/strategy_id", "/revision", "/title", "/candidate_type"),
    "origin": ("/origin/author", "/origin/licence", "/origin/claimed_performance",
               "/origin/unresolved_questions"),
    "market": ("/market",),
    "warmup": ("/warmup_closed_bars",),
    "indicators": ("/indicators",),
    "long_entry": ("/long/entry",),
    "long_stop": ("/long/exit/stop_loss",),
    "long_target": ("/long/exit/take_profit",),
    "long_hold": ("/long/exit/maximum_holding_bars",),
    "long_session_exit": ("/long/exit/close_on_session_end",),
    "long_opposite_exit": ("/long/exit/close_on_opposite_signal",),
    "long_trailing": ("/long/exit/trailing_stop",),
    "long_partials": ("/long/exit/partial_exits",),
    "short_side": ("/short",),
    "sessions": ("/sessions",),
    "sizing": ("/sizing",),
    "portfolio": ("/portfolio",),
    "execution": ("/execution",),
}


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _pointer(doc: dict[str, Any], pointer: str) -> Any:
    item: Any = doc
    for token in pointer.strip("/").split("/"):
        item = item[int(token)] if isinstance(item, list) else item[token]
    return item


def _source_text(source_bytes: bytes) -> str:
    if not isinstance(source_bytes, bytes) or not 0 < len(source_bytes) <= 250_000:
        raise ValueError("source must be bounded, original nonempty bytes")
    try:
        text = source_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("written-rule source is not UTF-8") from exc
    if "\x00" in text:
        raise ValueError("binary source is not written rules")
    return text


@dataclass(frozen=True)
class WrittenRuleReceipt:
    source_sha256: str
    spec_sha256: str
    evidence_sha256: str
    completeness_state: str
    evidence_groups: tuple[str, ...]
    signal_adapter_type: str
    internal_fixture_only: bool = True
    original_platform_parity_verified: bool = False
    independent_human_attestation_verified: bool = False

    def to_json(self) -> str:
        return _canonical({
            "schema": INTAKE_VERSION,
            "source_sha256": self.source_sha256,
            "spec_sha256": self.spec_sha256,
            "evidence_sha256": self.evidence_sha256,
            "completeness_state": self.completeness_state,
            "evidence_groups": list(self.evidence_groups),
            "signal_adapter_type": self.signal_adapter_type,
            "internal_fixture_only": self.internal_fixture_only,
            "original_platform_parity_verified": self.original_platform_parity_verified,
            "independent_human_attestation_verified": self.independent_human_attestation_verified,
        })


def intake_written_rules(
    source_bytes: bytes,
    spec_json: str,
    evidence: dict[str, dict[str, Any]],
    *,
    expected_source_sha256: str,
    snapshot_ref: str,
) -> tuple[StrategySpec, WrittenRuleReceipt]:
    """Reject any missing rule group, quote anchor or unqualified source bytes.

    Each caller explicitly supplies exact full spec and group-level expected
    values. This does NOT infer or synthesize omitted strategy fields.
    Only the limited EMA-cross closed-indicator trace adapter is supported.
    """
    source = _source_text(source_bytes)
    source_hash = sha256(source_bytes).hexdigest()
    if source_hash != expected_source_sha256:
        raise ValueError("original written-rule source SHA256 mismatch")
    spec = StrategySpec.from_json(spec_json)
    if (spec.origin.source_language != "written_rules"
        or spec.origin.source_sha256 != source_hash
        or spec.origin.source_snapshot_ref != snapshot_ref
        or spec.origin.unresolved_questions
        or spec.candidate_type != "complete_mechanical"):
        raise ValueError("written source provenance or interpretation not qualified")
    if set(evidence) != set(RULE_BINDINGS):
        raise ValueError("missing/unexpected explicit written-rule evidence groups")
    material = spec.to_wire()
    for group, paths in RULE_BINDINGS.items():
        row = evidence[group]
        if not isinstance(row, dict) or set(row) != {"source_excerpt", "declared_values"}:
            raise ValueError(f"invalid claim structure in {group}")
        excerpt = row["source_excerpt"]
        if not isinstance(excerpt, str) or len(excerpt) < 12 or source.count(excerpt) != 1:
            raise ValueError(f"missing or ambiguous exact written-source quote: {group}")
        claimed = row["declared_values"]
        if not isinstance(claimed, dict) or set(claimed) != set(paths):
            raise ValueError(f"missing or extraneous field bindings: {group}")
        for pointer in paths:
            if claimed[pointer] != _pointer(material, pointer):
                raise ValueError(f"rule value contradicts confirmed mapping: {group}/{pointer}")
    # A supplementary literal guard catches a reviewer accidentally binding
    # source passages with a *different* numerical stop, target, or warmup.
    # This is not semantic NLP; exact source-author intent remains review-gated.
    literal_checks = {
        "warmup": str(spec.warmup_closed_bars),
        "indicators": f"({spec.indicators[0].period})",
        "long_stop": format(spec.long.exit.stop_loss.value, "f")
            if spec.long.exit.stop_loss else "",
        "long_target": format(spec.long.exit.take_profit.value, "f")
            if spec.long.exit.take_profit else "",
        "long_hold": str(spec.long.exit.maximum_holding_bars),
        "sizing": format(spec.sizing.risk_percent_equity, "f")
            if spec.sizing.risk_percent_equity else "",
        "portfolio": format(spec.portfolio.max_total_risk_percent, "f"),
    }
    for group, literal in literal_checks.items():
        if not literal or literal not in evidence[group]["source_excerpt"]:
            raise ValueError(f"explicit source literal does not match declared {group} value")
    # Day09 validates completeness but has no source-semantic understanding.
    assessment = assess_rule_completeness(spec, source_snapshot=source_bytes)
    if not assessment.ready_for_later_reproduction:
        raise ValueError("Day09 rule-completeness/source test rejected intake")
    if not _is_supported_cross(spec):
        raise ValueError("EMA cross signal adapter unsupported or incomplete")
    evidence_hash = sha256(_canonical(evidence).encode("utf-8")).hexdigest()
    return spec, WrittenRuleReceipt(
        source_hash, sha256(spec.to_json().encode()).hexdigest(), evidence_hash,
        assessment.state, tuple(sorted(RULE_BINDINGS)),
        "closed_ema_indicator_cross_above.v1",
    )


def _is_supported_cross(spec: StrategySpec) -> bool:
    if (spec.market.signal_timeframe != "M5"
        or spec.market.symbol != "XAUUSD"
        or spec.warmup_closed_bars != 50
        or len(spec.indicators) != 2
        or spec.short.entry.enabled
        or not spec.long.entry.enabled
        or spec.long.entry.combination != "ALL"
        or len(spec.long.entry.predicates) != 1):
        return False
    indicators = {i.id: i for i in spec.indicators}
    p = spec.long.entry.predicates[0]
    if p.operator != "cross_above":
        return False
    if (p.left.kind, p.right.kind, p.left.field, p.right.field,
        p.left.offset_closed_bars, p.right.offset_closed_bars) != (
            "indicator", "indicator", "value", "value", 0, 0):
        return False
    fast, slow = indicators.get(p.left.reference), indicators.get(p.right.reference)
    return bool(
        fast and slow
        and (fast.kind, fast.period, slow.kind, slow.period) == ("EMA", 10, "EMA", 30)
        and all(
            i.timeframe == "M5" and i.price_field == "close" and not i.additional_parameters
            for i in (fast, slow)
        )
    )


@dataclass(frozen=True)
class ClosedIndicatorSample:
    closed_at_utc: datetime
    fast_ema: Decimal
    slow_ema: Decimal


def evaluate_closed_indicator_cross(
    spec: StrategySpec,
    samples: tuple[ClosedIndicatorSample, ...],
) -> tuple[datetime, ...]:
    """Parity of closed-indicator cross **predicate**, not EMA computation parity.

    The source platform's EMA seeding, missing data and timestamp rules still
    require independent tests. This function never sees future samples.
    """
    spec = StrategySpec.from_json(spec.to_json())
    if not _is_supported_cross(spec):
        raise ValueError("unsupported written-rule signal adapter")
    if not isinstance(samples, tuple) or len(samples) <= spec.warmup_closed_bars:
        raise ValueError("not enough fully closed indicator samples")
    last: datetime | None = None
    for sample in samples:
        t = sample.closed_at_utc
        if (not isinstance(t, datetime) or t.tzinfo is None
            or t.utcoffset() != timedelta(0)
            or (last is not None and t-last != timedelta(minutes=5))):
            raise ValueError("nonclosed/noncontinuous M5 indicator timestamps")
        last = t
        for price in (sample.fast_ema, sample.slow_ema):
            if not isinstance(price, Decimal) or not price.is_finite() or price <= 0:
                raise ValueError("indicator sample must be finite positive Decimal")
    # Fixed crossing semantics explicitly declared in internal written rules.
    return tuple(
        samples[i].closed_at_utc
        for i in range(spec.warmup_closed_bars, len(samples))
        if (samples[i - 1].fast_ema <= samples[i - 1].slow_ema
            and samples[i].fast_ema > samples[i].slow_ema)
    )
