# Day 30 — Actual downloadable PDF, complete CSV, chart PNGs and audit manifest

**Owner-locked B08 Day30:** "Produce complete report, full trades and cost scenario charts"; pass only when actual PDF/CSV/JSON reconciles against the Day29 original reference case. This build creates the real requested files, not a design, screenshot, promise, marketing-ready fictional investment record, or a rewritten 40-day roadmap.

## Source data and separation

- **AIDY** is the research/test/evidence engine. **GoldThinker** is the customer-facing name for future individually offered and paper-qualified strategies and the one-account **GoldThinker Elite 20** premium combined portfolio.
- The source case here is the frozen, real Day29 **canonical JSON** from `scripts/strategy_lab/day29_canonical_report_acceptance.py`. Its economic cash and trades are a **Day24 internal SYNTHETIC SQLite journal** and its three comparative cost scenarios are **Day25 internal SYNTHETIC BID/ASK quotations**. Days26/27 genuinely fetched retrospective XAUUSD historical BID M1/M5 are separate direction tests, NOT the source of these cash profits.
- The research sample is NOT GoldThinker public content. This builder refuses to export a customer-enabled, named, eligible, actual paper/live-funded or Elite20 combined-account return. The original **nine-factor research rating is null/ORANGE** with no authenticated real costed XAUUSD profit. *No synthetic $13 sample win becomes a published backtest result.*

## Software and actual deliverables

The working implementation is `src/aidy/strategy_lab_report_exports.py`. It accepts only the legitimate source-validated original Day29 report and builds the self-contained `artifacts/strategy_lab/day30/` folder:

| Actual file | Contents and important checks |
| --- | --- |
| `research_report.pdf` | Branded premium GoldThinker/AIDY multi-page **actual PDF**, financial facts, exact day/week/month/year/all-time realised P&L, full original 4 trades, 3 net cost scenarios, both embedded actual PNG charts, nine-factor evidence statuses, detailed original source SHA appendix and prominent synthetic-only/no-broker-profit disclosures |
| `trades.csv` | **Every** source-verified original journal close, exact gross/fee/net USD, UTC times, stable position ID, canonical run SHA, original journal receipt SHA, zero omitted fees |
| `cost_scenarios.csv` | All **three** base/adverse/severe separate quotation scenarios with full gross, commission/slippage/funding, candidate/clock-long/clock-short/scheduled-naive and exact reported differences, quotation/policy SHA and report-run SHA |
| `equity_curve.png` | Actual rendered high-resolution PNG of the *synthetic realised cash example*, a completed-trades step line, NOT forward paper account equity |
| `cost_stress.png` | Actual rendered high-resolution PNG of source-anchored cost-stressed candidate net versus independently scheduled naive long, explicitly synthetic |
| `canonical_result.json` | Exact original frozen Day29 JSON report for trustworthy programme access, original input cash/source hashes and all numeric lineage |
| `report_preview_page1.png` | **Rasterized independently from the finished PDF** using PDFium so the cover page image is not merely a separate illustration |
| `manifest.json` | Exact byte length and SHA256 for each of the seven downloadable assets and original canonical result SHA and run ID; exported files may be verified without trusting display text |

The original source accounting cash journal proves: initial $10,000, gross +$15, fees -$2, four completed synthetic trades with trade net `+9.50/-5.50/+14.50/-5.50`, net +$13, final $10,013. At **2026-10-01T11:04:00Z** the five original realised buckets are **DAY +$9, WEEK +$13, MONTH +$9, YEAR +$13, ALL-TIME +$13**. Monday-based week correctly spans 30 September and 1 October; September and October monthly buckets do not merge.

`scripts/strategy_lab/day30_actual_exports_acceptance.py` first runs the existing source-controlled Day29 generator from two authentic read-only real historical BigQuery acquisitions, verifies original input source SHA, renders and independently validates all seven assets, and writes an explicit PASS/BLOCKED receipt `artifacts/strategy_lab/day30_exports_acceptance.json`. Actual GitHub Action `.github/workflows/strategy-lab-day30-exports.yml` installs PDF, plotting and PDFium render libraries, reruns the full earlier financial/OOS/source tests, runs Day30 adversarial export tests, produces real artefacts and **uploads them as one downloadable GitHub Actions archive**.

## Exact acceptance and fail-closed evidence

- Every exported numerical accounting amount, trade, period and stress result must match the original source-bound canonical `run_id`/`canonical_result_sha256`, journal tip, quotation or policy receipt; the bundle source receipt comes from the actual Day29 double-read external historical source + the separately replayed actual on-disk SQLite synthetic known answers.
- Every CSV source row maps to an original indexed trade or cost scenario. Full CSV amount sums reconcile to the same PDF/JSON net return; no trade is omitted. Excel/Sheets formula text injection must be rejected, including misleading `=...` and `+...` formula prefixes in user-entered text fields.
- Re-reading each file against its recorded actual byte SHA256 detects any byte edit, loss, substitution or partial corruption. Additionally, editing the CSV and recomputing its manifest SHA still fails numeric source-of-truth verification.
- Every actual PDF page must independently render using PDFium with nonblank contrast. PDF text extraction checks source report hashes, economic amounts, synthetic warning, paper/Elite20 separation and all required report sections.
- Strict Ruff and compile checks, pypdf text extraction, PDFium render, Pillow image validation, realistic sample report tests, bad-source/paper-profit tamper rejection and previous Days24–29 full regression tests are mandatory; CI/merge and Notion only after actual PASS.
- Hash-verified research output here is **not** a validated arbitrary customer-submitted system or an independent authenticity signature, never permission to connect a broker; GoldThinker system name/hero image/public join come only **after** AIDY research and ongoing forward paper production both qualify and owner/licence approval. Elite20 requires one actual centrally reconciled broker/demo account, NOT the sum of standalone balances.

## Verified completion record

**NOT YET ACCEPTED** until actual downloadable files are produced, PDF pages rendered/tested, main PR merged, independent GitHub CI passes, and original real source and file SHA digests recorded here and in the owner Notion master tracker. Do not mark Day30 complete based on this document alone.
