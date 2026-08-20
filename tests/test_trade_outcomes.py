from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from aidy.context_packet import build_context_packet
from aidy.feature_engine import build_feature_packet
from aidy.trade_outcomes import (
    RESEARCH_TRADE_OUTCOMES,
    TRADE_OUTCOME_BUNDLE_VERSION,
    TRADE_OUTCOME_VERSION,
    build_trade_outcome_bundle,
    trade_outcome_distribution,
    trade_outcome_storage_row,
    verify_trade_outcome_bundle_digest,
    verify_trade_outcome_digest,
)

ANCHOR = datetime(2025, 1, 6, 12, 0, tzinfo=UTC)


def _row(
    minute: int,
    *,
    open_price: str = "2000",
    high: str = "2001",
    low: str = "1999",
    close: str = "2000",
) -> dict[str, object]:
    return {
        "research_identity": f"outcome-{minute:04d}-{open_price}-{high}-{low}-{close}",
        "provenance_class": "retrospective_history",
        "pit_eligible": False,
        "symbol": "XAUUSD",
        "timeframe": "M1",
        "open_time_utc": (ANCHOR + timedelta(minutes=minute)).isoformat(),
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "source": "histdata",
        "source_file_sha256": "a" * 64,
        "source_payload_sha256": "b" * 64,
    }


def _quiet_rows(minutes: int = 15) -> list[dict[str, object]]:
    return [_row(minute) for minute in range(1, minutes + 1)]


def _long_bundle(
    rows: list[dict[str, object]], *, horizons: tuple[int, ...] = (15,)
) -> dict[str, object]:
    return build_trade_outcome_bundle(
        anchor_time=ANCHOR,
        direction="long",
        entry="2000",
        stop_loss="1995",
        targets=("2005", "2010"),
        research_rows=rows,
        horizons_minutes=horizons,
    )


def _long_label(rows: list[dict[str, object]]) -> dict[str, object]:
    return _long_bundle(rows)["outcomes"][0]


def test_trade_geometry_is_directional_and_strict() -> None:
    with pytest.raises(ValueError, match="Long stop_loss must be below entry"):
        build_trade_outcome_bundle(
            anchor_time=ANCHOR,
            direction="long",
            entry="2000",
            stop_loss="2001",
            targets=("2005",),
            research_rows=_quiet_rows(),
            horizons_minutes=(15,),
        )
    with pytest.raises(ValueError, match="Short targets must be strictly decreasing"):
        build_trade_outcome_bundle(
            anchor_time=ANCHOR,
            direction="short",
            entry="2000",
            stop_loss="2005",
            targets=("1990", "1995"),
            research_rows=_quiet_rows(),
            horizons_minutes=(15,),
        )
    with pytest.raises(ValueError, match="between one and three targets"):
        build_trade_outcome_bundle(
            anchor_time=ANCHOR,
            direction="long",
            entry="2000",
            stop_loss="1995",
            targets=(),
            research_rows=_quiet_rows(),
            horizons_minutes=(15,),
        )


def test_long_mfe_mae_terminal_and_times_are_deterministic() -> None:
    rows = _quiet_rows()
    rows[2] = _row(3, high="2008", low="1998", close="2006")
    rows[7] = _row(8, open_price="2001", high="2002", low="1994", close="1997")
    rows[-1] = _row(15, open_price="1999", high="2003", low="1998", close="2002")
    label = _long_label(rows)
    metrics = label["metrics"]
    assert metrics["mfe_price"] == "8"
    assert metrics["mae_price"] == "6"
    assert metrics["mfe_r"] == "1.6"
    assert metrics["mae_r"] == "1.2"
    assert metrics["time_to_mfe_seconds"] == 180
    assert metrics["time_to_mae_seconds"] == 480
    assert metrics["terminal_favorable_delta"] == "2"
    assert metrics["terminal_favorable_r"] == "0.4"


def test_short_mfe_mae_are_mirrored_correctly() -> None:
    rows = _quiet_rows()
    rows[3] = _row(4, high="2002", low="1992", close="1994")
    rows[8] = _row(9, open_price="1999", high="2006", low="1998", close="2003")
    rows[-1] = _row(15, open_price="2001", high="2002", low="1996", close="1998")
    label = build_trade_outcome_bundle(
        anchor_time=ANCHOR,
        direction="short",
        entry="2000",
        stop_loss="2005",
        targets=("1995", "1990"),
        research_rows=rows,
        horizons_minutes=(15,),
    )["outcomes"][0]
    metrics = label["metrics"]
    assert metrics["mfe_price"] == "8"
    assert metrics["mae_price"] == "6"
    assert metrics["mfe_r"] == "1.6"
    assert metrics["mae_r"] == "1.2"
    assert metrics["terminal_favorable_delta"] == "2"


def test_target_before_stop_order_and_time_to_levels() -> None:
    rows = _quiet_rows()
    rows[2] = _row(3, high="2006", low="1999", close="2004")
    rows[6] = _row(7, open_price="1998", high="1999", low="1994", close="1996")
    label = _long_label(rows)
    levels = label["level_analysis"]
    assert levels["stop_target_order"] == "target_before_stop"
    assert levels["events"]["target_1"]["first_hit_minute"] == 3
    assert levels["events"]["target_1"]["time_to_level_seconds"] == 180
    assert levels["events"]["stop"]["first_hit_minute"] == 7
    assert levels["targets_strictly_before_stop"] == 1


def test_stop_before_target_order_is_preserved() -> None:
    rows = _quiet_rows()
    rows[1] = _row(2, high="2001", low="1994", close="1996")
    rows[8] = _row(9, open_price="2003", high="2006", low="2002", close="2005")
    label = _long_label(rows)
    assert label["outcome_state"] == "stop_before_any_target"
    assert label["level_analysis"]["targets_strictly_before_stop"] == 0


def test_same_bar_stop_and_target_is_order_unknown() -> None:
    rows = _quiet_rows()
    rows[4] = _row(5, high="2006", low="1994", close="2000")
    label = _long_label(rows)
    levels = label["level_analysis"]
    assert label["outcome_state"] == "same_bar_order_unknown"
    assert levels["intrabar_order_state"] == "ambiguous"
    assert levels["ambiguous_first_hit_groups"] == [
        {"minute": 5, "levels": ["stop", "target_1"]}
    ]
    assert levels["targets_strictly_before_stop"] == 0


def test_multiple_targets_first_hit_same_bar_remain_intrabar_ambiguous() -> None:
    rows = _quiet_rows()
    rows[5] = _row(6, high="2011", low="1999", close="2008")
    label = _long_label(rows)
    levels = label["level_analysis"]
    assert levels["stop_target_order"] == "target_only"
    assert levels["intrabar_order_state"] == "ambiguous"
    assert levels["ambiguous_first_hit_groups"] == [
        {"minute": 6, "levels": ["target_1", "target_2"]}
    ]


def test_incomplete_horizon_fails_closed_without_partial_hit_claims() -> None:
    rows = [
        row
        for row in _quiet_rows()
        if row["open_time_utc"] != (ANCHOR + timedelta(minutes=7)).isoformat()
    ]
    label = _long_label(rows)
    assert label["coverage_state"] == "incomplete"
    assert label["outcome_state"] == "unknown"
    assert label["metrics"]["expected_rows"] == 15
    assert label["metrics"]["observed_rows"] == 14
    assert label["metrics"]["missing_minutes"] == [7]
    assert label["level_analysis"] == {"state": "unknown_due_incomplete_horizon"}
    assert label["path_behavior"] == {"path_class": "unknown"}


def test_same_evidence_is_deterministic_under_input_reordering() -> None:
    rows = _quiet_rows()
    rows[4] = _row(5, high="2007", low="1999", close="2005")
    first = _long_bundle(rows)
    second = _long_bundle(list(reversed(rows)))
    assert first == second
    assert verify_trade_outcome_bundle_digest(first) is True
    assert verify_trade_outcome_digest(first["outcomes"][0]) is True


def test_path_behavior_reuses_move_detective_without_causal_claims() -> None:
    rows = _quiet_rows()
    rows[2] = _row(3, high="2006", low="1999", close="2003")
    rows[9] = _row(10, open_price="1998", high="1999", low="1994", close="1996")
    label = _long_label(rows)
    assert label["path_behavior"]["path_class"] == "reversal_up_to_down"
    assert label["realized_pnl_included"] is False


def test_outcomes_are_future_only_and_storage_contract_is_separate() -> None:
    bundle = _long_bundle(_quiet_rows(60), horizons=(15, 60))
    assert bundle["trade_outcome_bundle_version"] == TRADE_OUTCOME_BUNDLE_VERSION
    assert bundle["evaluation_only"] is True
    assert bundle["future_derived"] is True
    assert bundle["pit_eligible"] is False
    assert bundle["decision_input_allowed"] is False
    assert bundle["realized_pnl_included"] is False
    assert bundle["available_after_utc"] == (ANCHOR + timedelta(minutes=60)).isoformat()

    field_names = {field.name for field in RESEARCH_TRADE_OUTCOMES.fields}
    assert RESEARCH_TRADE_OUTCOMES.name == "research_trade_outcomes"
    assert "first_observed_at" not in field_names
    assert "pit_eligible" in field_names
    assert "available_after_utc" in field_names
    row = trade_outcome_storage_row(bundle["outcomes"][0])
    assert row["outcome_version"] == TRADE_OUTCOME_VERSION
    assert row["pit_eligible"] is False
    assert row["realized_pnl_included"] is False


def test_future_trade_outcome_bundle_cannot_enter_day10_context() -> None:
    bundle = _long_bundle(_quiet_rows())
    feature = build_feature_packet(
        as_of=ANCHOR,
        symbol="XAUUSD",
        candle_rows=[],
        mode="pit",
        snapshot=None,
    )
    with pytest.raises(ValueError, match="Unsupported AIDY signal-state fields"):
        build_context_packet(
            as_of=ANCHOR,
            symbol="XAUUSD",
            feature_packet=feature,
            event_rows=[],
            macro_evidence_state="known",
            cross_market_rows=[],
            aidy_signal_state=bundle,
        )


def test_research_boundary_and_revision_selection_are_fail_closed() -> None:
    pit_row = deepcopy(_quiet_rows()[0])
    pit_row["pit_eligible"] = True
    with pytest.raises(ValueError, match="pit_eligible=false"):
        _long_label([pit_row, *_quiet_rows()[1:]])

    wrong = deepcopy(_quiet_rows()[0])
    wrong["provenance_class"] = "pit_observed"
    with pytest.raises(ValueError, match="retrospective_history"):
        _long_label([wrong, *_quiet_rows()[1:]])

    duplicate = deepcopy(_quiet_rows()[0])
    duplicate["research_identity"] = "alternate-revision"
    with pytest.raises(ValueError, match="one explicitly selected research revision"):
        _long_label([*_quiet_rows(), duplicate])


def test_distribution_and_digest_guards_are_deterministic() -> None:
    quiet = _long_label(_quiet_rows())
    target_rows = _quiet_rows()
    target_rows[2] = _row(3, high="2006", low="1999", close="2004")
    target = _long_label(target_rows)
    first = trade_outcome_distribution([quiet, target])
    second = trade_outcome_distribution([target, quiet])
    assert first == second
    assert first["outcome_count"] == 2
    assert first["coverage_counts"] == {"complete": 2}
    assert first["realized_pnl_included"] is False
    assert first["outcome_causality_included"] is False

    tampered = deepcopy(quiet)
    tampered["outcome_state"] = "target_only"
    assert verify_trade_outcome_digest(tampered) is False
    with pytest.raises(ValueError, match="valid Day 13 trade outcomes"):
        trade_outcome_storage_row(tampered)
    with pytest.raises(ValueError, match="invalid trade outcome digest"):
        trade_outcome_distribution([tampered])
