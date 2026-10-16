"""GoldThinker two-year bull/down regime qualification and selective comparison.

Frozen S010 sequence: real historical 2025 bullish-year baseline, then unchanged
2021 down-year baseline. Only after BOTH real years are profitable may a
source-specific analyst test up to two diagnosed small changes. Each accepted
hypothesis needs a second-year development result AND first-year unchanged
cross-check. Never use invented second-year numbers or mark 2025 unseen.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

REGIME_SOURCE_2021 = "https://www.gold.org/goldhub/research/gold-outlook-2022"
REGIME_SOURCE_2025 = (
    "https://www.gold.org/goldhub/research/gold-market-commentary-december-2025"
)
FROZEN_S010_YEARS = (2025, 2021)
REGIME_BY_YEAR = {2020: "bull_year", 2021: "down_year",
                  2022: "range_year", 2023: "bull_year",
                  2024: "bull_year", 2025: "bull_year"}
RULE_VERSION = "goldthinker.two_year_selective_analyst.v1"


@dataclass(frozen=True, slots=True)
class YearReport:
    year: int
    regime: str
    system: str
    rule_hash: str
    execution_cost_hash: str
    original_report_hash: str
    real_source_hash: str
    completed_real_months: int
    starting_usd: Decimal
    net_usd: Decimal
    return_pct: Decimal
    max_drawdown_pct: Decimal
    trades: int
    profit_factor: Decimal
    worst_trade_usd: Decimal
    has_protective_stop: bool
    leverage: Decimal

    def problems(self) -> list[str]:
        issues = []
        if self.regime != REGIME_BY_YEAR.get(self.year):
            issues.append("Regime must be prelabelled from independent gold market history")
        if (self.completed_real_months != 12 or self.trades < 20
                or self.net_usd <= 0 or self.return_pct <= 0
                or self.profit_factor <= 1 or self.starting_usd <= 0):
            issues.append("Full-year original not profitable with adequate real-source evidence")
        if self.max_drawdown_pct > 0 or self.worst_trade_usd >= 0:
            issues.append("Original risk ledger invalid")
        if any(not isinstance(h, str) or len(h) != 64
               or any(c not in "0123456789abcdef" for c in h)
               for h in (self.rule_hash, self.execution_cost_hash,
                         self.original_report_hash, self.real_source_hash)):
            issues.append("Missing independently source-fingerprinted original or prices")
        return issues


@dataclass(frozen=True, slots=True)
class SmallChange:
    key: str
    observed_weakness: str
    exact_change: str
    rationale: str


@dataclass(frozen=True, slots=True)
class VariantReport:
    year: int
    hypothesis_key: str
    modified_rule_hash: str
    original_report_hash: str
    same_cost_model: bool
    independently_replayed: bool
    full_real_year: bool
    net_usd: Decimal
    return_pct: Decimal
    max_drawdown_pct: Decimal


def eligibility(first: YearReport, second: YearReport | None = None) -> dict:
    if second is None:
        return {
            "status": "BLOCKED_FIRST_YEAR" if first.problems()
                      else "AWAIT_UNCHANGED_2021_DOWN_YEAR",
            "first": first.year,
            "second": None,
            "market_context": "2025 LBMA-PM gold +67%, 2021 approximately -4.3%",
            "improvements_allowed": False,
            "problems": first.problems(),
        }
    issues = first.problems() + second.problems()
    if first.system != second.system:
        issues.append("Original system changed")
    if first.system == "S010" and (first.year, second.year) != FROZEN_S010_YEARS:
        issues.append("S010 must preserve first run 2025 and second run 2021")
    if {first.regime, second.regime} != {"bull_year", "down_year"}:
        issues.append("Require genuinely different bull and declining market years")
    if first.year == second.year or first.real_source_hash == second.real_source_hash:
        issues.append("Cannot recycle same year or historical source")
    if (first.rule_hash != second.rule_hash
            or first.execution_cost_hash != second.execution_cost_hash
            or first.starting_usd != second.starting_usd):
        issues.append("Original rules, costs and starting cash changed between years")
    return {
        "status": "TWO_YEAR_PROMISING_ELIGIBLE_FOR_DIAGNOSTICS" if not issues
                  else "NOT_ELIGIBLE_OR_BLOCKED",
        "first": first.year,
        "first_regime": first.regime,
        "second": second.year,
        "second_regime": second.regime,
        "improvements_allowed": not issues,
        "problems": issues,
        "not_a_live_broker_certificate": True,
    }


def targeted_diagnosis(first: YearReport, second: YearReport) -> list[SmallChange]:
    """No random parameter optimisation; zero changes when no specific weakness."""
    if not eligibility(first, second)["improvements_allowed"]:
        return []
    suggestions = []
    if (not first.has_protective_stop and not second.has_protective_stop
            and min(first.worst_trade_usd / first.starting_usd,
                    second.worst_trade_usd / second.starting_usd)
            <= Decimal("-0.12")):
        suggestions.append(SmallChange(
            "atr3_stop", "Large loss concentration without a protective stop",
            "Original MA/RSI signals + single 3x preceding CLOSED H1 ATR stop",
            "Test reduction of severe losses without destroying useful recoveries",
        ))
    if (first.leverage > 2 and second.leverage > 2
            and min(first.max_drawdown_pct, second.max_drawdown_pct) <= -25):
        suggestions.append(SmallChange(
            "leverage2", "Large drawdown amplified by original leverage",
            "Keep source entry/exit rules; cap initial exposure at 2x",
            "Test if lower risk justifies lower expected return",
        ))
    return suggestions[:2]


def compare(first: YearReport, second: YearReport, hypothesis: SmallChange,
            second_variant: VariantReport, first_crosscheck: VariantReport) -> dict:
    """Last year run (2021) is the change test; first year (2025) cross-check.

    Changes must be IDENTICAL across years and costs held constant. Original
    yearly reports remain immutable and any failed tweaks are reported.
    """
    if not eligibility(first, second)["improvements_allowed"]:
        raise ValueError("Unchanged original has not passed two-year gate")
    if hypothesis not in targeted_diagnosis(first, second):
        raise ValueError("Hypothesis not justified by the actual trade evidence")
    if (second_variant.year != second.year or first_crosscheck.year != first.year
            or second_variant.hypothesis_key != hypothesis.key
            or first_crosscheck.hypothesis_key != hypothesis.key
            or second_variant.modified_rule_hash != first_crosscheck.modified_rule_hash
            or second_variant.modified_rule_hash == first.rule_hash):
        raise ValueError("Variant was refitted across years or not a genuine small change")
    for original, variant in ((second, second_variant), (first, first_crosscheck)):
        if (variant.original_report_hash != original.original_report_hash
                or not variant.same_cost_model or not variant.full_real_year
                or not variant.independently_replayed):
            raise ValueError("Not a matching real-year and cost-controlled variant report")
    comparison = []
    for original, variant in ((second, second_variant), (first, first_crosscheck)):
        increased_usd = variant.net_usd - original.net_usd
        reduced_dd = abs(original.max_drawdown_pct)-abs(variant.max_drawdown_pct)
        comparison.append({
            "year": original.year,
            "market": original.regime,
            "original_net_usd": str(original.net_usd),
            "variant_net_usd": str(variant.net_usd),
            "net_change_usd": str(increased_usd),
            "original_max_drawdown_pct": str(original.max_drawdown_pct),
            "variant_max_drawdown_pct": str(variant.max_drawdown_pct),
            "drawdown_reduction_points": str(reduced_dd),
            "profit_improved": increased_usd > 0,
            "risk_improved": reduced_dd > 0,
        })
    clearly_worse = any(
        v.net_usd <= 0 or (
            v.net_usd < o.net_usd
            and abs(v.max_drawdown_pct) >= abs(o.max_drawdown_pct)
        ) for o, v in ((second, second_variant), (first, first_crosscheck))
    )
    improved_both = all(
        v.net_usd > o.net_usd or
        abs(v.max_drawdown_pct) < abs(o.max_drawdown_pct)
        for o, v in ((second, second_variant), (first, first_crosscheck))
    )
    if clearly_worse:
        verdict = "REJECTED_KEEP_ORIGINAL"
    elif improved_both:
        verdict = "PROMISING_TWO_REGIME_COMPARISON_UNCONFIRMED"
    else:
        verdict = "MIXED_KEEP_ORIGINAL"
    return {
        "version": RULE_VERSION,
        "first_year": first.year,
        "second_year": second.year,
        "market_regime_sources": {
            "2021": REGIME_SOURCE_2021, "2025": REGIME_SOURCE_2025,
        },
        "original_results_never_edited": True,
        "hypothesis": {
            "key": hypothesis.key,
            "observed_gap": hypothesis.observed_weakness,
            "exact_change": hypothesis.exact_change,
            "rationale": hypothesis.rationale,
        },
        "last_year_trial_then_first_year_crosscheck": comparison,
        "verdict": verdict,
        "report_both_positive_and_failed_variants": True,
        "no_auto_promotion_to_live": True,
        "2025_was_already_examined_not_blind_oos": True,
        "true_market_spreads_swaps_and_margin_not_yet_qualified": True,
    }
