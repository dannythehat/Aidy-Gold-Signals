# B03 Day 12 — Bid/Ask Next-Quote Execution Contract

**Status: DAY 12 TECHNICAL ACCEPTANCE PASSED (14 October 2026).** Isolated AIDY Strategy Lab development branch. No real trading authority and no owner-approved B03 release.

## Implemented contract

`src/aidy/strategy_lab_bidask_execution.py` adds the following actual reusable Python interfaces:

- `QuoteTape.from_snapshot(source_json_bytes, expected_sha256=...)`: parses genuine caller-supplied frozen quote snapshot bytes into ordered UTC `BidAskQuote` rows with exact decimal bid/ask, explicit provenance and source identity. Rejects partial/mid-only, duplicated, crossed, unbounded, future-fabricated or non-UTC/unsorted quote inputs rather than synthesising spread. Each backtest call replays the **original frozen bytes** and compares the parsed quote tape to prevent externally constructed objects being passed as source-verified.
- `SpreadScenario(extra_ticks_per_side=N)`: optional explicit **adverse stress**; subtracts N broker ticks from bid and adds N ticks to ask. This is a synthetic *scenario*, never a claim about actual historical or broker spreads. Zero means original bid and ask unchanged.
- `research_round_trip(profile, broker_source_bytes, quote_tape, direction='long'|'short', lots='...', entry_signal_closed_at_utc=..., exit_signal_closed_at_utc=...)`: validates Day 11 BrokerProfile and real supplied broker evidence bytes, lot grid, immutable quote source, strictly future quote timing and freshness before constructing side-aware `SideFill` entry/exit pairs. Outputs explicit raw/effective bid/ask, chosen side and price, quote index, UTC timestamps, quote/source/spec fingerprints, mark-to-quote gross USD and tick move.
- **Long:** ENTER buy at **ask**, EXIT sell at **bid**. **Short:** ENTER sell at **bid**, EXIT buy at **ask**.
- **No lookahead:** even a quote with timestamp exactly equal to a closed-bar signal is not eligible. First quote must be strictly later (`>` timestamp). A gap longer than the explicit allowed `max_lag_seconds` (1–300, default 60) is rejected instead of pretending the market was open or replaying a distant stale quote. Exit must occur after entry fill on a later quote. Unordered/repeated-timestamp historical feeds fail until Day 06 normalized derived data has provenance.
- **Quote-side gross USD only:** direction-adjusted price difference times declared USD ounces/lot times validated lots. Output `costs_included=false`, `real_broker_terms_qualified=false`. No commissions, swaps, slippage charges, margin calls, stop/target ambiguity, hedge/netting, intra-tick lifecycle, FX conversion or live fill claims. These are distinct Day 13+ gates.

## Isolated arithmetic acceptance fixture (never claim broker parity)

`research/strategy_lab/fixtures/day12_illustrative_bidask_quotes.json` is a **synthetic, internally authored** quote file (its `source_class=internal_fixture`); it is paired with the explicitly illustrative Day 11 USD gold broker contract fixture. Closed-entry signal is 14:00:00 UTC; strictly subsequent entry quote 14:00:01 has **bid 2650.00 / ask 2650.10**. Closed-exit signal is 14:05:00 UTC; next eligible exit quote 14:05:01 has **bid 2651.00 / ask 2651.10**.

| Case | Enter | Exit | 0.1-lot gross USD before commission, swaps, slippage |
|---|---:|---:|---:|
| Long, unchanged observed fixture spread | Buy 2650.10 | Sell 2651.00 | +9.00 |
| Short, unchanged observed fixture spread | Sell 2650.00 | Buy 2651.10 | −11.00 |
| Long, additional adverse two ticks **per side** | Buy 2650.12 | Sell 2650.98 | +8.60 |
| Short, additional adverse two ticks **per side** | Sell 2649.98 | Buy 2651.12 | −11.40 |

Price source reality is **not** inferred from fixture examples. `quote_source_class` and `broker_source_state` remain independently recorded in every result. The quote snapshot's `source_archive_sha256` describes the intended archival source; the sample `ffffffff…` is a clearly fictitious fixture marker, not a claimed 2024–26 ZIP checksum. Only the embedded original quote snapshot bytes' digest is cryptographically frozen by this stage.

## Security, source authenticity, research limits

- Source-matched Day 11 broker JSON is necessary for a *research-only* fill. A broker-labelled JSON export remains `BROKER_EVIDENCE_MATCHED_UNATTESTED` even with its hash matched; Day 11 explicitly cannot independently qualify Vantage's real contract. AIDY code cannot use GoldThinker, Super Signals, broker credentials, terminals or accounts.
- A `histdata_retrospective_bid_ask` quote label does not magically turn historical third-party prices into executable Vantage quotes. The original source ZIP must be separately checked via B01 provenance and data-rights gates; date-sorted, source-aware derivatives must be qualified prior to use.
- Transaction costs beyond explicit spread scenario are **not deducted**. The word “gross” in this module means **spread-aware price P&L before commission, swap, slippage, fees and other effects**.
- The Day 12 engine is not a future-proof guarantee that real brokers accept an order at the quoted top of book; no latency or market-impact certainty is inferred.
- SHA-256 source integrity and consistent decimals are tested independently from provider-authenticity claims. The fixture does not demonstrate actual execution with an independent broker.

## Acceptance evidence

- **Passing CI:** [run 38551416776](https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/38551416776), job `115810011674`, code/test commit `3e75142ffcef9185485830396979b69df95190ca`. Strict Ruff and source compilation PASS. **135 Day11+Day12 automated tests PASSED** (one non-failing existing pytest configuration warning).
- Frozen **original illustrative bid/ask quote JSON SHA256:** `6f782e6cd8580d93a250950f8d0a1461ffd026a66e1d807014c2cc1943e21066`, calculated independently by GitHub CI with `sha256sum`. Day11 broker-contract fixture SHA256: `1302931d9cc35a04d979b178e113cd6bf06315d1a1c75850d7f4403ba3dc44df`.
- Exact CI-known answers: long +USD 9.000, short −USD 11.000; scenario +2 adverse ticks per side yields long +USD 8.600, short −USD 11.400, each at 0.1 illustrative lots. Entry selected index 1, exit index 3 after strict closed-signal timestamps.
- Deterministic Day12 baseline result SHA256: long `e82147fa02513f2dcea0453b439eb7aa01240dc0687e817cf914324ba9908e71`, short `a7af44530a665d5f3c6273cab26efe2c340125a084e93e4a60aa349f6c8ff348`.
- Source/broker qualification flags: `quote_source=synthetic_illustrative_only`, `broker_qualified=false`, `broker_orders_executed=false`, `commissions_and_funding_deducted=false`. These labels prevent a fixture success from being used as real-broker parity or any market profitability claim.
- **Day-level Day12 PASS only.** Broker-realness, B03 stage and owner acceptance remain OPEN. Next: Day13 cash commission, explicit slippage and swap/rollover, then USD journal reconciliation.
