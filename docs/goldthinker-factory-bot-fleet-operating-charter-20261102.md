# GoldThinker Factory — Bot Fleet Operating Charter (GT-00)
**Owner vision interpreted 2 November 2026.** Proposed organisation, not authorisation to provision agents, spend money, connect accounts, deploy software or trade. Lead: Grok Bot ("Gaffer"/WorkerBee). Engineering source of truth: [GT-00 issue #377](https://github.com/dannythehat/Aidy-Gold-Signals/issues/377), [AIDY factory PR #376](https://github.com/dannythehat/Aidy-Gold-Signals/pull/376), [website PR #28](https://github.com/dannythehat/GoldThinker-Website/pull/28), [original research PR #374](https://github.com/dannythehat/Aidy-Gold-Signals/pull/374).

## 1. The whole picture: a strategy factory, not just a collection of trading bots

**AIDY is the independent scientific research engine. GoldThinker is the future public-facing strategy brand and marketplace.** The factory takes independently sourced strategies through a controlled evidence pipeline. It must distinguish *research backtest*, *forward demo/paper*, *cent* and *funded/live* evidence at every stage. The eventual website can display named, source-licensed, independently verified strategies and an elite combined portfolio, but cannot invent paper balances or advertise model returns as realised results.

End-to-end stages:

`Discover → Rights/source/rules → Native MT5 compile and real-tick annual tests → Ledger/execution audit → Candidate policy review → AIDY independent selected-year replay → Independent forward paper account → Finance/risk verification → Owner-approved public-safe staging → Optional owner-approved individual subscription → Optional owner-approved elite master portfolio`

- Research first: preserve all 83 original candidate IDs, duplicate/source blockers, original variants, all losing years and every test run; no cherry-picked results. Original strategy rules and later modifications have different immutable identities.
- GT-00 **is only one reproducible isolated MT5 → AIDY → private staging proof**, not the launch of the whole factory. MT5 real-tick model selection does not itself prove tick coverage or execution realism.
- Owner's established **minimum** forward criteria: 3 consecutive complete, reconciled profitable paper months for *individual subscription review-readiness*, 6 for *elite portfolio consideration*, followed by independent operational/risk review and owner approval. These are NOT automatic trading permissions. No approved fixed numerical research thresholds exist yet.
- The premium/Elite 20 portfolio must have **one independently funded/allocated combined paper account** with a single real order/fill/cash ledger, correlations, shared margin and risk limits. Never sum standalone hypothetical $10k system books and claim that is a combined account.
- The existing Super Signals copier and funded/Gina terminals are separate systems and out of scope for this factory. No agent may touch them to get GT-00 working.

## 2. Leadership and ownership

**Danny (Owner / final decision maker):** Approves capital, broker account access, permitted external spend, research promotion thresholds, any cent/live account transition, subscriptions, publication of performance, default-branch merges and production deployments. He receives concise exception and milestone reports, not constant agent chatter.

**Grok Bot (Gaffer / Factory Coordinator):** Maintains one authoritative queue in issue #377 and future child issues; assigns work; controls dependencies and costs; checks that each specialist's deliverable has independent review; escalates only decisions or genuine blockers. Grok can create separate agent roles as organisational labels, but those names alone are NOT credential or filesystem isolation. Prevent overlapping agents editing the same file/branch.

**ChatGPT (Independent Design, Evidence and Financial Systems Reviewer):** Crosswalk reviewer for architecture, independent research evidence, accounting/reconciliation, risk, policy conflicts and second opinions. Can read and respond through `goldthinkerfactory`. Not a 24/7 synchronous operator; current scheduled checks are hourly. It does not approve its own work, and cannot confer owner authorisation.

## 3. Existing Grok team: keep and clarify these four

| Bot / role | Owns | Output and boundary |
|---|---|---|
| **Engineer** (existing) | Factory schemas, parsers, CLI, CI, integrations | Versioned draft PRs, reproducible tests, hashes, strict fail states. No live keys or production deploys. |
| **MT5 Operator** (existing) | Separate restricted Windows research terminal, demo tester prerequisites, year-scoped runs | Broker/symbol contract, compile receipts, 2021–2025 completed years + 2026 YTD, actual raw reports and tester logs, rejected orders, tick coverage. **No funded/Gina/Super Signals terminal access.** |
| **Quant Reviewer** (existing) | Statistical/economic validation of original and modified strategies | Original-vs-variant assessment, cost stress, benchmark, OOS/regime, sample sufficiency, selection bias, negative evidence. Does not invent thresholds or self-certify an EA. |
| **Site Publisher** (existing, rename **Staging Site Editor** until launch) | Public-safe projection, individual system page, card and UX | **Private/noindex staging only**, clear stage labels, null absent data, rights and evidence links. Production publication requires owner approval. |

**Do not replace these four or spin up a large fleet before GT-00 is proven.** Add distinct roles first as *responsibilities*; instantiate separate scheduled Bots only when the workload, test coverage and permission boundary justify them.

## 4. Additional specialist roles, in activation order

### Phase A — GT-00 proof: add two independent roles NOW as review responsibilities

1. **Evidence Custodian / Ledger Accountant** — Needed because a valid strategy cannot be inferred from MT5 summary profit. Receives read-only raw reports, deals, orders, account cash adjustments and immutable hashes. Reconstructs position-level realised P&L from deals (including partial fills/closes, reversals, commissions, swaps, deposits/withdrawals), reconciles report ↔ ledger ↔ annual bundle, records unmatched rows and rejects fabricated/missing values. Also establishes period-cutoff and balance-vs-equity conventions. Must be independent of the Engineer writing the extractor. **GT-00 output:** one real annual ledger reconciliation receipt or explicit FAILED/BLOCKED evidence.

2. **QA / Red-Team Gatekeeper** — Needed because a green CI run with synthetic fixtures does not prove genuine execution. Tests tampered report, duplicated deal IDs, wrong broker clock, incomplete tick coverage, missing commission, 2026 YTD accidentally treated as full year, altered hash, mismatched totals, unauthorized paper/live claims and website publication leaks. Must not be the implementer of the code under review. **GT-00 output:** adversarial acceptance report and open blockers.

These can initially be tasks assigned to the Quant Reviewer and ChatGPT/independent reviewer respectively, but **independence of checks matters more than separate Bot labels**. Avoid the Engineer signing off its own outputs.

### Phase B — once GT-00 proves a real end-to-end run: add three production-research roles

3. **Source Scout & Licensing Researcher** — Systematically discovers original gold strategies from lawful public GitHub, videos and research, captures exact source, authorship, licence, dependencies, date and immutable source hash. Distinguishes original strategies from near-duplicates, unsupported claims and marketing. Cannot approve profitability. **Output:** provenance-backed candidate register and rights blockers.

4. **Rules Reconstructor / EA Compiler** — Converts independently verified complete rules into source-faithful, versioned MQL5 implementations; documents any ambiguity, input defaults, timing assumptions, slippage and source-to-EA parity. Separates original and modified versions, no quiet optimisation. **Output:** compile receipt, original-rule parity checklist and tested binary/source identity.

5. **AIDY Replay Investigator** — Independently rebuilds the selected highest-profitable *completed* year from AIDY's authorised historical inputs and source-faithful rules. Compares every entry/exit, timestamp, price, costs and cash against MT5, including unmatched trades; reports MATCH / MISMATCH / INCONCLUSIVE with residuals. Must not consume MT5 P&L as if it were independent proof. **Output:** replay receipt, source hashes and mismatch register.

### Phase C — only when authenticated forward paper operation is approved: add three operational roles

6. **Paper Fleet Operator** — Operates one isolated, appropriately permitted **demo/paper** book per strategy and separately any approved paper master. Records versions, signals, orders, fills, positions, margin and failures. Can stop an unsafe paper system; cannot self-promote to cent/live. **Output:** source-identifiable paper trades and uptime/failure logs.

7. **Risk & Portfolio Controller** — Independently monitors exposure, correlated strategies, margin, drawdown, kill switches, concentration, stopouts, portfolio allocation and account-level constraints. Owns risk exceptions, not a mandate to increase risk. **Output:** per-system and combined portfolio risk review, explicit owner go/no-go.

8. **Performance Accountant & Reconciliation Officer** — Finance-grade read-only account statements, broker balances/equity, deposits/withdrawals, realised/floating P&L, day/week/month/year/all-time windows, paper streaks and audit receipts. Ensures website feed reconciles with actual paper books; no fabricated or stale data. **Output:** dated, signed, public-safe performance snapshots and exception reports.

### Phase D — only when owner authorises customer-facing operation: add three service roles

9. **Promotion / Compliance Officer** — Enforces the three-month individual and six-month elite review-ready minima, source rights, truthful marketing, subscription eligibility, operational and jurisdictional compliance. Recommends a stage transition but cannot authorise it. **Output:** owner approval packet and immutable decision trail.

10. **Website Content & Brand Editor** — Creates unique names, artwork briefs, strategy explanations, risk disclosures, original/variant labels, system pages and evidence-linked customer tiles. Never relabels backtest as paper or silently edits returns. **Output:** approved, source-attributed staging content.

11. **Customer Integration & Entitlements Engineer** — Only after authorisation, implements broker-specific account consent, isolated tenant credentials, subscription controls, revocation, order limits and auditable access. No unreviewed copying into client accounts. **Output:** tested permissions/security controls and revocation evidence.

### Cross-cutting support, not a bot explosion

12. **Infrastructure / Security & Reliability Engineer** — May be a rotating specialist rather than a permanent Bot. Owns CI secrets boundaries, isolated runtime identities, job scheduling, alerting, backups, observability and spend caps. No access to funded broker credentials for research work. **Output:** security audit, recoverability test and cost dashboard.

13. **Research Programme Analyst / Daily Reporter** — Can be a scheduled Coordinator function. Aggregates candidate pipeline, blocked reasons, test costs, daily/weekly/monthly progress and review queue. **Output:** short evidence-linked owner dashboard, not daily speculative P&L headlines.

## 5. Who hands work to whom

| Gate | Producer | Independent checker | Required evidence | Next action |
|---|---|---|---|---|
| Source eligibility | Scout + Rules Reconstructor | Quant Reviewer + rights check | Exact source, licence, frozen rules, duplicates, baseline | Admit to isolated research queue or BLOCK |
| Native MT5 run | MT5 Operator + Engineer | Evidence Custodian + QA | Build, broker contract, real tick coverage, six annual logs, raw report/ledger hashes | Annual bundle; retain failures |
| Research candidate review | Quant Reviewer | ChatGPT + Evidence Custodian | Costs, DD, trade sample, benchmark, regime, losing years, policy version | Owner review; no auto-pass |
| Selected-year parity | AIDY Replay Investigator | QA + Quant Reviewer | Trade-by-trade MT5↔AIDY matching and residuals | MATCH/MISMATCH/INCONCLUSIVE |
| Forward paper | Paper Fleet Operator | Risk Controller + Accountant | Real separate demo book, statements, reconciled equity, uptime | Paper observation; no auto-cent |
| Individual review-ready | Promotion Officer | Accountant + Risk + owner | 3 consecutive profitable complete reconciled paper months, source rights, approvals | Owner decision only |
| Elite review-ready | Portfolio Controller | Accountant + independent review + owner | 6 months per component, **single** combined account evidence, correlations and kill switches | Owner decision only |
| Public site/subscription | Site Editor + Integration Engineer | Compliance + Accountant + owner | Signed safe feed, permissions, consent, security, source links | Owner-controlled deployment |

**Work contract for every Bot:** ticket ID, source link, task, allowed tools, forbidden actions, input artefact hashes, expected output path, test/acceptance conditions, cost/time budget, owner and independent reviewer. Status must be one of BLOCKED / IN PROGRESS / PASS-SCOPED / FAIL / INCONCLUSIVE / REVIEW-READY / OWNER-APPROVED. A scoped CI pass must never be shown as a strategy or economic PASS.

## 6. Gaffer's operating rules

- **One lead, one queue:** Issue #377 is GT-00; later work gets numbered child issues and small draft PRs. Preserve PR #374 unchanged. No disconnected repo, spreadsheet or undocumented cloud computer edits.
- **Bounded concurrency:** GT-00 = one source, one isolated MT5 tester, one extractor, one AIDY reconciliation, one staging card. No 83 concurrent terminals. Add agents when the first chain is repeatable and audited.
- **Credentials:** Grok Bot names share a cloud computer and browser state. For true separation use different service identities, OS users, secret scopes and MT5 directories. Never paste credentials into Crosswalk/GitHub; do not reuse funded account or Super Signals credentials.
- **Audit:** immutable source hash, code commit, tester build, symbol contract, UTC/broker clocks, cost assumptions, data coverage, original and modified rules, versioned thresholds, reviewer identity and decision history. Missing evidence stays NULL/BLOCKED.
- **Research policy:** numerical thresholds currently UNAPPROVED. Do not retrofit to the selected winner. Pre-register candidate-specific trade-frequency and cost/risk rules with the owner; preserve out-of-sample tests, passive-gold benchmark and all failures.
- **Money and publication:** No broker account creation/funding, KYC workaround, cent/live trades, default-branch merges, public deployment, subscriber activation or performance marketing without explicit owner approval.
- **Budget:** request approval for paid APIs, compute/VPS expansion or long-running infrastructure. Start with existing authorised data and existing resources. Track runtime and actual cost per candidate.
- **Communication:** Engineering updates belong in GitHub, concise handoffs in Crosswalk `goldthinkerfactory`, decisions to Danny. ChatGPT can review on its schedule but is not an always-online service.

## 7. Next seven assignments, in order

1. **Gaffer:** record current four Bots' responsibilities and name one independent Evidence Custodian and one QA reviewer (can be temporary roles); make clear these are not separate credential boundaries.
2. **MT5 Operator:** report the isolated research terminal/demo tester readiness and exact access blocker. No touching existing funded/Gina/Super Signals processes.
3. **Gaffer + Quant Reviewer:** choose **S040 for a toolchain smoke only**, based on existing native comparison work and known missing tester account. No original owner-approved profitability EA is fixed yet. For subsequent economic research, prioritise **S016 20/20** as provisional, **S083** secondary; confirm source/EA parity before running.
4. **Engineer:** implement report/ledger extractor and fail-closed v2 schema with synthetic/tampered fixtures on draft PR #376; maintain v1 compatibility and avoid claiming synthetic tests are real MT5 evidence.
5. **Evidence Custodian + QA:** write the independent reconciliation acceptance and adversarial tests; check deals-vs-positions, partial closures, cost attribution, hashes, account flows and report-vs-ledger totals.
6. **AIDY Investigator (initially Engineer + independent Quant review):** prepare selected-year trade-by-trade replay and mismatch receipt, but mark it NOT_EXECUTED until a genuine native report exists.
7. **Staging Site Editor:** produce one noindex, source-attributed card and detailed page with all absent forward paper/cent/live figures NULL. Do not deploy to production.

**First milestone report to Danny:** what ran for real, what is only synthetic, what failed, what costs were incurred, the current critical blocker, the next decision needed, and links to exact GitHub artefacts. The goal is a reproducible evidence-producing factory, not a theatre of agents reporting progress without trades, source data or reconciliations.
