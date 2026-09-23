"""Pinned to the real 2026-09-23 production measurement.

Every number here was read from D1 at scope_type='gate_global'. They are pinned so a
change to the maths shows up as a failing test rather than as a quietly different
conclusion about whether AIDY has any edge.
"""

from __future__ import annotations

from aidy.gold_baseline_edge import (
    ALPHA,
    MIN_BASELINE_N,
    VERDICT_BEATS,
    VERDICT_INSUFFICIENT,
    VERDICT_INVERTED,
    VERDICT_NOMINAL_ONLY,
    assess,
    assess_subject,
    majority_baseline,
    normal_two_sided_p,
    strategy_comparison,
    two_sided_binomial_p,
    wilson_interval,
)

#: The real gate confusion matrix: 286 scored gate calls, 247 with a directional outcome.
PRODUCTION_CONFUSION = [
    {"said": "bearish", "happened": "bearish", "n": 68},
    {"said": "bearish", "happened": "bullish", "n": 60},
    {"said": "bearish", "happened": "neutral", "n": 20},
    {"said": "bullish", "happened": "bearish", "n": 75},
    {"said": "bullish", "happened": "bullish", "n": 44},
    {"said": "bullish", "happened": "neutral", "n": 19},
]


def test_the_pooled_exact_binomial_does_not_overflow() -> None:
    """The first version of this used comb(n, k) * p**k and raised
    'OverflowError: int too large to convert to float' at the pooled sample size - which
    is the size it is actually used at. Log-space via lgamma is why it now works."""
    p = two_sided_binomial_p(998, 2843, 0.4798)
    assert 0.0 < p < 1e-40
    # Cross-check the exact tail against the normal approximation: same order.
    assert 0.0 < normal_two_sided_p(998, 2843, 0.4798) < 1e-40


def test_the_baseline_is_the_majority_class_not_one_half() -> None:
    """h4_acceleration's real sample: 52 bullish, 65 bearish, 20 neutral."""
    assert majority_baseline({"bullish": 52, "bearish": 65, "neutral": 20}) == 65 / 137


def test_h4_acceleration_does_not_beat_its_baseline() -> None:
    """The largest sample of any subject, and still below its own majority class."""
    edge = assess_subject(
        subject_type="subcalculator",
        subject_id="h4_acceleration",
        n=137,
        correct=52,
        class_counts={"bullish": 52, "bearish": 65, "neutral": 20},
        corrected_alpha=ALPHA / 53,
    )
    assert round(edge.accuracy, 4) == 0.3796
    assert round(edge.baseline, 4) == 0.4745
    assert edge.edge < 0
    assert not edge.beats_baseline
    # Nominally significant, but it does not survive correction across 53 subjects.
    assert edge.p_value < ALPHA
    assert edge.verdict == VERDICT_NOMINAL_ONLY


def test_the_four_survivors_are_all_inverted_not_better() -> None:
    """Four subjects cleared Bonferroni on 2026-09-23 and every one was significantly
    WORSE than its baseline. A test that only checked 'significant' would have called
    these a discovery."""
    survivors = [
        ("liquidity_new_york_opening_30m_low", 20, 3, {"bullish": 5, "bearish": 13, "neutral": 2}),
        ("h1_breakout_acceptance", 76, 23, {"bullish": 23, "bearish": 40, "neutral": 13}),
        ("liquidity_confirmed_m15_swing_low", 32, 7, {"bullish": 9, "bearish": 18, "neutral": 5}),
        ("m5_breakout_acceptance", 76, 24, {"bullish": 25, "bearish": 39, "neutral": 12}),
    ]
    for subject_id, n, correct, classes in survivors:
        edge = assess_subject(
            subject_type="subcalculator",
            subject_id=subject_id,
            n=n,
            correct=correct,
            class_counts=classes,
            corrected_alpha=ALPHA / 53,
        )
        assert edge.verdict == VERDICT_INVERTED, subject_id
        assert not edge.beats_baseline
        assert edge.p_value < ALPHA / 53


def test_a_genuine_winner_would_be_reported_as_one() -> None:
    """The suite must be able to say yes, or a clean sweep of noes proves nothing."""
    edge = assess_subject(
        subject_type="gate",
        subject_id="hypothetical",
        n=200,
        correct=160,
        class_counts={"bullish": 90, "bearish": 100, "neutral": 10},
        corrected_alpha=ALPHA / 53,
    )
    assert edge.verdict == VERDICT_BEATS
    assert edge.beats_baseline
    assert edge.edge > 0


def test_an_underpowered_subject_gets_no_verdict_and_leaves_the_family() -> None:
    rows = [
        {"subject_type": "gate", "subject_id": "thin", "n": MIN_BASELINE_N - 1,
         "correct": 0, "class_counts": {"bullish": 5, "bearish": 14, "neutral": 0}},
        {"subject_type": "gate", "subject_id": "fat", "n": 100,
         "correct": 40, "class_counts": {"bullish": 40, "bearish": 48, "neutral": 12}},
    ]
    results = {item.subject_id: item for item in assess(rows)}
    assert results["thin"].verdict == VERDICT_INSUFFICIENT
    # Correction divides by the tests actually performed - one, not two.
    assert results["fat"].corrected_alpha == ALPHA / 1


def test_the_ensemble_is_below_the_majority_baseline_but_not_below_random() -> None:
    """The finding that stopped a polarity flip being shipped.

    Significantly worse than a constant answer, NOT significantly worse than a coin.
    That is 'fails to exploit a drift', not 'reads the market backwards'.
    """
    result = strategy_comparison(PRODUCTION_CONFUSION)
    assert result.n == 247
    assert result.follow_correct == 112
    assert result.majority_class == "bearish"
    assert result.majority_correct == 143
    assert round(result.follow_accuracy, 3) == 0.453
    assert round(result.majority_accuracy, 3) == 0.579

    assert result.p_vs_majority < 0.001      # z = -4.00
    assert result.p_vs_random > 0.10         # z = -1.46, not significant


def test_inverting_the_experts_was_not_exploitable() -> None:
    """Inverting scored 54.7 per cent and the constant answer scored 57.9, so flipping
    polarity would have been worse than answering 'bearish' every time. This is the
    check that makes 'invert them' refutable rather than tempting."""
    result = strategy_comparison(PRODUCTION_CONFUSION)
    assert round(result.invert_accuracy, 3) == 0.547
    assert result.invert_accuracy > result.follow_accuracy
    assert result.invert_accuracy < result.majority_accuracy
    assert result.inversion_is_exploitable is False


def test_neutral_outcomes_are_excluded_from_the_strategy_comparison() -> None:
    """286 scored calls, 247 directional. A neutral outcome cannot reward or punish a
    directional call, and leaving them in lowers every strategy together - which would
    make the experts look closer to the baseline than they are."""
    assert strategy_comparison(PRODUCTION_CONFUSION).n == 247
    assert sum(row["n"] for row in PRODUCTION_CONFUSION) == 286


def test_wilson_excludes_the_baseline_for_the_pooled_sample() -> None:
    low, high = wilson_interval(998, 2843)
    assert round(low, 4) == 0.3337
    assert round(high, 4) == 0.3688
    assert not (low <= 0.4798 <= high)
