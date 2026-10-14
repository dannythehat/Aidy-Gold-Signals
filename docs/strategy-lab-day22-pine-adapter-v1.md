# B06 Day 22 — Restricted Pine Script v6 adapter

**Engineering status (14 October 2026): DAY-LEVEL INTERNAL TECHNICAL PASS — verified on real XAUUSD historical data and merged into main in [PR #273](https://github.com/dannythehat/Aidy-Gold-Signals/pull/273). The previous *separate* original TradingView provider-execution parity requirement remains UNVERIFIED. This is an explicit scoped acceptance update, not a claim of platform parity.**

## Product contract — inbound customer submissions (owner clarification, 14 October 2026)

**AIDY is a customer-led independent testing service.** Customers come **to AIDY** with a trading strategy; AIDY must accept supplied strategy materials (written rules, uploaded source code and files, or a source link), clarify missing or ambiguous requirements in ordinary language, reproduce the supported rules independently, test them against qualified market/broker assumptions, and report reproducible results with provenance and limitations. Researching publicly available strategies ourselves is an **optional separate research activity**, not the customer acquisition model.

**Never require the owner or a customer to become a TradingView user, learn Pine Script, procure chart exports, or manage platform-specific technical workflows merely to submit a strategy.** TradingView is only one possible origin for customer-provided source. If a customer supplies only rules or a script, we can build an independently testable interpretation for supported rules. Any claim that we exactly match TradingView's proprietary execution/indicator behaviour requires independent comparative evidence and must be labelled **unverified** without it. That optional fidelity tier is per submission/reference and cannot be confused with the customer-facing intake contract.

Today's restricted Pine importer is **not a general Pine translation service**. It handles a narrow verified syntax subset and correctly blocks unsupported scripts; production B10 customer intake and additional adapter capabilities remain to be built. Do not treat passing synthetic acceptance fixtures as complete TradingView-platform replication.

**Original TradingView platform-parity calibration** remains an OPEN, separately classified advanced provider-fidelity gate under the roadmap's earlier criterion; it is not an obligation on customers or the owner to export data, nor a reason to reframe AIDY as an outbound strategy-hunting business.

## What is actually built

- `src/aidy/strategy_lab_pine_adapter.py`: `admit_pine_subset(...)`, `pine_predicate_signals(...)`, `compare_pine_to_spec(...)`, and `compare_pine_reference(...)`.
- Pin **original exact UTF-8 source bytes** by SHA-256, source reference, Pine major version and a full StrategySpec, including `origin.source_language=pine`. No arbitrary or untrusted Pine is executed.
- Source parser admits **Pine v6 only** for this stage, with `strategy(..., process_orders_on_close=false, calc_on_every_tick=false, calc_on_order_fills=false, pyramiding=0)`, two `ta.ema(close, n)` assignments, explicit `barstate.isconfirmed and ta.crossover(fastEma, slowEma)`, and one guarded long `strategy.entry` instruction. No added statements, inferred partial exits, unsupported security/timeframe calls or unspecified versions. All other Pine forms are BLOCKED.
- Pine `ta.crossover(a,b)` predicate is mapped to **previous a <= b AND current a > b** on fully closed, strictly ordered UTC M5 indicator samples; compare signal times against the **separate** Day20 StrategySpec predicate implementation. Signal generation operates on supplied indicator samples. **TradingView original `ta.ema` initialization and exact series values are not independently reproduced here**.
- A source-hashed, schema-validated reference trace can hold timestamped EMA data and Boolean signal markers. Every marker is checked against the supported predicate, including false bars, not just positive matches. An `origin=internal_synthetic` trace can demonstrate internal math equality only. A user-labelled `origin=tradingview_user_export_unattested` cannot be promoted to verified TradingView evidence based on its declared origin alone.
- Both `PineReferenceResult.real_tradingview_capture_qualified` and `complete_strategy_parity_qualified` deliberately remain **false** even when signal vectors match. This is critical: mere hash agreement validates exact submitted bytes, not external provenance.
- Original Pine source fixture `research/strategy_lab/fixtures/day22_internal_pine_v6.pine.txt` is **self-authored internal testing code**, not a claimed external profitable gold strategy or TradingView export.

## Original source-platform parity criterion — remains a separate unpassed advanced gate

The **former Notion Day22 source-platform PASS criterion was “Original TradingView reference signals match.”** It remains technically UNMET and has explicitly been separated from the later completed internal adapter acceptance. That requires an independently captured TradingView chart or test export linked to its frozen exact original Pine script version, chart symbol/feed, timeframe/timezone, relevant EMA series values and timestamped long signal markers. AIDY must compare the external reference against its interpreter and the source-to-StrategySpec mapping.

Without that external reference, mark **the original-provider parity gate** UNVERIFIED; do not claim the provider ran our Pine script. The revised **day-level internal adapter acceptance** is independently supported by read-only verified historical market data and accepted under a distinct evidence tier in PR #273. No statement that synthetic parity qualifies original TradingView behaviour is acceptable.

## Source references

TradingView official Pine docs:
- `https://www.tradingview.com/pine-script-docs/concepts/strategies/` documents the default next-available-tick execution behaviour and the `process_orders_on_close` and `calc_on_every_tick` exceptions.
- `https://www.tradingview.com/pine-script-reference/v6/` documents `barstate.isconfirmed` and Pine v6 APIs.
- `https://www.tradingview.com/pine-script-docs/concepts/repainting/` discusses repainting and closed-bar confirmation.

**No live trading, broker terminal, customer strategy, downloaded provider dataset or historical profitability is verified.**

## Acceptance evidence
**Initial synthetic-fixture engineering CI PASS; external native-TradingView parity remains UNVERIFIED. This paragraph is historical and was superseded for internal day-level acceptance by the later real-data PR #273.**

- [GitHub Actions run 38563701850](https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/38563701850), job `115850918670`: **133 Day20/21/22 tests passed**, Ruff and compileall passed, one non-fatal existing pytest `asyncio_mode` configuration warning.
- Tested implementation head `a54623e221c07d9e5ce864bd944e8766f46a1414` and [PR #268](https://github.com/dannythehat/Aidy-Gold-Signals/pull/268). Original internally authored Pine source SHA256 `1b403e7c305adecbb0f35437e1671108e2be72def45ff4358c6e5ceef5128411`.
- Independent Day20 closed-M5 predicate parity: exactly two synthetic signal timestamps, 2026-10-14T12:10:00Z and 2026-10-14T12:30:00Z.
- **CI explicitly reports** `day22_notional_acceptance=BLOCKED_NO_INDEPENDENT_TRADINGVIEW_REFERENCE`, `original_tradingview_qualified=false`, `full_strategy_import_qualified=false`, `broker_orders_executed=false`.
- The source code and adversarial tests are validated and can be merged to main. **Historical statement superseded by scoped internal acceptance on 14 October 2026.** Day22 Notion checkbox is now checked for genuine historical-data **internal** source signal reproduction. The original provider-platform parity item remains separately unpassed and must never be described as a verified platform match.



## Day22 final internal technical acceptance — 14 October 2026

- [PR #273](https://github.com/dannythehat/Aidy-Gold-Signals/pull/273) merged into `main`, squash `60d00c9a549b7af72dc3af380315f23f95aae9e0`.
- [Real historical independent EMA + closed-M5 crossover CI PASS](https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/38615858064): **122 tests passed**, source/lint passed, read-only historical query and identical digest replay passed. [Evidence semantic gate](https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/38615857818): PASS.
- Real historical 2025-01-06 XAUUSD HistData bid OHLC: **600 native M1 records**, **120 complete M5 closes**, two source/spec/independent-oracle matching signal times **15:30 UTC** and **18:25 UTC**. Frozen historical source SHA `50d0bc064f9a2dd91f93a38abc3ab9270d1f1f5082c9e85f936d276b5593207b`, original Pine SHA `1b403e7c305adecbb0f35437e1671108e2be72def45ff4358c6e5ceef5128411`.
- [Implementation, genuine-source methodology and limits](https://github.com/dannythehat/Aidy-Gold-Signals/blob/main/docs/strategy-lab-day22-real-history-audit.md). This verifies **internal** reproducible EMA and crossover decisions, not original TradingView's source runtime. We use a bounded history-window EMA seed. We do not claim customer strategies fully ported, broker fills, profits or exact OANDA chart identity.
- Customer/owner provider signup **not required**. Original source-identical TradingView execution parity remains **UNVERIFIED** as a separate higher-assurance assessment with the previously reproduced anonymous sign-in access block.
