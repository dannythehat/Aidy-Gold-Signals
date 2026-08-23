from __future__ import annotations

import importlib.util
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from pathlib import Path

import pytest

from aidy.cme_contract_intelligence import (
    CME_CONTRACT_INTELLIGENCE_VERSION,
    J6_QUADRANTS,
    CmeContractError,
    build_contract_calendar_observation,
    build_contract_roll_state,
    build_daily_contract_records,
    parse_cme_gold_bulletin_text,
    parse_cme_gold_official_json,
    parse_gold_calendar_table,
    run_j6_descriptive,
    select_daily_contract_records_as_of,
    verify_contract_roll_state,
    verify_daily_contract_record,
    verify_j6_study,
)
from aidy.context_packet_v6 import build_context_packet_v6, verify_context_hash_v6

_BULLETIN = """
PG62 BULLETIN # 166@ Fri, Aug 21, 2026 CME GROUP
PRELIMINARY
GC FUT COMEX GOLD FUTURES
AUG26 4310.00 4320.00 4300.00 4315.00 + 107.80 120 1000 + 10
SEP26 4320.00 4330.00 4310.00 4325.00 - 5.00 90 800 - 20
DEC26 4380.00 4400.00 4370.00 4390.00 + 109.20 5000 180000 + 3082
TOTAL GC FUT 5210 181800 + 3072
""".strip()


def _records(
    *, observed: datetime = datetime(2026, 8, 22, 6, tzinfo=UTC), final: bool = False
) -> list[dict[str, object]]:
    text = _BULLETIN.replace("PRELIMINARY", "FINAL") if final else _BULLETIN
    snapshot = parse_cme_gold_bulletin_text(
        text,
        source_bytes=(b"%PDF-test-final" if final else b"%PDF-test-preliminary"),
        first_observed_at=observed,
    )
    return build_daily_contract_records(snapshot)


def _calendar(
    code: str,
    month: str,
    first_notice: str,
    *,
    observed: datetime = datetime(2026, 8, 22, 6, tzinfo=UTC),
) -> dict[str, object]:
    return build_contract_calendar_observation(
        contract_code=code,
        contract_month=month,
        first_notice_date=first_notice,
        last_trade_date="2026-08-27" if code == "GCQ26" else "2026-12-29",
        first_delivery_date=None,
        last_delivery_date=None,
        first_observed_at=observed,
        source_document_sha256="a" * 64,
    )


def test_realistic_cme_bulletin_text_yields_contract_settlement_and_daily_oi() -> None:
    records = _records()
    assert [row["contract_code"] for row in records] == ["GCQ26", "GCU26", "GCZ26"]
    assert records[0]["settlement"] == "4315"
    assert records[0]["settlement_change"] == "107.8"
    assert records[1]["open_interest_change"] == -20
    assert records[2]["settlement_change_bps"] == "255.092506073631096991216595"
    assert all(verify_daily_contract_record(row) for row in records)
    assert all(row["open_interest_frequency"] == "daily_t_plus_1" for row in records)
    assert all(row["intraday_open_interest_inferred"] is False for row in records)


def test_bulletin_rejects_missing_header_section_and_official_host() -> None:
    with pytest.raises(CmeContractError, match="header"):
        parse_cme_gold_bulletin_text(
            "GC FUT COMEX GOLD FUTURES",
            source_bytes=b"x",
            first_observed_at="2026-08-22T00:00:00+00:00",
        )
    with pytest.raises(CmeContractError, match="section"):
        parse_cme_gold_bulletin_text(
            "PG62 BULLETIN # 1@ Fri, Aug 21, 2026 PRELIMINARY",
            source_bytes=b"x",
            first_observed_at="2026-08-22T00:00:00+00:00",
        )
    with pytest.raises(ValueError, match="official HTTPS allowlist"):
        parse_cme_gold_bulletin_text(
            _BULLETIN,
            source_bytes=b"x",
            first_observed_at="2026-08-22T00:00:00+00:00",
            source_url="https://example.com/fake.pdf",
        )


def test_official_json_bundle_joins_settlement_with_final_daily_open_interest() -> None:
    settlements = {
        "tradeDate": "08/21/2026",
        "reportType": "Final",
        "empty": False,
        "settlements": [
            {
                "month": "DEC 26",
                "change": "+109.2",
                "settle": "4680.6",
            }
        ],
    }
    volume = {
        "tradeDate": "20260821",
        "updateTime": "2026-08-22T05:20:07.000Z",
        "empty": False,
        "monthData": [
            {
                "month": "DEC 2026",
                "atClose": "328,666",
                "change": "3,082",
            }
        ],
    }
    snapshot = parse_cme_gold_official_json(
        settlements,
        volume,
        first_observed_at="2026-08-23T12:00:00+00:00",
        settlements_url=(
            "https://www.cmegroup.com/CmeWS/mvc/Settlements/Futures/Settlements/"
            "437/FUT?tradeDate=08/21/2026"
        ),
        volume_url=(
            "https://www.cmegroup.com/CmeWS/mvc/Volume/Details/F/437/20260821/P"
        ),
    )
    assert snapshot.publication_state == "final"
    assert snapshot.bulletin_number is None
    assert snapshot.official_published_at == datetime(2026, 8, 22, 5, 20, 7, tzinfo=UTC)
    assert snapshot.rows[0].contract_code == "GCZ26"
    assert snapshot.rows[0].open_interest == 328666
    assert snapshot.rows[0].open_interest_change == 3082
    records = build_daily_contract_records(snapshot)
    assert records[0]["official_published_at"] == "2026-08-22T05:20:07+00:00"
    assert verify_daily_contract_record(records[0])


def test_official_json_bundle_rejects_nonfinal_and_mismatched_trade_dates() -> None:
    settlements = {
        "tradeDate": "08/21/2026",
        "reportType": "Preliminary",
        "empty": False,
        "settlements": [],
    }
    volume = {
        "tradeDate": "20260820",
        "updateTime": "2026-08-22T05:20:07+00:00",
        "empty": False,
        "monthData": [],
    }
    with pytest.raises(CmeContractError, match="trade_date_disagreement"):
        parse_cme_gold_official_json(
            settlements,
            volume,
            first_observed_at="2026-08-23T12:00:00+00:00",
            settlements_url=(
                "https://www.cmegroup.com/CmeWS/mvc/Settlements/Futures/Settlements/437/FUT"
            ),
            volume_url=(
                "https://www.cmegroup.com/CmeWS/mvc/Volume/Details/F/437/20260820/P"
            ),
        )
def test_pit_selection_excludes_future_observations_and_prefers_final_revision() -> None:
    preliminary = _records()
    final = _records(observed=datetime(2026, 8, 22, 16, tzinfo=UTC), final=True)
    early = select_daily_contract_records_as_of(
        [*preliminary, *final], as_of="2026-08-22T12:00:00+00:00"
    )
    late = select_daily_contract_records_as_of(
        [*preliminary, *final], as_of="2026-08-22T18:00:00+00:00"
    )
    assert {row["publication_state"] for row in early} == {"preliminary"}
    assert {row["publication_state"] for row in late} == {"final"}


def test_record_digest_tampering_is_rejected() -> None:
    record = _records()[0]
    record["open_interest"] = 999999
    assert not verify_daily_contract_record(record)
    with pytest.raises(ValueError, match="Invalid CME daily"):
        select_daily_contract_records_as_of(
            [record], as_of="2026-08-23T00:00:00+00:00"
        )


def test_public_calendar_table_preserves_contract_dates_and_source_digest() -> None:
    table = [
        ["Gold Futures"],
        [
            "Product Code",
            "First Trade",
            "Last Trade",
            "First Notice",
            "Last Notice",
            "First Delivery",
            "Last Delivery",
        ],
        [
            "GCQ26",
            "30 Sep 2024",
            "27 Aug 2026",
            "31 Jul 2026",
            "28 Aug 2026",
            "03 Aug 2026",
            "31 Aug 2026",
        ],
        [
            "GCZ26",
            "31 Dec 2020",
            "29 Dec 2026",
            "27 Nov 2026",
            "30 Dec 2026",
            "01 Dec 2026",
            "31 Dec 2026",
        ],
    ]
    rows = parse_gold_calendar_table(
        table,
        first_observed_at="2026-08-23T00:00:00+00:00",
        source_document_sha256=sha256(b"official-xls").hexdigest(),
    )
    assert [row["contract_code"] for row in rows] == ["GCQ26", "GCZ26"]
    assert rows[0]["first_notice_date"] == "2026-07-31"
    assert rows[0]["last_delivery_date"] == "2026-08-31"


def test_calendar_code_month_disagreement_is_rejected() -> None:
    with pytest.raises(ValueError, match="disagree"):
        _calendar("GCZ26", "2026-08-01", "2026-07-31")


def test_roll_state_distinguishes_nearest_listed_from_liquidity_leader() -> None:
    state = build_contract_roll_state(
        as_of="2026-08-23T00:00:00+00:00",
        daily_records=_records(),
        calendar_records=[_calendar("GCQ26", "2026-08-01", "2026-07-31")],
    )
    assert verify_contract_roll_state(state)
    assert state["front_month_contract"] == "GCQ26"
    assert state["second_listed_contract"] == "GCU26"
    assert state["active_contract"] == "GCZ26"
    assert state["roll_state"] == "post_first_notice_active_shifted"
    assert state["days_to_first_notice_business"] == 0
    assert state["predictive_edge_claimed"] is False


def test_roll_state_is_partial_unknown_without_pit_calendar() -> None:
    state = build_contract_roll_state(
        as_of="2026-08-23T00:00:00+00:00",
        daily_records=_records(),
        calendar_records=[],
    )
    assert state["state"] == "partial_unknown_calendar"
    assert state["roll_state"] == "unknown_contract_calendar"
    assert state["pit_reconstructable"] is False


def test_roll_state_is_unknown_without_observed_daily_bulletin() -> None:
    state = build_contract_roll_state(
        as_of="2026-08-21T00:00:00+00:00",
        daily_records=_records(),
        calendar_records=[],
    )
    assert state["state"] == "unknown_no_daily_bulletin"
    assert verify_contract_roll_state(state)


def _episode(quadrant: str, index: int) -> dict[str, object]:
    price_up = quadrant.startswith("price_up")
    oi_up = quadrant.endswith("oi_up")
    day = date(2026, 1, 1) + timedelta(days=index)
    return {
        "trade_date": day.isoformat(),
        "contract_code": "GCG26",
        "price_change_bps": "10" if price_up else "-10",
        "open_interest_change": 100 if oi_up else -100,
        "trend_state": "up" if index % 2 else "down",
        "market_structure_epoch": "post_2022_pre_1oz_24x7",
        "roll_state": "clear",
        "next_return_bps": {
            "1": "2" if price_up else "-2",
            "3": "3" if price_up else "-3",
            "5": "4" if price_up else "-4",
        },
    }


def test_j6_reports_all_quadrants_horizons_and_controls_without_edge_claim() -> None:
    episodes = [
        _episode(quadrant, index + quadrant_index * 40)
        for quadrant_index, quadrant in enumerate(J6_QUADRANTS)
        for index in range(30)
    ]
    study = run_j6_descriptive(episodes)
    assert verify_j6_study(study)
    assert study["independent_daily_episode_count"] == 120
    for result in study["quadrant_results"].values():
        assert result["independent_daily_episode_n"] == 30
        assert set(result["horizons"]) == {"1", "3", "5"}
        assert all(item["state"] == "descriptive" for item in result["horizons"].values())
        assert set(result["trend_strata"]) == {"down", "up"}
        assert all(
            set(stratum["horizons"]) == {"1", "3", "5"}
            for stratum in result["trend_strata"].values()
        )
    assert study["trend_control_reported"] is True
    assert study["market_structure_epoch_reported"] is True
    assert study["predictive_edge_claimed"] is False
    assert study["trading_gate_created"] is False


def test_j6_sparse_and_missing_future_outcomes_remain_insufficient() -> None:
    episode = _episode("price_up_oi_up", 0)
    episode["next_return_bps"] = {"1": None, "3": None, "5": None}
    study = run_j6_descriptive([episode])
    result = study["quadrant_results"]["price_up_oi_up"]
    assert result["independent_daily_episode_n"] == 1
    assert all(item["known_n"] == 0 for item in result["horizons"].values())
    assert all(item["state"] == "insufficient" for item in result["horizons"].values())


def test_j6_excludes_neutral_rows_and_rejects_conflicting_duplicates() -> None:
    neutral = _episode("price_up_oi_up", 0)
    neutral["open_interest_change"] = 0
    study = run_j6_descriptive([neutral])
    assert study["neutral_episode_count_excluded"] == 1
    first = _episode("price_up_oi_up", 1)
    conflict = dict(first)
    conflict["open_interest_change"] = -100
    with pytest.raises(ValueError, match="Conflicting rows"):
        run_j6_descriptive([first, conflict])


def test_j6_rejects_trade_pnl_and_inferred_intent() -> None:
    for field in ("pnl", "win_rate", "trader_intent"):
        episode = _episode("price_up_oi_up", 0)
        episode[field] = "forbidden"
        with pytest.raises(ValueError, match="trade P/L"):
            run_j6_descriptive([episode])


def test_context_v6_covers_verified_contract_state_and_same_t(monkeypatch: pytest.MonkeyPatch) -> None:
    as_of = "2026-08-23T00:00:00+00:00"
    state = build_contract_roll_state(
        as_of=as_of,
        daily_records=_records(),
        calendar_records=[_calendar("GCQ26", "2026-08-01", "2026-07-31")],
    )

    def fake_v5(**kwargs: object) -> dict[str, object]:
        return {
            "as_of_utc": str(kwargs["as_of"]),
            "context_packet_version": "v5",
            "source_contract_versions": {"macro_event_intelligence": "v2"},
            "context_hash": "old",
        }

    monkeypatch.setattr("aidy.context_packet_v6.build_context_packet_v5", fake_v5)
    packet = build_context_packet_v6(
        as_of=as_of,
        symbol="XAUUSD",
        feature_packet={},
        price_structure_packet={},
        rates_macro_state={},
        event_intelligence_state={},
        cme_contract_state=state,
        event_rows=[],
        macro_evidence_state="unknown",
        cross_market_rows=[],
    )
    assert verify_context_hash_v6(packet)
    assert packet["source_contract_versions"]["cme_contract_intelligence"] == (
        CME_CONTRACT_INTELLIGENCE_VERSION
    )
    tampered = dict(packet)
    tampered["cme_contract_context"] = dict(state, active_contract="GCQ26")
    assert not verify_context_hash_v6(tampered)


def test_context_v6_rejects_mismatched_as_of(monkeypatch: pytest.MonkeyPatch) -> None:
    state = build_contract_roll_state(
        as_of="2026-08-23T00:00:00+00:00", daily_records=[], calendar_records=[]
    )

    monkeypatch.setattr(
        "aidy.context_packet_v6.build_context_packet_v5",
        lambda **kwargs: {"as_of_utc": "2026-08-24T00:00:00+00:00"},
    )
    with pytest.raises(ValueError, match="share the same T"):
        build_context_packet_v6(
            as_of="2026-08-23T00:00:00+00:00",
            symbol="XAUUSD",
            feature_packet={},
            price_structure_packet={},
            rates_macro_state={},
            event_intelligence_state={},
            cme_contract_state=state,
            event_rows=[],
            macro_evidence_state="unknown",
            cross_market_rows=[],
        )


def test_acceptance_uses_verified_seed_when_cloud_ip_is_blocked(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    spec = importlib.util.spec_from_file_location(
        "day30_cme_contract_acceptance", "scripts/day30_cme_contract_acceptance.py"
    )
    assert spec is not None and spec.loader is not None
    acceptance = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(acceptance)

    class BlockedGateway:
        def fetch_current(self, **kwargs: object) -> object:
            raise CmeContractError("cme_bulletin_http_403")

    monkeypatch.setattr(acceptance, "CmePublicBulletinGateway", BlockedGateway)
    daily, calendar, transport = acceptance._capture_sources(
        tmp_path, "2026-08-23T12:30:00+00:00"
    )
    assert len(daily) == 28
    assert len(calendar) == 35
    assert transport == "checked_in_verified_official_capture"
    assert all(verify_daily_contract_record(row) for row in daily)
