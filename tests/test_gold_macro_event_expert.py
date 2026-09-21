from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

import pytest

from aidy.gold_cycle_environment import build_cycle_environment
from aidy.gold_expert_gate_contract import verify_expert_gate_packet
from aidy.gold_macro_event_expert import (
    CONDITIONAL_RESPONSE_MIN_N,
    MACRO_EVENT_EXPERT_VERSION,
    MACRO_EVENT_GATE_ID,
    NO_NEWS_CONTROL_MIN_N,
    STANDARDIZED_SURPRISE_MIN_N,
    build_macro_event_expert,
)
from aidy.macro_event_intelligence import (
    build_actual_observation,
    build_consensus_observation,
    build_schedule_observation,
    run_j4_j15_descriptive,
)

EVENT_AT = datetime(2026, 9, 18, 12, 30, tzinfo=UTC)


def _schedule(
    *,
    event_class: str = "retail_sales",
    external_id: str = "retail-sales-primary",
    scheduled_time: time = time(8, 30),
) -> dict[str, object]:
    if event_class == "retail_sales":
        source_key = "census_economic_indicators"
        url = "https://www.census.gov/economic-indicators/calendar-listview.html"
    elif event_class == "ism_services":
        source_key = "ism_reports"
        url = (
            "https://www.ismworld.org/supply-management-news-and-reports/"
            "reports/rob-report-calendar/"
        )
    else:
        raise AssertionError("fixture event class unsupported")
    return build_schedule_observation(
        event_class=event_class,
        source_key=source_key,
        external_id=external_id,
        scheduled_date=date(2026, 9, 18),
        scheduled_time=scheduled_time,
        timezone_name="America/New_York",
        first_observed_at=datetime(2026, 9, 1, 12, tzinfo=UTC),
        source_url=url,
    )


def _environment(as_of: datetime) -> dict:
    return build_cycle_environment(
        as_of_utc=as_of,
        target_window_start_utc=as_of + timedelta(minutes=15),
        session_code="london",
        observed_state="neutral",
        gold_state={
            "market_structure": {
                "timeframes": {
                    "M5": {"net_close_direction": "flat", "state": "known"},
                    "M15": {"net_close_direction": "flat", "state": "known"},
                    "H1": {"net_close_direction": "up", "state": "known"},
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
                    "60m": {"direction": "up", "return_bps": "2"},
                },
            },
            "volatility": {
                "state": "normal",
                "jump_continuous": {"state": "continuous_dominant"},
            },
            "scheduled_event_risk": {
                "state": "known",
                "timing_state": "near_event_window",
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
        regime={"compound_regime_key": "event|normal"},
    )


def _m1_rows(
    *,
    mode: str = "retrospective",
    future_spike: bool = False,
) -> list[dict[str, object]]:
    start = EVENT_AT - timedelta(minutes=300)
    rows: list[dict[str, object]] = []
    value = Decimal("2400")
    for index in range(320):
        opened = start + timedelta(minutes=index)
        if opened < EVENT_AT:
            step = Decimal("0.03") if index % 2 else Decimal("-0.01")
        else:
            step = Decimal("0.45") if index < 315 else Decimal("0.20")
        value += step
        open_price = value - step
        row: dict[str, object] = {
            "symbol": "XAUUSD",
            "timeframe": "M1",
            "open_time_utc": opened,
            "open": str(open_price),
            "high": str(max(open_price, value) + Decimal("0.05")),
            "low": str(min(open_price, value) - Decimal("0.05")),
            "close": str(value),
            "source": "build15_fixture",
            "source_file_sha256": "a" * 64,
            "source_payload_sha256": "b" * 64,
            "derivation_version": "build15-fixture-v1",
        }
        if mode == "pit":
            row.update(
                {
                    "load_identity": f"build15-pit-{index}",
                    "provenance_class": "pit_observed",
                    "pit_eligible": True,
                    "first_observed_at": (opened + timedelta(minutes=1)).isoformat(),
                }
            )
        else:
            row.update(
                {
                    "research_identity": f"build15-retro-{index}",
                    "provenance_class": "retrospective_history",
                    "pit_eligible": False,
                }
            )
        rows.append(row)
    if future_spike:
        opened = EVENT_AT + timedelta(minutes=30)
        rows.append(
            {
                "symbol": "XAUUSD",
                "timeframe": "M1",
                "open_time_utc": opened,
                "open": "2400",
                "high": "9999",
                "low": "2300",
                "close": "9999",
                "source": "future_build15",
                "load_identity": "future-build15",
                "provenance_class": "pit_observed",
                "pit_eligible": True,
                "first_observed_at": (opened + timedelta(minutes=1)).isoformat(),
            }
        )
    return rows


def _tier_study() -> dict[str, object]:
    episodes: list[dict[str, object]] = []
    for index in range(20):
        episodes.append(
            {
                "event_class": "retail_sales",
                "independent_episode_id": f"retail-{index}",
                "post_abs_return_bps": "10",
                "post_realized_vol_bps": "10",
                "outcome_return_bps": "2" if index % 2 else "-2",
            }
        )
    return run_j4_j15_descriptive(episodes)


def _consensus(schedule: dict[str, object]) -> dict[str, object]:
    return build_consensus_observation(
        schedule=schedule,
        value="0.4",
        unit="percent_mom",
        captured_at=EVENT_AT - timedelta(minutes=30),
        source_url="https://calendar.example.org/immutable/retail-sales",
        source_qualification="timestamped_immutable_approved",
    )


def _actuals(schedule: dict[str, object]) -> tuple[dict[str, object], dict[str, object]]:
    first = build_actual_observation(
        schedule=schedule,
        value="0.8",
        unit="percent_mom",
        first_observed_at=EVENT_AT + timedelta(seconds=3),
        published_at=EVENT_AT,
        source_url="https://www.census.gov/retail/sales.html",
        revision_index=0,
    )
    revision = build_actual_observation(
        schedule=schedule,
        value="0.6",
        unit="percent_mom",
        first_observed_at=EVENT_AT + timedelta(days=20),
        published_at=EVENT_AT + timedelta(days=20),
        source_url="https://www.census.gov/retail/sales.html",
        revision_index=1,
        previous_value="0.8",
    )
    return first, revision


def _surprise_history() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for index in range(STANDARDIZED_SURPRISE_MIN_N + 5):
        value = Decimal("-0.5") + Decimal(index) * Decimal("0.04")
        rows.append(
            {
                "event_class": "retail_sales",
                "unit": "percent_mom",
                "independent_episode_id": f"surprise-{index}",
                "surprise_value": str(value),
                "first_observed_at": (
                    EVENT_AT - timedelta(days=(index + 1) * 7)
                ).isoformat(),
                "pit_reconstructable": True,
            }
        )
    return rows


def _response_history(direction: str = "positive") -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for index in range(CONDITIONAL_RESPONSE_MIN_N + 5):
        rows.append(
            {
                "event_class": "retail_sales",
                "independent_episode_id": f"response-{index}",
                "standardized_surprise_direction": direction,
                "gold_return_15m_bps": str(Decimal("-6") - Decimal(index % 3)),
                "first_observed_at": (
                    EVENT_AT - timedelta(days=(index + 1) * 8)
                ).isoformat(),
                "pit_reconstructable": True,
            }
        )
    return rows


def _controls() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for index in range(NO_NEWS_CONTROL_MIN_N + 5):
        rows.append(
            {
                "control_type": "matched_no_news",
                "control_id": f"control-{index}",
                "abs_gold_return_15m_bps": str(Decimal("2") + Decimal(index % 2)),
                "first_observed_at": (
                    EVENT_AT - timedelta(days=(index + 1) * 5)
                ).isoformat(),
                "pit_reconstructable": True,
            }
        )
    return rows


def _build(
    *,
    as_of: datetime,
    actuals: list[dict[str, object]] | None = None,
    schedules: list[dict[str, object]] | None = None,
    mode: str = "retrospective",
    rows: list[dict[str, object]] | None = None,
) -> dict:
    primary = _schedule()
    return build_macro_event_expert(
        global_environment=_environment(as_of),
        primary_schedule=primary,
        schedule_records=schedules or [primary],
        consensus_observations=[_consensus(primary)],
        actual_observations=actuals or [],
        m1_candle_rows=rows or _m1_rows(mode=mode),
        tier_study=_tier_study(),
        historical_surprise_rows=_surprise_history(),
        historical_response_rows=_response_history(),
        no_news_control_rows=_controls(),
        mode=mode,
    )


def test_build15_is_context_only_and_has_no_macro_direction_rule() -> None:
    first, _ = _actuals(_schedule())
    result = _build(as_of=EVENT_AT + timedelta(minutes=15), actuals=[first])
    packet = result["expert_packet"]

    assert result["expert_version"] == MACRO_EVENT_EXPERT_VERSION
    assert packet["gate_id"] == MACRO_EVENT_GATE_ID
    assert packet["gate_mode"] == "context_only"
    assert packet["conclusion"] == "context_only"
    assert packet["gate_scoreable"] is False
    assert packet["internal_conviction"] is None
    assert verify_expert_gate_packet(packet)
    assert result["direction_policy"]["directional_vote_allowed"] is False
    assert result["direction_policy"]["macro_event_alone_creates_direction"] is False
    assert result["direction_policy"]["vendor_importance_label_used"] is False
    assert result["direction_policy"]["trade_pnl_used"] is False


def test_build15_pre_event_at_release_boundary_cannot_see_actual_three_seconds_later() -> None:
    first, _ = _actuals(_schedule())
    result = _build(as_of=EVENT_AT, actuals=[first])

    assert result["pre_event"]["state"] == "known"
    assert result["pre_event"]["future_values_used"] is False
    assert result["surprise"]["first_print_state"] == "unknown"
    assert result["surprise"]["surprise_state"] == "unknown"
    calc = next(
        item for item in result["expert_packet"]["subcalculators"]
        if item["calculator_id"] == "macro_event_surprise"
    )
    assert calc["vote"] == "unknown"


def test_build15_actual_enters_only_after_first_observed_timestamp() -> None:
    first, _ = _actuals(_schedule())
    before = _build(as_of=EVENT_AT + timedelta(seconds=2), actuals=[first])
    after = _build(as_of=EVENT_AT + timedelta(seconds=3), actuals=[first])

    assert before["surprise"]["first_print_state"] == "unknown"
    assert after["surprise"]["first_print_state"] == "known"
    assert after["surprise"]["surprise_value"] == "0.4"


def test_build15_revision_stays_separate_from_first_print_surprise() -> None:
    first, revision = _actuals(_schedule())
    result = _build(
        as_of=EVENT_AT + timedelta(days=21),
        actuals=[revision, first],
    )

    assert result["surprise"]["surprise_value"] == "0.4"
    assert result["surprise"]["first_print_observation_digest"] == first["observation_digest"]
    assert result["surprise"]["latest_revision_index"] == 1


def test_build15_standardized_surprise_uses_only_pit_historical_episodes() -> None:
    first, _ = _actuals(_schedule())
    result = _build(as_of=EVENT_AT + timedelta(minutes=15), actuals=[first])
    standardized = result["standardized_surprise"]

    assert standardized["state"] == "known"
    assert standardized["sample_n"] == STANDARDIZED_SURPRISE_MIN_N + 5
    assert standardized["direction"] == "positive"
    assert standardized["band"] in {"small", "moderate", "large", "extreme"}
    assert Decimal(standardized["z_score"]) > 0


def test_build15_event_tier_comes_from_independent_gold_episodes_not_vendor_label() -> None:
    result = _build(as_of=EVENT_AT)
    tier = result["event_tier"]

    assert tier["state"] == "known"
    assert tier["tier"] == "tier_2"
    assert tier["independent_episode_n"] == 20
    assert tier["tier_source"] == "independent_gold_episodes"
    assert tier["vendor_importance_label_used"] is False
    assert tier["trade_pnl_used"] is False


def test_build15_event_cluster_is_measured_from_pit_known_schedules() -> None:
    primary = _schedule()
    nearby = _schedule(
        event_class="ism_services",
        external_id="ism-neighbor",
        scheduled_time=time(8, 45),
    )
    result = build_macro_event_expert(
        global_environment=_environment(EVENT_AT),
        primary_schedule=primary,
        schedule_records=[primary, nearby],
        consensus_observations=[_consensus(primary)],
        actual_observations=[],
        m1_candle_rows=_m1_rows(),
        tier_study=_tier_study(),
        historical_surprise_rows=_surprise_history(),
        historical_response_rows=_response_history(),
        no_news_control_rows=_controls(),
    )
    assert result["event_cluster"]["state"] == "clustered"
    assert result["event_cluster"]["event_count_30m"] == 1
    assert result["event_cluster"]["neighbor_event_classes"] == ["ism_services"]


def test_build15_post_release_confirmation_uses_completed_gold_bars() -> None:
    first, _ = _actuals(_schedule())
    result = _build(as_of=EVENT_AT + timedelta(minutes=15), actuals=[first])
    post = result["post_release_confirmation"]

    assert post["state"] == "gold_up"
    assert post["observed_minutes"] == 15
    assert Decimal(post["return_5m_bps"]) > 0
    assert Decimal(post["return_15m_bps"]) > 0
    assert post["future_values_used"] is False


def test_build15_historical_response_and_no_news_control_are_separate() -> None:
    first, _ = _actuals(_schedule())
    result = _build(as_of=EVENT_AT + timedelta(minutes=15), actuals=[first])

    response = result["historical_conditional_response"]
    control = result["no_news_control"]
    comparison = result["event_vs_no_news"]

    assert response["state"] == "known"
    assert response["sample_n"] == CONDITIONAL_RESPONSE_MIN_N + 5
    assert response["historical_response_direction"] == "gold_down"
    assert response["trade_pnl_used"] is False
    assert response["predictive_edge_claimed"] is False

    assert control["state"] == "known"
    assert control["sample_n"] == NO_NEWS_CONTROL_MIN_N + 5
    assert control["control_is_no_news"] is True
    assert comparison["state"] == "known"
    assert Decimal(comparison["event_minus_no_news_abs_bps"]) > 0


def test_build15_insufficient_no_news_control_remains_unknown() -> None:
    primary = _schedule()
    first, _ = _actuals(primary)
    result = build_macro_event_expert(
        global_environment=_environment(EVENT_AT + timedelta(minutes=15)),
        primary_schedule=primary,
        schedule_records=[primary],
        consensus_observations=[_consensus(primary)],
        actual_observations=[first],
        m1_candle_rows=_m1_rows(),
        tier_study=_tier_study(),
        historical_surprise_rows=_surprise_history(),
        historical_response_rows=_response_history(),
        no_news_control_rows=_controls()[:5],
    )
    assert result["no_news_control"]["state"] == "unknown_insufficient_control"
    assert result["event_vs_no_news"]["state"] == "unknown"


def test_build15_pit_mode_and_future_rows_do_not_change_frozen_result() -> None:
    primary = _schedule()
    first, _ = _actuals(primary)
    as_of = EVENT_AT + timedelta(minutes=15)
    base_rows = _m1_rows(mode="pit")
    future_rows = _m1_rows(mode="pit", future_spike=True)

    kwargs = dict(
        global_environment=_environment(as_of),
        primary_schedule=primary,
        schedule_records=[primary],
        consensus_observations=[_consensus(primary)],
        actual_observations=[first],
        tier_study=_tier_study(),
        historical_surprise_rows=_surprise_history(),
        historical_response_rows=_response_history(),
        no_news_control_rows=_controls(),
        mode="pit",
    )
    first_result = build_macro_event_expert(m1_candle_rows=base_rows, **kwargs)
    second_result = build_macro_event_expert(m1_candle_rows=future_rows, **kwargs)

    assert first_result["expert_packet"]["packet_digest"] == second_result["expert_packet"]["packet_digest"]
    assert first_result["post_release_confirmation"] == second_result["post_release_confirmation"]
    assert first_result["future_values_used"] is False


def test_build15_future_historical_rows_are_excluded_from_standardization_and_response() -> None:
    primary = _schedule()
    first, _ = _actuals(primary)
    surprise_history = _surprise_history()
    surprise_history.append(
        {
            "event_class": "retail_sales",
            "unit": "percent_mom",
            "independent_episode_id": "future-surprise",
            "surprise_value": "999",
            "first_observed_at": (EVENT_AT + timedelta(days=1)).isoformat(),
            "pit_reconstructable": True,
        }
    )
    response_history = _response_history()
    response_history.append(
        {
            "event_class": "retail_sales",
            "independent_episode_id": "future-response",
            "standardized_surprise_direction": "positive",
            "gold_return_15m_bps": "999",
            "first_observed_at": (EVENT_AT + timedelta(days=1)).isoformat(),
            "pit_reconstructable": True,
        }
    )

    result = build_macro_event_expert(
        global_environment=_environment(EVENT_AT + timedelta(minutes=15)),
        primary_schedule=primary,
        schedule_records=[primary],
        consensus_observations=[_consensus(primary)],
        actual_observations=[first],
        m1_candle_rows=_m1_rows(),
        tier_study=_tier_study(),
        historical_surprise_rows=surprise_history,
        historical_response_rows=response_history,
        no_news_control_rows=_controls(),
    )

    assert result["standardized_surprise"]["sample_n"] == STANDARDIZED_SURPRISE_MIN_N + 5
    assert result["historical_conditional_response"]["sample_n"] == CONDITIONAL_RESPONSE_MIN_N + 5


def test_build15_rejects_primary_schedule_unknown_at_as_of() -> None:
    primary = build_schedule_observation(
        event_class="retail_sales",
        source_key="census_economic_indicators",
        external_id="future-known-schedule",
        scheduled_date=date(2026, 9, 18),
        scheduled_time=time(8, 30),
        timezone_name="America/New_York",
        first_observed_at=EVENT_AT + timedelta(days=1),
        source_url="https://www.census.gov/economic-indicators/calendar-listview.html",
    )
    with pytest.raises(ValueError, match="not known"):
        build_macro_event_expert(
            global_environment=_environment(EVENT_AT),
            primary_schedule=primary,
            schedule_records=[primary],
            consensus_observations=[],
            actual_observations=[],
            m1_candle_rows=_m1_rows(),
            tier_study=_tier_study(),
            historical_surprise_rows=_surprise_history(),
            historical_response_rows=_response_history(),
            no_news_control_rows=_controls(),
        )
