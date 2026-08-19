"""Free official-source US macro timing and release evidence for AIDY.

The module records observable facts only. It never infers market impact, surprises,
causes, forecasts or trading decisions. Scheduled observations and released
observations are distinct evidence. Unknown publication times stay unknown.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from hashlib import sha256
from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree

import httpx

from .market_sessions import new_york_utc_offset_hours

BLS_CALENDAR_URL = "https://www.bls.gov/schedule/news_release/bls.ics"
BLS_RSS_FEEDS = {
    "bls_employment_situation": "https://www.bls.gov/feed/empsit.rss",
    "bls_cpi": "https://www.bls.gov/feed/cpi.rss",
    "bls_ppi": "https://www.bls.gov/feed/ppi.rss",
    "bls_jolts": "https://www.bls.gov/feed/jolts.rss",
    "bls_eci": "https://www.bls.gov/feed/eci.rss",
}
BLS_FEED_EVENT_CLASS = {
    "bls_employment_situation": "employment_situation",
    "bls_cpi": "cpi",
    "bls_ppi": "ppi",
    "bls_jolts": "jolts",
    "bls_eci": "employment_cost_index",
}
BEA_SCHEDULE_URL = "https://www.bea.gov/news/schedule/full"
BEA_CURRENT_RELEASES_URL = "https://www.bea.gov/news/current-releases"
FED_CALENDAR_PREFIX = "https://www.federalreserve.gov/newsevents/"

_MAX_SOURCE_BYTES = 4_000_000
_FORBIDDEN_XML = re.compile(r"<!\s*(?:DOCTYPE|ENTITY)", re.IGNORECASE)
_SPACE = re.compile(r"\s+")
_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}
_MONTH_NAMES = tuple(_MONTHS)


class OfficialMacroError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class OfficialMacroCaptureResult:
    sources_checked: int
    sources_failed: int
    observations_seen: int
    observations_added: int
    sources_unchanged: int = 0


@dataclass(frozen=True, slots=True)
class FetchedSource:
    source_key: str
    url: str
    text: str | None


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value: object) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _normalize_text(value: str | None) -> str:
    return _SPACE.sub(" ", unescape(value or "")).strip()


def _parse_rss_timestamp(raw: str | None) -> datetime | None:
    value = _normalize_text(raw)
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        parsed = None
    if parsed is not None:
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(UTC)
    iso = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(iso)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _eastern_wall_to_utc(local_wall: datetime) -> datetime:
    """Convert an Eastern local wall time using AIDY's explicit DST rules."""

    if local_wall.tzinfo is not None:
        raise ValueError("Eastern wall time must be naive before conversion.")
    for offset in (-4, -5):
        candidate = (local_wall - timedelta(hours=offset)).replace(tzinfo=UTC)
        if new_york_utc_offset_hours(candidate) == offset:
            return candidate
    raise ValueError(f"Eastern local time is ambiguous or invalid: {local_wall.isoformat()}")


def _event_class_from_title(title: str) -> str | None:
    lowered = _normalize_text(title).lower()
    if "consumer price index" in lowered or re.search(r"\bcpi\b", lowered):
        return "cpi"
    if "producer price index" in lowered or re.search(r"\bppi\b", lowered):
        return "ppi"
    if "employment situation" in lowered:
        return "employment_situation"
    if "job openings and labor turnover" in lowered or "jolts" in lowered:
        return "jolts"
    if "employment cost index" in lowered:
        return "employment_cost_index"
    if "personal income and outlays" in lowered:
        return "personal_income_outlays_pce"
    if "gross domestic product" in lowered or re.search(r"\bgdp\b", lowered):
        return "gdp"
    if "international trade in goods and services" in lowered:
        return "international_trade"
    if "fomc meeting" in lowered or "fomc statement" in lowered:
        return "fomc_decision"
    if "fomc press conference" in lowered:
        return "fomc_press_conference"
    return None


def _event_key(*, agency: str, event_class: str, title: str) -> str:
    normalized = _normalize_text(title).lower()
    return sha256(f"{agency}\0{event_class}\0{normalized}".encode()).hexdigest()


def _observation(
    *,
    source: str,
    external_id: str,
    event_type: str,
    published_at: datetime | None,
    headline: str | None,
    structured: dict[str, object],
    raw: dict[str, object],
) -> dict[str, object]:
    raw_json = _canonical_json(raw)
    return {
        "source": source,
        "external_id": external_id,
        "event_type": event_type,
        "published_at": published_at,
        "headline": headline,
        "structured_data_json": _canonical_json(structured),
        "raw_payload_json": raw_json,
        "payload_digest": sha256(raw_json.encode()).hexdigest(),
    }


def _unfold_ics(text: str) -> list[str]:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    unfolded: list[str] = []
    for line in lines:
        if line.startswith((" ", "\t")) and unfolded:
            unfolded[-1] += line[1:]
        else:
            unfolded.append(line)
    return unfolded


def _ics_unescape(value: str) -> str:
    return (
        value.replace("\\n", " ")
        .replace("\\N", " ")
        .replace("\\,", ",")
        .replace("\\;", ";")
        .replace("\\\\", "\\")
    )


def _parse_ics_dtstart(raw_key: str, raw_value: str) -> datetime | None:
    value = raw_value.strip()
    if "VALUE=DATE" in raw_key.upper() or "T" not in value:
        return None
    try:
        local = datetime.strptime(value.rstrip("Z"), "%Y%m%dT%H%M%S")
    except ValueError:
        try:
            local = datetime.strptime(value.rstrip("Z"), "%Y%m%dT%H%M")
        except ValueError:
            return None
    if value.endswith("Z"):
        return local.replace(tzinfo=UTC)
    if "TZID=AMERICA/NEW_YORK" in raw_key.upper():
        return _eastern_wall_to_utc(local)
    return None


def parse_bls_calendar_ics(text: str) -> list[dict[str, object]]:
    if len(text.encode("utf-8")) > _MAX_SOURCE_BYTES:
        raise OfficialMacroError("bls_calendar_too_large")
    lines = _unfold_ics(text)
    events: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for line in lines:
        if line == "BEGIN:VEVENT":
            current = {}
            continue
        if line == "END:VEVENT":
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
        event_class = _event_class_from_title(summary)
        if event_class not in {
            "cpi",
            "ppi",
            "employment_situation",
            "jolts",
            "employment_cost_index",
        }:
            continue
        dt_pair = next(((key, value) for key, value in event.items() if key.startswith("DTSTART")), None)
        if dt_pair is None:
            continue
        scheduled_at = _parse_ics_dtstart(*dt_pair)
        if scheduled_at is None:
            continue
        uid = next((value for key, value in event.items() if key.startswith("UID")), "").strip()
        description = next(
            (value for key, value in event.items() if key.startswith("DESCRIPTION")), ""
        )
        url = next((value for key, value in event.items() if key.startswith("URL")), "")
        stable = uid or _digest({"summary": summary, "scheduled_date": scheduled_at.date().isoformat()})
        event_key = _event_key(agency="BLS", event_class=event_class, title=summary)
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
        observations.append(
            _observation(
                source="bls_calendar",
                external_id=f"bls_calendar:{stable}",
                event_type="macro_schedule",
                published_at=None,
                headline=summary,
                structured=structured,
                raw=raw,
            )
        )
    return observations


def _xml_local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _xml_first_text(element: ElementTree.Element, *names: str) -> str | None:
    wanted = set(names)
    for child in element.iter():
        if _xml_local_name(child.tag) in wanted and child.text and child.text.strip():
            return child.text.strip()
    return None


def _xml_link(element: ElementTree.Element) -> str | None:
    for child in element.iter():
        if _xml_local_name(child.tag) != "link":
            continue
        href = child.attrib.get("href")
        if href and href.strip():
            return href.strip()
        if child.text and child.text.strip():
            return child.text.strip()
    return None


def parse_bls_release_rss(text: str, *, feed_key: str) -> list[dict[str, object]]:
    if feed_key not in BLS_RSS_FEEDS:
        raise OfficialMacroError("bls_rss_feed_not_allowed")
    encoded = text.encode("utf-8")
    if len(encoded) > _MAX_SOURCE_BYTES:
        raise OfficialMacroError("bls_rss_feed_too_large")
    if _FORBIDDEN_XML.search(text):
        raise OfficialMacroError("bls_rss_doctype_not_allowed")
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError as exc:
        raise OfficialMacroError("bls_rss_invalid_xml") from exc

    event_class = BLS_FEED_EVENT_CLASS[feed_key]
    observations: list[dict[str, object]] = []
    for item in root.iter():
        if _xml_local_name(item.tag) not in {"item", "entry"}:
            continue
        title = _normalize_text(_xml_first_text(item, "title"))
        link = _xml_first_text(item, "link") or _xml_link(item)
        guid = _xml_first_text(item, "guid", "id") or link
        published_raw = _xml_first_text(item, "pubDate", "published", "updated")
        description = _normalize_text(_xml_first_text(item, "description", "summary", "content"))
        if not guid:
            guid = _digest({"feed_key": feed_key, "title": title, "published": published_raw})
        event_key = _event_key(agency="BLS", event_class=event_class, title=title)
        structured = {
            "agency": "BLS",
            "event_class": event_class,
            "event_key": event_key,
            "phase": "released",
            "source_url": link,
            "feed_key": feed_key,
        }
        raw = {
            "feed_key": feed_key,
            "guid": guid,
            "title": title,
            "link": link,
            "published": published_raw,
            "description": description or None,
        }
        observations.append(
            _observation(
                source="bls_rss",
                external_id=f"{feed_key}:{guid}",
                event_type="macro_release",
                published_at=_parse_rss_timestamp(published_raw),
                headline=title or None,
                structured=structured,
                raw=raw,
            )
        )
    return observations


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[dict[str, Any]]] = []
        self._row: list[dict[str, Any]] | None = None
        self._cell: dict[str, Any] | None = None
        self._depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = {"text": [], "links": []}
            self._depth = 1
        elif self._cell is not None:
            self._depth += 1
            if tag == "a":
                href = dict(attrs).get("href")
                if href:
                    self._cell["links"].append(href)

    def handle_endtag(self, tag: str) -> None:
        if self._cell is not None and tag in {"td", "th"} and self._depth == 1:
            self._cell["text"] = _normalize_text("".join(self._cell["text"]))
            assert self._row is not None
            self._row.append(self._cell)
            self._cell = None
            self._depth = 0
        elif self._cell is not None:
            self._depth = max(self._depth - 1, 1)
        if tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell["text"].append(data)


_BEA_DATE_RE = re.compile(
    r"^(January|February|March|April|May|June|July|August|September|October|November|December)\s+"
    r"(\d{1,2})\s+(\d{1,2}:\d{2})\s+(AM|PM)$",
    re.IGNORECASE,
)
_BEA_PUBLISHED_RE = re.compile(
    r"^(January|February|March|April|May|June|July|August|September|October|November|December)\s+"
    r"(\d{1,2}),\s*(\d{4})$",
    re.IGNORECASE,
)


def parse_bea_schedule_html(text: str, *, year: int) -> list[dict[str, object]]:
    if len(text.encode("utf-8")) > _MAX_SOURCE_BYTES:
        raise OfficialMacroError("bea_schedule_too_large")
    parser = _TableParser()
    parser.feed(text)
    observations: list[dict[str, object]] = []
    for row in parser.rows:
        texts = [str(cell["text"]) for cell in row]
        date_cell = next((value for value in texts if _BEA_DATE_RE.match(value)), None)
        if date_cell is None:
            continue
        match = _BEA_DATE_RE.match(date_cell)
        assert match is not None
        title_candidates = [
            value
            for value in texts
            if value != date_cell and value.lower() not in {"news", "data", "article", "visual data", "n", "d", "a", "v"}
        ]
        title = max(title_candidates, key=len, default="")
        event_class = _event_class_from_title(title)
        if event_class not in {"gdp", "personal_income_outlays_pce", "international_trade"}:
            continue
        month = _MONTHS[match.group(1).lower()]
        day = int(match.group(2))
        hour, minute = (int(part) for part in match.group(3).split(":"))
        if match.group(4).upper() == "PM" and hour != 12:
            hour += 12
        if match.group(4).upper() == "AM" and hour == 12:
            hour = 0
        scheduled_at = _eastern_wall_to_utc(datetime(year, month, day, hour, minute))
        links = [link for cell in row for link in cell["links"]]
        release_url = next((urljoin(BEA_SCHEDULE_URL, link) for link in links if link), None)
        event_key = _event_key(agency="BEA", event_class=event_class, title=title)
        structured = {
            "agency": "BEA",
            "event_class": event_class,
            "event_key": event_key,
            "phase": "scheduled",
            "scheduled_at": scheduled_at.isoformat(),
            "source_timezone": "America/New_York",
            "source_url": release_url or BEA_SCHEDULE_URL,
        }
        stable = _digest({"event_class": event_class, "title": _normalize_text(title).lower()})
        observations.append(
            _observation(
                source="bea_schedule",
                external_id=f"bea_schedule:{stable}",
                event_type="macro_schedule",
                published_at=None,
                headline=title,
                structured=structured,
                raw={"date_cell": date_cell, "title": title, "release_url": release_url},
            )
        )
    return observations


def parse_bea_current_releases_html(text: str) -> list[dict[str, object]]:
    if len(text.encode("utf-8")) > _MAX_SOURCE_BYTES:
        raise OfficialMacroError("bea_current_releases_too_large")
    parser = _TableParser()
    parser.feed(text)
    observations: list[dict[str, object]] = []
    for row in parser.rows:
        texts = [str(cell["text"]) for cell in row]
        title = next((value for value in texts if _event_class_from_title(value)), "")
        event_class = _event_class_from_title(title)
        if event_class not in {"gdp", "personal_income_outlays_pce", "international_trade"}:
            continue
        published_text = next((value for value in texts if _BEA_PUBLISHED_RE.match(value)), None)
        links = [link for cell in row for link in cell["links"]]
        release_url = next((urljoin(BEA_CURRENT_RELEASES_URL, link) for link in links if link), None)
        stable_seed = release_url or f"{title}|{published_text or ''}"
        event_key = _event_key(agency="BEA", event_class=event_class, title=title)
        structured = {
            "agency": "BEA",
            "event_class": event_class,
            "event_key": event_key,
            "phase": "released",
            "published_date": published_text,
            "published_at_precision": "unknown_time",
            "source_url": release_url or BEA_CURRENT_RELEASES_URL,
        }
        observations.append(
            _observation(
                source="bea_releases",
                external_id=f"bea_release:{sha256(stable_seed.encode()).hexdigest()}",
                event_type="macro_release",
                published_at=None,
                headline=title,
                structured=structured,
                raw={"title": title, "published_date": published_text, "release_url": release_url},
            )
        )
    return observations


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        value = _normalize_text(data)
        if value:
            self.parts.append(value)


def fed_month_calendar_url(*, year: int, month: int) -> str:
    name = _MONTH_NAMES[month - 1]
    return f"{FED_CALENDAR_PREFIX}{year}-{name}.htm"


def parse_fed_month_calendar_html(
    text: str,
    *,
    year: int,
    month: int,
    source_url: str,
) -> list[dict[str, object]]:
    if len(text.encode("utf-8")) > _MAX_SOURCE_BYTES:
        raise OfficialMacroError("fed_calendar_too_large")
    parser = _TextParser()
    parser.feed(text)
    flattened = _normalize_text(" ".join(parser.parts))
    observations: list[dict[str, object]] = []
    patterns = (
        ("fomc_decision", r"2:00\s*p\.m\.\s*FOMC Meeting.*?(\d{1,2})(?:\s|$)"),
        ("fomc_press_conference", r"2:30\s*p\.m\.\s*FOMC Press Conference\s+(\d{1,2})(?:\s|$)"),
    )
    for event_class, pattern in patterns:
        match = re.search(pattern, flattened, re.IGNORECASE)
        if not match:
            continue
        day = int(match.group(1))
        hour = 14
        minute = 0 if event_class == "fomc_decision" else 30
        scheduled_at = _eastern_wall_to_utc(datetime(year, month, day, hour, minute))
        title = "FOMC Meeting" if event_class == "fomc_decision" else "FOMC Press Conference"
        event_key = _event_key(agency="Federal Reserve", event_class=event_class, title=f"{title} {year}-{month:02d}-{day:02d}")
        structured = {
            "agency": "Federal Reserve",
            "event_class": event_class,
            "event_key": event_key,
            "phase": "scheduled",
            "scheduled_at": scheduled_at.isoformat(),
            "source_timezone": "America/New_York",
            "source_url": source_url,
        }
        external_id = f"fed_calendar:{event_class}:{year:04d}-{month:02d}-{day:02d}"
        observations.append(
            _observation(
                source="federal_reserve_calendar",
                external_id=external_id,
                event_type="macro_schedule",
                published_at=None,
                headline=title,
                structured=structured,
                raw={"year": year, "month": month, "day": day, "title": title},
            )
        )
    return observations


def _valid_source(source_key: str, url: str) -> bool:
    if source_key == "bls_calendar":
        return url == BLS_CALENDAR_URL
    if source_key in BLS_RSS_FEEDS:
        return url == BLS_RSS_FEEDS[source_key]
    if source_key == "bea_schedule":
        return url == BEA_SCHEDULE_URL
    if source_key == "bea_releases":
        return url == BEA_CURRENT_RELEASES_URL
    if source_key.startswith("fed_calendar_"):
        parsed = urlparse(url)
        return (
            parsed.scheme == "https"
            and parsed.netloc == "www.federalreserve.gov"
            and re.fullmatch(r"/newsevents/\d{4}-(?:" + "|".join(_MONTH_NAMES) + r")\.htm", parsed.path)
            is not None
            and not parsed.query
            and not parsed.fragment
        )
    return False


class OfficialMacroGateway:
    def __init__(
        self,
        *,
        timeout_seconds: float = 20.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._timeout = httpx.Timeout(timeout_seconds)
        self._transport = transport
        self._validators: dict[str, tuple[str | None, str | None]] = {}

    async def fetch(self, *, source_key: str, url: str) -> FetchedSource:
        if not _valid_source(source_key, url):
            raise OfficialMacroError("official_macro_source_not_allowed")
        headers = {
            "Accept": "text/html, text/calendar, application/rss+xml, application/xml, text/xml",
            "User-Agent": "AIDY-Gold-Macro-Recorder/1.0",
        }
        etag, last_modified = self._validators.get(source_key, (None, None))
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                follow_redirects=False,
                transport=self._transport,
            ) as client:
                async with client.stream("GET", url, headers=headers) as response:
                    if response.status_code == 304:
                        return FetchedSource(source_key, url, None)
                    if response.status_code != 200:
                        raise OfficialMacroError(f"official_macro_http_{response.status_code}")
                    declared = response.headers.get("content-length", "").strip()
                    if declared.isdigit() and int(declared) > _MAX_SOURCE_BYTES:
                        raise OfficialMacroError("official_macro_source_too_large")
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > _MAX_SOURCE_BYTES:
                            raise OfficialMacroError("official_macro_source_too_large")
                    encoding = response.encoding or "utf-8"
                    validators = (
                        response.headers.get("etag"),
                        response.headers.get("last-modified"),
                    )
        except httpx.TimeoutException as exc:
            raise OfficialMacroError("official_macro_timeout") from exc
        except httpx.HTTPError as exc:
            raise OfficialMacroError("official_macro_unreachable") from exc
        try:
            text = bytes(body).decode(encoding)
        except (LookupError, UnicodeDecodeError) as exc:
            raise OfficialMacroError("official_macro_undecodable") from exc
        self._validators[source_key] = validators
        return FetchedSource(source_key, url, text)


def upcoming_fed_calendar_sources(now: datetime, *, months: int = 4) -> list[tuple[str, str, int, int]]:
    if now.tzinfo is None:
        raise ValueError("Fed calendar source time must be timezone-aware.")
    cursor_year = now.astimezone(UTC).year
    cursor_month = now.astimezone(UTC).month
    result: list[tuple[str, str, int, int]] = []
    for _ in range(max(1, months)):
        url = fed_month_calendar_url(year=cursor_year, month=cursor_month)
        result.append((f"fed_calendar_{cursor_year}_{cursor_month:02d}", url, cursor_year, cursor_month))
        cursor_month += 1
        if cursor_month == 13:
            cursor_month = 1
            cursor_year += 1
    return result
