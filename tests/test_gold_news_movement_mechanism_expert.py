from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest

from aidy.gold_cycle_environment import build_cycle_environment
from aidy.gold_expert_gate_contract import verify_expert_gate_packet
from aidy.gold_movement_investigator import build_gold_movement_investigation
from aidy.gold_news_movement_mechanism_expert import (
    FINNHUB_API_KEY_ENV,
    FinnhubNewsClient,
    build_news_movement_mechanism_expert,
    collapse_duplicate_news,
    news_source_contract,
    normalize_finnhub_market_news,
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
    price = Decimal(4380)
    for index in range(130):
        opened = start + timedelta(minutes=index)
        delta = Decimal("0.05")
        if shock and index >= 125:
            delta = Decimal(4)
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
                    price=Decimal(4300) + Decimal(index),
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


def _volatility() -> dict[str, object]:
    return {
        "mode": "pit",
        "state": "partial",
        "decision_input_allowed": True,
        "retrospective_history_included": False,
        "volatility_state_digest": "v" * 64,
        "realized_volatility": {"state": "known"},
        "jump_continuous": {"state": "continuous_dominant"},
        "vol_of_vol": {"state": "unknown_insufficient_history"},
        "gvz": {"state": "unknown"},
        "iv_minus_rv": {"state": "unknown_missing_iv_or_comparable_rv"},
    }


def _semantic_context(*, event: bool) -> dict[str, object]:
    return {
        "gold": {"quote_context": {"mid": "4401"}},
        "session": {"computed_session_code": "new_york"},
        "event_risk": (
            {
                "evidence_state": "known",
                "timing_state": "inside_high_impact_window",
                "events_in_window": [
                    {
                        "event_type": "cpi",
                        "scheduled_at": AS_OF.isoformat(),
                    }
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


def _gold_state(*, event: bool) -> dict:
    return build_gold_state_engine(
        as_of=AS_OF,
        symbol="XAUUSD",
        candle_rows=_candles(shock=True),
        semantic_context=_semantic_context(event=event),
        price_structure_packet=_price_structure(),
        volatility_state=_volatility(),
    )


def _investigation(*, event: bool) -> dict:
    return build_gold_movement_investigation(
        as_of=AS_OF,
        gold_state=_gold_state(event=event),
        semantic_context=_semantic_context(event=event),
        rates_macro_state={"state": "unknown"},
        event_intelligence_state={"state": "unknown"},
        cme_contract_state={"state": "unknown"},
        volatility_state=_volatility(),
    )


def _environment(*, event: bool) -> dict:
    timing = "inside_high_impact_window" if event else "clear_current_window"
    return build_cycle_environment(
        as_of_utc=AS_OF,
        target_window_start_utc=AS_OF + timedelta(minutes=15),
        session_code="new_york",
        observed_state="bullish",
        gold_state={
            "market_structure": {
                "timeframes": {
                    "M5": {"net_close_direction": "up", "state": "known"},
                    "M15": {"net_close_direction": "up", "state": "known"},
                    "H1": {"net_close_direction": "up", "state": "known"},
                    "H4": {"net_close_direction": "up", "state": "known"},
                    "D1": {"net_close_direction": "up", "state": "known"},
                }
            },
            "move_observation": {
                "five_minute_distribution_state": "extreme_recent_displacement",
                "five_minute_range_state": "extreme_range_expansion",
                "windows": {
                    "5m": {"direction": "up", "return_bps": "10"},
                    "15m": {"direction": "up", "return_bps": "12"},
                    "60m": {"direction": "up", "return_bps": "15"},
                },
            },
            "volatility": {
                "state": "high",
                "jump_continuous": {"state": "continuous_dominant"},
            },
            "scheduled_event_risk": {
                "state": "known",
                "timing_state": timing,
            },
        },
        semantic_context={
            "data_quality": {
                "quote_state": "known",
                "quote_freshness": "fresh",
                "spread_state": "unknown",
            },
            "cross_market": {"series": {}},
        },
        regime={"compound_regime_key": "build18|high"},
    )


def _normalized_news(
    *,
    source: str,
    headline: str,
    summary: str = "",
    provider_id: int = 1,
    seconds_before: int = 60,
    category: str = "general",
) -> list[dict]:
    raw = [
        {
            "id": provider_id,
            "category": category,
            "datetime": int((AS_OF - timedelta(seconds=seconds_before)).timestamp()),
            "headline": headline,
            "source": source,
            "summary": summary,
            "url": f"https://example.test/{provider_id}",
            "related": "",
        }
    ]
    return normalize_finnhub_market_news(
        raw,
        fetched_at_utc=AS_OF,
        as_of_utc=AS_OF,
        category=category,
    )


def _build(
    *,
    event: bool,
    news: list[dict] | None = None,
    narratives: tuple[str, ...] = (),
) -> dict:
    return build_news_movement_mechanism_expert(
        global_environment=_environment(event=event),
        movement_investigation=_investigation(event=event),
        news_observations=news or [],
        narrative_claims=narratives,
    )


def test_build18_scheduled_event_alone_stays_unconfirmed_context() -> None:
    result = _build(event=True)

    assert result["mechanism_resolution"]["state"] == "scheduled_event_context_only"
    assert result["mechanism_resolution"]["cause_known"] is False
    assert result["expert_packet"]["gate_mode"] == "context_only"
    assert result["expert_packet"]["gate_scoreable"] is False
    assert result["directional_authority"] is False
    assert verify_expert_gate_packet(result["expert_packet"])


def test_build18_single_credible_news_story_is_supported_context_not_causality() -> None:
    news = _normalized_news(
        source="Reuters",
        headline="Gold climbs as dollar and Treasury yields retreat",
        summary="Bullion gains as the dollar eases.",
    )
    result = _build(event=False, news=news)
    mechanism = result["mechanism_resolution"]

    assert mechanism["state"] == "supported_context"
    assert mechanism["agreement_state"] == "single_credible_news_source"
    assert mechanism["credible_story_n"] == 1
    assert mechanism["strongest_source_authority"] == "major_wire"
    assert mechanism["cause_known"] is False
    assert mechanism["causal_claim"] is False
    assert mechanism["news_directional_vote_allowed"] is False


def test_build18_duplicate_syndicated_story_cannot_manufacture_confirmation() -> None:
    one = _normalized_news(
        source="Reuters",
        headline="Gold climbs as dollar retreats",
        provider_id=101,
    )[0]
    two = _normalized_news(
        source="Reuters",
        headline="Gold climbs as dollar retreats",
        provider_id=202,
    )[0]
    collapsed = collapse_duplicate_news([one, two])

    assert collapsed["input_story_n"] == 2
    assert collapsed["unique_story_n"] == 1
    assert collapsed["duplicate_story_n"] == 1


def test_build18_unsupported_narrative_is_explicitly_rejected_as_evidence() -> None:
    result = _build(
        event=False,
        narratives=("The move was obviously manipulation.",),
    )
    mechanism = result["mechanism_resolution"]

    assert mechanism["state"] == "unsupported_narrative"
    assert mechanism["unsupported_narratives"]
    assert mechanism["unsupported_narratives_used_as_evidence"] is False
    assert mechanism["cause_known"] is False


def test_build18_unknown_fixture_remains_unknown() -> None:
    result = _build(event=False)
    mechanism = result["mechanism_resolution"]

    assert mechanism["state"] == "unknown"
    assert mechanism["agreement_state"] == "unknown_no_supported_mechanism"
    assert mechanism["cause_known"] is False


def test_build18_credible_source_disagreement_remains_unresolved() -> None:
    news = []
    news.extend(
        _normalized_news(
            source="Reuters",
            headline="Fed signals rate cut debate after policy meeting",
            provider_id=301,
        )
    )
    news.extend(
        _normalized_news(
            source="Associated Press",
            headline="Oil prices surge after supply shock",
            provider_id=302,
        )
    )
    result = _build(event=False, news=news)
    mechanism = result["mechanism_resolution"]

    assert mechanism["state"] == "disagreement_unresolved"
    assert mechanism["agreement_state"] == "credible_news_sources_disagree_unresolved"
    assert mechanism["agreement"]["disagreement_unresolved"] is True
    assert result["expert_packet"]["contradictions"]


def test_build18_scheduled_event_and_news_can_agree_without_claiming_cause() -> None:
    news = _normalized_news(
        source="Reuters",
        headline="Gold moves after CPI inflation report",
        summary="Consumer price data was released.",
        provider_id=401,
    )
    result = _build(event=True, news=news)
    mechanism = result["mechanism_resolution"]

    assert mechanism["state"] == "supported_context"
    assert mechanism["agreement_state"] == "scheduled_event_and_news_agree"
    assert "inflation" in mechanism["agreement"]["agreement_tags"]
    assert mechanism["cause_known"] is False


def test_build18_future_news_is_excluded_from_the_frozen_packet() -> None:
    base = _build(event=False)
    future = {
        "provider": "Finnhub",
        "provider_id": "future",
        "provider_category": "general",
        "story_key": "provider:future",
        "headline": "Gold jumps on future information",
        "summary": "future",
        "source": "Reuters",
        "source_authority": "major_wire",
        "published_at_utc": (AS_OF + timedelta(minutes=2)).isoformat(),
        "first_observed_at_utc": (AS_OF + timedelta(minutes=2)).isoformat(),
        "age_seconds_at_as_of": -120,
        "url": None,
        "related": None,
        "mechanism_tags": ["gold_specific"],
        "gold_relevance_state": "relevant",
        "causal_claim": False,
        "directional_vote": None,
        "future_values_used": False,
    }
    with_future = _build(event=False, news=[future])

    assert base["mechanism_resolution"] == with_future["mechanism_resolution"]
    assert base["expert_packet"]["packet_digest"] == with_future["expert_packet"]["packet_digest"]
    assert with_future["future_values_used"] is False


def test_build18_news_never_becomes_directional_vote() -> None:
    news = _normalized_news(
        source="Reuters",
        headline="Gold surges as dollar drops",
        provider_id=501,
    )
    result = _build(event=False, news=news)
    packet = result["expert_packet"]

    assert packet["gate_mode"] == "context_only"
    assert packet["conclusion"] == "context_only"
    assert packet["internal_conviction"] is None
    assert packet["gate_scoreable"] is False
    assert all(item["role"] == "context_only" for item in packet["subcalculators"])
    assert result["live_money_execution_allowed"] is False


def test_build18_source_contract_is_finnhub_bounded_and_non_directional() -> None:
    contract = news_source_contract()

    assert contract["provider"] == "Finnhub"
    assert contract["secret_env_var"] == FINNHUB_API_KEY_ENV
    assert contract["endpoint"] == "/news"
    assert contract["future_rows_allowed"] is False
    assert contract["duplicate_story_collapse_required"] is True
    assert contract["causal_claim_from_single_headline_allowed"] is False
    assert contract["news_directional_vote_allowed"] is False
    assert contract["live_money_execution_allowed"] is False


def test_build18_finnhub_adapter_normalizes_real_schema_contract() -> None:
    payload = [
        {
            "id": 9001,
            "category": "general",
            "datetime": int((AS_OF - timedelta(minutes=1)).timestamp()),
            "headline": "Gold gains as Treasury yields retreat",
            "source": "Reuters",
            "summary": "The dollar also weakened.",
            "url": "https://example.test/news/9001",
            "related": "",
        }
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/news"
        assert request.url.params["category"] == "general"
        assert request.url.params["token"] == "test-key"
        return httpx.Response(200, json=payload)

    client = FinnhubNewsClient(
        api_key="test-key",
        transport=httpx.MockTransport(handler),
    )
    rows = asyncio.run(client.fetch_market_news(category="general", as_of_utc=AS_OF))

    assert len(rows) == 1
    assert rows[0]["provider"] == "Finnhub"
    assert rows[0]["source_authority"] == "major_wire"
    assert "gold_specific" in rows[0]["mechanism_tags"]
    assert rows[0]["future_values_used"] is False


def test_build18_finnhub_from_env_fails_closed_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(FINNHUB_API_KEY_ENV, raising=False)
    with pytest.raises(ValueError, match="FINNHUB_API_KEY is required"):
        FinnhubNewsClient.from_env()
