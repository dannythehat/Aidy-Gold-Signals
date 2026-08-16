from __future__ import annotations

from datetime import UTC

import pytest

from aidy.fed_rss import FedRssError, _published_at, parse_fed_rss


def test_naive_publication_time_is_unknown() -> None:
    assert _published_at("2026-08-16T12:00:00") is None


def test_rfc822_publication_time_is_normalized_to_utc() -> None:
    parsed = _published_at("Sun, 16 Aug 2026 08:00:00 -0400")
    assert parsed is not None
    assert parsed.tzinfo is UTC
    assert parsed.hour == 12


def test_entity_bearing_xml_is_rejected_before_parsing() -> None:
    xml = '<!DOCTYPE rss [<!ENTITY x "boom">]><rss><channel/></rss>'
    with pytest.raises(FedRssError, match="fed_rss_doctype_not_allowed"):
        parse_fed_rss(xml, feed_key="fed_speeches")


def test_rss_item_becomes_deterministic_evidence() -> None:
    xml = """
    <rss><channel><item>
      <title>Federal Reserve statement</title>
      <guid>abc-123</guid>
      <link>https://www.federalreserve.gov/example</link>
      <pubDate>Sun, 16 Aug 2026 08:00:00 -0400</pubDate>
      <description>Example</description>
    </item></channel></rss>
    """
    rows = parse_fed_rss(xml, feed_key="fed_press_monetary")
    assert len(rows) == 1
    assert rows[0]["external_id"] == "fed_press_monetary:abc-123"
    assert rows[0]["headline"] == "Federal Reserve statement"
