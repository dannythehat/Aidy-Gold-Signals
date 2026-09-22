"""AIDY must never be able to affect Super Signals trading, Telegram, app or website.

AIDY and Super Signals were entangled once before and had to be untangled after AIDY
work interrupted real trading time. The separation currently holds by construction, but
nothing pinned it, so the next change to the Worker entry could quietly reintroduce the
coupling. These tests make the boundary explicit and enforced.

The boundary has four parts:

1. The request path Super Signals calls (``Default.fetch`` -> ``/provider/context``)
   must do no learning-loop work, so AIDY telemetry can never add latency to, or fail,
   a provider-context read.
2. Health and shadow writes must never raise, so a telemetry fault cannot take down
   market capture.
3. AIDY owns exactly one datastore binding and must never name a Super Signals table.
4. AIDY's own Telegram publisher must stay out of every deployed entry path.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
PROVIDER_ENTRY = SRC / "provider_entry.py"

#: Work that belongs to the learning loop and must stay off the request path.
LOOP_WORK = (
    "_sync_gold_expert_shadow_best_effort",
    "_append_shadow_health_history",
    "_activate_gold_expert_shadow_best_effort",
    "_sync_gold_cycle_memory_best_effort",
    "_sync_gold_movement_memory_best_effort",
    "_sync_episode_memory_best_effort",
)

#: Super Signals owns these. AIDY may never read or write them.
SUPER_SIGNALS_TABLES = (
    "broker_deals",
    "mt5_accounts",
    "performance_account_snapshots",
    "performance_trade_outcomes",
    "performance_reporting_overrides",
    "user_trading_controls",
)


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text())


def _function(tree: ast.Module, name: str) -> ast.AsyncFunctionDef | ast.FunctionDef:
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
            and node.name == name
        ):
            return node
    raise AssertionError(f"{name} not found")


def _called_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for item in ast.walk(node):
        if not isinstance(item, ast.Call):
            continue
        func = item.func
        if isinstance(func, ast.Name):
            names.add(func.id)
        elif isinstance(func, ast.Attribute):
            names.add(func.attr)
    return names


def test_the_super_signals_request_path_does_no_learning_loop_work() -> None:
    """Default.fetch serves /provider/context. A shadow sync or health append there
    would put AIDY's learning loop inside Super Signals' latency and failure budget."""
    called = _called_names(_function(_tree(PROVIDER_ENTRY), "fetch"))
    for name in LOOP_WORK:
        assert name not in called, f"fetch must not invoke {name}"


def test_loop_work_runs_only_from_the_scheduled_and_queue_handlers() -> None:
    """The shadow sync belongs to the cron, not to a request."""
    tree = _tree(PROVIDER_ENTRY)
    for handler in ("scheduled", "queue"):
        assert "_sync_gold_expert_shadow_best_effort" in _called_names(
            _function(tree, handler)
        ), f"{handler} should drive the shadow sync"


def test_health_history_can_never_raise_into_market_capture() -> None:
    """Telemetry must not be able to fail a capture cycle. The append is required to
    catch every exception and to re-raise none of them."""
    node = _function(_tree(PROVIDER_ENTRY), "_append_shadow_health_history")

    handlers = [
        handler
        for item in ast.walk(node)
        if isinstance(item, ast.Try)
        for handler in item.handlers
    ]
    assert handlers, "the health append must wrap its work in try/except"
    catches_everything = any(
        handler.type is None
        or (isinstance(handler.type, ast.Name) and handler.type.id == "Exception")
        for handler in handlers
    )
    assert catches_everything, "the health append must catch Exception"

    reraises = [item for item in ast.walk(node) if isinstance(item, ast.Raise)]
    assert not reraises, "the health append must never raise"


def test_aidy_binds_exactly_one_datastore() -> None:
    """A second binding is how an AIDY change reaches a Super Signals database."""
    bindings = {
        node.attr
        for node in ast.walk(_tree(PROVIDER_ENTRY))
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "env"
        and node.attr.isupper()
    }
    assert bindings == {"AIDY_OPS"}, f"unexpected Worker bindings: {sorted(bindings)}"


def test_no_super_signals_table_is_named_anywhere_in_aidy_source() -> None:
    offenders: list[str] = []
    for path in SRC.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        text = path.read_text().lower()
        for table in SUPER_SIGNALS_TABLES:
            if table in text:
                offenders.append(f"{path.name}:{table}")
    assert not offenders, f"AIDY references Super Signals tables: {offenders}"


def test_aidy_telegram_publisher_is_not_wired_into_any_deployed_entry() -> None:
    """AIDY has its own Telegram publisher. Members' Telegram is published by Super
    Signals, so AIDY must not be able to post from a deployed Worker entry."""
    for entry in ("provider_entry.py", "entry.py"):
        path = SRC / entry
        if not path.exists():
            continue
        imported = {
            alias.name
            for node in ast.walk(_tree(path))
            if isinstance(node, ast.Import | ast.ImportFrom)
            for alias in node.names
        } | {
            node.module or ""
            for node in ast.walk(_tree(path))
            if isinstance(node, ast.ImportFrom)
        }
        assert not any("telegram" in name.lower() for name in imported), (
            f"{entry} must not import a Telegram publisher"
        )
