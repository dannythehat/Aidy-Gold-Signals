from __future__ import annotations

import json

from aidy.bls_calendar_parser import parse_bls_official_calendar


def _structured(row: dict[str, object]) -> dict[str, object]:
    return json.loads(str(row["structured_data_json"]))


def test_plain_bls_dtstart_is_official_eastern_wall_time() -> None:
    text = """BEGIN:VCALENDAR
BEGIN:VEVENT
UID:cpi-live-shape
DTSTART:20260911T083000
SUMMARY:Consumer Price Index for August 2026
END:VEVENT
END:VCALENDAR
"""
    rows = parse_bls_official_calendar(text)
    assert len(rows) == 1
    assert _structured(rows[0])["event_class"] == "cpi"
    assert _structured(rows[0])["scheduled_at"] == "2026-09-11T12:30:00+00:00"


def test_bls_employer_costs_title_maps_to_eci_class() -> None:
    text = """BEGIN:VCALENDAR
BEGIN:VEVENT
UID:eci-live-name
DTSTART:20261030T083000
SUMMARY:Employer Costs for Employee Compensation for Third Quarter 2026
END:VEVENT
END:VCALENDAR
"""
    rows = parse_bls_official_calendar(text)
    assert len(rows) == 1
    assert _structured(rows[0])["event_class"] == "employment_cost_index"


def test_live_bls_us_eastern_tzid_alias_is_accepted() -> None:
    text = """BEGIN:VCALENDAR
BEGIN:VEVENT
UID:jobs-live-tzid
DTSTART;TZID=US-Eastern:20260110T083000
SUMMARY:Employment Situation
END:VEVENT
END:VCALENDAR
"""
    rows = parse_bls_official_calendar(text)
    assert len(rows) == 1
    assert _structured(rows[0])["event_class"] == "employment_situation"
    assert _structured(rows[0])["scheduled_at"] == "2026-01-10T13:30:00+00:00"
