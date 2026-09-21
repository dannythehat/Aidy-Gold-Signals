from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from aidy.gold_price_expert_math import (
    PRICE_EXPERT_MATH_VERSION,
    PRIMITIVE_DEFINITIONS,
    build_price_expert_math_packet,
    verify_price_expert_math_packet,
)

BASE = datetime(2026, 9, 21, 0, 0, tzinfo=UTC)
STEP = timedelta(minutes=15)


def _row(
    index: int,
    *,
    close: Decimal,
    open_price: Decimal | None = None,
    high: Decimal | None = None,
    low: Decimal | None = None,
    timeframe: str = "M15",
) -> dict[str, object]:
    opened = BASE + STEP * index
    open_value = open_price if open_price is not None else close
    high_value = high if high is not None else max(open_value, close) + Decimal("0.5")
    low_value = low if low is not None else min(open_value, close) - Decimal("0.5")
    return {
        "research_identity": f"build4-{timeframe}-{index}",
        "provenance_class": "retrospective_history",
        "pit_eligible": False,
        "symbol": "XAUUSD",
        "timeframe": timeframe,
        "open_time_utc": opened,
        "open": str(open_value),
        "high": str(high_value),
        "low": str(low_value),
        "close": str(close),
        "source": "build4_fixture",
        "source_file_sha256": "a" * 64,
        "source_payload_sha256": "b" * 64,
        "derivation_version": "build4-fixture-v1",
    }


def _packet(rows: list[dict[str, object]], *, as_of: datetime | None = None) -> dict:
    if as_of is None:
        latest = max(row["open_time_utc"] for row in rows)
        assert isinstance(latest, datetime)
        as_of = latest + STEP
    return build_price_expert_math_packet(
        as_of=as_of,
        symbol="XAUUSD",
        candle_rows=rows,
        mode="retrospective",
    )


def _closes(values: list[str]) -> list[dict[str, object]]:
    return [
        _row(index, close=Decimal(value))
        for index, value in enumerate(values)
    ]


def test_build4_clean_uptrend_has_high_quality_directional_path() -> None:
    rows = _closes([str(100 + index) for index in range(25)])
    packet = _packet(rows)
    m15 = packet["timeframes"]["M15"]
    primitives = m15["primitives"]

    assert packet["price_expert_math_version"] == PRICE_EXPERT_MATH_VERSION
    assert primitives["multi_lookback_returns"]["values"]["5_bar"]["direction"] == "bullish"
    assert primitives["close_step_persistence"]["directional_persistence_ratio"] == "1"
    assert primitives["path_efficiency"]["efficiency_ratio"] == "1"
    regression = primitives["log_ols_slope"]["windows"]["20_bar"]
    assert regression["direction"] == "bullish"
    assert Decimal(regression["r_squared"]) > Decimal("0.99")
    assert verify_price_expert_math_packet(packet)


def test_build4_clean_downtrend_has_high_quality_directional_path() -> None:
    rows = _closes([str(130 - index) for index in range(25)])
    primitives = _packet(rows)["timeframes"]["M15"]["primitives"]
    assert primitives["multi_lookback_returns"]["values"]["8_bar"]["direction"] == "bearish"
    assert primitives["close_step_persistence"]["directional_persistence_ratio"] == "1"
    assert primitives["path_efficiency"]["signed_efficiency"] == "-1"
    regression = primitives["log_ols_slope"]["windows"]["20_bar"]
    assert regression["direction"] == "bearish"
    assert Decimal(regression["r_squared"]) > Decimal("0.99")


def test_build4_range_chop_does_not_masquerade_as_strong_trend() -> None:
    values = ["100", "101"] * 13
    primitives = _packet(_closes(values))["timeframes"]["M15"]["primitives"]
    efficiency = Decimal(primitives["path_efficiency"]["efficiency_ratio"])
    regression = primitives["log_ols_slope"]["windows"]["20_bar"]
    assert efficiency < Decimal("0.10")
    assert Decimal(regression["r_squared"]) < Decimal("0.10")
    assert Decimal(primitives["close_step_persistence"]["directional_persistence_ratio"]) < Decimal(
        "0.60"
    )


def test_build4_exact_path_efficiency_and_persistence_math() -> None:
    rows = _closes(["100", "101", "102", "101", "103", "104", "105", "106"])
    primitives = _packet(rows)["timeframes"]["M15"]["primitives"]
    # Net path is +6; travelled path is 8 => 0.75 efficiency.
    assert primitives["path_efficiency"]["efficiency_ratio"] == "0.75"
    # Six of seven close steps point in the net bullish direction.
    assert primitives["close_step_persistence"]["directional_persistence_ratio"] == "0.857143"


def test_build4_reversal_is_explicit_in_acceleration_state() -> None:
    rows = _closes(["108", "107", "106", "105", "104", "105", "106", "107", "108"])
    acceleration = _packet(rows)["timeframes"]["M15"]["primitives"][
        "acceleration_deceleration"
    ]
    assert acceleration["state"] == "known"
    assert Decimal(acceleration["previous_return_bps"]) < 0
    assert Decimal(acceleration["recent_return_bps"]) > 0
    assert acceleration["state_label"] == "direction_reversal"


def test_build4_volatility_normalisation_reuses_completed_price_path() -> None:
    rows = _closes([str(100 + Decimal(index) / Decimal(2)) for index in range(25)])
    normalised = _packet(rows)["timeframes"]["M15"]["primitives"][
        "atr_rv_normalisation"
    ]
    assert normalised["atr_14_bps"] is not None
    assert normalised["realized_vol_20_bps"] is not None
    assert normalised["normalised_returns"]["5_bar"]["atr_units"] is not None


def test_build4_candle_geometry_has_exact_expected_ratios() -> None:
    rows = _closes([str(100 + index) for index in range(7)])
    rows.append(
        _row(
            7,
            open_price=Decimal("100"),
            high=Decimal("110"),
            low=Decimal("90"),
            close=Decimal("108"),
        )
    )
    geometry = _packet(rows)["timeframes"]["M15"]["primitives"]["candle_geometry"]
    assert geometry["body_direction"] == "bullish"
    assert geometry["close_location"] == "0.9"
    assert geometry["body_fraction_of_range"] == "0.4"
    assert geometry["signed_body_bps"] == "800"


def test_build4_confirmed_swing_requires_right_wing_no_lookahead() -> None:
    rows = [
        _row(0, close=Decimal("100"), high=Decimal("101"), low=Decimal("99")),
        _row(1, close=Decimal("101"), high=Decimal("102"), low=Decimal("100")),
        _row(2, close=Decimal("102"), high=Decimal("105"), low=Decimal("101")),
        _row(3, close=Decimal("101"), high=Decimal("103"), low=Decimal("100")),
        _row(4, close=Decimal("100"), high=Decimal("102"), low=Decimal("99")),
    ]
    before_confirmation = _packet(
        rows,
        as_of=rows[4]["open_time_utc"],
    )
    assert (
        before_confirmation["timeframes"]["M15"]["primitives"]["confirmed_swing_sequence"][
            "confirmed_highs"
        ]
        == []
    )

    after_confirmation = _packet(rows)
    highs = after_confirmation["timeframes"]["M15"]["primitives"][
        "confirmed_swing_sequence"
    ]["confirmed_highs"]
    assert len(highs) == 1
    assert highs[0]["price"] == "105"
    assert highs[0]["open_time_utc"] == rows[2]["open_time_utc"].isoformat()


def test_build4_partial_current_bar_is_excluded() -> None:
    completed = _closes([str(100 + index) for index in range(8)])
    as_of = BASE + STEP * 8
    partial = _row(
        8,
        close=Decimal("150"),
        high=Decimal("151"),
        low=Decimal("99"),
    )
    packet = _packet(completed + [partial], as_of=as_of)
    m15 = packet["timeframes"]["M15"]
    assert m15["bars_available"] == 8
    assert m15["latest_completed_open_time_utc"] == completed[-1]["open_time_utc"].isoformat()
    assert m15["primitives"]["multi_lookback_returns"]["values"]["1_bar"]["return_bps"] != (
        _packet(completed + [partial], as_of=as_of + STEP)["timeframes"]["M15"]["primitives"][
            "multi_lookback_returns"
        ]["values"]["1_bar"]["return_bps"]
    )


def test_build4_breakout_acceptance_requires_completed_closes_beyond_swing() -> None:
    rows = [
        _row(0, close=Decimal("100"), high=Decimal("101"), low=Decimal("99")),
        _row(1, close=Decimal("102"), high=Decimal("103"), low=Decimal("100")),
        _row(2, close=Decimal("104"), high=Decimal("105"), low=Decimal("102")),
        _row(3, close=Decimal("103"), high=Decimal("104"), low=Decimal("101")),
        _row(4, close=Decimal("102"), high=Decimal("103"), low=Decimal("100")),
        _row(5, close=Decimal("106"), high=Decimal("107"), low=Decimal("102")),
        _row(6, close=Decimal("107"), high=Decimal("108"), low=Decimal("104")),
    ]
    high_side = _packet(rows)["timeframes"]["M15"]["primitives"]["breakout_lifecycle"][
        "high_side"
    ]
    assert high_side["level"] == "105"
    assert high_side["penetrated"] is True
    assert high_side["close_beyond_count"] == 2
    assert high_side["accepted"] is True
    assert high_side["held_at_latest_close"] is True
    assert high_side["state"] == "accepted_hold"


def test_build4_breakout_rejection_is_distinct_from_acceptance() -> None:
    rows = [
        _row(0, close=Decimal("100"), high=Decimal("101"), low=Decimal("99")),
        _row(1, close=Decimal("102"), high=Decimal("103"), low=Decimal("100")),
        _row(2, close=Decimal("104"), high=Decimal("105"), low=Decimal("102")),
        _row(3, close=Decimal("103"), high=Decimal("104"), low=Decimal("101")),
        _row(4, close=Decimal("102"), high=Decimal("103"), low=Decimal("100")),
        _row(5, close=Decimal("104"), high=Decimal("106"), low=Decimal("102")),
        _row(6, close=Decimal("103"), high=Decimal("104"), low=Decimal("101")),
    ]
    high_side = _packet(rows)["timeframes"]["M15"]["primitives"]["breakout_lifecycle"][
        "high_side"
    ]
    assert high_side["penetrated"] is True
    assert high_side["close_beyond_count"] == 0
    assert high_side["accepted"] is False
    assert high_side["reclaimed_inside"] is True
    assert high_side["state"] == "reclaimed_inside"


def test_build4_range_position_is_a_factual_location_not_a_vote() -> None:
    rows = []
    for index in range(20):
        close = Decimal("100") + Decimal(index)
        rows.append(
            _row(
                index,
                close=close,
                high=close + Decimal("1"),
                low=close - Decimal("1"),
            )
        )
    packet = _packet(rows)
    position = packet["timeframes"]["M15"]["primitives"]["range_position"]["windows"]["20_bar"]
    assert position["state"] == "known"
    assert Decimal(position["position"]) > Decimal("0.90")
    assert packet["directional_gate_vote_emitted"] is False


def test_build4_contradictions_are_diagnostics_not_hidden_averages() -> None:
    rows = _closes(
        [
            "100",
            "101",
            "102",
            "103",
            "104",
            "105",
            "106",
            "107",
            "106",
            "105",
            "104",
            "103",
            "102",
            "101",
            "100",
            "99",
            "98",
            "97",
            "96",
            "95",
        ]
    )
    contradictions = _packet(rows)["timeframes"]["M15"]["primitives"][
        "contradiction_flags"
    ]
    assert contradictions["contradiction_count"] >= 1
    assert contradictions["flags"]


def test_build4_primitive_catalog_contains_no_duplicate_feature_counting() -> None:
    packet = _packet(_closes([str(100 + index) for index in range(25)]))
    manifest_ids = [item["primitive_id"] for item in packet["primitive_manifest"]]
    assert len(manifest_ids) == len(PRIMITIVE_DEFINITIONS)
    assert len(manifest_ids) == len(set(manifest_ids))
    for timeframe in packet["timeframes"].values():
        assert timeframe["duplicate_primitive_count"] == 0
        assert len(timeframe["primitive_ids"]) == len(set(timeframe["primitive_ids"]))


def test_build4_packet_is_deterministic_and_digest_detects_mutation() -> None:
    rows = _closes([str(100 + index) for index in range(25)])
    first = _packet(rows)
    second = _packet(list(reversed(rows)))
    assert first == second
    assert verify_price_expert_math_packet(first)
    first["timeframes"]["M15"]["bars_available"] = 999
    assert verify_price_expert_math_packet(first) is False


def test_build4_missing_timeframe_stays_unknown_instead_of_fabricated() -> None:
    packet = _packet(_closes([str(100 + index) for index in range(8)]))
    assert packet["timeframes"]["H1"]["state"] == "unknown"
    assert packet["timeframes"]["H1"]["bars_available"] == 0
    assert packet["timeframes"]["H1"]["primitives"]["log_ols_slope"]["windows"]["5_bar"][
        "state"
    ] == "insufficient"
