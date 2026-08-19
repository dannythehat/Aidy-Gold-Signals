from datetime import UTC, datetime, timedelta

from aidy.pit_reconstruction import query_contract, select_latest_candles_as_of


def test_future_dated_candle_is_not_visible_even_if_observed_early() -> None:
    cutoff = datetime(2026, 8, 19, 10, 0, tzinfo=UTC)
    row = {
        "load_identity": "future-candle",
        "record_type": "candle",
        "evidence_id": "future-candle-evidence",
        "archive_key": "archive/future.json",
        "payload_digest": "future-digest",
        "revision_index": 1,
        "source": "fixture",
        "symbol": "XAUUSD",
        "timeframe": "M1",
        "open_time_utc": cutoff + timedelta(minutes=1),
        "first_observed_at": cutoff - timedelta(seconds=1),
    }
    assert select_latest_candles_as_of([row], as_of=cutoff, symbol="XAUUSD") == []


def test_bigquery_candle_query_enforces_open_time_cutoff() -> None:
    sql = query_contract(project="aidy-signals", dataset="aidy_analytics_test")["candles"].sql
    assert "open_time_utc <= @as_of" in sql
    assert "first_observed_at <= @as_of" in sql
