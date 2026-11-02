# GoldThinker Autonomous Strategy Factory — architecture v1 (proposal)

Status: **DESIGN / NOT DEPLOYED**, 2026-11-02. This document is a build contract, not evidence of agents created, a broker connection, a completed MT5 replay, or permission to trade. Do not merge, change production, publish performance, open accounts or submit funded orders as a side effect of reading this document.

## Goal and existing foundations

Continuously discover candidate trading strategies from YouTube, websites, public code, publications, submissions and the existing 83-candidate AIDY research catalogue. Automatically convert complete rules into versioned MQL5 EAs, run reproducible MT5 historical tests, have AIDY independently reconcile **only the best profitable completed calendar year**, then create properly evidenced system profiles on the separate GoldThinker website and advance systems through paper, funded cent and owner-approved real trading. Track each system and its financial results independently at all times.

Preserve \`dannythehat/Aidy-Gold-Signals\` and all PR #374 source, negative, trade, data, duplicate and blocker evidence. Reuse AIDY's existing StrategySpec, append-only registry, evidence system, walk-forward/risk tools where appropriate, and report contracts. GoldThinker public site remains the separate \`dannythehat/GoldThinker-Website\` repository. Existing research may identify promising candidates but **none may be assumed packaging or live eligible**.

AIDY remains the independent research verifier and does not execute broker orders or receive live broker credentials. The MT5 test and live runtime are separately permissioned systems.

## Permanent, event-driven conveyor belt

- \`DISCOVERED\`: unique lead, original link and timestamp; automated searches may find duplicate or unautomatable ideas.
- \`SOURCED\`: provenance, author, publication, license/reuse basis, cited original material, content hash and whether source is complete. A transcript is source material, not proof of executable rules.
- \`RULES_FROZEN\`: source-bound StrategySpec with exact trading signals, indicators, timing, market/session clock, money management, stops/exits, order types and uncertainty resolved. Unknown material rules go to \`BLOCKED_RULES\`, not AI invention.
- \`EA_BUILT\`: reviewed MQL5 \`.mq5\` source, versioned source hash, source/spec parity tests, compiled \`.ex5\`, logs and inputs. Compile success does not mean trade parity.
- \`MT5_TESTED\`: one full date-scoped test per available calendar year 2021 through 2026, with 2026 explicitly PARTIAL at current as-of date. Never claim six full years when a period has missing or inadequate data. Cost/contract, real-tick coverage, rejected orders, complete trade ledger, execution settings, annual P&L, drawdowns and result hashes are mandatory. Any missing prerequisite becomes \`BLOCKED_DATA\` or \`BLOCKED_TESTER\`.
- \`AIDY_RECONCILED\`: if MT5 passes predeclared research thresholds, select the highest **net-profit completed calendar year** from the frozen MT5 reports; AIDY independently reproduces signal intent, order lifecycle, realistic costs, trade chronology, and cash reconciliation for that year only. Report \`MATCH\`, \`MISMATCH\` or \`INCONCLUSIVE\` with tolerances and ledger differences. Keep all other MT5 annual outputs. Confirmation of the best selected year proves replay fidelity only, **not** independent proof of out-of-sample alpha.
- \`PACKAGED\`: human-readable unique system name, permanent ID, immutable version, signed research manifest, licensed/reviewed code artefact, installation runbook, risk summary, brand card, detail-page data and current research status. Package is not an instruction to trade.
- \`PAPER\`: isolated broker demo or paper environment with original time-stamped decisions, independent fills, funding, equity, open/closed P&L and health records. Advance only when forward evidence policy passes and owner-approved account access exists.
- \`CENT\`: distinct actual broker cent/micro account, broker-confirmed fills and cash/equity; no simulated-cent substitution. Requires explicit account approval, legal/KYC steps and independently approved deployment.
- \`LIVE\`: separate actual live account and owner-authorised strategy/version/capital/risk limits. No autonomous transfer of funds or escalation of privilege.
- \`PAUSED\`, \`BLOCKED_*\`, \`REJECTED\`, \`RETIRED\` are durable outcomes; never delete their evidence or silently rebrand parameter variants as new independent systems.

Every transition is an immutable event with \`system_id\`, version IDs, UTC timestamp, predecessor state, actor, reason, approval evidence and reference to input/output hashes. Phase elapsed time is computed from these events. Queue jobs are idempotent and retryable without creating duplicates.

## Processing architecture

1. **Grok Bot team**: each specialist has a skill for one transformation; scheduled discovery and event-triggered handoffs. Grok Bot conversations/memory are not the database and do not themselves constitute test evidence. GitHub PRs and versioned job/artifact manifests are the coordination boundary accessible to ChatGPT reviewers.
2. **Control plane**: a narrowly scoped factory queue and status service, preferably alongside existing Cloudflare operational infrastructure but logically separate from AIDY's market-data runtime. D1 for strategy/stage/job/approval index; R2 for large immutable test reports, provenance, journals and ledgers; GitHub for code and review. The control plane never stores raw trading account passwords in GitHub or the public website.
3. **MT5 test worker**: a dedicated restricted Windows process on the existing Contabo server or separate isolated host; outbound-only authenticated polling of signed research jobs. Independent portable MT5 terminal directories and process ownership: never mix with Super Signals, Gina or funded followers. Local MT5 tester only by default; no paid MQL5 Cloud unless explicitly authorised. Record installer/terminal/build, tester account, symbol contract/timezone, starting deposit/currency, leverage, commission/swap/spreads, and executed test range. Use MetaEditor compilation logs and \`terminal64.exe /config:<file> /portable\` with \`[Tester]\` configs. No live trader login required for source analysis; MT5 may need a configured tester account even when only simulating orders, as the prior phase05 probe demonstrated.
4. **AIDY reconciliation worker**: ingest authenticated selected-year MT5 output and independently compute matching decisions and ledgers using qualified data/source semantics; no broker credentials, no live execution.
5. **Public projection**: generate a site-safe JSON projection of a bot's source, plain-language description, original publisher credit, status, evidence, running-time-in-stage and distinct research/paper/cent/live financial streams. Site worker serves read-only signed snapshots or verified public data. Website cards/pages use the existing \`/systems/\`, \`/results/\` and individual route design rather than rewriting the site.
6. **Broker runtime worker**: independent broker demo/cent/live workers on isolated terminal instances with per-strategy position ownership and event journals. Monitoring ingest is read-only and source-signed. A failed bot cannot access the others' credentials or place trades on their accounts.

### Minimum job and artefact identities

\`lead_id\`, \`original_source_url\`, \`source_sha256\`, \`strategy_family_id\`, \`system_id\`, \`strategy_spec_sha256\`, \`ea_source_sha256\`, \`compiled_binary_sha256\`, \`tester_build\`, \`data_dataset_id\`, \`broker_profile_id\`, \`test_config_sha256\`, \`run_id\`, \`report_sha256\`, \`ledger_sha256\`, \`approval_id\`.

One logical strategy can have many declared versions; trial count and complete losing experiments remain attached to the same family. Each broker account and phase has its own ledger and start/end timestamps.

## Historical verification and stage promotion

- Test 2021–2025 calendar years and 2026 year-to-date only where valid source data and broker terms are available. State coverage quality, tick mode and gaps per year. Prefer real ticks where meaningful; price-discovery and exact venue execution are different claims.
- Evaluate overall six-year MT5 profitability **and** annual behaviour, risk, number of trades, cost stress and concentration using explicit pre-registered thresholds. One jackpot year alone is not enough for promotion.
- AIDY replays **the top completed calendar year only**, as specifically directed by the owner. It does not need to repeat all six years. Select after freezing MT5 annual reports and retain the selection method and year.
- AIDY parity matching must record expected/actual orders, price/timestamp differences, net cash differences, unexplained residuals and missing data. No pass via simply comparing two final P&L figures.

## Offline gates now in the factory PR

These are research tools. They do not start MT5, do not read broker credentials, and do not authorise paper, cent, live or public performance.

- The extractor turns one English Strategy Tester report per year into a canonical deal CSV and a v1 bundle. Raw-file SHA-256 and ledger-CSV SHA-256 are separate. Net profit and closed-trade count must agree with the ledger. Balance drawdown is recomputed from the ledger and checked against the report. Equity drawdown is the report's own equity figure and may be deeper than the balance path. A Fee column is included in net P&L. A discrepancy marks the year FAILED with null result fields. 2026 stays PARTIAL. Synthetic HTML, including a UTF-16 copy and a tester-shaped layout, is labelled `SYNTHETIC_FIXTURE` and is not a terminal result.
- v2 (`goldthinker.factory.mt5_bundle.v2`) adds profit factor overall and per year, worst closed trade as a share of that year's ledger net, average profit per trade versus quoted round-trip spread plus commission, and a doubled-cost stress net (ledger net minus one extra quoted spread and round-turn commission). The validator recomputes every figure from the ledger. v1 validation is unchanged.
- Reconciliation reads the selection receipt and only that year's ledger, after converting broker-server timestamps with an explicit clock. It itemises signal, entry, exit, price, cost (commission, fee and swap) and cash differences. MATCH requires an approved tolerance file. The shipped file is UNSET, so identical trades are INCONCLUSIVE and v2 selection is `BLOCKED_THRESHOLDS_UNSET`. A dropped trade, a shifted price, a changed cost, or any itemised mismatch together with a residual is MISMATCH and blocks research packaging. Worst-trade share is not defined for a losing or zero-net year, so that year cannot pass the gate.
- There is still no adapter from an arbitrary strategy into that trade list. The receipt says so. Real tester files are not in the tree; the real-report test is skipped.

Promotion rules below are unchanged and still have no approved numbers.

- Forward PAPER and funded CENT gates use minimum independent observation periods and trades and credible risk thresholds to be agreed with owner; do not invent accepted numeric thresholds. Never promote on a single profitable day.
- Separately approved account creation (KYC, terms, email, identity and funding), paid services, publishing to public domain, cent-to-live and raising capital/risk are **owner approvals**. Bots may prepare applications and verify demo-creation capabilities but cannot impersonate identity, bypass KYC or make speculative claims.
- Production rollback and circuit breakers for stale market data, out-of-range P&L, disconnected account, changed EA, order duplication, runaway risk and pricing discrepancies are deterministic and non-discretionary.

## Source discovery and publication rights

- Search YouTube metadata/captions/transcripts where accessed lawfully, linked source code, creator GitHub repositories, TradingView/public strategies, blogs, community discussions, papers and user submissions. Respect API terms, robots/rate limits and licence rights. No account bypass, secret scraping or broad copyrighted re-publication.
- Extract a structured claim/evidence sheet with original URL/video timestamps, cited author, release version, methodology, declared symbol/timeframe/market conditions and source code location. Validate code licences separately from the right to research publicly discussed rules.
- Reject duplicate families and parameter-tweaked copies before compilation. Archive unsupported discretionary systems rather than generating guessed orders.
- Public card descriptions must be original summaries with attribution. No creator's original code or full transcript is republished without rights clearance.
- Never represent backtested dollars as broker-confirmed money or forward returns, and never use a mock amount where no ledger exists.

## Performance data for cards and pages

Each system shows: ID, name, short rules and why under test; source and attribution; evidence status; backtest years and calendar-year figures with clear hypothetical labels; AIDY selected-year reconciliation and limitations; current paper/cent/live status; period start and elapsed time for each stage; current cash balance, equity, closed net P&L, floating P&L, deposits/withdrawals, fees/swap, net return after cash flows, peak-to-trough equity drawdown; freshness, time zone and last confirmed broker event. No account has "0%" fabricated when it has not traded: use null/not yet available.

Ledger records must reconcile broker deal IDs, magic/system ID, account ID, strategy version and actual fills. Never sum separate brokers or strategies into a fictitious master account. Provide history and a "last updated" indicator. Preserve existing website design, accessibility and SEO/owner approval gates.

## Daily operating rhythm

- Daily discovery routine in Europe/Sofia time, plus GitHub event/webhook routing. Initial cap on newly queued ideas, compiler attempts, active backtests, AI usage and broker resources is configurable (no silent unlimited testing).
- The coordinator can select the next eligible queue items without human involvement, and specialists can hand off with persisted job outputs.
- Server monitors running EAs continuously during trading sessions and reconciles P&L on a fixed interval. A separate nightly immutable financial close produces per-system stage reports, with clear configurable trading-day cut-off.
- Daily digest: leads, duplicates, blocked source/rules, compiled, tested, rejected, AIDY matched/mismatched, packaged, paper/cent P&L, stage ageing, website sync health, exceptions, and outstanding approvals.
- On source/API outages or missing market data, mark unavailable/stale and retry with bounded backoff; never publish invented success.

## Implementation order and proof

1. Validate a fully reproducible isolated MT5 tester run and full report extraction on the Windows worker, including the phase05 missing-account prerequisite; never touch live/follower terminals.
2. Wire existing AIDY StrategySpec and code registry to the test job format and immutable result store. Make a reference authored EA run all available date-scoped years; test 2021/2022/2026 coverage before claiming 6 years.
3. Have AIDY replay and reconcile the highest-profit **completed** MT5 year, with deliberate mismatch fixtures proving failures block packaging.
4. Build first data-driven GoldThinker card and full page in private staging from authenticated sample or real strategy evidence, with independent P&L streams and stale data handling.
5. Add demo-only bot runtime and broker reconciliation, then supervised funded cent, with explicit authorisations.
6. After one complete real end-to-end strategy journey passes all engineering checks, enable multi-agent discovery, queued throughput, scheduled routines and conditional handoffs.

All work in isolated PRs and environment-scoped workers. Never merge PR #374 or deploy a trading strategy as a side effect of implementing the factory.