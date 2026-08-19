from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from aidy.fomc_calendar_parser import parse_fomc_calendar
from aidy.macro_event_windows import reconstruct_macro_event_window
from aidy.official_macro import (
    FetchedSource,
    OfficialMacroError,
    OfficialMacroGateway,
    parse_bea_current_releases_html,
    parse_bea_schedule_html,
    parse_bls_calendar_ics,
    parse_bls_release_rss,
)
from aidy.official_macro_recorder import AidyOfficialMacroRecorderService

BLS_ICS = """BEGIN:VCALENDAR
BEGIN:VEVENT
UID:cpi-sep-2026
DTSTART;TZID=America/New_York:20260910T083000
SUMMARY:Consumer Price Index
URL:https://www.bls.gov/cpi/
END:VEVENT
BEGIN:VEVENT
UID:jobs-sep-2026
DTSTART;TZID=America/New_York:20260904T083000
SUMMARY:Employment Situation
URL:https://www.bls.gov/news.release/empsit.nr0.htm
END:VEVENT
END:VCALENDAR
"""

BLS_RSS = """<rss><channel><item>
<title>Consumer Price Index - July 2026</title>
<link>https://www.bls.gov/news.release/cpi.nr0.htm</link>
<guid>cpi-july-2026</guid>
<pubDate>Wed, 12 Aug 2026 08:30:00 -0400</pubDate>
<description>Official CPI release.</description>
</item></channel></rss>"""

BEA_SCHEDULE = """<html><table><tr>
<td>August 26 8:30 AM</td><td>News</td>
<td><a href="/news/2026/gdp-second-estimate">GDP (Second Estimate), 2nd Quarter 2026</a></td>
</tr><tr>
<td>August 26 8:30 AM</td><td>News</td>
<td>Personal Income and Outlays, July 2026</td>
</tr></table></html>"""

BEA_RELEASES = """<html><table><tr>
<td><a href="/news/2026/gdp-advance">GDP (Advance Estimate), 2nd Quarter 2026</a></td>
<td>July 30, 2026</td>
</tr><tr>
<td>Personal Income and Outlays, June 2026</td><td>July 30, 2026</td>
</tr></table></html>"""

FED_SEPTEMBER = """<html><body>
<div>2:30 p.m.</div><div>FOMC Press Conference</div><div>16</div>
<div>2:00 p.m.</div><div>FOMC Meeting</div>
<div>Two-day meeting, September 15 - 16</div><div>Press Conference</div><div>16</div>
</body></html>"""

FED_SEPTEMBER_REVISED = """<html><body>
<div>2:30 p.m.</div><div>FOMC Press Conference</div><div>17</div>
<div>2:00 p.m.</div><div>FOMC Meeting</div>
<div>Two-day meeting, September 16 - 17</div><div>Press Conference</div><div>17</div>
</body></html>"""


def _structured(observation: dict[str, object]) -> dict[str, object]:
    return json.loads(str(observation["structured_data_json"]))


def test_bls_calendar_preserves_official_schedule_and_stable_uid() -> None:
    observations = parse_bls_calendar_ics(BLS_ICS)
    assert {str(_structured(item)["event_class"]) for item in observations} == {
        "cpi",
        "employment_situation",
    }
    cpi = next(item for item in observations if _structured(item)["event_class"] == "cpi")
    assert cpi["external_id"] == "bls_calendar:cpi-sep-2026"
    assert _structured(cpi)["scheduled_at"] == "2026-09-10T12:30:00+00:00"
    assert cpi["published_at"] is None


def test_bls_rss_preserves_release_publication_time() -> None:
    observations = parse_bls_release_rss(BLS_RSS, feed_key="bls_cpi")
    assert len(observations) == 1
    release = observations[0]
    assert _structured(release)["event_class"] == "cpi"
    assert _structured(release)["phase"] == "released"
    assert release["published_at"] == datetime(2026, 8, 12, 12, 30, tzinfo=UTC)


def test_bea_schedule_and_release_keep_unknown_release_clock_unknown() -> None:
    schedule = parse_bea_schedule_html(BEA_SCHEDULE, year=2026)
    classes = {_structured(item)["event_class"] for item in schedule}
    assert {"gdp", "personal_income_outlays_pce"}.issubset(classes)
    gdp = next(item for item in schedule if _structured(item)["event_class"] == "gdp")
    assert _structured(gdp)["scheduled_at"] == "2026-08-26T12:30:00+00:00"

    releases = parse_bea_current_releases_html(BEA_RELEASES)
    release = next(item for item in releases if _structured(item)["event_class"] == "gdp")
    assert release["published_at"] is None
    assert _structured(release)["published_at_precision"] == "unknown_time"


def test_fomc_calendar_uses_release_day_not_first_meeting_day() -> None:
    observations = parse_fomc_calendar(
        FED_SEPTEMBER,
        year=2026,
        month=9,
        source_url="https://www.federalreserve.gov/newsevents/2026-september.htm",
    )
    decision = next(
        item for item in observations if _structured(item)["event_class"] == "fomc_decision"
    )
    press = next(
        item
        for item in observations
        if _structured(item)["event_class"] == "fomc_press_conference"
    )
    assert _structured(decision)["scheduled_at"] == "2026-09-16T18:00:00+00:00"
    assert _structured(press)["scheduled_at"] == "2026-09-16T18:30:00+00:00"


def test_fomc_same_month_date_change_is_an_append_only_revision_identity() -> None:
    first = parse_fomc_calendar(
        FED_SEPTEMBER,
        year=2026,
        month=9,
        source_url="https://www.federalreserve.gov/newsevents/2026-september.htm",
    )
    revised = parse_fomc_calendar(
        FED_SEPTEMBER_REVISED,
        year=2026,
        month=9,
        source_url="https://www.federalreserve.gov/newsevents/2026-september.htm",
    )
    first_decision = next(
        item for item in first if _structured(item)["event_class"] == "fomc_decision"
    )
    revised_decision = next(
        item for item in revised if _structured(item)["event_class"] == "fomc_decision"
    )
    assert first_decision["external_id"] == revised_decision["external_id"]
    assert first_decision["payload_digest"] != revised_decision["payload_digest"]


def _event_row(
    *,
    source: str,
    external_id: str,
    revision: int,
    observed: datetime,
    event_class: str | None,
    scheduled: datetime | None = None,
    headline: str = "",
) -> dict[str, object]:
    structured: dict[str, object] = {"phase": "scheduled" if scheduled else "released"}
    if event_class is not None:
        structured["event_class"] = event_class
    if scheduled is not None:
        structured["scheduled_at"] = scheduled.isoformat()
    return {
        "source": source,
        "external_id": external_id,
        "event_type": "macro_schedule" if scheduled else "fed_press_monetary",
        "first_observed_at": observed,
        "published_at": observed if scheduled is None else None,
        "revision_index": revision,
        "headline": headline,
        "structured_data": structured,
        "load_identity": f"{external_id}-{revision}",
        "evidence_id": f"evidence-{external_id}-{revision}",
        "archive_key": f"events/{external_id}/{revision}.json",
        "payload_digest": f"digest-{external_id}-{revision}",
    }


def test_event_window_filters_revision_by_what_was_known_at_t() -> None:
    first_seen = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
    revised_seen = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)
    first_time = datetime(2026, 9, 16, 18, 0, tzinfo=UTC)
    revised_time = datetime(2026, 9, 17, 18, 0, tzinfo=UTC)
    rows = [
        _event_row(
            source="federal_reserve_calendar",
            external_id="fed-calendar-sep",
            revision=1,
            observed=first_seen,
            event_class="fomc_decision",
            scheduled=first_time,
        ),
        _event_row(
            source="federal_reserve_calendar",
            external_id="fed-calendar-sep",
            revision=2,
            observed=revised_seen,
            event_class="fomc_decision",
            scheduled=revised_time,
        ),
    ]
    before = reconstruct_macro_event_window(
        rows,
        as_of=first_seen + timedelta(days=1),
        center_at=first_time,
        event_class="fomc_decision",
    )
    after = reconstruct_macro_event_window(
        rows,
        as_of=revised_seen + timedelta(seconds=1),
        center_at=revised_time,
        event_class="fomc_decision",
    )
    assert [item["revision_index"] for item in before["observations"]] == [1]
    assert [item["revision_index"] for item in after["observations"]] == [2]


def test_fed_release_is_absent_before_first_observed_and_present_after() -> None:
    center = datetime(2026, 9, 16, 18, 0, tzinfo=UTC)
    observed = center + timedelta(seconds=4)
    rows = [
        _event_row(
            source="federal_reserve_rss",
            external_id="fed-press-statement",
            revision=1,
            observed=observed,
            event_class=None,
            headline="Federal Reserve issues FOMC statement",
        )
    ]
    before = reconstruct_macro_event_window(
        rows,
        as_of=center,
        center_at=center,
        event_class="fomc_decision",
    )
    after = reconstruct_macro_event_window(
        rows,
        as_of=observed,
        center_at=center,
        event_class="fomc_decision",
    )
    assert before["observations"] == []
    assert len(after["observations"]) == 1
    assert after["observations"][0]["first_observed_at"] == observed.isoformat()


@pytest.mark.asyncio
async def test_gateway_rejects_non_official_or_unapproved_source() -> None:
    gateway = OfficialMacroGateway()
    with pytest.raises(OfficialMacroError, match="source_not_allowed"):
        await gateway.fetch(source_key="bls_calendar", url="https://example.com/calendar.ics")


class _FakeGateway:
    async def fetch(self, *, source_key: str, url: str) -> FetchedSource:
        if source_key == "bls_calendar":
            text = BLS_ICS
        elif source_key.startswith("bls_"):
            text = "<rss><channel></channel></rss>"
        else:
            text = "<html><table></table></html>"
        return FetchedSource(source_key, url, text)


class _FakeRepository:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def store_event_observation(self, **kwargs):
        self.calls.append(kwargs)
        return uuid4(), 1, True


@pytest.mark.asyncio
async def test_recorder_stamps_first_observed_after_source_fetch() -> None:
    base = datetime(2026, 8, 19, 15, 0, tzinfo=UTC)
    counter = -1

    def clock() -> datetime:
        nonlocal counter
        counter += 1
        return base + timedelta(seconds=counter)

    repository = _FakeRepository()
    result = await AidyOfficialMacroRecorderService(
        repository=repository,  # type: ignore[arg-type]
        gateway=_FakeGateway(),  # type: ignore[arg-type]
        clock=clock,
    ).capture_once()

    assert result.sources_failed == 0
    assert result.observations_added == 2
    assert repository.calls
    assert all(call["first_observed_at"] > base for call in repository.calls)
