"""Momentum stance, pinned against the production measurement of 2026-09-23.

Over the 138 gate calls where the previous resolved move was known: experts voted with
the prior move 66.7 per cent of the time, the market continued it 43.5 per cent of the
time, and following momentum scored 0.4022 against 0.5000 for fading it.
"""

from __future__ import annotations

from aidy.gold_expert_momentum_stance import (
    MIN_STANCE_N,
    STANCE_FADER,
    STANCE_INSUFFICIENT,
    STANCE_MIXED,
    STANCE_MOMENTUM,
    assess,
    assess_subject,
    with_prior_direction,
)


def _row(call: str, got: str, prior: str | None) -> dict[str, object]:
    return {
        "subject_id": "expert",
        "conclusion": call,
        "realised_direction": got,
        "prior_direction": prior,
    }


def _live_shape() -> list[dict[str, object]]:
    """Reproduce the production split: 92 followed (37 right), 46 faded (23 right)."""
    rows: list[dict[str, object]] = []
    rows += [_row("bullish", "bullish", "bullish") for _ in range(37)]
    rows += [_row("bullish", "bearish", "bullish") for _ in range(55)]
    rows += [_row("bullish", "bullish", "bearish") for _ in range(23)]
    rows += [_row("bullish", "bearish", "bearish") for _ in range(23)]
    return rows


def test_the_production_sample_reads_as_a_momentum_extrapolator() -> None:
    stance = assess_subject("expert", _live_shape())
    assert stance.n == 138
    assert stance.followed_n == 92
    assert stance.faded_n == 46
    assert stance.momentum_alignment == "0.666667"
    assert stance.followed_accuracy == "0.402174"
    assert stance.faded_accuracy == "0.500000"
    assert stance.stance == STANCE_MOMENTUM
    assert stance.chases_momentum is True


def test_market_continuation_is_measured_separately_from_the_expert() -> None:
    """The expert's alignment and the market's behaviour are different quantities.
    Conflating them is how a momentum chaser looks correct in a trending sample."""
    stance = assess_subject("expert", _live_shape())
    # continued = outcome matched prior: 37 (bull after bull) + 23 (bear after bear)
    assert stance.market_continuation == "0.434783"
    assert stance.momentum_alignment != stance.market_continuation


def test_a_fader_is_reported_as_a_fader() -> None:
    rows = [_row("bullish", "bullish", "bearish") for _ in range(45)]
    rows += [_row("bullish", "bullish", "bullish") for _ in range(5)]
    stance = assess_subject("fader", rows)
    assert stance.stance == STANCE_FADER
    assert stance.chases_momentum is False


def test_a_balanced_expert_is_mixed_not_forced_into_a_camp() -> None:
    rows = [_row("bullish", "bullish", "bullish") for _ in range(25)]
    rows += [_row("bullish", "bullish", "bearish") for _ in range(25)]
    assert assess_subject("balanced", rows).stance == STANCE_MIXED


def test_an_under_powered_expert_gets_no_verdict() -> None:
    rows = [_row("bullish", "bullish", "bullish") for _ in range(MIN_STANCE_N - 1)]
    stance = assess_subject("thin", rows)
    assert stance.n < MIN_STANCE_N
    assert stance.stance == STANCE_INSUFFICIENT
    assert stance.alignment_interval is None


def test_rows_without_a_known_prior_move_are_not_evidence() -> None:
    """The first call a subject ever makes has no prior move to extrapolate from."""
    rows = [_row("bullish", "bullish", None), _row("bullish", "bullish", "bullish")]
    assert assess_subject("expert", rows).n == 1


def test_neutral_and_abstain_never_count_as_a_stance() -> None:
    rows = [
        _row("neutral", "bullish", "bullish"),
        _row("abstain", "bullish", "bullish"),
        _row("bullish", "neutral", "bullish"),
        _row("bullish", "bullish", "neutral"),
    ]
    assert assess_subject("expert", rows).n == 0


def test_prior_direction_is_attached_per_subject_in_time_order() -> None:
    """Two experts interleaved in time must not read each other's prior moves."""
    rows = [
        {"subject_id": "a", "decided_at": "01", "conclusion": "bullish", "realised_direction": "bullish"},
        {"subject_id": "b", "decided_at": "02", "conclusion": "bullish", "realised_direction": "bearish"},
        {"subject_id": "a", "decided_at": "03", "conclusion": "bullish", "realised_direction": "bearish"},
        {"subject_id": "b", "decided_at": "04", "conclusion": "bullish", "realised_direction": "bullish"},
    ]
    enriched = {(r["subject_id"], r["decided_at"]): r["prior_direction"] for r in with_prior_direction(rows)}
    assert enriched[("a", "01")] is None
    assert enriched[("a", "03")] == "bullish"   # a's own previous outcome
    assert enriched[("b", "02")] is None
    assert enriched[("b", "04")] == "bearish"   # b's own previous outcome, not a's


def test_assess_groups_by_subject() -> None:
    rows = [
        {"subject_id": "a", "decided_at": "01", "conclusion": "bullish", "realised_direction": "bullish"},
        {"subject_id": "b", "decided_at": "01", "conclusion": "bearish", "realised_direction": "bearish"},
    ]
    assert {item.subject_id for item in assess(rows)} == {"a", "b"}
