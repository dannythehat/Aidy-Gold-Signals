# Day 35 — B10 Customer Strategy Input Interfaces (private offline prototype)

**Owner-locked build:** Paste / upload / link / template; guided missing-rule form. **PASS:** Reject unsafe binaries and unsupported specifications. This Day35 is ONLY intake engineering and DOES NOT test any of the 83 collected gold strategies for profitability. The final lab audit must finish first.

## Actual delivered components

**Python server-side intake contract** `src/aidy/strategy_lab_customer_intake.py` accepts four inert source types, with original input SHA256, deterministic source/rule draft hash, explicit source kind, submission title, optional rights *declaration* and ten independently required strategy fields:

1. market (only XAUUSD);
2. native timeframe (M1, M5, M15, M30, H1, H4 or D1);
3. long/short/both;
4. objective entry/confirmation;
5. objective exits;
6. stop-loss (or explicit justified absence);
7. take-profit/other exit;
8. position sizing/risk;
9. named trading session/timezone/DST;
10. realistic order execution, spreads and fees/slippage.

Missing fields produce `INCOMPLETE_RULES` plus explicit field-level guidance. Populated fields produce `AWAITING_INDEPENDENT_RULE_REVIEW`; this does not claim evidence qualification or execute anything. The original submission and tenant identity are not authenticated; rights declaration is NOT a licence to copy or publish a customer's IP. The draft is an inert **untrusted input** for future human/engine examination, never direct Day34 authenticated source evidence.

**Actual interactive HTML file** `web/strategy_lab/day35_private_intake_preview.html`: offline responsive dark/gold AIDY private prototype with working paste, text-file selection, public HTTPS link, blank research template, rules questionnaire, missing-field hints, status feedback and local JSON draft download. User input is presented using safe `textContent`, not direct HTML. No HTTP request, form POST, customer server, storage, broker credentials, trading connection or public GoldThinker website. Downloaded browser draft is an untrusted client preview and **does not** carry a trusted Python server validation receipt or signed licence. Browser code has separate UX preflight; a future authenticated server must validate every source byte and all fields again via the Python module.

**Unsupported and explicitly rejected source material:** executables, archives, PDFs/images, arbitrary foreign script runtimes, uploaded UTF-16/non-UTF8, MIME claims with magic bytes matching ZIP/EXE/ELF/PDF/JPEG/PNG, NUL or controls, >64 KiB files or paste, unsafe credential-like content, active HTML/SVG/iframe/script text, unsupported market or timeframe, unsafe URL schemes, localhost/private IP/credentials/unexpected ports/tokens, unsupported template and extra rule properties. Filename cannot contain paths or traversal. A public HTTPS URL is recorded only as a source **reference**, NEVER fetched by Day35. A text `.pine` source is treated as **inert bytes**, never executable PineScript. No implicit performance or copying rights.

**Action lockdown:** All draft outputs have `tenant_authenticated=false`, `trusted_server_accepted=false`, `actual_licence_verified=false`, `strategy_rules_verified=false`, `eligible_for_production=false`, `aidy_research_executed=false`, `real_xauusd_profit_evaluated=false`, `paper_or_live_trading_enabled=false` and `goldthinker_named_or_joinable=false`. Even rehashed edited drafts cannot assert operational permissions. Day34 separate internally authenticated HMAC reviewer queue must NOT be fed directly from these customer drafts.

**Day35 acceptance code** `scripts/strategy_lab/day35_strategy_intake_acceptance.py`: generates four valid test-only drafts and seven rejected hostile attempts, confirms missing rule guidance and the actual HTML widget, archives `artifacts/strategy_lab/day35/intake_acceptance.json` and `four_safe_test_drafts.json`. `tests/test_strategy_lab_customer_intake.py` covers paths, MIME spoofing, binary signatures, malformed links, secret/HTML injection, title, source hash, nine missing fields and privilege tampering. The Day35 CI adds earlier Day28–34 regression and a genuine **Day34 historical read-only BigQuery double-replay** (original 83 registry still untested) before publishing downloadable artifacts.

## Source / future work boundaries

This static offline prototype is **not a deployed customer site, multi-tenant secure upload backend, virus scanner, safe remote URL fetcher, arbitrary PDF parser or working trading model compiler**. Formal tenancy, private persistence, upload malware sandboxing and permissions are Days36+ and later implementation. No actual strategy rules have been extracted from the 83 candidates, and the original B10 customer workflow is not production-ready.

AIDY is the independent evidence engine. GoldThinker is the future customer-facing brand; a strategy only earns its name, hero imagery, individual forward paper P&L and opt-in after passing actual independent AIDY evidence and subsequently its OWN paper account. GoldThinker Elite 20 will later have one centrally reconciled shared-risk master account rather than summing individual accounts.

## Final verified completion record

**PENDING** actual strict CI/acceptance, protected GitHub main merge and independent Notion verification. Do not mark owner Day35 checked until implementation and real source acceptance are green.
