from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from aidy.gold_cycle_memory import (
    CYCLE_NEUTRAL_BAND_BPS,
    GOLD_CYCLE_MEMORY_VERSION,
    GOLD_CYCLE_OUTCOME_VERSION,
    GOLD_CYCLE_VIEW_VERSION,
    build_cycle_view_payload,
)
from aidy.gold_movement_investigator import build_gold_movement_investigation
from aidy.gold_state_engine import build_gold_state_engine
from aidy.gold_toolbox_registry import build_gold_toolbox_manifest

ROOT = Path(__file__).resolve().parents[1]
AS_OF = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)
_SECONDS = {"M1": 60, "M5": 300, "M15": 900, "H1": 3600, "H4": 14400}


def _row(
    *,
    timeframe: str,
    opened: datetime,
    price: Decimal,
    close_delta: Decimal,
) -> dict[str, object]:
    seconds = _SECONDS[timeframe]
    return {
        "load_identity": f"{timeframe}:{opened.isoformat()}",
        "evidence_id": f"e:{timeframe}:{opened.isoformat()}",
        "archive_key": f"gold/{timeframe}/{int(opened.timestamp())}.json",
        "payload_digest": "d" * 64,
        "symbol": "XAUUSD",
        "timeframe": timeframe,
        "open_time_utc": opened,
        "first_observed_at": opened + timedelta(seconds=seconds),
        "open": str(price),
        "high": str(price + max(Decimal("0.8"), close_delta)),
        "low": str(price + min(Decimal("-0.8"), close_delta)),
        "close": str(price + close_delta),
        "source": "twelve_data",
    }


def _candles(direction: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    sign = Decimal(1) if direction == "up" else Decimal(-1)
    start = AS_OF - timedelta(minutes=130)
    price = Decimal("4380")
    for index in range(130):
        delta = sign * Decimal("0.08")
        if index >= 125:
            delta = sign * Decimal("0.50")
        rows.append(
            _row(
                timeframe="M1",
                opened=start + timedelta(minutes=index),
                price=price,
                close_delta=delta,
            )
        )
        price += delta

    for timeframe, bars in (("M5", 8), ("M15", 8), ("H1", 8), ("H4", 8)):
        duration = timedelta(seconds=_SECONDS[timeframe])
        start_tf = AS_OF - duration * bars
        base = Decimal("4300")
        for index in range(bars):
            rows.append(
                _row(
                    timeframe=timeframe,
                    opened=start_tf + duration * index,
                    price=base + sign * Decimal(index),
                    close_delta=sign * Decimal("0.5"),
                )
            )
    return rows


def _state(direction: str) -> tuple[dict, dict, dict]:
    semantic = {
        "gold": {"quote_context": {"mid": "4387"}},
        "session": {"computed_session_code": "london"},
        "event_risk": {"evidence_state": "unknown", "timing_state": "unknown"},
        "cross_market": {"series": {}},
    }
    price_structure = {
        "mode": "pit",
        "pit_eligible": True,
        "future_values_used": False,
        "structure_semantic_digest": "s" * 64,
        "structure": {
            "prior_periods": {},
            "asia_overnight_range": {},
            "opening_ranges": {},
            "session_extremes": {},
            "prior_day_breakout": {"state": "inside"},
            "swing_extreme_penetration_with_reversion": {},
            "wick_footprint": {},
        },
    }
    volatility = {
        "mode": "pit",
        "state": "partial",
        "decision_input_allowed": True,
        "retrospective_history_included": False,
        "volatility_state_digest": "v" * 64,
        "realized_volatility": {"state": "known"},
        "jump_continuous": {"state": "continuous_dominant"},
        "vol_of_vol": {"state": "unknown"},
        "gvz": {"state": "unknown"},
        "iv_minus_rv": {"state": "unknown"},
    }
    gold = build_gold_state_engine(
        as_of=AS_OF,
        symbol="XAUUSD",
        candle_rows=_candles(direction),
        semantic_context=semantic,
        price_structure_packet=price_structure,
        volatility_state=volatility,
    )
    investigation = build_gold_movement_investigation(
        as_of=AS_OF,
        gold_state=gold,
        semantic_context=semantic,
        volatility_state=volatility,
    )
    toolbox = build_gold_toolbox_manifest(
        gold_state=gold,
        semantic_context=semantic,
        live_source_availability={
            "market_structure": "derived_live",
            "price_liquidity_structure": "derived_live_from_admitted_twelve_candles",
            "rates_macro_vintages": "unknown_no_operational_day28_vintage_feed",
            "tiered_macro_events": "unknown_no_operational_day29_schedule_feed",
            "cme_contract_state": "unknown_no_operational_day30_bulletin_feed",
            "gvz_implied_volatility": "unknown_no_operational_day31_gvz_feed",
            "breaking_news_event_search": "known_capability_not_live_connected",
            "intraday_cross_asset_reaction": "known_capability_not_live_connected",
        },
    )
    return gold, investigation, toolbox


def test_cycle_view_is_reasoned_auditable_and_non_executable() -> None:
    gold, investigation, toolbox = _state("up")
    payload = build_cycle_view_payload(
        as_of=AS_OF,
        window_start=AS_OF + timedelta(minutes=15),
        session_code="london",
        gold_state=gold,
        movement_investigation=investigation,
        toolbox_manifest=toolbox,
        prior_observed_states=["neutral", "bullish"],
        analogue_summary={
            "sample_n": 0,
            "next_state_distribution": {"bullish": 0, "bearish": 0, "neutral": 0},
            "descriptive_only": True,
            "usable_for_live_edge_claim": False,
        },
    )

    assert payload["view_version"] == GOLD_CYCLE_VIEW_VERSION
    assert payload["view_direction"] in {"bullish", "bearish", "neutral", "unknown"}
    assert payload["reasoning_summary"]
    assert payload["all_directional_reasons"]
    assert payload["toolbox_considered"]
    assert "gold_cycle_15m_memory" in payload["toolbox_considered"]
    assert payload["toolbox_manifest_digest"] == toolbox["manifest_digest"]
    assert payload["research_only"] is True
    assert payload["predictive_edge_claimed"] is False
    assert payload["live_money_execution_allowed"] is False
    assert payload["future_values_used"] is False
    assert len(payload["view_digest"]) == 64


def test_cycle_view_keeps_contradiction_and_unknown_evidence_visible() -> None:
    gold, investigation, toolbox = _state("down")
    payload = build_cycle_view_payload(
        as_of=AS_OF,
        window_start=AS_OF + timedelta(minutes=15),
        session_code="london",
        gold_state=gold,
        movement_investigation=investigation,
        toolbox_manifest=toolbox,
        prior_observed_states=["bullish", "neutral", "bearish"],
        analogue_summary={
            "sample_n": 25,
            "next_state_distribution": {"bullish": 16, "bearish": 5, "neutral": 4},
            "descriptive_only": True,
            "usable_for_live_edge_claim": False,
        },
    )

    assert isinstance(payload["supporting_reasons"], list)
    assert isinstance(payload["contradicting_reasons"], list)
    assert isinstance(payload["unavailable_evidence"], list)
    assert ">" in payload["cycle_signature"]
    assert Decimal(payload["view_confidence"]) <= Decimal(1)
    assert Decimal(payload["view_confidence"]) >= Decimal(0)


def test_cycle_schema_separates_frozen_view_from_post_outcome_reasoning_review() -> None:
    migration = (
        ROOT / "migrations" / "d1" / "0023_gold_cycle_learning.sql"
    ).read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS aidy_gold_cycle_views" in migration
    assert "CREATE TABLE IF NOT EXISTS aidy_gold_cycle_outcomes" in migration
    assert "CREATE TABLE IF NOT EXISTS aidy_gold_cycle_historical" in migration
    assert "reasoning_summary TEXT NOT NULL" in migration
    assert "supporting_reasons_json" in migration
    assert "contradicting_reasons_json" in migration
    assert "unavailable_evidence_json" in migration
    assert "reasoning_review_json" in migration
    assert "future_values_used INTEGER NOT NULL DEFAULT 0" in migration
    assert "pit_eligible INTEGER NOT NULL DEFAULT 0" in migration


def test_cycle_runtime_is_wired_to_cron_provider_context_and_deploy_gate() -> None:
    wrapper = (ROOT / "src" / "provider_entry.py").read_text(encoding="utf-8")
    provider = (ROOT / "src" / "aidy" / "provider_context_api.py").read_text(
        encoding="utf-8"
    )
    deploy = (ROOT / "scripts" / "cloudflare_native_deploy.sh").read_text(
        encoding="utf-8"
    )
    assert "sync_gold_cycle_memory" in wrapper
    assert "gold_cycle_memory_version" in wrapper
    assert 'gold_state["cycle_memory"]' in provider
    assert "D1GoldCycleMemoryStore" in provider
    assert "gold_cycle_environment.py" in deploy
    assert "gold_cycle_memory.py" in deploy
    assert "gold_marker_brain.py" in deploy
    assert "test_gold_cycle_environment.py" in deploy
    assert "test_gold_cycle_memory.py" in deploy
    assert "test_gold_marker_brain.py" in deploy


def test_cycle_versions_and_neutral_band_are_explicit() -> None:
    assert GOLD_CYCLE_MEMORY_VERSION == "aidy_gold_cycle_memory_v3"
    assert GOLD_CYCLE_VIEW_VERSION == "aidy_gold_cycle_view_v1"
    assert GOLD_CYCLE_OUTCOME_VERSION == "aidy_gold_cycle_outcome_v1"
    assert CYCLE_NEUTRAL_BAND_BPS > 0
