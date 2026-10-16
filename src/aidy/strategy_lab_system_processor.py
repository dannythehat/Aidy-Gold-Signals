"""Read-only multi-system gold research processor.

Two explicitly supported rule families share the same costed next-open
execution/accounting engine. Arbitrary user code or unreviewed catalogue
systems are NOT silently mapped to a rule family.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from typing import Any

import pandas as pd

from aidy.strategy_lab_s010_backtest import (
    BASE,
    STRESS,
    Costs,
    derive_signals,
    simulate,
)

S010 = "S010"
DONCHIAN = "LAB_DONCHIAN_20_10"
SUPPORTED = (S010, DONCHIAN)
SCHEMA = "aidy.strategy_lab.multi_system_h1_research.v1"


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()).hexdigest()


def donchian_closed_bar_signals(bars: pd.DataFrame) -> tuple[int, ...]:
    """Long breakout over PRIOR 20 highs; flat on PRIOR 10 lows.

    Explicitly an AIDY laboratory system, NOT an independently sourced S040,
    S005, or any other vendor's original strategy.
    """
    x = derive_signals(bars)
    high_prior = x["high"].rolling(20).max().shift(1)
    low_prior = x["low"].rolling(10).min().shift(1)
    enters = x["close"] > high_prior
    exits = x["close"] < low_prior
    if (enters & exits).any():
        raise ValueError("Contradictory Donchian signals")
    out = []
    for i in range(len(x)):
        if i < 20:
            out.append(0)
        elif bool(enters.iloc[i]):
            out.append(1)
        elif bool(exits.iloc[i]):
            out.append(-1)
        else:
            out.append(0)
    return tuple(out)


def process_systems(
    bars: pd.DataFrame,
    *,
    requested: Sequence[str] = SUPPORTED,
    source_identity: str,
) -> dict:
    """Return two genuine price-replay results given independently fetched bars.

    Caller must separately authenticate the market provenance/rights. This
    routine checks bar chronology, rule identity, one USD10k account per system,
    source fingerprint, and separate results. It does not connect an account.
    """
    if (not isinstance(source_identity, str) or len(source_identity) != 64
            or any(c not in "0123456789abcdef" for c in source_identity)):
        raise ValueError("Frozen historical input SHA256 required")
    if (not isinstance(requested, (tuple, list))
            or not requested or len(requested) > len(SUPPORTED)
            or len(set(requested)) != len(requested)
            or any(system not in SUPPORTED for system in requested)):
        raise ValueError("Unsupported or duplicate strategy adapter")
    x = derive_signals(bars)
    if len(x) < 200:
        raise ValueError("Insufficient complete H1 source bars")
    if x["open_time_utc"].dt.strftime("%Y").nunique() != 1:
        raise ValueError("Mixed calendar years require independent runs")
    signals = donchian_closed_bar_signals(bars) if DONCHIAN in requested else ()
    models = {}
    for system in requested:
        override = signals if system == DONCHIAN else None
        leverage = 1.0 if system == DONCHIAN else 3.28
        base = simulate(
            bars, leverage, BASE, verified_signal_override=override
        )
        stress = simulate(
            bars, leverage, STRESS, verified_signal_override=override
        )
        if (base["bars"] != len(x) or stress["bars"] != len(x)
                or base["closed_trades"] != len(base["trades"])
                or stress["closed_trades"] != len(stress["trades"])
                or base["initial_usd"] != 10000.0
                or stress["initial_usd"] != 10000.0):
            raise ValueError("Incomplete independent model ledger")
        models[system] = {
            "strategy_id": system,
            "source_category": (
                "PUBLISHED_SOURCE_REPRODUCTION_WITH_LIMITATIONS"
                if system == S010 else "LABORATORY_DEFINED_NOT_CATALOGUE"
            ),
            "rules": (
                "SMA12/34 RSI14 long-only original next-open" if system == S010
                else "H1 close > previous 20-bar high; exit on close below "
                     "previous 10-bar low; next H1 open; unlevered"
            ),
            "market_data_sha256": source_identity,
            "base": base,
            "stress": stress,
            "historical_broker_fills_verified": False,
            "customer_strategy_source_parity_verified": False,
            "research_only": True,
            "paper_or_live_orders": 0,
        }
    packet = {
        "schema": SCHEMA,
        "status": "RESEARCH_MODELS_PROCESSED",
        "market": "XAUUSD",
        "source_basis": "RETROSPECTIVE_HISTDATA_H1_BID_FROM_NATIVE_M1",
        "market_data_sha256": source_identity,
        "source_rows": len(x),
        "model_count": len(models),
        "models": models,
        "broker_financing_margin_and_actual_ask_verified": False,
        "research_not_a_production_or_customer_subscription_gate": True,
    }
    packet["sha256"] = _digest(packet)
    return packet
