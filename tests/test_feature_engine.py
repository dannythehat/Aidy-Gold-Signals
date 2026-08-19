from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from aidy.feature_engine import FEATURE_DEFINITION_VERSION, TIMEFRAMES, build_feature_packet

_BASE = datetime(2025, 6, 10, 12, 40, tzinfo=UTC)
_STEP_MINUTES = {"M1": 1, "M5": 5, "M15": 15, "H1": 60, "H4": 240, "D1": 1440}


def _research_row(
    *,
    timeframe: str,
    index: int,
    close: Decimal | None = None,
    high: Decimal | None = None,
    low: Decimal | None = None,
) -> dict[str, object]:
    price = close if close is not None else Decimal(3300) + Decimal(index) / Decimal(10)
    open_price = price - Decimal("0.05")
    high_price = high if high is not None else price + Decimal("0.20")
    low_price = low if low is not None else open_price - Decimal("0.20")
    opened = _BASE + timedelta(minutes=_STEP_MINUTES[timeframe] * index)
    return {
        "research_identity": f"research-{timeframe}-{index}",
        "provenance_class": "retrospective_history",
        "pit_eligible": False,
        "symbol": "XAUUSD",
        "timeframe": timeframe,
        "open_time_utc": opened,
        "open": str(open_price),
        "high": str(high_price),
        "low": str(low_price),
        "close": str(price),
        "source": "histdata",
        "source_file_sha256": "a" * 64,
        "source_payload_sha256": "b" * 64,
        "derivation_version": "fixture-v1",
    }


def _pit_row(*, index: int, observed_delay_seconds: int = 5) -> dict[str, object]:
    opened = _BASE + timedelta(minutes=index)
    price = Decimal(3300) + Decimal(index) / Decimal(10)
    return {
        "load_identity": f"pit-{index}",
        "evidence_id": f"evidence-{index}",
        "archive_key": f"gold/candles/{index}.json",
        "payload_digest": "c" * 64,
        "record_type": "candle",
        "schema_version": 1,
        "symbol": "XAUUSD",
        "timeframe": "1m",
        "open_time_utc": opened,
        "first_observed_at": opened + timedelta(seconds=observed_delay_seconds),
        "open": str(price - Decimal("0.05")),
        "high": str(price + Decimal("0.20")),
        "low": str(price - Decimal("0.25")),
        "close": str(price),
        "source": "fixture_pit",
    }


def _snapshot(*, as_of: datetime, quote_state: str = "available") -> dict[str, object]:
    return {
        "load_identity": "snapshot-load",
        "evidence_id": "snapshot-evidence",
        "archive_key": "gold/snapshot.json",
        "payload_digest": "d" * 64,
        "record_type": "snapshot",
        "schema_version": 2,
        "captured_at": as_of,
        "symbol": "XAUUSD",
        "capture_status": "complete" if quote_state == "available" else "partial",
        "bid": None,
        "ask": None,
        "mid": "3302.4",
        "spread": None,
        "quote_time": as_of - timedelta(seconds=17),
        "quote_age_seconds": 17.0,
        "session_code": "london_new_york_overlap",
        "data_availability": {"quote": quote_state, "market_data_source": "gold_api"},
    }


def _research_fixture() -> tuple[list[dict[str, object]], datetime]:
    rows: list[dict[str, object]] = []
    for timeframe in TIMEFRAMES:
        rows.extend(_research_row(timeframe=timeframe, index=index) for index in range(25))
    as_of = max(row["open_time_utc"] for row in rows)
    assert isinstance(as_of, datetime)
    return rows, as_of


def test_retrospective_packet_is_deterministic_and_permanently_pit_ineligible() -> None:
    rows, as_of = _research_fixture()
    first = build_feature_packet(
        as_of=as_of,
        symbol="XAUUSD",
        candle_rows=rows,
        mode="retrospective",
    )
    second = build_feature_packet(
        as_of=as_of,
        symbol="XAUUSD",
        candle_rows=reversed(rows),
        mode="retrospective",
    )
    assert first == second
    assert first["feature_definition_version"] == FEATURE_DEFINITION_VERSION
    assert first["pit_eligible"] is False
    assert first["provenance_class"] == "retrospective_history"
    assert first["feature_packet_digest"] == second["feature_packet_digest"]


def test_full_research_fixture_produces_technical_features_and_alignment() -> None:
    rows, as_of = _research_fixture()
    packet = build_feature_packet(
        as_of=as_of,
        symbol="XAUUSD",
        candle_rows=rows,
        mode="retrospective",
    )
    for timeframe in TIMEFRAMES:
        features = packet["timeframes"][timeframe]
        assert features["state"] == "known"
        assert features["return_1_bps"] is not None
        assert features["return_5_bps"] is not None
        assert features["atr_14_bps"] is not None
        assert features["realized_vol_20_bps"] is not None
        assert features["recent_high_20"] is not None
        assert features["recent_low_20"] is not None
        assert features["source_identities"]
    assert packet["multi_timeframe_alignment"]["state"] == "all_bullish"
    assert packet["quote_context"]["state"] == "unknown"


def test_missing_history_stays_null_instead_of_being_fabricated() -> None:
    row = _research_row(timeframe="M1", index=0)
    packet = build_feature_packet(
        as_of=row["open_time_utc"],
        symbol="XAUUSD",
        candle_rows=[row],
        mode="retrospective",
    )
    m1 = packet["timeframes"]["M1"]
    assert m1["bars_available"] == 1
    assert m1["return_1_bps"] is None
    assert m1["return_5_bps"] is None
    assert m1["atr_14_bps"] is None
    assert m1["realized_vol_20_bps"] is None
    assert packet["timeframes"]["H1"]["state"] == "unknown"


def test_retrospective_row_is_rejected_from_pit_packet() -> None:
    row = _research_row(timeframe="M1", index=0)
    with pytest.raises(ValueError, match="Retrospective-only evidence"):
        build_feature_packet(
            as_of=row["open_time_utc"],
            symbol="XAUUSD",
            candle_rows=[row],
            mode="pit",
        )


def test_pit_row_first_observed_after_cutoff_is_not_visible() -> None:
    row = _pit_row(index=0, observed_delay_seconds=60)
    packet = build_feature_packet(
        as_of=row["open_time_utc"],
        symbol="XAUUSD",
        candle_rows=[row],
        mode="pit",
    )
    assert packet["timeframes"]["M1"]["state"] == "unknown"
    assert packet["source_links"]["M1"] == []


def test_pit_quote_context_preserves_stale_and_unknown_spread_without_invention() -> None:
    as_of = datetime(2026, 7, 1, 12, 30, tzinfo=UTC)
    snapshot = _snapshot(as_of=as_of, quote_state="gold_api_stale_quote")
    packet = build_feature_packet(
        as_of=as_of,
        symbol="XAUUSD",
        candle_rows=[],
        mode="pit",
        snapshot=snapshot,
    )
    quote = packet["quote_context"]
    assert packet["pit_eligible"] is True
    assert quote["state"] == "known"
    assert quote["quote_state"] == "gold_api_stale_quote"
    assert quote["spread"] is None
    assert quote["recorded_session_code"] == "london_new_york_overlap"
    assert quote["computed_session_code"] == "london_new_york_overlap"
    assert quote["session_code_consistent"] is True
    assert quote["source_identity"] == "snapshot-load"


def test_retrospective_packet_cannot_mix_modern_pit_snapshot() -> None:
    row = _research_row(timeframe="M1", index=0)
    as_of = row["open_time_utc"]
    assert isinstance(as_of, datetime)
    with pytest.raises(ValueError, match="cannot mix"):
        build_feature_packet(
            as_of=as_of,
            symbol="XAUUSD",
            candle_rows=[row],
            mode="retrospective",
            snapshot=_snapshot(as_of=as_of),
        )


def test_invalid_ohlc_geometry_fails_closed() -> None:
    row = _research_row(
        timeframe="M1",
        index=0,
        close=Decimal(3300),
        high=Decimal(3299),
        low=Decimal(3298),
    )
    with pytest.raises(ValueError, match="OHLC geometry"):
        build_feature_packet(
            as_of=row["open_time_utc"],
            symbol="XAUUSD",
            candle_rows=[row],
            mode="retrospective",
        )


def test_duplicate_logical_candle_fails_closed() -> None:
    row = _research_row(timeframe="M1", index=0)
    duplicate = dict(row)
    duplicate["research_identity"] = "different-identity-same-logical-candle"
    with pytest.raises(ValueError, match="duplicate logical candles"):
        build_feature_packet(
            as_of=row["open_time_utc"],
            symbol="XAUUSD",
            candle_rows=[row, duplicate],
            mode="retrospective",
        )


def test_confirmed_swing_uses_only_bars_already_present_by_as_of() -> None:
    highs = ["3301", "3302", "3305", "3302", "3301", "3302", "3303"]
    rows = []
    for index, high_text in enumerate(highs):
        close = Decimal(3300)
        rows.append(
            _research_row(
                timeframe="M1",
                index=index,
                close=close,
                high=Decimal(high_text),
                low=Decimal(3299),
            )
        )
    as_of = rows[-1]["open_time_utc"]
    packet = build_feature_packet(
        as_of=as_of,
        symbol="XAUUSD",
        candle_rows=rows,
        mode="retrospective",
    )
    swing = packet["timeframes"]["M1"]["confirmed_swing_high"]
    assert swing is not None
    assert swing["price"] == "3305"
    assert swing["open_time_utc"] == rows[2]["open_time_utc"].isoformat()


def test_source_link_audit_contains_exact_research_identity_and_hashes() -> None:
    row = _research_row(timeframe="M1", index=0)
    packet = build_feature_packet(
        as_of=row["open_time_utc"],
        symbol="XAUUSD",
        candle_rows=[row],
        mode="retrospective",
    )
    link = packet["source_links"]["M1"][0]
    assert link["identity"] == row["research_identity"]
    assert link["source_file_sha256"] == "a" * 64
    assert link["source_payload_sha256"] == "b" * 64
    assert link["pit_eligible"] is False
