from __future__ import annotations

import json
import os
import time
from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import day28_macro_vintage_acceptance as acceptance
import httpx

from aidy.macro_vintages import SERIES_T10YIE, AlfredSnapshot

_FRED_OBSERVATIONS_URL = "https://api.stlouisfed.org/fred/series/observations"
_RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}
_MAX_ATTEMPTS = 6
_REQUEST_SPACING_SECONDS = 0.6


def _sanitized_source_url(*, series_id: str, vintage: date) -> str:
    params = {
        "series_id": series_id,
        "file_type": "json",
        "realtime_start": vintage.isoformat(),
        "realtime_end": vintage.isoformat(),
        "observation_start": acceptance.OBSERVATION_START.isoformat(),
        "observation_end": acceptance.OBSERVATION_END.isoformat(),
        "output_type": "1",
    }
    return f"{_FRED_OBSERVATIONS_URL}?{urlencode(params)}"


def _parse_fred_snapshot(
    raw: bytes,
    *,
    series_id: str,
    vintage: date,
) -> AlfredSnapshot:
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("Day 28 FRED API returned invalid JSON.") from exc

    if not isinstance(payload, dict):
        raise TypeError("Day 28 FRED API response is not an object.")
    vintage_text = vintage.isoformat()
    if payload.get("realtime_start") != vintage_text or payload.get("realtime_end") != vintage_text:
        raise RuntimeError("Day 28 FRED API response real-time period does not match requested vintage.")

    observations = payload.get("observations")
    if not isinstance(observations, list):
        raise TypeError("Day 28 FRED API response has no observations list.")

    values: list[tuple[date, str | None]] = []
    for item in observations:
        if not isinstance(item, dict):
            raise TypeError("Day 28 FRED API observation is not an object.")
        try:
            observation_date = date.fromisoformat(str(item["date"]))
        except (KeyError, ValueError) as exc:
            raise RuntimeError("Day 28 FRED API observation has an invalid date.") from exc
        if not acceptance.OBSERVATION_START <= observation_date <= acceptance.OBSERVATION_END:
            continue
        raw_value = str(item.get("value", ".")).strip()
        value = None if raw_value in {"", "."} else raw_value
        values.append((observation_date, value))

    values.sort(key=lambda item: item[0])
    return AlfredSnapshot(
        series_id=series_id,
        vintage_date=vintage,
        observation_start=acceptance.OBSERVATION_START,
        observation_end=acceptance.OBSERVATION_END,
        values=tuple(values),
        source_url=_sanitized_source_url(series_id=series_id, vintage=vintage),
        source_sha256=sha256(raw).hexdigest(),
    )


def _load_snapshots_v2(cache_dir: Path) -> list[AlfredSnapshot]:
    """Capture PIT snapshots through the authenticated official FRED API."""

    api_key = os.environ.get("FRED_API_KEY", "").strip()
    if len(api_key) != 32 or not api_key.isalnum() or api_key.lower() != api_key:
        raise RuntimeError("Day 28 FRED_API_KEY is missing or malformed.")

    cache_dir = cache_dir / "fred_api"
    cache_dir.mkdir(parents=True, exist_ok=True)
    vintages = acceptance._date_range(acceptance.VINTAGE_START, acceptance.VINTAGE_END)
    snapshots: list[AlfredSnapshot] = []
    total = len(acceptance.SERIES) * len(vintages)
    completed = 0

    timeout = httpx.Timeout(connect=30.0, read=60.0, write=30.0, pool=30.0)
    with httpx.Client(
        timeout=timeout,
        follow_redirects=False,
        headers={"User-Agent": "AIDY-Gold-Day28-PIT-FRED-API-Acceptance/1.0"},
    ) as client:
        for series_id in acceptance.SERIES:
            series_dir = cache_dir / series_id
            series_dir.mkdir(parents=True, exist_ok=True)
            for vintage in vintages:
                path = series_dir / f"{vintage.isoformat()}.json"
                snapshot: AlfredSnapshot | None = None

                if path.exists() and path.stat().st_size > 0:
                    try:
                        snapshot = _parse_fred_snapshot(
                            path.read_bytes(), series_id=series_id, vintage=vintage
                        )
                    except (OSError, RuntimeError, TypeError):
                        print(
                            f"DAY28 FRED invalid-cache {series_id} {vintage}; refetching",
                            flush=True,
                        )
                        path.unlink(missing_ok=True)

                if snapshot is None:
                    params = {
                        "series_id": series_id,
                        "api_key": api_key,
                        "file_type": "json",
                        "realtime_start": vintage.isoformat(),
                        "realtime_end": vintage.isoformat(),
                        "observation_start": acceptance.OBSERVATION_START.isoformat(),
                        "observation_end": acceptance.OBSERVATION_END.isoformat(),
                        "output_type": "1",
                    }
                    last_error: Exception | None = None
                    for attempt in range(1, _MAX_ATTEMPTS + 1):
                        try:
                            response = client.get(_FRED_OBSERVATIONS_URL, params=params)
                            if response.status_code == 200:
                                raw = response.content
                                snapshot = _parse_fred_snapshot(
                                    raw, series_id=series_id, vintage=vintage
                                )
                                temp_path = path.with_suffix(".json.tmp")
                                temp_path.write_bytes(raw)
                                temp_path.replace(path)
                                time.sleep(_REQUEST_SPACING_SECONDS)
                                break
                            if response.status_code not in _RETRYABLE_STATUS:
                                raise RuntimeError(
                                    "Day 28 FRED API request failed "
                                    f"{series_id} {vintage}: HTTP {response.status_code}"
                                )
                            last_error = RuntimeError(f"HTTP {response.status_code}")
                        except (httpx.TimeoutException, httpx.NetworkError) as exc:
                            last_error = exc

                        if attempt < _MAX_ATTEMPTS:
                            delay = min(30, 2 ** (attempt - 1))
                            print(
                                f"DAY28 FRED retry {series_id} {vintage} "
                                f"attempt={attempt + 1}/{_MAX_ATTEMPTS} after={delay}s",
                                flush=True,
                            )
                            time.sleep(delay)

                    if snapshot is None:
                        raise RuntimeError(
                            f"Day 28 FRED API exhausted retries {series_id} {vintage}"
                        ) from last_error

                snapshots.append(snapshot)
                completed += 1
                if completed == 1 or completed % 20 == 0 or completed == total:
                    print(f"DAY28 FRED snapshots={completed}/{total}", flush=True)

    if len(snapshots) != acceptance.EXPECTED_SNAPSHOT_COUNT:
        raise RuntimeError(
            f"Day 28 expected {acceptance.EXPECTED_SNAPSHOT_COUNT} frozen snapshots, "
            f"found {len(snapshots)}."
        )
    return snapshots


def _utc(value: datetime | str) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError("Day 28 acceptance timestamps must be timezone-aware.")
    return parsed.astimezone(UTC)


def _canonical_decimal(value: Decimal) -> str:
    text = format(value, "f").rstrip("0").rstrip(".")
    return text or "0"


def _same_observation_reference(
    records: list[dict[str, Any]],
    *,
    observation_date: str,
    as_of: datetime | str,
) -> dict[str, Any] | None:
    cutoff = _utc(as_of)
    eligible: list[dict[str, Any]] = []
    for record in records:
        if record.get("series_id") != SERIES_T10YIE:
            continue
        if record.get("observation_date") != observation_date:
            continue
        if not acceptance.verify_version_record(record):
            continue
        if _utc(str(record["pit_available_after_utc"])) > cutoff:
            continue
        if record.get("value") is None:
            continue
        eligible.append(record)
    if not eligible:
        return None
    return max(
        eligible,
        key=lambda item: (
            _utc(str(item["pit_available_after_utc"])),
            int(item["revision_index"]),
            str(item["version_identity"]),
        ),
    )


_ORIGINAL_BUILD_RATES_STATE = acceptance.build_rates_macro_state


def _build_rates_macro_state_with_aligned_reference(
    records: Any,
    *,
    as_of: datetime | str,
) -> dict[str, Any]:
    materialized = list(records)
    state = _ORIGINAL_BUILD_RATES_STATE(materialized, as_of=as_of)
    derived = state["derived"]["breakeven_10y"]
    if derived.get("state") == "known" and derived.get("observation_date"):
        reference = _same_observation_reference(
            materialized,
            observation_date=str(derived["observation_date"]),
            as_of=as_of,
        )
        if reference is not None:
            delta = Decimal(str(derived["value"])) - Decimal(str(reference["value"]))
            if delta != 0:
                raise RuntimeError(
                    "Day 28 same-date T10YIE validation mismatch: "
                    f"derived={derived['value']} official={reference['value']} "
                    f"observation_date={derived['observation_date']}"
                )
            official = state["official_breakeven_reference"]
            official["state"] = "known"
            official["observation_date"] = reference["observation_date"]
            official["reference_value"] = reference["value"]
            official["reference_version_identity"] = reference["version_identity"]
            official["derived_minus_official"] = _canonical_decimal(delta)
            body = dict(state)
            body.pop("state_digest", None)
            state["state_digest"] = acceptance.digest(body)
    return state


def _persist_with_fred_metadata(*args: Any, **kwargs: Any) -> int:
    rows = kwargs.get("rows")
    table_id = str(kwargs.get("table_id", ""))
    if (
        table_id.endswith(f".{acceptance.SUMMARY_TABLE}")
        and isinstance(rows, list)
        and rows
    ):
        row = rows[0]
        summary = row.get("summary_json") if isinstance(row, dict) else None
        if isinstance(summary, dict):
            summary["source"] = "FRED_API"
            summary["source_auth_required"] = True
            summary["source_endpoint"] = "fred/series/observations"
            summary["source_transport"] = "authenticated_official_api"
            summary["official_breakeven_validation_method"] = (
                "same_observation_date_pit_valid_t10yie_exact_match"
            )
            summary.pop("summary_digest", None)
            summary["summary_digest"] = acceptance.digest(summary)
            row["summary_digest"] = summary["summary_digest"]
    return _ORIGINAL_PERSIST(*args, **kwargs)


_ORIGINAL_PERSIST = acceptance._persist_experiment_rows


def main() -> int:
    acceptance._ALLOWED_CHANGED_FILES.add("scripts/day28_macro_vintage_acceptance_v2.py")
    acceptance._load_snapshots = _load_snapshots_v2
    acceptance.build_rates_macro_state = _build_rates_macro_state_with_aligned_reference
    acceptance._persist_experiment_rows = _persist_with_fred_metadata
    return acceptance.main()


if __name__ == "__main__":
    raise SystemExit(main())
