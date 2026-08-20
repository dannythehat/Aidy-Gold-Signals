from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from aidy.context_packet import build_context_packet, verify_context_hash
from aidy.cross_market import (
    SERIES_US2Y,
    SERIES_US10Y,
    SERIES_US10Y_REAL,
    SERIES_USD_BROAD,
)
from aidy.feature_engine import build_feature_packet

AS_OF = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)


def _feature_packet(*, snapshot: dict[str, object] | None = None) -> dict[str, object]:
    return build_feature_packet(
        as_of=AS_OF,
        symbol="XAUUSD",
        candle_rows=[],
        mode="pit",
        snapshot=snapshot,
    )


def _event(
    *,
    external_id: str,
    event_class: str,
    scheduled_at: datetime,
    observed_at: datetime,
    revision: int = 1,
) -> dict[str, object]:
    return {
        "source": "bls_calendar",
        "external_id": external_id,
        "event_type": "macro_schedule",
        "first_observed_at": observed_at,
        "published_at": None,
        "revision_index": revision,
        "headline": event_class,
        "structured_data": {
            "phase": "scheduled",
            "event_class": event_class,
            "scheduled_at": scheduled_at.isoformat(),
            "source_url": "https://www.bls.gov/schedule/",
        },
        "load_identity": f"{external_id}-{revision}",
        "evidence_id": f"event-{external_id}-{revision}",
        "archive_key": f"events/{external_id}/{revision}.json",
        "payload_digest": f"digest-{external_id}-{revision}",
    }


def _cross(
    *,
    series_id: str,
    value: str,
    observation_date: str = "2026-08-19",
    observed_at: datetime = AS_OF - timedelta(hours=1),
) -> dict[str, object]:
    source = "federal_reserve_h10" if series_id == SERIES_USD_BROAD else "us_treasury"
    return {
        "source": source,
        "series_id": series_id,
        "observation_date": observation_date,
        "value": value,
        "unit": "index_jan_2006_100" if series_id == SERIES_USD_BROAD else "percent",
        "first_observed_at": observed_at,
        "revision_index": 1,
        "source_url": "https://example.invalid/official",
        "load_identity": f"{series_id}-{observation_date}",
        "evidence_id": f"evidence-{series_id}",
        "archive_key": f"cross-market/{series_id}.json",
        "payload_digest": f"digest-{series_id}-{value}",
        "source_document_digest": f"document-{series_id}",
    }


def _signal(signal_id: str, entry: str) -> dict[str, object]:
    return {
        "aidy_signal_id": signal_id,
        "originating_decision_id": f"decision-{signal_id}",
        "status": "open",
        "direction": "buy",
        "entry_type": "market",
        "entry_price": entry,
        "stop_loss": "3300",
        "targets": ["3400", "3450"],
        "opened_at_utc": (AS_OF - timedelta(hours=2)).isoformat(),
        "updated_at_utc": (AS_OF - timedelta(minutes=5)).isoformat(),
    }


def test_same_evidence_produces_identical_packet_and_hash_across_input_order() -> None:
    events = [
        _event(
            external_id="cpi",
            event_class="cpi",
            scheduled_at=AS_OF + timedelta(minutes=30),
            observed_at=AS_OF - timedelta(days=10),
        ),
        _event(
            external_id="jobs",
            event_class="employment_situation",
            scheduled_at=AS_OF + timedelta(days=2),
            observed_at=AS_OF - timedelta(days=10),
        ),
    ]
    cross = [
        _cross(series_id=SERIES_USD_BROAD, value="119.2"),
        _cross(series_id=SERIES_US2Y, value="4.15"),
        _cross(series_id=SERIES_US10Y, value="4.31"),
        _cross(series_id=SERIES_US10Y_REAL, value="1.92"),
    ]
    state_a = {
        "lifecycle_version": "fixture-v1",
        "state": "active",
        "as_of_utc": AS_OF,
        "last_decision_id": "decision-b",
        "active_signals": [_signal("b", "3360.00"), _signal("a", "3350")],
    }
    state_b = {**state_a, "active_signals": list(reversed(state_a["active_signals"]))}

    first = build_context_packet(
        as_of=AS_OF,
        symbol="XAUUSD",
        feature_packet=_feature_packet(),
        event_rows=events,
        macro_evidence_state="known",
        cross_market_rows=cross,
        aidy_signal_state=state_a,
    )
    second = build_context_packet(
        as_of=AS_OF,
        symbol="XAUUSD",
        feature_packet=_feature_packet(),
        event_rows=list(reversed(events)),
        macro_evidence_state="known",
        cross_market_rows=list(reversed(cross)),
        aidy_signal_state=state_b,
    )

    assert first == second
    assert verify_context_hash(first) is True
    assert first["event_risk"]["timing_state"] == "inside_high_impact_window"
    assert [item["aidy_signal_id"] for item in first["aidy_signal_lifecycle"]["active_signals"]] == [
        "a",
        "b",
    ]


def test_changed_evidence_changes_context_hash() -> None:
    baseline = build_context_packet(
        as_of=AS_OF,
        symbol="XAUUSD",
        feature_packet=_feature_packet(),
        event_rows=[],
        macro_evidence_state="known",
        cross_market_rows=[_cross(series_id=SERIES_US10Y, value="4.31")],
    )
    changed = build_context_packet(
        as_of=AS_OF,
        symbol="XAUUSD",
        feature_packet=_feature_packet(),
        event_rows=[],
        macro_evidence_state="known",
        cross_market_rows=[_cross(series_id=SERIES_US10Y, value="4.32")],
    )
    assert baseline["context_hash"] != changed["context_hash"]


def test_missing_inputs_remain_explicit_unknown_and_never_become_clear_evidence() -> None:
    packet = build_context_packet(
        as_of=AS_OF,
        symbol="XAUUSD",
        feature_packet=_feature_packet(),
        event_rows=[],
        macro_evidence_state="unknown",
        cross_market_rows=[],
    )
    assert packet["event_risk"]["timing_state"] == "unknown"
    assert packet["aidy_signal_lifecycle"]["evidence_state"] == "unknown"
    assert packet["data_quality"]["missing_gold_timeframes"] == ["M1", "M5", "M15", "H1", "H4", "D1"]
    assert packet["data_quality"]["quote_freshness"] == "unknown"
    assert packet["data_quality"]["spread_state"] == "unknown"
    assert packet["data_quality"]["cross_market_missing_series"] == sorted(
        [SERIES_USD_BROAD, SERIES_US2Y, SERIES_US10Y, SERIES_US10Y_REAL]
    )
    assert packet["retrospective_history_included"] is False
    assert packet["broker_follower_state_included"] is False


def test_context_rejects_retrospective_gold_features() -> None:
    research = build_feature_packet(
        as_of=AS_OF,
        symbol="XAUUSD",
        candle_rows=[],
        mode="retrospective",
        snapshot=None,
    )
    with pytest.raises(ValueError, match="PIT Gold features only"):
        build_context_packet(
            as_of=AS_OF,
            symbol="XAUUSD",
            feature_packet=research,
            event_rows=[],
            macro_evidence_state="known",
            cross_market_rows=[],
        )


def test_context_rejects_tampered_feature_packet_digest() -> None:
    feature = _feature_packet()
    feature["quote_context"]["mid"] = "9999"
    with pytest.raises(ValueError, match="digest"):
        build_context_packet(
            as_of=AS_OF,
            symbol="XAUUSD",
            feature_packet=feature,
            event_rows=[],
            macro_evidence_state="known",
            cross_market_rows=[],
        )


def test_context_rejects_broker_or_follower_account_state() -> None:
    with pytest.raises(ValueError, match="Forbidden broker/follower state"):
        build_context_packet(
            as_of=AS_OF,
            symbol="XAUUSD",
            feature_packet=_feature_packet(),
            event_rows=[],
            macro_evidence_state="known",
            cross_market_rows=[],
            aidy_signal_state={
                "state": "active",
                "active_signals": [],
                "balance": "100000",
            },
        )


def test_macro_revision_after_asof_cannot_leak_into_context() -> None:
    old_time = AS_OF + timedelta(minutes=30)
    revised_time = AS_OF + timedelta(days=1)
    rows = [
        _event(
            external_id="cpi",
            event_class="cpi",
            scheduled_at=old_time,
            observed_at=AS_OF - timedelta(days=2),
            revision=1,
        ),
        _event(
            external_id="cpi",
            event_class="cpi",
            scheduled_at=revised_time,
            observed_at=AS_OF + timedelta(minutes=1),
            revision=2,
        ),
    ]
    packet = build_context_packet(
        as_of=AS_OF,
        symbol="XAUUSD",
        feature_packet=_feature_packet(),
        event_rows=rows,
        macro_evidence_state="known",
        cross_market_rows=[],
    )
    assert packet["event_risk"]["events_in_window"][0]["scheduled_at"] == old_time.isoformat()
    assert packet["event_risk"]["events_in_window"][0]["provenance"]["revision_index"] == 1


def test_every_enabled_cross_market_value_keeps_reconstruction_provenance() -> None:
    rows = [
        _cross(series_id=SERIES_USD_BROAD, value="119.2"),
        _cross(series_id=SERIES_US2Y, value="4.15"),
        _cross(series_id=SERIES_US10Y, value="4.31"),
        _cross(series_id=SERIES_US10Y_REAL, value="1.92"),
    ]
    packet = build_context_packet(
        as_of=AS_OF,
        symbol="XAUUSD",
        feature_packet=_feature_packet(),
        event_rows=[],
        macro_evidence_state="known",
        cross_market_rows=rows,
        aidy_signal_state={"state": "none", "active_signals": []},
    )
    for series_id in (SERIES_USD_BROAD, SERIES_US2Y, SERIES_US10Y, SERIES_US10Y_REAL):
        series = packet["cross_market"]["series"][series_id]
        assert series["state"] == "known"
        assert series["provenance"]["evidence_id"] == f"evidence-{series_id}"
        assert packet["provenance"]["cross_market_series"][series_id] == series["provenance"]
