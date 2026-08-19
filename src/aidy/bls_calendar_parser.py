from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256

from .official_macro import (
    BLS_CALENDAR_URL,
    OfficialMacroError,
    _digest,
    _eastern_wall_to_utc,
    _ics_unescape,
    _normalize_text,
    _unfold_ics,
)

_ACCEPTED_CLASSES = {
    "cpi",
    "ppi",
    "employment_situation",
    "jolts",
    "employment_cost_index",
}


def _event_class(title: str) -> str | None:
    lowered = _normalize_text(title).lower()
    if "consumer price index" in lowered:
        return "cpi"
    if "producer price index" in lowered:
        return "ppi"
    if "employment situation" in lowered:
        return "employment_situation"
    if "job openings and labor turnover" in lowered or "jolts" in lowered:
        return "jolts"
    if (
        "employment cost index" in lowered
        or "employer costs for employee compensation" in lowered
    ):
        return "employment_cost_index"
    return None


def _dtstart_to_utc(raw_key: str, raw_value: str) -> datetime | None:
    value = raw_value.strip()
    if "VALUE=DATE" in raw_key.upper() or "T" not in value:
        return None
    formats = ("%Y%m%dT%H%M%S", "%Y%m%dT%H%M")
    local: datetime | None = None
    for fmt in formats:
        try:
            local = datetime.strptime(value.rstrip("Z"), fmt)  # noqa: DTZ007
            break
        except ValueError:
            continue
    if local is None:
        return None
    if value.endswith("Z"):
        return local.replace(tzinfo=UTC)
    # BLS explicitly defines its release-calendar clock as Eastern Time. The
    # live ICS may omit TZID, so a plain DTSTART is still an Eastern wall time.
    if "TZID=" in raw_key.upper() and "AMERICA/NEW_YORK" not in raw_key.upper():
        return None
    return _eastern_wall_to_utc(local)


def parse_bls_official_calendar(text: str) -> list[dict[str, object]]:
    if len(text.encode("utf-8")) > 4_000_000:
        raise OfficialMacroError("bls_calendar_too_large")
    if "BEGIN:VEVENT" not in text:
        preview = " ".join(text[:600].split())
        raise OfficialMacroError(f"bls_calendar_no_vevent:{preview}")

    events: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for line in _unfold_ics(text):
        marker = line.strip()
        if marker == "BEGIN:VEVENT":
            current = {}
            continue
        if marker == "END:VEVENT":
            if current is not None:
                events.append(current)
            current = None
            continue
        if current is None or ":" not in line:
            continue
        key, value = line.split(":", 1)
        current[key] = _ics_unescape(value)

    observations: list[dict[str, object]] = []
    for event in events:
        summary = next((value for key, value in event.items() if key.startswith("SUMMARY")), "")
        event_class = _event_class(summary)
        if event_class not in _ACCEPTED_CLASSES:
            continue
        dt_pair = next(
            ((key, value) for key, value in event.items() if key.startswith("DTSTART")),
            None,
        )
        if dt_pair is None:
            continue
        scheduled_at = _dtstart_to_utc(*dt_pair)
        if scheduled_at is None:
            continue
        uid = next((value for key, value in event.items() if key.startswith("UID")), "").strip()
        description = next(
            (value for key, value in event.items() if key.startswith("DESCRIPTION")), ""
        )
        url = next((value for key, value in event.items() if key.startswith("URL")), "")
        stable = uid or _digest(
            {"summary": summary, "scheduled_date": scheduled_at.date().isoformat()}
        )
        event_key = sha256(
            f"BLS\0{event_class}\0{_normalize_text(summary).lower()}".encode()
        ).hexdigest()
        structured = {
            "agency": "BLS",
            "event_class": event_class,
            "event_key": event_key,
            "phase": "scheduled",
            "scheduled_at": scheduled_at.isoformat(),
            "source_timezone": "America/New_York",
            "source_url": url or BLS_CALENDAR_URL,
        }
        raw = {
            "uid": uid or None,
            "summary": summary,
            "description": description or None,
            "url": url or None,
            "dtstart_key": dt_pair[0],
            "dtstart_value": dt_pair[1],
        }
        raw_json = json.dumps(raw, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        observations.append(
            {
                "source": "bls_calendar",
                "external_id": f"bls_calendar:{stable}",
                "event_type": "macro_schedule",
                "published_at": None,
                "headline": summary,
                "structured_data_json": json.dumps(
                    structured, sort_keys=True, separators=(",", ":"), ensure_ascii=False
                ),
                "raw_payload_json": raw_json,
                "payload_digest": sha256(raw_json.encode()).hexdigest(),
            }
        )

    if events and not observations:
        samples: list[dict[str, object]] = []
        for event in events[:5]:
            summaries = [
                [key, value] for key, value in event.items() if key.upper().startswith("SUMMARY")
            ]
            starts = [
                [key, value] for key, value in event.items() if key.upper().startswith("DTSTART")
            ]
            samples.append({"summary": summaries, "dtstart": starts})
        raise OfficialMacroError(
            "bls_calendar_no_supported_events:"
            + json.dumps(samples, sort_keys=True, separators=(",", ":"))
        )
    return observations
