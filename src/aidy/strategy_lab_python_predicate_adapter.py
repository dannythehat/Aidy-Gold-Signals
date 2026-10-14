"""Day 21 — restricted Python strategy predicate adapter.

UNTRUSTED SOURCE IS NEVER EXECUTED. The only accepted Python form is a
four-argument, one-return, closed-EMA crossover function with two approved
comparison predicates. We parse the AST and interpret Decimal comparisons
ourselves; no compile(), eval(), exec(), import, calls, attributes, filesystem,
network, or subprocess is available to strategy source.

This is NOT a general secure Python sandbox. Other Python strategies remain
BLOCKED pending independently isolated runtimes / expanded approved grammars.
"""
from __future__ import annotations

import ast
import json
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from hashlib import sha256
from typing import Any

from aidy.strategy_lab_spec import StrategySpec
from aidy.strategy_lab_written_rule_intake import (
    ClosedIndicatorSample,
    _is_supported_cross,
    evaluate_closed_indicator_cross,
)

ADAPTER_VERSION = "aidy.python_predicate_adapter.v1"
ALLOWED_ARGS = ("fast_prev", "slow_prev", "fast_now", "slow_now")
ALLOWED_PREDICATES = frozenset({
    ("fast_prev", "LtE", "slow_prev"),
    ("fast_now", "Gt", "slow_now"),
})
SOURCE_BYTE_LIMIT = 8_192


def _source_tree(source_bytes: bytes) -> ast.BoolOp:
    if not isinstance(source_bytes, bytes) or not 0 < len(source_bytes) <= SOURCE_BYTE_LIMIT:
        raise ValueError("Python source must be bounded nonempty original bytes")
    try:
        decoded = source_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("Python source must be UTF-8") from exc
    if "\x00" in decoded:
        raise ValueError("binary NUL forbidden in Python source")
    try:
        tree = ast.parse(decoded, mode="exec")
    except (SyntaxError, ValueError) as exc:
        raise ValueError("Python source is not valid isolated syntax") from exc
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.FunctionDef):
        raise ValueError("only one pure signal function is supported")
    func = tree.body[0]
    args = func.args
    if (func.name != "signal" or func.decorator_list or func.returns is not None
        or func.type_params or args.posonlyargs or args.vararg or args.kwarg
        or args.kwonlyargs or args.kw_defaults or args.defaults
        or len(args.args) != 4
        or any(a.annotation is not None for a in args.args)
        or tuple(a.arg for a in args.args) != ALLOWED_ARGS
        or len(func.body) != 1 or not isinstance(func.body[0], ast.Return)):
        raise ValueError("only pure signal(fast_prev,slow_prev,fast_now,slow_now) supported")
    expression = func.body[0].value
    if not isinstance(expression, ast.BoolOp) or not isinstance(expression.op, ast.And):
        raise ValueError("signal must AND both supported crossover predicates")
    if len(expression.values) != 2:
        raise ValueError("signal must contain exactly two crossover predicates")
    predicates: set[tuple[str, str, str]] = set()
    for comparison in expression.values:
        if (not isinstance(comparison, ast.Compare)
            or len(comparison.ops) != 1 or len(comparison.comparators) != 1
            or not isinstance(comparison.left, ast.Name)
            or not isinstance(comparison.comparators[0], ast.Name)):
            raise ValueError("only direct closed-indicator comparisons supported")
        key = (
            comparison.left.id, type(comparison.ops[0]).__name__,
            comparison.comparators[0].id,
        )
        if key not in ALLOWED_PREDICATES or key in predicates:
            raise ValueError("comparison not in approved StrategySpec crossover")
        predicates.add(key)
    if predicates != ALLOWED_PREDICATES:
        raise ValueError("both exact crossover comparisons are mandatory")
    # Structural whitelist: no Call, Attribute, Import, comprehension, lambda,
    # arithmetic, subscripts, globals, decorators, annotations or statements.
    whitelist = (
        ast.Module, ast.FunctionDef, ast.arguments, ast.arg, ast.Return,
        ast.BoolOp, ast.And, ast.Compare, ast.Name, ast.Load, ast.LtE, ast.Gt,
    )
    if any(not isinstance(node, whitelist) for node in ast.walk(tree)):
        raise ValueError("Python AST contains forbidden executable syntax")
    return expression


def _interpret(expression: ast.BoolOp, values: dict[str, Decimal]) -> bool:
    """No Python bytecode execution: only two fixed Decimal comparisons."""
    results = []
    for node in expression.values:
        if not isinstance(node, ast.Compare):
            raise ValueError("invalid untrusted expression")
        left, right = node.left, node.comparators[0]
        if not isinstance(left, ast.Name) or not isinstance(right, ast.Name):
            raise ValueError("unsupported expression operands")
        x, y = values[left.id], values[right.id]
        op = node.ops[0]
        if isinstance(op, ast.LtE):
            results.append(x <= y)
        elif isinstance(op, ast.Gt):
            results.append(x > y)
        else:
            raise ValueError("unsupported expression comparator")
    return all(results)


@dataclass(frozen=True)
class PythonPredicateAdapter:
    source_bytes: bytes
    spec_json: str
    source_sha256: str
    spec_sha256: str
    ast_sha256: str
    source_snapshot_ref: str
    grammar: str = ADAPTER_VERSION
    unrestricted_python_executed: bool = False
    broker_platform_parity_verified: bool = False

    def to_json(self) -> str:
        return json.dumps({
            "grammar":self.grammar,
            "source_sha256":self.source_sha256,
            "spec_sha256":self.spec_sha256,
            "ast_sha256":self.ast_sha256,
            "source_snapshot_ref":self.source_snapshot_ref,
            "unrestricted_python_executed":self.unrestricted_python_executed,
            "broker_platform_parity_verified":self.broker_platform_parity_verified,
        },sort_keys=True,separators=(",",":"))


def admit_python_predicate(
    source_bytes: bytes, spec_json: str, *,
    expected_source_sha256: str, source_snapshot_ref: str,
) -> PythonPredicateAdapter:
    """Bind original restricted source to an explicitly reviewed canonical spec.

    Cannot infer a complete trading strategy from this one signal function.
    Other entry, exit, sizing and session rules MUST be supplied as exact spec
    metadata and separately source-reviewed.
    """
    expression = _source_tree(source_bytes)
    if not isinstance(expected_source_sha256, str) or (
        sha256(source_bytes).hexdigest() != expected_source_sha256
    ):
        raise ValueError("original Python strategy source SHA256 mismatch")
    spec = StrategySpec.from_json(spec_json)
    if (not _is_supported_cross(spec)
        or spec.origin.source_language != "python"
        or spec.origin.source_sha256 != expected_source_sha256
        or spec.origin.source_snapshot_ref != source_snapshot_ref
        or not isinstance(source_snapshot_ref, str) or not source_snapshot_ref.strip()
        or spec.origin.unresolved_questions):
        raise ValueError("Python predicate inconsistent with qualified StrategySpec")
    return PythonPredicateAdapter(
        source_bytes, spec.to_json(), expected_source_sha256,
        sha256(spec.to_json().encode()).hexdigest(),
        sha256(ast.dump(expression, include_attributes=False).encode()).hexdigest(),
        source_snapshot_ref,
    )


def evaluate_restricted_python(
    adapter: PythonPredicateAdapter, samples: tuple[ClosedIndicatorSample, ...],
) -> tuple:
    """Return closed-bar signal UTC timestamps with no user code execution.

    Validate original source and typed spec again, disallow forged adapter
    records, and enforce exactly ordered closed M5 input timestamps.
    """
    if not isinstance(adapter, PythonPredicateAdapter):
        raise ValueError("expected a frozen restricted-Python adapter")
    fresh = admit_python_predicate(
        adapter.source_bytes, adapter.spec_json,
        expected_source_sha256=adapter.source_sha256,
        source_snapshot_ref=adapter.source_snapshot_ref,
    )
    if fresh != adapter:
        raise ValueError("Python adapter or evidence was tampered with")
    spec = StrategySpec.from_json(adapter.spec_json)
    if not isinstance(samples, tuple) or len(samples) <= spec.warmup_closed_bars:
        raise ValueError("insufficient fully closed bars")
    previous = None
    for sample in samples:
        if not isinstance(sample, ClosedIndicatorSample):
            raise ValueError("only closed indicator trace records supported")
        stamp = sample.closed_at_utc
        if (stamp.tzinfo is None or stamp.utcoffset() != timedelta(0)
            or (previous is not None and stamp - previous != timedelta(minutes=5))):
            raise ValueError("indicator bars must be strictly consecutive UTC M5 closes")
        previous = stamp
        if any(not isinstance(value, Decimal) or not value.is_finite() or value <= 0
               for value in (sample.fast_ema, sample.slow_ema)):
            raise ValueError("closed indicator values require finite positive Decimal")
    expression = _source_tree(adapter.source_bytes)
    matched = []
    for i in range(spec.warmup_closed_bars, len(samples)):
        old, now = samples[i-1], samples[i]
        env = {
            "fast_prev":old.fast_ema, "slow_prev":old.slow_ema,
            "fast_now":now.fast_ema, "slow_now":now.slow_ema,
        }
        if _interpret(expression, env):
            matched.append(now.closed_at_utc)
    return tuple(matched)


def compare_python_with_spec(
    adapter: PythonPredicateAdapter, samples: tuple[ClosedIndicatorSample, ...],
) -> dict[str, Any]:
    """Independent Day20 StrategySpec reference check on the SAME frozen trace."""
    spec = StrategySpec.from_json(adapter.spec_json)
    observed = evaluate_restricted_python(adapter, samples)
    reference = evaluate_closed_indicator_cross(spec, samples)
    if observed != reference:
        raise ValueError("restricted Python and Day20 StrategySpec signal parity mismatch")
    return {
        "status":"SIGNAL_PREDICATE_PARITY_ONLY",
        "python_signals_utc": [x.isoformat().replace("+00:00","Z") for x in observed],
        "spec_signals_utc": [x.isoformat().replace("+00:00","Z") for x in reference],
        "signal_count":len(observed),
        "source_sha256":adapter.source_sha256,
        "spec_sha256":adapter.spec_sha256,
        "unrestricted_python_executed":False,
        "external_python_strategy_qualified":False,
        "original_broker_platform_parity":False,
    }
