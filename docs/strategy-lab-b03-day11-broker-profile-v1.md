# B03 Day 11 — BrokerProfile v1: evidence-bound XAUUSD contract

**Status: CODE WRITTEN, AWAITING CI.** This is isolated Strategy Lab code on the existing draft research branch; it cannot access brokerage credentials, customer trades, positions or MT5.

## Built
- `src/aidy/strategy_lab_broker_profile.py` defines immutable typed **BrokerProfile v1** and strict `from_wire`, `from_json`, `to_json` / `to_wire` contracts.
- Broker and account-type identifier; reference quote/account/profit/margin currency; XAUUSD contract ounces/lot, tick/point sizes, decimal digits, tick value per lot, min/max/step lots and broker stop/freeze constraints.
- Margin method deliberately **declared**, not universally assumed: currently exact USD notional divided by declared leverage. Alternative broker margin models must fail rather than silently use leverage.
- Commission per side, signed long/short swap costs, triple-swap weekday, rollover clock and explicit positive slippage scenario; no cost calculations or opening/closing fill simulation implemented until Days 12–13.
- Exact decimal-only arithmetic, bid/ask execution later. No conversion into EUR or other account/profit/margin currencies until real FX evidence is qualified; only explicit USD/USD gold contract supported in this stage.
- Server time model explicit fixed UTC offset or IANA timezone; an observed UTC timestamp must reproduce an observed broker-server clock to the minute. **HistData fixed UTC−05 is not assumed equal to a broker's trading-server clock.**
- Evidence source kind, original snapshot reference, captured-at timestamp, mandatory SHA-256; independently supplied source bytes are checked by SHA, parsed as a strict observation JSON and compared against **every** declared contract, margin, costs and clock field. A missing/contradictory/forged original is fail-closed.
- `BrokerQualification.real_broker_terms_qualified` is **always false** at this gate. Matching fixture source bytes proves internal model/code behaviour, not that a broker published/executed those numbers. A document merely claiming to be a terminal export is not an independent broker attestation.
- Unknown commission or swap fields can be represented as `null` only where structurally valid, but a complete-cost qualification blocks when any required cost is unknown. In particular an incomplete swap+rollover bundle is invalid.

## Actual AIDY production ownership
The existing repo's `docs/architecture.md` makes the boundary explicit: AIDY's active reference market feed is public independent Gold-API, not broker/follower account data; Super Signals alone handles Vantage execution and reconciliation. No MetaAPI token, Vantage account credentials, or GoldThinker secrets are needed, copied or touched. **No claimed Vantage-specific lots, swaps, server offset or real commissions.**

## Illustrative fixture and tests
The only bundled observation is `research/strategy_lab/fixtures/day11_illustrative_broker_observation.json`. It is **synthetic**, with arbitrarily chosen 100 oz/lot, USD0.01 price tick, USD1 tick value/lot, USD100 leverage ratio, commission USD2.50/lot/side, and a fixed UTC+02:00 clock. These figures are mathematically internally consistent; **they are NOT representations of Vantage, a real account, or trading fees anyone actually paid.**

CI tests independently check round-trip canonical JSON, SHA-matched exact source field provenance, tick value USD1/lot, USD265 margin for 0.1 lot at USD2650 with synthetic 100:1 leverage, lots grid, weekday rollover costs, IANA DST and fixed clock mapping, unsupported currencies/margin models, absent costs/invalid quotes, invalid direct-constructed profiles and false real-broker claims.

## Pending before real broker simulations
1. Get a genuinely timestamped and permitted **read-only** `symbol_info` / contract export, redacted of accounts, broker credentials and other identifying details, from the intended broker + account type. User/owner approval and source authenticity should be checked independently.
2. Source and verify commission schedule, XAUUSD tick economics, margin tier/leverage, swap long/short terms (possible points/currency conversion), rollover/daylight-saving behaviour. Track effective dates and contract changes. Do **not** derive any missing terms from HistData quote spreads.
3. Reconcile specified terms with at least one known independent broker contract/price observation and then enable the Day 12 bid/ask fill model.
4. This module is a data contract and exact arithmetic helpers, **not** a production-approved broker engine. Day 13 will implement actual commission/swap/slippage application and reconciled USD journal.

## Acceptance record
- Source and fixture hashes, exact CI run link, test count and result to be filled **only after real green CI**.
- Day 11 technical **schema/contract/source-identity** gate and separate **real broker qualification** gate must not be conflated.
