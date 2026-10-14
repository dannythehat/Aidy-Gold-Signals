# B01 Day 06F — Actual historical gold tick recovery and R2 inventory

**Acquisition/storage recovery: PASS (14 October 2026).**
**Full Day 06 source/licensing/warehouse acceptance: STILL PARTIAL.**
No work has started on Day 11 under the owner's hold.

## Verified real outcomes

- Target **XAUUSD HistData Generic ASCII Bid/Ask tick ZIPs**, Jan 2020–Sep 2026 inclusive: **81 monthly source archives**.
- Original [2020–26 historical acquisition](https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/38522925686): **71 ZIPs** reported uploaded with real source tick validation. The original seven GitHub year manifests were retrieved independently via the authenticated GitHub connector.
- [Targeted recovery and byte-for-byte SHA readback](https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/38530864450): all remaining **10** monthly source ZIPs recovered, untouched original archives uploaded, R2 downloaded back, and exact original source ZIP SHA-256 matched. **All 10 month jobs + 11 source-preservation tests PASSED**.
- Independent subsequent [Cloudflare R2 bucket enumeration](https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/38533224909) found **81/81 exact expected keys with nonzero sizes, 0 missing**. The source manifests and recovery source-file SHA evidence contain **389,659,808 tick rows** and **2,714,707,139 ZIP bytes** across 81 months. This sum is for the contents stated by genuine source acquisition/recovery manifests; remote 81/81 listing is independently verified.
- Actual private storage: Cloudflare R2 bucket `aidy-memory-test`, prefix `strategy-lab/histdata/xauusd/ticks/`, monthly object `{YYYYMM}/HISTDATA_COM_ASCII_XAUUSD_T_{YYYYMM}.zip`.
- Locally generated consolidated manifest SHA-256: `4617229c836d002bc2e916e5e16ad2a5cda3f604201901ee3605f1fde5387a2e` (includes monthly original SHA-256, counts, object keys, anomalies, readback status). Original 71 manifests were accessible through GitHub connector even though the read-only CI `GITHUB_TOKEN` returned HTTP 401 downloading older artifact ZIPs. That CI credentials issue **does not mean source files were missing**.

## Originally failed and now archived

| Month | Source chronology regression pairs | Original ZIP SHA readback |
|---|---:|---|
| 2020-10 | 1 | PASS |
| 2021-10 | 1 | PASS |
| 2022-10 | 1 | PASS |
| 2023-10 | 1 | PASS |
| 2024-10 | 1 | PASS |
| 2025-10 | 1 | PASS |
| 2026-06 | 1,402 | PASS |
| 2026-07 | 10,546 | PASS |
| 2026-08 | 2,707 | PASS |
| 2026-09 | 13,293 | PASS |

**Root cause of prior 10 source download *process* failures:** the acquisition script applied a chronologically strict *ingestion reader* before preserving the archive; these ten otherwise valid raw-source ZIPs contain out-of-order ticks. The fix performs source-month and valid bid/ask/ZIP checks, records source out-of-order pairs, archives the original ZIP byte-for-byte, and independently re-downloads the R2 object for SHA verification. Time without explicit milliseconds is now parsed as second precision before interpreting the fractional component. It **does not silently sort or modify source data**.

## Data integrity boundaries still open

1. The ten recovered archives all contain source-order anomalies. The existing strictly monotonic `iter_histdata_ticks` parser cannot ingest them unchanged. Deterministic, auditable chronological normalization into a **separate derived dataset**, keeping original ZIPs immutable, is required before trading simulations use their quotes. In particular the four 2026 months have thousands of out-of-order pairs.
2. All **71 earlier** objects were checked as nonempty and present on R2 and have original manifest SHA-256 values; they were **not all downloaded again to recompute remote SHA-256**. Only the **10 recovered** archives have independently verified exact R2 readback SHA-256 in this remediation.
3. The full 2020–26 bid/ask data has **not** been inserted into the BigQuery minute-quote warehouse. Earlier testing had only Dec 2024 and Jan 2025 in that derived table; source ZIP acquisition does not imply analytical ingestion.
4. Broker-specific Vantage tick values, executable spread equivalence, historical sessions/holidays, and HistData redistribution/commercial licensing remain unqualified. These gates must not be implied from storage success.
5. GitHub Actions artefact retention is time-limited; the real source ZIPs reside in R2. No live trading or production BigQuery writes were made, and no branch was merged.

**Owner-facing result:** The missing-download incident is repaired; full 81-month raw source archive is now present in private R2. Day 11 can be considered next for broker-contract engineering only; the Day 06 general checklist remains open until licensing, chronologically normalized derivatives, warehouse ingestion and completeness evidence pass.
