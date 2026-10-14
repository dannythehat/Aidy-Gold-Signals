# AIDY Strategy Lab — Customer-grade XAUUSD strategy audit contract v1

Status: PROPOSED, not implemented or independently validated.
Date: 2026-10-14
Scope: research-only. No modification to live AIDY cycle, broker integration, publication or GoldThinker.

## Objective

Build a deterministic and reproducible testing product that can ingest a clearly specified external trading system, backtest it on qualified gold history under a declared USD 10,000 account contract, and provide a full evidence-linked report. Internal owner experiments and paying customer experiments use the SAME testing, data, costing and reporting pipeline. The only difference is access/billing entitlement.

No report may imply that historical returns guarantee suitability or future profitability. All actual results must be produced by runs and traceable to their exact immutable ledgers.

## Build order — no portal before the engine

### Gate A — data qualification and broker contract

- Catalogue all stored data partitions, completeness, timeframe, raw bid/ask versus bid-only, licence rights, timezone and DST source conventions, digits, tick size and source hash. Never assume the ~709,543 reported 2024/25 M1 bars form continuous history without inspection.
- Assert monotonic unique timestamps, OHLC integrity, source discontinuities, weekends and platform-specific sessions.
- Replay supports multiple named data sources, each pinned to an immutable manifest. Synthetic reconstruction must be labelled and never passed off as actual tick or bid/ask.
- Broker profiles declare symbol contract size, tick size, tick value/currency, minimum/step/max lots, margin/leverage, stop-distance limits, commissions, swap schedule and historical spread/slippage policy. Missing critical contract facts block VERIFIED.
- Model realistic fills: buys execute on ask, sells on bid; protective stop/target triggers depend on bid/ask and order direction; next tradable quote not signal close; spread, commission, slippage, partial fills, overnight/weekend gaps, financing, rejected orders and margin calls explicitly treated.
- For ambiguous intrabar sequencing, use ticks when available; otherwise disclose and calculate adverse-first sensitivity. Do not claim unique execution path from OHLC alone.

### Gate B — canonical StrategySpec and safe reproducibility

- Each strategy has a globally unique system ID, original author/source, licence, claimed-versus-verified performance separation, frozen version/hash and schema version.
- Define market, timezone, supported timeframe(s), warmup, indicators/settings, full long/short entry logic, signal confirmation, exits, stops, targets, trailing/partial/scale rules, allowed sessions, exceptions, max positions, sizing and portfolio constraints.
- Store exact original code snapshots and a documented normalized rule interpretation with discrepancies; owner must resolve material ambiguities before the test is graded.
- Candidate types: full mechanical strategy / partial indicator / variant / opaque black box. Only complete, deterministic specs can receive a VERIFIED full audit.
- Pine, MQL4/5, Python and written rules use controlled adapters. Uploads are NEVER executed directly in privileged AIDY/Cloudflare processes. Parse/review first; use sandboxing, dependency allowlists, resource quotas, no network/secrets, no broker credentials and user tenancy boundaries.
- Functional parity tests compare signal timestamps, direction, entry, stop, target and position lifecycle to the source platform on selected fixtures.

### Gate C — deterministic $10,000 execution and trade ledger

- Default isolated account: opening balance USD 10,000, account currency USD, 1% equity risk at initial stop as an *explicit research default*, not an automatic suitability recommendation. Preserve source-specific sizing as a separate run arm.
- Exact lot sizing derives from validated broker contract and stop distance, rounds DOWN to admissible step, then enforces minimum size, margin and maximum exposure. Decline trades if actual max risk would be exceeded.
- Record cash balance, equity, margin and mark-to-market in event-time; account equity includes open unrealised positions for drawdown.
- Immutable trade/event ledger includes experiment/run, strategy, version, order intent, rejection, fill timestamps, bid/ask, planned and actual quantity, stop/target state, each partial fill, exit reason, fees, spreads, slippage, swap, realised USD and R, equity after event, market regime and source identifiers.
- Reconcile every result: opening balance + realised net P&L = closing cash (subject to declared transfers); cash + unrealised = equity; trade costs equal event costs; all report aggregates must match the ledger.
- Fail-closed on negative/zero stop distance, stale quotes, future-data leaks, missing contract metadata, inconsistent account arithmetic and fill impossibilities.

### Gate D — research design and falsification

- Full test is fixed-source and original-rule first; no silent enhancement.
- No-look-ahead signals; higher-timeframe context becomes eligible only when completed and published.
- Pre-register parameter search, baselines, train/dev/calibration/holdout boundaries and purge/embargo/CPCV where applicable; prevent tuning on reused holdouts.
- Baselines: buy-and-hold/flat or matched exposure; random timing/direction controls where appropriate; fee-adjusted equal-exposure controls and session/regime-conditioned baselines. Choose comparisons matched to strategy behaviour.
- Report counts, CAGR where mathematically suitable, gross/net USD, return, MDD (equity and cash separately), profit factor, expectancy USD and R, max loss streak, long/short, session, year, bull/bear/range and volatility/news regimes, time in market, turnover, exposures, worst trade, daily/monthly curves and cost sensitivity.
- Report sample uncertainty and multiple-testing correction. Small sample/incomplete regime coverage results in INSUFFICIENT EVIDENCE rather than a false score.
- Outcome gate: NOT RUN, INCOMPLETE, REPRODUCTION BLOCKED, VERIFIED, REJECTED. No performance cells filled from publisher claims.
- The /100 AIDY rating follows the existing nine-factor lab weights. An untested or unverified strategy has no numeric evidence-based score. RED/ORANGE/GREEN are research dispositions, never permission to trade.
- Findings and code-version outputs must be replayable byte-for-byte or numerically within an explicit deterministic tolerance.

### Gate E — report and user portal

Report sections:
1. Cover: strategy ID/version, customer, market, dates, evidence grade, test status, plain-English finding.
2. Exact system rules and source attribution; exclusions/interpretation decisions and license.
3. Data provenance/coverage and bid/ask confidence; candle clock/DST; missing segments.
4. Broker assumptions, risk schedule, position sizing, slippage, commission, financing and margin.
5. $10,000 account financial statement and order/trade reconciliation.
6. Win/loss distribution, risk-adjusted metrics, drawdown and full equity/balance curves.
7. Long/short and session/timeframe performance.
8. Bull/bear/range, volatility, year/month and news-window comparisons.
9. Train/development/calibration/holdout splits, walk-forward and robustness/multiple trials.
10. Matched market baselines, excess expectancy and null-hypothesis tests.
11. Parameter sensitivity, cost stress, data-source and broker sensitivity, failure modes.
12. Confidence/score out of 100 (only if independently verified) and RED/ORANGE/GREEN evidence classification.
13. GoldThinker research disposition; never auto-integrate.
14. Reproducibility appendix: hashes, inputs, source code, run ID, full trade/event ledger download.
15. Limitations: historical/hypothetical, execution caveats, insufficient evidence, no promise of future return.

Report channels: web dashboard, PDF, JSON/CSV export, compact shareable read-only result link (opt-in). Each reports the same verified canonical result object.

User-submission paths (only AFTER Gates A-D):
- Guided natural-language rule entry using a strict structured rule confirmation flow.
- Upload Pine Script, .mq4/.mq5 text, Python source or rule documents; reject executables, unsafe archives and untrusted binary execution.
- Paste code, enter source links for read-only acquisition, select an existing open-source strategy, choose an approved prebuilt strategy template.
- User sees completeness checklist; cannot request 'VERIFIED' before ambiguities resolved.
- Asynchronous isolated jobs, per-tenant rate limits, job status, deletion/privacy controls, user ownership and explicit data-retention controls.
- Entitlements: internal-owner FREE/UNLIMITED-BILLING (compute usage still measured); external paid plans/credits. The backend must NOT bypass safety/quality gates for internal runs.

## Initial acceptance tests (must pass before first external report)

1. One no-trade spec returns a $10,000 flat balance, zero trades, no invented ratios and an honest insufficient-evidence verdict.
2. Long and short one-trade fixtures reconcile bid/ask and all charges to the cent.
3. Spread widening turns otherwise identical gross signals into worse or equal net execution, all else held fixed.
4. Adverse-first same-bar SL/TP ambiguity never improves the default result.
5. Inconsistent quote clocks, missing warm-up and future higher-TF values fail closed.
6. Multiple simultaneous positions, partial exits, trailing stops, margin reject and overnight swaps reconcile exactly.
7. Repeated frozen run returns identical trade/events and report digest.
8. Two customers submitting the same public rules cannot access each other's private upload, report or artefacts.
9. Every PDF figure equals the canonical JSON and downloadable ledger.
10. Original platform parity fixtures pass for each enabled import language.

## Architecture and isolation

- Keep existing src/aidy/paper_simulator.py unchanged in contract; it is research R-multiple lifecycle, not an executable brokerage simulator.
- New independent package proposal: src/aidy/strategy_lab/{schemas,ingest,market_data,broker_profiles,engine,ledger,metrics,regimes,benchmark,validation,reporting}.
- Research runs use sandboxed compute and object storage; never install arbitrary customer code into Cloudflare Worker, live AIDY signal provider, GoldThinker or any broker terminal.
- Google workbook is an indexed summary; large detailed trade ledgers and downloadable artefacts must be immutable run-linked files/database records rather than overfilling Sheets.
- D1 for job metadata and research audit index; R2 for frozen artefacts; existing BigQuery for large historical analyses where commercially licensed and appropriate. Exact final deployment topology requires profiling.
- Keep AIDY gold-learning signals, GoldThinker, Super Signals and brokerage completely isolated until explicit separately audited owner approval.

## Current known gaps, as of 2026-10-14 code inspection

- Existing Day 46 paper simulation explicitly reports R-only, no account currency or lot sizing; this is NOT the required $10k engine.
- Day 27 HistData historical tick/spread source was qualified for bounded research windows; this does not prove full historic broker-executable bid/ask coverage.
- Day 37 replay gives excellent integrity primitives, but does not itself provide arbitrary source-strategy trade execution.
- Strategy importer, external-user tenancy, complete cash account simulator, customer report and billing entitlements are NOT yet shown as working end-to-end capabilities.
- Consequently AIDY cannot currently be called customer-grade for trade/no-trade decisions.

## First implementation slice

1. Build StrategySpec v1 and BrokerProfile v1 with strict validation and test fixtures.
2. Build bid/ask candle+tick provenance validator.
3. Implement a deterministic USD-account execution engine and double-entry-like cash/equity trade ledger.
4. Prove one simple reference strategy end-to-end against a frozen fixture and source-platform signals.
5. Integrate report JSON and PDF, then qualified actual 2024/25 partitions.
6. Only then create authenticated customer uploads, job scheduling, billing and dashboard.

**Completion criterion:** a reviewer can take the frozen code, data, broker profile and strategy specification; rerun; and independently reconcile every reported dollar and every order.
