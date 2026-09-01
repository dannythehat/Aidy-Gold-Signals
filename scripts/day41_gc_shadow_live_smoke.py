from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import httpx

from aidy.databento_gc import (
    DATABENTO_DATASET,
    GC_CONTINUOUS_SYMBOL,
    DatabentoHistoricalClient,
    HistoricalRequest,
)
from aidy.gc_shadow_spine import (
    canonical_json,
    day41_architecture_manifest,
    digest,
    normalize_databento_api_key,
    pair_shadow_observations,
    parse_databento_ohlcv_jsonl,
    resolve_gc_contract_map,
    xau_observation_from_gold_api,
)

LIVE_SMOKE_MAX_COST_USD = Decimal("0.25")
GOLD_API_URL = "https://api.gold-api.com/price/XAU"
DATABENTO_SYMBOLOGY_URL = "https://hist.databento.com/v0/symbology.resolve"


def _gold_api_payload() -> dict[str, object]:
    response = httpx.get(
        GOLD_API_URL,
        timeout=20.0,
        headers={"Accept": "application/json", "User-Agent": "AIDY-Signals/Day41"},
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise TypeError("Gold API returned a non-object payload.")
    return payload


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


def _available_ohlcv_window(dataset_range: dict[str, object]) -> tuple[datetime, datetime]:
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

    request_end = available_end.replace(second=0, microsecond=0)
    if request_end > available_end:
        request_end -= timedelta(minutes=1)
    day_start = request_end.replace(hour=0, minute=0, second=0, microsecond=0)
    request_start = max(request_end - timedelta(minutes=10), available_start, day_start)
    if request_start >= request_end:
        raise RuntimeError("Databento ohlcv-1m range is too short for the Day 41 smoke test.")
    return request_start, request_end


def _symbology_resolve(
    api_key: str,
    *,
    symbols: str,
    stype_in: str,
    stype_out: str,
    start_date: str,
) -> dict[str, object]:
    form = {
        "dataset": DATABENTO_DATASET,
        "symbols": symbols,
        "stype_in": stype_in,
        "stype_out": stype_out,
        "start_date": start_date,
    }
    response = httpx.post(
        DATABENTO_SYMBOLOGY_URL,
        auth=httpx.BasicAuth(api_key, ""),
        timeout=20.0,
        data=form,
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
    now = datetime.now(UTC)

    raw_path = Path(args.raw_gc)
    with DatabentoHistoricalClient.from_env() as client:
        entitlement = client.assert_gc_entitlement()
        dataset_range = client.dataset_range()
        request_start, request_end = _available_ohlcv_window(dataset_range)
        request = HistoricalRequest(
            schema="ohlcv-1m",
            start=request_start.isoformat(),
            end=request_end.isoformat(),
        )
        quote = client.estimate_cost(request)
        if quote.quoted_cost_usd > LIVE_SMOKE_MAX_COST_USD:
            raise RuntimeError(
                "Day 41 live smoke quote exceeds the stricter $0.25 acceptance cap."
            )
        receipt = client.download_jsonl(request, quote=quote, output_path=raw_path)

    start_date = request_start.date().isoformat()
    continuous_resolution = _symbology_resolve(
        api_key,
        symbols=GC_CONTINUOUS_SYMBOL,
        stype_in="continuous",
        stype_out="instrument_id",
        start_date=start_date,
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
        )
    contract_map = resolve_gc_contract_map(continuous_resolution, raw_resolutions)

    observations = parse_databento_ohlcv_jsonl(
        raw_path.read_text(encoding="utf-8"),
        contract_by_instrument_id=contract_map,
    )
    if not observations:
        raise RuntimeError("Databento returned no mapped GC minute observations.")
    gc = max(observations, key=lambda item: item.observed_at)

    xau_payload = _gold_api_payload()
    xau = xau_observation_from_gold_api(xau_payload)
    pair = pair_shadow_observations(gc, xau)
    if pair["paired"] is not True:
        raise RuntimeError(
            "Genuine Databento GC and Gold-API XAU observations exceeded the acceptance skew limit."
        )

    symbology_evidence = {
        "continuous": continuous_resolution,
        "raw": raw_resolutions,
    }
    evidence = {
        "evidence_version": "aidy_day41_genuine_shadow_evidence_v1",
        "candidate_head_sha": head_sha,
        "observed_at_utc": now.isoformat(),
        "genuine_databento_observation_ingested": True,
        "genuine_gold_api_observation_ingested": True,
        "databento_entitlement": entitlement,
        "databento_ohlcv_available_end_utc": request_end.isoformat(),
        "databento_request": request.payload(),
        "databento_quote_usd": str(quote.quoted_cost_usd),
        "databento_live_smoke_max_cost_usd": str(LIVE_SMOKE_MAX_COST_USD),
        "databento_download_receipt": receipt,
        "databento_contract_map": {str(key): value for key, value in sorted(contract_map.items())},
        "databento_symbology_resolution_digest": digest(symbology_evidence),
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
                "provider": pair["gc"]["provider"],
                "contract_symbol": pair["gc"]["contract_symbol"],
                "gc_observed_at_utc": pair["gc"]["observed_at_utc"],
                "xau_observed_at_utc": pair["xau"]["observed_at_utc"],
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
