from __future__ import annotations

import json
import re
from datetime import datetime
from hashlib import sha256
from html.parser import HTMLParser

from .official_macro import OfficialMacroError, _eastern_wall_to_utc


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        value = " ".join(data.split())
        if value:
            self.parts.append(value)


def parse_fomc_calendar(text: str, *, year: int, month: int, source_url: str) -> list[dict[str, object]]:
    if len(text.encode("utf-8")) > 4_000_000:
        raise OfficialMacroError("fed_calendar_too_large")
    parser = _Text()
    parser.feed(text)
    flat = " ".join(parser.parts)
    patterns = (
        ("fomc_decision", "FOMC Meeting", 14, 0, r"2:00\s*p\.m\.\s*FOMC Meeting.*?Press Conference\s+(\d{1,2})(?:\s|$)"),
        ("fomc_press_conference", "FOMC Press Conference", 14, 30, r"2:30\s*p\.m\.\s*FOMC Press Conference\s+(\d{1,2})(?:\s|$)"),
    )
    output: list[dict[str, object]] = []
    for event_class, title, hour, minute, pattern in patterns:
        match = re.search(pattern, flat, re.IGNORECASE)
        if not match:
            continue
        day = int(match.group(1))
        scheduled = _eastern_wall_to_utc(datetime(year, month, day, hour, minute))
        logical = f"{year:04d}-{month:02d}"
        event_key = sha256(f"Federal Reserve\0{event_class}\0{logical}".encode()).hexdigest()
        raw = {"year": year, "month": month, "release_day": day, "title": title}
        raw_json = json.dumps(raw, sort_keys=True, separators=(",", ":"))
        structured = {
            "agency": "Federal Reserve",
            "event_class": event_class,
            "event_key": event_key,
            "phase": "scheduled",
            "scheduled_at": scheduled.isoformat(),
            "source_timezone": "America/New_York",
            "source_url": source_url,
        }
        output.append({
            "source": "federal_reserve_calendar",
            "external_id": f"fed_calendar:{event_class}:{logical}",
            "event_type": "macro_schedule",
            "published_at": None,
            "headline": title,
            "structured_data_json": json.dumps(structured, sort_keys=True, separators=(",", ":")),
            "raw_payload_json": raw_json,
            "payload_digest": sha256(raw_json.encode()).hexdigest(),
        })
    return output
