# B00 / Day 03 — Prioritised gap register and decision gate
Date: 2026-10-14
Status: DRAFT pending R2 Day02 proof and owner acceptance.

## Evidence-linked baseline
- [Day01 repo audit](b00_day01_architecture_audit.md) establishes structural source inventory, not successful production use.
- [Day02 BigQuery proof](b00_day02_warehouse_proof.json) verifies actual 2024=355592, 2025=353951 M1 bid-OHLC rows in `aidy-signals.aidy_analytics_test.research_candles` on 2026-10-14. One SELECT-only read; identity counts and zero null OHLC.
- [Day02 R2 proof](b00_day02_r2_proof.json) pending; do not call the entire B00 stage passed without it and owner approval.
- Existing [Day27 spread research](../../docs/day27-historical-spread-j3-contract.md) uses Dec2024/Jan2025 tick quotes; not full 2-year broker executable ticks.
- [Day46 simulator contract](../../docs/day46-paper-simulator-invalidation-contract.md) explicitly says R units only, no position size/account currency.
- [Day37 replay contract](../../docs/day37-frozen-replay-cpcv-contract.md) contains credible anti-leakage research primitives; does not execute arbitrary customer strategies.

## Backlog ranked for sound results (not visual impact)

| Priority | Gap | Evidence / why blocked | First owner stage | Pass requirement |
|---|---|---|---|---|
| P0 | Full historical dataset quality and licensed research use | BigQuery counts verified, not interval integrity or commercial licence | B01 | Source-matched coverage, gap class, legal use matrix, hashes |
| P0 | Source-specific clock/session and HTF completion | HistData fixed EST; Vantage/Broker candle sessions may differ | B01 | Golden bar-clock comparison, DST fixtures and no future HTF leakage |
| P0 | Canonical arbitrary-strategy specification | Replay harness accepts internal decision subjects, not external full rules | B02 | Complete typed spec, rule hash, ambiguity rejection |
| P0 | Named broker profiles + instrument metadata | HistData bid candle not full bid/ask broker fills | B03 | Verified contract/tick/lot/cost/margin assumptions |
| P0 | Realistic chronological execution/position engine | Day46 intentionally R-only and research-scoped | B04 | Independent long/short and gap/SL/TP reference fills |
| P0 | USD cash/equity, ledger and reconciliation | No demonstrated source-faithful 10k portfolio cash simulation | B05 | Every cent, every fill, all costs accounted, immutable ledger |
| P0 | System/source fidelity and parity | Import is unproven; source-code execution would pose risk | B06 | Golden platform parity or UNSUPPORTED |
| P0 | Historical performance statistics/holdout and uncertainty | AIDY's native research metrics are not full account backtests | B07 | Known-answer metrics, prereg, score only if verified |
| P1 | Bid/ask tick coverage vs spread sensitivity | Authentic tick source windows limited; broker spread history incomplete | B01/B03 | Explicit measured coverage + conservative cost sensitivity |
| P1 | Full user-quality report and canonical JSON/CSV/PDF | Research reports are not validated customer audit product | B08 | Every report figure sourced to same ledger/run |
| P1 | Private bulk research console | Strategy Google Sheet is a summary index only | B09 | Dedup, queue, resume, provenance, 100-job synthetic tests |
| P1 | Secure upload and tenant privacy | No validated untrusted-code isolation or tenant boundary | B10 | Tenant separation, quota/retention, no arbitrary privileged execution |
| P2 | Billing, launch, disclosures | Depends on accurate results and commercial licence | B11 | Sandbox billing, owner exemption, legal/licence review |

## Proposed gate disposition
- Day 01 PASS: source inventory.
- Day 02 BigQuery PASS: real historical table accessible.
- Day 02 R2: pending independent read-only object check.
- Day 03: draft gap register complete; stage B00 not yet OWNER ACCEPTED.
- NEXT after B00 acceptance: B01 data/clock/source qualification and B02 StrategySpec schema in parallel.
- Existing AIDY live feed, GoldThinker and brokerage are NOT modified.

## Mandatory decision before B01 begins
A broker-neutral source simulation may be supported, but it must not be described as faithful to the Vantage executable clock/fees unless actual contract/fill evidence is independently qualified. Separate reports for 'generic source simulation' vs 'Vantage-specific execution assumptions'.
