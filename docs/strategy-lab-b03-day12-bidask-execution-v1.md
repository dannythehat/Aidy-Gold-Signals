# B03 Day 12 — Bid/Ask Next-Quote Execution Contract

**Status: IMPLEMENTED — CI PENDING**. Isolated AIDY Strategy Lab development branch. No real trading authority and no owner-approved B03 release.

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

Add actual immutable GitHub CI URL, commit hash, fixture SHA256, test count, test job ID and scope qualification **after all tests pass**. Don't tick Notion based on planned code.
