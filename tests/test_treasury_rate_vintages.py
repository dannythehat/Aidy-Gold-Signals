"""The Treasury curve we already store, turned into records the rates expert reads.

Every test here runs on the real 69 rows exported from production
`cross_market_observations` on 2026-09-23 (tests/fixtures/treasury_cross_market_rows.csv)
rather than on invented ones. This morning a synthetic fixture passed while production
stayed broken, so the data under test is the data that will be adapted.
"""

from __future__ import annotations

import csv
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from aidy.gold_rates_usd_cross_asset_expert import DAILY_RATE_SERIES, _daily_rates_context
from aidy.macro_vintages import (
    SERIES_DFII10,
    SERIES_DGS2,
    SERIES_DGS10,
    SERIES_T10YIE,
    SOURCE_ALFRED,
    SOURCE_US_TREASURY,
    conservative_available_after,
    verify_version_record,
)
from aidy.treasury_rate_vintages import (
    BREAKEVEN_DERIVATION,
    DERIVED_BREAKEVEN_ROLE,
    build_treasury_rate_records,
)

_FIXTURE = Path(__file__).parent / "fixtures" / "treasury_cross_market_rows.csv"


def _rows() -> list[dict[str, str]]:
    with _FIXTURE.open() as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        row["source"] = SOURCE_US_TREASURY
        row["source_url"] = "https://home.treasury.gov/resource-center/data-chart-center"
        row["source_document_digest"] = "a" * 64
    return rows


def _by(records, series_id):
    return {item["observation_date"]: item for item in records if item["series_id"] == series_id}


def test_every_produced_record_verifies() -> None:
    """The contract is the point. A record the expert would skip is worth nothing."""
    records = build_treasury_rate_records(_rows())
    assert records
    for record in records:
        assert verify_version_record(record), record["series_id"]


def test_all_four_series_the_expert_asks_for_are_produced() -> None:
    records = build_treasury_rate_records(_rows())
    produced = {item["series_id"] for item in records}
    assert produced == set(DAILY_RATE_SERIES)
    for series_id in DAILY_RATE_SERIES:
        assert len(_by(records, series_id)) == 23


def test_values_carry_through_unchanged() -> None:
    """The Treasury number and the FRED identifier describe the same published rate."""
    records = build_treasury_rate_records(_rows())
    assert _by(records, SERIES_DGS10)["2026-09-22"]["value"] == "4.96"
    assert _by(records, SERIES_DGS2)["2026-09-22"]["value"] == "4.71"
    assert _by(records, SERIES_DFII10)["2026-09-22"]["value"] == "2.63"


def test_the_breakeven_is_derived_and_says_so() -> None:
    """10y breakeven = nominal - real, which is FRED's own definition of T10YIE."""
    records = build_treasury_rate_records(_rows())
    breakeven = _by(records, SERIES_T10YIE)["2026-09-22"]
    assert Decimal(breakeven["value"]) == Decimal("4.96") - Decimal("2.63")
    assert breakeven["value"] == "2.33"
    assert breakeven["series_role"] == DERIVED_BREAKEVEN_ROLE
    assert breakeven["derivation"] == BREAKEVEN_DERIVATION
    assert "official" not in breakeven["series_role"]


def test_a_late_ingest_delays_availability_beyond_the_conservative_bound() -> None:
    """The 2026-09-11 curve was not in our database until 2026-09-13T07:00:56Z. Calling
    it available at midnight on the 12th would let a replay read a value we did not hold."""
    records = build_treasury_rate_records(_rows())
    record = _by(records, SERIES_DGS10)["2026-09-11"]
    available = datetime.fromisoformat(record["pit_available_after_utc"])
    assert available == datetime(2026, 9, 13, 7, 0, 56, 676000, tzinfo=UTC)
    assert available > conservative_available_after(date(2026, 9, 11))


def test_a_same_day_ingest_still_waits_for_the_conservative_bound() -> None:
    """2026-09-22 was ingested at 20:01Z, but the record is not available until midnight
    on the 23rd. Treasury publishes in the evening; the bound is what protects us."""
    records = build_treasury_rate_records(_rows())
    record = _by(records, SERIES_DGS10)["2026-09-22"]
    assert record["pit_available_after_utc"] == "2026-09-23T00:00:00+00:00"


def test_availability_is_never_earlier_than_the_conservative_bound() -> None:
    """The invariant that makes this safe, checked over every record produced."""
    for record in build_treasury_rate_records(_rows()):
        observed = date.fromisoformat(record["observation_date"])
        available = datetime.fromisoformat(record["pit_available_after_utc"])
        assert available >= conservative_available_after(observed), record


def test_a_derived_value_is_never_available_before_its_inputs() -> None:
    """A breakeven computed from two series cannot be known before both of them are."""
    records = build_treasury_rate_records(_rows())
    nominal, real, breakeven = (
        _by(records, SERIES_DGS10),
        _by(records, SERIES_DFII10),
        _by(records, SERIES_T10YIE),
    )
    for day, record in breakeven.items():
        available = datetime.fromisoformat(record["pit_available_after_utc"])
        assert available >= datetime.fromisoformat(nominal[day]["pit_available_after_utc"])
        assert available >= datetime.fromisoformat(real[day]["pit_available_after_utc"])


def test_the_rates_expert_reads_them_as_known() -> None:
    """End to end: the block that has reported `unknown` on every cycle since Build 16."""
    records = build_treasury_rate_records(_rows())
    context = _daily_rates_context(records, as_of=datetime(2026, 9, 23, 6, 0, tzinfo=UTC))
    assert context["state"] == "known"
    for series_id in DAILY_RATE_SERIES:
        assert context["series"][series_id]["state"] == "known"
    assert Decimal(context["series"][SERIES_DGS10]["value_percent"]) == Decimal("4.96")
    assert context["series"][SERIES_DGS10]["observation_date"] == "2026-09-22"


def test_the_expert_sees_nothing_before_the_data_was_available() -> None:
    """The same call an hour before the 09-22 curve becomes available must not see it."""
    records = build_treasury_rate_records(_rows())
    context = _daily_rates_context(records, as_of=datetime(2026, 9, 22, 23, 0, tzinfo=UTC))
    assert context["series"][SERIES_DGS10]["observation_date"] == "2026-09-21"


def test_the_curve_counts_as_one_unit_of_evidence_not_four() -> None:
    """Four correlated components of one mechanism. The expert's own dependency policy
    says so, and it is the reason deriving the breakeven adds no false independence."""
    records = build_treasury_rate_records(_rows())
    context = _daily_rates_context(records, as_of=datetime(2026, 9, 23, 6, 0, tzinfo=UTC))
    policy = context["dependency_policy"]
    assert policy["independent_confirmation_units"] == 1
    assert policy["same_mechanism_components_not_independent"] is True


def test_malformed_rows_are_skipped_rather_than_guessed_at() -> None:
    rows = _rows()
    rows.append({**rows[0], "value": ""})
    rows.append({**rows[0], "observation_date": "not-a-date"})
    rows.append({**rows[0], "series_id": "UNKNOWN_SERIES"})
    rows.append({**rows[0], "source": SOURCE_ALFRED})
    records = build_treasury_rate_records(rows)
    assert len(_by(records, SERIES_DGS10)) == 23
    for record in records:
        assert verify_version_record(record)


def test_a_later_revision_supersedes_an_earlier_print() -> None:
    rows = _rows()
    first = next(r for r in rows if r["series_id"] == "UST_NOMINAL_10Y" and r["observation_date"] == "2026-09-22")
    rows.append({**first, "value": "5.10", "revision_index": "2"})
    records = build_treasury_rate_records(rows)
    assert _by(records, SERIES_DGS10)["2026-09-22"]["value"] == "5.1"


def test_the_relaxation_does_not_leak_to_alfred_records() -> None:
    """Treasury records may declare availability later than the conservative bound.
    ALFRED records may not - their rule stays exact, so this change cannot loosen the
    path that was already correct."""
    from aidy.macro_vintages import _digest

    records = build_treasury_rate_records(_rows())
    treasury = dict(_by(records, SERIES_DGS10)["2026-09-11"])
    assert verify_version_record(treasury)

    alfred = {k: v for k, v in treasury.items() if k != "version_identity"}
    alfred["source"] = SOURCE_ALFRED
    alfred["version_identity"] = _digest(
        {k: v for k, v in alfred.items() if k != "version_identity"}
    )
    assert not verify_version_record(alfred), (
        "an ALFRED record whose availability is later than the conservative bound "
        "must still be rejected"
    )


def test_availability_earlier_than_the_bound_is_rejected_for_treasury_too() -> None:
    """Later is safe because it only withholds evidence. Earlier is lookahead, and is
    refused under both sources."""
    from aidy.macro_vintages import _digest

    record = dict(_by(build_treasury_rate_records(_rows()), SERIES_DGS10)["2026-09-22"])
    del record["version_identity"]
    record["pit_available_after_utc"] = "2026-09-22T12:00:00+00:00"
    record["version_identity"] = _digest(record)
    assert not verify_version_record(record)


def test_the_real_expert_builds_a_verifiable_packet_from_these_records() -> None:
    """The call the shadow loop will make, on the real Treasury rows.

    This morning a change that passed its own tests took the loop down for five hours,
    because the tests exercised a reconstruction and production exercised the real thing.
    So this runs the actual expert builder against the actual data, and checks the packet
    the loop would store.
    """
    from test_gold_rates_usd_cross_asset_expert import _environment

    from aidy.gold_expert_gate_contract import verify_expert_gate_packet
    from aidy.gold_rates_usd_cross_asset_expert import (
        RATES_CROSS_ASSET_GATE_ID,
        build_rates_usd_cross_asset_expert,
    )

    result = build_rates_usd_cross_asset_expert(
        global_environment=_environment(),
        rates_version_records=build_treasury_rate_records(_rows()),
        cross_asset_observations=(),
        relationship_history_rows=(),
    )
    packet = result["expert_packet"]
    assert packet["gate_id"] == RATES_CROSS_ASSET_GATE_ID
    assert verify_expert_gate_packet(packet)
    # context_only: it carries regime context and can never cast a directional vote.
    assert packet["gate_mode"] == "context_only"
    assert packet["conclusion"] == "context_only"


def test_connecting_it_cannot_create_directional_mass() -> None:
    """The safety property that makes this change small: whatever the rates block says,
    a context_only gate contributes zero directional weight, so this cannot move a
    trading decision or paper over the family deadlock."""
    from test_gold_rates_usd_cross_asset_expert import _environment

    from aidy.gold_rates_usd_cross_asset_expert import build_rates_usd_cross_asset_expert

    result = build_rates_usd_cross_asset_expert(
        global_environment=_environment(),
        rates_version_records=build_treasury_rate_records(_rows()),
        cross_asset_observations=(),
        relationship_history_rows=(),
    )
    for item in result["expert_packet"]["subcalculators"]:
        assert item["role"] == "context_only"
        assert item["scoreable"] is False


def test_the_rates_gate_is_no_longer_a_stub() -> None:
    """The point of all of this. Until 2026-09-23 the live loop emitted a hardcoded
    `unknown` for this gate and never called the expert, while the Treasury data it
    needed sat in the database unread."""
    from aidy.gold_expert_shadow import _DISCONNECTED_CONTEXT_GATES, EXPECTED_GATES
    from aidy.gold_rates_usd_cross_asset_expert import RATES_CROSS_ASSET_GATE_ID

    assert RATES_CROSS_ASSET_GATE_ID not in _DISCONNECTED_CONTEXT_GATES
    assert RATES_CROSS_ASSET_GATE_ID in EXPECTED_GATES


def test_the_expert_still_builds_when_no_treasury_rows_are_available_yet() -> None:
    """The most likely production shape on any cycle whose as_of predates our first
    Treasury row. It must report unknown, not raise - a raise here takes the whole
    shadow loop down, which is exactly how AIDY lost five hours this morning."""
    from test_gold_rates_usd_cross_asset_expert import _environment

    from aidy.gold_expert_gate_contract import verify_expert_gate_packet
    from aidy.gold_rates_usd_cross_asset_expert import build_rates_usd_cross_asset_expert

    assert build_treasury_rate_records([]) == []
    result = build_rates_usd_cross_asset_expert(
        global_environment=_environment(),
        rates_version_records=(),
        cross_asset_observations=(),
        relationship_history_rows=(),
    )
    assert verify_expert_gate_packet(result["expert_packet"])
