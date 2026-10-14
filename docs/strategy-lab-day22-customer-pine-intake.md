# Day 22 — Customer Pine Script submission intake

## Locked commercial model

**Customers submit trading strategies to AIDY.** AIDY independently analyses, translates supported rules, tests and reports. We do not require customers or the owner to use TradingView or produce TradingView exports. Discovering public strategies for our own research is a separate optional workflow.

## Delivered engineering addition

- `src/aidy/strategy_lab_customer_pine_intake.py`: deterministic original-byte SHA-256 evidence and strict customer-facing intake receipt for an original Pine script file or pasted source.
- Accepts supplied Pine script version and detects strategy/indicator/library declaration without attempting to execute Pine or invent missing order rules.
- Distinguishes `SIGNAL_SUBSET_SUPPORTED_REQUIRES_REVIEW` (our already tested exact Pine v6 EMA long crossover subset), `RULE_RECONSTRUCTION_REQUIRED` (other/customer-specific scripts), and `NEEDS_SCRIPT_IDENTIFICATION` (version or programme type incomplete).
- For other scripts, identifies supported high-impact gaps (higher timeframe/lookahead, intrabar, exits/orders, loops/state/alerts, indicator-only sources) and asks ordinary-language questions about rules, exits, risk, hours, and broker costs. It **does not** pretend that detecting keyword text constitutes safe execution or full understanding.
- Uploaded filename is a display label only, never a file to write; rejects relative paths, control characters, unbounded or non-UTF8 content. Submitted code is never imported/evaluated/executed, and no external accounts, broker orders, user data stores or provider exports are invoked.
- `scripts/strategy_lab/day22_triage_customer_pine.py` performs a read-only local inspection of an original Pine source document and emits a structured JSON customer-explanation receipt.
- This does **not** replace the future B10 customer portal, full Pine language support, customer data retention/privacy checks, or a fully qualified risk and exit StrategySpec.

## Separate external platform calibration

- Existing source-hashed restricted importer [PR #268](https://github.com/dannythehat/Aidy-Gold-Signals/pull/268) and chart reference verifier [PR #269](https://github.com/dannythehat/Aidy-Gold-Signals/pull/269) are already merged.
- The roadmap's **specific original-TradingView signal parity gate** remains outstanding. Public unauthenticated original references collected so far are **different scripts**. Genuine output from the supported calibration source has not been authenticated.
- Independent parity is a separate engineering evidence tier and is **not** a requirement for customers to submit a strategy. Any verification receipt based on synthetic source or customer self-labelled data must retain an **unverified** provider status.
- **14 October 2026 scoped day-level update:** Day22 internal customer source-intake/adapter checkbox is now accepted after independent genuine XAUUSD historical-data reproduction and 122 passing tests in [PR #273](https://github.com/dannythehat/Aidy-Gold-Signals/pull/273). The *original* stronger criterion — exact TradingView-native source/platform parity — remains **separately UNVERIFIED** and must never be relabelled as provider parity. No user/customer TradingView account is required.

## Acceptance CI

Test original-byte determinism, supported subset recognition, unsupported/customer-specific strategy review, missing source/file metadata, altered source SHA, untrusted Python payload as data (never run), and no technical provider requirement. Record actual passing CI and merge IDs once verified.


## Real historical market-data proof — final Day22 internal scope

[CI 38615858064](https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/38615858064) verified 600 real XAUUSD M1 bid records, 120 fully closed M5 bars and two independently agreeing EMA(10)/EMA(30) crossing timestamps, **15:30 and 18:25 UTC, 6 January 2025**. Exact replay of the historical source digest passed. Tests: **122 PASS**; [evidence gate 38615857818](https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/38615857818) PASS. GitHub [PR #273 merged into main](https://github.com/dannythehat/Aidy-Gold-Signals/pull/273). This qualifies AIDY's internal deterministic supported-subset pathway, not the TradingView engine or a whole customer trading system. The older anonymous login-gate finding stands unchanged.
