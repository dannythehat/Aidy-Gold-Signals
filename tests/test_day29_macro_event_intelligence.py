from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

import pytest

from aidy.macro_event_intelligence import (
    EVENT_CLASSES,
    EVENT_INTELLIGENCE_VERSION,
    build_actual_observation,
    build_consensus_observation,
    build_event_intelligence_state,
    build_pre_event_features,
    build_schedule_observation,
    build_surprise_state,
    run_j4_j15_descriptive,
    select_schedule_as_of,
    verify_event_intelligence_state,
    verify_j4_j15_study,
    verify_schedule_observation,
)


def _schedule(
    *,
    event_class: str = "retail_sales",
    observed: datetime = datetime(2026, 3, 1, 12, tzinfo=UTC),
    day: date = date(2026, 3, 6),
    wall: time | None = time(8, 30),
    provenance: str = "pit_observed",
) -> dict[str, object]:
    source = {
        "retail_sales": (
            "census_economic_indicators",
            "https://www.census.gov/economic-indicators/calendar-listview.html",
            "America/New_York",
        ),
        "ism_services": (
            "ism_reports",
            "https://www.ismworld.org/supply-management-news-and-reports/reports/rob-report-calendar/",
            "America/New_York",
        ),
    }[event_class]
    return build_schedule_observation(
        event_class=event_class,
        source_key=source[0],
        external_id=f"{event_class}-{day.isoformat()}",
        scheduled_date=day,
        scheduled_time=wall,
        timezone_name=source[2] if wall is not None else None,
        first_observed_at=observed,
        source_url=source[1],
        provenance_class=provenance,
    )


def _candles(event_at: datetime, *, include_future: bool = False) -> list[dict[str, object]]:
    start = event_at - timedelta(minutes=300)
    rows = []
    for index in range(300):
        stamp = start + timedelta(minutes=index)
        price = 2000 + index * 0.02
        rows.append(
            {
                "symbol": "XAUUSD",
                "timeframe": "M1",
                "open_time_utc": stamp.isoformat(),
                "open": str(price),
                "high": str(price + 0.15),
                "low": str(price - 0.1),
                "close": str(price + (0.01 if index % 2 else -0.01)),
            }
        )
    if include_future:
        rows.append(
            {
                "symbol": "XAUUSD",
                "timeframe": "M1",
                "open_time_utc": event_at.isoformat(),
                "open": "9999",
                "high": "9999",
                "low": "9999",
                "close": "9999",
            }
        )
    return rows


def _episode(event_class: str, index: int, *, impact: str = "9") -> dict[str, object]:
    return {
        "event_class": event_class,
        "independent_episode_id": f"{event_class}-{index}",
        "post_abs_return_bps": impact,
        "post_realized_vol_bps": impact,
        "outcome_return_bps": "-2" if index % 2 else "2",
    }


def test_new_day29_event_classes_are_explicit_and_versioned() -> None:
    assert set(EVENT_CLASSES) == {
        "initial_jobless_claims",
        "ism_manufacturing",
        "ism_services",
        "retail_sales",
        "fed_speech",
        "fed_chair_testimony",
        "fomc_minutes",
        "treasury_auction",
        "ecb_decision",
        "boj_decision",
        "boe_decision",
    }
    assert EVENT_INTELLIGENCE_VERSION.endswith("_v2")


def test_schedule_conversion_is_dst_safe() -> None:
    before_dst = _schedule(day=date(2026, 3, 6))
    after_dst = _schedule(day=date(2026, 3, 10))
    assert before_dst["scheduled_at"] == "2026-03-06T13:30:00+00:00"
    assert after_dst["scheduled_at"] == "2026-03-10T12:30:00+00:00"
    assert verify_schedule_observation(before_dst)


def test_date_only_official_schedule_does_not_invent_a_clock() -> None:
    schedule = _schedule(wall=None)
    assert schedule["scheduled_at"] is None
    assert schedule["scheduled_time_precision"] == "date_only"
    features = build_pre_event_features(
        schedule=schedule,
        candle_rows=[],
        as_of=datetime(2026, 3, 5, tzinfo=UTC),
    )
    assert features["state"] == "unknown_release_time"


def test_non_official_schedule_host_is_rejected() -> None:
    with pytest.raises(ValueError, match="official allowlist"):
        build_schedule_observation(
            event_class="retail_sales",
            source_key="census_economic_indicators",
            external_id="bad",
            scheduled_date="2026-03-06",
            scheduled_time="08:30",
            timezone_name="America/New_York",
            first_observed_at="2026-03-01T12:00:00+00:00",
            source_url="https://example.com/calendar",
        )


def test_official_eta_claims_host_is_allowlisted() -> None:
    schedule = build_schedule_observation(
        event_class="initial_jobless_claims",
        source_key="dol_initial_claims",
        external_id="claims-2026-03-05",
        scheduled_date="2026-03-05",
        scheduled_time="08:30",
        timezone_name="America/New_York",
        first_observed_at="2026-03-01T12:00:00+00:00",
        source_url="https://oui.doleta.gov/unemploy/claims.asp",
    )
    assert verify_schedule_observation(schedule)


def test_as_of_selection_excludes_future_revisions_and_retrospective_rows() -> None:
    first = _schedule(observed=datetime(2026, 3, 1, 12, tzinfo=UTC), day=date(2026, 3, 6))
    revised = _schedule(observed=datetime(2026, 3, 3, 12, tzinfo=UTC), day=date(2026, 3, 7))
    retrospective = _schedule(
        observed=datetime(2026, 8, 1, tzinfo=UTC),
        day=date(2025, 1, 7),
        provenance="retrospective_official_schedule",
    )
    selected = select_schedule_as_of(
        [first, revised, retrospective], as_of=datetime(2026, 3, 2, tzinfo=UTC)
    )
    assert [item["schedule_digest"] for item in selected] == [first["schedule_digest"]]


def test_pre_event_features_use_closed_pre_release_bars_only() -> None:
    schedule = _schedule()
    event_at = datetime.fromisoformat(str(schedule["scheduled_at"]))
    rows = _candles(event_at, include_future=True)
    with_future = build_pre_event_features(
        schedule=schedule, candle_rows=rows, as_of=event_at
    )
    without_future = build_pre_event_features(
        schedule=schedule, candle_rows=rows[:-1], as_of=event_at
    )
    assert with_future == without_future
    assert with_future["state"] == "known"
    assert with_future["recent_observed_minutes"] == 60
    assert with_future["baseline_observed_minutes"] == 240
    assert with_future["future_values_used"] is False


def test_pre_event_features_fail_unknown_on_incomplete_coverage() -> None:
    schedule = _schedule()
    event_at = datetime.fromisoformat(str(schedule["scheduled_at"]))
    result = build_pre_event_features(
        schedule=schedule,
        candle_rows=_candles(event_at)[:100],
        as_of=event_at,
    )
    assert result["state"] == "unknown_insufficient_pre_event_coverage"


def test_j4_j15_remains_unclassified_below_preregistered_n() -> None:
    study = run_j4_j15_descriptive([_episode("ism_services", index) for index in range(19)])
    assert verify_j4_j15_study(study)
    assert study["class_results"]["ism_services"]["independent_episode_n"] == 19
    assert (
        study["class_results"]["ism_services"]["tier_state"]
        == "unclassified_insufficient_evidence"
    )
    assert study["trade_pnl_used"] is False
    assert study["trading_gate_created"] is False


@pytest.mark.parametrize(
    ("impact", "expected"), [("4", "tier_1"), ("8", "tier_2"), ("16", "tier_3")]
)
def test_j4_j15_tiers_use_descriptive_volatility_not_trade_pnl(
    impact: str, expected: str
) -> None:
    study = run_j4_j15_descriptive(
        [_episode("ism_services", index, impact=impact) for index in range(20)]
    )
    assert study["class_results"]["ism_services"]["tier_state"] == expected


def test_j4_j15_rejects_trade_outcome_fields() -> None:
    episode = _episode("ism_services", 1)
    episode["pnl"] = "100"
    with pytest.raises(ValueError, match="trade P/L"):
        run_j4_j15_descriptive([episode])


def test_missing_historical_consensus_stays_unknown() -> None:
    schedule = _schedule()
    state = build_surprise_state(
        schedule=schedule,
        consensus_observations=[],
        actual_observations=[],
        as_of=datetime(2026, 3, 6, 14, tzinfo=UTC),
    )
    assert state["consensus_state"] == "unknown"
    assert state["surprise_state"] == "unknown"
    assert state["historical_consensus_backfilled"] is False


def test_forward_consensus_and_first_print_create_surprise_then_preserve_revision() -> None:
    schedule = _schedule()
    consensus = build_consensus_observation(
        schedule=schedule,
        value="0.4",
        unit="percent_mom",
        captured_at="2026-03-06T12:00:00+00:00",
        source_url="https://calendar.example.org/immutable/retail-sales",
        source_qualification="timestamped_immutable_approved",
    )
    first = build_actual_observation(
        schedule=schedule,
        value="0.6",
        unit="percent_mom",
        first_observed_at="2026-03-06T13:30:03+00:00",
        published_at="2026-03-06T13:30:00+00:00",
        source_url="https://www.census.gov/retail/sales.html",
        revision_index=0,
    )
    revision = build_actual_observation(
        schedule=schedule,
        value="0.5",
        unit="percent_mom",
        first_observed_at="2026-04-01T12:30:03+00:00",
        published_at="2026-04-01T12:30:00+00:00",
        source_url="https://www.census.gov/retail/sales.html",
        revision_index=1,
        previous_value="0.6",
    )
    state = build_surprise_state(
        schedule=schedule,
        consensus_observations=[consensus],
        actual_observations=[revision, first],
        as_of="2026-04-01T13:00:00+00:00",
    )
    assert state["surprise_value"] == "0.2"
    assert state["first_print_observation_digest"] == first["observation_digest"]
    assert state["latest_revision_index"] == 1


def test_unknown_tier_nearby_fails_closed_without_creating_a_gate() -> None:
    schedule = _schedule(event_class="ism_services", day=date(2026, 3, 6), wall=time(10))
    study = run_j4_j15_descriptive([])
    state = build_event_intelligence_state(
        as_of="2026-03-06T14:30:00+00:00",
        schedule_records=[schedule],
        tier_study=study,
    )
    assert verify_event_intelligence_state(state)
    assert state["timing_state"] == "unknown_severity_nearby"
    assert state["one_size_window_used"] is False
    assert state["trading_gate_created"] is False
