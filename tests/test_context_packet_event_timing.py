from __future__ import annotations

from datetime import UTC, datetime, timedelta

from aidy.context_packet import build_context_packet
from aidy.feature_engine import build_feature_packet

AS_OF = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)


def _feature_packet() -> dict[str, object]:
    return build_feature_packet(
        as_of=AS_OF,
        symbol="XAUUSD",
        candle_rows=[],
        mode="pit",
        snapshot=None,
    )


def _scheduled_event(*, scheduled_at: datetime, observed_at: datetime) -> dict[str, object]:
    return {
        "source": "bls_calendar",
        "external_id": "cpi-future",
        "event_type": "macro_schedule",
        "first_observed_at": observed_at,
        "published_at": None,
        "revision_index": 1,
        "headline": "Consumer Price Index",
        "structured_data": {
            "phase": "scheduled",
            "event_class": "cpi",
            "scheduled_at": scheduled_at.isoformat(),
            "source_url": "https://www.bls.gov/schedule/",
        },
        "load_identity": "cpi-future-1",
        "evidence_id": "evidence-cpi-future-1",
        "archive_key": "events/cpi-future/1.json",
        "payload_digest": "digest-cpi-future-1",
    }


def test_recent_calendar_refresh_does_not_create_false_event_window() -> None:
    scheduled = AS_OF + timedelta(days=5)
    row = _scheduled_event(
        scheduled_at=scheduled,
        observed_at=AS_OF - timedelta(minutes=1),
    )

    packet = build_context_packet(
        as_of=AS_OF,
        symbol="XAUUSD",
        feature_packet=_feature_packet(),
        event_rows=[row],
        macro_evidence_state="known",
        cross_market_rows=[],
    )

    assert packet["event_risk"]["timing_state"] == "clear_current_window"
    assert packet["event_risk"]["events_in_window"] == []
    assert packet["event_risk"]["next_scheduled_event"]["scheduled_at"] == scheduled.isoformat()


def test_unknown_macro_evidence_never_becomes_clear_even_with_no_rows() -> None:
    packet = build_context_packet(
        as_of=AS_OF,
        symbol="XAUUSD",
        feature_packet=_feature_packet(),
        event_rows=[],
        macro_evidence_state="unknown",
        cross_market_rows=[],
    )

    assert packet["event_risk"]["evidence_state"] == "unknown"
    assert packet["event_risk"]["timing_state"] == "unknown"
