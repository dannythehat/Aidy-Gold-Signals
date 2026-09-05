from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from aidy.config import AidySettings
from aidy.forward_live_observer import _blocked_reason
from aidy.twelve_data_market import (
    MAX_OPEN_SESSION_LAG_SECONDS,
    TwelveDataOhlcGateway,
    aggregate_m1,
    day53_twelve_data_market_manifest,
    expected_market_minute_opens,
    latest_completed_d1_bucket,
)

ROOT = Path(__file__).resolve().parents[1]
API_KEY = "td_test_secret"
FETCHED = datetime(2026, 9, 2, 4, 44, 41, tzinfo=UTC)


def _bar(opened: datetime, *, value: Decimal = Decimal("4329.50")) -> dict[str, str]:
    return {
        "datetime": opened.strftime("%Y-%m-%d %H:%M:%S"),
        "open": str(value),
        "high": str(value + Decimal("0.80")),
        "low": str(value - Decimal("0.60")),
        "close": str(value + Decimal("0.20")),
    }


def _response(values: list[dict[str, str]], *, headers: dict[str, str] | None = None):
    return httpx.Response(
        200,
        json={
            "meta": {
                "symbol": "XAU/USD",
                "interval": "1min",
                "currency": "USD",
                "exchange_timezone": "Australia/Sydney",
                "exchange": "COMMODITY",
                "type": "Precious Metal",
            },
            "values": values,
            "status": "ok",
        },
        headers=headers,
    )


@pytest.mark.asyncio
async def test_live_adapter_drops_forming_bar_and_records_real_freshness_and_credits() -> None:
    seen_auth = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_auth
        seen_auth = request.headers.get("Authorization")
        assert API_KEY not in str(request.url)
        return _response(
            [
                _bar(datetime(2026, 9, 2, 4, 44, tzinfo=UTC)),
                _bar(datetime(2026, 9, 2, 4, 43, tzinfo=UTC), value=Decimal(4328)),
                _bar(datetime(2026, 9, 2, 4, 42, tzinfo=UTC), value=Decimal(4327)),
            ],
            headers={
                "Api-Credits-Request": "1",
                "Api-Credits-Used": "2",
                "Api-Credits-Left": "6",
            },
        )

    result = await TwelveDataOhlcGateway(
        api_key=API_KEY,
        transport=httpx.MockTransport(handler),
    ).fetch_1m(outputsize=30, clock=lambda: FETCHED)

    assert seen_auth == f"apikey {API_KEY}"
    assert result.forming_bar_count == 1
    assert [bar.open_time_utc for bar in result.closed_bars] == [
        datetime(2026, 9, 2, 4, 42, tzinfo=UTC),
        datetime(2026, 9, 2, 4, 43, tzinfo=UTC),
    ]
    assert result.latest_closed_bar_close_utc == datetime(2026, 9, 2, 4, 44, tzinfo=UTC)
    assert result.open_session_lag_seconds == pytest.approx(41.0)
    assert result.freshness_state == "fresh"
    assert result.credit_headers == {
        "api-credits-request": "1",
        "api-credits-used": "2",
        "api-credits-left": "6",
    }
    assert result.meta["exchange"] == "COMMODITY"


@pytest.mark.asyncio
async def test_open_session_fifteen_minute_delay_is_explicitly_stale() -> None:
    latest_open = FETCHED.replace(second=0, microsecond=0) - timedelta(minutes=16)
    result = await TwelveDataOhlcGateway(
        api_key=API_KEY,
        transport=httpx.MockTransport(lambda request: _response([_bar(latest_open)])),
    ).fetch_1m(clock=lambda: FETCHED)
    assert result.session_open_at_fetch is True
    assert result.open_session_lag_seconds is not None
    assert result.open_session_lag_seconds > 15 * 60
    assert result.freshness_state == "stale"
    assert MAX_OPEN_SESSION_LAG_SECONDS == 180.0


@pytest.mark.asyncio
async def test_weekend_vendor_prints_are_preserved_as_response_but_not_admitted_as_market_bars() -> None:
    saturday = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
    fetched = saturday + timedelta(minutes=5)
    result = await TwelveDataOhlcGateway(
        api_key=API_KEY,
        transport=httpx.MockTransport(lambda request: _response([_bar(saturday)])),
    ).fetch_1m(clock=lambda: fetched)
    assert result.raw_bar_count == 1
    assert result.off_session_bar_count == 1
    assert result.closed_bars == ()
    assert result.session_open_at_fetch is False
    assert result.freshness_state == "session_closed"


def test_real_iana_timezone_moves_1700_new_york_close_across_dst() -> None:
    summer_start, summer_close = latest_completed_d1_bucket(
        datetime(2026, 7, 2, 22, 0, tzinfo=UTC)
    )
    winter_start, winter_close = latest_completed_d1_bucket(
        datetime(2026, 1, 2, 23, 0, tzinfo=UTC)
    )
    assert summer_close == datetime(2026, 7, 2, 21, 0, tzinfo=UTC)
    assert summer_start == datetime(2026, 7, 1, 22, 0, tzinfo=UTC)
    assert winter_close == datetime(2026, 1, 2, 22, 0, tzinfo=UTC)
    assert winter_start == datetime(2026, 1, 1, 23, 0, tzinfo=UTC)


def test_session_calendar_not_arithmetic_denominator_for_h4_spanning_daily_break() -> None:
    start = datetime(2026, 9, 2, 20, 0, tzinfo=UTC)
    end = datetime(2026, 9, 3, 0, 0, tzinfo=UTC)
    expected = expected_market_minute_opens(start, end)
    assert len(expected) == 180
    assert datetime(2026, 9, 2, 21, 30, tzinfo=UTC) not in expected
    assert datetime(2026, 9, 2, 22, 0, tzinfo=UTC) in expected


def _stored_rows(start: datetime, end: datetime) -> list[dict[str, object]]:
    rows = []
    for index, opened in enumerate(expected_market_minute_opens(start, end)):
        value = Decimal(4300) + Decimal(index) / Decimal(100)
        rows.append(
            {
                "id": f"m1-{index}",
                "open_time_utc": opened,
                "open": str(value),
                "high": str(value + Decimal("0.5")),
                "low": str(value - Decimal("0.4")),
                "close": str(value + Decimal("0.1")),
                "revision_index": 1,
                "payload_digest": f"{index:064x}"[-64:],
            }
        )
    return rows


def test_one_missing_expected_minute_makes_bucket_inadmissible() -> None:
    start = datetime(2026, 9, 2, 20, 0, tzinfo=UTC)
    end = datetime(2026, 9, 3, 0, 0, tzinfo=UTC)
    rows = _stored_rows(start, end)
    candle, state = aggregate_m1(
        rows[:-1],
        timeframe="4h",
        start_utc=start,
        end_utc=end,
        first_observed_at=end + timedelta(seconds=30),
    )
    assert candle is None
    assert state["expected_market_minutes"] == 180
    assert state["observed_market_minutes"] == 179
    assert state["admissible"] is False


def test_complete_roll_crossing_h4_uses_true_m1_high_low_and_is_admissible() -> None:
    start = datetime(2026, 9, 2, 20, 0, tzinfo=UTC)
    end = datetime(2026, 9, 3, 0, 0, tzinfo=UTC)
    rows = _stored_rows(start, end)
    candle, state = aggregate_m1(
        rows,
        timeframe="4h",
        start_utc=start,
        end_utc=end,
        first_observed_at=end + timedelta(seconds=30),
    )
    assert candle is not None
    assert state["admissible"] is True
    assert candle["tick_volume"] == 180
    assert Decimal(str(candle["high"])) == max(Decimal(str(row["high"])) for row in rows)
    assert Decimal(str(candle["low"])) == min(Decimal(str(row["low"])) for row in rows)


def test_missing_spread_is_advisory_but_observed_bad_spread_still_blocks() -> None:
    snapshot = {
        "capture_status": "complete",
        "quote_age_seconds": 42.0,
        "bid": None,
        "ask": None,
        "spread": None,
        "latest_m1_id": "m1",
        "latest_m5_id": "m5",
        "latest_m15_id": "m15",
        "latest_h1_id": "h1",
        "latest_h4_id": "h4",
        "latest_d1_id": "d1",
        "data_availability_json": json.dumps({"spread_advisory_state": "unavailable"}),
    }
    assert _blocked_reason(snapshot) is None
    snapshot["data_availability_json"] = json.dumps(
        {"spread_advisory_state": "out_of_tolerance"}
    )
    assert _blocked_reason(snapshot) == "observed_spread_out_of_tolerance"


def test_twelve_data_basic_quota_requires_at_least_five_minute_polling() -> None:
    values = {
        "AIDY_CAPTURE_ENABLED": "true",
        "AIDY_MARKET_DATA_SOURCE": "twelve_data",
        "AIDY_MARKET_DATA_OWNERSHIP": "public_independent",
    }
    settings = AidySettings._from_getter(lambda name, default: values.get(name, default))
    assert settings.market_poll_seconds == 300.0
    values["AIDY_MARKET_POLL_SECONDS"] = "60"
    with pytest.raises(RuntimeError, match="800-request daily quota"):
        AidySettings._from_getter(lambda name, default: values.get(name, default))


def test_manifest_freezes_forming_bar_session_completeness_and_pit_rules() -> None:
    manifest = day53_twelve_data_market_manifest()
    assert manifest["forming_bar_rule"] == "admit_only_when_close_time_strictly_before_fetch_time"
    assert manifest["session_timezone"] == "America/New_York"
    assert manifest["daily_close_boundary"] == "17:00 America/New_York"
    assert manifest["off_session_vendor_bars_admissible"] is False
    assert set(manifest["completeness_thresholds"].values()) == {"1.00"}
    assert manifest["vendor_revisions_overwrite_prior_evidence"] is False
    assert manifest["spread_missing_blocks"] is False
    assert manifest["live_money_execution_allowed"] is False


def test_worker_source_does_not_import_broker_execution_for_twelve_data() -> None:
    runtime = (ROOT / "src" / "aidy" / "runtime.py").read_text(encoding="utf-8")
    module = (ROOT / "src" / "aidy" / "twelve_data_market.py").read_text(encoding="utf-8")
    assert "TwelveDataOhlcGateway" in runtime
    assert "MetaApi" not in module
    assert "Vantage" not in module
    assert "Super Signals" not in module


def test_twelve_admission_plan_is_keyed_by_request_ledger_id() -> None:
    migration = (ROOT / "migrations" / "d1" / "0014_twelve_admission_plan.sql").read_text(
        encoding="utf-8"
    )
    assert "INDEXED BY idx_twelve_data_request_ledger_completion_success" in migration
    assert "INDEXED BY idx_twelve_data_bootstrap_requests_by_ledger_window" in migration
