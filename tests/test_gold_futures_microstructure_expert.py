from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from aidy.cme_contract_intelligence import (
    build_contract_calendar_observation,
    build_daily_contract_records,
    parse_cme_gold_bulletin_text,
)
from aidy.gc_microstructure import (
    MinuteMicrostructure,
    build_weekday_clock_baseline,
    normalize_minute,
)
from aidy.gold_cycle_environment import build_cycle_environment
from aidy.gold_expert_gate_contract import verify_expert_gate_packet
from aidy.gold_futures_microstructure_expert import (
    FUTURES_MICROSTRUCTURE_EXPERT_VERSION,
    FUTURES_MICROSTRUCTURE_GATE_ID,
    INCREMENTAL_HOLDOUT_MINIMUM_N,
    build_futures_microstructure_expert,
    summarise_incremental_holdout,
)

AS_OF = datetime(2026, 8, 24, 15, 1, tzinfo=UTC)
_BULLETIN = """
PG62 BULLETIN # 166@ Fri, Aug 21, 2026 CME GROUP
FINAL
GC FUT COMEX GOLD FUTURES
AUG26 4310.00 4320.00 4300.00 4315.00 + 107.80 120 1000 + 10
SEP26 4320.00 4330.00 4310.00 4325.00 - 5.00 90 800 - 20
DEC26 4380.00 4400.00 4370.00 4390.00 + 109.20 5000 180000 + 3082
TOTAL GC FUT 5210 181800 + 3072
""".strip()


def _environment() -> dict:
    return build_cycle_environment(
        as_of_utc=AS_OF,
        target_window_start_utc=AS_OF + timedelta(minutes=15),
        session_code="london_new_york_overlap",
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
                    "5m": {"direction": "up", "return_bps": "2"},
                    "15m": {"direction": "up", "return_bps": "4"},
                    "60m": {"direction": "up", "return_bps": "6"},
                },
            },
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


def _minute(
    *,
    stamp: datetime,
    contract: str = "GCZ26",
    volume: str = "160",
    spread_bps: str = "1.6",
    signed: str | None = "0.65",
    distance_bps: str = "2.0",
) -> MinuteMicrostructure:
    anchored = Decimal("4390")
    last = anchored * (Decimal(1) + Decimal(distance_bps) / Decimal(10000))
    signed_value = None if signed is None else Decimal(signed)
    known_volume = Decimal("120") if signed_value is not None else Decimal(0)
    buy = (
        known_volume * (Decimal(1) + signed_value) / Decimal(2)
        if signed_value is not None
        else Decimal(0)
    )
    sell = (
        known_volume * (Decimal(1) - signed_value) / Decimal(2)
        if signed_value is not None
        else Decimal(0)
    )
    total = Decimal(volume)
    unknown = total - known_volume
    return MinuteMicrostructure(
        minute_utc=stamp,
        contract_symbol=contract,
        session="london_new_york_overlap",
        trade_count=20,
        trade_volume=total,
        buy_aggressor_volume=buy,
        sell_aggressor_volume=sell,
        unknown_side_volume=unknown,
        known_side_volume=known_volume,
        signed_trade_imbalance=signed_value,
        vwap=Decimal("4390.5"),
        last_trade_price=last,
        mean_spread_bps=Decimal(spread_bps),
        median_spread_bps=Decimal(spread_bps),
        session_vwap=anchored,
        anchored_vwap=anchored,
        anchor_identity=f"{contract}:{stamp.date().isoformat()}:london_new_york_overlap",
        source_trade_digests=(f"{stamp.toordinal():064x}",),
    )


def _historical_minutes() -> list[MinuteMicrostructure]:
    base = datetime(2026, 4, 6, 15, 0, tzinfo=UTC)
    return [
        _minute(
            stamp=base + timedelta(weeks=index),
            volume=str(100 + index),
            spread_bps=str(Decimal("1.0") + Decimal(index) / Decimal(100)),
            signed=str(Decimal("0.05") + Decimal(index) / Decimal(1000)),
            distance_bps=str(Decimal("0.4") + Decimal(index) / Decimal(100)),
        )
        for index in range(20)
    ]


def _micro_inputs(
    *,
    contract: str = "GCZ26",
    signed: str | None = "0.65",
) -> tuple[dict, dict, dict]:
    baseline = build_weekday_clock_baseline(_historical_minutes())
    current = _minute(
        stamp=AS_OF - timedelta(minutes=1),
        contract=contract,
        volume="180",
        spread_bps="1.8",
        signed=signed,
        distance_bps="2.5",
    )
    normalized = normalize_minute(current, baseline)
    return current.as_dict(), normalized, baseline


def _daily_records() -> list[dict]:
    snapshot = parse_cme_gold_bulletin_text(
        _BULLETIN,
        source_bytes=b"%PDF-build17",
        first_observed_at=datetime(2026, 8, 22, 16, tzinfo=UTC),
    )
    return build_daily_contract_records(snapshot)


def _calendar() -> list[dict]:
    return [
        build_contract_calendar_observation(
            contract_code="GCQ26",
            contract_month="2026-08-01",
            first_notice_date="2026-07-31",
            last_trade_date="2026-08-27",
            first_delivery_date=None,
            last_delivery_date=None,
            first_observed_at=datetime(2026, 8, 22, 16, tzinfo=UTC),
            source_document_sha256="a" * 64,
        )
    ]


def _split() -> dict[str, object]:
    return {
        "manifest_version": "aidy_chronological_split_manifest_v1",
        "split_digest": "b" * 64,
        "purge_required": True,
        "embargo_required": True,
        "holdout_tuning_allowed": False,
    }


def _positive_holdout() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for index in range(40):
        rows.append(
            {
                "independent_episode_id": f"episode-{index}",
                "split": "holdout",
                "spot_ohlc_correct": 1 if index < 24 else 0,
                "spot_plus_microstructure_correct": 1 if index < 30 else 0,
            }
        )
    return rows


def _build(
    *,
    contract: str = "GCZ26",
    signed: str | None = "0.65",
    holdout: list[dict[str, object]] | None = None,
) -> dict:
    minute, normalized, baseline = _micro_inputs(contract=contract, signed=signed)
    return build_futures_microstructure_expert(
        global_environment=_environment(),
        current_microstructure_minute=minute,
        normalized_microstructure=normalized,
        weekday_clock_baseline=baseline,
        daily_contract_records=_daily_records(),
        contract_calendar_records=_calendar(),
        retrospective_holdout_rows=holdout or _positive_holdout(),
        holdout_split_binding=_split(),
    )


def test_build17_is_context_only_research_phase_a() -> None:
    result = _build()
    packet = result["expert_packet"]

    assert result["expert_version"] == FUTURES_MICROSTRUCTURE_EXPERT_VERSION
    assert packet["gate_id"] == FUTURES_MICROSTRUCTURE_GATE_ID
    assert packet["gate_mode"] == "context_only"
    assert packet["conclusion"] == "context_only"
    assert packet["gate_scoreable"] is False
    assert packet["internal_conviction"] is None
    assert verify_expert_gate_packet(packet)
    assert result["research_phase"] == "phase_a_retrospective"
    assert result["statistically_validated"] is False
    assert result["formal_forward_evidence_created"] is False
    assert result["paid_feed_activated"] is False
    assert result["live_money_execution_allowed"] is False


def test_build17_genuine_tbbo_feature_definition_matches_entitlement() -> None:
    result = _build()
    feature = result["microstructure"]
    entitlement = result["entitlement_contract"]

    assert entitlement["provider"] == "Databento"
    assert entitlement["dataset"] == "GLBX.MDP3"
    assert entitlement["schema"] == "tbbo"
    assert entitlement["historical_phase_a_only"] is True
    assert "genuine_trade_volume" in entitlement["approved_features"]
    assert "pretrade_best_bid_ask_spread" in entitlement["approved_features"]
    assert "known_aggressor_signed_trade_flow" in entitlement["approved_features"]
    assert "trade_price_size_vwap" in entitlement["approved_features"]
    assert feature["genuine_trade_volume"] is True
    assert feature["genuine_pretrade_bbo_spread"] is True
    assert feature["unknown_aggressor_side_imputed"] is False


def test_build17_no_depth_or_order_book_imbalance_claim() -> None:
    result = _build()
    entitlement = result["entitlement_contract"]
    feature = result["microstructure"]

    assert entitlement["bid_ask_sizes_do_not_authorize_depth_claim"] is True
    assert entitlement["full_depth_claimed"] is False
    assert entitlement["order_book_imbalance_claimed"] is False
    assert entitlement["l2_claimed"] is False
    assert entitlement["l3_claimed"] is False
    assert entitlement["mbo_claimed"] is False
    assert entitlement["mbp10_claimed"] is False
    assert feature["depth_claimed"] is False
    assert feature["order_book_imbalance_claimed"] is False


def test_build17_clock_normalised_volume_spread_flow_vwap_are_explicit() -> None:
    result = _build()
    feature = result["microstructure"]

    assert feature["state"] == "known"
    assert feature["volume_z"] is not None
    assert feature["spread_z"] is not None
    assert feature["signed_trade_imbalance_z"] is not None
    assert feature["vwap_distance_z"] is not None
    assert feature["volume_state"] in {"high_volume", "extreme_high_volume"}
    assert feature["spread_state"] in {"wide_spread", "extreme_wide_spread"}
    assert feature["flow_state"] == "buy_aggressor_dominant"
    assert feature["vwap_state"] in {"above_vwap", "extreme_above_vwap"}


def test_build17_unknown_aggressor_side_remains_unknown() -> None:
    result = _build(signed=None)
    feature = result["microstructure"]

    assert feature["signed_trade_imbalance"] is None
    assert feature["flow_state"] == "unknown_aggressor_side_insufficient"
    assert feature["unknown_aggressor_side_imputed"] is False


def test_build17_official_cme_roll_and_oi_are_daily_not_intraday() -> None:
    result = _build()
    roll = result["contract_roll_oi"]

    assert roll["state"] == "known"
    assert roll["active_contract"] == "GCZ26"
    assert roll["roll_state"] == "post_first_notice_active_shifted"
    assert roll["active_contract_alignment"] == "aligned_to_active_contract"
    assert roll["open_interest_frequency"] == "daily_t_plus_1"
    assert roll["open_interest_is_intraday"] is False
    assert roll["intraday_open_interest_inferred"] is False


def test_build17_contract_mismatch_is_explicit() -> None:
    result = _build(contract="GCU26")
    assert (
        result["contract_roll_oi"]["active_contract_alignment"]
        == "micro_contract_differs_from_oi_leader"
    )


def test_build17_retrospective_holdout_shows_incremental_value_without_promotion() -> None:
    result = _build()
    holdout = result["incremental_holdout"]

    assert holdout["state"] == "incremental_value_observed"
    assert holdout["sample_n"] == 40
    assert holdout["spot_ohlc_accuracy"] == "0.600000"
    assert holdout["spot_plus_microstructure_accuracy"] == "0.750000"
    assert holdout["incremental_accuracy"] == "0.150000"
    assert holdout["statistically_validated"] is False
    assert holdout["gate_promoted"] is False
    assert holdout["live_weight_granted"] is False
    assert holdout["paid_feed_activation_allowed"] is False


def test_build17_null_holdout_is_retained_without_promotion() -> None:
    rows = [
        {
            "independent_episode_id": f"null-{index}",
            "split": "holdout",
            "spot_ohlc_correct": index % 2,
            "spot_plus_microstructure_correct": index % 2,
        }
        for index in range(INCREMENTAL_HOLDOUT_MINIMUM_N)
    ]
    summary = summarise_incremental_holdout(rows, split_binding=_split())

    assert summary["state"] == "null_no_incremental_value"
    assert summary["incremental_accuracy"] == "0.000000"
    assert summary["gate_promoted"] is False
    assert summary["paid_feed_activation_allowed"] is False


def test_build17_underperformance_is_retained_without_promotion() -> None:
    rows = [
        {
            "independent_episode_id": f"bad-{index}",
            "split": "holdout",
            "spot_ohlc_correct": 1 if index < 24 else 0,
            "spot_plus_microstructure_correct": 1 if index < 18 else 0,
        }
        for index in range(40)
    ]
    summary = summarise_incremental_holdout(rows, split_binding=_split())

    assert summary["state"] == "microstructure_underperformed_spot"
    assert Decimal(summary["incremental_accuracy"]) < 0
    assert summary["gate_promoted"] is False


def test_build17_insufficient_holdout_is_unknown_to_gate() -> None:
    result = _build(holdout=_positive_holdout()[:5])
    holdout = result["incremental_holdout"]
    calc = next(
        item
        for item in result["expert_packet"]["subcalculators"]
        if item["calculator_id"] == "futures_incremental_holdout"
    )

    assert holdout["state"] == "insufficient"
    assert calc["state"] == "insufficient"
    assert calc["vote"] == "unknown"


def test_build17_holdout_requires_purge_embargo_and_no_tuning() -> None:
    bad = _split()
    bad["purge_required"] = False
    with pytest.raises(ValueError, match="purge"):
        summarise_incremental_holdout(_positive_holdout(), split_binding=bad)

    bad = _split()
    bad["embargo_required"] = False
    with pytest.raises(ValueError, match="embargo"):
        summarise_incremental_holdout(_positive_holdout(), split_binding=bad)

    bad = _split()
    bad["holdout_tuning_allowed"] = True
    with pytest.raises(ValueError, match="tune"):
        summarise_incremental_holdout(_positive_holdout(), split_binding=bad)


def test_build17_phase_b_paid_activation_is_off_and_owner_gated() -> None:
    policy = _build()["phase_b_policy"]

    assert policy["status"] == "not_activated"
    assert policy["live_or_delayed_paid_feed_enabled"] is False
    assert policy["recurring_paid_data_enabled"] is False
    assert policy["owner_approval_required"] is True
    assert policy["price_and_entitlement_review_required"] is True
    assert policy["pit_contract_required_before_live_use"] is True
    assert policy["phase_a_incremental_value_required"] is True
    assert policy["feature_count_alone_can_justify_activation"] is False


def test_build17_rejects_tampered_depth_claim() -> None:
    minute, normalized, baseline = _micro_inputs()
    minute["depth_claimed"] = True

    with pytest.raises(ValueError, match="genuine Day-42"):
        build_futures_microstructure_expert(
            global_environment=_environment(),
            current_microstructure_minute=minute,
            normalized_microstructure=normalized,
            weekday_clock_baseline=baseline,
            daily_contract_records=_daily_records(),
            contract_calendar_records=_calendar(),
            retrospective_holdout_rows=_positive_holdout(),
            holdout_split_binding=_split(),
        )


def test_build17_rejects_future_microstructure_minute() -> None:
    minute, normalized, baseline = _micro_inputs()
    minute["minute_utc"] = (AS_OF + timedelta(minutes=1)).isoformat()

    with pytest.raises(ValueError, match="future"):
        build_futures_microstructure_expert(
            global_environment=_environment(),
            current_microstructure_minute=minute,
            normalized_microstructure=normalized,
            weekday_clock_baseline=baseline,
            daily_contract_records=_daily_records(),
            contract_calendar_records=_calendar(),
            retrospective_holdout_rows=_positive_holdout(),
            holdout_split_binding=_split(),
        )


def test_build17_build3_environment_specific_trust_scopes_exist() -> None:
    result = _build()
    scope_types = {scope["scope_type"] for scope in result["trust_scopes"]}

    assert "mini_exact" in scope_types
    assert "mini_reduced_microstructure_state" in scope_types
    assert "mini_reduced_roll_context" in scope_types
    assert "mini_reduced_incremental_value" in scope_types
