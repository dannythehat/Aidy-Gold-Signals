from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
import json

import pytest

from aidy.cross_market import (
    CrossMarketError,
    CrossMarketGateway,
    CrossMarketObservation,
    SERIES_US10Y,
    SERIES_US10Y_REAL,
    SERIES_US2Y,
    SERIES_USD_BROAD,
    parse_fred_broad_dollar_csv,
    parse_treasury_yield_xml,
)
from aidy.cross_market_asof import reconstruct_cross_market_as_of
from aidy.cross_market_bigquery import ArchivedCrossMarketEvidence
from aidy.cross_market_recorder import AidyCrossMarketRecorderService
from aidy.cross_market_storage import cross_market_archive_key


FRED_CSV = b"""observation_date,DTWEXBGS
2026-08-17,119.1000
2026-08-18,119.2500
"""

TREASURY_NOMINAL = b"""<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:m="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata"
      xmlns:d="http://schemas.microsoft.com/ado/2007/08/dataservices">
  <entry><content type="application/xml"><m:properties>
    <d:NEW_DATE m:type="Edm.DateTime">2026-08-18T00:00:00</d:NEW_DATE>
    <d:BC_2YEAR m:type="Edm.Double">3.75</d:BC_2YEAR>
    <d:BC_10YEAR m:type="Edm.Double">4.31</d:BC_10YEAR>
  </m:properties></content></entry>
</feed>"""

TREASURY_REAL = b"""<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:m="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata"
      xmlns:d="http://schemas.microsoft.com/ado/2007/08/dataservices">
  <entry><content type="application/xml"><m:properties>
    <d:NEW_DATE m:type="Edm.DateTime">2026-08-18T00:00:00</d:NEW_DATE>
    <d:TC_10YEAR m:type="Edm.Double">1.92</d:TC_10YEAR>
  </m:properties></content></entry>
</feed>"""


def test_fred_broad_dollar_uses_latest_real_daily_observation() -> None:
    observation = parse_fred_broad_dollar_csv(FRED_CSV)
    assert observation.series_id == SERIES_USD_BROAD
    assert observation.observation_date == date(2026, 8, 18)
    assert observation.value == "119.25"
    assert observation.unit == "index_jan_2006_100"
    assert len(observation.source_document_digest) == 64


def test_treasury_nominal_extracts_only_approved_tenors() -> None:
    rows = parse_treasury_yield_xml(
        TREASURY_NOMINAL,
        source_url="https://home.treasury.gov/example",
        real=False,
    )
    assert {row.series_id for row in rows} == {SERIES_US2Y, SERIES_US10Y}
    assert {row.value for row in rows} == {"3.75", "4.31"}
    assert all(row.observation_date == date(2026, 8, 18) for row in rows)


def test_treasury_real_extracts_ten_year_real_yield() -> None:
    rows = parse_treasury_yield_xml(
        TREASURY_REAL,
        source_url="https://home.treasury.gov/example",
        real=True,
    )
    assert len(rows) == 1
    assert rows[0].series_id == SERIES_US10Y_REAL
    assert rows[0].value == "1.92"


def test_treasury_xml_rejects_entities() -> None:
    with pytest.raises(CrossMarketError, match="unsafe_xml"):
        parse_treasury_yield_xml(
            b"<!DOCTYPE foo [<!ENTITY xxe SYSTEM 'file:///etc/passwd'>]><feed/>",
            source_url="https://home.treasury.gov/example",
        )


def _row(
    *,
    series_id: str,
    value: str,
    first_seen: datetime,
    revision: int = 1,
    observation_day: date = date(2026, 8, 18),
) -> dict[str, object]:
    return {
        "load_identity": f"load-{series_id}-{revision}",
        "evidence_id": f"evidence-{series_id}-{revision}",
        "archive_key": f"cross-market/{series_id}/{revision}.json",
        "payload_digest": f"digest-{series_id}-{revision}",
        "source_document_digest": f"source-{series_id}-{revision}",
        "source": "fixture",
        "series_id": series_id,
        "observation_date": observation_day.isoformat(),
        "value": value,
        "unit": "percent",
        "source_url": "https://example.invalid/source",
        "first_observed_at": first_seen,
        "revision_index": revision,
    }


def test_cross_market_revision_does_not_leak_backwards() -> None:
    first = datetime(2026, 8, 19, 10, 0, tzinfo=UTC)
    rows = [
        _row(series_id=SERIES_US10Y, value="4.30", first_seen=first, revision=1),
        _row(
            series_id=SERIES_US10Y,
            value="4.31",
            first_seen=first + timedelta(hours=2),
            revision=2,
        ),
    ]
    before = reconstruct_cross_market_as_of(rows, as_of=first + timedelta(hours=1))
    after = reconstruct_cross_market_as_of(rows, as_of=first + timedelta(hours=2))
    assert before["series"][SERIES_US10Y]["fact"]["value"] == "4.30"
    assert after["series"][SERIES_US10Y]["fact"]["value"] == "4.31"


def test_cross_market_unknown_before_first_aidy_observation() -> None:
    first = datetime(2026, 8, 19, 10, 0, tzinfo=UTC)
    result = reconstruct_cross_market_as_of(
        [_row(series_id=SERIES_US2Y, value="3.75", first_seen=first)],
        as_of=first - timedelta(microseconds=1),
    )
    assert result["series"][SERIES_US2Y]["state"] == "unknown"


def test_source_observation_date_cannot_create_future_knowledge() -> None:
    first = datetime(2026, 8, 19, 10, 0, tzinfo=UTC)
    result = reconstruct_cross_market_as_of(
        [
            _row(
                series_id=SERIES_US2Y,
                value="3.75",
                first_seen=first,
                observation_day=date(2026, 8, 20),
            )
        ],
        as_of=first,
    )
    assert result["series"][SERIES_US2Y]["state"] == "unknown"


def test_cross_market_archive_key_is_digest_bearing_and_namespaced() -> None:
    observed = datetime(2026, 8, 19, 10, 0, tzinfo=UTC)
    key = cross_market_archive_key(
        source="us_treasury",
        series_id=SERIES_US10Y,
        observation_date=date(2026, 8, 18),
        first_observed_at=observed,
        payload_digest="a" * 64,
    )
    assert key.startswith("cross-market/2026/08/19/us_treasury/UST_NOMINAL_10Y/")
    assert "a" * 64 in key


def test_bigquery_cross_market_archive_preserves_provenance() -> None:
    raw = json.dumps(
        {
            "schema_version": 1,
            "record_type": "cross_market",
            "evidence_id": "evidence-1",
            "archive_key": "cross-market/evidence.json",
            "payload_digest": "a" * 64,
            "revision_index": 2,
            "payload": {
                "source": "us_treasury",
                "series_id": SERIES_US10Y,
                "observation_date": "2026-08-18",
                "value": "4.31",
                "unit": "percent",
                "source_url": "https://home.treasury.gov/source",
                "source_document_digest": "b" * 64,
                "first_observed_at": "2026-08-19T10:00:00+00:00",
            },
        }
    )
    row = ArchivedCrossMarketEvidence.from_json(raw).analytical_row()
    assert row["series_id"] == SERIES_US10Y
    assert row["revision_index"] == 2
    assert row["source_document_digest"] == "b" * 64


class _FakeRepository:
    def __init__(self) -> None:
        self.rows: list[dict[str, object]] = []

    async def store_cross_market_observation(self, **kwargs):
        self.rows.append(kwargs)
        return "id", 1, True


class _FakeGateway:
    async def fetch_broad_dollar(self):
        return CrossMarketObservation(
            source="fred_stlouisfed",
            series_id=SERIES_USD_BROAD,
            observation_date=date(2026, 8, 18),
            value="119.25",
            unit="index_jan_2006_100",
            source_url="https://fred.stlouisfed.org/source",
            source_document_digest="a" * 64,
        )

    async def fetch_treasury_nominal(self):
        return [
            CrossMarketObservation(
                source="us_treasury",
                series_id=SERIES_US2Y,
                observation_date=date(2026, 8, 18),
                value="3.75",
                unit="percent",
                source_url="https://home.treasury.gov/source",
                source_document_digest="b" * 64,
            ),
            CrossMarketObservation(
                source="us_treasury",
                series_id=SERIES_US10Y,
                observation_date=date(2026, 8, 18),
                value="4.31",
                unit="percent",
                source_url="https://home.treasury.gov/source",
                source_document_digest="b" * 64,
            ),
        ]

    async def fetch_treasury_real(self):
        return [
            CrossMarketObservation(
                source="us_treasury",
                series_id=SERIES_US10Y_REAL,
                observation_date=date(2026, 8, 18),
                value="1.92",
                unit="percent",
                source_url="https://home.treasury.gov/source",
                source_document_digest="c" * 64,
            )
        ]


@pytest.mark.asyncio
async def test_recorder_stamps_first_observed_after_each_source_result() -> None:
    base = datetime(2026, 8, 19, 10, 0, tzinfo=UTC)
    tick = -1

    def clock() -> datetime:
        nonlocal tick
        tick += 1
        return base + timedelta(seconds=tick)

    repository = _FakeRepository()
    result = await AidyCrossMarketRecorderService(
        repository=repository,  # type: ignore[arg-type]
        gateway=_FakeGateway(),  # type: ignore[arg-type]
        clock=clock,
    ).capture_once()
    assert result.sources_checked == 3
    assert result.sources_failed == 0
    assert result.observations_seen == 4
    assert result.observations_added == 4
    assert len(repository.rows) == 4
    assert all(row["first_observed_at"] >= base for row in repository.rows)


@pytest.mark.asyncio
async def test_gateway_rejects_unapproved_host() -> None:
    gateway = CrossMarketGateway()
    with pytest.raises(CrossMarketError, match="source_not_allowed"):
        await gateway._fetch("https://example.com/fake")  # noqa: SLF001
