from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from urllib.parse import urlparse
from xml.etree import ElementTree

import httpx

from .fed_h10_dollar import FED_H10_CURRENT_URL, H10ParseError, parse_fed_h10_broad_dollar_html

TREASURY_NOMINAL_URL = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml"
    "?data=daily_treasury_yield_curve&field_tdr_date_value={year}"
)
TREASURY_REAL_URL = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml"
    "?data=daily_treasury_real_yield_curve&field_tdr_date_value={year}"
)

SOURCE_FED_H10 = "federal_reserve_h10"
SOURCE_TREASURY = "us_treasury"
SERIES_USD_BROAD = "DTWEXBGS"
SERIES_US2Y = "UST_NOMINAL_2Y"
SERIES_US10Y = "UST_NOMINAL_10Y"
SERIES_US10Y_REAL = "UST_REAL_10Y"
ENABLED_SERIES = (SERIES_USD_BROAD, SERIES_US2Y, SERIES_US10Y, SERIES_US10Y_REAL)

_ALLOWED_HOSTS = {"www.federalreserve.gov", "home.treasury.gov"}
_MAX_XML_BYTES = 4_000_000


class CrossMarketError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CrossMarketObservation:
    source: str
    series_id: str
    observation_date: date
    value: str
    unit: str
    source_url: str
    source_document_digest: str

    @property
    def payload_digest(self) -> str:
        payload = {
            "source": self.source,
            "series_id": self.series_id,
            "observation_date": self.observation_date.isoformat(),
            "value": self.value,
            "unit": self.unit,
            "source_url": self.source_url,
        }
        return sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


def _decimal_text(value: str) -> str:
    try:
        parsed = Decimal(value.strip())
    except InvalidOperation as exc:
        raise CrossMarketError("cross_market_invalid_decimal") from exc
    if not parsed.is_finite():
        raise CrossMarketError("cross_market_non_finite_decimal")
    text = format(parsed, "f").rstrip("0").rstrip(".")
    return text or "0"


def _digest(raw: bytes) -> str:
    return sha256(raw).hexdigest()


def parse_fed_h10_broad_dollar(raw: bytes) -> CrossMarketObservation:
    try:
        observation_date, raw_value = parse_fed_h10_broad_dollar_html(raw)
    except H10ParseError as exc:
        raise CrossMarketError(str(exc)) from exc
    return CrossMarketObservation(
        source=SOURCE_FED_H10,
        series_id=SERIES_USD_BROAD,
        observation_date=observation_date,
        value=_decimal_text(raw_value),
        unit="index_jan_2006_100",
        source_url=FED_H10_CURRENT_URL,
        source_document_digest=_digest(raw),
    )


def _xml_text(element: ElementTree.Element, suffix: str) -> str | None:
    suffix = suffix.upper()
    for child in element.iter():
        local = child.tag.rsplit("}", 1)[-1].upper()
        if local == suffix and child.text is not None:
            value = child.text.strip()
            if value:
                return value
    return None


def _treasury_date(entry: ElementTree.Element) -> date | None:
    raw = _xml_text(entry, "NEW_DATE") or _xml_text(entry, "NEW_DATE_VALUE")
    if raw is None:
        return None
    try:
        return datetime.fromisoformat(raw).date()
    except ValueError:
        try:
            return date.fromisoformat(raw[:10])
        except ValueError as exc:
            raise CrossMarketError("treasury_invalid_date") from exc


def parse_treasury_yield_xml(
    raw: bytes,
    *,
    source_url: str,
    real: bool = False,
) -> list[CrossMarketObservation]:
    if not raw or len(raw) > _MAX_XML_BYTES:
        raise CrossMarketError("treasury_payload_size")
    lowered = raw[:2048].lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        raise CrossMarketError("treasury_unsafe_xml")
    try:
        root = ElementTree.fromstring(raw)
    except ElementTree.ParseError as exc:
        raise CrossMarketError("treasury_invalid_xml") from exc

    candidates: list[tuple[date, ElementTree.Element]] = []
    for entry in root.iter():
        if entry.tag.rsplit("}", 1)[-1].lower() != "entry":
            continue
        day = _treasury_date(entry)
        if day is not None:
            candidates.append((day, entry))
    if not candidates:
        raise CrossMarketError("treasury_no_entries")
    day, entry = max(candidates, key=lambda item: item[0])
    document_digest = _digest(raw)

    if real:
        raw_10y = _xml_text(entry, "TC_10YEAR")
        if raw_10y is None:
            raise CrossMarketError("treasury_real_10y_missing")
        return [
            CrossMarketObservation(
                source=SOURCE_TREASURY,
                series_id=SERIES_US10Y_REAL,
                observation_date=day,
                value=_decimal_text(raw_10y),
                unit="percent",
                source_url=source_url,
                source_document_digest=document_digest,
            )
        ]

    raw_2y = _xml_text(entry, "BC_2YEAR")
    raw_10y = _xml_text(entry, "BC_10YEAR")
    if raw_2y is None or raw_10y is None:
        raise CrossMarketError("treasury_nominal_required_tenor_missing")
    return [
        CrossMarketObservation(
            source=SOURCE_TREASURY,
            series_id=SERIES_US2Y,
            observation_date=day,
            value=_decimal_text(raw_2y),
            unit="percent",
            source_url=source_url,
            source_document_digest=document_digest,
        ),
        CrossMarketObservation(
            source=SOURCE_TREASURY,
            series_id=SERIES_US10Y,
            observation_date=day,
            value=_decimal_text(raw_10y),
            unit="percent",
            source_url=source_url,
            source_document_digest=document_digest,
        ),
    ]


class CrossMarketGateway:
    def __init__(self, *, timeout_seconds: float = 30.0) -> None:
        self._timeout = timeout_seconds

    @staticmethod
    def _validate_url(url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in _ALLOWED_HOSTS:
            raise CrossMarketError("cross_market_source_not_allowed")

    async def _fetch(self, url: str) -> bytes:
        self._validate_url(url)
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                follow_redirects=True,
                headers={"User-Agent": "AIDY-Signals-Cross-Market/1.0"},
            ) as client:
                response = await client.get(url)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise CrossMarketError("cross_market_http_error") from exc
        return response.content

    async def fetch_broad_dollar(self) -> CrossMarketObservation:
        raw = await self._fetch(FED_H10_CURRENT_URL)
        return parse_fed_h10_broad_dollar(raw)

    async def fetch_treasury_nominal(self, *, year: int | None = None) -> list[CrossMarketObservation]:
        resolved_year = year or datetime.now(UTC).year
        url = TREASURY_NOMINAL_URL.format(year=resolved_year)
        raw = await self._fetch(url)
        return parse_treasury_yield_xml(raw, source_url=url, real=False)

    async def fetch_treasury_real(self, *, year: int | None = None) -> list[CrossMarketObservation]:
        resolved_year = year or datetime.now(UTC).year
        url = TREASURY_REAL_URL.format(year=resolved_year)
        raw = await self._fetch(url)
        return parse_treasury_yield_xml(raw, source_url=url, real=True)
