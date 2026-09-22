"""Directional skill and polarity, pinned against the first live sample.

The numbers here are the real confusion matrices measured from the production outcome
ledger joined to gate snapshots on packet_digest, over the 31 hours to
2026-09-22T23:39Z, aggregated at gate_global scope.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from aidy.gold_expert_directional_skill import (
    MIN_DIRECTIONAL_N,
    POLARITY_ALIGNED,
    POLARITY_INSUFFICIENT,
    POLARITY_INVERTED,
    POLARITY_NO_SIGNAL,
    assess,
    assess_subject,
    family_z,
    wilson_interval,
)

#: gate_id -> (agreed, opposed) over directional calls with directional outcomes.
LIVE_SAMPLE = {
    "m5_price_structure_expert": (18, 36),
    "liquidity_reclaim_expert": (21, 24),
    "momentum_impulse_expert": (18, 18),
    "m15_price_structure_expert": (13, 21),
    "h1_price_structure_expert": (13, 14),
    "h4_price_structure_expert": (4, 2),
}


def _rows(gate_id: str, agreed: int, opposed: int) -> list[dict[str, str]]:
    return [
        {"subject_id": gate_id, "conclusion": "bullish", "realised_direction": "bullish"}
        for _ in range(agreed)
    ] + [
        {"subject_id": gate_id, "conclusion": "bullish", "realised_direction": "bearish"}
        for _ in range(opposed)
    ]


def _live_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for gate_id, (agreed, opposed) in LIVE_SAMPLE.items():
        rows.extend(_rows(gate_id, agreed, opposed))
    return rows


def test_wilson_interval_is_correct_at_small_n() -> None:
    """Normal approximation gives nonsense near the bounds; Wilson does not."""
    low, high = wilson_interval(0, 10)
    assert Decimal("0") <= low < Decimal("0.000001")
    assert Decimal("0.27") < high < Decimal("0.31")

    low, high = wilson_interval(5, 10)
    assert low < Decimal("0.5") < high


def test_family_z_widens_with_the_number_of_subjects_tested() -> None:
    assert family_z(1) == pytest.approx(Decimal("1.959964"), abs=Decimal("0.000001"))
    assert family_z(6) == pytest.approx(Decimal("2.638257"), abs=Decimal("0.000001"))
    assert family_z(6) > family_z(2) > family_z(1)


def test_m5_is_inverted_on_its_own_and_not_after_correcting_for_six() -> None:
    """The headline finding, and the reason it must not be acted on yet.

    18 of 54 is a 95 per cent interval of [0.222, 0.466], which excludes chance. But six
    experts were examined to find it, and Bonferroni over six widens the interval to
    [0.192, 0.513], which does not.
    """
    skill = assess_subject(
        "m5_price_structure_expert", _rows("m5", 18, 36), subject_count=6
    )
    assert skill.directional_n == 54
    assert skill.agreement_rate == "0.333333"
    assert skill.nominal_interval == ("0.222414", "0.466390")
    assert skill.nominal_polarity == POLARITY_INVERTED
    assert skill.family_interval == ("0.191941", "0.512785")
    assert skill.polarity == POLARITY_NO_SIGNAL
    assert skill.reason == "excluded_chance_nominally_but_not_after_family_correction"
    assert skill.actionable is False


def test_momentum_impulse_is_a_perfect_coin_but_still_under_powered() -> None:
    """It sat at exactly 18 of 36 - the real null. The frozen minimum of 40 still
    withholds a verdict, because 0.500 at n=36 and 0.500 at n=360 are not the same
    claim and the rule must not pretend otherwise."""
    agreed, opposed = LIVE_SAMPLE["momentum_impulse_expert"]
    skill = assess_subject("momentum_impulse_expert", _rows("m", agreed, opposed))
    assert skill.agreement_rate == "0.500000"
    assert skill.directional_n == 36
    assert skill.polarity == POLARITY_INSUFFICIENT


def test_a_coin_flip_reports_no_signal_once_it_is_powered() -> None:
    skill = assess_subject("coin", _rows("c", 25, 25), subject_count=1)
    assert skill.agreement_rate == "0.500000"
    assert skill.nominal_polarity == POLARITY_NO_SIGNAL
    assert skill.polarity == POLARITY_NO_SIGNAL
    assert skill.reason == "interval_spans_chance"


def test_under_powered_subjects_get_no_verdict_rather_than_a_guess() -> None:
    """m15 at 34 and h1 at 27 sit below the frozen minimum. A verdict from an interval
    that cannot exclude chance at any polarity is noise dressed as a finding."""
    for gate_id in ("m15_price_structure_expert", "h1_price_structure_expert"):
        agreed, opposed = LIVE_SAMPLE[gate_id]
        skill = assess_subject(gate_id, _rows(gate_id, agreed, opposed))
        assert skill.directional_n < MIN_DIRECTIONAL_N
        assert skill.polarity == POLARITY_INSUFFICIENT
        assert skill.nominal_interval is None
        assert skill.actionable is False


def test_no_expert_in_the_live_sample_is_actionable() -> None:
    """The whole point. On 31 hours of evidence nothing has earned a polarity change."""
    results = assess(_live_rows())
    assert len(results) == len(LIVE_SAMPLE)
    assert not [item for item in results if item.actionable]


def test_the_live_sample_corrects_for_all_six_subjects_examined() -> None:
    """Including the under-powered ones. Correcting only for the two that reach the
    minimum would reverse the m5 verdict, which is exactly the selection error this
    guards against."""
    results = {item.subject_id: item for item in assess(_live_rows())}
    m5 = results["m5_price_structure_expert"]
    assert m5.family_interval == ("0.191941", "0.512785")
    assert m5.polarity == POLARITY_NO_SIGNAL

    # Proof that the family size is doing the work, not a coincidence of rounding.
    survivors_only = assess_subject(
        "m5_price_structure_expert", _rows("m5", 18, 36), subject_count=2
    )
    assert survivors_only.polarity == POLARITY_INVERTED


def test_a_genuinely_skilled_expert_would_be_reported_aligned() -> None:
    """Negative control: the rule is capable of firing, it just has not."""
    skill = assess_subject("strong", _rows("s", 40, 14), subject_count=6)
    assert skill.polarity == POLARITY_ALIGNED
    assert skill.actionable is True


def test_neutral_outcomes_and_abstentions_are_not_evidence() -> None:
    """A neutral outcome says nothing about a directional call, and an expert that
    abstained made no claim to score."""
    rows = [
        {"subject_id": "x", "conclusion": "bullish", "realised_direction": "neutral"},
        {"subject_id": "x", "conclusion": "abstain", "realised_direction": "bullish"},
        {"subject_id": "x", "conclusion": "unknown", "realised_direction": "bearish"},
        {"subject_id": "x", "conclusion": "bullish", "realised_direction": "bullish"},
    ]
    skill = assess_subject("x", rows)
    assert skill.directional_n == 1
    assert skill.agreed == 1
