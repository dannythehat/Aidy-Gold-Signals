from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from aidy.context_packet_v3 import build_context_packet_v3, verify_context_hash_v3
from aidy.feature_engine import build_feature_packet
from aidy.price_structure_v2 import (
    PRICE_STRUCTURE_VERSION,
    build_price_structure_packet,
    verify_price_structure_packet,
)


def _research_row(
    *,
    opened: datetime,
    timeframe: str,
    open_price: Decimal = Decimal("2000"),
    high: Decimal = Decimal("2002"),
    low: Decimal = Decimal("1998"),
    close: Decimal = Decimal("2001"),
    identity: str | None = None,
) -> dict[str, object]:
    return {
        "research_identity": identity or f"r-{timeframe}-{opened.isoformat()}",
        "provenance_class": "retrospective_history",
        "pit_eligible": False,
        "symbol": "XAUUSD",
        "timeframe": timeframe,
        "open_time_utc": opened,
        "open": str(open_price),
        "high": str(high),
        "low": str(low),
        "close": str(close),
        "source": "histdata",
        "source_file_sha256": "a" * 64,
        "source_payload_sha256": "b" * 64,
        "derivation_version": "fixture-v1",
    }


def _pit_row(
    *,
    opened: datetime,
    timeframe: str = "M1",
    open_price: Decimal = Decimal("2000"),
    high: Decimal = Decimal("2002"),
    low: Decimal = Decimal("1998"),
    close: Decimal = Decimal("2001"),
    identity: str | None = None,
    observed_delay_seconds: int = 5,
) -> dict[str, object]:
    return {
        "load_identity": identity or f"p-{timeframe}-{opened.isoformat()}",
        "evidence_id": f"e-{opened.isoformat()}",
        "archive_key": f"gold/{timeframe}/{opened.timestamp()}.json",
        "payload_digest": "c" * 64,
        "symbol": "XAUUSD",
        "timeframe": timeframe,
        "open_time_utc": opened,
        "first_observed_at": opened + timedelta(seconds=observed_delay_seconds),
        "open": str(open_price),
        "high": str(high),
        "low": str(low),
        "close": str(close),
        "source": "gold_api",
    }


def _snapshot(as_of: datetime) -> dict[str, object]:
    return {
        "load_identity": "snapshot-day26",
        "captured_at": as_of - timedelta(seconds=1),
        "symbol": "XAUUSD",
        "capture_status": "complete",
        "bid": "2000",
        "ask": "2000.2",
        "mid": "2000.1",
        "spread": "0.2",
        "quote_time": as_of - timedelta(seconds=12),
        "quote_age_seconds": 12,
        "session_code": "london",
        "data_availability": {"quote": "known"},
    }


def _daily(opened: datetime, high: str, low: str, close: str) -> dict[str, object]:
    close_value = Decimal(close)
    return _research_row(
        opened=opened,
        timeframe="D1",
        open_price=close_value,
        high=Decimal(high),
        low=Decimal(low),
        close=close_value,
    )


def test_exact_completed_bar_boundary_excludes_forming_candle() -> None:
    start = datetime(2026, 8, 21, 7, 0, tzinfo=UTC)  # 08:00 London BST
    rows = [
        _research_row(
            opened=start + timedelta(minutes=index),
            timeframe="M1",
            open_price=Decimal(2000 + index),
            high=Decimal(2001 + index),
            low=Decimal(1999 + index),
            close=Decimal(2000 + index),
        )
        for index in range(16)
    ]
    rows[-1]["high"] = "9999"  # opens exactly at T and must not leak into T
    rows[-1]["close"] = "2000"
    rows[-1]["open"] = "2000"
    rows[-1]["low"] = "1999"

    forming = build_price_structure_packet(
        as_of=start + timedelta(minutes=14, seconds=59),
        symbol="XAUUSD",
        candle_rows=rows,
        mode="retrospective",
    )
    assert forming["structure"]["opening_ranges"]["london"]["15m"]["state"] == "forming"
    assert forming["structure"]["opening_ranges"]["london"]["15m"]["high"] is None

    completed = build_price_structure_packet(
        as_of=start + timedelta(minutes=15),
        symbol="XAUUSD",
        candle_rows=rows,
        mode="retrospective",
    )
    opening = completed["structure"]["opening_ranges"]["london"]["15m"]
    assert opening["state"] == "known"
    assert opening["observed_m1_bars"] == 15
    assert Decimal(opening["high"]) < Decimal(9999)


def test_opening_range_with_missing_completed_bar_fails_closed() -> None:
    start = datetime(2026, 8, 21, 7, 0, tzinfo=UTC)
    rows = [
        _research_row(opened=start + timedelta(minutes=index), timeframe="M1")
        for index in range(15)
        if index != 7
    ]
    packet = build_price_structure_packet(
        as_of=start + timedelta(minutes=15),
        symbol="XAUUSD",
        candle_rows=rows,
        mode="retrospective",
    )
    opening = packet["structure"]["opening_ranges"]["london"]["15m"]
    assert opening["state"] == "incomplete"
    assert opening["observed_m1_bars"] == 14
    assert opening["high"] is None
    assert opening["low"] is None


def test_session_extreme_never_uses_current_forming_bar() -> None:
    start = datetime(2026, 8, 21, 7, 0, tzinfo=UTC)
    rows = [
        _research_row(
            opened=start + timedelta(minutes=index),
            timeframe="M1",
            high=Decimal(2010 + index),
            low=Decimal(1990),
            close=Decimal(2000),
        )
        for index in range(16)
    ]
    rows[-1]["high"] = "9000"
    packet = build_price_structure_packet(
        as_of=start + timedelta(minutes=15),
        symbol="XAUUSD",
        candle_rows=rows,
        mode="retrospective",
    )
    london = packet["structure"]["session_extremes"]["london"]
    assert london["observed_m1_bars"] == 15
    assert london["high"] == "2024"


def test_prior_day_week_month_use_only_completed_d1() -> None:
    as_of = datetime(2026, 8, 21, 12, tzinfo=UTC)
    rows: list[dict[str, object]] = []
    for day, high, low, close in [
        (1, "1905", "1890", "1900"),
        (2, "1910", "1895", "1905"),
        (30, "1990", "1970", "1980"),
        (31, "2000", "1980", "1990"),
    ]:
        rows.append(_daily(datetime(2026, 7, day, tzinfo=UTC), high, low, close))
    for day, high, low, close in [
        (10, "2010", "1990", "2000"),
        (11, "2020", "2000", "2010"),
        (12, "2030", "2010", "2020"),
        (13, "2040", "2020", "2030"),
        (14, "2050", "2030", "2040"),
        (20, "2100", "2050", "2080"),
        (21, "9999", "1", "5000"),  # current D1 is still forming at T
    ]:
        rows.append(_daily(datetime(2026, 8, day, tzinfo=UTC), high, low, close))

    packet = build_price_structure_packet(
        as_of=as_of,
        symbol="XAUUSD",
        candle_rows=rows,
        mode="retrospective",
    )
    prior = packet["structure"]["prior_periods"]
    assert prior["prior_day"]["period_key"] == "2026-08-20"
    assert prior["prior_day"]["close"] == "2080"
    assert prior["prior_week"]["period_key"] == "2026-W33"
    assert prior["prior_week"]["high"] == "2050"
    assert prior["prior_month"]["period_key"] == "2026-07"
    assert prior["prior_month"]["high"] == "2000"
    assert prior["prior_month"]["close"] == "1990"


def test_missing_prior_periods_remain_unknown() -> None:
    packet = build_price_structure_packet(
        as_of=datetime(2026, 8, 21, 12, tzinfo=UTC),
        symbol="XAUUSD",
        candle_rows=[],
        mode="retrospective",
    )
    prior = packet["structure"]["prior_periods"]
    assert prior["prior_day"]["state"] == "unknown"
    assert prior["prior_week"]["state"] == "unknown"
    assert prior["prior_month"]["state"] == "unknown"


def test_utc_day_gap_fill_state_is_literal_touch_of_prior_close() -> None:
    d1 = _daily(datetime(2026, 8, 20, tzinfo=UTC), "2010", "1980", "2000")
    day = datetime(2026, 8, 21, tzinfo=UTC)
    first = _research_row(
        opened=day,
        timeframe="M1",
        open_price=Decimal("2010"),
        high=Decimal("2012"),
        low=Decimal("2005"),
        close=Decimal("2008"),
    )
    second = _research_row(
        opened=day + timedelta(minutes=1),
        timeframe="M1",
        open_price=Decimal("2008"),
        high=Decimal("2010"),
        low=Decimal("2003"),
        close=Decimal("2005"),
    )
    unfilled = build_price_structure_packet(
        as_of=day + timedelta(minutes=2),
        symbol="XAUUSD",
        candle_rows=[d1, first, second],
        mode="retrospective",
    )["structure"]["utc_day_gap"]
    assert unfilled["direction"] == "up"
    assert unfilled["fill_state"] == "unfilled"

    filler = _research_row(
        opened=day + timedelta(minutes=2),
        timeframe="M1",
        open_price=Decimal("2005"),
        high=Decimal("2006"),
        low=Decimal("1999"),
        close=Decimal("2001"),
    )
    filled = build_price_structure_packet(
        as_of=day + timedelta(minutes=3),
        symbol="XAUUSD",
        candle_rows=[d1, first, second, filler],
        mode="retrospective",
    )["structure"]["utc_day_gap"]
    assert filled["fill_state"] == "filled"


def test_trend_persistence_and_acceleration_use_raw_completed_m15_closes() -> None:
    start = datetime(2026, 8, 21, 8, tzinfo=UTC)
    closes = [Decimal("2000"), Decimal("2001"), Decimal("2002"), Decimal("2005"), Decimal("2009")]
    rows = [
        _research_row(
            opened=start + timedelta(minutes=15 * index),
            timeframe="M15",
            open_price=close - Decimal("0.5"),
            high=close + Decimal(1),
            low=close - Decimal(1),
            close=close,
        )
        for index, close in enumerate(closes)
    ]
    trend = build_price_structure_packet(
        as_of=start + timedelta(minutes=75),
        symbol="XAUUSD",
        candle_rows=rows,
        mode="retrospective",
    )["structure"]["trend_persistence_acceleration"]
    assert trend["state"] == "known"
    assert trend["direction"] == "up"
    assert trend["persistence_ratio"] == "1"
    assert Decimal(trend["absolute_acceleration_bps"]) > 0


def test_prior_day_breakout_failure_is_mechanical_reversion_inside() -> None:
    d1 = _daily(datetime(2026, 8, 20, tzinfo=UTC), "2005", "1980", "1995")
    day = datetime(2026, 8, 21, tzinfo=UTC)
    rows = [
        _research_row(
            opened=day,
            timeframe="M1",
            open_price=Decimal("2000"),
            high=Decimal("2007"),
            low=Decimal("1999"),
            close=Decimal("2006"),
        ),
        _research_row(
            opened=day + timedelta(minutes=1),
            timeframe="M1",
            open_price=Decimal("2006"),
            high=Decimal("2006"),
            low=Decimal("2002"),
            close=Decimal("2004"),
        ),
    ]
    breakout = build_price_structure_packet(
        as_of=day + timedelta(minutes=2),
        symbol="XAUUSD",
        candle_rows=[d1, *rows],
        mode="retrospective",
    )["structure"]["prior_day_breakout"]
    assert breakout["state"] == "upside_failed"
    assert breakout["upside"]["penetrated"] is True
    assert breakout["upside"]["reverted_inside"] is True


def test_wick_footprint_has_geometry_without_pattern_name() -> None:
    opened = datetime(2026, 8, 21, 8, tzinfo=UTC)
    row = _research_row(
        opened=opened,
        timeframe="M15",
        open_price=Decimal("2000"),
        high=Decimal("2010"),
        low=Decimal("1995"),
        close=Decimal("2002"),
    )
    wick = build_price_structure_packet(
        as_of=opened + timedelta(minutes=15),
        symbol="XAUUSD",
        candle_rows=[row],
        mode="retrospective",
    )["structure"]["wick_footprint"]
    assert wick["state"] == "known"
    assert Decimal(wick["upper_wick_bps"]) > Decimal(wick["lower_wick_bps"])
    assert "pattern" not in wick


def test_swing_extreme_penetration_with_reversion_waits_for_confirmation_bars() -> None:
    start = datetime(2026, 8, 21, 8, tzinfo=UTC)
    highs = [101, 102, 105, 103, 102, 106, 103]
    closes = [100, 101, 102, 102, 101, 104, 103]
    rows = [
        _research_row(
            opened=start + timedelta(minutes=15 * index),
            timeframe="M15",
            open_price=Decimal(closes[index]),
            high=Decimal(highs[index]),
            low=Decimal(98),
            close=Decimal(closes[index]),
            identity=f"swing-{index}",
        )
        for index in range(len(highs))
    ]
    result = build_price_structure_packet(
        as_of=start + timedelta(minutes=15 * len(rows)),
        symbol="XAUUSD",
        candle_rows=rows,
        mode="retrospective",
    )["structure"]["swing_extreme_penetration_with_reversion"]["high_side"]
    assert result["state"] == "known"
    assert result["swing_price"] == "105"
    assert result["penetrated"] is True
    assert result["reverted"] is True


def test_retrospective_feed_arrival_and_quote_state_stay_unknown() -> None:
    packet = build_price_structure_packet(
        as_of=datetime(2026, 8, 21, 12, tzinfo=UTC),
        symbol="XAUUSD",
        candle_rows=[],
        mode="retrospective",
    )
    assert packet["feed_health"]["timeframes"]["M1"]["arrival_observation"]["state"] == "unknown"
    assert packet["feed_health"]["quote"]["state"] == "unknown"
    assert packet["feed_health"]["threshold_based_health_classification"] is False


def test_pit_feed_health_reports_observable_gap_and_arrival_delay() -> None:
    start = datetime(2026, 8, 21, 8, tzinfo=UTC)
    rows = [
        _pit_row(opened=start, observed_delay_seconds=4),
        _pit_row(opened=start + timedelta(minutes=1), observed_delay_seconds=6),
        _pit_row(opened=start + timedelta(minutes=3), observed_delay_seconds=5),
    ]
    packet = build_price_structure_packet(
        as_of=start + timedelta(minutes=5),
        symbol="XAUUSD",
        candle_rows=rows,
        mode="pit",
        snapshot=_snapshot(start + timedelta(minutes=5)),
    )
    m1 = packet["feed_health"]["timeframes"]["M1"]
    assert m1["interbar_gap_count"] == 1
    assert m1["max_interbar_gap_seconds"] == 120
    assert m1["arrival_observation"]["state"] == "observed"
    assert m1["arrival_observation"]["sample_n"] == 3
    assert packet["feed_health"]["quote"]["quote_age_seconds"] == "12"


def test_future_pit_observation_cannot_change_packet_at_t() -> None:
    start = datetime(2026, 8, 21, 8, tzinfo=UTC)
    visible = _pit_row(opened=start, observed_delay_seconds=5)
    future_known = _pit_row(
        opened=start + timedelta(minutes=1),
        high=Decimal("9000"),
        close=Decimal("2000"),
        observed_delay_seconds=600,
    )
    as_of = start + timedelta(minutes=3)
    left = build_price_structure_packet(
        as_of=as_of,
        symbol="XAUUSD",
        candle_rows=[visible],
        mode="pit",
    )
    right = build_price_structure_packet(
        as_of=as_of,
        symbol="XAUUSD",
        candle_rows=[visible, future_known],
        mode="pit",
    )
    assert left["structure_semantic_digest"] == right["structure_semantic_digest"]


def test_equivalent_pit_and_retrospective_ohlc_share_structure_semantic_digest() -> None:
    start = datetime(2026, 8, 20, 0, tzinfo=UTC)
    research_rows = [
        _research_row(
            opened=start + timedelta(minutes=index),
            timeframe="M1",
            open_price=Decimal(2000 + index),
            high=Decimal(2001 + index),
            low=Decimal(1999 + index),
            close=Decimal(2000 + index),
            identity=f"r-{index}",
        )
        for index in range(10)
    ]
    pit_rows = [
        _pit_row(
            opened=start + timedelta(minutes=index),
            timeframe="M1",
            open_price=Decimal(2000 + index),
            high=Decimal(2001 + index),
            low=Decimal(1999 + index),
            close=Decimal(2000 + index),
            identity=f"p-{index}",
        )
        for index in range(10)
    ]
    as_of = start + timedelta(minutes=20)
    research = build_price_structure_packet(
        as_of=as_of,
        symbol="XAUUSD",
        candle_rows=research_rows,
        mode="retrospective",
    )
    pit = build_price_structure_packet(
        as_of=as_of,
        symbol="XAUUSD",
        candle_rows=pit_rows,
        mode="pit",
    )
    assert research["structure_semantic_digest"] == pit["structure_semantic_digest"]
    assert research["feed_health"]["timeframes"]["M1"]["arrival_observation"]["state"] == "unknown"
    assert pit["feed_health"]["timeframes"]["M1"]["arrival_observation"]["state"] == "observed"


def test_packet_is_deterministic_under_input_reordering_and_digest_verifies() -> None:
    start = datetime(2026, 8, 21, 8, tzinfo=UTC)
    rows = [_research_row(opened=start + timedelta(minutes=index), timeframe="M1") for index in range(10)]
    first = build_price_structure_packet(
        as_of=start + timedelta(minutes=15),
        symbol="XAUUSD",
        candle_rows=rows,
        mode="retrospective",
    )
    second = build_price_structure_packet(
        as_of=start + timedelta(minutes=15),
        symbol="XAUUSD",
        candle_rows=reversed(rows),
        mode="retrospective",
    )
    assert first == second
    assert first["price_structure_version"] == PRICE_STRUCTURE_VERSION
    assert verify_price_structure_packet(first) is True


def test_context_v3_accepts_verified_pit_price_structure_and_rehashes() -> None:
    start = datetime(2026, 8, 21, 8, tzinfo=UTC)
    as_of = start + timedelta(minutes=2)
    rows = [_pit_row(opened=start), _pit_row(opened=start + timedelta(minutes=1))]
    snapshot = _snapshot(as_of)
    feature = build_feature_packet(
        as_of=as_of,
        symbol="XAUUSD",
        candle_rows=rows,
        mode="pit",
        snapshot=snapshot,
    )
    structure = build_price_structure_packet(
        as_of=as_of,
        symbol="XAUUSD",
        candle_rows=rows,
        mode="pit",
        snapshot=snapshot,
    )
    context = build_context_packet_v3(
        as_of=as_of,
        symbol="XAUUSD",
        feature_packet=feature,
        price_structure_packet=structure,
        event_rows=[],
        macro_evidence_state="unknown",
        cross_market_rows=[],
    )
    assert context["price_structure_context"]["price_structure_digest"] == structure["price_structure_digest"]
    assert verify_context_hash_v3(context) is True


def test_context_v3_rejects_tampered_price_structure() -> None:
    start = datetime(2026, 8, 21, 8, tzinfo=UTC)
    as_of = start + timedelta(minutes=2)
    rows = [_pit_row(opened=start)]
    snapshot = _snapshot(as_of)
    feature = build_feature_packet(
        as_of=as_of,
        symbol="XAUUSD",
        candle_rows=rows,
        mode="pit",
        snapshot=snapshot,
    )
    structure = build_price_structure_packet(
        as_of=as_of,
        symbol="XAUUSD",
        candle_rows=rows,
        mode="pit",
        snapshot=snapshot,
    )
    structure["future_values_used"] = True
    with pytest.raises(ValueError, match="digest"):
        build_context_packet_v3(
            as_of=as_of,
            symbol="XAUUSD",
            feature_packet=feature,
            price_structure_packet=structure,
            event_rows=[],
            macro_evidence_state="unknown",
            cross_market_rows=[],
        )
