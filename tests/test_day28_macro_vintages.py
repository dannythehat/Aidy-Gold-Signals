from __future__ import annotations

from copy import deepcopy
from datetime import UTC, date, datetime
from hashlib import sha256

import pytest

import aidy.context_packet_v4 as context_v4
from aidy.macro_vintages import (
    EVIDENCE_FAMILY,
    REAL_YIELD_DIRECTIONAL_INFLUENCE,
    SERIES_CPI,
    SERIES_DFII10,
    SERIES_DGS2,
    SERIES_DGS10,
    SERIES_T10YIE,
    AlfredSnapshot,
    alfred_url,
    build_rates_macro_state,
    build_version_history,
    conservative_available_after,
    parse_alfred_csv,
    reconstruct_series_as_of,
    verify_rates_macro_state,
)


def _snapshot(series: str, vintage: date, values: dict[str, str | None], suffix: str = "a") -> AlfredSnapshot:
    rows = tuple(sorted((date.fromisoformat(day), value) for day, value in values.items()))
    return AlfredSnapshot(
        series_id=series,
        vintage_date=vintage,
        observation_start=date(2024, 10, 1),
        observation_end=date(2025, 1, 8),
        values=rows,
        source_url=f"https://alfred.stlouisfed.org/graph/alfredgraph.csv?fixture={suffix}",
        source_sha256=(suffix * 64)[:64],
    )


def _rates_records(*, dgs2_date: str = "2025-01-03") -> list[dict[str, object]]:
    snapshots = [
        _snapshot(SERIES_DGS2, date(2025, 1, 4), {dgs2_date: "4.25"}, "a"),
        _snapshot(SERIES_DGS10, date(2025, 1, 4), {"2025-01-03": "4.60"}, "b"),
        _snapshot(SERIES_DFII10, date(2025, 1, 4), {"2025-01-03": "2.10"}, "c"),
        _snapshot(SERIES_T10YIE, date(2025, 1, 4), {"2025-01-03": "2.50"}, "d"),
        _snapshot(SERIES_CPI, date(2024, 12, 12), {"2024-11-01": "315.493"}, "e"),
    ]
    return build_version_history(snapshots)


def test_alfred_url_is_keyless_and_vintage_scoped() -> None:
    url = alfred_url(
        series_id=SERIES_DGS10,
        vintage_date=date(2025, 1, 6),
        observation_start=date(2024, 12, 1),
        observation_end=date(2025, 1, 6),
    )
    assert "api_key" not in url
    assert "vintage_date=2025-01-06" in url
    assert "id=DGS10" in url


def test_parse_alfred_csv_uses_column_position_and_preserves_missing() -> None:
    raw = b"observation_date,DGS10_20250106\n2025-01-02,4.55\n2025-01-03,.\n"
    snapshot = parse_alfred_csv(
        raw,
        series_id=SERIES_DGS10,
        vintage_date=date(2025, 1, 6),
        observation_start=date(2025, 1, 1),
        observation_end=date(2025, 1, 6),
        source_url="https://alfred.stlouisfed.org/graph/alfredgraph.csv?fixture=1",
    )
    assert snapshot.values == ((date(2025, 1, 2), "4.55"), (date(2025, 1, 3), None))
    assert snapshot.source_sha256 == sha256(raw).hexdigest()


def test_date_only_vintage_is_available_next_utc_day() -> None:
    assert conservative_available_after(date(2025, 1, 6)) == datetime(
        2025, 1, 7, 0, 0, tzinfo=UTC
    )


def test_first_snapshot_never_claims_historical_first_print() -> None:
    records = build_version_history(
        [_snapshot(SERIES_CPI, date(2024, 12, 1), {"2024-10-01": "314.686"})]
    )
    assert records[0]["first_print_state"] == "pre_window_unknown"
    assert records[0]["revision_type"] == "captured_existing"


def test_new_observation_after_window_start_is_first_print_known() -> None:
    records = build_version_history(
        [
            _snapshot(SERIES_CPI, date(2024, 12, 10), {"2024-10-01": "314.686"}, "a"),
            _snapshot(
                SERIES_CPI,
                date(2024, 12, 12),
                {"2024-10-01": "314.686", "2024-11-01": "315.493"},
                "b",
            ),
        ]
    )
    november = [item for item in records if item["observation_date"] == "2024-11-01"]
    assert len(november) == 1
    assert november[0]["first_print_state"] == "known"
    assert november[0]["revision_type"] == "first_print"
    assert november[0]["publication_date"] == "2024-12-12"


def test_revision_is_append_only_with_delta() -> None:
    records = build_version_history(
        [
            _snapshot(SERIES_CPI, date(2024, 12, 12), {"2024-11-01": "315.493"}, "a"),
            _snapshot(SERIES_CPI, date(2025, 1, 15), {"2024-11-01": "315.600"}, "b"),
        ]
    )
    assert len(records) == 2
    assert records[1]["revision_index"] == 1
    assert records[1]["revision_type"] == "revision"
    assert records[1]["previous_value"] == "315.493"
    assert records[1]["revision_delta"] == "0.107"


def test_same_day_vintage_cannot_leak_into_intraday_t() -> None:
    records = build_version_history(
        [_snapshot(SERIES_DGS10, date(2025, 1, 6), {"2025-01-06": "4.61"})]
    )
    intraday = reconstruct_series_as_of(
        records, series_id=SERIES_DGS10, as_of=datetime(2025, 1, 6, 23, 59, tzinfo=UTC)
    )
    next_day = reconstruct_series_as_of(
        records, series_id=SERIES_DGS10, as_of=datetime(2025, 1, 7, 0, 0, tzinfo=UTC)
    )
    assert intraday["state"] == "unknown"
    assert next_day["state"] == "known"


def test_future_revision_does_not_change_earlier_reconstruction() -> None:
    records = build_version_history(
        [
            _snapshot(SERIES_CPI, date(2024, 12, 12), {"2024-11-01": "315.493"}, "a"),
            _snapshot(SERIES_CPI, date(2025, 1, 15), {"2024-11-01": "315.600"}, "b"),
        ]
    )
    before = reconstruct_series_as_of(
        records, series_id=SERIES_CPI, as_of=datetime(2025, 1, 10, tzinfo=UTC)
    )
    after = reconstruct_series_as_of(
        records, series_id=SERIES_CPI, as_of=datetime(2025, 1, 16, tzinfo=UTC)
    )
    assert before["fact"]["value"] == "315.493"
    assert after["fact"]["value"] == "315.6"
    assert before["fact"]["revision_index"] == 0
    assert after["fact"]["revision_index"] == 1


def test_version_history_is_deterministic_under_snapshot_reversal() -> None:
    snapshots = [
        _snapshot(SERIES_CPI, date(2024, 12, 10), {"2024-10-01": "314.686"}, "a"),
        _snapshot(
            SERIES_CPI,
            date(2024, 12, 12),
            {"2024-10-01": "314.686", "2024-11-01": "315.493"},
            "b",
        ),
    ]
    assert build_version_history(snapshots) == build_version_history(reversed(snapshots))


def test_rates_decomposition_is_mechanical_and_single_family() -> None:
    state = build_rates_macro_state(
        _rates_records(), as_of=datetime(2025, 1, 6, 12, tzinfo=UTC)
    )
    assert verify_rates_macro_state(state)
    assert state["derived"]["breakeven_10y"]["value"] == "2.5"
    assert state["derived"]["slope_2s10s"]["value"] == "0.35"
    assert state["official_breakeven_reference"]["derived_minus_official"] == "0"
    assert state["evidence_family"] == EVIDENCE_FAMILY
    assert state["independent_confirmation_units"] == 1
    assert state["components_not_independent"] is True


def test_stale_leg_mixing_is_forbidden_for_curve_derivation() -> None:
    state = build_rates_macro_state(
        _rates_records(dgs2_date="2025-01-02"),
        as_of=datetime(2025, 1, 6, 12, tzinfo=UTC),
    )
    assert state["derived"]["slope_2s10s"]["state"] == "unknown"
    assert state["derived"]["slope_2s10s"]["value"] is None


def test_real_yield_remains_context_only_and_j12_provisional() -> None:
    state = build_rates_macro_state(
        _rates_records(), as_of=datetime(2025, 1, 6, 12, tzinfo=UTC)
    )
    assert state["real_yield_role"] == "context_regime_only"
    assert state["directional_influence"] == REAL_YIELD_DIRECTIONAL_INFLUENCE
    assert state["predictive_edge_claimed"] is False
    assert state["trading_gate_created"] is False


def test_tampered_rates_state_is_rejected() -> None:
    state = build_rates_macro_state(
        _rates_records(), as_of=datetime(2025, 1, 6, 12, tzinfo=UTC)
    )
    tampered = deepcopy(state)
    tampered["independent_confirmation_units"] = 3
    assert not verify_rates_macro_state(tampered)


def test_context_v4_adds_one_rates_family_and_rehashes(monkeypatch: pytest.MonkeyPatch) -> None:
    as_of = datetime(2025, 1, 6, 12, tzinfo=UTC)
    rates = build_rates_macro_state(_rates_records(), as_of=as_of)

    def fake_v3(**kwargs: object) -> dict[str, object]:
        return {
            "context_packet_version": "aidy_market_context_v3_price_structure_feed_health",
            "as_of_utc": str(kwargs["as_of"].isoformat()),
            "symbol": kwargs["symbol"],
            "source_contract_versions": {},
            "context_hash": "old",
        }

    monkeypatch.setattr(context_v4, "build_context_packet_v3", fake_v3)
    packet = context_v4.build_context_packet_v4(
        as_of=as_of,
        symbol="XAUUSD",
        feature_packet={},
        price_structure_packet={},
        rates_macro_state=rates,
        event_rows=[],
        macro_evidence_state="known",
        cross_market_rows=[],
    )
    assert packet["rates_macro_context"]["independent_confirmation_units"] == 1
    assert context_v4.verify_context_hash_v4(packet)


def test_context_v4_rejects_different_rates_t(monkeypatch: pytest.MonkeyPatch) -> None:
    context_t = datetime(2025, 1, 6, 12, tzinfo=UTC)
    rates = build_rates_macro_state(
        _rates_records(), as_of=datetime(2025, 1, 6, 13, tzinfo=UTC)
    )

    monkeypatch.setattr(
        context_v4,
        "build_context_packet_v3",
        lambda **_: {
            "as_of_utc": context_t.isoformat(),
            "symbol": "XAUUSD",
            "source_contract_versions": {},
            "context_hash": "old",
        },
    )
    with pytest.raises(ValueError, match="share the same T"):
        context_v4.build_context_packet_v4(
            as_of=context_t,
            symbol="XAUUSD",
            feature_packet={},
            price_structure_packet={},
            rates_macro_state=rates,
            event_rows=[],
            macro_evidence_state="known",
            cross_market_rows=[],
        )
