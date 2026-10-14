# B06 Day 22 — Restricted Pine Script v6 adapter

**Engineering status: implementation submitted; complete Day22 acceptance remains BLOCKED until original TradingView output evidence is independently obtained and compared.**

## What is actually built

- `src/aidy/strategy_lab_pine_adapter.py`: `admit_pine_subset(...)`, `pine_predicate_signals(...)`, `compare_pine_to_spec(...)`, and `compare_pine_reference(...)`.
- Pin **original exact UTF-8 source bytes** by SHA-256, source reference, Pine major version and a full StrategySpec, including `origin.source_language=pine`. No arbitrary or untrusted Pine is executed.
- Source parser admits **Pine v6 only** for this stage, with `strategy(..., process_orders_on_close=false, calc_on_every_tick=false, calc_on_order_fills=false, pyramiding=0)`, two `ta.ema(close, n)` assignments, explicit `barstate.isconfirmed and ta.crossover(fastEma, slowEma)`, and one guarded long `strategy.entry` instruction. No added statements, inferred partial exits, unsupported security/timeframe calls or unspecified versions. All other Pine forms are BLOCKED.
- Pine `ta.crossover(a,b)` predicate is mapped to **previous a <= b AND current a > b** on fully closed, strictly ordered UTC M5 indicator samples; compare signal times against the **separate** Day20 StrategySpec predicate implementation. Signal generation operates on supplied indicator samples. **TradingView original `ta.ema` initialization and exact series values are not independently reproduced here**.
- A source-hashed, schema-validated reference trace can hold timestamped EMA data and Boolean signal markers. Every marker is checked against the supported predicate, including false bars, not just positive matches. An `origin=internal_synthetic` trace can demonstrate internal math equality only. A user-labelled `origin=tradingview_user_export_unattested` cannot be promoted to verified TradingView evidence based on its declared origin alone.
- Both `PineReferenceResult.real_tradingview_capture_qualified` and `complete_strategy_parity_qualified` deliberately remain **false** even when signal vectors match. This is critical: mere hash agreement validates exact submitted bytes, not external provenance.
- Original Pine source fixture `research/strategy_lab/fixtures/day22_internal_pine_v6.pine.txt` is **self-authored internal testing code**, not a claimed external profitable gold strategy or TradingView export.

## How true Day22 acceptance will be earned

The **actual Notion Day22 PASS criterion is “Original TradingView reference signals match.”** That requires an independently captured TradingView chart or test export linked to its frozen exact original Pine script version, chart symbol/feed, timeframe/timezone, relevant EMA series values and timestamped long signal markers. AIDY must compare the external reference against its interpreter and the source-to-StrategySpec mapping.

Without that external reference, mark the Day22 *software integration* as **implemented and merged with tests**, but keep the **day-level acceptance checkbox unchecked/PARTIAL**. No statement that synthetic parity qualifies original TradingView behaviour is acceptable.

## Source references

TradingView official Pine docs:
- `https://www.tradingview.com/pine-script-docs/concepts/strategies/` documents the default next-available-tick execution behaviour and the `process_orders_on_close` and `calc_on_every_tick` exceptions.
- `https://www.tradingview.com/pine-script-reference/v6/` documents `barstate.isconfirmed` and Pine v6 APIs.
- `https://www.tradingview.com/pine-script-docs/concepts/repainting/` discusses repainting and closed-bar confirmation.

**No live trading, broker terminal, customer strategy, downloaded provider dataset or historical profitability is verified.**

## Acceptance evidence
**Day22 engineering CI PASS; full Day22 original-TradingView parity remains BLOCKED.**

- [GitHub Actions run 38563701850](https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/38563701850), job `115850918670`: **133 Day20/21/22 tests passed**, Ruff and compileall passed, one non-fatal existing pytest `asyncio_mode` configuration warning.
- Tested implementation head `a54623e221c07d9e5ce864bd944e8766f46a1414` and [PR #268](https://github.com/dannythehat/Aidy-Gold-Signals/pull/268). Original internally authored Pine source SHA256 `1b403e7c305adecbb0f35437e1671108e2be72def45ff4358c6e5ceef5128411`.
- Independent Day20 closed-M5 predicate parity: exactly two synthetic signal timestamps, 2026-10-14T12:10:00Z and 2026-10-14T12:30:00Z.
- **CI explicitly reports** `day22_notional_acceptance=BLOCKED_NO_INDEPENDENT_TRADINGVIEW_REFERENCE`, `original_tradingview_qualified=false`, `full_strategy_import_qualified=false`, `broker_orders_executed=false`.
- The source code and adversarial tests are validated and can be merged to main. **Do not mark the Day22 Notion checkbox complete** until an independent original TradingView reference capture and source-platform signal comparison is recorded.

