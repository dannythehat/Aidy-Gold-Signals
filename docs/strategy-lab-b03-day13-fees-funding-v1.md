# B03 Day 13 — Fees, Slippage Scenario and Overnight Funding

**Status: DAY 13 TECHNICAL ACCEPTANCE PASSED (14 October 2026)** — research-only scope; B03 owner stage not accepted.

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

## Verified Day 13 CI acceptance evidence

- [GitHub Actions successful run 38553163892](https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/38553163892), job `115815754605`: **149 Day11+Day12+Day13 tests PASSED**, strict Ruff compilation and quality checks PASSED (one non-fatal pre-existing pytest configuration warning).
- Passing source/test commit `1d1927c84d2f2fd203fd445284165e79ab61dd8d`. Source module `src/aidy/strategy_lab_fees_funding.py`, tests `tests/test_strategy_lab_fees_funding.py`.
- Frozen actual illustrative source hashes, checked by GitHub CI with `sha256sum`: Day11 broker observation `1302931d9cc35a04d979b178e113cd6bf06315d1a1c75850d7f4403ba3dc44df`; Day12 bid/ask quote snapshot `6f782e6cd8580d93a250950f8d0a1461ffd026a66e1d807014c2cc1943e21066`.
- Independent CI outputs: intraday long net `8.30`, intraday short net `-11.70`, Tuesday/Wednesday overnight long `-2.30`, overnight short `-1.39`, each event list reconciled exactly in USD cents.
- Result SHA-256s (result JSON): long intraday `e5bf7a48390a67662a65f05c539b911e84b2d74770dbd8c50d7f073c5e8c8b32`, short intraday `440c51eae1be96cdab088737611859eeda08e2106dcc6784aeee1def08dee04a`, long overnight `87886b36a93dc5e88f1d086214da0eb50fe1ca368e2c594490534ee315f47dba`, short overnight `c41162c4d8769a5889e290608f35e1675a0109e9613f0d376c85880d241c884b`.
- All examples have `actual_trade_executed=false`, `real_broker_terms_verified=false`, `vendor_holiday_calendar_verified=false` in CI. This is not evidence of Vantage profitability or funding schedule fidelity. The Day17 portfolio-level append-only cash/equity ledger is separate and not yet built.

**Day 13 acceptance is a day-level implementation+test PASS only.** Day14 order lifecycle state machine NEXT; B03 owner-stage approval, real broker evidence, historical tick chronology normalization and licensing remain OPEN.
