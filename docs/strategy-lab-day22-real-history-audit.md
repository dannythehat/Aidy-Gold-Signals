# Day 22 — Real historical XAUUSD Pine-subset internal reproduction audit

Owner-requested engineering qualification without requiring a TradingView account, a customer chart export, or any customer technical effort.

## Added evidence and execution

- Read-only access to the previously verified actual HistData 2025-01-06 XAUUSD native M1 bid OHLC records in BigQuery.
- Fixed EST-based historical source clock and no missing-minute or interpolated-candle allowance. The selected 11:00–21:00 UTC 600-minute interval stays outside the daily gold close.
- Derive 120 fully closed M5 candles from 600 qualified original M1 rows.
- Bind the unchanged original Pine v6 source bytes to source-SHA256, a reviewed typed StrategySpec and the subset parser. Customer's original code is **not** executed.
- Reproduce ta.ema(close,10/30) by two separate Decimal recurrences and independently compare closed-bar crossover timestamps after a 50-bar warmup. Fail on any discrepancy, source drift, chronology violation or replay digest difference.
- Store both read-only query job IDs, original source archive hashes, input digest, signal timestamps and provenance in a GitHub Actions artefact.

Actual machine-readable pass/failure data is emitted by `scripts/strategy_lab/day22_real_history_ema_audit.py` to `artifacts/strategy_lab/day22_real_history_ema_audit.json`. The workflow FAILS if the real BigQuery query, replay, source identity or independent calculations fail. Synthetic regression tests do not replace this live query.

## Scientific distinction — do not conflate evidence tiers

**Internal independent signal reproduction on genuine historical market data** may pass. This establishes that AIDY can take its known supported Pine subset, consume qualified historical closes and produce deterministic independent crossover decisions.

**External original TradingView execution parity is NOT demonstrated by this check.** The source platform requires a sign-in to run Add-to-chart; no AIDY-controlled authenticated TradingView QA session or original provider export is currently supplied. The 120 M5 history window also seeds EMAs at its first observed close and cannot establish equivalence to TradingView's full earlier chart history. OANDA and HistData can differ in candle source. We do not silently waive or label original platform parity PASS.

## Operational model

AIDY accepts customer Pine text/files and generates source receipts and human-readable rule-clarification questions. Neither customers nor the owner need an account with TradingView to use that intake. The exact source-platform parity comparison is an **optional higher evidence tier** for independently verified provider equivalence; it is not proof of profitability, live execution or an onboarding prerequisite.

## Acceptance decision

The imported subset, triage and chart comparison tooling were previously merged in #268, #269, #271 and #272. This added real-data calibration tests independent AIDY reproductions, with its own CI evidence. Day22 can be labelled **INTERNAL_ADAPTER_IMPLEMENTED** only when this workflow passes and merges. The separate original TradingView source-parity requirement stays **UNVERIFIED** until genuine original-platform evidence is available. Do not represent it as satisfied based on our own EMA calculations.
