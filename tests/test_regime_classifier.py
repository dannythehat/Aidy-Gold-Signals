from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from aidy.context_packet import build_context_packet, compute_context_hash
from aidy.feature_engine import build_feature_packet
from aidy.regime_classifier import (
    REGIME_DEFINITION_VERSION,
    classify_gold_regime,
    classify_trend_structure,
    classify_volatility_band,
    regime_distribution,
    verify_regime_digest,
)

AS_OF = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
_STEP_SECONDS = {"M15": 900, "H1": 3600, "H4": 14400}


def _candles(
    timeframe: str,
    direction: str,
    *,
    range_size: float = 4.0,
) -> list[dict[str, object]]:
    step_seconds = _STEP_SECONDS[timeframe]
    rows: list[dict[str, object]] = []
    for index in range(21):
        open_time = AS_OF - timedelta(seconds=step_seconds * (21 - index))
        if direction == "bullish":
            close = 2000.0 + index
            open_price = close - 0.2
        elif direction == "bearish":
            close = 2020.0 - index
            open_price = close + 0.2
        elif direction == "flat":
            close = 2000.0
            open_price = close
        else:
            raise ValueError(direction)
        half_range = range_size / 2
        rows.append(
            {
                "source": "fixture",
                "symbol": "XAUUSD",
                "timeframe": timeframe,
                "open_time_utc": open_time,
                "first_observed_at": open_time,
                "open": open_price,
                "high": max(open_price, close) + half_range,
                "low": min(open_price, close) - half_range,
                "close": close,
                "load_identity": f"{timeframe}-{index}",
            }
        )
    return rows


def _feature_packet(
    *,
    directions: dict[str, str] | None = None,
    snapshot: dict[str, object] | None = None,
) -> dict[str, object]:
    rows: list[dict[str, object]] = []
    for timeframe, direction in (directions or {}).items():
        range_size = 6.0 if timeframe == "H1" else 4.0
        rows.extend(_candles(timeframe, direction, range_size=range_size))
    return build_feature_packet(
        as_of=AS_OF,
        symbol="XAUUSD",
        candle_rows=rows,
        mode="pit",
        snapshot=snapshot,
    )


def _event(minutes_from_as_of: int) -> dict[str, object]:
    scheduled = AS_OF + timedelta(minutes=minutes_from_as_of)
    return {
        "source": "bls_calendar",
        "external_id": "cpi-fixture",
        "event_type": "macro_schedule",
        "first_observed_at": AS_OF - timedelta(days=5),
        "published_at": None,
        "revision_index": 1,
        "headline": "Consumer Price Index",
        "structured_data": {
            "phase": "scheduled",
            "event_class": "cpi",
            "scheduled_at": scheduled.isoformat(),
            "source_url": "https://www.bls.gov/schedule/",
        },
        "load_identity": "cpi-fixture-1",
        "evidence_id": "event-cpi-fixture-1",
        "archive_key": "events/cpi-fixture/1.json",
        "payload_digest": "digest-cpi-fixture-1",
    }


def _context(
    *,
    feature: dict[str, object] | None = None,
    events: list[dict[str, object]] | None = None,
    macro_state: str = "known",
) -> dict[str, object]:
    return build_context_packet(
        as_of=AS_OF,
        symbol="XAUUSD",
        feature_packet=feature or _feature_packet(),
        event_rows=events or [],
        macro_evidence_state=macro_state,
        cross_market_rows=[],
    )


def test_trend_structure_rules_are_conservative_and_null_aware() -> None:
    assert classify_trend_structure({"M15": "bullish"}) == "unknown"
    assert (
        classify_trend_structure({"M15": "bullish", "H1": "bullish", "H4": "flat"})
        == "bullish_trend"
    )
    assert (
        classify_trend_structure({"M15": "bearish", "H1": "bearish", "H4": "flat"})
        == "bearish_trend"
    )
    assert classify_trend_structure({"M15": "flat", "H1": "flat"}) == "range"
    assert (
        classify_trend_structure({"M15": "bullish", "H1": "bearish", "H4": "flat"})
        == "mixed"
    )
    assert (
        classify_trend_structure({"M15": "bullish", "H1": "bullish", "H4": "bearish"})
        == "mixed"
    )


def test_volatility_band_exact_boundaries_are_versioned_and_deterministic() -> None:
    assert classify_volatility_band(None) == "unknown"
    assert classify_volatility_band("19.999999") == "low"
    assert classify_volatility_band("20") == "normal"
    assert classify_volatility_band("49.999999") == "normal"
    assert classify_volatility_band("50") == "high"
    with pytest.raises(ValueError, match="non-negative"):
        classify_volatility_band("-0.1")


def test_integrated_regime_is_explainable_and_has_no_hindsight_labels() -> None:
    feature = _feature_packet(
        directions={"M15": "bullish", "H1": "bullish", "H4": "flat"}
    )
    regime = classify_gold_regime(_context(feature=feature, events=[_event(30)]))

    assert regime["regime_definition_version"] == REGIME_DEFINITION_VERSION
    assert regime["labels"]["trend_structure"] == "bullish_trend"
    assert regime["labels"]["volatility_band"] == "normal"
    assert regime["labels"]["session"] == "london_new_york_overlap"
    assert regime["labels"]["event_timing"] == "inside_high_impact_window"
    assert regime["labels"]["quote_spread_condition"] == "unknown"
    assert regime["hindsight_outcomes_included"] is False
    assert regime["causal_claims_included"] is False
    assert verify_regime_digest(regime) is True
    assert regime["rule_evidence"]["trend_structure"]["directions"] == {
        "M15": "bullish",
        "H1": "bullish",
        "H4": "flat",
    }
    forbidden_tokens = {"profit", "loss", "win", "winner", "loser", "future", "outcome"}
    for value in regime["labels"].values():
        tokens = set(str(value).lower().split("_"))
        assert tokens.isdisjoint(forbidden_tokens)


def test_missing_context_remains_unknown_instead_of_becoming_a_regime_guess() -> None:
    regime = classify_gold_regime(_context(macro_state="unknown"))
    assert regime["labels"]["trend_structure"] == "unknown"
    assert regime["labels"]["volatility_band"] == "unknown"
    assert regime["labels"]["quote_spread_condition"] == "unknown"
    assert regime["labels"]["event_timing"] == "unknown"
    assert set(regime["unknown_labels"]) == {
        "trend_structure",
        "volatility_band",
        "quote_spread_condition",
        "event_timing",
    }
    assert regime["all_labels_known"] is False


def test_quote_and_spread_condition_preserves_supported_unknown_spread() -> None:
    snapshot = {
        "captured_at": AS_OF - timedelta(seconds=5),
        "symbol": "XAUUSD",
        "capture_status": "ok",
        "quote_time": AS_OF - timedelta(seconds=5),
        "quote_age_seconds": 5,
        "bid": None,
        "ask": None,
        "mid": "3350.25",
        "spread": None,
        "session_code": "london_new_york_overlap",
        "data_availability": {"quote": "known"},
        "load_identity": "snapshot-1",
    }
    regime = classify_gold_regime(_context(feature=_feature_packet(snapshot=snapshot)))
    assert regime["labels"]["quote_spread_condition"] == "fresh_quote_spread_unknown"


def test_regime_digest_is_repeatable_and_changes_when_context_changes() -> None:
    context = _context(events=[_event(30)])
    first = classify_gold_regime(context)
    second = classify_gold_regime(deepcopy(context))
    clear = classify_gold_regime(_context(events=[_event(240)]))

    assert first == second
    assert first["regime_digest"] == second["regime_digest"]
    assert first["regime_digest"] != clear["regime_digest"]
    assert first["source_context_hash"] != clear["source_context_hash"]


def test_tampered_non_objective_or_hindsight_context_is_rejected() -> None:
    tampered = _context()
    tampered["data_quality"]["quote_freshness"] = "fresh"
    with pytest.raises(ValueError, match="Context hash"):
        classify_gold_regime(tampered)

    hindsight = _context()
    hindsight["retrospective_history_included"] = True
    with pytest.raises(ValueError, match="Retrospective"):
        classify_gold_regime(hindsight)

    contaminated = _context()
    contaminated["future_return"] = "2.5%"
    contaminated["context_hash"] = compute_context_hash(contaminated)
    with pytest.raises(ValueError, match="Hindsight field"):
        classify_gold_regime(contaminated)


def test_distribution_report_counts_only_descriptive_regimes() -> None:
    bullish = classify_gold_regime(
        _context(
            feature=_feature_packet(
                directions={"M15": "bullish", "H1": "bullish", "H4": "flat"}
            )
        )
    )
    bearish = classify_gold_regime(
        _context(
            feature=_feature_packet(
                directions={"M15": "bearish", "H1": "bearish", "H4": "flat"}
            )
        )
    )
    report = regime_distribution([bullish, bullish, bearish])

    assert report["packet_count"] == 3
    assert report["label_counts"]["trend_structure"] == {
        "bearish_trend": 1,
        "bullish_trend": 2,
    }
    assert report["outcome_statistics_included"] is False


def test_distribution_rejects_tampered_regime_packet() -> None:
    regime = classify_gold_regime(_context())
    regime["labels"]["session"] = "asia"
    with pytest.raises(ValueError, match="bad regime digest"):
        regime_distribution([regime])
