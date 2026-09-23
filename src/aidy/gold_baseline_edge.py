"""Does any AIDY subject beat the majority-class baseline it is actually competing with?

`gold_expert_directional_skill` asks whether a subject's committed calls agree with the
market more often than chance. This asks the harder and more useful question: does the
subject beat *doing nothing clever* - always answering the most common outcome in the
same sample.

Three traps this module exists to avoid, all of which flattered earlier readings:

1. **Scope fan-out.** The outcome ledger repeats each result across many scope keys, so
   counting rows inflates n several-fold. Callers must pass one scope only; the report
   script uses `gate_global`, the scope every subject actually falls back to.

2. **The wrong baseline.** The label is three-class - bullish, bearish OR neutral - so
   0.5 is not the bar. The bar is the majority class share *in that subject's own
   evaluated sample*, which on a trending sample can sit near 0.58.

3. **Multiple comparisons.** With ~100 subcalculators, several will look significant by
   luck. Verdicts are Bonferroni-corrected across the subjects actually tested, and a
   subject that only clears the uncorrected threshold is reported as exactly that.

It also separates two claims that are easy to conflate and have different remedies:

    vs the MAJORITY baseline - is the subject worth more than a constant answer?
    vs RANDOM (0.5)          - does the subject carry any information at all?

On 2026-09-23 the ensemble was far below the majority baseline (p=6.5e-05) yet NOT
significantly below random (p=0.14). That combination means "fails to exploit a drift",
not "reads the market backwards", and it is why `strategy_comparison` reports what
inverting would have earned: on that sample inverting still lost to always-bearish, so
the inversion was not exploitable and flipping any polarity would have been a mistake.

Read-only. Computes; changes no expert, no weight and no behaviour.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from math import erfc, exp, lgamma, log, log1p, sqrt

#: Frozen before the 2026-09-23 result was examined.
MIN_BASELINE_N = 20
ALPHA = 0.05
NOMINAL_Z = 1.959963984540054

DIRECTIONAL = frozenset({"bullish", "bearish"})
OUTCOME_CLASSES = ("bullish", "bearish", "neutral")

VERDICT_BEATS = "beats_baseline"
VERDICT_INVERTED = "significantly_worse_than_baseline"
VERDICT_NOMINAL_ONLY = "nominal_only_dies_under_correction"
VERDICT_NO_EVIDENCE = "no_evidence_of_difference"
VERDICT_INSUFFICIENT = "insufficient_sample"


def _log_binom_pmf(k: int, n: int, p: float) -> float:
    """Log pmf via lgamma.

    Deliberately not `comb(n, k) * p**k * ...`: that overflows to
    `OverflowError: int too large to convert to float` on a pooled sample of a few
    thousand, which is exactly the size this gets used at.
    """
    if p <= 0.0:
        return 0.0 if k == 0 else float("-inf")
    if p >= 1.0:
        return 0.0 if k == n else float("-inf")
    return (
        lgamma(n + 1)
        - lgamma(k + 1)
        - lgamma(n - k + 1)
        + k * log(p)
        + (n - k) * log1p(-p)
    )


def two_sided_binomial_p(k: int, n: int, p: float) -> float:
    """Doubled tail on the observed side. Conservative, and exact rather than normal."""
    if n <= 0:
        return 1.0
    if p <= 0.0 or p >= 1.0:
        return 1.0
    mean = n * p
    lo, hi = (k, n) if k >= mean else (0, k)
    total = 0.0
    for i in range(lo, hi + 1):
        lp = _log_binom_pmf(i, n, p)
        if lp != float("-inf"):
            total += exp(lp)
    return min(1.0, 2.0 * total)


def wilson_interval(k: int, n: int, *, z: float = NOMINAL_Z) -> tuple[float, float]:
    if n <= 0:
        return (0.0, 1.0)
    phat = k / n
    denom = 1.0 + z * z / n
    centre = (phat + z * z / (2 * n)) / denom
    half = z * sqrt(phat * (1 - phat) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def normal_two_sided_p(k: int, n: int, p: float) -> float:
    """For reporting a pooled figure where the exact tail is not the point."""
    if n <= 0 or p <= 0.0 or p >= 1.0:
        return 1.0
    z = (k / n - p) / sqrt(p * (1 - p) / n)
    return erfc(abs(z) / sqrt(2))


def majority_baseline(class_counts: Mapping[str, int]) -> float:
    total = sum(class_counts.values())
    if total <= 0:
        return 0.0
    return max(class_counts.values()) / total


@dataclass(frozen=True, slots=True)
class SubjectEdge:
    subject_type: str
    subject_id: str
    n: int
    correct: int
    class_counts: tuple[tuple[str, int], ...]
    accuracy: float
    baseline: float
    edge: float
    p_value: float
    corrected_alpha: float
    wilson: tuple[float, float]
    verdict: str

    @property
    def beats_baseline(self) -> bool:
        return self.verdict == VERDICT_BEATS


def assess_subject(
    *,
    subject_type: str,
    subject_id: str,
    n: int,
    correct: int,
    class_counts: Mapping[str, int],
    corrected_alpha: float,
) -> SubjectEdge:
    baseline = majority_baseline(class_counts)
    accuracy = (correct / n) if n else 0.0
    p_value = two_sided_binomial_p(correct, n, baseline) if n else 1.0
    counts = tuple(sorted((str(k), int(v)) for k, v in class_counts.items()))

    if n < MIN_BASELINE_N:
        verdict = VERDICT_INSUFFICIENT
    elif p_value < corrected_alpha:
        verdict = VERDICT_BEATS if accuracy > baseline else VERDICT_INVERTED
    elif p_value < ALPHA:
        verdict = VERDICT_NOMINAL_ONLY
    else:
        verdict = VERDICT_NO_EVIDENCE

    return SubjectEdge(
        subject_type=subject_type,
        subject_id=subject_id,
        n=n,
        correct=correct,
        class_counts=counts,
        accuracy=accuracy,
        baseline=baseline,
        edge=accuracy - baseline,
        p_value=p_value,
        corrected_alpha=corrected_alpha,
        wilson=wilson_interval(correct, n),
        verdict=verdict,
    )


def assess(rows: Sequence[Mapping[str, object]]) -> tuple[SubjectEdge, ...]:
    """Assess every subject with enough sample, correcting across those tested.

    The correction divides by the number of subjects that clear MIN_BASELINE_N, because
    those are the tests actually performed. Subjects below it are reported as
    insufficient and are not part of the family.
    """
    eligible = [row for row in rows if int(row.get("n") or 0) >= MIN_BASELINE_N]
    corrected = ALPHA / len(eligible) if eligible else ALPHA
    out = [
        assess_subject(
            subject_type=str(row.get("subject_type") or ""),
            subject_id=str(row.get("subject_id") or ""),
            n=int(row.get("n") or 0),
            correct=int(row.get("correct") or 0),
            class_counts={
                name: int((row.get("class_counts") or {}).get(name, 0))  # type: ignore[union-attr]
                for name in OUTCOME_CLASSES
            },
            corrected_alpha=corrected,
        )
        for row in rows
    ]
    return tuple(sorted(out, key=lambda item: (item.p_value, item.subject_id)))


@dataclass(frozen=True, slots=True)
class StrategyComparison:
    """What the calls were worth, against the alternatives they must beat.

    Restricted to directional outcomes: a neutral outcome cannot reward or punish a
    directional call, and leaving those in silently lowers every strategy together.
    """

    n: int
    follow_correct: int
    invert_correct: int
    majority_correct: int
    majority_class: str
    follow_accuracy: float
    invert_accuracy: float
    majority_accuracy: float
    random_accuracy: float
    p_vs_majority: float
    p_vs_random: float

    @property
    def inversion_is_exploitable(self) -> bool:
        """Inverting only means anything if it beats the constant answer."""
        return self.invert_accuracy > self.majority_accuracy


def strategy_comparison(
    confusion: Iterable[Mapping[str, object]],
) -> StrategyComparison:
    """Compare following, inverting and a constant answer over a said/happened table.

    Each row carries `said`, `happened` and `n`.
    """
    counts: dict[tuple[str, str], int] = {}
    for row in confusion:
        said = str(row.get("said") or "").strip().lower()
        happened = str(row.get("happened") or "").strip().lower()
        if said in DIRECTIONAL and happened in DIRECTIONAL:
            counts[(said, happened)] = counts.get((said, happened), 0) + int(
                row.get("n") or 0
            )

    total = sum(counts.values())
    follow = sum(n for (said, happened), n in counts.items() if said == happened)
    invert = total - follow
    outcome_totals = {
        cls: sum(n for (_, happened), n in counts.items() if happened == cls)
        for cls in sorted(DIRECTIONAL)
    }
    majority_class = (
        max(outcome_totals, key=lambda cls: outcome_totals[cls]) if total else ""
    )
    majority = outcome_totals.get(majority_class, 0)
    majority_rate = (majority / total) if total else 0.0

    return StrategyComparison(
        n=total,
        follow_correct=follow,
        invert_correct=invert,
        majority_correct=majority,
        majority_class=majority_class,
        follow_accuracy=(follow / total) if total else 0.0,
        invert_accuracy=(invert / total) if total else 0.0,
        majority_accuracy=majority_rate,
        # A 50/50 caller into a p/(1-p) market scores 0.5 whatever p is.
        random_accuracy=0.5,
        p_vs_majority=normal_two_sided_p(follow, total, majority_rate) if total else 1.0,
        p_vs_random=normal_two_sided_p(follow, total, 0.5) if total else 1.0,
    )


__all__ = [
    "ALPHA",
    "MIN_BASELINE_N",
    "OUTCOME_CLASSES",
    "VERDICT_BEATS",
    "VERDICT_INSUFFICIENT",
    "VERDICT_INVERTED",
    "VERDICT_NOMINAL_ONLY",
    "VERDICT_NO_EVIDENCE",
    "StrategyComparison",
    "SubjectEdge",
    "assess",
    "assess_subject",
    "majority_baseline",
    "normal_two_sided_p",
    "strategy_comparison",
    "two_sided_binomial_p",
    "wilson_interval",
]
