# Random one-system AIDY research challenge — S046 Session Sweep Boxes

**Experiment frozen 15 October 2026. Owner explicitly authorised exactly one strategy experiment on one randomly selected candidate. No running the other 82, no external account, no orders and no live/paper trade enrolment.**

## Random selection
Read live user [AIDY Google Drive original 83-system SCOREBOARD](https://docs.google.com/spreadsheets/d/14EbIPxW5ZeueRX0vz0i6qG7BmlosL04x8-xXl3Hh6N4/edit), 83 rows, of which 25 SOURCE REVIEWED. Python `secrets.randbelow(25)` yielded **15** (zero-based), selecting **S046** (16th row): *Session Sweep Boxes: session-level reclaim*. A single draw, no post-hoc cherry-picking or optimisation.

Original author: [MQL5 CodeBase entry 77953 — Session Sweep Boxes](https://www.mql5.com/en/code/77953), published 3 October 2026. This is an **INDICATOR, not a complete trading EA**. Public description says closed-bar high/low sweeps of completed GMT session ranges, with options to stop on first sweep and to cancel a level on a close beyond. GMT windows Asia 00–08, London 07–16, New York 12–21. Source-code internals and exact default settings have NOT been independently audited.

## Hard original blockers
The Drive entry lists **"RULES LOCKED? NO"**, stop/target **MISSING**, sizing **MISSING**, MQL5/source parity **NOT ESTABLISHED**, historical broker clock parity **NOT PROVEN**. Thus executing an actual $10,000 strategy P&L backtest, verifying wins/losses or marking score/rank as profitable would be fabricated; AIDY must refuse. S046 may produce honest *signal-only* research evidence without trading.

## Pre-registered independent signal-proxy experiment

1. Read-only BigQuery `aidy-signals.aidy_analytics_test.research_candles` **histdata** XAUUSD native M1 BID, verified `EST_FIXED_UTC_MINUS_05` to UTC time contract, immutable provenance, no missing minute repair.
2. Pre-registered historical dates UTC **2025-01-07 and 2025-01-08** (both earlier than public source publication: retrospective, NOT out of sample). Each fixed 00:00–21:00 UTC, timeframe **M5**, **252 completed candles/day** (504 total). The New York session ends at 21:00, so **no after-close NY signal observation**, not a false "zero signals" claim.
3. For each complete session, preserve high and low only after the entire session is closed. Only the later 5-minute bar with a wick beyond the level **and a close strictly back within the completed full range** qualifies. Opposite-direction mark for high/low. Explicit analyst-chosen toggles: **first sweep per level only; cancel on closing beyond** (these are NOT documented/default-MQL5 parity).
4. Two independent real source queries per day, confirm byte-identical validated aggregate `ReadResult` and equal signal sets before reporting. Log source digests, genuine BigQuery job IDs and native archive hashes, deterministic signal event CSV and sha256.
5. Zero inferred fills, zero spread/P&L estimates, no invented $10k equity results, no publication or paper forward stage. The code is an **independent proxy derived from public indicator prose**, not a port of the original `.mq5`. Full original-code buffer parity audit is a separate prerequisite before labeling the original S046 *signal detector* replicated.

**Success means** real M5 BID source and an independent closed-bar detector ran and reproduced. **It does not mean** the trading strategy is profitable or even runnable. `status=PASS_REAL_HISTORICAL_SIGNAL_PROXY_ONLY` remains non-qualifying; any clock/data/cost/provenance failure must be reported as `BLOCKED_REAL_DATA_OR_RULE_VALIDATION`.

## Audit history and artifact

- [Research PR](https://github.com/dannythehat/Aidy-Gold-Signals/pulls?q=is%3Apr+S046) — no writeback to the original Drive Results $10K ledger until an owner-reviewed actual complete trading system and costed broker-parity backtest exist.
- Exact generated output: `artifacts/strategy_lab/s046_signal_research/experiment_result.json`, `closed_bar_signal_events.csv` if real data accepted, stored as CI workflow artifact.
