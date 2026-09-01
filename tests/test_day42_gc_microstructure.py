from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from aidy.gc_microstructure import (
    BASELINE_VERSION,
    J2_VERSION,
    J3_RICH_VERSION,
    MicrostructureError,
    MinuteMicrostructure,
    aggregate_tbbo_minutes,
    build_weekday_clock_baseline,
    day42_experiment_plan,
    normalize_minute,
    parse_databento_tbbo_jsonl,
    run_shadow_experiment,
    verify_weekday_clock_baseline,
)

BASE = datetime(2026, 8, 28, 15, 0, tzinfo=UTC)
CONTRACT_MAP = {12345: "GCZ6"}


def _row(
    *,
    second: int,
    side: str,
    price: str,
    size: int,
    bid: str = "4499.9",
    ask: str = "4500.1",
    instrument_id: int = 12345,
) -> dict[str, object]:
    return {
        "hd": {
            "ts_event": (BASE + timedelta(seconds=second)).isoformat(),
            "instrument_id": instrument_id,
        },
        "action": "T",
        "side": side,
        "price": price,
        "size": size,
        "levels": [{"bid_px": bid, "ask_px": ask, "bid_sz": 12, "ask_sz": 15}],
    }


def _minute(
    *,
    index: int,
    volume: str,
    spread_bps: str,
    signed: str,
    distance_bps: str,
) -> MinuteMicrostructure:
    minute = datetime(2026, 1, 5, 15, 0, tzinfo=UTC) + timedelta(weeks=index)
    anchored = Decimal(4500)
    last = anchored * (Decimal(1) + Decimal(distance_bps) / Decimal(10000))
    return MinuteMicrostructure(
        minute_utc=minute,
        contract_symbol="GCG6",
        session="london_new_york_overlap",
        trade_count=3,
        trade_volume=Decimal(volume),
        buy_aggressor_volume=Decimal(2),
        sell_aggressor_volume=Decimal(1),
        unknown_side_volume=Decimal(0),
        known_side_volume=Decimal(3),
        signed_trade_imbalance=Decimal(signed),
        vwap=Decimal(4500),
        last_trade_price=last,
        mean_spread_bps=Decimal(spread_bps),
        median_spread_bps=Decimal(spread_bps),
        session_vwap=anchored,
        anchored_vwap=anchored,
        anchor_identity=f"GCG6:{minute.date().isoformat()}:london_new_york_overlap",
        source_trade_digests=(f"{index:064x}",),
    )


def _split_binding() -> dict[str, object]:
    return {
        "manifest_version": "aidy_chronological_split_manifest_v1",
        "split_digest": "a" * 64,
        "purge_required": True,
        "embargo_required": True,
        "holdout_tuning_allowed": False,
    }


def test_tbbo_parser_uses_genuine_trade_and_pretrade_bbo() -> None:
    payload = json.dumps(_row(second=1, side="B", price="4500.0", size=3))
    trade = parse_databento_tbbo_jsonl(payload, contract_by_instrument_id=CONTRACT_MAP)[0]
    assert trade.contract_symbol == "GCZ6"
    assert trade.price == Decimal("4500.0")
    assert trade.size == Decimal(3)
    assert trade.aggressor_side == "B"
    assert trade.bid == Decimal("4499.9")
    assert trade.ask == Decimal("4500.1")
    assert trade.signed_volume == Decimal(3)
    assert trade.as_dict()["depth_claimed"] is False
    assert trade.as_dict()["order_book_imbalance_claimed"] is False


def test_tbbo_unknown_aggressor_side_is_never_imputed() -> None:
    payload = json.dumps(_row(second=2, side="N", price="4500.0", size=2))
    trade = parse_databento_tbbo_jsonl(payload, contract_by_instrument_id=CONTRACT_MAP)[0]
    assert trade.aggressor_side == "N"
    assert trade.signed_volume is None
    assert trade.as_dict()["aggressor_side_unknown_never_imputed"] is True


def test_tbbo_non_trade_action_fails_closed() -> None:
    row = _row(second=3, side="B", price="4500", size=1)
    row["action"] = "A"
    with pytest.raises(MicrostructureError, match="non-trade"):
        parse_databento_tbbo_jsonl(json.dumps(row), contract_by_instrument_id=CONTRACT_MAP)


def test_tbbo_crossed_bbo_fails_closed() -> None:
    payload = json.dumps(
        _row(second=4, side="A", price="4500", size=1, bid="4500.2", ask="4500.1")
    )
    with pytest.raises(MicrostructureError, match="ask"):
        parse_databento_tbbo_jsonl(payload, contract_by_instrument_id=CONTRACT_MAP)


def test_tbbo_contract_identity_conflict_fails_closed() -> None:
    row = _row(second=5, side="B", price="4500", size=1)
    row["symbol"] = "GCG7"
    with pytest.raises(MicrostructureError, match="conflict"):
        parse_databento_tbbo_jsonl(json.dumps(row), contract_by_instrument_id=CONTRACT_MAP)


def test_tbbo_requires_raw_contract_mapping() -> None:
    payload = json.dumps(_row(second=6, side="B", price="4500", size=1))
    with pytest.raises(MicrostructureError, match="instrument-to-GC"):
        parse_databento_tbbo_jsonl(payload, contract_by_instrument_id={})


def test_minute_features_use_trade_size_price_and_known_aggressor_flow() -> None:
    payload = "\n".join(
        json.dumps(row)
        for row in (
            _row(second=1, side="B", price="4500", size=2),
            _row(second=10, side="A", price="4502", size=1),
            _row(second=20, side="N", price="4501", size=3),
        )
    )
    minute = aggregate_tbbo_minutes(
        parse_databento_tbbo_jsonl(payload, contract_by_instrument_id=CONTRACT_MAP)
    )[0]
    assert minute.trade_count == 3
    assert minute.trade_volume == Decimal(6)
    assert minute.buy_aggressor_volume == Decimal(2)
    assert minute.sell_aggressor_volume == Decimal(1)
    assert minute.unknown_side_volume == Decimal(3)
    assert minute.known_side_volume == Decimal(3)
    assert minute.signed_trade_imbalance == Decimal(1) / Decimal(3)
    assert minute.vwap == Decimal(27005) / Decimal(6)
    assert minute.unknown_side_fraction == Decimal("0.5")
    assert minute.as_dict()["genuine_exchange_trade_volume"] is True
    assert minute.as_dict()["signed_trade_flow_only"] is True


def test_session_vwap_is_deterministic_and_cumulative_inside_session() -> None:
    payload = "\n".join(
        [
            json.dumps(_row(second=1, side="B", price="4500", size=1)),
            json.dumps(
                {
                    **_row(second=61, side="B", price="4504", size=1),
                    "hd": {
                        "ts_event": (BASE + timedelta(seconds=61)).isoformat(),
                        "instrument_id": 12345,
                    },
                }
            ),
        ]
    )
    rows = aggregate_tbbo_minutes(
        parse_databento_tbbo_jsonl(payload, contract_by_instrument_id=CONTRACT_MAP)
    )
    assert len(rows) == 2
    assert rows[0].session == rows[1].session
    assert rows[0].anchored_vwap == Decimal(4500)
    assert rows[1].anchored_vwap == Decimal(4502)
    assert rows[0].anchor_identity == rows[1].anchor_identity


def _baseline_minutes() -> list[MinuteMicrostructure]:
    return [
        _minute(
            index=index,
            volume=str(100 + index),
            spread_bps=str(Decimal(1) + Decimal(index) / Decimal(100)),
            signed=str(Decimal("0.1") + Decimal(index) / Decimal(1000)),
            distance_bps=str(Decimal("0.5") + Decimal(index) / Decimal(100)),
        )
        for index in range(20)
    ]


def test_weekday_clock_baseline_is_frozen_without_outcomes() -> None:
    minutes = _baseline_minutes()
    baseline = build_weekday_clock_baseline(minutes)
    assert verify_weekday_clock_baseline(baseline)
    assert baseline["baseline_version"] == BASELINE_VERSION
    assert baseline["outcome_fields_used"] is False
    assert baseline["ordinary_session_activity_can_count_as_alpha"] is False
    bucket = baseline["groups"]["0:60"]
    assert bucket["volume"]["state"] == "known"
    assert bucket["spread_bps"]["state"] == "known"


def test_normalization_uses_matching_weekday_clock_bucket() -> None:
    minutes = _baseline_minutes()
    baseline = build_weekday_clock_baseline(minutes)
    normalized = normalize_minute(minutes[-1], baseline)
    assert normalized["state"] == "known"
    assert normalized["baseline_key"] == "0:60"
    assert normalized["volume_z"] is not None
    assert normalized["spread_z"] is not None
    assert normalized["ordinary_session_activity_can_count_as_alpha"] is False
    assert normalized["outcome_fields_used_for_normalization"] is False


def test_experiment_plan_freezes_j2_j3_and_rejects_depth() -> None:
    plan = day42_experiment_plan()
    assert plan["j2_version"] == J2_VERSION
    assert plan["j3_version"] == J3_RICH_VERSION
    assert plan["purge_required"] is True
    assert plan["embargo_required"] is True
    assert plan["day32_trial_registry_required"] is True
    assert plan["ordinary_session_activity_can_count_as_alpha"] is False
    assert plan["null_or_insufficient_result_allowed"] is True
    assert plan["single_result_can_promote_gate"] is False
    assert plan["depth_claimed"] is False
    assert plan["order_book_imbalance_claimed"] is False
    assert plan["mbo_allowed"] is False


def test_shadow_experiment_retains_insufficient_result_without_gate() -> None:
    rows = [
        {"independent_episode_id": "episode-1", "incremental_statistic": "0.2"},
        {"independent_episode_id": "episode-1", "incremental_statistic": "99"},
    ]
    result = run_shadow_experiment(
        experiment="J2", eligible_rows=rows, split_binding=_split_binding()
    )
    assert result["effective_independent_n"] == 1
    assert result["result_state"] == "insufficient"
    assert result["gate_promoted"] is False
    assert result["proposed_trading_gate"] is None


def test_shadow_experiment_can_report_preregistered_null() -> None:
    rows = [
        {"independent_episode_id": f"episode-{index}", "incremental_statistic": "0"}
        for index in range(30)
    ]
    result = run_shadow_experiment(
        experiment="J3", eligible_rows=rows, split_binding=_split_binding()
    )
    assert result["effective_independent_n"] == 30
    assert result["result_state"] == "null"
    assert result["mean_incremental_statistic"] == "0"
    assert result["predictive_edge_claimed"] is False


def test_non_null_shadow_result_still_cannot_promote_gate() -> None:
    rows = [
        {"independent_episode_id": f"episode-{index}", "incremental_statistic": "0.1"}
        for index in range(30)
    ]
    result = run_shadow_experiment(
        experiment="J2", eligible_rows=rows, split_binding=_split_binding()
    )
    assert result["result_state"] == "descriptive_non_null"
    assert result["gate_promoted"] is False
    assert result["features_shadow_only"] is True
    assert result["formal_forward_evidence_created"] is False


def test_shadow_experiment_rejects_unpurged_or_tuning_holdout_contract() -> None:
    binding = _split_binding()
    binding["purge_required"] = False
    with pytest.raises(MicrostructureError, match="purge"):
        run_shadow_experiment(experiment="J2", eligible_rows=[], split_binding=binding)

    binding = _split_binding()
    binding["holdout_tuning_allowed"] = True
    with pytest.raises(MicrostructureError, match="holdout"):
        run_shadow_experiment(experiment="J3", eligible_rows=[], split_binding=binding)
