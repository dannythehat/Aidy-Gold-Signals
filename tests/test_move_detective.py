from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from aidy.context_packet import build_context_packet
from aidy.feature_engine import build_feature_packet
from aidy.move_detective import (
    MOVE_BUNDLE_VERSION,
    MOVE_LABEL_VERSION,
    RESEARCH_MOVE_LABELS,
    build_move_bundle,
    move_label_distribution,
    move_label_storage_row,
    verify_move_bundle_digest,
    verify_move_label_digest,
)

ANCHOR = datetime(2025, 1, 6, 12, 0, tzinfo=UTC)
ANCHOR_PRICE = Decimal(2000)


def _row(
    minute: int,
    *,
    open_price: str = "2000",
    high: str = "2001",
    low: str = "1999",
    close: str = "2000",
) -> dict[str, object]:
    return {
        "research_identity": f"research-{minute:04d}-{open_price}-{high}-{low}-{close}",
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


def _directional_up_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    previous = Decimal(2000)
    for minute in range(1, 16):
        close = Decimal(2000) + Decimal(minute) * Decimal("0.7")
        high = max(previous, close) + Decimal("0.2")
        low = min(previous, close) - Decimal("0.2")
        rows.append(
            _row(
                minute,
                open_price=str(previous),
                high=str(high),
                low=str(low),
                close=str(close),
            )
        )
        previous = close
    return rows


def _spike_up_reverted_rows() -> list[dict[str, object]]:
    rows = _quiet_rows()
    rows[4] = _row(5, high="2010", low="1999.5", close="2004")
    rows[5] = _row(6, open_price="2004", high="2004.5", low="2002", close="2002.5")
    rows[6] = _row(7, open_price="2002.5", high="2003", low="2001", close="2001.5")
    rows[-1] = _row(15, open_price="2000.5", high="2001.5", low="1999.5", close="2001")
    return rows


def _reversal_rows(*, same_bar: bool = False) -> list[dict[str, object]]:
    rows = _quiet_rows()
    if same_bar:
        rows[4] = _row(5, high="2006", low="1994", close="2000")
        return rows
    rows[2] = _row(3, high="2006", low="1999", close="2002")
    rows[3] = _row(4, open_price="2002", high="2003", low="2000", close="2001")
    rows[9] = _row(10, high="2000", low="1994", close="1996")
    rows[-1] = _row(15, open_price="1996", high="1997", low="1994.5", close="1995")
    return rows


def _label(rows: list[dict[str, object]]) -> dict[str, object]:
    return build_move_bundle(
        anchor_time=ANCHOR,
        anchor_price=ANCHOR_PRICE,
        research_rows=rows,
        horizons_minutes=(15,),
    )["labels"][0]


def test_fixture_paths_classify_quiet_directional_spike_and_reversal() -> None:
    assert _label(_quiet_rows())["path_class"] == "quiet"
    assert _label(_directional_up_rows())["path_class"] == "directional_up"
    assert _label(_spike_up_reverted_rows())["path_class"] == "spike_up_reverted"
    assert _label(_reversal_rows())["path_class"] == "reversal_up_to_down"
    assert _label(_reversal_rows(same_bar=True))["path_class"] == (
        "two_sided_intrabar_order_unknown"
    )


def test_exact_meaningful_threshold_is_inclusive() -> None:
    rows = _quiet_rows()
    for minute in range(8, 16):
        rows[minute - 1] = _row(
            minute,
            open_price="2002",
            high="2005",
            low="1999.5",
            close="2003",
        )
    label = _label(rows)
    assert label["path_stats"]["max_up_bps"] == "25"
    assert label["path_class"] == "directional_up"


def test_incomplete_horizon_fails_closed_instead_of_filling_gap() -> None:
    rows = [row for row in _quiet_rows() if row["open_time_utc"] != (ANCHOR + timedelta(minutes=7)).isoformat()]
    label = _label(rows)
    assert label["coverage_state"] == "incomplete"
    assert label["path_class"] == "unknown"
    assert label["path_stats"]["expected_rows"] == 15
    assert label["path_stats"]["observed_rows"] == 14
    assert label["path_stats"]["missing_minutes"] == [7]


def test_same_research_evidence_is_deterministic_under_input_reordering() -> None:
    rows = _directional_up_rows()
    first = build_move_bundle(
        anchor_time=ANCHOR,
        anchor_price=ANCHOR_PRICE,
        research_rows=rows,
        horizons_minutes=(15,),
    )
    second = build_move_bundle(
        anchor_time=ANCHOR,
        anchor_price="2000.000",
        research_rows=list(reversed(rows)),
        horizons_minutes=(15,),
    )
    assert first == second
    assert verify_move_bundle_digest(first) is True
    assert verify_move_label_digest(first["labels"][0]) is True


def test_labels_are_horizon_tagged_future_derived_and_not_pit_eligible() -> None:
    bundle = build_move_bundle(
        anchor_time=ANCHOR,
        anchor_price=ANCHOR_PRICE,
        research_rows=_quiet_rows(60),
        horizons_minutes=(15, 60),
    )
    assert bundle["move_bundle_version"] == MOVE_BUNDLE_VERSION
    assert bundle["evaluation_only"] is True
    assert bundle["future_derived"] is True
    assert bundle["pit_eligible"] is False
    assert bundle["decision_input_allowed"] is False
    assert bundle["available_after_utc"] == (ANCHOR + timedelta(minutes=60)).isoformat()
    for label in bundle["labels"]:
        assert label["label_version"] == MOVE_LABEL_VERSION
        assert label["available_after_utc"] == label["horizon_end_utc"]
        assert label["pit_eligible"] is False
        assert label["decision_input_allowed"] is False


def test_storage_contract_is_physically_separate_from_pit_tables() -> None:
    field_names = {field.name for field in RESEARCH_MOVE_LABELS.fields}
    assert RESEARCH_MOVE_LABELS.name == "research_move_labels"
    assert "first_observed_at" not in field_names
    assert "pit_eligible" in field_names
    assert "available_after_utc" in field_names
    row = move_label_storage_row(_label(_directional_up_rows()))
    assert row["pit_eligible"] is False
    assert row["future_derived"] is True
    assert row["decision_input_allowed"] is False


def test_future_move_bundle_cannot_be_used_as_day10_signal_state() -> None:
    bundle = build_move_bundle(
        anchor_time=ANCHOR,
        anchor_price=ANCHOR_PRICE,
        research_rows=_quiet_rows(),
        horizons_minutes=(15,),
    )
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


def test_move_detective_rejects_pit_or_non_research_candles() -> None:
    pit_row = deepcopy(_quiet_rows()[0])
    pit_row["pit_eligible"] = True
    with pytest.raises(ValueError, match="pit_eligible=false"):
        _label([pit_row, *_quiet_rows()[1:]])

    wrong_provenance = deepcopy(_quiet_rows()[0])
    wrong_provenance["provenance_class"] = "pit_observed"
    with pytest.raises(ValueError, match="retrospective_history"):
        _label([wrong_provenance, *_quiet_rows()[1:]])


def test_duplicate_research_revisions_require_explicit_selection() -> None:
    rows = _quiet_rows()
    duplicate = deepcopy(rows[0])
    duplicate["research_identity"] = "different-revision"
    with pytest.raises(ValueError, match="one explicitly selected research revision"):
        _label([*rows, duplicate])


def test_distribution_is_deterministic_and_contains_no_causal_claims() -> None:
    labels = [
        _label(_quiet_rows()),
        _label(_directional_up_rows()),
        _label(_spike_up_reverted_rows()),
        _label(_reversal_rows()),
    ]
    first = move_label_distribution(labels)
    second = move_label_distribution(reversed(labels))
    assert first == second
    assert first["label_count"] == 4
    assert first["coverage_counts"] == {"complete": 4}
    assert first["path_class_counts_by_horizon"]["15"] == {
        "directional_up": 1,
        "quiet": 1,
        "reversal_up_to_down": 1,
        "spike_up_reverted": 1,
    }
    assert first["outcome_causality_included"] is False


def test_tampered_label_digest_is_rejected_by_storage_and_distribution() -> None:
    label = _label(_quiet_rows())
    label["path_class"] = "directional_up"
    assert verify_move_label_digest(label) is False
    with pytest.raises(ValueError, match="valid Day 12 move labels"):
        move_label_storage_row(label)
    with pytest.raises(ValueError, match="invalid move label"):
        move_label_distribution([label])
