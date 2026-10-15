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

**PASS — working code and ACTUAL DOWNLOADABLE ARTEFACTS verified and merged (15 October 2026).**

- **Working [PR #289 — seven real exported files](https://github.com/dannythehat/Aidy-Gold-Signals/pull/289) MERGED into protected `main`**, squash SHA `6e1f5f270108da65cea11da5d7bf687cae989b05`. [Final original CI 38702568755](https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/38702568755) **PASS 158 tests**, strict Ruff/compile, genuinely generated four-page PDF, original full four-trade CSV and three-scenario CSV, two real chart PNGs, independently PDFium-rendered PNG cover, canonical JSON and their exact SHA byte manifest. Complete original Day24–29 regression suite including adversarial cash and false customer paper P&L tests PASS. [Evidence semantic gate 38702568737](https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/38702568737) PASS.
- **[DOWNLOAD THE ACTUAL COMPRESSED REPORT FILES](https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/38702568755/artifacts/11956279199)** — GitHub Actions ZIP ID `11956279199`, verified successful 331133-byte archive. Includes `research_report.pdf` (4 actual extractable-text pages), `trades.csv`, `cost_scenarios.csv`, `equity_curve.png`, `cost_stress.png`, `canonical_result.json`, `report_preview_page1.png`, `manifest.json`, source/provenance run receipt `day30_exports_acceptance.json` and Day29 independently acquired original historical source receipt. GitHub Actions artifact retention currently **90 days**; archival long-term retention and user-system deployment remain future infrastructure.
- **Original true historical source checks:** original retrospective XAUUSD HistData BID M1 digest `50d0bc064f9a2dd91f93a38abc3ab9270d1f1f5082c9e85f936d276b5593207b`; independently run READ-ONLY BigQuery jobs `11cba028-a89b-4b83-87d4-7249c50d964c` and `a367f2cf-4182-4ffb-b527-c47b2938eba6`. The source's historical BID-only direction data have NOT been turned into false cash executions. Original Day29 canonical run `aidy-d29-f58da53ce086b411e8e554f9` and entire immutable research result SHA256 `c99842f76138ebe79d7e1696fb9955d810162fc44aff0283128034cd6ce5d670`.
- **Acted-upon report file SHA256 from real CI manifest**, byte-verified and independent-revalidated:
  - `research_report.pdf` — `1fbe3512f70d23b05d683fe26282bfe25d0b578d9960f7d2d9992d7ce06e299f`
  - `trades.csv` — `757dc1319d5605175cc364bac0a2b802772f61bd577c8f0db36557603ced8ab1`
  - `cost_scenarios.csv` — `a2b1d16419cd0b66415e5377659b77a911eda8aa039a1ced7c81c5bac70898cf`
  - `equity_curve.png` — `d361ed1666fcc93d03ace064cf101e28182377d94fc6aed3b7c774b37f034e36`
  - `cost_stress.png` — `e18f12763e166612e2355105dde723fe86ba84cccb74940abbd01006fe20d0df`
  - `canonical_result.json` — `0237c29484ec98b73cea59d05b1a97705f8c4aa9e32e757459fdb0a3a8a91c30`
  - `report_preview_page1.png` — `501273586787f023fc51691d9b869803f73b194e05266a26ec05a03c8dd5a2e4`
- **Exact known-answer separate synthetic cash ledger:** 4/4 closed trades; complete stress cases 3/3; costed synthetic original net `+$13.00` with source-linked date buckets DAY +$9, WEEK +$13, MONTH +$9, YEAR +$13, ALL-TIME +$13; fully consistent in parsed PDF, CSV and canonical JSON. All four finished PDF pages rendered and checked at original output time. The number `+$13` is **NOT actual XAUUSD alpha** or forward GoldThinker paper money.
- **Fixes honestly recorded:** first run failed strict import/typing format; next run exposed too-low PDF cover raster resolution and a test that expected different wording from an already-correct publication guard; the following full regression run passed all **158 tests**, then real JSON serialization sorted the unordered period keys, and the final run passed 158 again plus genuinely produced/downloaded all files. Production program identity remains separate: **AIDY engine, GoldThinker brand**, future per-system paper account P&L and GoldThinker Elite20 ONE master account P&L both `null`. All AIDY customer-access features remain disabled in this synthetic research example; real costed trading edge NOT FOUND/NOT PROVEN.
- **Next:** Locked Day31 B08 adversarial report acceptance (bad inputs, zero trades, mismatched data and misleading performance assertions) and owner B08 stage gate. Trusted customer-submission attestations, real broker/paper isolation, strategy naming/public launch and branding graphics are separate later capabilities; no scope was silently marked live.

