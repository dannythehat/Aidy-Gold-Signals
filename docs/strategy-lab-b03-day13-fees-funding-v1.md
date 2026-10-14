# B03 Day 13 — Fees, Slippage Scenario and Overnight Funding

**Status:** Implementation submitted for CI; day-level PASS only after verified tests.

## Reusable research implementation
- `src/aidy/strategy_lab_fees_funding.py` accepts **Day11 source-matched BrokerProfile** and **Day12 quote-side ResearchRoundTrip**, including unchanged, SHA-pinned original quote bytes; recomputes entry/exit independently from the pinned source before accepting a result.
- All cash amounts use exact Decimal and **ROUND_HALF_UP to the nearest USD cent per cash event**, not binary floats, and a deterministic JSON serialisation. No user/broker connectivity.
- Commission: `commission_usd_per_lot_per_side × lots` separately for **entry and exit**, signed debits. Both sides are explicitly accounted for.
- Slippage: `costs.slippage_scenario_ticks × tick_value_USD_per_lot × lots`, applied as an additional **adverse scenario per transaction side**, not a live fill. It is distinct from the observed bid/ask spread and from Day12 explicit spread widening (already in Day12 gross P&L). Double-counting Day12 spread stress is prohibited.
- Funding: enumerate disclosed broker-server HH:MM rollover on **Monday–Friday broker-local dates**, exact server offset or IANA timezone from Day11; use signed long/short swap amount per lot and **three times** the charge on the declared triple-swap weekday. UTC conversions, weekday rollover timestamps and each multiplier are recorded per cash event. An ambiguous/nonexistent DST local rollover, exact rollover/fill collision, absent costs or holdings over 31 days fails closed.
- Auditable `CashEvent` list with USD signed cash and event UTC, plus `CostedRoundTrip` gross price P&L, separate commission, slippage, funding totals and net USD. The check `net = cent-rounded spread-aware gross + sum(exact cent-rounded cash legs)` is mandatory.
- **No broker holiday calendar or Vantage-specific overnight funding proven**: event dates follow only the *explicit weekday and triple day rule in the illustrative BrokerProfile*. The outcome includes `broker_attested=false` and `provider_calendar_qualified=false` and remains scenario-based, not a certified trade ledger.

## Golden synthetic fixtures (100 oz/lot, 0.01 tick, USD2.50/lot/side fee, one tick adverse slippage per side)
At 0.1 lots, Day12 representative bid/ask path:

| Case | Gross after bid/ask spread | Commission | Slippage scenario | Funding | Net cash P&L |
|---|---:|---:|---:|---:|---:|
| Long, intraday | +$9.00 | -$0.50 | -$0.20 | $0.00 | +$8.30 |
| Short, intraday | -$11.00 | -$0.50 | -$0.20 | $0.00 | -$11.70 |
| Long, +2 spread-stress ticks per side | +$8.60 | -$0.50 | -$0.20 | $0.00 | +$7.90 |
| Short, +2 spread-stress ticks per side | -$11.40 | -$0.50 | -$0.20 | $0.00 | -$12.10 |
| Long, Tue+Wed server rollovers, flat price | -$1.00 | -$0.50 | -$0.20 | -$0.60 | -$2.30 |
| Short, Tue+Wed server rollovers, flat price | -$1.00 | -$0.50 | -$0.20 | +$0.31 | -$1.39 |

**Rounding detail:** for the short overnight case, two signed swap credits of `0.75 USD/lot × 0.1 lots × (1, 3)` produce **$0.08 and $0.23**, respectively, with separately rounded events ($0.31 in total). This is deliberate and verified. Broker booking/rounding practice might differ.

## Explicit limitations
- The only cost evidence is the internal *illustrative* Day11 fixture and Day12 synthetic quote source. These rates, costs and hours are **not** independently sourced to a Vantage contract.
- Swaps can be broker-price-point based, variable over time, account-specific, denominated in a different currency, and depend on holidays and DST. Such cases require new qualified contract models, exact broker evidence, and real session calendars; this v1 USD-per-lot-per-rollover model fails closed for other interpretations.
- The Day13 event list is a **single-trade cash-cost reconciliation**, not the fully append-only ledger in Day17, no strategy signals/order lifecycle, no financing exposure caps, and no live broker fills.
- Source historical tick ZIPs 2020–2026 are stored in private R2 but sorted derived quotes/warehouse/lawful commercial source use are still outstanding Day06 dependencies.
- No production writes, merges, live orders, GoldThinker access or hidden assumptions.

## Acceptance requirements
CI source compilation, Ruff and Day11+12+13 tests; independent script demonstrating long/short cash vectors and frozen source SHA256, including a Wednesday triple-rollover example. Attach exact job, commit, hashes and totals only once witnessed.
