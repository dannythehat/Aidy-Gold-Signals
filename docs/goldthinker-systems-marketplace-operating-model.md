# GoldThinker — individual system marketplace and elite multi-system account

**Owner product direction — 16 October 2026.** AIDY is the internal research/validation engine. **GoldThinker is the customer-facing brand.** This is the product blueprint, not a live trading entitlement, broker account or deployment authorisation.

## Drive operations register — created and populated
- [**GoldThinker systems database**](https://docs.google.com/spreadsheets/d/1ri94tJaaEiPGbhRaFyA12kUUl4l3enP3jzOepX1RCsU/edit): 83 original AIDY candidates (read-only copy of names/source IDs from existing [83 candidate source scoreboard](https://docs.google.com/spreadsheets/d/14EbIPxW5ZeueRX0vz0i6qG7BmlosL04x8-xXl3Hh6N4/edit)); separate original historical runs/12-month snapshots, per-system $10K paper books, open/closed paper trades, month-end snapshots, approval gates, portfolio member attribution, master-account ledger, customer tile content, timestamped equity snapshots and risk events.
- [**S010 PDF**](https://drive.google.com/file/d/1pI3cH59oFAX9iQXVPBVX9n_64Ff78KBG/view?usp=drivesdk) attached to research-only S010. 2025 historic +150.328% modelled return, -33.671% marked DD, 83 trades, modelled costs; 2021 down-market test missing. Do NOT mark S010 broker-qualified, paper active, or available for purchase.
- [**Tile example and assets**](https://drive.google.com/drive/folders/1-aYD4o8_x_sLo3Uc4Q2qZ3j7Xr27I3JZ): responsive HTML/CSS interactive S010 working-name "CROSSFIRE" prototype with research and paper tabs, evidence link, strengths/weaknesses, trading timeframe, zero fabricated paper returns. [Source HTML stored in Drive](https://drive.google.com/file/d/1Mf1pTY8Pb3a2RAflDlhJpU496hNg1nP2/view).

## Buyer-facing individual system
Each system ultimately has a distinct permitted public brand name, bespoke art direction, explainable methodology and source/licence trail, UTC trading session/timeframe, long/short policy, independently reviewed strengths and negatives, market-condition profile, original vs optional improved research reports, dated historical chart and, once connected, **live-updating PAPER** stats. Date filters: day, week, month, year, all time. Fields: paper equity, original $10K start, external flows, net closed P&L, floating P&L, balances, margin and drawdown, 3-month current streak, every trade with ticket and source receipt, PDF evidence links.

**Names can be assigned as working drafts early, but public subscription/performance marketing requires the appropriate later gate and explicit owner approval.** First sample working name: CROSS FIRE / CROSSFIRE (S010), not a launched product.

### Owner's staged timing (minimum, not automatic risk approval)
1. **Research:** Reconstruct source rules, 1-year historical test, untouched same rules in opposite-market year. Only positive two-year result can trigger targeted small analyst improvement proposals; show original vs variant/why and failed attempts too. Apply realistic execution/cost/margin tests; don't fabricate broker quotes.
2. **Independent paper track:** $10,000 hypothetical seed per system **per separate system book**; independent MT5 paper positions, realised and floating P&L, identical method/version metadata; retain all trade IDs/quotes/costs and account statements. No paper accounts exist yet in this register.
3. **Individual subscription REVIEW-READY:** After **three consecutive profitable, complete, reconciled paper calendar months**, plus data-source verification, max drawdown/stopout review, broker execution parity, security, permissions/MT5 connection controls, compliance and owner approval. User's "unlocks itself" means qualification to activate an approved subscription, **not** circumventing account security/operational approvals.
4. **Elite master candidate REVIEW-READY:** Each component requires **six consecutive profitable complete reconciled paper calendar months**, plus a **combined** risk/correlation study, concentration limit, simultaneous exposure cap, loss kill switch, margin/liquidation checks, source provenance and owner approval. Six good separate systems do not imply their aggregate is safe or profitable.
5. **Premium master:** A **single separate paper master trading account** runs selected approved subsystems concurrently with explicit capital allocation, account-level initial balance, mark-to-market equity, cost/swaps, netting/hedging behaviour, correlated drawdowns, portfolio stopout checks and a per-system attribution ledger that reconciles with the master-account deal IDs. **Never sum 50 independent $10K paper equity curves and pretend that equals one shared account's return.** A premium paid product needs its own validated paper trial and owner go/no-go.

No live brokerage orders, no user credentials, no payments, no master paper portfolio, no subscriptions and no automatic entitlement creation in this build.

## Register data definitions
- **01_SYSTEMS** 83 imported *research candidates*, not 83 tested systems; source URL and private working/public identity kept separate.
- **02_RESEARCH_REVIEWS** immutable test run version, gold regime, full-year results, largest model win/loss, P&L, drawdown, model costs, evidence PDF and source sha.
- **03_RESEARCH_MONTHS** original S010 verified 2025 research months, monthly trade counts, biggest realised win/loss and modelled end-equity. Never mislabel as paper.
- **04_PAPER_ACCOUNTS** $10K hypothetical planned seed, actual MT5-account identity/clock/reconciliation only after creation.
- **05_PAPER_MONTHS** finance-checked month-end equity and actual net profits excluding deposits/withdrawals; largest wins and losses, actual spread/slippage/swap/commission, stopouts and evidence.
- **06_PAPER_TRADES** UTC deals, lots, actual quote-side fills, cost allocation, realised net profit, MAE/MFE, account/deal IDs and broker audit SHA.
- **07_ELIGIBILITY** manually source-backed monthly streaks and operational approvals; formula yields **REVIEW-READY only**, NEVER grants an active MT5 entitlement in Sheets.
- **08_MASTER_ACCOUNT**, **09_MASTER_MEMBERS** individual master account ledger and approved component weights, co-exposure and risk checks.
- **10_CUSTOMER_TILES** copy, identity, source-backed paper metrics and asset/report URLs with metadata.
- **11_RULEBOOK**, **12_ACCOUNT_SNAPSHOTS**, **13_RISK_EVENTS** definitions, future timestamped account-equity feed and halt/stopout investigations.

## UI / integration principles
Google Drive is the **operations and report register**, not a streaming data backend. The eventual website reads structured source-authenticated, timestamped and reconciled per-system and master account snapshots from a security-isolated backend. A standard tile component supports named strategy identities, distinct illustrations, research report, live paper P&L and owner-verified stage; no paper-data placeholder is repackaged as profit.

**Subscription security:** Each client MT5 brokerage account must be explicitly authorised and technically isolated. Separate customer/subscription entitlements and agent loop identity; encrypted secrets/secure key rotation and revocation; limits and emergency disable; broker-specific market permissions; consent and compliance/regulated-service review. Neither Drive nor Canva should store MT5 login credentials, investor passwords, or trade-signing secrets.

## Truth and naming guardrails
- Historical model return ≠ live-paper return ≠ customer live outcome.
- Research passed ≠ paper production started ≠ subscription sale allowed.
- 3 and 6 months = **eligibility minima**; an owner-approved risk/operational/correlation check still applies.
- A system may show a gain yet be excluded due to excessive drawdown or hard liquidation.
- Each system and the master has independent day/week/month/year/all-time arithmetic and auditable source.
- No imaginary paper accounts, customer counts, balances, returns or live trades.
- AIDY's 81 original 2020–Sep2026 raw tick ZIP archives exist, but normalisation and broker-parity gaps remain for complete cross-regime real BID/ASK backtesting.

## Immediate next integration work
1. Finish independent account-level margin/stopout source-quote engine, historical BID/ASK ingestion, swap/broker contract provenance and cost-sensitive reruns.
2. Source-normalise the already archived 2021 BID/ASK ticks and test original S010 unchanged in 2021 down/sideways year, comparing 2025 bull.
3. When original is promising in both, permit tightly defined evidence-led edits and publish accurate original-vs-modified PDF comparisons.
4. Build service and synchronisation boundaries for system-specific $10k MT5 paper accounts, then rolling 3-/6-month reconciled eligibility.
5. Finally build separately risk-managed premium paper master portfolio, client-facing website and explicit subscription/connection authorisation.

Source-of-truth: original Drive [83 candidate scoreboard](https://docs.google.com/spreadsheets/d/14EbIPxW5ZeueRX0vz0i6qG7BmlosL04x8-xXl3Hh6N4/edit); technical S010 [PR309](https://github.com/dannythehat/Aidy-Gold-Signals/pull/309); opposite market gate [PR310](https://github.com/dannythehat/Aidy-Gold-Signals/pull/310).
