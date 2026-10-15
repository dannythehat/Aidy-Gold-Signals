"""Day25: source-pinned same-window naive XAUUSD baselines and cost stress.

This is an ENGINEERING comparator, never a demonstration of market alpha.
Reuse Day12 quote-side fills and Day13 cash events, so observed spread is
already paid via fills and must NEVER be subtracted as a second cash cost.
The blind scheduled LONG benchmark shares entry/exit and position exposure
with a Day19 signal and is only an ACCOUNTING CONTROL, not an independent
out-of-sample benchmark. Short-side counterfactual is a separate diagnostic.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal
from hashlib import sha256

from aidy.strategy_lab_bidask_execution import (
    QuoteTape,
    SpreadScenario,
    research_round_trip,
)
from aidy.strategy_lab_broker_profile import BrokerProfile
from aidy.strategy_lab_fees_funding import apply_research_costs
from aidy.strategy_lab_reference_run import ReferenceResult

CENT = Decimal("0.01")
SCHEMA = "aidy.strategy_lab.matched_baselines_cost_stress.v1"
POLICY = (
    ("base", 0, Decimal(1)),
    ("adverse", 2, Decimal("1.5")),
    ("severe", 5, Decimal(2)),
)


def _cash(x: Decimal) -> Decimal:
    return x.quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class ScenarioResult:
    name: str
    extra_spread_ticks_per_side: int
    cash_charge_multiplier: Decimal
    candidate_gross_quote_side_usd: Decimal
    candidate_commission_usd: Decimal
    candidate_slippage_usd: Decimal
    candidate_funding_usd: Decimal
    candidate_net_usd: Decimal
    independent_blind_clock_long_net_usd: Decimal
    matched_exposure_difference_usd: Decimal
    blind_clock_short_net_usd: Decimal
    source_quote_snapshot_sha256: str
    broker_profile_sha256: str


@dataclass(frozen=True)
class BaselineAudit:
    schema: str
    policy_sha256: str
    original_day19_rule_sha256: str
    source_day19_candle_sha256: str
    quote_snapshot_sha256: str
    broker_source_sha256: str
    reference_journal_tip_sha256: str
    scenario_results: tuple[ScenarioResult, ...]
    accounting_control_pass: bool
    independent_strategy_benchmark_completed: bool = False
    genuine_strategy_alpha_qualified: bool = False
    native_broker_execution_verified: bool = False
    sample_origin: str = "internal_synthetic_fixed_window_not_historical_edge"

    def to_wire(self) -> dict:
        def encode(x):
            if isinstance(x, Decimal):
                return format(x, "f")
            if isinstance(x, tuple):
                return [encode(y) for y in x]
            if isinstance(x, dict):
                return {k: encode(v) for k, v in x.items()}
            return x
        return encode(asdict(self))

    def to_json(self) -> str:
        return json.dumps(self.to_wire(), sort_keys=True, separators=(",", ":"))


def _scenario_pnl(
    profile: BrokerProfile, broker_source_bytes: bytes, quote_tape: QuoteTape,
    *, direction: str, lots: str, entry_closed, exit_closed,
    extra_ticks_per_side: int, cash_multiplier: Decimal,
) -> tuple[Decimal, Decimal, Decimal, Decimal, Decimal, str]:
    if (not isinstance(cash_multiplier, Decimal)
            or not cash_multiplier.is_finite()
            or not Decimal(1) <= cash_multiplier <= Decimal(5)):
        raise ValueError("bounded Decimal cost multiplier required")
    trip = research_round_trip(
        profile, broker_source_bytes, quote_tape, direction=direction,
        lots=lots, entry_signal_closed_at_utc=entry_closed,
        exit_signal_closed_at_utc=exit_closed,
        scenario=SpreadScenario(extra_ticks_per_side),
    )
    paid = apply_research_costs(profile, broker_source_bytes, quote_tape, trip)
    cash_events = paid.events
    if any(x.kind not in ("commission", "slippage_scenario") for x in cash_events):
        # Day25's fixed-window demonstration has NO funding/rollovers. Never
        # accidentally scale swap credits, or skip a funding ledger leg.
        raise ValueError("unsupported funding leg in intraday stress scenario")
    if len(cash_events) != 4 or any(x.usd > 0 for x in cash_events):
        raise ValueError("unexpected Day13 cost event attribution")
    extra_charge = sum(
        (_cash(e.usd * cash_multiplier) for e in cash_events), Decimal(0)
    )
    commission = sum(
        (_cash(e.usd * cash_multiplier) for e in cash_events
         if e.kind == "commission"), Decimal(0)
    )
    slippage = sum(
        (_cash(e.usd * cash_multiplier) for e in cash_events
         if e.kind == "slippage_scenario"), Decimal(0)
    )
    funding = paid.funding_usd
    net = _cash(paid.quote_gross_usd + extra_charge + funding)
    if net != _cash(paid.quote_gross_usd + commission + slippage + funding):
        raise ValueError("scenario cost attribution does not reconcile")
    if net > paid.quote_gross_usd or (cash_multiplier == 1 and net != paid.net_usd):
        raise ValueError("scenario invents favourable net execution")
    # No observed bid/ask spread is counted as a cash event a second time.
    return paid.quote_gross_usd, commission, slippage, funding, net, paid.broker_profile_sha256


def compare_day19_fixed_window(
    reference: ReferenceResult, *,
    profile: BrokerProfile, broker_source_bytes: bytes,
    quote_tape: QuoteTape,
    source_candle_sha256: str,
    entry_signal_closed_at_utc,
    exit_signal_closed_at_utc,
) -> BaselineAudit:
    """Audit one Day19 candidate against clock-only controls on the same tape.

    The clock-long naive control has exactly the candidate's direction,
    quantity, entry/exit and session exposure. Matching it proves only
    integrity of arithmetic; no independent comparison with selection-free
    real prices has been made. The clock-short diagnostic reverses direction.
    """
    if not isinstance(reference, ReferenceResult):
        raise ValueError("required genuine Day19 internal reference receipt")  # noqa: TRY004
    if (reference.actual_broker_attested or not reference.rule_sha256
            or reference.closed_candle_sha256 != source_candle_sha256
            or reference.quote_sha256 != quote_tape.snapshot_sha256
            or reference.opening_cash_usd != Decimal(10000)
            or reference.closing_cash_usd != Decimal("10008.30")
            or reference.net_usd != Decimal("8.30")
            or reference.entry_utc != entry_signal_closed_at_utc + timedelta(seconds=1)
            or reference.exit_utc != exit_signal_closed_at_utc + timedelta(seconds=1)):
        raise ValueError("Day19 reference is not the frozen known-answer fixture")
    if (entry_signal_closed_at_utc.utcoffset() != timedelta(0)
            or exit_signal_closed_at_utc.utcoffset() != timedelta(0)
            or exit_signal_closed_at_utc - entry_signal_closed_at_utc != timedelta(minutes=5)):
        raise ValueError("frozen session/time exposure mismatch")
    results = []
    for name, ticks, multiplier in POLICY:
        gross, commission, slip, funding, candidate_net, fingerprint = _scenario_pnl(
            profile, broker_source_bytes, quote_tape,
            direction="long", lots="0.1",
            entry_closed=entry_signal_closed_at_utc,
            exit_closed=exit_signal_closed_at_utc,
            extra_ticks_per_side=ticks, cash_multiplier=multiplier,
        )
        # Independently call the actual quote/cash event engines for each
        # predeclared blind clock baseline, not a mathematical gross return.
        _, _, _, _, naive_long, _ = _scenario_pnl(
            profile, broker_source_bytes, quote_tape,
            direction="long", lots="0.1",
            entry_closed=entry_signal_closed_at_utc,
            exit_closed=exit_signal_closed_at_utc,
            extra_ticks_per_side=ticks, cash_multiplier=multiplier,
        )
        _, _, _, _, naive_short, _ = _scenario_pnl(
            profile, broker_source_bytes, quote_tape,
            direction="short", lots="0.1",
            entry_closed=entry_signal_closed_at_utc,
            exit_closed=exit_signal_closed_at_utc,
            extra_ticks_per_side=ticks, cash_multiplier=multiplier,
        )
        if (name == "base" and (
            gross != reference.gross_usd
            or commission != reference.commissions_usd
            or slip != reference.slippage_usd
            or funding != reference.swaps_usd
            or candidate_net != reference.net_usd
        )):
            raise ValueError("Day12/13 counterfactual differs from Day19 journal")
        if candidate_net != naive_long:
            raise ValueError("same-window same-exposure baseline accounting mismatch")
        results.append(ScenarioResult(
            name, ticks, multiplier, gross, commission, slip, funding,
            candidate_net, naive_long, candidate_net - naive_long,
            naive_short, quote_tape.snapshot_sha256, fingerprint,
        ))
    if any(results[i].candidate_net_usd < results[i+1].candidate_net_usd
           for i in range(len(results)-1)):
        raise ValueError("higher execution cost made candidate more profitable")
    policy_sha = sha256(json.dumps(
        [(name, ticks, str(multiplier)) for name, ticks, multiplier in POLICY],
        separators=(",", ":"),
    ).encode()).hexdigest()
    return BaselineAudit(
        SCHEMA, policy_sha, reference.rule_sha256,
        reference.closed_candle_sha256, quote_tape.snapshot_sha256,
        sha256(broker_source_bytes).hexdigest(), reference.journal_tip_sha256,
        tuple(results), True,
    )
