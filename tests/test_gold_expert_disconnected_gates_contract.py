"""The five stubbed experts, declared rather than silently absent.

`gold_expert_shadow` holds `_DISCONNECTED_CONTEXT_GATES`: five fully built, fully
tested experts whose real builders the live shadow loop never calls. It emits
`_build_unknown_with_history(...)` for each instead. Nothing flagged that, so five
experts sat inert in production and the only way to notice was to read the loop.

These tests turn that hidden debt into declared debt. They do not connect anything -
connecting an expert is a data and point-in-time question, not a test question. They
pin the invariant that makes stubbing *safe*, so the day someone stubs an expert that
carries direction, CI says so instead of the ensemble quietly losing a vote.

Written against the 2026-09-23 measurement, which corrected an earlier belief: all nine
context experts declare `gate_mode="context_only"`, so feeding these five their data
adds context and not one directional vote. That is why the family deadlock needs a new
directional expert rather than this list getting shorter.
"""

from __future__ import annotations

import ast
from pathlib import Path

from aidy.gold_expert_shadow import (
    _DISCONNECTED_CONTEXT_GATES,
    EXPECTED_GATES,
)

_SRC = Path(__file__).resolve().parents[1] / "src" / "aidy"

#: Gate id -> the module that owns the expert. Spelled out so that adding a gate to the
#: disconnected set without deciding what owns it fails here.
_OWNING_MODULE = {
    "macro_event_expert": "gold_macro_event_expert.py",
    "rates_usd_cross_asset_expert": "gold_rates_usd_cross_asset_expert.py",
    "futures_microstructure_expert": "gold_futures_microstructure_expert.py",
    "news_movement_mechanism_expert": "gold_news_movement_mechanism_expert.py",
    "analogue_episode_expert": "gold_analogue_episode_expert.py",
}


def _declares_context_only(module_name: str) -> bool:
    """True when the module's *code* passes gate_mode="context_only".

    Parsed rather than grepped: a docstring or a comment saying "context_only" must not
    be able to satisfy a contract about what the expert actually emits.
    """
    tree = ast.parse((_SRC / module_name).read_text())
    return any(
        isinstance(node, ast.keyword)
        and node.arg == "gate_mode"
        and isinstance(node.value, ast.Constant)
        and node.value.value == "context_only"
        for node in ast.walk(tree)
    )


def test_the_disconnected_set_is_exactly_the_five_known_stubs() -> None:
    """Pinned so that disconnecting a sixth expert - or reconnecting one of these -
    is a deliberate change a reviewer sees, not a one-line edit nobody notices."""
    assert set(_DISCONNECTED_CONTEXT_GATES) == set(_OWNING_MODULE)


def test_every_disconnected_expert_is_context_only() -> None:
    """The invariant that makes stubbing safe. A context_only gate contributes zero
    directional mass, so stubbing it costs context and no votes. Stub a *directional*
    expert and the ensemble silently loses a vote it needs to reach a decision - so
    that case must fail here rather than in a month of unexplained abstentions."""
    for gate_id, module_name in sorted(_OWNING_MODULE.items()):
        assert _declares_context_only(module_name), (
            f"{gate_id} is disconnected but does not declare "
            f'gate_mode="context_only" - stubbing it loses directional mass'
        )


def test_disconnected_gates_are_still_expected_in_the_packet() -> None:
    """Stubbed is not the same as gone. Each one still has to appear in the packet as a
    known gate emitting `unknown`, because a gate that vanishes from EXPECTED_GATES
    stops being counted, and an expert nobody counts is an expert nobody misses."""
    for gate_id in sorted(_DISCONNECTED_CONTEXT_GATES):
        assert gate_id in EXPECTED_GATES


def test_reconnecting_an_expert_requires_touching_this_list() -> None:
    """The shadow loop reads the dict directly, so the dict is the switch. This asserts
    the coupling rather than the loop's wording: the loop may be rewritten, but while it
    reads this mapping, emptying the mapping is what reconnects an expert."""
    loop = (_SRC / "gold_expert_shadow.py").read_text()
    assert "_DISCONNECTED_CONTEXT_GATES" in loop
    assert loop.count("_DISCONNECTED_CONTEXT_GATES") >= 2  # defined, and read
