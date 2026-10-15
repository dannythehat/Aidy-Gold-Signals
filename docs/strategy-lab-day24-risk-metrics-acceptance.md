# Day 24 — Statistics and risk metrics from AIDY's verified cash journal

**Acceptance target:** actual independent calculations reconciled to the Day17 disk-backed immutable USD cash/equity journal, Day18 deterministic replay and Day19 single-trade reference. Statistical outputs never certify trading profitability.

## Actual software built

- `src/aidy/strategy_lab_risk_metrics.py`: read **existing** SQLite journal read-only within one DB snapshot, check application append-only triggers and **every hash-chain event** using Day17 verification, require a caller-pinned journal tip SHA256, source SHA256, declared lot contract, and bounded records; fail instead of truncating data.
- Allocate commission, slippage, and swap events to a unique active or same-timestamp completed position, sum partial-close realised P&L, reject overlapping positions and unmatched fees. Reject any deposit/withdrawal after initial capital instead of mislabelling cash transfers as strategy profit. Reject incomplete/open positions rather than present an unsupported final all-closed return.
- Per completed trade compute exact Decimal gross P&L, costs, net P&L, win/loss/breakeven, **net USD expectancy = sum(net closed trade P&L)/closed trades**, **profit factor = positive net trades / absolute negative net trades** (null if no losing trades), net win percentage, and chronological monthly net P&L assigned to **UTC close month**. Fully reconcile final cash and equity to all completed net trade results and verified Day17 realised gross P&L.
- **Maximum observed mark-to-market drawdown**: walk validated journal event prefixes (including actual stored mark, partial fills and cost events), measure peak-to-trough USD and percentage over the OBSERVED event-sampled equity curve. This deliberately does **not** claim intrabar maximum drawdown, verified execution highs/lows or unrealised broker risk beyond stored mark evidence.
- **Sharpe caveat:** do NOT annualise sporadic trade outcomes. Main ledger report always emits `sharpe_annualized=null` with explicit lack of independently qualified consecutive daily account returns/session calendar; separate `qualified_daily_sharpe` mathematical primitive requires 30+ finite complete risk-free-adjusted daily observations plus a declared independently validated session calendar and 252-period assumption. It refuses zero variance or insufficient samples. No market-calendar attestation is supplied by synthetic unit tests.
- `research/strategy_lab/fixtures/day24_known_answer_journal.json` is original immutable INTERNAL illustrative source, NOT HistData execution nor a profitable strategy. `scripts/strategy_lab/day24_ledger_metrics_acceptance.py` SHA-pins its bytes and Day18 canonical event manifest, builds **two actual independent on-disk SQLite journals**, checks idempotent replay and hash tips, then asserts independent arithmetic against the ledger. Its full machine-readable results are archived by GitHub CI.

## Explicit golden account checks

Start `$10,000.00`, 4 independently authored LONG research trades spanning September and October 2026: gross results `+10, -5, +15, -5 USD`, commission `-0.50 USD` per trade. Therefore exact net trade P&L is `+9.50, -5.50, +14.50, -5.50`. Gross total `+15.00`, costs `-2.00`, net `+13.00`, ending account cash/equity `$10,013.00`. Win rate `50%`; net expectancy `$3.25/trade`; profit factor `24/11 ≈ 2.181818...`; event-observed maximum equity drawdown `$6.00`; monthly results `2026-09: +$4.00`, `2026-10: +$9.00`. Annualised Sharpe **NOT ESTIMABLE** from this four-trade event stream.

The pre-existing Day17 `$10,000 -> $10,008.30` fee-adjusted cash/equity regression is independently retested through this metric engine; the one winning trade MUST return `profit_factor=null`, not a fabricated infinite or attractive ratio.

## Proof, boundaries and follow-on days

CI `.github/workflows/strategy-lab-day24-metrics.yml` runs strict Ruff, compileall, Day17+18+19+24 regressions, the actual two-file SHA-pinned on-disk acceptance check, negative cases for altered DB/journal source, open positions, costs, capital injections and inadequate daily-return history. Tests' synthetic origin is always labelled, never represented as real historical trading, customer strategy profit, broker attestation or annualised model statistics.

**Stage boundaries:** Day25 benchmarks and cost stress, Day26 out-of-sample, Day27 regime, Day28 evidence rating and future B08 report APIs are NOT completed by this day. No live broker orders, production signal decisions, Cloudflare objects, strategy profitability reports or account deployments are modified.

## Final Day24 verified engineering acceptance — 15 October 2026

- **Day-level technical PASS:** source build [PR #277 merged into protected main](https://github.com/dannythehat/Aidy-Gold-Signals/pull/277) as squash `8f514a053fc7981b392e9a3a0dc9bc31d949d576`.
- **Successful real CI:** [GitHub Actions 38686277850](https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/38686277850), **47 tests PASSED**, Ruff and Python compilation PASS, end-to-end double-database SQLite test PASS. [Evidence semantics gate 38686277835](https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/38686277835) PASS. Earlier lint-only attempts failed, were repaired and rerun before merge.
- **Immutable input identity:** internal known-answer fixture SHA256 `9c7050a7857549d33cd1e354c5840b2e06120fc5216f3b3e17b4996043a39952`; canonical Day18 event-manifest SHA256 `b6274f33a4fe8abf0271d5e27439875bc35fc877f47d7952f42e8beac969af3b`; both independently replayed on-disk Day17 SQLite journals have the same final tip SHA256 `04abd2abf5716c58202bb09c38173c71362308617643ceb1a8d8d1ed137281a4`.
- **Exact observed golden metrics:** gross $15, fees -$2, net +$13, starting $10,000 -> final cash/equity $10,013; 4 closed trades, 2 winners, 2 losers, 50% win rate, net expectancy $3.25/trade, profit factor exactly 24/11, max mark/event sampled drawdown $6 (~0.05994%), Sep +$4 and Oct +$9. Unqualified annualised Sharpe remains null.
- **Non-negotiable caveat:** the original source events are internally authored synthetic exercises. The comparison is not a real historical edge, broker fill equivalence, true intrabar drawdown, daily-risk-adjusted Sharpe or an independently authenticated trading account. No live trading, customer accounts or production decisions changed. B07 stage approval and Days25 onward separate.

