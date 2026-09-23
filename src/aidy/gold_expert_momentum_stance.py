"""Is an expert extrapolating momentum, and does that pay at this horizon?

`gold_expert_directional_skill` answers *whether* an expert's calls carry
information. This answers *what the expert is actually doing* - and it exists because
of a specific finding that the skill module could not express.

Measured against production on 2026-09-23, over the 138 gate calls where the previous
resolved move was known:

    experts voted WITH the prior move          66.7 per cent of the time
    the market continued the prior move        43.5 per cent of the time

    followed momentum   n=92   accuracy 0.4022
    faded momentum      n=46   accuracy 0.5000

The experts are momentum extrapolators. Conditional on the moments they commit to a
direction, gold reverts more often than it continues, so the dominant behaviour is
systematically mismatched to the market's conditional behaviour. That is a coherent
explanation for an ensemble sitting 14 points below the majority baseline at every
move size, with a clean label and clean point-in-time discipline.

It is NOT yet a proven one. At n=138 the split between following and fading is
z = -1.1, p = 0.27 - under-powered. The aggregate inversion is significant
(p = 0.026); this particular mechanism is not, on its own, yet.

So this module measures and waits. It flips nothing, weights nothing and changes no
decision. It exists so the hypothesis either hardens or dies on evidence rather than
on whoever argues hardest, and so we learn *which* experts chase momentum rather than
treating the ensemble as one lump.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal

from aidy.gold_expert_directional_skill import (
    DIRECTIONAL,
    NOMINAL_Z,
    wilson_interval,
)

#: Frozen before the result was examined. Below this a stance estimate is reported but
#: carries no verdict, for the same reason MIN_DIRECTIONAL_N exists next door.
MIN_STANCE_N = 40

STANCE_MOMENTUM = "momentum_extrapolator"
STANCE_FADER = "momentum_fader"
STANCE_MIXED = "mixed"
STANCE_INSUFFICIENT = "insufficient_sample"

_ZERO = Decimal("0")
_HALF = Decimal("0.5")


def _fmt(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_EVEN))


def _rate(part: int, whole: int) -> str | None:
    if whole <= 0:
        return None
    return _fmt(Decimal(part) / Decimal(whole))


@dataclass(frozen=True, slots=True)
class MomentumStance:
    subject_id: str
    #: Calls where a prior resolved move and a directional outcome were both known.
    n: int
    followed_n: int
    faded_n: int
    followed_correct: int
    faded_correct: int
    momentum_alignment: str | None
    market_continuation: str | None
    followed_accuracy: str | None
    faded_accuracy: str | None
    stance: str
    #: 95 per cent Wilson interval on momentum_alignment, uncorrected.
    alignment_interval: tuple[str, str] | None

    @property
    def chases_momentum(self) -> bool:
        return self.stance == STANCE_MOMENTUM


def _stance(followed: int, total: int) -> tuple[str, tuple[Decimal, Decimal] | None]:
    if total < MIN_STANCE_N:
        return STANCE_INSUFFICIENT, None
    interval = wilson_interval(followed, total, z=NOMINAL_Z)
    low, high = interval
    if low > _HALF:
        return STANCE_MOMENTUM, interval
    if high < _HALF:
        return STANCE_FADER, interval
    return STANCE_MIXED, interval


def assess_subject(
    subject_id: str,
    rows: Iterable[Mapping[str, object]],
) -> MomentumStance:
    """Score one expert over rows carrying its call, the outcome, and the prior move.

    A row contributes only when the expert committed to a direction, the outcome
    resolved directionally, and the previous resolved move is known. Anything else
    cannot speak to whether the expert was extrapolating.
    """
    followed = faded = followed_correct = faded_correct = continued = 0
    for row in rows:
        call = str(row.get("conclusion") or "").strip().lower()
        got = str(row.get("realised_direction") or "").strip().lower()
        prior = str(row.get("prior_direction") or "").strip().lower()
        if call not in DIRECTIONAL or got not in DIRECTIONAL or prior not in DIRECTIONAL:
            continue
        if got == prior:
            continued += 1
        if call == prior:
            followed += 1
            if call == got:
                followed_correct += 1
        else:
            faded += 1
            if call == got:
                faded_correct += 1

    total = followed + faded
    stance, interval = _stance(followed, total)
    return MomentumStance(
        subject_id=subject_id,
        n=total,
        followed_n=followed,
        faded_n=faded,
        followed_correct=followed_correct,
        faded_correct=faded_correct,
        momentum_alignment=_rate(followed, total),
        market_continuation=_rate(continued, total),
        followed_accuracy=_rate(followed_correct, followed),
        faded_accuracy=_rate(faded_correct, faded),
        stance=stance,
        alignment_interval=(
            (_fmt(interval[0]), _fmt(interval[1])) if interval is not None else None
        ),
    )


def with_prior_direction(
    rows: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Attach each row's previous resolved move, per subject, in time order.

    The caller supplies rows carrying `subject_id`, `decided_at`, `conclusion` and
    `realised_direction`. The prior move is the previous *resolved* direction for that
    same subject, which is what an extrapolating expert would be reading.
    """
    ordered = sorted(
        (dict(row) for row in rows),
        key=lambda row: (str(row.get("subject_id") or ""), str(row.get("decided_at") or "")),
    )
    previous: dict[str, str] = {}
    out: list[dict[str, object]] = []
    for row in ordered:
        subject = str(row.get("subject_id") or "")
        row["prior_direction"] = previous.get(subject)
        out.append(row)
        got = str(row.get("realised_direction") or "").strip().lower()
        if got in DIRECTIONAL:
            previous[subject] = got
    return out


def assess(rows: Sequence[Mapping[str, object]]) -> tuple[MomentumStance, ...]:
    """Assess every subject, attaching prior moves first."""
    enriched = with_prior_direction(rows)
    grouped: dict[str, list[Mapping[str, object]]] = {}
    for row in enriched:
        key = str(row.get("subject_id") or "")
        if key:
            grouped.setdefault(key, []).append(row)
    return tuple(
        sorted(
            (assess_subject(key, items) for key, items in grouped.items()),
            key=lambda item: (item.momentum_alignment or "0", item.subject_id),
            reverse=True,
        )
    )


__all__ = [
    "MIN_STANCE_N",
    "STANCE_FADER",
    "STANCE_INSUFFICIENT",
    "STANCE_MIXED",
    "STANCE_MOMENTUM",
    "MomentumStance",
    "assess",
    "assess_subject",
    "with_prior_direction",
]
