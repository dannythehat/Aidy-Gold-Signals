from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from aidy.gc_microstructure import BASELINE_VERSION
from aidy.gold_cycle_environment import build_cycle_environment
from aidy.gold_expert_gate_contract import verify_expert_gate_packet
from aidy.gold_session_participation_expert import (
    MATCHED_CLOCK_MINIMUM_N,
    SESSION_PARTICIPATION_EXPERT_VERSION,
    SESSION_PARTICIPATION_GATE_ID,
    build_session_participation_expert,
)
from aidy.market_sessions import session_code_at


def _text(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.000001")), "f").rstrip("0").rstrip(".")


def _m1_rows(
    *,
    as_of: datetime,
    high_activity: bool = True,
    mode: str = "retrospective",
) -> list[dict[str, object]]:
    values: list[Decimal] = []
    value = Decimal("2400")
    for index in range(20):
        if high_activity:
            value += Decimal("0.65") if index % 2 else Decimal("-0.48")
        else:
            value += Decimal("0.015") if index % 2 else Decimal("-0.010")
        values.append(value)

    start = as_of - timedelta(minutes=len(values))
    rows: list[dict[str, object]] = []
    previous = values[0]
    for index, close in enumerate(values):
        opened = start + timedelta(minutes=index)
        open_price = previous if index else close
        padding = Decimal("0.12") if high_activity else Decimal("0.02")
        row: dict[str, object] = {
            "symbol": "XAUUSD",
            "timeframe": "M1",
            "open_time_utc": opened,
            "open": _text(open_price),
            "high": _text(max(open_price, close) + padding),
            "low": _text(min(open_price, close) - padding),
            "close": _text(close),
            "source": "build14_fixture",
            "source_file_sha256": "a" * 64,
            "source_payload_sha256": "b" * 64,
            "derivation_version": "build14-fixture-v1",
        }
        if mode == "pit":
            row.update(
                {
                    "load_identity": f"build14-pit-{index}",
                    "provenance_class": "pit_observed",
                    "pit_eligible": True,
                    "first_observed_at": (opened + timedelta(minutes=1)).isoformat(),
                }
            )
        else:
            row.update(
                {
                    "research_identity": f"build14-retro-{index}",
                    "provenance_class": "retrospective_history",
                    "pit_eligible": False,
                }
            )
        rows.append(row)
        previous = close
    return rows


def _environment(
    *,
    as_of: datetime,
    event_timing: str = "outside_near_event_window",
) -> dict:
    session = session_code_at(as_of)
    return build_cycle_environment(
        as_of_utc=as_of,
        target_window_start_utc=as_of + timedelta(minutes=15),
        session_code=session,
        observed_state="neutral",
        gold_state={
            "market_structure": {
                "timeframes": {
                    "M5": {"net_close_direction": "flat", "state": "known"},
                    "M15": {"net_close_direction": "flat", "state": "known"},
                    "H1": {"net_close_direction": "flat", "state": "known"},
                    "H4": {"net_close_direction": "up", "state": "known"},
                    "D1": {"net_close_direction": "up", "state": "known"},
                }
            },
            "move_observation": {
                "five_minute_distribution_state": "within_recent_distribution",
                "five_minute_range_state": "normal_range",
                "windows": {
                    "5m": {"direction": "flat", "return_bps": "0"},
                    "15m": {"direction": "flat", "return_bps": "0"},
                    "60m": {"direction": "flat", "return_bps": "0"},
                },
            },
            "volatility": {
                "state": "normal",
                "jump_continuous": {"state": "continuous_dominant"},
            },
            "scheduled_event_risk": {
                "state": "known",
                "timing_state": event_timing,
            },
        },
        semantic_context={
            "data_quality": {
                "quote_state": "known",
                "quote_freshness": "fresh",
                "spread_state": "known",
            },
            "cross_market": {"series": {}},
        },
        regime={"compound_regime_key": "range|normal"},
    )


def _bucket(as_of: datetime) -> str:
    timestamp = as_of - timedelta(minutes=1)
    minute = (timestamp.minute // 15) * 15
    return f"{timestamp.hour:02d}:{minute:02d}"


def _history(
    *,
    as_of: datetime,
    clean_n: int = MATCHED_CLOCK_MINIMUM_N + 5,
    event_n: int = 5,
    quiet: bool = True,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    bucket = _bucket(as_of)
    weekday = as_of.weekday()
    for index in range(clean_n):
        rows.append(
            {
                "weekday_utc": weekday,
                "utc_clock_bucket_15m": bucket,
                "realized_volatility_bps": (
                    "0.35" if quiet else _text(Decimal("1.0") + Decimal(index % 4) * Decimal("0.1"))
                ),
                "range_bps": (
                    "1.0" if quiet else _text(Decimal("3.0") + Decimal(index % 4) * Decimal("0.2"))
                ),
                "event_timing_state": "outside_near_event_window",
                "observed_at_utc": (as_of - timedelta(days=index + 1)).isoformat(),
            }
        )
    for index in range(event_n):
        rows.append(
            {
                "weekday_utc": weekday,
                "utc_clock_bucket_15m": bucket,
                "realized_volatility_bps": "99",
                "range_bps": "250",
                "event_timing_state": "near_event_window",
                "observed_at_utc": (as_of - timedelta(days=clean_n + index + 1)).isoformat(),
            }
        )
    return rows


def _gc_context(
    *,
    as_of: datetime,
    pit_eligible: bool = False,
    volume_z: str = "2.6",
    spread_z: str = "2.2",
) -> dict[str, object]:
    return {
        "state": "known",
        "observed_at_utc": (as_of - timedelta(minutes=1)).isoformat(),
        "baseline_version": BASELINE_VERSION,
        "baseline_digest": "fixture-baseline-digest",
        "volume_z": volume_z,
        "spread_z": spread_z,
        "ordinary_session_activity_can_count_as_alpha": False,
        "outcome_fields_used_for_normalization": False,
        "genuine_exchange_trade_volume": True,
        "genuine_pretrade_bbo_spread": True,
        "pit_eligible": pit_eligible,
    }


def _result(
    *,
    as_of: datetime,
    event_timing: str = "outside_near_event_window",
    gc_context: dict[str, object] | None = None,
    high_activity: bool = True,
    history: list[dict[str, object]] | None = None,
    mode: str = "retrospective",
) -> dict:
    return build_session_participation_expert(
        global_environment=_environment(as_of=as_of, event_timing=event_timing),
        m1_candle_rows=_m1_rows(as_of=as_of, high_activity=high_activity, mode=mode),
        weekday_clock_history=history if history is not None else _history(as_of=as_of),
        gc_activity_context=gc_context,
    )


def test_build14_is_context_only_and_has_no_session_direction_rule() -> None:
    as_of = datetime(2026, 9, 21, 14, 0, tzinfo=UTC)
    result = _result(as_of=as_of)
    packet = result["expert_packet"]

    assert result["expert_version"] == SESSION_PARTICIPATION_EXPERT_VERSION
    assert packet["gate_id"] == SESSION_PARTICIPATION_GATE_ID
    assert packet["gate_mode"] == "context_only"
    assert packet["conclusion"] == "context_only"
    assert packet["gate_scoreable"] is False
    assert packet["internal_conviction"] is None
    assert verify_expert_gate_packet(packet)

    assert result["direction_policy"]["directional_vote_allowed"] is False
    assert result["direction_policy"]["session_direction_rule_present"] is False
    assert result["direction_policy"]["ordinary_session_activity_can_count_as_alpha"] is False
    assert all(item["role"] == "context_only" for item in packet["subcalculators"])
    assert all(item["vote"] in {"context_only", "unknown"} for item in packet["subcalculators"])


def test_build14_london_dst_transition_is_correct() -> None:
    before = datetime(2026, 3, 27, 8, 30, tzinfo=UTC)
    after = datetime(2026, 3, 30, 7, 30, tzinfo=UTC)

    before_result = _result(as_of=before)
    after_result = _result(as_of=after)

    assert before_result["session_snapshot"]["london_utc_offset_hours"] == 0
    assert after_result["session_snapshot"]["london_utc_offset_hours"] == 1
    assert before_result["session_snapshot"]["session_code"] == "london"
    assert after_result["session_snapshot"]["session_code"] == "london"


def test_build14_new_york_dst_transition_is_correct() -> None:
    before = datetime(2026, 3, 6, 13, 30, tzinfo=UTC)
    after = datetime(2026, 3, 9, 12, 30, tzinfo=UTC)

    before_result = _result(as_of=before)
    after_result = _result(as_of=after)

    assert before_result["session_snapshot"]["new_york_utc_offset_hours"] == -5
    assert after_result["session_snapshot"]["new_york_utc_offset_hours"] == -4
    assert "new_york" in before_result["session_snapshot"]["active_markets"]
    assert "new_york" in after_result["session_snapshot"]["active_markets"]


def test_build14_overlap_identifies_london_and_new_york_without_direction() -> None:
    as_of = datetime(2026, 9, 21, 14, 0, tzinfo=UTC)
    result = _result(as_of=as_of)

    snapshot = result["session_snapshot"]
    assert snapshot["overlap_state"] == "london_new_york_overlap"
    assert snapshot["active_markets"] == ["london", "new_york"]
    assert snapshot["individual_participant_identity_claimed"] is False
    assert result["direction_policy"]["directional_vote_allowed"] is False


def test_build14_matched_weekday_clock_baseline_detects_unusually_high_activity() -> None:
    as_of = datetime(2026, 9, 21, 14, 0, tzinfo=UTC)
    result = _result(as_of=as_of, high_activity=True)

    baseline = result["matched_clock_activity"]
    assert baseline["weekday_utc"] == as_of.weekday()
    assert baseline["utc_clock_bucket_15m"] == _bucket(as_of)
    assert baseline["event_clean_sample_n"] >= MATCHED_CLOCK_MINIMUM_N
    assert baseline["baseline_population"] == "event_clean_weekday_clock"
    assert baseline["state"] == "unusually_high_activity"
    assert Decimal(baseline["volatility_percentile"]) >= Decimal("0.90")
    assert Decimal(baseline["range_percentile"]) >= Decimal("0.90")


def test_build14_event_rows_are_excluded_when_enough_clean_history_exists() -> None:
    as_of = datetime(2026, 9, 21, 14, 0, tzinfo=UTC)
    history = _history(as_of=as_of, clean_n=25, event_n=10, quiet=True)
    result = _result(as_of=as_of, history=history)

    baseline = result["matched_clock_activity"]
    assert baseline["matched_sample_n"] == 35
    assert baseline["event_clean_sample_n"] == 25
    assert baseline["selected_sample_n"] == 25
    assert baseline["baseline_population"] == "event_clean_weekday_clock"


def test_build14_event_time_confounding_is_explicit() -> None:
    as_of = datetime(2026, 9, 21, 14, 0, tzinfo=UTC)
    result = _result(as_of=as_of, event_timing="near_event_window")

    confounding = result["event_confounding"]
    assert confounding["state"] == "event_time_confounded"
    assert confounding["confounded"] is True
    assert confounding["activity_attributed_to_session_only"] is False
    assert confounding["event_causal_claim"] is False
    assert result["direction_policy"]["event_proximity_is_causal_claim"] is False


def test_build14_genuine_gc_volume_spread_context_is_kept_descriptive() -> None:
    as_of = datetime(2026, 9, 21, 14, 0, tzinfo=UTC)
    result = _result(as_of=as_of, gc_context=_gc_context(as_of=as_of))

    gc = result["gc_participation"]
    assert gc["state"] == "known"
    assert gc["qualification"] == "retrospective_research_only"
    assert gc["volume_state"] == "unusually_high"
    assert gc["spread_state"] == "unusually_wide"
    assert gc["genuine_exchange_trade_volume"] is True
    assert gc["genuine_pretrade_bbo_spread"] is True
    assert gc["ordinary_session_activity_can_count_as_alpha"] is False
    assert gc["depth_claimed"] is False
    assert gc["order_book_imbalance_claimed"] is False
    assert result["direction_policy"]["directional_vote_allowed"] is False


def test_build14_pit_qualified_gc_context_is_distinguished() -> None:
    as_of = datetime(2026, 9, 21, 14, 0, tzinfo=UTC)
    result = _result(
        as_of=as_of,
        gc_context=_gc_context(as_of=as_of, pit_eligible=True),
    )
    assert result["gc_participation"]["qualification"] == "pit_qualified"
    assert result["gc_participation"]["research_only"] is False


def test_build14_unqualified_gc_context_stays_unknown() -> None:
    as_of = datetime(2026, 9, 21, 14, 0, tzinfo=UTC)
    raw = _gc_context(as_of=as_of)
    raw["ordinary_session_activity_can_count_as_alpha"] = True
    result = _result(as_of=as_of, gc_context=raw)

    assert result["gc_participation"]["state"] == "unknown"
    calc = next(
        item for item in result["expert_packet"]["subcalculators"]
        if item["calculator_id"] == "session_gc_volume_spread"
    )
    assert calc["state"] == "insufficient"
    assert calc["vote"] == "unknown"


def test_build14_insufficient_clock_history_remains_unknown() -> None:
    as_of = datetime(2026, 9, 21, 14, 0, tzinfo=UTC)
    result = _result(
        as_of=as_of,
        history=_history(as_of=as_of, clean_n=8, event_n=0),
    )
    assert result["matched_clock_activity"]["state"] == "unknown_insufficient_matched_clock_history"
    calc = next(
        item for item in result["expert_packet"]["subcalculators"]
        if item["calculator_id"] == "session_matched_clock_activity"
    )
    assert calc["vote"] == "unknown"


def test_build14_pit_mode_uses_completed_m1_and_no_future_values() -> None:
    as_of = datetime(2026, 9, 21, 14, 0, tzinfo=UTC)
    result = _result(as_of=as_of, mode="pit")
    assert result["future_values_used"] is False
    assert result["expert_packet"]["no_hindsight_attestation"]["future_values_used"] is False
    for evidence in result["expert_packet"]["evidence_inputs"]:
        assert evidence["provenance"]["future_values_used"] is False


def test_build14_chronological_freeze_ignores_future_m1_and_history_rows() -> None:
    as_of = datetime(2026, 9, 21, 14, 0, tzinfo=UTC)
    environment = _environment(as_of=as_of)
    m1 = _m1_rows(as_of=as_of, mode="pit")
    future_m1 = list(m1)
    future_m1.append(
        {
            "symbol": "XAUUSD",
            "timeframe": "M1",
            "open_time_utc": as_of,
            "open": "2400",
            "high": "2600",
            "low": "2300",
            "close": "2550",
            "source": "future_fixture",
            "load_identity": "build14-future",
            "provenance_class": "pit_observed",
            "pit_eligible": True,
            "first_observed_at": (as_of + timedelta(minutes=1)).isoformat(),
        }
    )
    history = _history(as_of=as_of)
    future_history = list(history) + [
        {
            "weekday_utc": as_of.weekday(),
            "utc_clock_bucket_15m": _bucket(as_of),
            "realized_volatility_bps": "999",
            "range_bps": "999",
            "event_timing_state": "outside_near_event_window",
            "observed_at_utc": (as_of + timedelta(minutes=1)).isoformat(),
        }
    ]

    first = build_session_participation_expert(
        global_environment=environment,
        m1_candle_rows=m1,
        weekday_clock_history=history,
    )
    second = build_session_participation_expert(
        global_environment=environment,
        m1_candle_rows=future_m1,
        weekday_clock_history=future_history,
    )
    assert first["expert_packet"]["packet_digest"] == second["expert_packet"]["packet_digest"]
    assert first["current_activity"] == second["current_activity"]
    assert first["matched_clock_activity"] == second["matched_clock_activity"]


def test_build14_rejects_session_environment_mismatch() -> None:
    as_of = datetime(2026, 9, 21, 14, 0, tzinfo=UTC)
    environment = _environment(as_of=as_of)
    environment["exact_facts"]["session"]["session_code"] = "asia"

    with pytest.raises(ValueError, match="DST-safe session code"):
        build_session_participation_expert(
            global_environment=environment,
            m1_candle_rows=_m1_rows(as_of=as_of),
            weekday_clock_history=_history(as_of=as_of),
        )
