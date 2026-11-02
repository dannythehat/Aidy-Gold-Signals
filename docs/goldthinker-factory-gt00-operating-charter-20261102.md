# GoldThinker Factory — GT-00 Chief of Staff operating charter v1
Date: 2026-11-02. Status: proposal / draft PR, NOT an operational or approved trading programme.

**Owner's mission:** Build a factory of distinct, traceable trading systems with AI doing almost all the research, coding, historical testing, independent checking, writing, deployment and monitoring. Source ideas from YouTube, related code/videos/transcripts, public websites, GitHub, TradingView, papers, communities and submissions. Display every investigated bot on GoldThinker with a short card, an explanatory strategy page, original attribution, historical results, exactly what is being tested, stage age, and individually reconciled paper/cent/live P&L. Operate authorised paper EAs continuously on a Windows server. Permit advancing funded accounts only after explicit owner-approved qualification, risk and account onboarding. Preserve and label failures.

This is **not** a promise that any strategy is profitable, a licence to copy proprietary source, permission to open/fund brokerage accounts, or authority to deploy to real money.

## The full conveyor belt

SOURCE DISCOVERY → SOURCE RIGHTS & DUPLICATES → EXACT RULE SPECIFICATION → MQL5 EA BUILD → INDEPENDENT CODE PARITY REVIEW → ISOLATED NATIVE MT5 BACKTEST 2021–2025 + PARTIAL 2026 → REAL MT5 REPORT / DEAL / COST RECONCILIATION → AIDY INDEPENDENT VERIFICATION OF **BEST COMPLETED YEAR ONLY** → NAMED VERSIONED PACKAGE → GOLDTHINKER CARD & DETAIL PAGE → AUTHORISED FORWARD PAPER/DEMO → BROKER P&L SYNC + HEALTH MONITORING → REVIEW-READY → OWNER-AUTHORISED CENT → CENT PERFORMANCE REVIEW → OWNER-AUTHORISED LIVE, WITH WATCHDOGS.

Preliminary paper or failure entries can exist as accurately labelled research cards; packaging and qualification must not manufacture "approved" results. The historical six years are *calendar-year scoped*, not a claim that all tick coverage currently exists. As of 2026-11-02, 2026 is YTD, NOT a complete year. Next years require a versioned date policy, not a hardcoded future claim.

## The existing Grok team (DO NOT duplicate these)

| Already appointed | Role in factory | Primary deliverables |
|---|---|---|
| WorkerBee / Grok Bot | GT-00 Chief of Staff / Engineering Programme Manager | Priority queue, dependencies, task assignment, deadlines, agent roster, daily board, approvals and blockers, Crosswalk updates to ChatGPT |
| Engineer | GT-04 MQL5 Developer + pipeline integrator (can temporarily include GT-05 tests, but NEVER approve its own parity findings) | Versioned original-source EAs, parser, manifests, tests and PRs |
| MT5 Operator | GT-06 Native MT5 Test Operator | Isolated Windows tester, real per-year tester runs, source log/ledger/report receipts, broker test account prerequisite |
| Quant Reviewer | GT-05 independent rule/code and metric reviewer, GT-07 AIDY replay examiner until separate role needed | Code/strategy parity, cost/risk analysis, independently reconcile highest-profit completed year |
| Site Publisher | GT-08 GoldThinker Editor / Card Builder | Catalogue entry, system detail page, stage history and source-backed P&L visualisation via draft PR / protected staging |

The four specialists plus the coordinator are the CURRENT proposed working team as described by Grok, NOT a claim that every workflow is fully deployed. One person/agent may wear two hats for the first smoke proof, but a different agent/reviewer must sign off independently on economic evidence.

## Bots to add and WHY (order of importance)

### NEXT WAVE: discovery and source fidelity (after one MT5 smoke proof)
**GT-01 YouTube Strategy Hunter.** Discover candidate videos by keyword/channel/subscriptions, capture link, creator, publish date, exact video timestamps, lawful transcripts/captions, linked GitHub/Pine/MQL/Python, claimed performance and any missing rules. Do NOT auto-repeat creator claims as facts; do not scrape against access terms. HANDOFF: immutable sourced lead to Rules Librarian. WHY: YouTube is a major existing source, yet manually researching/transcribing videos is expensive.

**GT-02 Internet / Research Hunter.** Scan relevant public GitHub repositories, TradingView, community posts, journals, technical papers, blogs and public repositories for new strategy source and explanations. Evaluate source lineage, version, licence, possible duplicates and instrument/timeframe. HANDOFF: source manifest. WHY: cover multiple channels beyond YouTube without manually copying ideas.

**GT-03 Strategy Librarian / Rules Reconstructor.** Deduplicate sources against the 83-candidate register and existing system families; reconcile inconsistent tutorial narrations and code; specify precise entry/exit, SL/TP, position sizing, hours, tick/lot units, broker clock, symbols, account assumptions, contradictory screenshots, and provenance/licensing. Freeze StrategySpec, classify incomplete ideas BLOCKED_RULES, return missing fact questions rather than invent trading rules. WHY: most AI trading-project mistakes begin with fabricated or silently changed strategy logic.

### NEXT WAVE: data and operations plumbing (can start immediately alongside MT5 proof)
**GT-12 Historical Data & Broker-Contract Steward** (new specialist, may start as MT5 Operator subagent). Inventory actual XAUUSD real tick datasets per calendar year and actual broker server, quote sides, GMT/DST, symbol suffix/contract size, quote spread, commission, financing, min lot/margin, gaps/rollover, Tester Model=4 availability. Certify *data coverage only*, never economic success. WHY: a six-year MT5-looking report is unreliable when the data and assumptions silently change.

**GT-13 Broker Demo Onboarding & Environment Provisioner** (new specialist, initially inside GT-09). Check which brokers allow automated DEMO creation and multiple isolated test accounts; inventory owner's existing PU Prime DEMO before requesting anything new; verify platform-specific account requirements/terms; prepare applications and runbooks. DO NOT impersonate user, complete KYC, create/fund cent/live accounts or obtain passwords by chat. WHY: each EA should have independent forward-testing attribution and MT5 needs a real authorised tester profile.

**GT-14 Site/Server Reliability & Integration Engineer** (new specialist, start as Engineer subagent). Build GitHub webhook/crosswalk job routing; idempotent queue; CI; Windows dedicated portable terminal setup; automatic restart/heartbeat/log rotation; R2 immutable evidence; D1 job index; site read-only signed feed; server costs and health; zero interference with Super Signals/Gina/funded accounts. WHY: 24/7 operation cannot be entrusted to unbounded chat loops.

### LATER WAVE: forward trading, finance, promotion (activate when paper demo is real)
**GT-09 Trading Fleet / EA Deployment Operator.** Owner-authorised DEMO stage installation of each approved EA on isolated terminal, per-system version/account/tag and risk budgets. Continuously watch broker connectivity, actual trading windows, order rejects, duplicate-trade and runaway losses. Funded cent/live stage requires separate explicit owner approval and credentials/risk scope. WHY: a successful MT5 backtest is not a persistent, accountable broker runtime.

**GT-10 Trading Performance Accountant.** Pull actual demo/cent/live deal/position/cash histories with read-only broker access; map broker account + deals + magic/comment + exact EA version; reconcile balance, equity, deposited/withdrawn cash, commissions, swaps, realised and floating P&L, open exposure, daily/week/month/all-time return, max equity DD; mark stale feeds and mismatches; publish only trustworthy read-only snapshots. WHY: website P&L must match its specific broker ledger and never use modelled historical profit as real profit. Current 21:00 local Super Signals cutoff is NOT assumed for new strategies; document whichever reporting day boundary owner chooses.

**GT-11 Qualification / Risk / Promotion Officer.** Maintain candidate's stage clock, risk evidence, source rights and proposed policy; compute eligibility for paper-to-cent and cent-to-live under approved criteria; prepare decision packet to owner. Owner approves funded account opening/funding, capital, risk size and final live launch. WHY: promotions need explicit, auditable sign-off and protection against cherry-picked historical winners.

### ON-DEMAND, not a permanent bot immediately
- Strategy optimiser / investigator: propose numbered variants *after* original unchanged baseline is frozen, with holdout discipline and all losing trials retained. No unrestricted self-tuning based on best-year profits.
- Rights/compliance review: check reuse of creator code, transcript, publication claims and brokerage jurisdiction before public pages or subscriptions.
- Security review: audit broker worker permissions, encrypted key stores, third-party code and site data boundaries, separate from authors.
- Presentation designer / SEO specialist: preserve existing GoldThinker visual system, responsive templates and indexing/release gates; no new separate website project.
- Portfolio construction analyst: a future single-account Top 20 / Premium master only **after** individual bots establish credible forward evidence; don't sum independent accounts and call it a portfolio.

## Suggested staffing sequence (minimum viable, not 15 subscriptions)
- **Today**: GT-00 + Engineer + MT5 Operator + Quant Reviewer + Site Publisher already reported by Grok. Attach GT-12 data steward to the tester and GT-14 CI/reliability to Engineer as *temporary responsibilities*, not necessarily new paid Bots.
- **After first actual native test and AIDY reproduction**: add GT-01 YouTube Hunter, GT-02 Internet Hunter and GT-03 Rules Librarian to generate a controlled pipeline of 1–3 qualified leads at a time; increase only after cost/quality controls work.
- **Before actual demo paper trading**: introduce GT-09 Fleet, GT-10 Accountant and GT-13 Broker Environment as dedicated roles or delegated subagents. No funded trading.
- **After multiple independently reconciled months**: add GT-11 Promotion Officer and on-demand optimisation/rights/portfolio agents. No automatic cent/live activation.

Bot count is a resource allocation, not proof of progress: 5 effective agents doing reproducible work beat 15 merely chatting. Create real specialist Bot identities only when the coordinator can demonstrate that role's tools, permissions, triggers, success receipts and cost envelope.

## Agent handoffs and responsibilities in detail

| Input | Responsible | Must hand to | Required receipt / stopping condition |
|---|---|---|---|
| New source/video | GT-01/GT-02 | GT-03 | URL, publication/creator, transcript or source hash, candidate family/rights, timestamped references |
| Researchable strategy | GT-03 | GT-04 | Frozen original rules/StrategySpec and original source mapping, no missing critical rules |
| Frozen rules | GT-04 | GT-05 | .mq5/.set, source hash, independent fixtures, PR, compile logs; no undeclared 'optimisation' |
| Review | GT-05 | GT-06 | Signed diff/rule parity; reject lookahead, timing errors, broker unit mismatches |
| Tester request | GT-06 + GT-12 | GT-07 | Per-year MT5 log/report, execution settings, deals/positions, drawdown/equity and costs; missing years documented |
| Historical outcome | GT-07 | GT-08 | Best **completed** year only AIDY detailed replay MATCH/MISMATCH/INCONCLUSIVE; all annual MT5 results kept |
| Verified research | GT-08 | Private GoldThinker staging | Permanent ID/name, source attribution, why testing, hypothetical results labelled, risks, current stage and immutable version |
| Approved demo start | GT-09 + GT-13 | GT-10 | Owner approval and specific DEMO account/EA version/risk, server startup receipt, live process heartbeat |
| Broker activity | GT-10 | Website feed / GT-11 | Broker-confirmed per-strategy ledger; balance/equity/realised/floating/costs/stale data |
| Eligibility recommendation | GT-11 | Owner | Months/trade count, full chronology, drawdown, licensing, risks, account terms, yes/no gate and human decision |
| Funded approval | Owner + GT-09 | Controlled CENT/LIVE worker | Actual broker account, risk/capital bound, 2-person review, rollback tested |

All jobs include job ID, source/spec/EA/test/config/data/report hashes, UTC times, exact agent identity, action performed, PASS/BLOCKED/FAILED with reason, next owner, and task/PR link. Crosswalk is the conversation. GitHub PRs and the protected job/evidence registry are the operational truth; no chat is accepted as trade proof.

## Important policy & existing evidence

- **Chosen EA for first proof:** *no owner-designated final EA*. Use S040 as a **native MT5 toolchain smoke candidate only**, because PR #374 has price/indicator parity evidence and the known missing tester-account blocker. After the toolchain works, S016 20/20 is the leading **provisional** profitability candidate, S083 secondary; neither is independently qualified or approved for deployment. S010 / CROSSFIRE is already a website research example but does not prove a full new pipeline.
- **Research threshold policy:** GT-00/Quant's PF 1.3, 30 closed trades/year, DD limits, 4/5 profitable years, doubled-cost stress etc are **unapproved discussion points**, not gates. Different system speeds can be compared fairly with confidence/sample warnings and audited risk policy. Freeze a proposal once the owner selects and understands the trial; never design tests to rubberstamp a winner.
- **Existing owner policy for product readiness:** docs/goldthinker-systems-marketplace-operating-model.md describes three consecutive complete, profitable, reconciled forward paper months to become **individual subscription REVIEW-READY**, and six such months to become **elite candidate REVIEW-READY**, subject to all risk and owner approvals. These are not automatic promotion permissions and not necessarily cent/live requirements. Actual cent/live thresholds need separate owner decision.
- The user now requests **2021–2025 completed years plus 2026 YTD** in MT5. AIDY replays **only the most profitable completed year**, not all six. Paper and cent stages are the forward robustness filter; a strong best year is not independent proof of future profitability.
- Live/funded/account provisioning and public website release require explicit owner approval; research and non-trading draft PR tests do not grant these permissions.
- Original GoldThinker web repository is separate from AIDY repository. Current website PR #28 fixes draft Wrangler build preparation but *Cloudflare deployment workflow skipped* at observed head. Do not state public staging release works until verified.
- Windows Contabo server is external, NOT currently connected through this conversation/Grok based on GT-00 report. Don't assume code has been executed on it. Protect existing follower workers.

## Day-to-day management

**Morning:** GT-00 reads the queue and crosswalk, records blocked/progressed/rejected candidates, allocates capped jobs, gets status of real Windows research runner and website feed. Discovery Bots add sourced leads only when capacity exists. Engineer works PRs; Reviewer checks source/implementation; MT5 tester records actual completed evidence; AIDY Investigator reviews best completed year where eligible. Site Editor stages new or updated cards and explains "why testing." Fleet and Accountant check broker runtime during genuine trading sessions. GT-11 runs eligibility calculations against approved version of policy.

**Throughout day:** completion events progress jobs. Retry limited, never duplicate trade/order/run or overwrite original ledger. For failures, persist evidence and report true exception rather than continuing optimistically.

**Evening:** one concise report: new ideas / videos, exact sourced strategies, builds, compiled, backtested, blocked, AIDY matched/mismatched, page drafts, active demo trades, separate realised and floating P&L per bot, stage elapsed days, exceptions, costs and owner approvals needed. Agents message each other in Crosswalk, avoid needlessly pinging owner. User can read entire project board.

## First three deliverables GT-00 should actually commission

**D1 — PROVE WINDOWS MT5 TESTER:** Restricted separate portable terminal, authorised demo profile, one source-faithful EA, compiled binary, per-year native run logs/trade ledger and raw report. Real annual coverage/provenance, not blank INI generator; own account and source details kept private.

**D2 — PROVE AIDY RECONCILIATION:** Reconstruct all orders/deals, choose best completed year ONLY using immutable rule, demonstrate detailed AIDY replay and mismatch fixtures. Capture source/quote/cost assumptions; no false qualification.

**D3 — PROVE WEBSITE RECORD:** Generate one safely attributed named system from real evidence, paper/cent/live null if not operating, include research status, reason for test, each year's actual test output, current stage age, and private staging preview. Confirm Cloudflare staging build actual execution and release gate.

Only after D1–D3 works should daily research volume, account creation or dozens of Grok Bots be switched on.

## Governance non-negotiables

- Source and licence before code reuse; the fact a YouTube transcript is publicly viewable is not permission to redistribute the original author's code.
- No passwords in Crosswalk, GitHub, public website or screenshot logs; least privilege, credentials separately scoped.
- One source strategy ID/family → many immutable variants, all negative results retained, no trial laundering.
- Backtest ≠ paper ≠ cent ≠ live; distinct money records, time periods and attributions, no fabricated account values.
- No broker KYC bypass, no automatic payments/deposits, no unapproved real trades, no public profit claim without independently backed evidence and release review.
- An agent report cannot certify its own financial results; independent review and server-side source checks mandatory.
