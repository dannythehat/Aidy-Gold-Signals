from __future__ import annotations

import calendar
from datetime import date, datetime
from html.parser import HTMLParser
import re

FED_H10_CURRENT_URL = "https://www.federalreserve.gov/releases/h10/current/default.htm"

_SPACE = re.compile(r"\s+")
_RELEASE_DATE = re.compile(
    r"Release Date:\s*([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})",
    re.IGNORECASE,
)
_DATE_LABEL = re.compile(r"([A-Za-z]{3,9})\.?\s+(\d{1,2})$")


class H10ParseError(RuntimeError):
    pass


class _H10TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self.text_parts: list[str] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        del attrs
        lowered = tag.lower()
        if lowered == "tr":
            self._row = []
        elif lowered in {"td", "th"} and self._row is not None:
            self._cell = []

    def handle_data(self, data: str) -> None:
        value = _SPACE.sub(" ", data).strip()
        if not value:
            return
        self.text_parts.append(value)
        if self._cell is not None:
            self._cell.append(value)

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered in {"td", "th"} and self._cell is not None and self._row is not None:
            self._row.append(_SPACE.sub(" ", " ".join(self._cell)).strip())
            self._cell = None
        elif lowered == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None
            self._cell = None


def _release_date(flat_text: str) -> date:
    match = _RELEASE_DATE.search(flat_text)
    if match is None:
        raise H10ParseError("fed_h10_release_date_missing")
    month_name, day_raw, year_raw = match.groups()
    try:
        month = datetime.strptime(month_name[:3], "%b").month  # noqa: DTZ007
    except ValueError as exc:
        raise H10ParseError("fed_h10_release_month_invalid") from exc
    return date(int(year_raw), month, int(day_raw))


def _observation_date(label: str, *, released: date) -> date:
    match = _DATE_LABEL.fullmatch(_SPACE.sub(" ", label).strip())
    if match is None:
        raise H10ParseError(f"fed_h10_date_label_invalid:{label}")
    month_name, day_raw = match.groups()
    normalized = month_name[:3].title()
    month_map = {name: index for index, name in enumerate(calendar.month_abbr) if name}
    if normalized not in month_map:
        raise H10ParseError(f"fed_h10_month_invalid:{month_name}")
    candidate = date(released.year, month_map[normalized], int(day_raw))
    if candidate > released:
        candidate = date(released.year - 1, candidate.month, candidate.day)
    if (released - candidate).days > 14:
        raise H10ParseError("fed_h10_observation_too_far_from_release")
    return candidate


def parse_fed_h10_broad_dollar_html(raw: bytes) -> tuple[date, str]:
    if not raw or len(raw) > 4_000_000:
        raise H10ParseError("fed_h10_payload_size")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise H10ParseError("fed_h10_encoding") from exc

    parser = _H10TableParser()
    parser.feed(text)
    released = _release_date(" ".join(parser.text_parts))

    header: list[str] | None = None
    broad: list[str] | None = None
    for row in parser.rows:
        normalized = [cell.upper() for cell in row]
        if len(row) >= 3 and "COUNTRY" in normalized[0] and "CURRENCY" in normalized[1]:
            header = row
        if row and row[0].upper().replace(" ", "").startswith("1)BROAD"):
            broad = row

    if header is None:
        raise H10ParseError("fed_h10_header_missing")
    if broad is None:
        raise H10ParseError("fed_h10_broad_row_missing")
    if len(header) < 3 or len(broad) < 3:
        raise H10ParseError("fed_h10_table_incomplete")

    date_labels = header[2:]
    values = broad[2:]
    pairs: list[tuple[date, str]] = []
    for label, value in zip(date_labels, values, strict=False):
        clean_value = value.strip()
        if not clean_value or clean_value.upper() == "ND":
            continue
        observed = _observation_date(label, released=released)
        pairs.append((observed, clean_value))
    if not pairs:
        raise H10ParseError("fed_h10_no_broad_observations")
    return max(pairs, key=lambda item: item[0])
