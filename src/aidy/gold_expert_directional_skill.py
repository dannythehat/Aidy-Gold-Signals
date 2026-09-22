"""Does a directional expert carry information, and in which polarity?

Raw accuracy cannot answer this. An expert that answers "bearish" into a window that
resolved bearish 48.5 per cent of the time scores 48.5 per cent while knowing nothing,
and the conditional-trust engine will happily reward it for the base rate. Worse, an
expert whose calls are *reliably wrong* carries just as much information as one that is
reliably right, but raw accuracy files it next to the noise and shrinkage pulls it to
0.5 where it disappears.

This module measures the thing that matters: over the cycles where an expert committed
to a direction and the market resolved to one, how often did the market agree with it?
An agreement rate far from 0.5 in *either* direction is information. Only a rate at 0.5
is genuinely nothing.

On the first live sample this separated real structure from noise immediately.
Aggregated over gate_global, m5_price_structure_expert agreed with the market on 18 of
54 directional resolutions - 33.3 per cent, a 95 per cent Wilson interval of
[0.222, 0.466] that excludes chance - and the inversion was symmetric across both call
types, which base-rate bias cannot produce. momentum_impulse_expert sat at exactly 18 of
36. One of those is a signal read with the wrong sign; the other is a coin.

NOTHING HERE FLIPS AN EXPERT. Six subjects were assessed to find that result, and under
a family-wise correction for six the same interval widens to [0.192, 0.513] and no
longer excludes chance. Acting on it now would be fitting 54 observations. The frozen
promotion rule below exists so the decision is made by evidence that has already been
specified, not by whichever threshold happens to make the answer come out.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from math import sqrt
from statistics import NormalDist

#: Frozen before looking at any result. Changing these is a new pre-registration.
#:
#: MIN_DIRECTIONAL_N - below this a Wilson interval is too wide to exclude chance at
#: any polarity, so the verdict is withheld rather than guessed.
MIN_DIRECTIONAL_N = 40
#: Two-sided family-wise error rate. The per-subject level is ALPHA / subject_count.
ALPHA = 0.05
#: Two-sided 95 per cent, used for the uncorrected interval reported alongside.
NOMINAL_Z = Decimal("1.959964")

DIRECTIONAL = ("bullish", "bearish")

POLARITY_ALIGNED = "aligned"
POLARITY_INVERTED = "inverted"
POLARITY_NO_SIGNAL = "no_signal"
POLARITY_INSUFFICIENT = "insufficient_sample"

_ZERO = Decimal("0")
_HALF = Decimal("0.5")
_ONE = Decimal("1")


def _fmt(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_EVEN))


def family_z(subject_count: int) -> Decimal:
    """Exact two-sided Bonferroni quantile for assessing `subject_count` subjects.

    Six experts were examined to find one inverted candidate. Reporting that candidate
    at an uncorrected 95 per cent would be the multiple-comparison error that makes
    backtests look profitable. The family is every subject a verdict was sought from,
    not only the ones that happened to survive.
    """
    subjects = max(1, subject_count)
    quantile = 1.0 - ALPHA / (2.0 * subjects)
    return Decimal(str(NormalDist().inv_cdf(quantile)))


def wilson_interval(
    successes: int,
    total: int,
    *,
    z: Decimal = NOMINAL_Z,
) -> tuple[Decimal, Decimal]:
    """Wilson score interval. Correct at small n, where normal approximation is not."""
    if total <= 0:
        return (_ZERO, _ONE)
    n = Decimal(total)
    p_hat = Decimal(successes) / n
    z_sq = z * z
    denominator = _ONE + z_sq / n
    centre = (p_hat + z_sq / (Decimal(2) * n)) / denominator
    inner = p_hat * (_ONE - p_hat) / n + z_sq / (Decimal(4) * n * n)
    half = (z / denominator) * Decimal(sqrt(float(inner)))
    low = centre - half
    high = centre + half
    return (max(_ZERO, low), min(_ONE, high))


@dataclass(frozen=True, slots=True)
class DirectionalSkill:
    subject_id: str
    directional_n: int
    agreed: int
    opposed: int
    agreement_rate: str | None
    nominal_interval: tuple[str, str] | None
    family_interval: tuple[str, str] | None
    polarity: str
    nominal_polarity: str
    reason: str

    @property
    def actionable(self) -> bool:
        """True only when the family-wise interval excludes chance."""
        return self.polarity in (POLARITY_ALIGNED, POLARITY_INVERTED)


def _verdict(
    interval: tuple[Decimal, Decimal],
) -> str:
    low, high = interval
    if high < _HALF:
        return POLARITY_INVERTED
    if low > _HALF:
        return POLARITY_ALIGNED
    return POLARITY_NO_SIGNAL


def assess_subject(
    subject_id: str,
    rows: Iterable[Mapping[str, object]],
    *,
    subject_count: int = 1,
) -> DirectionalSkill:
    """Score one subject over rows carrying a call and a realised direction.

    Only cycles where the expert committed to a direction AND the market resolved to
    one are counted. A neutral outcome is not evidence about a directional call, and an
    abstaining expert made no claim to score.
    """
    agreed = 0
    opposed = 0
    for row in rows:
        call = str(row.get("conclusion") or "").strip().lower()
        realised = str(row.get("realised_direction") or "").strip().lower()
        if call not in DIRECTIONAL or realised not in DIRECTIONAL:
            continue
        if call == realised:
            agreed += 1
        else:
            opposed += 1

    total = agreed + opposed
    if total < MIN_DIRECTIONAL_N:
        return DirectionalSkill(
            subject_id=subject_id,
            directional_n=total,
            agreed=agreed,
            opposed=opposed,
            agreement_rate=_fmt(Decimal(agreed) / Decimal(total)) if total else None,
            nominal_interval=None,
            family_interval=None,
            polarity=POLARITY_INSUFFICIENT,
            nominal_polarity=POLARITY_INSUFFICIENT,
            reason=f"directional_n_{total}_below_minimum_{MIN_DIRECTIONAL_N}",
        )

    nominal = wilson_interval(agreed, total)
    family = wilson_interval(agreed, total, z=family_z(subject_count))
    polarity = _verdict(family)
    nominal_polarity = _verdict(nominal)
    if polarity == POLARITY_NO_SIGNAL and nominal_polarity != POLARITY_NO_SIGNAL:
        reason = "excluded_chance_nominally_but_not_after_family_correction"
    elif polarity == POLARITY_NO_SIGNAL:
        reason = "interval_spans_chance"
    else:
        reason = "family_interval_excludes_chance"

    return DirectionalSkill(
        subject_id=subject_id,
        directional_n=total,
        agreed=agreed,
        opposed=opposed,
        agreement_rate=_fmt(Decimal(agreed) / Decimal(total)),
        nominal_interval=(_fmt(nominal[0]), _fmt(nominal[1])),
        family_interval=(_fmt(family[0]), _fmt(family[1])),
        polarity=polarity,
        nominal_polarity=nominal_polarity,
        reason=reason,
    )


def assess(rows: Sequence[Mapping[str, object]]) -> tuple[DirectionalSkill, ...]:
    """Assess every subject present, correcting for how many were examined.

    The family is every subject with at least one directional resolution, not only the
    ones that reach MIN_DIRECTIONAL_N. Correcting for the survivors alone would be the
    same selection error moved one step later.
    """
    grouped: dict[str, list[Mapping[str, object]]] = {}
    for row in rows:
        key = str(row.get("subject_id") or row.get("gate_id") or "").strip()
        if key:
            grouped.setdefault(key, []).append(row)

    # Every subject a verdict was sought from counts toward the family, including the
    # under-powered ones. Correcting only for the survivors is the same selection error
    # in a different place.
    subject_count = max(
        1,
        sum(
            1
            for subject_rows in grouped.values()
            if assess_subject("_", subject_rows).directional_n > 0
        ),
    )

    return tuple(
        sorted(
            (
                assess_subject(key, subject_rows, subject_count=subject_count)
                for key, subject_rows in grouped.items()
            ),
            key=lambda item: (item.agreement_rate or "9", item.subject_id),
        )
    )


__all__ = [
    "ALPHA",
    "DIRECTIONAL",
    "DirectionalSkill",
    "MIN_DIRECTIONAL_N",
    "NOMINAL_Z",
    "POLARITY_ALIGNED",
    "POLARITY_INSUFFICIENT",
    "POLARITY_INVERTED",
    "POLARITY_NO_SIGNAL",
    "assess",
    "assess_subject",
    "family_z",
    "wilson_interval",
]
