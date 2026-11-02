# GoldThinker Factory — START HERE (2 November 2026)

Status: TESTED OFFLINE CONTRACTS, NOT A LIVE PIPELINE. All new code remains in draft PRs.

## Source of truth
- AIDY factory: https://github.com/dannythehat/Aidy-Gold-Signals/pull/376
- GoldThinker website preview: https://github.com/dannythehat/GoldThinker-Website/pull/28
- Existing 83-source evidence: https://github.com/dannythehat/Aidy-Gold-Signals/pull/374

Read the first two PRs and the original evidence before assigning agent tasks.

## Prepared and verified
1. AIDY schema and selector: src/aidy/goldthinker_factory_contract.py
   - Exactly one scoped row for each of 2021–2026.
   - Highest profitable completed calendar year (2021–2025, as of 2 November 2026) is selected for independent AIDY investigation. Verified 2026 YTD figures may be recorded but never counted as a complete calendar year.
   - Self-labelled result hashes do not authenticate the actual MT5 report and never grant paper/live/publication permission.
2. AIDY CLI: scripts/goldthinker_factory/prepare_handoff.py
   - PYTHONPATH=src python -m scripts.goldthinker_factory.prepare_handoff --input validated_bundle.json --output selected_year.json
   - Fail-closed, output atomic; this does not execute AIDY's independent replay.
3. MT5 offline config generator: scripts/goldthinker_factory/mt5_job_generator.py
   - PYTHONPATH=src python -m scripts.goldthinker_factory.mt5_job_generator --system GT_TEST01 --expert Factory\DemoStrategy --symbol XAUUSD --period M15 --as-of 2026-11-02 --out-dir out/gt-test01 --deposit 10000.00
   - Writes only six year-scoped INI files plus manifest (2026 partial). Official MT5 real-tick Model=4, Optimization=0, UseCloud/Remote=0, ShutdownTerminal=1, no live trading.
   - Does NOT compile the EA, start MT5, provide credentials, qualify data coverage or create reports. Test job status remains NOT_EXECUTED.
4. Website factory-card draft: scripts/factory-card-contract.mjs and scripts/build-factory-card-preview.mjs in PR #28.
   - Node 22 offline validation/tests; preview is noindex and not wired to actual public routes.
   - Missing paper/cent/live P&L remains Not available; independent test profits explicitly hypothetical.
5. Both PRs include standalone CI workflow tests and preserve existing website and AIDY behavior.
6. MT5 report and deal-ledger extractor: `scripts/goldthinker_factory/extract_mt5_bundle.py` and `src/aidy/goldthinker_factory_mt5_extract.py`.
   - Reads an English Strategy Tester `.htm` (UTF-16 or UTF-8) or a simple SpreadsheetML `.xml`. Does not launch MT5.
   - `report_sha256` is the SHA-256 of the raw file bytes. `ledger_sha256` is the SHA-256 of the canonical deal CSV written beside the bundle.
   - Net profit and closed trades are admitted only when they match the ledger. Balance drawdown is recomputed from the ledger and cross-checked against the report's balance-drawdown lines. Equity drawdown is copied from the report's equity lines and is not forced to equal the balance path. A Fee column, when present, is part of net P&L and of the cost metrics. A discrepancy marks that year FAILED and leaves the bundle result fields null.
   - 2026 is always PARTIAL. Ledger times stay on the broker-server clock. Reconciliation converts them to UTC only with an explicit GMT offset and DST rule (`NONE` or `EU_LAST_SUNDAY_MAR_OCT`); a missing clock is INCONCLUSIVE.
7. Ledger metrics v2: `src/aidy/goldthinker_factory_metrics.py`. Schema `goldthinker.factory.mt5_bundle.v2`. v1 validation is unchanged. The v2 validator recomputes profit factor, worst-trade share, average profit versus quoted round-trip cost, and the doubled-cost stress net from the ledger CSV and rejects any difference.
8. Selected-year reconciliation: `scripts/goldthinker_factory/reconcile_selected_year.py`. It opens only `{system}_{selectedYear}_deals.csv`. Status is MATCH, MISMATCH or INCONCLUSIVE. Dropped trades, shifted prices and changed costs are MISMATCH and set `research_packaging_allowed` false. Final P&L alone cannot pass.
9. Thresholds and tolerances live in `config/goldthinker_factory_thresholds.json` with `approval_status` UNSET and every number null. Checks report UNSET, not PASS, until Danny approves numbers. v2 selection then returns `BLOCKED_THRESHOLDS_UNSET` and does not emit `SELECTED_PENDING_INDEPENDENT_EVIDENCE`. Worst-trade share is undefined when the year net is not strictly positive, so a losing year cannot pass that gate. v1 selection never emits `SELECTED_PENDING_INDEPENDENT_EVIDENCE` either.

## What is synthetic
`tests/fixtures/goldthinker_factory/synthetic/` holds an authored Strategy Tester-shaped HTML file labelled `SYNTHETIC_FIXTURE`. It is not a terminal run. The unit tests also build UTF-16, spaced/comma numbers and SpreadsheetML copies of that book. `tests/fixtures/goldthinker_factory/real_mt5_reports/` is empty apart from its README. `tests/test_goldthinker_factory_real_mt5_reports.py` is skipped until real tester output is dropped there and the skip is removed.

## Actual blockers for the FIRST true MT5 run
- The phase05 native MT5 attempt was blocked by a missing tester account: "tester not started because the account is not specified". The first job is to validate a dedicated restricted MT5 installation with a separately approved DEMO tester account. Do not use existing funded accounts, Gina or Super Signals terminals.
- PR #374 has authenticated 2023–2025 historical research, not a proven real-tick 2021–2026 set for the chosen broker. Confirm genuine data/quote sides, session/calendar, contract sizes, financing, lot steps, margin and tick availability year-by-year.
- No real Strategy Tester report is in this repo. The extractor has not been shown a genuine terminal file. Equity drawdown is admitted only when it equals the balance path, because the deals table has no floating-equity series. `in/out` and `out by` deals are refused (no position id). Non-English labels are refused. A year that is not flat at the end is not admitted.
- AIDY has no offline strategy replay that turns an arbitrary factory EA plus the selected year into trades. `strategy_lab_deterministic_replay` replays a recorded cash journal, `strategy_lab_order_lifecycle` fills one order on a quote tape, and `strategy_lab_reference_run` is a frozen 55-bar internal fixture. Reconciliation therefore takes an explicit trade list. Without that list the receipt is INCONCLUSIVE and names the missing hook. Even a perfect explicit list stays INCONCLUSIVE while tolerances are UNSET.
- Signature/authenticity of a real terminal file, original strategy-to-EA parity, a data-driven site endpoint, continuous paper/cent P&L and the promotion worker are NOT YET BUILT. No numeric promotion gate is approved. Best-year replication is not out-of-sample proof of edge.

## First operating proof requested from GT-00
1. Inspect existing StrategySpec and 83-candidate register. Choose one complete-rule source and mark its limitations. An internal EA can prove toolchain only, not market profit.
2. Establish restricted MT5 research terminal and demo account; capture its symbol contract and tester build. Generate annual INI jobs; use real ticks where actually available, not assumed.
3. Compile actual source MQL5 and run date-scoped jobs. Attach real logs, receipts, trade/deal ledgers, reports and data checks; persist full failed attempts.
4. Run `extract_mt5_bundle.py` with `REAL_MT5_TESTER` on those real reports (not the synthetic fixture). Danny must approve `config/goldthinker_factory_thresholds.json` before any gate can PASS. Select the best completed profitable year and reconcile THAT YEAR ONLY. A matching final P&L, or an explicit trade list while tolerances are UNSET, is not a success.
5. Build one private-staging card from the signed public-safe record using website PR #28. Draft one full-page system profile with source and rights, rule explanation, why under test, historical annual figures, stage clock, paper/cent/live P&L and last broker sync.
6. Only after this successful end-to-end proof: create the remaining specialist Grok Bots, teach verified skills, enable daily scans/routines, multi-agent handoffs and monitored demo trading. Funded accounts/public site require separate owner approval.

## Suggested access by agent
- Coordinator: repos, PRs, stage queue and audit receipts; not broker secrets.
- Source scouts: public YouTube, public websites, lawful captions and rights trails; not trade access.
- Rules/code/review: versioned research source, write only through scoped PRs; never production credentials.
- MT5 tester: separate Windows research terminal and authenticated test artifacts; no access to funded/live terminals.
- AIDY investigator: independent research price and trading evidence; no broker execution permission.
- Website editor: only public-safe projections and staging repo writes; never ability to publish unreviewed returns.
- Fleet operator: stage-specific owner-approved accounts; isolated per system.
- Accountant: read-only broker deals/equity, stage identity, agreed day cutoff and signed website feed.
- Promotion officer: recommendation/approval record, NOT automatic cent/live deployment or transfers.

Grok Bots on one account share a persistent cloud computer and browser logins. Different Bot names DO NOT provide secret isolation. Use explicit service permissions and separate MT5 directories.

## Initial lead Bot prompt
Read both factory PR #376 and website PR #28 plus AIDY research PR #374. Review their actual files and CI evidence. Begin with a single RESEARCH-ONLY native MT5 tester toolchain proof on a separately isolated terminal, not ten simultaneous bots or live order execution. Solve the missing-demo-account prerequisite without using funded account credentials. Never declare six-year tests complete without complete date/data evidence. After collecting genuine reports, have AIDY independently reconcile the most profitable completed year only; preserve all losing and failed years. Prepare one noindex website card preview, then report precisely what passed and what remains blocked. Do not fund/open real broker accounts, move to cent/live, or publish returns without owner approval.
