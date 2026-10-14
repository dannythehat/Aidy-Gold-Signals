"""Day20 narrowly scoped, human-reviewed written-rule -> StrategySpec admission.

Supports ONE fully enumerated internal EMA-crossover English syntax. Everything
else is BLOCKED rather than guessed. No executable user text and no claimed
third-party source-platform equivalence or external trading edge.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
from typing import Any

from aidy.strategy_lab_rule_validator import assess_rule_completeness
from aidy.strategy_lab_spec import StrategySpec

# FULL TEXT match: an appended unseen condition must fail; only numeric
# parameters and session hours in this one signed-off grammar may vary.
_SOURCE_GRAMMAR = re.compile(
    r"\\A# AIDY INTERNAL TEST FIXTURE ONLY — NOT A THIRD-PARTY STRATEGY\\. "
    r"# No source-platform parity or returns are claimed\\. "
    r"Instrument XAUUSD\\. Source HistData Generic ASCII native M1 bid OHLC with "
    r"fixed EST UTC-05 source clock\\. Signal timeframe M5\\. "
    r"UTC sessions Monday through Friday from (?P<session_start>\\d{2}:\\d{2}) "
    r"inclusive until (?P<session_end>\\d{2}:\\d{2}) exclusive, and flatten "
    r"at session end\\. Warm up for (?P<warmup>\\d+) fully closed M5 candles\\. "
    r"Compute EMA\\((?P<fast>\\d+)\\) and EMA\\((?P<slow>\\d+)\\) "
    r"on closed M5 close prices\\. Enter one long when EMA\\((?P<entry_fast>\\d+)\\) "
    r"crosses above EMA\\((?P<entry_slow>\\d+)\\) on a fully closed M5 bar\\. "
    r"Execute at next tradable quote \\(not at a known signal close\\)\\. "
    r"Never enter short positions\\. Initial long stop: "
    r"(?P<stop>\\d+) broker-defined ticks from entry\\. Take profit: "
    r"(?P<target>\\d+) ticks from entry\\. Maximum hold "
    r"(?P<hold>\\d+) closed signal-timeframe bars\\. "
    r"Close at the end of the active permitted session\\. "
    r"Risk (?P<risk>\\d+)% of equity at the initial stop, maximum portfolio risk "
    r"(?P<max_risk>\\d+)%, maximum one position, no hedging, no pyramiding\\. "
    r"Market source parity, precise EMA implementation, tick size, source "
    r"session closures and fill/fee costs are not evidenced by this fixture\\.\\Z"
)
_SUPPORTED_REVIEW_FIELDS = frozenset({
    "schema_version", "reviewer", "confirmed_at_utc", "source_snapshot_ref",
    "source_sha256", "approved_spec",
})
_ACCEPTANCE = "aidy.written_rule_review.v1"


def _utc_confirmation(value: Any) -> None:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("human review confirmation must contain UTC Z timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("invalid review timestamp") from exc
    if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
        raise ValueError("human confirmation timestamp not UTC")


def read_supported_written_rules(original: bytes) -> dict[str, Any]:
    if not isinstance(original, bytes) or not 0 < len(original) < 100_000:
        raise ValueError("written source is missing or unbounded")
    try:
        text = original.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("written rules must be UTF-8") from exc
    matched = _SOURCE_GRAMMAR.fullmatch(" ".join(text.split()))
    if matched is None:
        raise ValueError("UNSUPPORTED_WRITTEN_RULES: unrecognised/missing/extra conditions")
    p = matched.groupdict()
    for field in ("fast", "slow", "warmup", "stop", "target", "hold", "risk", "max_risk"):
        if not 1 <= int(p[field]) <= 100_000:
            raise ValueError("UNSUPPORTED_WRITTEN_RULES: invalid bounded numeric rule")
    if int(p["fast"]) >= int(p["slow"]) or (
        p["fast"] != p["entry_fast"] or p["slow"] != p["entry_slow"]
    ):
        raise ValueError("UNSUPPORTED_WRITTEN_RULES: contradiction in written EMA references")
    if not (p["session_start"] < p["session_end"] and p["session_end"] <= "23:59"):
        raise ValueError("UNSUPPORTED_WRITTEN_RULES: overnight/zero session unsupported")
    return {
        "fast_period": int(p["fast"]), "slow_period": int(p["slow"]),
        "warmup_closed_bars": int(p["warmup"]),
        "session_start": p["session_start"], "session_end": p["session_end"],
        "stop_ticks": int(p["stop"]), "target_ticks": int(p["target"]),
        "hold_bars": int(p["hold"]), "risk_percent": int(p["risk"]),
        "max_total_risk_percent": int(p["max_risk"]),
        "signal_operator": "cross_above", "signal_timeframe": "M5",
        "buy_only": True, "entry_execution": "next_tradable_quote",
    }


def _require_match(spec: StrategySpec, rules: dict[str, Any]) -> None:
    """No silent inference: compare ALL supported material fields and defaults."""
    w = spec.to_wire()
    em = w["indicators"]
    signature = {
        "origin_language": w["origin"]["source_language"],
        "origin_questions": w["origin"]["unresolved_questions"],
        "market": w["market"],
        "candidate_type": w["candidate_type"],
        "warmup": w["warmup_closed_bars"],
        "indicators": em,
        "long_entry": w["long"]["entry"],
        "long_exit": w["long"]["exit"],
        "short": w["short"],
        "sessions": w["sessions"],
        "sizing": w["sizing"],
        "portfolio": w["portfolio"],
        "execution": w["execution"],
    }
    expected = {
        "origin_language": "written_rules",
        "origin_questions": [],
        "market": {
            "symbol": "XAUUSD", "signal_timeframe": "M5",
            "data_source": "histdata:generic_ascii_m1",
            "source_clock": "EST_FIXED_UTC_MINUS_05", "price_basis": "bid",
        },
        "candidate_type": "complete_mechanical",
        "warmup": rules["warmup_closed_bars"],
        "indicators": [
            {"id":"fast_ema","kind":"EMA","timeframe":"M5","price_field":"close",
             "period":rules["fast_period"],"additional_parameters":{}},
            {"id":"slow_ema","kind":"EMA","timeframe":"M5","price_field":"close",
             "period":rules["slow_period"],"additional_parameters":{}},
        ],
        "long_entry": {
            "enabled": True, "combination": "ALL",
            "predicates": [{
                "left":{"kind":"indicator","reference":"fast_ema",
                        "field":"value","offset_closed_bars":0},
                "operator":"cross_above",
                "right":{"kind":"indicator","reference":"slow_ema",
                         "field":"value","offset_closed_bars":0},
            }],
        },
        "long_exit": {
            "stop_loss":{"mode":"ticks","value":str(rules["stop_ticks"]),"indicator_id":None},
            "take_profit":{"mode":"ticks","value":str(rules["target_ticks"]),"indicator_id":None},
            "trailing_stop":None,"partial_exits":[],
            "maximum_holding_bars":rules["hold_bars"],
            "close_on_opposite_signal":False,"close_on_session_end":True,
        },
        "short": {
            "entry":{"enabled":False,"combination":"ALL","predicates":[]},
            "exit":{"stop_loss":None,"take_profit":None,"trailing_stop":None,
                    "partial_exits":[],"maximum_holding_bars":None,
                    "close_on_opposite_signal":False,"close_on_session_end":False},
        },
        "sessions": {
            "timezone":"UTC",
            "allowed":[{"weekday":i,"start_hhmm":rules["session_start"],
                       "end_hhmm":rules["session_end"]} for i in range(5)],
            "excluded_dates":[],"flat_outside_sessions":True,
        },
        "sizing":{"mode":"risk_percent_equity","fixed_lots":None,
                  "risk_percent_equity":str(rules["risk_percent"])},
        "portfolio":{
            "max_positions":1,"allow_hedging":False,"allow_pyramiding":False,
            "max_total_risk_percent":str(rules["max_total_risk_percent"]),
        },
        "execution":{
            "signal_evaluation":"closed_bar_only",
            "entry_execution":"next_tradable_quote",
        },
    }
    differing = sorted(k for k in expected if signature[k] != expected[k])
    if differing:
        raise ValueError("REVIEW_SOURCE_RULE_MISMATCH: " + ",".join(differing))


@dataclass(frozen=True, slots=True)
class WrittenRuleAdmission:
    spec: StrategySpec
    source_sha256: str
    review_sha256: str
    spec_sha256: str
    parsed_rules: dict[str, Any]
    ready_for_later_reproduction: bool
    source_platform_parity_verified: bool = False

    def to_json(self) -> str:
        return json.dumps({
            "spec_sha256": self.spec_sha256, "review_sha256": self.review_sha256,
            "source_sha256": self.source_sha256,
            "ready_for_later_reproduction":self.ready_for_later_reproduction,
            "source_platform_parity_verified":self.source_platform_parity_verified,
            "parsed_rules":self.parsed_rules,
        },sort_keys=True,separators=(",",":"))


def admit_written_rules(source_bytes: bytes, review_bytes: bytes) -> WrittenRuleAdmission:
    rules = read_supported_written_rules(source_bytes)
    if not isinstance(review_bytes, bytes) or not review_bytes:
        raise ValueError("human written-rule review bytes required")
    try:
        manifest = json.loads(review_bytes.decode("utf-8"),
                              object_pairs_hook=_no_duplicate_fields)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid human confirmation JSON") from exc
    if not isinstance(manifest,dict) or set(manifest)!=_SUPPORTED_REVIEW_FIELDS:
        raise ValueError("written-rule human review incomplete/unknown fields")
    if manifest["schema_version"]!=_ACCEPTANCE:
        raise ValueError("unsupported human confirmation schema")
    reviewer=manifest["reviewer"]
    if not isinstance(reviewer,str) or not reviewer.strip() or reviewer!=reviewer.strip():
        raise ValueError("named human reviewer required")
    _utc_confirmation(manifest["confirmed_at_utc"])
    digest = sha256(source_bytes).hexdigest()
    if manifest["source_sha256"]!=digest:
        raise ValueError("pinned original written source does not match review SHA")
    if not isinstance(manifest["source_snapshot_ref"],str) or not manifest["source_snapshot_ref"].strip():
        raise ValueError("original source reference required")
    spec=StrategySpec.from_wire(manifest["approved_spec"])
    if (spec.origin.source_sha256 != digest or
        spec.origin.source_snapshot_ref != manifest["source_snapshot_ref"]):
        raise ValueError("human-reviewed spec not bound to original source bytes")
    _require_match(spec,rules)
    accepted=assess_rule_completeness(spec,source_snapshot=source_bytes)
    if not accepted.ready_for_later_reproduction:
        raise ValueError("Day09 rule admission blocked: "+",".join(
            issue.code for issue in accepted.issues
        ))
    return WrittenRuleAdmission(spec,digest,sha256(review_bytes).hexdigest(),
        accepted.spec_sha256 or "",rules,True)


def _no_duplicate_fields(pairs: list[tuple[str,Any]]) -> dict[str,Any]:
    values:dict[str,Any]={}
    for key,value in pairs:
        if key in values:
            raise ValueError("duplicate human review field")
        values[key]=value
    return values


def _ema_reference(period: int, closes: tuple[Decimal,...]) -> tuple[Decimal|None,...]:
    """Independent written-source EMA reference: SMA seed, recursive EMA."""
    result:list[Decimal|None] = [None] * len(closes)
    alpha=Decimal(2)/(Decimal(period)+1)
    for i in range(period-1,len(closes)):
        if i==period-1:
            result[i]=sum(closes[:period],Decimal(0))/period
        else:
            previous=result[i-1]
            assert previous is not None
            result[i]=alpha*closes[i]+(Decimal(1)-alpha)*previous
    return tuple(result)


def written_source_signal_indices(original:bytes, prices:tuple[Decimal,...]) -> tuple[int,...]:
    parsed=read_supported_written_rules(original)
    f=_ema_reference(parsed["fast_period"],prices)
    s=_ema_reference(parsed["slow_period"],prices)
    start=max(parsed["warmup_closed_bars"]-1,parsed["slow_period"])
    return tuple(i for i in range(start,len(prices))
        if f[i-1] is not None and s[i-1] is not None and f[i] is not None
        and s[i] is not None and f[i-1] <= s[i-1] and f[i]>s[i])


def strategy_spec_signal_indices(spec:StrategySpec,prices:tuple[Decimal,...])->tuple[int,...]:
    """Day08 machine-spec reference implementation; no source text consulted."""
    spec=StrategySpec.from_json(spec.to_json())
    if (len(spec.indicators)!=2 or not spec.long.entry.enabled or
        len(spec.long.entry.predicates)!=1 or
        spec.long.entry.predicates[0].operator!="cross_above"):
        raise ValueError("unsupported spec signal evaluator")
    ind={i.id:i for i in spec.indicators}
    p=spec.long.entry.predicates[0]
    fast,slow=ind[p.left.reference],ind[p.right.reference]
    def series(n:int)->list[Decimal|None]:
        output:list[Decimal|None]=[]
        prev:Decimal|None=None
        for index,close in enumerate(prices):
            if index<n-1:
                output.append(None)
                continue
            if index==n-1:
                prev=sum(prices[:n],Decimal(0))/Decimal(n)
            else:
                assert prev is not None
                prev=prev+(Decimal(2)/(Decimal(n)+1))*(close-prev)
            output.append(prev)
        return output
    a,b=series(fast.period),series(slow.period)
    out=[]
    for index in range(max(spec.warmup_closed_bars-1,slow.period),len(prices)):
        if all(x is not None for x in (a[index-1],b[index-1],a[index],b[index])):
            if a[index-1]<=b[index-1] and a[index]>b[index]:
                out.append(index)
    return tuple(out)
