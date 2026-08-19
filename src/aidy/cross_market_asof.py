from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime
from typing import Any

from .cross_market import ENABLED_SERIES

CROSS_MARKET_QUERY_VERSION = "aidy_cross_market_asof_v1"


def _utc(value: datetime | str) -> datetime:
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value)
    else:
        parsed = value
    if parsed.tzinfo is None:
        raise ValueError("Cross-market as-of timestamp must be timezone-aware.")
    return parsed.astimezone(UTC)


def _date(value: date | datetime | str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(value[:10])


def reconstruct_cross_market_as_of(
    rows: Iterable[Mapping[str, Any]],
    *,
    as_of: datetime | str,
) -> dict[str, Any]:
    cutoff = _utc(as_of)
    canonical: dict[tuple[str, str, date], Mapping[str, Any]] = {}

    for row in rows:
        series_id = str(row.get("series_id") or "")
        if series_id not in ENABLED_SERIES:
            continue
        first_seen_raw = row.get("first_observed_at")
        if not isinstance(first_seen_raw, (datetime, str)):
            continue
        first_seen = _utc(first_seen_raw)
        observation_date = _date(row.get("observation_date"))
        if first_seen > cutoff or observation_date > cutoff.date():
            continue
        key = (str(row.get("source") or ""), series_id, observation_date)
        current = canonical.get(key)
        sort_key = (
            first_seen,
            int(row.get("revision_index") or 0),
            str(row.get("load_identity") or row.get("evidence_id") or ""),
        )
        if current is None:
            canonical[key] = row
            continue
        current_key = (
            _utc(current["first_observed_at"]),
            int(current.get("revision_index") or 0),
            str(current.get("load_identity") or current.get("evidence_id") or ""),
        )
        if sort_key > current_key:
            canonical[key] = row

    latest_by_series: dict[str, Mapping[str, Any]] = {}
    for (_, series_id, observation_date), row in canonical.items():
        current = latest_by_series.get(series_id)
        if current is None or observation_date > _date(current["observation_date"]):
            latest_by_series[series_id] = row

    output: dict[str, Any] = {}
    for series_id in ENABLED_SERIES:
        row = latest_by_series.get(series_id)
        if row is None:
            output[series_id] = {"state": "unknown", "fact": None, "provenance": None}
            continue
        observation_date = _date(row["observation_date"])
        output[series_id] = {
            "state": "known",
            "observation_age_days": (cutoff.date() - observation_date).days,
            "fact": {
                "source": row.get("source"),
                "series_id": series_id,
                "observation_date": observation_date.isoformat(),
                "value": str(row.get("value")),
                "unit": row.get("unit"),
                "first_observed_at": _utc(row["first_observed_at"]).isoformat(),
                "revision_index": int(row.get("revision_index") or 0),
                "source_url": row.get("source_url"),
            },
            "provenance": {
                "load_identity": row.get("load_identity"),
                "evidence_id": row.get("evidence_id"),
                "archive_key": row.get("archive_key"),
                "payload_digest": row.get("payload_digest"),
                "source_document_digest": row.get("source_document_digest"),
            },
        }

    return {
        "query_version": CROSS_MARKET_QUERY_VERSION,
        "as_of_utc": cutoff.isoformat(),
        "frequency": "daily_context",
        "series": output,
    }


def bigquery_cross_market_sql(*, project: str, dataset: str) -> str:
    if not project.strip() or not dataset.strip():
        raise ValueError("project and dataset are required.")
    return f"""
WITH eligible AS (
  SELECT *, ROW_NUMBER() OVER (
    PARTITION BY source, series_id, observation_date
    ORDER BY first_observed_at DESC, revision_index DESC, load_identity DESC
  ) AS revision_rank
  FROM `{project}.{dataset}.market_cross_market_observations`
  WHERE first_observed_at <= @as_of
    AND observation_date <= DATE(@as_of)
), canonical AS (
  SELECT * EXCEPT(revision_rank), ROW_NUMBER() OVER (
    PARTITION BY series_id
    ORDER BY observation_date DESC, first_observed_at DESC, revision_index DESC, load_identity DESC
  ) AS latest_rank
  FROM eligible
  WHERE revision_rank = 1
)
SELECT * EXCEPT(latest_rank)
FROM canonical
WHERE latest_rank = 1
ORDER BY series_id
""".strip()
