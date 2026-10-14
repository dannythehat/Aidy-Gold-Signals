# AIDY STRATEGY LAB — ENGINEERING ROADMAP v1
Date: 2026-10-14 | status: proposed / unimplemented unless linked evidence proves otherwise
Parent specification: docs/strategy-lab-customer-audit-contract-v1.md
Owner intent: internal GoldThinker bulk independent XAUUSD strategy tests first; customer-grade testing portal subsequently.
Safety boundary: do not change production signal worker, GoldThinker execution, Super Signals or brokerage. Every engine change is reviewed on separate PRs.

## MANDATORY DELIVERY POLICY — REAL BUILDS, NO MOCK COMPLETION (owner directive, 14 October 2026)

This is an actual engineering programme. The type and deliverable of each numbered day are binding:

- **BUILD day:** implement production-intended working source code and integrations in AIDY's isolated development branch, plus tests and evidence. A specification or sample mock-up alone is NOT completion.
- **RESEARCH/AUDIT day:** inspect genuine source systems, repository code, recorded operations and/or verified external data; deliver a fact-checked report with links to evidence. Historical acceptance logs are not proof of current service access.
- **TEST/VERIFICATION day:** run actual tests in the required environment (including real historical BigQuery/R2 or other live infrastructure whenever the acceptance criterion demands it). A simulated fixture can demonstrate a component's behaviour but never substitute for an explicitly required real-data, broker-parity or operational verification.
- **REPORT/PORTAL day:** deliver actual end-to-end report rendering, security boundaries or customer-facing behaviour as specified, not design screenshots alone.
- **Mixed day:** satisfy ALL relevant categories, not the easiest one.

**Gate rule:** Do not mark a day PASSED because files were written, a CI test merely started, a synthetic fixture passed, or a plan exists. The day must satisfy its actual defined pass criteria. Record commit SHA, exact tests/run URLs, input/data provenance, output digests, blockers and limitations. If not all pass, status = PARTIAL / BLOCKED / FAILED and continue work on that same day. No calendar-based automatic progression. Never invent performance, data access, licensing, parity or customer readiness.

**Production protection:** 'real build' means code intended for the finished service, not permission to modify live AIDY decision logic, GoldThinker terminals, brokerage, or customer environments without separate explicit owner authorisation. Work in isolated branches; preserve existing integrity and evidence-semantic gates.

**Status accounting:** keep distinct (a) day-level evidence PASS, (b) stage-level technical acceptance, (c) owner's stage approval, and (d) production deployment. Never imply these are the same. Owner/admin uses the same verified test engine as customers, with billing exemption only.

**Daily handover:** update Notion's NOW / NEXT / BLOCKERS / COMPLETED, link source/PR/run evidence, and state clearly what was actually built and tested versus still only designed. This policy supersedes any weaker description of 'done' elsewhere in this roadmap.

## How we work (repeat for EVERY batch)

1. **Discover** actual relevant code, dataset and operational evidence. Mark PRESENT/ABSENT/UNKNOWN; don't infer successful deployment from docs/tests alone.
2. **Freeze contract**: exact interface/schema, expected output, acceptance thresholds and failure tests before implementation.
3. **Build small**: separate module and tests, ideally single focused PR, with change log and fixed seed/data.
4. **Verify**: automated unit/property/integration/regression tests; reproducible fixtures; independent golden results; negative tests; no permissions creep.
5. **Prove**: write an evidence file containing commit SHA, dataset hash, run command, test output, pass/fail and known caveats. Claim DONE only when independently reproducible.
6. **Gate**: owner reviews risk and accepts; next stage begins. A demo, documentation or synthetic fixture is not production proof.

## Status vocabulary

NOT STARTED / DISCOVERY / CONTRACT FROZEN / IMPLEMENTING / TESTING / FAILED / PASSED / OWNER ACCEPTED.
Anything not supported by immutable evidence remains NOT STARTED, even if an adjacent AIDY subsystem exists.

## Dependency map

B00 Inventory -> B01 Data -> B02 StrategySpec -> B03 Broker model -> B04 Account/fills -> B05 Ledger/reconciliation -> B06 Strategy adapters/parity -> B07 Statistical evaluation -> B08 Reports -> B09 Internal batch console -> B10 Customer intake/security -> B11 Billing/launch.
Parallelisation: B02 may run beside B01; B07 can be designed beside B03–B06; B08 template can be designed beside B07; neither counts as PASSED until dependencies pass.

## Stage tracker

| ID | Stage | Verifiable deliverable | Test / release gate | Depends | Status |
|---|---|---|---|---|---|
| B00 | Repository/data/runtime inventory | Machine-readable matrix of existing code, environment, dataset partitions, SHA/version, licenses, schemas, report capability and gaps | Every assertion points to code or immutable evidence; external data access limitations explicitly labelled; production untouched | — | DISCOVERY |
| B01 | Data qualification | Versioned XAUUSD M1 and tick/bid-ask manifest, calendar/timezone/DST parser, gaps/quality report, export interface | 100% source-file manifest, duplicates/invalid OHLC rejected, DST/weekend fixtures; independent coverage report; unknown data not called verified | B00 | NOT STARTED |
| B02 | Canonical StrategySpec v1 | Strict typed schema, rule completeness validator, canonical JSON/hash; supported indicator reference definitions | Known simple strategy validates; missing stops/exits/warmup/session/data definitions rejected; hash stability and no hindsight | B00 | NOT STARTED |
| B03 | BrokerProfile + cost model | Broker symbol contract registry, quote/fill sides, lot increments, margin, commission, swap, slippage policies | Known bid/ask long/short fixture; lot/tick and FX currency maths independently reconciled; unsupported fee or tick contract blocked | B01,B02 | NOT STARTED |
| B04 | Order/fill/account engine | Chronological state machine for entries/exits/orders/positions with starting balance $10,000 | Next-open fill; SL/TP ambiguity adversarial-first; gaps, reject/partial, trailing, pyramiding, hedging/netting, margin tests | B03 | NOT STARTED |
| B05 | Immutable ledger and accounting | Deterministic order, fill, cost, equity/cash journal + hashes, run manifest | Every cent reconciles; duplicate idempotent; replay byte-stable; tamper/missing event fails; flat strategy stays $10,000 | B04 | NOT STARTED |
| B06 | User strategy fidelity adapters | Phase 1 human-confirmed written rules and Python DSL, then Pine and MQL4/5 source interpreters with verified supported subset | Source-parity signal and trade fixtures for each enabled language; untrusted code sandbox/isolation; unsupported features fail visibly | B02,B05 | NOT STARTED |
| B07 | Research/evaluation core | Trade analytics, drawdown, risk/return, out-of-sample, baseline matching, regimes and evidence score | Known-answer analytical fixtures, split leakage tests, null baselines, small sample results INSUFFICIENT; repeatability | B05,B06 | NOT STARTED |
| B08 | Customer-grade reports | Canonical result JSON, PDF, CSV ledgers, charts, verdict/score and reproducibility appendix | Every report number equals ledger; no invented score; verified vs claimed distinction; PDF visual review | B07 | NOT STARTED |
| B09 | Owner research console | Batch queue, dedup, experiment comparison, import/export to Gold Edge sheet; free owner billing entitlement | 100+ queued synthetic run integration with quotas and resumability; owner and customer share engine; no automatic trade promotion | B08 | NOT STARTED |
| B10 | Customer intake and tenancy | Secure multi-tenant uploader/paste/link, permissions, validation, reports/history/downloads/deletion | Cross-user data isolation; upload malware/untrusted code; rate limit, retention, idempotency; no broker credentials | B08,B09 | NOT STARTED |
| B11 | Payments and controlled beta | Entitlements, billable quota/metering, cost caps, privacy/terms/licence assessment, incident/rollback checklist | Two-user paid sandbox transaction; owner exempt from billing; independent report replay; no uncontrolled cloud cost; formal owner go/no-go | B10 | NOT STARTED |

## Definition of done for every stage

- A fixed written specification and change-history/digest.
- A versioned implementation with automated tests, including failure cases.
- Independent accepted examples and exact instructions for Windows PowerShell invocation (user environment).
- Input fixture/data hashes, exact Git SHA, output artefact SHA and a test run evidence bundle.
- A plain-language stage verdict: PASSED / FAILED / BLOCKED with remaining risks.
- No alteration to live AIDY/GoldThinker/Super Signals without explicit owner approval.

## FIRST SPRINT: B00 — inspect, don't build a trading engine blindly

Outputs:
1. `research/strategy_lab/b00_repo_inventory.json`: core repo paths, versions, entrypoints, existing contracts, unit tests, external dependencies.
2. `research/strategy_lab/b00_data_inventory.json`: real dataset location/format/timezone/source/license/date range/M1 row counts/gap rates/bid-ask availability, each TRUE vs UNKNOWN. If remote store inaccessible, deliver read-only scripts and explicit verification command.
3. `research/strategy_lab/b00_gap_register.md`: confirmed reuse / missing / unknown; ranked by impact on accurate economic backtesting.
4. `research/strategy_lab/b00_acceptance.md`: evidence refs, status and owner decision gate.
5. A no-write inventory probe to run against existing private archive using read-only credentials, without exposing source raw data or credentials to a report.
Acceptance for B00: all key data assumptions are measured rather than asserted. AIDY full M1 history and broker quote/clock reconciliation are known or explicitly BLOCKED, never guessed.

## Critical implementation decisions to freeze before B03/B04

- Default reference broker/contract, and whether comparison is Vantage-specific or neutral. Use explicit named profiles, not universal XAUUSD lot assumptions.
- What is actual available M1 coverage in R2/BigQuery/on the Windows PC? Confirm file hashes and missing bars; research source license for commercial customer reports.
- Bid/ask tick availability vs reconstructed spreads; precise intrabar ambiguity and conservative policy.
- Strategy source interpretation: original exact code vs fully specified rules, and priority when instructions conflict.
- Risk variants: both original position sizing and standardised 1%-at-stop on a $10k account when executable.
- Internal experimentation vs paid-customer privacy, retention and evidence chain.

## Programme metrics (update on each gate)

| Metric | Target |
|---|---|
| Completed stages | 0/12 until evidence accepted |
| Historical coverage quality | Measured and disclosed, not a guessed percentage |
| Strategy fidelity | 100% match on specified platform golden fixtures, or NOT VERIFIED |
| Ledger arithmetic | Zero unreconciled USD cents in golden tests |
| Replay | Identical ledgers/reports for same frozen inputs |
| Import security | No network, broker keys or privileged filesystem from submitted code |
| Unsupported systems | Fail closed, NEVER fabricate approximate results under source title |
| Report numerical integrity | 100% traceable to canonical run records |
| Owner vs paid engine | Same results for same frozen run inputs |
| Live-money authority | None |
