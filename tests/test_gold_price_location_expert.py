from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from aidy.gold_cycle_environment import build_cycle_environment
from aidy.gold_expert_gate_contract import verify_expert_gate_packet
from aidy.gold_price_expert_math import build_price_expert_math_packet
from aidy.gold_price_location_expert import (
    PRICE_LOCATION_EXPERT_VERSION,
    PRICE_LOCATION_GATE_ID,
    REFERENCE_PRIORITY,
    build_price_location_expert,
)

BASE = datetime(2026, 9, 21, 6, 0, tzinfo=UTC)


def _text(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.000001")), "f").rstrip("0").rstrip(".")


def _m15_rows(count: int = 60, *, mode: str = "retrospective") -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    value = Decimal("2420")
    for index in range(count):
        opened = BASE + timedelta(minutes=15 * index)
        # Smooth enough for ATR/range math but monotonic enough not to manufacture swings.
        value += Decimal("0.18") + Decimal(index % 3) * Decimal("0.01")
        open_price = value - Decimal("0.12")
        row: dict[str, object] = {
            "symbol": "XAUUSD",
            "timeframe": "M15",
            "open_time_utc": opened,
            "open": _text(open_price),
            "high": _text(value + Decimal("0.25")),
            "low": _text(open_price - Decimal("0.25")),
            "close": _text(value),
            "source": "build11_fixture",
            "source_file_sha256": "a" * 64,
            "source_payload_sha256": "b" * 64,
            "derivation_version": "build11-fixture-v1",
        }
        if mode == "pit":
            row.update(
                {
                    "load_identity": f"build11-pit-{index}",
                    "provenance_class": "pit_observed",
                    "pit_eligible": True,
                    "first_observed_at": (opened + timedelta(minutes=15)).isoformat(),
                }
            )
        else:
            row.update(
                {
                    "research_identity": f"build11-retro-{index}",
                    "provenance_class": "retrospective_history",
                    "pit_eligible": False,
                }
            )
        rows.append(row)
    return rows


def _as_of(rows: list[dict[str, object]]) -> datetime:
    latest = max(row["open_time_utc"] for row in rows)
    assert isinstance(latest, datetime)
    return latest + timedelta(minutes=15)


def _location_payload(mid: str = "2427.00") -> dict:
    def ref(level: str, side: str, distance: str) -> dict:
        return {
            "level": level,
            "relative_side": side,
            "distance_bps": distance,
        }

    return {
        "state": "known",
        "mid": mid,
        "reference_distances": {
            "prior_day_high": ref("2432.00", "below", "-20.559211"),
            "prior_day_low": ref("2400.00", "above", "112.500000"),
            "prior_day_close": ref("2425.00", "above", "8.247423"),
            "asia_overnight_high": ref("2428.00", "below", "-4.118616"),
            "asia_overnight_low": ref("2418.00", "above", "37.220844"),
            "london_high": ref("2427.30", "below", "-1.235117"),
            "london_low": ref("2426.90", "above", "0.412049"),
            "london_opening_15m_high": ref("2427.40", "below", "-1.647851"),
            "london_opening_15m_low": ref("2426.80", "above", "0.824133"),
        },
        "range_positions": {
            "prior_day": "0.843750",
            "asia_overnight": "0.900000",
            "london": "0.250000",
            "london_opening_15m": "0.333333",
        },
        "round_number_references": {},
    }


def _environment(as_of: datetime, *, mid: str | None = "2427.00") -> dict:
    location = _location_payload(mid or "2427.00")
    if mid is None:
        location = {
            "state": "unknown",
            "mid": None,
            "reference_distances": {},
            "range_positions": {},
            "round_number_references": {},
        }
    return build_cycle_environment(
        as_of_utc=as_of,
        target_window_start_utc=as_of + timedelta(minutes=15),
        session_code="london",
        observed_state="neutral",
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
                "five_minute_distribution_state": "within_recent_distribution",
                "five_minute_range_state": "normal_range",
                "windows": {
                    "5m": {"direction": "up", "return_bps": "1"},
                    "15m": {"direction": "up", "return_bps": "2"},
                    "60m": {"direction": "up", "return_bps": "4"},
                },
            },
            "location": location,
            "volatility": {
                "state": "normal",
                "jump_continuous": {"state": "continuous_dominant"},
            },
            "scheduled_event_risk": {
                "state": "known",
                "timing_state": "outside_near_event_window",
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
        regime={"compound_regime_key": "trend|normal"},
    )


def _packet(
    rows: list[dict[str, object]],
    *,
    mode: str = "retrospective",
    as_of: datetime | None = None,
) -> dict:
    return build_price_expert_math_packet(
        as_of=as_of or _as_of(rows),
        symbol="XAUUSD",
        candle_rows=rows,
        mode=mode,
    )


def _result(*, mode: str = "retrospective") -> dict:
    rows = _m15_rows(mode=mode)
    as_of = _as_of(rows)
    return build_price_location_expert(
        global_environment=_environment(as_of),
        price_math_packet=_packet(rows, mode=mode),
    )


def test_build11_location_is_context_only_and_never_directional() -> None:
    result = _result()
    packet = result["expert_packet"]
    assert result["expert_version"] == PRICE_LOCATION_EXPERT_VERSION
    assert packet["gate_id"] == PRICE_LOCATION_GATE_ID
    assert packet["gate_mode"] == "context_only"
    assert packet["conclusion"] == "context_only"
    assert packet["gate_scoreable"] is False
    assert packet["internal_conviction"] is None
    assert verify_expert_gate_packet(packet)

    policy = result["reaction_rule_policy"]
    assert policy["directional_vote_allowed"] is False
    assert policy["tested_location_reaction_rules"] == []
    assert policy["location_alone_creates_edge"] is False
    assert policy["separate_reaction_rule_required"] is True
    assert all(item["role"] == "context_only" for item in packet["subcalculators"])
    assert all(item["vote"] in {"context_only", "unknown"} for item in packet["subcalculators"])


def test_build11_exact_geometric_nearest_level_math() -> None:
    result = _result()
    nearest = result["rankings"]["geometric_nearest"]

    assert nearest["reference"] == "london_low"
    assert nearest["level"] == "2426.900000"
    assert nearest["mid_minus_level"] == "0.100000"
    assert nearest["absolute_distance_usd"] == "0.100000"
    assert nearest["relative_side"] == "above"

    expected_bps = Decimal("0.1") / Decimal("2426.9") * Decimal(10000)
    assert Decimal(nearest["distance_bps"]) == expected_bps.quantize(Decimal("0.000001"))
    assert Decimal(nearest["distance_atr_units"]) >= 0


def test_build11_structural_priority_is_auditable_and_separate_from_nearest() -> None:
    result = _result()
    nearest = result["rankings"]["geometric_nearest"]
    priority = result["rankings"]["structural_priority_reference"]

    assert nearest["reference"] == "london_low"
    assert priority["reference"] == "prior_day_close"
    assert priority["priority_tier"] == 1
    assert priority["priority_reason"] == "prior-day structural reference"
    assert nearest["reference"] != priority["reference"]

    policy = result["rankings"]["priority_policy"]
    assert any(
        row["category"] == "prior_day"
        and row["priority_tier"] == REFERENCE_PRIORITY["prior_day"][0]
        for row in policy
    )
    assert result["rankings"]["priority_order"][0] == "prior_day_close"


def test_build11_confluence_represents_multiple_categories() -> None:
    result = _result()
    assert result["confluence"]["state"] == "confluence_present"
    clusters = result["confluence"]["clusters"]
    assert clusters
    assert any(
        cluster["multi_category"] is True
        and "active_session" in cluster["categories"]
        and "opening_range" in cluster["categories"]
        for cluster in clusters
    )


def test_build11_nearby_levels_on_both_sides_are_explicit_conflict() -> None:
    result = _result()
    conflict = result["bracket_conflict"]
    assert conflict["state"] == "bracketed_by_nearby_levels"
    assert conflict["nearest_level_above_price"]["relative_side"] == "below"
    assert conflict["nearest_level_below_price"]["relative_side"] == "above"
    assert Decimal(
        conflict["nearest_level_above_price"]["distance_atr_units"]
    ) <= Decimal("0.50")
    assert Decimal(
        conflict["nearest_level_below_price"]["distance_atr_units"]
    ) <= Decimal("0.50")


def test_build11_round_numbers_are_descriptive_and_ranked_low() -> None:
    result = _result()
    refs = {item["reference"]: item for item in result["references"]}
    assert refs["round_nearest_10_usd"]["level"] == "2430.000000"
    assert refs["round_nearest_50_usd"]["level"] == "2450.000000"
    assert refs["round_nearest_10_usd"]["priority_tier"] == 5
    assert refs["round_nearest_50_usd"]["priority_tier"] == 5
    assert result["reaction_rule_policy"]["directional_vote_allowed"] is False


def test_build11_atr_normalised_distance_uses_completed_price_math() -> None:
    result = _result()
    assert result["atr_source_timeframe"] == "M15"
    assert Decimal(result["atr_14_bps"]) > 0
    for item in result["references"]:
        assert item["distance_atr_units"] is not None
        assert item["atr_distance_band"] != "unknown"


def test_build11_missing_mid_fails_closed_to_context_unknown() -> None:
    rows = _m15_rows()
    as_of = _as_of(rows)
    result = build_price_location_expert(
        global_environment=_environment(as_of, mid=None),
        price_math_packet=_packet(rows),
    )
    assert result["mid"] is None
    assert result["references"] == []
    assert result["rankings"]["geometric_nearest"] is None
    assert result["expert_packet"]["conclusion"] == "context_only"
    assert result["expert_packet"]["gate_scoreable"] is False
    assert all(item["vote"] == "unknown" for item in result["expert_packet"]["subcalculators"])


def test_build11_pit_mode_keeps_completed_bar_provenance_and_no_future_values() -> None:
    result = _result(mode="pit")
    packet = result["expert_packet"]
    assert packet["no_hindsight_attestation"]["future_values_used"] is False
    assert result["future_values_used"] is False
    for evidence in packet["evidence_inputs"]:
        assert evidence["provenance"]["future_values_used"] is False


def test_build11_chronological_freeze_ignores_later_rows() -> None:
    all_rows = _m15_rows(70, mode="pit")
    prefix = all_rows[:60]
    as_of = _as_of(prefix)
    environment = _environment(as_of)

    first = build_price_location_expert(
        global_environment=environment,
        price_math_packet=_packet(prefix, mode="pit", as_of=as_of),
    )
    second = build_price_location_expert(
        global_environment=environment,
        price_math_packet=_packet(all_rows, mode="pit", as_of=as_of),
    )
    assert first["expert_packet"]["packet_digest"] == second["expert_packet"]["packet_digest"]
    assert first["rankings"] == second["rankings"]
    assert first["confluence"] == second["confluence"]


def test_build11_rejects_mismatched_as_of() -> None:
    rows = _m15_rows()
    as_of = _as_of(rows)
    with pytest.raises(ValueError, match="same as-of"):
        build_price_location_expert(
            global_environment=_environment(as_of + timedelta(minutes=15)),
            price_math_packet=_packet(rows),
        )


def test_build11_build3_trust_is_context_specific() -> None:
    base = _result()
    exact = base["trust_scopes"][0]
    score_row = {
        "scope_key": exact["scope_key"],
        "scope_type": exact["scope_type"],
        "sample_n": 30,
        "correct_n": 24,
        "incorrect_n": 6,
        "net_score": 20,
        "score_mean": "0.666667",
        "accuracy": "0.8",
        "recent_window": 20,
        "recent_sample_n": 12,
        "recent_correct_n": 10,
        "recent_net_score": 9,
        "recent_accuracy": "0.833333",
        "wilson_95_low": "0.626",
        "wilson_95_high": "0.905",
    }
    rows = _m15_rows()
    as_of = _as_of(rows)
    result = build_price_location_expert(
        global_environment=_environment(as_of),
        price_math_packet=_packet(rows),
        trust_score_rows_by_subject={f"gate:{PRICE_LOCATION_GATE_ID}": [score_row]},
    )
    gate_profile = next(
        item for item in result["trust_envelope"]["subject_profiles"]
        if item["subject_type"] == "gate"
    )["profile"]
    assert gate_profile["selected_scope_type"] == "mini_exact"
    assert gate_profile["sample_n"] == 30
    assert result["expert_packet"]["internal_conviction"] is None
