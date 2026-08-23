from __future__ import annotations

import importlib.util
import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from aidy.context_packet_v7 import build_context_packet_v7, verify_context_hash_v7
from aidy.volatility_intelligence import (
    CBOE_GVZ_HISTORY_URL,
    GVZ_RECORD_VERSION,
    J7_J8_FOUNDATION_VERSION,
    MIN_INTRADAY_RETURNS_PER_DAY,
    VOLATILITY_INTELLIGENCE_VERSION,
    CboeGvzGateway,
    VolatilityIntelligenceError,
    build_j7_j8_foundation,
    build_volatility_state,
    parse_gvz_history_csv,
    select_gvz_as_of,
    select_gvz_research_anchor,
    verify_gvz_record,
    verify_j7_j8_foundation,
    verify_volatility_state,
)

_CSV = b"""DATE,GVZ
12/29/2025,18.50
12/30/2025,19.20
08/21/2026,23.92
"""
_OBSERVED = datetime(2026, 8, 23, 12, tzinfo=UTC)


def _gvz_records() -> list[dict[str, object]]:
    return parse_gvz_history_csv(
        _CSV,
        first_observed_at=_OBSERVED,
        source_last_modified_at="2026-08-22T20:00:00+00:00",
    )


def _research_row(
    *, timeframe: str, timestamp: datetime, close: Decimal
) -> dict[str, object]:
    return {
        "research_identity": f"{timeframe}:{timestamp.isoformat()}",
        "provenance_class": "retrospective_history",
        "pit_eligible": False,
        "symbol": "XAUUSD",
        "timeframe": timeframe,
        "open_time_utc": timestamp.isoformat(),
        "close": str(close),
    }


def _daily_rows() -> list[dict[str, object]]:
    start = date(2025, 11, 25)
    price = Decimal(4000)
    rows = []
    for index in range(36):
        price *= Decimal("1.003") if index % 3 else Decimal("0.998")
        rows.append(
            _research_row(
                timeframe="D1",
                timestamp=datetime.combine(start + timedelta(days=index), datetime.min.time(), UTC),
                close=price,
            )
        )
    return rows


def _intraday_rows(*, days: int = 21) -> list[dict[str, object]]:
    rows = []
    start = datetime(2025, 12, 10, tzinfo=UTC)
    price = Decimal(4200)
    for day_index in range(days):
        day_start = start + timedelta(days=day_index)
        for minute in range(MIN_INTRADAY_RETURNS_PER_DAY + 2):
            increment = Decimal("0.02")
            if day_index == days - 1 and minute == 150:
                increment = Decimal(30)
            price += increment
            rows.append(
                _research_row(
                    timeframe="M1",
                    timestamp=day_start + timedelta(minutes=minute),
                    close=price,
                )
            )
    return rows


def test_official_gvz_csv_preserves_snapshot_timing_proxy_and_digest() -> None:
    records = _gvz_records()
    assert [row["observation_date"] for row in records] == [
        "2025-12-29",
        "2025-12-30",
        "2026-08-21",
    ]
    assert records[-1]["gvz_record_version"] == GVZ_RECORD_VERSION
    assert records[-1]["underlying_proxy"] == "SPDR_Gold_Shares_ETF_GLD"
    assert records[-1]["implied_horizon_calendar_days"] == 30
    assert records[-1]["historical_release_time_known"] is False
    assert records[-1]["first_observed_at"] == _OBSERVED.isoformat()
    assert records[-1]["source_last_modified_at"] == "2026-08-22T20:00:00+00:00"
    assert all(verify_gvz_record(row) for row in records)


def test_gvz_parser_rejects_bad_host_columns_duplicates_and_values() -> None:
    with pytest.raises(ValueError, match="official HTTPS allowlist"):
        parse_gvz_history_csv(
            _CSV, first_observed_at=_OBSERVED, source_url="https://example.com/gvz.csv"
        )
    with pytest.raises(VolatilityIntelligenceError, match="required_columns"):
        parse_gvz_history_csv(b"DATE,CLOSE\n2026-01-01,20\n", first_observed_at=_OBSERVED)
    with pytest.raises(VolatilityIntelligenceError, match="duplicate"):
        parse_gvz_history_csv(
            b"DATE,GVZ\n2026-01-01,20\n2026-01-01,21\n",
            first_observed_at=_OBSERVED,
        )
    with pytest.raises(ValueError, match="finite positive"):
        parse_gvz_history_csv(
            b"DATE,GVZ\n2026-01-01,-1\n",
            first_observed_at=_OBSERVED,
        )


def test_gvz_pit_selection_filters_knowability_before_latest_observation() -> None:
    records = _gvz_records()
    assert select_gvz_as_of(records, as_of="2026-08-23T11:59:59+00:00") is None
    selected = select_gvz_as_of(records, as_of="2026-08-23T12:00:00+00:00")
    assert selected is not None
    assert selected["observation_date"] == "2026-08-21"


def test_gvz_research_anchor_is_explicitly_separate_from_pit_selection() -> None:
    selected = select_gvz_research_anchor(_gvz_records(), anchor_date="2025-12-30")
    assert selected is not None
    assert selected["observation_date"] == "2025-12-30"


def test_gvz_digest_tampering_is_rejected() -> None:
    record = _gvz_records()[-1]
    record["value"] = "99"
    assert not verify_gvz_record(record)
    with pytest.raises(ValueError, match="Invalid GVZ"):
        select_gvz_as_of([record], as_of=_OBSERVED)


def test_gateway_uses_official_redirect_and_http_last_modified() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == CBOE_GVZ_HISTORY_URL
        return httpx.Response(
            200,
            content=_CSV,
            headers={"last-modified": "Sat, 22 Aug 2026 20:00:00 GMT"},
            request=request,
        )

    records = CboeGvzGateway(transport=httpx.MockTransport(handler)).fetch_history(
        first_observed_at=_OBSERVED
    )
    assert len(records) == 3
    assert records[-1]["source_last_modified_at"] == "2026-08-22T20:00:00+00:00"


def test_gateway_fails_closed_on_http_error_and_off_allowlist_redirect() -> None:
    gateway = CboeGvzGateway(
        transport=httpx.MockTransport(lambda request: httpx.Response(403, request=request))
    )
    with pytest.raises(VolatilityIntelligenceError, match="http_403"):
        gateway.fetch_history(first_observed_at=_OBSERVED)

    def redirect(request: httpx.Request) -> httpx.Response:
        if request.url.host == "example.com":
            return httpx.Response(200, content=_CSV, request=request)
        return httpx.Response(302, headers={"location": "https://example.com/fake.csv"}, request=request)

    with pytest.raises(ValueError, match="official HTTPS allowlist"):
        CboeGvzGateway(transport=httpx.MockTransport(redirect)).fetch_history(
            first_observed_at=_OBSERVED
        )


def test_realized_term_structure_jump_split_and_vol_of_vol_are_deterministic() -> None:
    state = build_volatility_state(
        as_of=_OBSERVED,
        gvz_record=select_gvz_research_anchor(_gvz_records(), anchor_date="2025-12-30"),
        daily_candles=_daily_rows(),
        intraday_candles=_intraday_rows(),
        mode="retrospective_research",
        anchor_date="2025-12-30",
    )
    repeat = build_volatility_state(
        as_of=_OBSERVED,
        gvz_record=select_gvz_research_anchor(_gvz_records(), anchor_date="2025-12-30"),
        daily_candles=_daily_rows(),
        intraday_candles=_intraday_rows(),
        mode="retrospective_research",
        anchor_date="2025-12-30",
    )
    assert state == repeat
    assert verify_volatility_state(state)
    assert state["state"] == "known"
    assert all(
        state["realized_volatility"]["annualized_percent"][str(horizon)] is not None
        for horizon in (5, 10, 21)
    )
    assert state["jump_continuous"]["known_daily_decomposition_count"] == 21
    assert state["jump_continuous"]["jump_share"] is not None
    assert state["vol_of_vol"]["state"] == "known"


def test_iv_rv_comparison_carries_instrument_and_horizon_caveats() -> None:
    state = build_volatility_state(
        as_of=_OBSERVED,
        gvz_record=select_gvz_research_anchor(_gvz_records(), anchor_date="2025-12-30"),
        daily_candles=_daily_rows(),
        intraday_candles=_intraday_rows(),
        mode="retrospective_research",
        anchor_date="2025-12-30",
    )
    comparison = state["iv_minus_rv"]
    assert comparison["cross_instrument_proxy"] is True
    assert comparison["iv_underlying"] == "GLD"
    assert comparison["rv_underlying"] == "XAUUSD"
    assert comparison["iv_horizon_calendar_days"] == 30
    assert comparison["rv_horizon_trading_days"] == 21
    assert comparison["spread_percentage_points"] is not None


def test_current_pit_state_keeps_missing_xauusd_volatility_unknown() -> None:
    state = build_volatility_state(
        as_of=_OBSERVED,
        gvz_record=select_gvz_as_of(_gvz_records(), as_of=_OBSERVED),
        daily_candles=[],
        intraday_candles=[],
        mode="pit",
    )
    assert verify_volatility_state(state)
    assert state["state"] == "partial"
    assert state["gvz"]["state"] == "known"
    assert state["realized_volatility"]["state"] == "unknown_insufficient_daily_history"
    assert state["jump_continuous"]["state"] == "unknown_insufficient_intraday_coverage"
    assert state["iv_minus_rv"]["spread_percentage_points"] is None
    assert state["decision_input_allowed"] is True


def test_retrospective_state_is_evaluation_only_and_pit_rejects_it() -> None:
    state = build_volatility_state(
        as_of=_OBSERVED,
        gvz_record=select_gvz_research_anchor(_gvz_records(), anchor_date="2025-12-30"),
        daily_candles=_daily_rows(),
        intraday_candles=[],
        mode="retrospective_research",
        anchor_date="2025-12-30",
    )
    assert state["evaluation_only"] is True
    assert state["decision_input_allowed"] is False
    assert state["pit_reconstructable"] is False
    with pytest.raises(ValueError, match="Retrospective candles"):
        build_volatility_state(
            as_of=_OBSERVED,
            gvz_record=select_gvz_as_of(_gvz_records(), as_of=_OBSERVED),
            daily_candles=_daily_rows(),
            intraday_candles=[],
            mode="pit",
        )


def test_incomplete_intraday_days_are_not_extrapolated() -> None:
    state = build_volatility_state(
        as_of=_OBSERVED,
        gvz_record=select_gvz_research_anchor(_gvz_records(), anchor_date="2025-12-30"),
        daily_candles=_daily_rows(),
        intraday_candles=_intraday_rows(days=1)[:100],
        mode="retrospective_research",
        anchor_date="2025-12-30",
    )
    assert state["jump_continuous"]["known_daily_decomposition_count"] == 0
    assert state["jump_continuous"]["jump_share"] is None
    assert state["vol_of_vol"]["state"] == "unknown_insufficient_history"


def test_state_digest_rejects_predictive_or_gate_tampering() -> None:
    state = build_volatility_state(
        as_of=_OBSERVED,
        gvz_record=select_gvz_as_of(_gvz_records(), as_of=_OBSERVED),
        daily_candles=[],
        intraday_candles=[],
        mode="pit",
    )
    state["predictive_edge_claimed"] = True
    assert not verify_volatility_state(state)


def test_j7_j8_foundation_freezes_inputs_without_running_formal_test() -> None:
    foundation = build_j7_j8_foundation()
    assert verify_j7_j8_foundation(foundation)
    assert foundation["foundation_version"] == J7_J8_FOUNDATION_VERSION
    assert foundation["formal_test_day"] == 43
    assert foundation["j7"]["formal_test_run"] is False
    assert foundation["j8"]["formal_test_run"] is False
    assert foundation["insufficient_or_null_result_allowed"] is True
    assert foundation["threshold_tuning_on_evaluation_set_allowed"] is False


def test_context_v7_covers_pit_state_and_rejects_research_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pit_state = build_volatility_state(
        as_of=_OBSERVED,
        gvz_record=select_gvz_as_of(_gvz_records(), as_of=_OBSERVED),
        daily_candles=[],
        intraday_candles=[],
        mode="pit",
    )

    def fake_v6(**kwargs: object) -> dict[str, object]:
        return {
            "as_of_utc": str(kwargs["as_of"]),
            "context_packet_version": "v6",
            "source_contract_versions": {"cme_contract_intelligence": "v1"},
            "context_hash": "old",
        }

    monkeypatch.setattr("aidy.context_packet_v7.build_context_packet_v6", fake_v6)
    packet = build_context_packet_v7(
        as_of=_OBSERVED.isoformat(),
        symbol="XAUUSD",
        feature_packet={},
        price_structure_packet={},
        rates_macro_state={},
        event_intelligence_state={},
        cme_contract_state={},
        volatility_state=pit_state,
        event_rows=[],
        macro_evidence_state="unknown",
        cross_market_rows=[],
    )
    assert verify_context_hash_v7(packet)
    assert packet["source_contract_versions"]["volatility_intelligence"] == (
        VOLATILITY_INTELLIGENCE_VERSION
    )
    research_state = build_volatility_state(
        as_of=_OBSERVED,
        gvz_record=select_gvz_research_anchor(_gvz_records(), anchor_date="2025-12-30"),
        daily_candles=_daily_rows(),
        intraday_candles=[],
        mode="retrospective_research",
        anchor_date="2025-12-30",
    )
    with pytest.raises(ValueError, match="Retrospective"):
        build_context_packet_v7(
            as_of=_OBSERVED.isoformat(),
            symbol="XAUUSD",
            feature_packet={},
            price_structure_packet={},
            rates_macro_state={},
            event_intelligence_state={},
            cme_contract_state={},
            volatility_state=research_state,
            event_rows=[],
            macro_evidence_state="unknown",
            cross_market_rows=[],
        )


def test_context_v7_requires_same_timestamp(monkeypatch: pytest.MonkeyPatch) -> None:
    state = build_volatility_state(
        as_of=_OBSERVED,
        gvz_record=select_gvz_as_of(_gvz_records(), as_of=_OBSERVED),
        daily_candles=[],
        intraday_candles=[],
        mode="pit",
    )
    monkeypatch.setattr(
        "aidy.context_packet_v7.build_context_packet_v6",
        lambda **kwargs: {"as_of_utc": "2026-08-24T00:00:00+00:00"},
    )
    with pytest.raises(ValueError, match="share the same T"):
        build_context_packet_v7(
            as_of=_OBSERVED.isoformat(),
            symbol="XAUUSD",
            feature_packet={},
            price_structure_packet={},
            rates_macro_state={},
            event_intelligence_state={},
            cme_contract_state={},
            volatility_state=state,
            event_rows=[],
            macro_evidence_state="unknown",
            cross_market_rows=[],
        )


def _acceptance_module() -> object:
    spec = importlib.util.spec_from_file_location(
        "day31_volatility_acceptance", "scripts/day31_volatility_acceptance.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_acceptance_reuses_only_verified_cached_official_capture(tmp_path: Path) -> None:
    acceptance = _acceptance_module()
    records = _gvz_records()
    (tmp_path / "gvz_observations.jsonl").write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in records),
        encoding="utf-8",
    )
    (tmp_path / "capture_transport.json").write_text(
        json.dumps({"transport": "official_https"}), encoding="utf-8"
    )
    captured, transport = acceptance._capture_gvz(tmp_path, _OBSERVED.isoformat())
    assert captured == records
    assert transport == "official_https"


def test_acceptance_contract_uses_day30_signed_base_and_four_new_tables() -> None:
    acceptance = _acceptance_module()
    assert acceptance.BASE_SHA == "a380932a2ad7ca0a26538c0b2fa2e846f0c77864"
    assert {
        acceptance.GVZ_TABLE,
        acceptance.STATE_TABLE,
        acceptance.FOUNDATION_TABLE,
        acceptance.SUMMARY_TABLE,
    } == {
        "research_day31_gvz_observations",
        "research_day31_volatility_state",
        "research_day31_j7_j8_foundation",
        "research_day31_summary",
    }
