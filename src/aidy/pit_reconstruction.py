from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any

from aidy.bigquery_exporter import MARKET_CANDLES, MARKET_EVENT_OBSERVATIONS, MARKET_SNAPSHOTS

QUERY_VERSION = "aidy_pit_asof_v1"
UNKNOWN = "unknown"
KNOWN = "known"


@dataclass(frozen=True, slots=True)
class PitQuery:
    kind: str
    sql: str

    @property
    def query_id(self) -> str:
        payload = f"{QUERY_VERSION}\0{self.kind}\0{self.sql}".encode()
        return sha256(payload).hexdigest()


def normalize_as_of(value: datetime | str) -> datetime:
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"Invalid as-of timestamp: {value}") from exc
    elif isinstance(value, datetime):
        parsed = value
    else:
        raise TypeError("as_of must be a timezone-aware datetime or ISO-8601 string.")
    if parsed.tzinfo is None:
        raise ValueError("as_of must be timezone-aware.")
    return parsed.astimezone(UTC)


def _known_at(row: Mapping[str, Any], field: str, as_of: datetime) -> bool:
    value = row.get(field)
    if value is None:
        return False
    observed = normalize_as_of(value) if isinstance(value, (str, datetime)) else None
    if observed is None:
        raise TypeError(f"{field} must be a timezone-aware datetime or ISO-8601 string.")
    return observed <= as_of


def _revision_sort_key(row: Mapping[str, Any], observed_field: str) -> tuple[Any, int, str]:
    observed = normalize_as_of(row[observed_field])
    revision = int(row.get("revision_index") or 0)
    identity = str(row.get("load_identity") or row.get("evidence_id") or "")
    return observed, revision, identity


def select_latest_revisions_as_of(
    rows: Iterable[Mapping[str, Any]],
    *,
    as_of: datetime | str,
    key_fields: Sequence[str],
    observed_field: str = "first_observed_at",
) -> list[dict[str, Any]]:
    cutoff = normalize_as_of(as_of)
    selected: dict[tuple[str, ...], Mapping[str, Any]] = {}
    for row in rows:
        if not _known_at(row, observed_field, cutoff):
            continue
        key = tuple(str(row.get(field) or "") for field in key_fields)
        current = selected.get(key)
        if current is None or _revision_sort_key(row, observed_field) > _revision_sort_key(
            current, observed_field
        ):
            selected[key] = row
    return [dict(selected[key]) for key in sorted(selected)]


def select_latest_candles_as_of(
    rows: Iterable[Mapping[str, Any]],
    *,
    as_of: datetime | str,
    symbol: str,
) -> list[dict[str, Any]]:
    if not symbol.strip():
        raise ValueError("symbol is required.")
    cutoff = normalize_as_of(as_of)
    canonical = select_latest_revisions_as_of(
        (
            row
            for row in rows
            if str(row.get("symbol") or "") == symbol
            and _known_at(row, "open_time_utc", cutoff)
        ),
        as_of=cutoff,
        key_fields=("source", "symbol", "timeframe", "open_time_utc"),
    )
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for row in canonical:
        key = (str(row.get("source") or ""), str(row.get("timeframe") or ""))
        current = latest.get(key)
        row_key = (
            normalize_as_of(row["open_time_utc"]),
            normalize_as_of(row["first_observed_at"]),
            int(row.get("revision_index") or 0),
            str(row.get("load_identity") or ""),
        )
        if current is None:
            latest[key] = row
            continue
        current_key = (
            normalize_as_of(current["open_time_utc"]),
            normalize_as_of(current["first_observed_at"]),
            int(current.get("revision_index") or 0),
            str(current.get("load_identity") or ""),
        )
        if row_key > current_key:
            latest[key] = row
    return [latest[key] for key in sorted(latest)]


def select_latest_events_as_of(
    rows: Iterable[Mapping[str, Any]],
    *,
    as_of: datetime | str,
) -> list[dict[str, Any]]:
    return select_latest_revisions_as_of(
        rows,
        as_of=as_of,
        key_fields=("source", "external_id"),
    )


def select_snapshot_as_of(
    rows: Iterable[Mapping[str, Any]],
    *,
    as_of: datetime | str,
    symbol: str,
) -> dict[str, Any] | None:
    cutoff = normalize_as_of(as_of)
    eligible = [
        dict(row)
        for row in rows
        if str(row.get("symbol") or "") == symbol and _known_at(row, "captured_at", cutoff)
    ]
    if not eligible:
        return None
    return max(
        eligible,
        key=lambda row: (
            normalize_as_of(row["captured_at"]),
            str(row.get("load_identity") or row.get("evidence_id") or ""),
        ),
    )


def _provenance(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "load_identity": row.get("load_identity"),
        "evidence_id": row.get("evidence_id"),
        "archive_key": row.get("archive_key"),
        "payload_digest": row.get("payload_digest"),
        "record_type": row.get("record_type"),
        "schema_version": row.get("schema_version"),
    }


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def reconstruction_bundle(
    *,
    as_of: datetime | str,
    symbol: str,
    candle_rows: Iterable[Mapping[str, Any]],
    event_rows: Iterable[Mapping[str, Any]],
    snapshot_rows: Iterable[Mapping[str, Any]],
    query_ids: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    cutoff = normalize_as_of(as_of)
    candles = select_latest_candles_as_of(candle_rows, as_of=cutoff, symbol=symbol)
    events = select_latest_events_as_of(event_rows, as_of=cutoff)
    snapshot = select_snapshot_as_of(snapshot_rows, as_of=cutoff, symbol=symbol)

    snapshot_payload: dict[str, Any]
    availability: Any
    if snapshot is None:
        snapshot_payload = {"state": UNKNOWN, "fact": None, "provenance": None}
        availability = {"state": UNKNOWN, "data": None}
    else:
        snapshot_payload = {
            "state": KNOWN,
            "fact": _json_safe(snapshot),
            "provenance": _provenance(snapshot),
        }
        availability = {
            "state": KNOWN,
            "data": _json_safe(snapshot.get("data_availability")),
            "snapshot_evidence_id": snapshot.get("evidence_id"),
        }

    return {
        "query_version": QUERY_VERSION,
        "as_of_utc": cutoff.isoformat(),
        "symbol": symbol,
        "retrospective_history_included": False,
        "query_ids": dict(query_ids or {}),
        "snapshot": snapshot_payload,
        "availability": availability,
        "candles": [
            {"state": KNOWN, "fact": _json_safe(row), "provenance": _provenance(row)}
            for row in candles
        ],
        "events": [
            {"state": KNOWN, "fact": _json_safe(row), "provenance": _provenance(row)}
            for row in events
        ],
    }


def candle_query(*, project: str, dataset: str) -> PitQuery:
    sql = f"""
WITH eligible AS (
  SELECT *, ROW_NUMBER() OVER (
    PARTITION BY source, symbol, timeframe, open_time_utc
    ORDER BY first_observed_at DESC, revision_index DESC, load_identity DESC
  ) AS revision_rank
  FROM `{project}.{dataset}.{MARKET_CANDLES.name}`
  WHERE symbol = @symbol
    AND open_time_utc <= @as_of
    AND first_observed_at <= @as_of
), canonical AS (
  SELECT * EXCEPT(revision_rank), ROW_NUMBER() OVER (
    PARTITION BY source, timeframe
    ORDER BY open_time_utc DESC, first_observed_at DESC, revision_index DESC, load_identity DESC
  ) AS latest_rank
  FROM eligible
  WHERE revision_rank = 1
)
SELECT * EXCEPT(latest_rank)
FROM canonical
WHERE latest_rank = 1
ORDER BY source, timeframe
""".strip()
    return PitQuery("candles", sql)


def event_query(*, project: str, dataset: str) -> PitQuery:
    sql = f"""
SELECT * EXCEPT(revision_rank)
FROM (
  SELECT *, ROW_NUMBER() OVER (
    PARTITION BY source, external_id
    ORDER BY first_observed_at DESC, revision_index DESC, load_identity DESC
  ) AS revision_rank
  FROM `{project}.{dataset}.{MARKET_EVENT_OBSERVATIONS.name}`
  WHERE first_observed_at <= @as_of
)
WHERE revision_rank = 1
ORDER BY first_observed_at, source, external_id
""".strip()
    return PitQuery("events", sql)


def snapshot_query(*, project: str, dataset: str) -> PitQuery:
    sql = f"""
SELECT *
FROM `{project}.{dataset}.{MARKET_SNAPSHOTS.name}`
WHERE symbol = @symbol AND captured_at <= @as_of
ORDER BY captured_at DESC, load_identity DESC
LIMIT 1
""".strip()
    return PitQuery("snapshot", sql)


def query_contract(*, project: str, dataset: str) -> dict[str, PitQuery]:
    if not project.strip() or not dataset.strip():
        raise ValueError("project and dataset are required.")
    return {
        "candles": candle_query(project=project, dataset=dataset),
        "events": event_query(project=project, dataset=dataset),
        "snapshot": snapshot_query(project=project, dataset=dataset),
    }


def contract_json(*, project: str, dataset: str) -> str:
    queries = query_contract(project=project, dataset=dataset)
    return json.dumps(
        {
            "query_version": QUERY_VERSION,
            "queries": {
                name: {"query_id": query.query_id, "sql": query.sql}
                for name, query in queries.items()
            },
            "retrospective_history_included": False,
        },
        sort_keys=True,
    )
