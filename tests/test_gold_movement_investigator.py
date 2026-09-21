from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from aidy.gold_movement_investigator import (
    GOLD_MOVEMENT_INVESTIGATOR_VERSION,
    GOLD_MOVEMENT_LEARNING_CARD_VERSION,
    build_gold_movement_investigation,
    build_gold_movement_learning_card,
    verify_gold_movement_investigation,
    verify_gold_movement_learning_card,
)
from aidy.gold_state_engine import build_gold_state_engine


AS_OF = datetime(2026, 9, 18, 16, 0, tzinfo=UTC)
_SECONDS = {"M1": 60, "M5": 300, "M15": 900, "H1": 3600, "H4": 14400}


def _row(
    *,
    timeframe: str,
    opened: datetime,
    price: Decimal,
    close_delta: Decimal = Decimal("0.2"),
) -> dict[str, object]:
    seconds = _SECONDS[timeframe]
    return {
        "load_identity": f"{timeframe}:{opened.isoformat()}",
        "evidence_id": f"e:{timeframe}:{opened.isoformat()}",
        "archive_key": f"gold/{timeframe}/{int(opened.timestamp())}.json",
        "payload_digest": "c" * 64,
        "symbol": "XAUUSD",
        "timeframe": timeframe,
        "open_time_utc": opened,
        "first_observed_at": opened + timedelta(seconds=seconds),
        "open": str(price),
        "high": str(price + max(Decimal("0.6"), close_delta)),
        "low": str(price + min(Decimal("-0.4"), close_delta)),
        "close": str(price + close_delta),
        "source": "twelve_data",
    }


def _candles(*, shock: bool) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    start = AS_OF - timedelta(minutes=130)
    price = Decimal("4380")
    for index in range(130):
        opened = start + timedelta(minutes=index)
        delta = Decimal("0.05")
        if shock and index >= 125:
            delta = Decimal("4")
        rows.append(_row(timeframe="M1", opened=opened, price=price, close_delta=delta))
        price += delta

    for timeframe, bars in (("M5", 8), ("M15", 8), ("H1", 8), ("H4", 8)):
        duration = timedelta(seconds=_SECONDS[timeframe])
        start_tf = AS_OF - duration * bars
        for index in range(bars):
            rows.append(
                _row(
                    timeframe=timeframe,
                    opened=start_tf + duration * index,
                    price=Decimal("4300") + Decimal(index),
                    close_delta=Decimal("0.5"),
                )
            )
    return rows


def _price_structure() -> dict[str, object]:
    return {
        "mode": "pit",
        "pit_eligible": True,
        "future_values_used": False,
        "structure_semantic_digest": "s" * 64,
        "structure": {
            "prior_periods": {
                "prior_day": {
                    "state": "known",
                    "high": "4390",
                    "low": "4350",
                    "close": "4370",
                }
            },
            "asia_overnight_range": {"state": "known", "high": "4385", "low": "4360"},
            "opening_ranges": {},
            "session_extremes": {},
            "prior_day_breakout": {"state": "inside_prior_day_range"},
            "swing_extreme_penetration_with_reversion": {},
            "wick_footprint": {"state": "known"},
        },
    }


def _volatility(*, jump_state: str = "continuous_dominant") -> dict[str, object]:
    return {
        "mode": "pit",
        "state": "partial",
        "decision_input_allowed": True,
        "retrospective_history_included": False,
        "volatility_state_digest": "v" * 64,
        "realized_volatility": {"state": "known"},
        "jump_continuous": {"state": jump_state},
        "vol_of_vol": {"state": "unknown_insufficient_history"},
        "gvz": {"state": "unknown"},
        "iv_minus_rv": {"state": "unknown_missing_iv_or_comparable_rv"},
    }


def _context(*, event: bool = False) -> dict[str, object]:
    return {
        "gold": {"quote_context": {"mid": "4401"}},
        "session": {"computed_session_code": "new_york"},
        "event_risk": (
            {
                "evidence_state": "known",
                "timing_state": "inside_high_impact_window",
                "events_in_window": [
                    {"event_type": "cpi", "scheduled_at": AS_OF.isoformat()}
                ],
            }
            if event
            else {
                "evidence_state": "known",
                "timing_state": "clear_current_window",
                "events_in_window": [],
            }
        ),
        "cross_market": {
            "series": {
                "DGS10": {
                    "state": "known",
                    "fact": {"value": "4.1"},
                }
            }
        },
    }


def _gold_state(*, shock: bool, event: bool = False, jump: str = "continuous_dominant") -> dict:
    return build_gold_state_engine(
        as_of=AS_OF,
        symbol="XAUUSD",
        candle_rows=_candles(shock=shock),
        semantic_context=_context(event=event),
        price_structure_packet=_price_structure(),
        volatility_state=_volatility(jump_state=jump),
    )


def test_normal_market_does_not_trigger_causal_investigation() -> None:
    result = build_gold_movement_investigation(
        as_of=AS_OF,
        gold_state=_gold_state(shock=False),
        semantic_context=_context(),
        volatility_state=_volatility(),
    )
    assert result["investigator_version"] == GOLD_MOVEMENT_INVESTIGATOR_VERSION
    assert result["state"] == "not_triggered"
    assert result["investigation_required"] is False
    assert result["attribution_state"] == "not_applicable"
    assert verify_gold_movement_investigation(result)


def test_spike_triggers_investigation_but_event_timing_alone_is_not_called_the_cause() -> None:
    result = build_gold_movement_investigation(
        as_of=AS_OF,
        gold_state=_gold_state(shock=True, event=True),
        semantic_context=_context(event=True),
        rates_macro_state={"state": "unknown"},
        event_intelligence_state={"state": "unknown"},
        cme_contract_state={"state": "unknown"},
        volatility_state=_volatility(),
    )
    assert result["state"] == "investigated"
    assert "abnormal_5m_displacement" in result["triggered_by"]
    assert result["attribution_state"] == "plausible_unconfirmed"
    assert result["cause_known"] is False
    assert result["leading_mechanism"]["mechanism"] == "scheduled_macro_event_window"
    assert result["leading_mechanism"]["causal_claim"] is False
    assert "macro_actual_surprise" in result["required_follow_up_tools"]
    assert "intraday_cross_asset_reaction" in result["required_follow_up_tools"]
    assert "breaking_news_event_search" in result["required_follow_up_tools"]
    assert verify_gold_movement_investigation(result)


def test_qualified_release_surprise_upgrades_mechanism_support_without_claiming_proof() -> None:
    event_state = {
        "timing_state": "inside_tiered_window",
        "events_in_window": [{"event_class": "CPI", "scheduled_at": AS_OF.isoformat()}],
        "surprise_state": {
            "surprise_state": "known",
            "event_class": "CPI",
            "surprise_value": "0.2",
            "first_print_state": "known",
            "consensus_state": "known",
        },
    }
    result = build_gold_movement_investigation(
        as_of=AS_OF,
        gold_state=_gold_state(shock=True, event=True),
        semantic_context=_context(event=True),
        event_intelligence_state=event_state,
        volatility_state=_volatility(),
    )
    assert result["attribution_state"] == "supported_mechanism"
    assert result["leading_mechanism"]["mechanism"] == "observed_macro_release_surprise"
    assert result["leading_mechanism"]["confidence"] == "0.75"
    assert result["cause_known"] is False
    assert result["predictive_edge_claimed"] is False


def test_jump_dominant_move_is_a_supported_market_mechanism_not_a_narrative_cause() -> None:
    result = build_gold_movement_investigation(
        as_of=AS_OF,
        gold_state=_gold_state(shock=True, jump="jump_dominant"),
        semantic_context=_context(),
        volatility_state=_volatility(jump_state="jump_dominant"),
    )
    mechanisms = {
        item["mechanism"]: item for item in result["mechanism_candidates"]
    }
    assert mechanisms["jump_dominant_market_reaction"]["support_level"] == "supported_mechanism"
    assert mechanisms["jump_dominant_market_reaction"]["causal_claim"] is False


def test_movement_learning_card_records_continuation_only_after_future_path_is_available() -> None:
    investigation = build_gold_movement_investigation(
        as_of=AS_OF,
        gold_state=_gold_state(shock=True),
        semantic_context=_context(),
        volatility_state=_volatility(),
    )
    card = build_gold_movement_learning_card(
        investigation=investigation,
        available_at=AS_OF + timedelta(minutes=61),
        forward_windows={
            "5m": {"return_bps": "3"},
            "15m": {"return_bps": "8"},
            "30m": {"return_bps": "12"},
            "60m": {"return_bps": "16"},
        },
    )
    assert card["learning_card_version"] == GOLD_MOVEMENT_LEARNING_CARD_VERSION
    assert card["path_class"] == "continuation"
    assert card["same_episode_retrieval_allowed"] is False
    assert card["predictive_rule_created"] is False
    assert verify_gold_movement_learning_card(card)


def test_learning_card_can_record_reversal_without_rewriting_original_attribution() -> None:
    investigation = build_gold_movement_investigation(
        as_of=AS_OF,
        gold_state=_gold_state(shock=True),
        semantic_context=_context(),
        volatility_state=_volatility(),
    )
    original_digest = investigation["investigation_digest"]
    card = build_gold_movement_learning_card(
        investigation=investigation,
        available_at=AS_OF + timedelta(minutes=61),
        forward_windows={
            "15m": {"return_bps": "-2"},
            "30m": {"return_bps": "-7"},
            "60m": {"return_bps": "-12"},
        },
    )
    assert card["path_class"] == "reversal"
    assert card["investigation_digest"] == original_digest
    assert investigation["investigation_digest"] == original_digest


def test_learning_cannot_use_future_path_at_or_before_trigger_time() -> None:
    investigation = build_gold_movement_investigation(
        as_of=AS_OF,
        gold_state=_gold_state(shock=True),
        semantic_context=_context(),
        volatility_state=_volatility(),
    )
    with pytest.raises(ValueError, match="cannot become available"):
        build_gold_movement_learning_card(
            investigation=investigation,
            available_at=AS_OF,
            forward_windows={"60m": {"return_bps": "10"}},
        )


def test_tampering_breaks_investigation_digest() -> None:
    result = build_gold_movement_investigation(
        as_of=AS_OF,
        gold_state=_gold_state(shock=True),
        semantic_context=_context(),
        volatility_state=_volatility(),
    )
    result["attribution_state"] = "supported_mechanism"
    assert not verify_gold_movement_investigation(result)
