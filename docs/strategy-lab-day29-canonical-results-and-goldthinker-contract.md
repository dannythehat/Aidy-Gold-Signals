# Day 29 — Canonical AIDY research results and traceable GoldThinker report contract

**Locked original scope:** B08 Day29: “Single canonical results API object and provenance appendix”; acceptance “Every number traces to journal and run hash.” This is a **working schema, true JSON report generator, negative tests, and actual audit artefact**, not yet a PDF, website, paper account, live broker account, or a profitable XAUUSD strategy.

## Exact brand and future product architecture

**AIDY** is the scientific engine. **GoldThinker** is the customer-facing brand and future website. A strategy is not named or published simply because source review or AIDY research finishes. Its lifecycle is candidate -> AIDY verified research -> individually isolated forward PAPER/DEMO production -> separately accepted forward results -> GoldThinker descriptive product NAME + profile/image -> owner-authorised individual system JOIN -> optional portfolio eligibility. Brand display names and unique individual accounts are **NULL** in this unqualified example.

**GoldThinker Elite 20** is a separate product with **ONE centrally funded combined account**, at most 20 qualified independently reviewed systems, shared risk limits and its own actual order/fill/cash ledger. Never sum standalone system balances or portfolio member P&L as if it were a filled master account. It remains NULL until actually implemented and sourced; no performance or subscriptions are invented.

## Implementation and report fields

`src/aidy/strategy_lab_report_contract.py` produces `aidy.strategy_lab.canonical_result.v1` with exact source-verified identifiers, study kind, restricted publication/join status, AIDY research stage, as-of UTC, separate GoldThinker hypothetical paper and Elite20 areas, original realised research accounting metrics and the complete four-trade synthetic reference ledger; research stress scenarios, Day28 nine original weighted evidence factors with missing reasons and literally `null` score. Every supported numeric first-party output for account balances, trade gross/cost/net, UTC day/week/month/year/all-time realised net P&L and win counts, cost stress USD and factor policy points has a source SHA and explicit JSON-pointer field lineage in the provenance appendix. Original synthetic trade ledger source and SHA-driven model are NOT combined with real historical BID direction performance into one fictitious system return.

Period calculations are based on the **same specific sample ledger**, UTC close timestamps and 4 completed trades: day, ISO Monday-based week, calendar month, year, all-time. Cash costs remain attributed and only realised closures enter the period net figure. Do not silently show a zero paper account return because the account does not exist: missing paper and master account figures are **`null`**.

`scripts/strategy_lab/day29_canonical_report_acceptance.py` generates the **real machine-readable JSON artefact** `artifacts/strategy_lab/day29_canonical_auditable_result.json`: it takes an independently verified Day24 original synthetic SQLite fixture receipt (the journal has physically been built and reconciled), reruns Day25 synthetic same-session naive and three bid/ask cost scenarios, runs the Day28 complete evidence audit which itself reruns prior Day24–27 fixtures and real retrospective historical XAUUSD BID-only samples, then reads 600 actual HistData M1 -> 120 closed M5 from two *independent read-only BigQuery queries* and replays the full canonical report identically. None of the synthetic cash trades are mistakenly presented as being produced by the real historical XAUUSD signal window; they are explicitly distinct study origins.

Day29 records a deterministic original-receipt-derived `run_id` and `canonical_result_sha256` over the complete content. `verify_canonical_report` detects modification without a matching hash. Recomputed hashes do **not** independently authenticate external data against malicious clients: later GoldThinker report API requires a trusted server-only adapter, immutable authenticated journal and tenant isolation. No user-supplied 64-char SHA or `verified=true` becomes source attestation by magic.

### Acceptance and test targets

- The Day24 synthetic known answer starts at `$10,000`, produces actual replayed trade amounts `+$9.50, -$5.50, +$14.50, -$5.50`, costs `-$2.00`, gross `+$15.00`, net `+$13.00`, ending `$10,013`. These are **toy cash ledger samples only**, not gold trading profitability.
- Sample as-of `2026-10-01T11:04:00Z`: realised Day `+$9.00`; Week `+$13.00`; Month `+$9.00`; Year `+$13.00`; All Time `+$13.00`, with each exact number recalculated from the original journal's four synthetic trades and labelled as such.
- The same example retains `GoldThinker name = null`, `join = false`, `published = false`, `forward paper P&L = null`, `Elite20 combined P&L = null`, nine-factor evidence score `null`, ORANGE, actual PDF/CSV/charts `DAY30_NOT_BUILT`.
- Adversarial tests must fail on changed ledger cash total, costs, closed trades, duplicate trade ID, bogus journal or cross-stage SHA, attempted GREEN score, future-dated closings, non-UTC as-of, tampered paper money/publication flags and missing provenance. Original Day24–28 regression suite runs in CI as well.

### Product limitations

The experiment only has 4 synthetic closed trades and a genuine historical *BID direction* diagnostic: neither is verified costed original-market gold strategy returns. A source receipt and a single research `$10k` display must not be equated to a dedicated forward-running paper account. No customers can connect in this build. GoldThinker strategy name, poster/hero image, website details, live paper investment graph, premium system or broker integration are later deliberately separate implementations. The Day30 promise to **actually generate downloadable PDF, CSV and charts**, not merely specify them, remains unchanged.

## Final verified CI and protected main source

PENDING until actual green CI, real two-read BigQuery replay, protected-main merge and evidence update. Preserve all run IDs, source hashes, code commits, limitations and no-alpha disclosures; do not falsely mark Day29 complete.
