from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from .pit_reconstruction import select_latest_events_as_of

WINDOW_VERSION = "aidy_macro_event_window_v1"


def _utc(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
    elif isinstance(value, datetime):
        parsed = value
    else:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _structured(row: Mapping[str, Any]) -> dict[str, Any]:
    value = row.get("structured_data")
    if isinstance(value, Mapping):
        return dict(value)
    value = row.get("structured_data_json")
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return dict(parsed) if isinstance(parsed, dict) else {}
    return {}


def event_class_of(row: Mapping[str, Any]) -> str | None:
    structured = _structured(row)
    value = str(structured.get("event_class") or "").strip()
    if value:
        return value
    headline = str(row.get("headline") or "").lower()
    if "fomc statement" in headline or "fomc meeting" in headline:
        return "fomc_decision"
    if "fomc press conference" in headline:
        return "fomc_press_conference"
    return None


def reconstruct_macro_event_window(
    rows: Iterable[Mapping[str, Any]],
    *,
    as_of: datetime | str,
    center_at: datetime | str,
    event_class: str,
    minutes_before: int = 60,
    minutes_after: int = 180,
) -> dict[str, Any]:
    cutoff = _utc(as_of)
    center = _utc(center_at)
    if cutoff is None or center is None:
        raise ValueError("as_of and center_at must be timezone-aware timestamps.")
    if minutes_before < 0 or minutes_after < 0:
        raise ValueError("Event-window minutes must be non-negative.")
    if not event_class.strip():
        raise ValueError("event_class is required.")

    start = center - timedelta(minutes=minutes_before)
    end = center + timedelta(minutes=minutes_after)
    canonical = select_latest_events_as_of(rows, as_of=cutoff)
    observations: list[dict[str, Any]] = []

    for row in canonical:
        if event_class_of(row) != event_class:
            continue
        structured = _structured(row)
        scheduled = _utc(structured.get("scheduled_at"))
        published = _utc(row.get("published_at"))
        observed = _utc(row.get("first_observed_at"))
        candidate_times = [value for value in (scheduled, published, observed) if value is not None]
        if not any(start <= value <= end for value in candidate_times):
            continue
        observations.append(
            {
                "source": row.get("source"),
                "external_id": row.get("external_id"),
                "event_type": row.get("event_type"),
                "event_class": event_class,
                "phase": structured.get("phase"),
                "scheduled_at": scheduled.isoformat() if scheduled else None,
                "published_at": published.isoformat() if published else None,
                "first_observed_at": observed.isoformat() if observed else None,
                "revision_index": int(row.get("revision_index") or 0),
                "headline": row.get("headline"),
                "source_url": structured.get("source_url"),
                "evidence_id": row.get("evidence_id"),
                "archive_key": row.get("archive_key"),
                "payload_digest": row.get("payload_digest"),
            }
        )

    observations.sort(
        key=lambda item: (
            item["first_observed_at"] or "",
            str(item["source"] or ""),
            str(item["external_id"] or ""),
        )
    )
    return {
        "window_version": WINDOW_VERSION,
        "as_of_utc": cutoff.isoformat(),
        "event_class": event_class,
        "center_at_utc": center.isoformat(),
        "window_start_utc": start.isoformat(),
        "window_end_utc": end.isoformat(),
        "observations": observations,
    }
