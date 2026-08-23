from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from aidy.historical_spread import (
    BASELINE_VERSION,
    HistDataTickPeriod,
    MinuteQuote,
    Tick,
    TickArchiveMeta,
    build_case_covariates,
    build_spread_baseline,
    collapse_to_minute_quotes,
    freeze_j3_strata,
    parse_tick_fields,
    run_j3,
    verify_j3,
    verify_j3_strata,
    verify_spread_baseline,
)


def _quote(
    minute: datetime,
    *,
    bid: str,
    ask: str,
    tick_offset_seconds: int = 50,
    suffix: str = "a",
) -> MinuteQuote:
    return MinuteQuote(
        minute_utc=minute,
        source_tick_time_utc=minute + timedelta(seconds=tick_offset_seconds),
        bid=Decimal(bid),
        ask=Decimal(ask),
        source_file=f"file-{suffix}.zip",
        source_file_sha256=(suffix * 64)[:64],
        source_payload_sha256=((suffix.upper() or "B") * 64)[:64],
        ingested_at=datetime(2026, 8, 23, 6, 0, tzinfo=UTC),
    )


def _baseline_quotes() -> list[MinuteQuote]:
    # All four dates are Mondays and all observations are in UTC slot 56 (14:00-14:14).
    return [
        _quote(datetime(2024, 12, 2, 14, 0, tzinfo=UTC), bid="100", ask="100.02", suffix="a"),
        _quote(datetime(2024, 12, 9, 14, 0, tzinfo=UTC), bid="100", ask="100.04", suffix="b"),
        _quote(datetime(2024, 12, 16, 14, 0, tzinfo=UTC), bid="100", ask="100.03", suffix="c"),
        _quote(datetime(2024, 12, 23, 14, 0, tzinfo=UTC), bid="100", ask="100.05", suffix="d"),
    ]


def _case(
    case_id: str,
    *,
    as_of: datetime,
    atr: str,
    session: str = "london",
    outcome_scale: str = "1",
) -> dict[str, object]:
    scale = Decimal(outcome_scale)
    return {
        "case_id": case_id,
        "as_of_utc": as_of.isoformat(),
        "input_boundary": {
            "feature": {"summary": {"H1": {"atr_14_bps": atr}}},
            "setup": {
                "detector_state": "single",
                "candidate_setup_ids": ["setup_x"],
            },
            "regime": {"labels": {"session": session}},
            "normalized_trade_spec": {
                "entry": "100",
                "stop_loss": "99",
                "targets": ["101", "102"],
            },
        },
        "future_evaluation": {
            "trade_outcome_bundle": {
                "outcomes": [
                    {
                        "coverage_state": "complete",
                        "horizon_minutes": 15,
                        "metrics": {
                            "mfe_r": str(scale),
                            "mae_r": str(scale / Decimal(2)),
                        },
                    },
                    {
                        "coverage_state": "complete",
                        "horizon_minutes": 60,
                        "metrics": {
                            "mfe_r": str(scale * Decimal(2)),
                            "mae_r": str(scale),
                        },
                    },
                    {
                        "coverage_state": "complete",
                        "horizon_minutes": 240,
                        "metrics": {
                            "mfe_r": str(scale * Decimal(3)),
                            "mae_r": str(scale * Decimal("1.5")),
                        },
                    },
                ]
            }
        },
    }


def test_tick_timestamp_fixed_est_converts_to_utc() -> None:
    tick = parse_tick_fields("20250106 090000123", "2640.10", "2640.30")
    assert tick.source_tick_time_utc == datetime(2025, 1, 6, 14, 0, 0, 123000, tzinfo=UTC)
    assert tick.bid == Decimal("2640.10")
    assert tick.ask == Decimal("2640.30")


def test_spread_is_derived_from_genuine_bid_and_ask() -> None:
    tick = parse_tick_fields("20250106 090000000", "100", "100.04")
    assert tick.spread == Decimal("0.04")
    assert tick.mid == Decimal("100.02")
    assert tick.spread_bps == Decimal("0.04") / Decimal("100.02") * Decimal(10000)


def test_ask_below_bid_fails_closed() -> None:
    with pytest.raises(ValueError, match="ask cannot be below bid"):
        parse_tick_fields("20250106 090000000", "100.05", "100.04")


def test_collapse_uses_last_genuine_tick_per_minute_and_no_volume_fields() -> None:
    meta = TickArchiveMeta(
        source_file="ticks.zip",
        source_file_sha256="a" * 64,
        payload_name="ticks.csv",
        source_payload_sha256="b" * 64,
    )
    ticks = [
        Tick(datetime(2025, 1, 6, 14, 0, 10, tzinfo=UTC), Decimal("100"), Decimal("100.02")),
        Tick(datetime(2025, 1, 6, 14, 0, 50, tzinfo=UTC), Decimal("100.01"), Decimal("100.04")),
        Tick(datetime(2025, 1, 6, 14, 1, 20, tzinfo=UTC), Decimal("100.02"), Decimal("100.05")),
    ]
    quotes, manifest = collapse_to_minute_quotes(
        ticks,
        meta=meta,
        ingested_at=datetime(2026, 8, 23, 6, 0, tzinfo=UTC),
    )
    assert len(quotes) == 2
    assert quotes[0].source_tick_time_utc == datetime(2025, 1, 6, 14, 0, 50, tzinfo=UTC)
    assert quotes[0].bid == Decimal("100.01")
    assert quotes[0].ask == Decimal("100.04")
    row = quotes[0].to_row()
    forbidden = {"volume", "depth", "order_flow", "tick_volume", "true_exchange_volume"}
    assert not (forbidden & set(row))
    assert manifest["raw_bid_ask_preserved"] is True
    assert manifest["depth_included"] is False
    assert manifest["true_exchange_volume_claimed"] is False
    assert manifest["order_flow_claimed"] is False
    assert not (forbidden & set(manifest))


def test_histdata_period_is_deterministic() -> None:
    period = HistDataTickPeriod(2024, 12)
    assert period.key == "202412"
    assert period.referer.endswith("/xauusd/2024/12")
    assert period.cache_name.endswith("202412.zip")


def test_baseline_is_deterministic_under_input_reversal() -> None:
    quotes = _baseline_quotes()
    forward = build_spread_baseline(quotes, min_bucket_n=2)
    reverse = build_spread_baseline(reversed(quotes), min_bucket_n=2)
    assert forward == reverse
    assert verify_spread_baseline(forward)
    assert forward["baseline_version"] == BASELINE_VERSION
    assert forward["outcome_fields_used"] is False


def test_baseline_uses_matched_weekday_and_15_minute_slot() -> None:
    baseline = build_spread_baseline(_baseline_quotes(), min_bucket_n=2)
    matched = baseline["groups"]["0:56"]
    assert matched["weekday_utc"] == 0
    assert matched["clock_slot_15m"] == 56
    assert matched["state"] == "known"
    assert matched["sample_n"] == 4


def test_baseline_bucket_with_too_few_rows_is_insufficient() -> None:
    baseline = build_spread_baseline(_baseline_quotes()[:1], min_bucket_n=2)
    assert baseline["groups"]["0:56"]["state"] == "insufficient"
    assert baseline["groups"]["0:56"]["mean_spread_bps"] is None
    assert baseline["groups"]["0:56"]["std_spread_bps"] is None


def test_future_quote_is_never_used_for_anchor_and_missing_stays_unknown() -> None:
    baseline = build_spread_baseline(_baseline_quotes(), min_bucket_n=2)
    as_of = datetime(2025, 1, 6, 14, 1, tzinfo=UTC)
    future_only = _quote(
        datetime(2025, 1, 6, 14, 1, tzinfo=UTC),
        bid="100",
        ask="100.06",
        tick_offset_seconds=30,
        suffix="e",
    )
    covariate = build_case_covariates(
        [_case("case-a", as_of=as_of, atr="20")],
        [future_only],
        baseline,
    )[0]
    assert covariate["state"] == "unknown"
    assert covariate["quote_identity"] is None
    assert covariate["future_evaluation_read"] is False


def test_case_covariates_are_input_only_even_if_future_outcomes_change() -> None:
    baseline = build_spread_baseline(_baseline_quotes(), min_bucket_n=2)
    as_of = datetime(2025, 1, 6, 14, 1, tzinfo=UTC)
    january_quote = _quote(
        datetime(2025, 1, 6, 14, 0, tzinfo=UTC),
        bid="100",
        ask="100.06",
        suffix="e",
    )
    original = _case("case-a", as_of=as_of, atr="20")
    changed = deepcopy(original)
    changed["future_evaluation"] = {"anything": "completely different"}
    first = build_case_covariates([original], [january_quote], baseline)[0]
    second = build_case_covariates([changed], [january_quote], baseline)[0]
    assert first == second
    assert first["state"] == "known"
    assert first["spread_z"] is not None


def test_strata_are_deterministic_and_frozen_without_outcomes() -> None:
    covariates = [
        {
            "case_id": f"case-{index}",
            "as_of_utc": f"2025-01-06T{index:02d}:00:00+00:00",
            "state": "known",
            "spread_z": str(index),
            "h1_atr_14_bps": str(10 + index),
            "outcome_geometry_available": True,
            "session": "london",
            "baseline_digest": "b" * 64,
        }
        for index in range(6)
    ]
    forward = freeze_j3_strata(covariates)
    reverse = freeze_j3_strata(reversed(covariates))
    assert forward == reverse
    assert verify_j3_strata(forward)
    assert forward["future_outcomes_used_for_strata"] is False
    assert [item["spread_tercile"] for item in forward["assignments"]].count("low") == 2
    assert [item["spread_tercile"] for item in forward["assignments"]].count("mid") == 2
    assert [item["spread_tercile"] for item in forward["assignments"]].count("high") == 2


def test_j3_reports_mfe_mae_by_horizon_volatility_and_spread_without_gate() -> None:
    cases = [
        _case(
            f"case-{index}",
            as_of=datetime(2025, 1, 6, 10 + index, 0, tzinfo=UTC),
            atr=str(10 + index),
            outcome_scale=str(index + 1),
        )
        for index in range(6)
    ]
    covariates = [
        {
            "case_id": f"case-{index}",
            "as_of_utc": cases[index]["as_of_utc"],
            "state": "known",
            "spread_z": str(index),
            "h1_atr_14_bps": str(10 + index),
            "outcome_geometry_available": True,
            "session": "london" if index < 3 else "new_york",
            "baseline_digest": "b" * 64,
        }
        for index in range(6)
    ]
    strata = freeze_j3_strata(covariates)
    result = run_j3(cases, strata, minimum_cell_n_for_gate_review=10)
    assert verify_j3(result)
    assert {cell["horizon_minutes"] for cell in result["cells"]} == {15, 60, 240}
    assert all(cell["mfe_r"]["n"] == cell["mae_r"]["n"] for cell in result["cells"])
    assert result["evidence_state"] == "descriptive_only_insufficient_for_gate"
    assert result["proposed_trading_gate"] is None
    assert result["gate_status"] == "provisional_no_gate"
    assert result["predictive_edge_claimed"] is False
    assert result["depth_claimed"] is False
    assert result["true_exchange_volume_claimed"] is False
    assert result["order_flow_claimed"] is False


def test_tampered_baseline_strata_and_j3_digests_are_rejected() -> None:
    baseline = build_spread_baseline(_baseline_quotes(), min_bucket_n=2)
    tampered_baseline = deepcopy(baseline)
    tampered_baseline["minimum_bucket_n"] = 999
    assert not verify_spread_baseline(tampered_baseline)

    strata = freeze_j3_strata(
        [
            {
                "case_id": "case-a",
                "as_of_utc": "2025-01-06T14:00:00+00:00",
                "state": "known",
                "spread_z": "1",
                "h1_atr_14_bps": "20",
                "outcome_geometry_available": True,
                "session": "london",
                "baseline_digest": baseline["baseline_digest"],
            }
        ]
    )
    tampered_strata = deepcopy(strata)
    tampered_strata["eligible_cases"] = 999
    assert not verify_j3_strata(tampered_strata)
    with pytest.raises(ValueError, match="strata digest"):
        run_j3([], tampered_strata)

    case = _case(
        "case-a",
        as_of=datetime(2025, 1, 6, 14, 0, tzinfo=UTC),
        atr="20",
    )
    result = run_j3([case], strata)
    tampered_result = deepcopy(result)
    tampered_result["predictive_edge_claimed"] = True
    assert not verify_j3(tampered_result)
