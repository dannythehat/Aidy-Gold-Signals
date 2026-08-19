import zipfile
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import pytest

from aidy.historical_backfill import (
    DERIVATION_VERSION,
    HISTDATA_SOURCE_TIMEZONE,
    RESEARCH_BACKFILL_MANIFEST,
    RESEARCH_CANDLES,
    RETROSPECTIVE_PROVENANCE,
    HistDataArchive,
    HistDataPeriod,
    _token_from_html,
    backfill_identity,
    build_research_candles,
    chunk_key,
    manifest_merge_sql,
    manifest_row,
    merge_sql,
    parse_histdata_m1,
    planned_periods,
    read_histdata_archive,
    request_signature,
    stage_fields,
)


def archive(text: str, *, year: int = 2024) -> HistDataArchive:
    raw = text.encode()
    return HistDataArchive(
        period=HistDataPeriod(year),
        zip_name=f"DAT_ASCII_XAUUSD_M1_{year}.zip",
        zip_sha256=sha256(b"zip").hexdigest(),
        payload_name=f"DAT_ASCII_XAUUSD_M1_{year}.csv",
        payload_sha256=sha256(raw).hexdigest(),
        payload_text=text,
        status_report_sha256=None,
    )


def sample_text() -> str:
    return (
        "20240102 000000;2000.00;2001.00;1999.00;2000.50;0\n"
        "20240102 000100;2000.50;2002.00;2000.00;2001.50;0\n"
        "20240102 000200;2001.50;2003.00;2001.00;2002.50;0\n"
        "20240102 000300;2002.50;2004.00;2002.00;2003.50;0\n"
        "20240102 000400;2003.50;2005.00;2003.00;2004.50;0\n"
        "20240102 000500;2004.50;2006.00;2004.00;2005.50;0"
    )


def test_research_tables_are_structurally_separate_from_live_pit_contract():
    candle_fields = {field.name for field in RESEARCH_CANDLES.fields}
    assert RESEARCH_CANDLES.name == "research_candles"
    assert "provenance_class" in candle_fields
    assert "pit_eligible" in candle_fields
    assert "first_observed_at" not in candle_fields
    assert RESEARCH_BACKFILL_MANIFEST.name == "research_backfill_manifest"
    assert RESEARCH_BACKFILL_MANIFEST.fields[-1].name == "out_of_order_rows"
    assert RESEARCH_BACKFILL_MANIFEST.fields[-1].mode == "NULLABLE"


def test_histdata_fixed_est_is_normalized_to_utc_without_dst_inference():
    bars, stats = parse_histdata_m1("20240701 120000;2300;2301;2299;2300.5;0\n")
    assert stats.rows == 1
    assert stats.out_of_order_rows == 0
    assert bars[0].open_time_utc == datetime(2024, 7, 1, 17, 0, tzinfo=UTC)
    assert HISTDATA_SOURCE_TIMEZONE == "EST_FIXED_UTC_MINUS_05"


def test_exact_duplicates_are_deduped_but_conflicting_duplicates_fail_closed():
    line = "20240102 000000;2000;2001;1999;2000.5;0"
    bars, stats = parse_histdata_m1(line + "\n" + line + "\n")
    assert len(bars) == 1
    assert stats.duplicate_rows == 1
    with pytest.raises(ValueError, match="Conflicting duplicate"):
        parse_histdata_m1(line + "\n20240102 000000;2000;2002;1999;2001;0\n")


def test_source_order_anomaly_is_counted_then_canonicalized_by_timestamp():
    bars, stats = parse_histdata_m1(
        "20240102 000100;2;3;1;2;0\n20240102 000000;2;3;1;2;0\n"
    )
    assert stats.out_of_order_rows == 1
    assert [bar.source_open_time for bar in bars] == [
        "20240102 000000",
        "20240102 000100",
    ]


def test_ohlc_invariants_fail_closed():
    with pytest.raises(ValueError, match="high invariant"):
        parse_histdata_m1("20240102 000000;2;1;0;2;0\n")


def test_source_aligned_aggregation_builds_m5_and_h1_from_m1():
    text = sample_text()
    bars, _ = parse_histdata_m1(text)
    source = archive(text)
    candles = build_research_candles(
        bars,
        timeframes=["M1", "M5", "H1"],
        symbol="XAUUSD",
        archive=source,
        ingested_at=datetime(2026, 8, 19, 12, 0, tzinfo=UTC),
        backfill_run_id="run-1",
    )
    assert len(candles["M1"]) == 6
    assert len(candles["M5"]) == 2
    first = candles["M5"][0]
    assert (first.open, first.high, first.low, first.close) == (
        "2000.00",
        "2005.00",
        "1999.00",
        "2004.50",
    )
    assert first.input_rows == 5
    assert first.open_time_utc == datetime(2024, 1, 2, 5, 0, tzinfo=UTC)
    assert first.derived_from_timeframe == "M1"
    assert first.to_row()["provenance_class"] == RETROSPECTIVE_PROVENANCE
    assert first.to_row()["pit_eligible"] is False
    assert first.to_row()["derivation_version"] == DERIVATION_VERSION


def test_research_identity_is_stable_across_run_ids_and_ingestion_times():
    text = sample_text()
    bars, _ = parse_histdata_m1(text)
    source = archive(text)
    one = build_research_candles(
        bars,
        timeframes=["M1"],
        symbol="XAUUSD",
        archive=source,
        ingested_at=datetime(2026, 8, 19, 12, 0, tzinfo=UTC),
        backfill_run_id="run-1",
    )["M1"][0]
    two = build_research_candles(
        bars,
        timeframes=["M1"],
        symbol="XAUUSD",
        archive=source,
        ingested_at=datetime(2026, 8, 20, 12, 0, tzinfo=UTC),
        backfill_run_id="run-2",
    )["M1"][0]
    assert one.research_identity == two.research_identity
    assert one.candle_key == two.candle_key
    assert one.to_row()["backfill_run_id"] != two.to_row()["backfill_run_id"]


def test_chunk_key_is_stable_and_period_specific():
    assert chunk_key(symbol="XAUUSD", period=HistDataPeriod(2024)) == chunk_key(
        symbol="XAUUSD", period=HistDataPeriod(2024)
    )
    assert chunk_key(symbol="XAUUSD", period=HistDataPeriod(2024)) != chunk_key(
        symbol="XAUUSD", period=HistDataPeriod(2025)
    )


def test_manifest_is_retrospective_and_reconciles_timeframe_counts():
    text = sample_text()
    bars, stats = parse_histdata_m1(text)
    source = archive(text)
    now = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)
    candles = build_research_candles(
        bars,
        timeframes=["M1", "M5", "H1"],
        symbol="XAUUSD",
        archive=source,
        ingested_at=now,
        backfill_run_id="run-1",
    )
    row = manifest_row(
        archive=source,
        symbol="XAUUSD",
        timeframes=["M1", "M5", "H1"],
        stats=stats,
        candles=candles,
        ingested_at=now,
        run_id="run-1",
    )
    assert row["pit_eligible"] is False
    assert row["provenance_class"] == RETROSPECTIVE_PROVENANCE
    assert row["m1_rows"] == 6
    assert row["out_of_order_rows"] == 0
    assert row["timeframe_counts"] == {"M1": 6, "M5": 2, "H1": 1}


def test_insert_only_merges_are_idempotent_by_immutable_identity():
    candle_sql = merge_sql(project="p", dataset="d")
    manifest_sql = manifest_merge_sql(project="p", dataset="d")
    assert "ON T.research_identity = S.research_identity" in candle_sql
    assert "WHEN MATCHED" not in candle_sql
    assert "ON T.backfill_identity = S.backfill_identity" in manifest_sql
    assert "WHEN MATCHED" not in manifest_sql
    assert stage_fields(RESEARCH_CANDLES)[0].name == "_backfill_run_id"


def test_planned_periods_use_annual_archives_for_complete_years_and_months_for_current_year():
    periods = planned_periods(2024, 2026, current_date=datetime(2026, 8, 19, tzinfo=UTC))
    assert periods[:2] == (HistDataPeriod(2024), HistDataPeriod(2025))
    assert periods[-1] == HistDataPeriod(2026, 8)
    assert len(periods) == 10


def test_archive_reader_requires_exactly_one_csv(tmp_path: Path):
    path = tmp_path / "one.zip"
    with zipfile.ZipFile(path, "w") as zipped:
        zipped.writestr("DAT_ASCII_XAUUSD_M1_2024.csv", sample_text())
        zipped.writestr("STATUS.txt", "ok")
    source = read_histdata_archive(path, HistDataPeriod(2024))
    assert source.payload_name.endswith(".csv")
    assert source.status_report_sha256 is not None

    bad_path = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad_path, "w") as zipped:
        zipped.writestr("a.csv", sample_text())
        zipped.writestr("b.csv", sample_text())
    with pytest.raises(RuntimeError, match="exactly one CSV"):
        read_histdata_archive(bad_path, HistDataPeriod(2024))


def test_manifest_identity_is_stable_for_same_source_and_changes_with_requested_shape():
    text = sample_text()
    source = archive(text)
    one = backfill_identity(archive=source, symbol="XAUUSD", timeframes=["M1", "H1"])
    two = backfill_identity(archive=source, symbol="XAUUSD", timeframes=["H1", "M1"])
    three = backfill_identity(archive=source, symbol="XAUUSD", timeframes=["M1"])
    assert one == two
    assert one != three


def test_histdata_token_parser_is_attribute_order_independent():
    assert _token_from_html('<input class="x" value="abc&amp;123" name="z" id="tk">') == "abc&123"
    with pytest.raises(RuntimeError, match="download token"):
        _token_from_html("<html></html>")


def test_request_signature_is_order_independent_and_versioned():
    assert request_signature(["M1", "H1"]) == request_signature(["H1", "M1"])
    assert request_signature(["M1"]) != request_signature(["M1", "H1"])
