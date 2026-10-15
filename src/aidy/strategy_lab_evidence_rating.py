"""AIDY Day28: ORIGINAL nine-factor score governance, not fabricated alpha.

The 9/100 owner-approved factor weights are locked here. All numeric evidence
must be independently source qualified by a future trusted evidence adapter.
Historical BID-only directions and synthetic cash-ledger demonstrations cannot
be promoted to authentic net XAUUSD strategy performance by filling in flags.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from decimal import Decimal
from hashlib import sha256

FACTOR_WEIGHTS = (
    ("net_trading_expectancy", 30),
    ("out_of_sample_robustness", 15),
    ("market_condition_performance", 10),
    ("drawdown_and_risk", 10),
    ("realistic_trading_costs", 10),
    ("rule_clarity", 10),
    ("adequate_sample_size", 5),
    ("broker_compatibility", 5),
    ("independent_reproducibility", 5),
)
TOTAL_WEIGHT = sum(w for _, w in FACTOR_WEIGHTS)
SCHEMA = "aidy.strategy_lab.nine_factor_evidence.v1"
POLICY_VERSION = "owner_9_factor_2026_10_15.v1"
ALL_STATUSES = frozenset(("VERIFIED", "UNKNOWN", "INSUFFICIENT", "CONTRADICTED"))
ORIGINS = frozenset(("internal_synthetic_fixture", "retrospective_bid_only",
                     "unqualified_customer_claim", "independent_costed_xauusd"))
CATEGORIES = frozenset(("RED_REJECT", "ORANGE_INVESTIGATE", "GREEN_HIGH_PRIORITY"))
FACTORS = dict(FACTOR_WEIGHTS)

if TOTAL_WEIGHT != 100 or len(FACTOR_WEIGHTS) != 9:
    raise RuntimeError("locked original nine-factor weight contract violated")


def _digest(obj: object) -> str:
    return sha256(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _sha(value: str) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        c in "0123456789abcdef" for c in value
    )


@dataclass(frozen=True)
class FactorFinding:
    factor: str
    status: str
    awarded_points: int | None
    source_sha256: str | None
    explanation: str

    def validate(self) -> None:
        if self.factor not in FACTORS or self.status not in ALL_STATUSES:
            raise ValueError("unsupported factor or evidence status")
        if not isinstance(self.explanation, str) or not 3 <= len(self.explanation) <= 250:
            raise ValueError("explain why factor was or was not independently verified")
        if self.status == "VERIFIED":
            if (type(self.awarded_points) is not int
                    or not 0 <= self.awarded_points <= FACTORS[self.factor]
                    or not _sha(self.source_sha256)):
                raise ValueError("verified factor requires bounded integer and exact source SHA")
        elif self.awarded_points is not None or self.source_sha256 is not None:
            raise ValueError("unqualified factor must preserve null score and provenance")


@dataclass(frozen=True)
class EvidenceBasis:
    """Source/trial/trading qualification CHECKS, NOT self-signed attestations.

    Later ingestion must independently verify source, journal, trading costs,
    trial chain and benchmark semantics before setting qualification booleans.
    This module is a policy calculator, not an attestation authority.
    """
    origin: str
    strategy_rule_sha256: str
    historical_input_sha256: str
    original_run_sha256: str | None
    verified_costed_trade_ledger_sha256: str | None
    oos_holdout_trial_tip_sha256: str | None
    fair_matched_benchmark_sha256: str | None
    historical_source_independently_verified: bool
    actual_bid_ask_costed_trades_independently_replayed: bool
    chronological_oos_trading_independently_verified: bool
    fair_benchmark_independently_verified: bool
    full_trial_family_independently_registered: bool
    historical_trades: int | None
    observed_net_expectancy_usd: Decimal | None
    observed_benchmark_edge_usd: Decimal | None
    independently_verified_unacceptable_risk: bool = False

    def validate(self) -> None:
        if self.origin not in ORIGINS:
            raise ValueError("unsupported source/evidence origin")
        if not _sha(self.strategy_rule_sha256) or not _sha(self.historical_input_sha256):
            raise ValueError("original source and rule hash required")
        for name in ("original_run_sha256", "verified_costed_trade_ledger_sha256",
                     "oos_holdout_trial_tip_sha256", "fair_matched_benchmark_sha256"):
            value = getattr(self, name)
            if value is not None and not _sha(value):
                raise ValueError("malformed source/ledger/trial proof SHA")
        for name in ("historical_source_independently_verified",
                     "actual_bid_ask_costed_trades_independently_replayed",
                     "chronological_oos_trading_independently_verified",
                     "fair_benchmark_independently_verified",
                     "full_trial_family_independently_registered",
                     "independently_verified_unacceptable_risk"):
            if type(getattr(self, name)) is not bool:
                raise ValueError("qualification is a boolean, not an implied truthy flag")
        if self.historical_trades is not None and (
                type(self.historical_trades) is not int
                or not 0 <= self.historical_trades <= 1_000_000):
            raise ValueError("invalid historically verified sample count")
        for name in ("observed_net_expectancy_usd", "observed_benchmark_edge_usd"):
            x = getattr(self, name)
            if x is not None and (not isinstance(x, Decimal) or not x.is_finite()):
                raise ValueError("P&L and baseline improvement must be finite Decimal")
        if self.origin != "independent_costed_xauusd" and (
                self.actual_bid_ask_costed_trades_independently_replayed
                or self.chronological_oos_trading_independently_verified
                or self.fair_benchmark_independently_verified
                or self.independently_verified_unacceptable_risk):
            raise ValueError("synthetic or bid-only source cannot claim independent trade proof")
        if self.historical_trades == 0 and (
                self.observed_net_expectancy_usd is not None
                or self.observed_benchmark_edge_usd is not None):
            raise ValueError("zero trades cannot have observed trading expectancy or edge")

    def qualified_for_economic_scoring(self) -> bool:
        return (
            self.origin == "independent_costed_xauusd"
            and self.historical_source_independently_verified
            and self.actual_bid_ask_costed_trades_independently_replayed
            and self.chronological_oos_trading_independently_verified
            and self.fair_benchmark_independently_verified
            and self.full_trial_family_independently_registered
            and self.historical_trades is not None and self.historical_trades >= 30
            and all(_sha(x) for x in (
                self.original_run_sha256,
                self.verified_costed_trade_ledger_sha256,
                self.oos_holdout_trial_tip_sha256,
                self.fair_matched_benchmark_sha256,
            ))
            and self.observed_net_expectancy_usd is not None
            and self.observed_benchmark_edge_usd is not None
        )

    def to_wire(self) -> dict:
        return {
            k: format(v, "f") if isinstance(v, Decimal) else v
            for k, v in asdict(self).items()
        }


@dataclass(frozen=True)
class EvidenceRating:
    schema: str
    policy_version: str
    scoring_policy_sha256: str
    evidence_input_sha256: str
    score_out_of_100: int | None
    score_status: str
    governance: str
    optimisation_suggestions_eligible: bool
    permitted_action: str
    missing_evidence: tuple[str, ...]
    veto_reasons: tuple[str, ...]
    factor_scores: tuple[FactorFinding, ...]
    factor_weights: tuple[tuple[str, int], ...]
    historical_profitability_qualified: bool
    automatically_authorised_for_live_trading: bool = False

    def to_wire(self) -> dict:
        return {
            **asdict(self),
            "factor_scores": [asdict(item) for item in self.factor_scores],
            "factor_weights": [list(x) for x in self.factor_weights],
            "missing_evidence": list(self.missing_evidence),
            "veto_reasons": list(self.veto_reasons),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_wire(), sort_keys=True, separators=(",", ":"))


def rate_strategy_evidence(
    basis: EvidenceBasis,
    findings: tuple[FactorFinding, ...],
) -> EvidenceRating:
    """Never turn internal fixtures, ambiguous source claims or missing factors
    into a synthetic 0/100 or into a GREEN ranking.

    For a genuine qualified externally checked strategy, raw factors are still
    independent evidence-review inputs: this calculator does not authenticate
    uploaded claims or grant access to trading accounts.
    """
    if not isinstance(basis, EvidenceBasis) or not isinstance(findings, tuple):
        raise ValueError("qualified evidence basis and immutable factor tuple required")  # noqa: TRY004
    basis.validate()
    if len(findings) != len(FACTOR_WEIGHTS):
        raise ValueError("exactly original nine independent factors required")
    if any(not isinstance(x, FactorFinding) for x in findings):
        raise ValueError("factor evidence must use typed reviewed findings")
    for expected, finding in zip(FACTOR_WEIGHTS, findings, strict=True):
        finding.validate()
        if finding.factor != expected[0]:
            raise ValueError("factor must match original owner ordering, no duplicates")
    provenance = [x.source_sha256 for x in findings if x.status == "VERIFIED"]
    if len(provenance) != len(set(provenance)):
        # Same source artifact may support several facts, but treating its
        # identical hash as independent corroboration would be misleading.
        raise ValueError("independent factor findings require distinct evidence receipts")

    qualified = basis.qualified_for_economic_scoring()
    missing = []
    if not qualified:
        missing.append("independently_qualified_costed_bidask_oos_benchmark_and_trial_proof")
    missing.extend(x.factor + ":" + x.status
                   for x in findings if x.status != "VERIFIED")
    if basis.historical_trades is None or basis.historical_trades < 30:
        missing.append("at_least_30_independent_completed_trades")
    if not all(x.status == "VERIFIED" for x in findings):
        missing.append("incomplete_nine_factor_independent_review")
    vetoes = []
    score: int | None = None
    if qualified and not missing:
        score = sum(x.awarded_points for x in findings if x.awarded_points is not None)
        if not 0 <= score <= TOTAL_WEIGHT:
            raise ValueError("invalid nine-factor total")
    if qualified:
        if basis.independently_verified_unacceptable_risk:
            vetoes.append("verified_unacceptable_risk")
        if basis.observed_net_expectancy_usd is not None and basis.observed_net_expectancy_usd <= 0:
            vetoes.append("nonpositive_net_expectancy")
        if basis.observed_benchmark_edge_usd is not None and basis.observed_benchmark_edge_usd <= 0:
            vetoes.append("nonpositive_advantage_over_matched_benchmark")
    factors = {x.factor: x for x in findings}
    green_requirements = (
        factors["net_trading_expectancy"].awarded_points is not None
        and factors["net_trading_expectancy"].awarded_points >= 21
        and factors["out_of_sample_robustness"].awarded_points is not None
        and factors["out_of_sample_robustness"].awarded_points >= 11
        and factors["drawdown_and_risk"].awarded_points is not None
        and factors["drawdown_and_risk"].awarded_points >= 7
        and factors["realistic_trading_costs"].awarded_points is not None
        and factors["realistic_trading_costs"].awarded_points >= 7
        and factors["independent_reproducibility"].awarded_points is not None
        and factors["independent_reproducibility"].awarded_points >= 4
    )
    if qualified and vetoes:
        governance = "RED_REJECT"
    elif score is not None and score >= 80 and green_requirements:
        governance = "GREEN_HIGH_PRIORITY"
    elif score is not None and score < 50:
        governance = "RED_REJECT"
    else:
        governance = "ORANGE_INVESTIGATE"
    optimisation = (
        governance == "GREEN_HIGH_PRIORITY" and score is not None
        and qualified and not vetoes
    )
    # Suggestion eligibility here is governed by the strongest category.
    # Actual code modification still requires separate customer authorisation.
    action = (
        "PROPOSE_EXPLAINABLE_OPTIMISATION_WITH_SEPARATE_USER_APPROVAL"
        if optimisation else
        "REJECT_NO_OPTIMISATION" if governance == "RED_REJECT"
        else "REQUEST_INDEPENDENT_EVIDENCE_NO_OPTIMISATION"
    )
    return EvidenceRating(
        SCHEMA, POLICY_VERSION, _digest({
            "policy": POLICY_VERSION,
            "weights": FACTOR_WEIGHTS,
            "green_minimum": 80,
            "red_below": 50,
            "green_factor_gates": [21, 11, 7, 7, 4],
            "min_trades": 30,
        }),
        _digest({"basis": basis.to_wire(), "factors": [asdict(x) for x in findings]}),
        score,
        "AVAILABLE_VERIFIED_NINE_FACTOR" if score is not None
        else "WITHHELD_UNQUALIFIED_OR_INCOMPLETE",
        governance, optimisation, action,
        tuple(missing), tuple(vetoes), findings, FACTOR_WEIGHTS,
        qualified and not vetoes and score is not None
        and basis.observed_net_expectancy_usd > 0
        and basis.observed_benchmark_edge_usd > 0,
    )
