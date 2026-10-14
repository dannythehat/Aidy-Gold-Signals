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
To be populated with actual CI workflow/test count, merged PR and source SHA when verified. Day22 remains PARTIAL until genuinely independent TradingView parity checks succeed.
