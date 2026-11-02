"""Boundary for an independent AIDY selected-year replay.

`replay(selection, data_manifest)` is only the adapter call. A real adapter
must run one frozen StrategySpec on authenticated bid/ask history and must
not read or copy MT5 deals. No such executor is wired. The S040 stub returns
unavailable and cannot produce MATCH.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol

from aidy.goldthinker_factory_reconcile import AidyReplayResult, AidyReplayUnavailable


@dataclass(frozen=True)
class ReplayRequest:
    """What one versioned strategy adapter must bind. Not an MT5 trade list."""

    year: int
    selection_sha256: str
    strategy_source_sha256: str
    adapter_sha256: str
    quote_dataset_sha256: str
    quote_coverage: str
    server_clock: Mapping[str, object]
    starting_capital_usd: str
    lot_size: str
    margin_model: str
    spread_model: str
    commission_model: str
    swap_model: str


class AidySelectedYearReplay(Protocol):
    def replay(
        self, *, selection: Mapping[str, object], data_manifest: Mapping[str, object],
    ) -> AidyReplayResult:
        """Return trades for selection['aidy_year'] only, from the strategy rules."""


class S040SmokeReplay:
    """First intended adapter. S040 has no StrategySpec or EA in this repo yet."""

    adapter_id = "s040_smoke_unavailable"

    def replay(
        self, *, selection: Mapping[str, object], data_manifest: Mapping[str, object],
    ) -> AidyReplayResult:
        raise AidyReplayUnavailable(
            "AIDY_REPLAY_UNAVAILABLE: S040 smoke adapter is a stub and did not read MT5 trades"
        )
