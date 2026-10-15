"""Day27 market regime classification regressions and adversarial causal tests."""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from test_strategy_lab_oos_protocol import sample_history

from aidy.strategy_lab_oos_protocol import SealedOOS
from aidy.strategy_lab_regimes import (
    NEWS_BUCKETS,
    SESSION_BUCKETS,
    TREND_BUCKETS,
    VOL_BUCKETS,
    RegimePolicy,
    _classify,
    _session,
    analyze_day26_development_regimes,
)


def example():
    history = sample_history()
    return history, SealedOOS(history)


def test_regime_labels_on_genuine_day26_development_folds_only():
    h, study = example()
    report = analyze_day26_development_regimes(h, study=study)
    assert report.schema == "aidy.market_regime_asof.v1"
    assert report.fully_closed_m5_available == 120
    assert report.development_labeled_samples == 94
    assert report.evaluated_walkforward_predictions == 48
    assert report.sealed_holdout_decisions_consumed == 0
    assert len(report.evaluated) == 48
    assert len({r.decision_utc for r in report.evaluated}) == 48
    assert report.day26_model_sha256 == study.review_development().model_sha256
    assert report.day26_holdout_commit_sha256 == study.review_development().holdout_sha256
    assert all(r.decision_utc == r.last_closed_bar_available_utc
               for r in report.evaluated)
    assert all(r.first_window_close_available_utc < r.decision_utc
               for r in report.evaluated)
    assert all(r.news == "unknown_unqualified_calendar" for r in report.evaluated)
    assert all(r.utc_session in SESSION_BUCKETS for r in report.evaluated)
    assert all(r.volatility in VOL_BUCKETS for r in report.evaluated)
    assert all(r.trend in TREND_BUCKETS for r in report.evaluated)
    assert not report.news_source_qualified
    assert not report.actual_bid_ask_execution_costs_verified
    assert not report.strategy_alpha_qualified


def test_every_partition_sums_to_exact_preaudited_validation_count():
    history, study = example()
    report = analyze_day26_development_regimes(history, study=study)
    for dim, categories in (
        ("trend", TREND_BUCKETS), ("volatility", VOL_BUCKETS),
        ("session", SESSION_BUCKETS), ("news", NEWS_BUCKETS),
    ):
        subset = [v for v in report.breakdowns if v.dimension == dim]
        assert {v.label for v in subset} == set(categories)
        assert sum(v.validation_signals for v in subset) == 48
        for v in subset:
            if v.state == "MEASURED_RETROSPECTIVE_DIRECTION_ONLY":
                assert v.validation_signals >= 12
                assert 0 <= v.direction_correct <= v.validation_signals
                assert 0 <= v.naive_always_positive_correct <= v.validation_signals
                assert v.model_direction_hit_rate_percent is not None
                assert v.naive_direction_hit_rate_percent is not None
            else:
                assert v.model_direction_hit_rate_percent is None
                assert v.naive_direction_hit_rate_percent is None
    news = [v for v in report.breakdowns if v.dimension == "news"]
    assert len(news) == 1
    assert news[0].validation_signals == 48
    assert news[0].state == "SOURCE_UNAVAILABLE_NO_NEWS_CONCLUSIONS"


def test_no_regime_may_read_a_future_quote_even_if_future_market_changes():
    history, study = example()
    before = _classify(history.bars, 65, RegimePolicy())
    modified = list(history.bars)
    modified[66] = replace(modified[66], close=Decimal("999999.00"))
    modified[98] = replace(modified[98], close=Decimal("1000000.00"))
    assert _classify(tuple(modified), 65, RegimePolicy()) == before
    whole = analyze_day26_development_regimes(history, study=study)
    # The final 20 Day26 holdout observations must not influence Day27 labels.
    changed = list(history.bars)
    for i in range(100, 120):
        changed[i] = replace(changed[i], close=changed[i].close+Decimal(500))
    alt = replace(history, bars=tuple(changed))
    assert analyze_day26_development_regimes(alt, study=study).to_json() == whole.to_json()


def test_directional_efficiency_is_bounded_and_volatility_based_on_past_returns():
    history, _ = example()
    for i in (15, 25, 49, 70, 95):
        trend, vol, session, news, efficiency, bps = _classify(
            history.bars, i, RegimePolicy()
        )
        assert trend in TREND_BUCKETS
        assert vol in VOL_BUCKETS
        assert session in SESSION_BUCKETS
        assert news in NEWS_BUCKETS
        assert Decimal(0) <= Decimal(efficiency) <= Decimal(1)
        assert Decimal(bps) >= 0
    with pytest.raises(ValueError, match="insufficient"):
        _classify(history.bars, 11, RegimePolicy())


@pytest.mark.parametrize("policy", [
    RegimePolicy(lookback_closed_m5_returns=2),
    RegimePolicy(lookback_closed_m5_returns=True),
    RegimePolicy(min_validation_signals_per_bucket=2),
    RegimePolicy(min_validation_signals_per_bucket=True),
    RegimePolicy(trend_efficiency_min=Decimal("0.30")),
    RegimePolicy(range_efficiency_max=Decimal("0.70")),
    RegimePolicy(low_vol_mean_abs_return_bps=Decimal(0)),
    RegimePolicy(high_vol_mean_abs_return_bps=Decimal(1)),
    RegimePolicy(low_vol_mean_abs_return_bps=Decimal("NaN")),
    RegimePolicy(trend_efficiency_min=0.6),
])
def test_hindsight_or_invalid_regime_policy_not_accepted(policy):
    h, study = example()
    with pytest.raises(ValueError):
        analyze_day26_development_regimes(h, study=study, policy=policy)


def test_insufficient_sample_counts_withheld_not_relabelled_as_bad_performance():
    h, study = example()
    report = analyze_day26_development_regimes(
        h, study=study, policy=RegimePolicy(min_validation_signals_per_bucket=60)
    )
    assert all(x.state != "MEASURED_RETROSPECTIVE_DIRECTION_ONLY"
               for x in report.breakdowns)
    assert all(x.direction_correct is None for x in report.breakdowns)
    assert all(x.model_direction_hit_rate_percent is None for x in report.breakdowns)


def test_british_summer_time_and_new_york_dst_change_session_correctly():
    assert _session(datetime(2025, 3, 28, 8, tzinfo=UTC)) == "london"
    assert _session(datetime(2025, 3, 31, 7, tzinfo=UTC)) == "london"
    assert _session(datetime(2025, 3, 28, 13, tzinfo=UTC)) == "london_new_york_overlap"
    assert _session(datetime(2025, 3, 31, 12, tzinfo=UTC)) == "london_new_york_overlap"
    assert _session(datetime(2025, 1, 6, 22, tzinfo=UTC)) == "outside"


def test_wrong_source_digest_or_missing_archives_denied():
    h, study = example()
    with pytest.raises(ValueError, match="source/provenance mismatch"):
        analyze_day26_development_regimes(
            replace(h, input_digest="f"*64), study=study
        )
    with pytest.raises(ValueError):
        analyze_day26_development_regimes(
            replace(h, source_archive_hashes=()), study=study
        )


def test_gaps_unclosed_quotes_and_invalid_pit_status_blocked_through_day26():
    h = sample_history()
    for field, replacement in (
        ("pit_eligible", True), ("native_m1_rows", 555),
        ("provenance", "fictional"),
    ):
        with pytest.raises(ValueError):
            SealedOOS(replace(h, **{field: replacement}))
    changed = list(h.bars)
    changed[51] = replace(changed[51],
                          available_at_utc=changed[51].available_at_utc+timedelta(minutes=1))
    with pytest.raises(ValueError):
        SealedOOS(replace(h, bars=tuple(changed)))


def test_source_and_policy_fingerprints_replay_deterministically():
    h, study = example()
    one = analyze_day26_development_regimes(h, study=study)
    two = analyze_day26_development_regimes(h, study=study)
    assert one == two
    assert one.to_json() == two.to_json()
    assert len(one.decisions_sha256) == 64
    assert len(one.regime_policy_sha256) == 64
