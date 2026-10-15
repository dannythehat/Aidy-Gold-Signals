"""Day25 matched-clock baseline vs Day19 and realistic Day12/13 cost stresses."""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256

import pytest

from aidy.strategy_lab_baselines_stress import (
    POLICY,
    _scenario_pnl,
    compare_day19_fixed_window,
)
from aidy.strategy_lab_bidask_execution import QuoteTape
from aidy.strategy_lab_reference_run import run_internal_reference
from scripts.strategy_lab.day25_baselines_cost_stress_acceptance import (
    audit,
    build_source_bundle,
)

START = datetime(2026, 10, 14, 14, tzinfo=UTC)
END = START + timedelta(minutes=5)


def example(tmp_path):
    profile, broker, tape, candles = build_source_bundle()
    digest = sha256(candles).hexdigest()
    receipt = run_internal_reference(
        closed_bar_source=candles, expected_closed_bar_sha256=digest,
        quote_tape=tape, broker_profile=profile,
        broker_source_bytes=broker, sqlite_path=tmp_path/"day19.db",
    )
    return receipt, profile, broker, tape, digest


def compare(inputs, **changes):
    reference, profile, broker, tape, digest = inputs
    args = {
        "reference": reference, "profile": profile, "broker_source_bytes": broker,
        "quote_tape": tape, "source_candle_sha256": digest,
        "entry_signal_closed_at_utc": START, "exit_signal_closed_at_utc": END,
        "naive_session_entry_closed_at_utc": START+timedelta(minutes=10),
        "naive_session_exit_closed_at_utc": START+timedelta(minutes=15),
    }
    args.update(changes)
    return compare_day19_fixed_window(**args)


def test_real_sqlite_day19_account_reference_matches_baseline_and_stress(tmp_path):
    report = compare(example(tmp_path))
    assert report.accounting_control_pass
    assert [s.name for s in report.scenario_results] == ["base", "adverse", "severe"]
    assert [s.candidate_gross_quote_side_usd for s in report.scenario_results] == [
        Decimal("9.00"), Decimal("8.60"), Decimal("8.00"),
    ]
    assert [s.candidate_net_usd for s in report.scenario_results] == [
        Decimal("8.30"), Decimal("7.54"), Decimal("6.60"),
    ]
    assert [s.blind_clock_short_net_usd for s in report.scenario_results] == [
        Decimal("-11.70"), Decimal("-12.46"), Decimal("-13.40"),
    ]
    assert all(s.matched_exposure_difference_usd == 0 for s in report.scenario_results)
    assert all(s.independent_blind_clock_long_net_usd == s.candidate_net_usd
               for s in report.scenario_results)
    assert report.sample_origin == "internal_synthetic_fixed_window_not_historical_edge"
    assert not report.genuine_strategy_alpha_qualified
    assert not report.independent_strategy_benchmark_completed
    assert not report.native_broker_execution_verified
    assert report.scheduled_naive_same_session_tested
    assert [s.independently_scheduled_same_session_long_net_usd
            for s in report.scenario_results] == [
                Decimal("18.30"), Decimal("17.54"), Decimal("16.60"),
            ]
    assert [s.candidate_minus_scheduled_naive_usd
            for s in report.scenario_results] == [Decimal(-10)]*3


def test_each_cost_component_has_one_unambiguous_source(tmp_path):
    report = compare(example(tmp_path))
    base, adverse, severe = report.scenario_results
    assert base.candidate_gross_quote_side_usd == Decimal("9.00")
    assert base.candidate_commission_usd == Decimal("-0.50")
    assert base.candidate_slippage_usd == Decimal("-0.20")
    assert base.candidate_funding_usd == 0
    assert adverse.candidate_commission_usd == Decimal("-0.76")
    assert adverse.candidate_slippage_usd == Decimal("-0.30")
    assert adverse.candidate_gross_quote_side_usd == Decimal("8.60")
    assert severe.candidate_commission_usd == Decimal("-1.00")
    assert severe.candidate_slippage_usd == Decimal("-0.40")
    assert severe.candidate_gross_quote_side_usd == Decimal("8.00")
    assert base.candidate_net_usd == base.candidate_gross_quote_side_usd - Decimal("0.70")
    assert all(s.candidate_net_usd == (
        s.candidate_gross_quote_side_usd + s.candidate_commission_usd +
        s.candidate_slippage_usd + s.candidate_funding_usd
    ) for s in report.scenario_results)
    assert tuple((n, t, m) for n, t, m in POLICY) == (
        ("base", 0, Decimal(1)),
        ("adverse", 2, Decimal("1.5")),
        ("severe", 5, Decimal(2)),
    )


def test_two_independent_real_day19_ledgers_give_identical_hashes_and_reports():
    proof = audit()
    assert proof["status"] == "PASS"
    assert proof["independent_disk_backed_cash_journals"] == 2
    assert proof["day19_verified_final_cash_usd"] == "10008.30"
    assert proof["benchmark_and_stress"]["genuine_strategy_alpha_qualified"] is False
    assert proof["scheduled_naive_same_session_tested"]
    assert not proof["independent_real_market_benchmark_qualified"]
    assert len(proof["reference_journal_tip_sha256"]) == 64


@pytest.mark.parametrize("tamper", [
    {"rule_sha256": "0"*64},
    {"quote_sha256": "f"*64},
    {"closed_candle_sha256": "a"*64},
    {"opening_cash_usd": Decimal("9999.00")},
    {"closing_cash_usd": Decimal("10008.31")},
    {"net_usd": Decimal("8.31")},
    {"actual_broker_attested": True},
    {"journal_tip_sha256": ""},
])
def test_untrusted_day19_reference_or_claim_is_rejected(tmp_path, tamper):
    inputs = example(tmp_path)
    with pytest.raises(ValueError, match="frozen known-answer"):
        compare(inputs, reference=replace(inputs[0], **tamper))


def test_wrong_broker_source_or_quote_snapshot_fails_closed(tmp_path):
    inputs = example(tmp_path)
    with pytest.raises(ValueError):
        compare(inputs, broker_source_bytes=b"pretend broker")
    data = inputs[3].snapshot_bytes + b" "
    with pytest.raises(ValueError, match="SHA256"):
        QuoteTape.from_snapshot(data, expected_sha256=inputs[3].snapshot_sha256)
    with pytest.raises(ValueError):
        compare(inputs, quote_tape=replace(
            inputs[3], quotes=inputs[3].quotes[:-1],
        ))


@pytest.mark.parametrize("time_change", [
    timedelta(seconds=1), timedelta(minutes=1), timedelta(minutes=-1),
])
def test_wrong_candidate_window_and_selection_rejected(tmp_path, time_change):
    inputs = example(tmp_path)
    with pytest.raises(ValueError):
        compare(inputs, entry_signal_closed_at_utc=START+time_change)
    with pytest.raises(ValueError):
        compare(inputs, exit_signal_closed_at_utc=END+time_change)


@pytest.mark.parametrize("bad", [Decimal(-1), Decimal("0.99"), Decimal("5.01"), Decimal("NaN"), 1.5, True])
def test_cost_multiplier_validation_refuses_unsafe_or_untestable_values(bad):
    profile, broker, tape, _ = build_source_bundle()
    with pytest.raises(ValueError, match="multiplier"):
        _scenario_pnl(
            profile, broker, tape, direction="long", lots="0.1",
            entry_closed=START, exit_closed=END,
            extra_ticks_per_side=0, cash_multiplier=bad,
        )


def test_spread_stress_rejects_negative_non_integer_and_absurd_values():
    profile, broker, tape, _ = build_source_bundle()
    for invalid in [-1, True, 1.1, 10001, "2"]:
        with pytest.raises(ValueError):
            _scenario_pnl(
                profile, broker, tape, direction="long", lots="0.1",
                entry_closed=START, exit_closed=END,
                extra_ticks_per_side=invalid, cash_multiplier=Decimal(1),
            )


def test_advance_registration_of_naive_schedule_and_source_is_enforced(tmp_path):
    original = example(tmp_path)
    for delta in (timedelta(minutes=1), timedelta(minutes=-1)):
        with pytest.raises(ValueError, match="predeclared"):
            compare(
                original,
                naive_session_entry_closed_at_utc=START+timedelta(minutes=10)+delta,
            )
    assert compare(original).scenario_results[0].candidate_minus_scheduled_naive_usd < 0


def test_outdated_timing_data_fails_no_fill_instead_of_guessing():
    profile, broker, tape, _ = build_source_bundle()
    with pytest.raises(ValueError, match="stale|no quote"):
        _scenario_pnl(
            profile, broker, tape, direction="long", lots="0.1",
            entry_closed=START+timedelta(seconds=2), exit_closed=END,
            extra_ticks_per_side=0, cash_multiplier=Decimal(1),
        )
