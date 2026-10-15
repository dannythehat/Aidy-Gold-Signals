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

**PASS — working interactive HTML, safe intake and authentic CI proved (15 October 2026).**

- [Day35 working implementation PR #300](https://github.com/dannythehat/Aidy-Gold-Signals/pull/300) **MERGED into protected `main`** squash SHA `9db00d86e5587151f96c1f1fbf798460ecf4a05a`. [Original full acceptance CI run 38720118901](https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/38720118901): **260 automated unit/adversarial + locked previous stage regression tests PASS**, actual extracted HTML JavaScript syntax checked via Node, strict Ruff and compilation PASS, private original binary/security scanner PASS, genuine historical XAUUSD BID-only source replayed TWICE via original Day34 BigQuery and original 83 Gold Edge candidates still UNTESTED. [Independent evidence semantic gate 38720118980](https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/38720118980) PASS.
- **[DOWNLOAD ACTUAL DAY35 HTML FORM, FOUR SAMPLE INERT DRAFTS AND EVIDENCE ZIP](https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/38720118901/artifacts/11964318671)**: archived by real CI under GitHub artifact ID `11964318671`. Extract and open `web/strategy_lab/day35_private_intake_preview.html` locally; choose paste/upload/link/template, enter 10 rule details, and generate local draft JSON. No network upload, true customer server, authenticated licence, backtest/trade or market execution is implied. The HTML is a private offline test prototype, **not a public GoldThinker website**.
- **Actual validation outputs:** `day35/intake_acceptance.json` `status=PASS`, 4/4 submission modes, 9/9 unknown-rule reminders for partial case, seven independent named hostile-input cases correctly rejected (fake EXE and ZIP-as-TXT, active HTML, leaked-key text, loopback SSRF link, `javascript:` link, unsupported PDF). The full unit suite additionally includes unsupported TF and market, UTF8 decoding, URL credentials/token/fragment, file name traversal, source tampering and no-trading claims. All client drafts remain `trusted_server_accepted=false` and `aidy_research_executed=false`. Sending a malicious-looking draft to an actual future secure backend will require independent server-side revalidation; content hashes alone do not confer trust.
- **Independent economic evidence rechecked but no idea mining:** The actual locked Day34 read-only retrospective HistData XAUUSD original source digest is `50d0bc064f9a2dd91f93a38abc3ab9270d1f1f5082c9e85f936d276b5593207b`, queried in read-only BigQuery jobs `db8729c7-b2e3-4697-b478-dc2e78bb3eac` and `e5a2fdb1-056e-4c3e-96e7-1ac451883ec7` for this CI. Original 83-source register SHA `48899aee95fbdde7ec4bdf10ac28921911a68704817dc63205a3c09e49f5afd3` and source-linked dashboard SHA `2b40cfa98d542da23ac8f6b2303db466afe92f32d2b386d845f0ef839f6f5b54`. `0/83` strategies profitability-tested, `0` production handoffs and `0` paper accounts created. The 100 Day32 queue diagnostic runs are engineering-only, not strategy economic returns.
- **First CI run** rejected a strict Ruff import layout in two new Python files, corrected without relaxing any validation. Final CI independently re-ran all 260 tests and real archived source checks and PASS. Human/browser acceptance has **not** independently certified multi-tenant deployments, network sandboxing or public payments; these remain subsequent locked days. No auto-activation of untrusted strategy code or GoldThinker system production.

