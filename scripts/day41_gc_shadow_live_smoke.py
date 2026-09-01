from __future__ import annotations

import argparse
import csv
import io
import json
import os
import subprocess
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

import httpx

from aidy.databento_gc import (
    DATABENTO_DATASET,
    GC_CONTINUOUS_SYMBOL,
    DatabentoHistoricalClient,
    HistoricalRequest,
)
from aidy.gc_shadow_spine import (
    HISTORICAL_XAU_REFERENCE_SOURCE,
    XauObservation,
    canonical_json,
    day41_architecture_manifest,
    digest,
    normalize_databento_api_key,
    pair_shadow_observations,
    parse_databento_ohlcv_jsonl,
    resolve_gc_contract_map,
)
from aidy.historical_backfill import (
    RETROSPECTIVE_PROVENANCE,
    HistDataPeriod,
    download_histdata_period,
    read_histdata_archive,
)

HISTORICAL_SMOKE_MAX_COST_USD = Decimal("0.25")
DATABENTO_SYMBOLOGY_URL = "https://hist.databento.com/v0/symbology.resolve"
PAIR_MAX_SKEW_SECONDS = 60


def _parse_utc_timestamp(value: object, *, name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"Databento {name} is missing from the entitled range.")
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError as exc:
        raise RuntimeError(f"Databento {name} is not a valid ISO-8601 timestamp.") from exc
    if parsed.tzinfo is None:
        raise RuntimeError(f"Databento {name} must be timezone-aware.")
    return parsed.astimezone(UTC)


def _last_fully_available_utc_day(dataset_range: dict[str, object]) -> datetime:
    schema_map = dataset_range.get("schema")
    if not isinstance(schema_map, dict):
        raise TypeError("Databento dataset range did not include per-schema availability.")
    ohlcv_range = schema_map.get("ohlcv-1m")
    if not isinstance(ohlcv_range, dict):
        raise TypeError("Databento account has no entitled ohlcv-1m availability range.")

    available_start = _parse_utc_timestamp(
        ohlcv_range.get("start"),
        name="ohlcv-1m start",
    )
    available_end = _parse_utc_timestamp(
        ohlcv_range.get("end"),
        name="ohlcv-1m end",
    )
    if available_end <= available_start:
        raise RuntimeError("Databento ohlcv-1m entitled range is empty.")

    target_date = available_end.date() - timedelta(days=1)
    target_start = datetime.combine(target_date, time.min, tzinfo=UTC)
    target_end = target_start + timedelta(days=1)
    if target_start < available_start or target_end > available_end:
        raise RuntimeError("Databento has no fully entitled UTC day for Day 41 acceptance.")
    return target_start


def _gc_request_window(target_day: datetime) -> tuple[datetime, datetime]:
    target_end = target_day + timedelta(days=1)
    return target_end - timedelta(minutes=10), target_end


def _symbology_resolve(
    api_key: str,
    *,
    symbols: str,
    stype_in: str,
    stype_out: str,
    start_date: str,
    end_date: str,
) -> dict[str, object]:
    response = httpx.post(
        DATABENTO_SYMBOLOGY_URL,
        auth=httpx.BasicAuth(api_key, ""),
        timeout=20.0,
        data={
            "dataset": DATABENTO_DATASET,
            "symbols": symbols,
            "stype_in": stype_in,
            "stype_out": stype_out,
            "start_date": start_date,
            "end_date": end_date,
        },
        headers={"User-Agent": "AIDY-Signals/Day41"},
    )
    if response.is_error:
        safe_body = response.text.replace(api_key, "***")[:1000]
        raise RuntimeError(
            f"Databento symbology resolve failed with HTTP {response.status_code}: {safe_body}"
        )
    payload = response.json()
    if not isinstance(payload, dict):
        raise TypeError("Databento symbology endpoint returned a non-object payload.")
    return payload


def _continuous_instrument_ids(payload: dict[str, object]) -> list[str]:
    result = payload.get("result")
    if not isinstance(result, dict):
        raise TypeError("Databento continuous resolution is missing its result mapping.")
    entries = result.get(GC_CONTINUOUS_SYMBOL)
    if not isinstance(entries, list) or not entries:
        raise RuntimeError("Databento continuous resolution returned no GC instruments.")
    instrument_ids = sorted(
        {
            str(entry.get("s"))
            for entry in entries
            if isinstance(entry, dict) and str(entry.get("s", "")).isdigit()
        }
    )
    if not instrument_ids:
        raise RuntimeError("Databento continuous resolution returned no numeric GC instrument IDs.")
    return instrument_ids


def _histdata_row_time(raw: str, *, line_number: int) -> datetime:
    try:
        return datetime.strptime(f"{raw}-0500", "%Y%m%d %H%M%S%z").astimezone(UTC)
    except ValueError as exc:
        raise RuntimeError(
            f"HistData target-window timestamp is invalid at line {line_number}."
        ) from exc


def _histdata_decimal(raw: str, *, field: str, line_number: int) -> Decimal:
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise RuntimeError(
            f"HistData target-window {field} is invalid at line {line_number}."
        ) from exc
    if not value.is_finite() or value <= 0:
        raise RuntimeError(
            f"HistData target-window {field} is not a positive finite value at line {line_number}."
        )
    return value


def _target_histdata_bar(payload_text: str, gc_observed_at: datetime) -> dict[str, object]:
    candidates: list[dict[str, object]] = []
    reader = csv.reader(io.StringIO(payload_text), delimiter=";")
    for line_number, row in enumerate(reader, start=1):
        if not row or all(not value.strip() for value in row):
            continue
        if len(row) < 5:
            continue
        source_open_time = row[0].strip()
        source_time_utc = _histdata_row_time(source_open_time, line_number=line_number)
        skew = abs((source_time_utc - gc_observed_at).total_seconds())
        if skew > PAIR_MAX_SKEW_SECONDS:
            continue
        values = tuple(value.strip() for value in row[1:5])
        open_value, high_value, low_value, close_value = (
            _histdata_decimal(value, field=field, line_number=line_number)
            for value, field in zip(
                values,
                ("open", "high", "low", "close"),
                strict=True,
            )
        )
        if high_value < max(open_value, low_value, close_value):
            raise RuntimeError("HistData target-window high invariant failed.")
        if low_value > min(open_value, high_value, close_value):
            raise RuntimeError("HistData target-window low invariant failed.")
        candidates.append(
            {
                "line_number": line_number,
                "source_open_time": source_open_time,
                "open_time_utc": source_time_utc,
                "ohlc": values,
                "close": close_value,
                "skew_seconds": skew,
            }
        )

    if not candidates:
        raise RuntimeError(
            "HistData XAUUSD has no M1 bar within 60 seconds of the Databento GC observation."
        )
    minimum_skew = min(float(item["skew_seconds"]) for item in candidates)
    nearest = [item for item in candidates if float(item["skew_seconds"]) == minimum_skew]
    nearest_times = {item["open_time_utc"] for item in nearest}
    if len(nearest_times) != 1:
        raise RuntimeError("HistData target-window has ambiguous equally-near timestamps.")
    unique_ohlc = {item["ohlc"] for item in nearest}
    if len(unique_ohlc) != 1:
        raise RuntimeError("HistData target minute contains conflicting duplicate candles.")

    selected = nearest[0]
    return {
        "source_open_time": selected["source_open_time"],
        "open_time_utc": selected["open_time_utc"],
        "close": selected["close"],
        "pair_skew_seconds": minimum_skew,
        "target_duplicate_rows": len(nearest),
    }


def _matching_histdata_xau(
    gc_observed_at: datetime,
    *,
    cache_dir: Path,
) -> tuple[XauObservation, dict[str, object]]:
    period = HistDataPeriod(gc_observed_at.year, gc_observed_at.month)
    archive_path = download_histdata_period(period, cache_dir=cache_dir)
    archive = read_histdata_archive(archive_path, period)
    selected = _target_histdata_bar(archive.payload_text, gc_observed_at)
    open_time_utc = selected["open_time_utc"]
    close = selected["close"]
    if not isinstance(open_time_utc, datetime) or not isinstance(close, Decimal):
        raise RuntimeError("HistData target-window parser returned invalid typed values.")

    provenance = {
        "source": HISTORICAL_XAU_REFERENCE_SOURCE,
        "source_file": archive.zip_name,
        "source_file_sha256": archive.zip_sha256,
        "source_payload_sha256": archive.payload_sha256,
        "source_open_time": selected["source_open_time"],
        "open_time_utc": open_time_utc.isoformat(),
        "close": str(close),
        "price_basis": "bid",
        "provenance_class": RETROSPECTIVE_PROVENANCE,
        "pit_eligible": False,
    }
    xau = XauObservation(
        observed_at=open_time_utc,
        price=close,
        source=HISTORICAL_XAU_REFERENCE_SOURCE,
        source_digest=digest(provenance),
        provenance_class=RETROSPECTIVE_PROVENANCE,
        pit_eligible=False,
    )
    evidence = {
        **provenance,
        "archive_payload_name": archive.payload_name,
        "archive_status_report_sha256": archive.status_report_sha256,
        "pair_skew_seconds": selected["pair_skew_seconds"],
        "target_duplicate_rows": selected["target_duplicate_rows"],
        "full_archive_global_conflicts_ignored": False,
        "target_window_only_parsing": True,
    }
    return xau, evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="day41_live_evidence.json")
    parser.add_argument("--raw-gc", default="day41_gc_sample.jsonl")
    args = parser.parse_args()

    raw_key = os.environ.get("DATABENTO_API_KEY", "")
    if not raw_key.strip():
        raise RuntimeError("DATABENTO_API_KEY is required for genuine Day 41 evidence.")
    api_key = normalize_databento_api_key(raw_key)
    os.environ["DATABENTO_API_KEY"] = api_key

    root = Path(__file__).resolve().parents[1]
    head_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    observed_at = datetime.now(UTC)

    raw_path = Path(args.raw_gc)
    with DatabentoHistoricalClient.from_env() as client:
        entitlement = client.assert_gc_entitlement()
        dataset_range = client.dataset_range()
        target_day = _last_fully_available_utc_day(dataset_range)
        request_start, request_end = _gc_request_window(target_day)
        request = HistoricalRequest(
            schema="ohlcv-1m",
            start=request_start.isoformat(),
            end=request_end.isoformat(),
        )
        quote = client.estimate_cost(request)
        if quote.quoted_cost_usd > HISTORICAL_SMOKE_MAX_COST_USD:
            raise RuntimeError(
                "Day 41 historical smoke quote exceeds the strict $0.25 acceptance cap."
            )
        receipt = client.download_jsonl(request, quote=quote, output_path=raw_path)

    start_date = target_day.date().isoformat()
    end_date = (target_day.date() + timedelta(days=1)).isoformat()
    continuous_resolution = _symbology_resolve(
        api_key,
        symbols=GC_CONTINUOUS_SYMBOL,
        stype_in="continuous",
        stype_out="instrument_id",
        start_date=start_date,
        end_date=end_date,
    )
    instrument_ids = _continuous_instrument_ids(continuous_resolution)
    raw_resolutions: dict[str, dict[str, object]] = {}
    for instrument_id in instrument_ids:
        raw_resolutions[instrument_id] = _symbology_resolve(
            api_key,
            symbols=instrument_id,
            stype_in="instrument_id",
            stype_out="raw_symbol",
            start_date=start_date,
            end_date=end_date,
        )
    contract_map = resolve_gc_contract_map(continuous_resolution, raw_resolutions)

    observations = parse_databento_ohlcv_jsonl(
        raw_path.read_text(encoding="utf-8"),
        contract_by_instrument_id=contract_map,
    )
    if not observations:
        raise RuntimeError("Databento returned no mapped GC minute observations.")
    gc = max(observations, key=lambda item: item.observed_at)

    xau, histdata_evidence = _matching_histdata_xau(
        gc.observed_at,
        cache_dir=root / ".day41_histdata_cache",
    )
    pair = pair_shadow_observations(gc, xau, max_skew_seconds=PAIR_MAX_SKEW_SECONDS)
    if pair["paired"] is not True:
        raise RuntimeError("Genuine historical Databento GC and HistData XAU observations did not pair.")
    if pair["historical_research_pair"] is not True:
        raise RuntimeError("Day 41 historical acceptance pair lost retrospective provenance.")

    symbology_evidence = {
        "continuous": continuous_resolution,
        "raw": raw_resolutions,
    }
    evidence = {
        "evidence_version": "aidy_day41_genuine_historical_shadow_evidence_v1",
        "candidate_head_sha": head_sha,
        "observed_at_utc": observed_at.isoformat(),
        "target_historical_utc_day": start_date,
        "genuine_databento_observation_ingested": True,
        "genuine_histdata_xau_observation_ingested": True,
        "historical_research_pair": True,
        "formal_forward_evidence_created": False,
        "pit_eligible": False,
        "databento_entitlement": entitlement,
        "databento_request": request.payload(),
        "databento_quote_usd": str(quote.quoted_cost_usd),
        "databento_historical_smoke_max_cost_usd": str(HISTORICAL_SMOKE_MAX_COST_USD),
        "databento_download_receipt": receipt,
        "databento_contract_map": {str(key): value for key, value in sorted(contract_map.items())},
        "databento_symbology_resolution_digest": digest(symbology_evidence),
        "histdata_xau_evidence": histdata_evidence,
        "shadow_pair": pair,
        "architecture": day41_architecture_manifest(),
        "paid_subscription_activated": False,
        "live_gc_subscription_activated": False,
        "live_gc_promoted": False,
        "broker_market_data_dependency": False,
        "api_key_recorded": False,
    }
    output = Path(args.output)
    output.write_text(canonical_json(evidence) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": True,
                "candidate_head_sha": head_sha,
                "target_historical_utc_day": start_date,
                "provider": pair["gc"]["provider"],
                "contract_symbol": pair["gc"]["contract_symbol"],
                "gc_observed_at_utc": pair["gc"]["observed_at_utc"],
                "xau_observed_at_utc": pair["xau"]["observed_at_utc"],
                "xau_source": pair["xau"]["source"],
                "historical_research_pair": pair["historical_research_pair"],
                "formal_forward_evidence_eligible": pair["formal_forward_evidence_eligible"],
                "timestamp_skew_seconds": pair["timestamp_skew_seconds"],
                "basis_usd": pair["basis_usd"],
                "quoted_cost_usd": str(quote.quoted_cost_usd),
                "paid_subscription_activated": False,
                "live_gc_promoted": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
