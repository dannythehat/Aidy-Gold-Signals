from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime
from typing import Any

from aidy.bls_calendar_parser import parse_bls_official_calendar
from aidy.fed_rss import FED_RSS_FEEDS, FedRssGateway, parse_fed_rss
from aidy.fomc_calendar_parser import parse_fomc_calendar
from aidy.official_macro import (
    BEA_CURRENT_RELEASES_URL,
    BEA_SCHEDULE_URL,
    BLS_CALENDAR_URL,
    BLS_RSS_FEEDS,
    OfficialMacroGateway,
    parse_bea_current_releases_html,
    parse_bea_schedule_html,
    parse_bls_release_rss,
    upcoming_fed_calendar_sources,
)


def _class_set(observations: list[dict[str, object]]) -> set[str]:
    result: set[str] = set()
    for observation in observations:
        raw = observation.get("structured_data_json")
        if not isinstance(raw, str):
            continue
        try:
            structured = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(structured, dict) and structured.get("event_class"):
            result.add(str(structured["event_class"]))
    return result


async def probe() -> dict[str, Any]:
    now = datetime.now(UTC)
    gateway = OfficialMacroGateway(timeout_seconds=30)
    report: dict[str, Any] = {"observed_at": now.isoformat(), "sources": {}}

    fetched = await gateway.fetch(source_key="bls_calendar", url=BLS_CALENDAR_URL)
    assert fetched.text is not None
    bls_calendar = parse_bls_official_calendar(fetched.text)
    bls_schedule_classes = _class_set(bls_calendar)
    required_bls = {
        "cpi",
        "ppi",
        "employment_situation",
        "jolts",
        "employment_cost_index",
    }
    if not required_bls.issubset(bls_schedule_classes):
        raise RuntimeError(
            f"BLS calendar missing required classes: {sorted(required_bls - bls_schedule_classes)}"
        )
    report["sources"]["bls_calendar"] = {
        "observations": len(bls_calendar),
        "classes": sorted(bls_schedule_classes),
    }

    bls_release_classes: set[str] = set()
    for key, url in BLS_RSS_FEEDS.items():
        fetched = await gateway.fetch(source_key=key, url=url)
        assert fetched.text is not None
        observations = parse_bls_release_rss(fetched.text, feed_key=key)
        if not observations:
            raise RuntimeError(f"Official BLS RSS feed returned no observations: {key}")
        classes = _class_set(observations)
        bls_release_classes.update(classes)
        report["sources"][key] = {
            "observations": len(observations),
            "classes": sorted(classes),
        }
    if not required_bls.issubset(bls_release_classes):
        raise RuntimeError(
            f"BLS RSS missing required classes: {sorted(required_bls - bls_release_classes)}"
        )

    fetched = await gateway.fetch(source_key="bea_schedule", url=BEA_SCHEDULE_URL)
    assert fetched.text is not None
    bea_schedule = parse_bea_schedule_html(fetched.text, year=now.year)
    bea_schedule_classes = _class_set(bea_schedule)
    required_bea = {"gdp", "personal_income_outlays_pce", "international_trade"}
    if not required_bea.issubset(bea_schedule_classes):
        raise RuntimeError(
            f"BEA schedule missing required classes: {sorted(required_bea - bea_schedule_classes)}"
        )
    report["sources"]["bea_schedule"] = {
        "observations": len(bea_schedule),
        "classes": sorted(bea_schedule_classes),
    }

    fetched = await gateway.fetch(source_key="bea_releases", url=BEA_CURRENT_RELEASES_URL)
    assert fetched.text is not None
    bea_releases = parse_bea_current_releases_html(fetched.text)
    bea_release_classes = _class_set(bea_releases)
    if not bea_releases:
        raise RuntimeError("BEA current releases produced no accepted observations")
    report["sources"]["bea_releases"] = {
        "observations": len(bea_releases),
        "classes": sorted(bea_release_classes),
    }

    fed_classes: set[str] = set()
    fed_rows = 0
    fed_source_rows: dict[str, int] = {}
    for key, url, year, month in upcoming_fed_calendar_sources(now, months=4):
        fetched = await gateway.fetch(source_key=key, url=url)
        assert fetched.text is not None
        observations = parse_fomc_calendar(
            fetched.text,
            year=year,
            month=month,
            source_url=url,
        )
        classes = _class_set(observations)
        fed_classes.update(classes)
        fed_rows += len(observations)
        fed_source_rows[key] = len(observations)
    required_fed = {"fomc_decision", "fomc_press_conference"}
    if not required_fed.issubset(fed_classes):
        raise RuntimeError(
            f"Federal Reserve calendar missing required classes: {sorted(required_fed - fed_classes)}"
        )
    report["sources"]["federal_reserve_calendars"] = {
        "observations": fed_rows,
        "classes": sorted(fed_classes),
        "monthly_counts": fed_source_rows,
    }

    fed_gateway = FedRssGateway(timeout_seconds=30)
    monetary_url = FED_RSS_FEEDS["fed_press_monetary"]
    xml = await fed_gateway.fetch(feed_key="fed_press_monetary", url=monetary_url)
    assert xml is not None
    monetary = parse_fed_rss(xml, feed_key="fed_press_monetary")
    if not monetary:
        raise RuntimeError("Federal Reserve monetary-policy RSS returned no observations")
    report["sources"]["fed_press_monetary"] = {"observations": len(monetary)}

    report["accepted_classes"] = sorted(required_bls | required_bea | required_fed)
    report["status"] = "PASS"
    return report


def main() -> int:
    try:
        print(json.dumps(asyncio.run(probe()), sort_keys=True))
        return 0
    except Exception as exc:
        print(f"DAY8_OFFICIAL_MACRO_PROBE_ERROR={type(exc).__name__}:{exc}", file=sys.stderr)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
