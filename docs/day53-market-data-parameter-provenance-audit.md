# Day 53 — market-data parameter provenance audit

Audit date: 2 September 2026  
Scope: decision-relevant constants and comparison geometry that can cross the HistData/Twelve Data source boundary.

## Finding

The Day 53 reconciliation establishes that HistData and Twelve Data are not interchangeable evidential instruments. HistData is a bid-based `generic_ascii_m1` source with fixed UTC-05 timestamp semantics; Twelve Data uses its own XAU/USD OHLC feed plus the AIDY New York/DST-aware session calendar and vendor/session aggregation contract.

Therefore a rule being fixed, descriptive, deterministic or non-outcome-calibrated is **not sufficient** to establish transferability across feeds. Source-scale and candle-boundary provenance must also be qualified.

Until the items below are resolved, formal accumulation against the Twelve Data decision surface remains unqualified.

## Audited surfaces

| Surface | Existing constant/geometry | Source-boundary risk | Disposition before Twelve Data cohort |
| --- | --- | --- | --- |
| `regime_classifier.py` | H1 ATR(14) `<20 bps`, `20–50 bps`, `>=50 bps` volatility bands | Direct scale dependence. A feed-level OHLC difference can change band labels. | **BLOCKED** pending Twelve Data-specific qualification or deterministic equivalence proof. |
| `analogue_retrieval.py` | H1 ATR numeric scale `40 bps`; M15 realized-vol scale `30 bps`; fixed similarity/coverage thresholds | Direct cross-feed distance distortion if live query features and historical candidate features come from different market-data semantics. | **BLOCKED** for cross-instrument matching. |
| `analogue_retrieval_v2.py` | Carries Day-17 thresholds forward; H1 ATR numeric scale `40 bps`; hard gates on `regime.volatility_band` | Both the hard gate and soft similarity geometry inherit feed-scale dependence. | **BLOCKED** for cross-instrument matching. |
| `historical_cases.py` | Retrospective cases explicitly allow analogue matching and are built from retrospective HistData rows | Candidate provenance distinguishes retrospective/PIT, but not a sufficiently explicit market-data semantic identity for safe cross-feed comparison. | **BLOCKED** until source semantic identity participates in retrieval compatibility. |
| `setup_detector.py` | Many range-position/close-location thresholds; sign tests on bps returns/body; low/high volatility-band setup gates; `m15_range_atr_ratio >= 1.00` | Most position/ratio tests are dimensionless or sign-only, but volatility-band-dependent setups inherit the 20/50 bps issue and all candle-derived values depend on candle/session semantics. | **QUALIFY** under Twelve Data semantics; volatility-dependent setups remain blocked with the regime band. |
| ATR-normalized risk geometry | H1 ATR feeds normalized stop/target/risk basis | Direct scale dependence if used beyond research normalization. | **BLOCKED** from cross-feed reuse unless the consuming surface proves source-qualified semantics. |

## Critical downstream implication

The largest contamination path is not evidence pooling itself. It is **live Twelve Data query features entering similarity or classification logic whose historical comparison geometry was defined against HistData-derived cases**.

The current analogue query contract defaults candidate provenance to `retrospective_history`. Retrospective cases explicitly set `analogue_match_allowed=true`. That means provenance-class separation alone does not prove market-data semantic compatibility.

A cohort reset does not cure this if the same historical cases, thresholds or numeric scales are reused unchanged.

## Required market-data semantic identity

Every decision-time feature packet and every analogue candidate must expose a deterministic market-data semantic identity containing at least:

- provider/source family
- vendor symbol/instrument mapping
- price basis when known
- raw timeframe source
- session calendar version
- timezone/DST policy
- maintenance-gap policy
- candle aggregation/construction version
- current-bucket completeness rule version

Retrieval must fail closed when query and candidate semantic identities differ, unless an ex-ante deterministic normalization/equivalence contract explicitly permits that pair.

A generic provenance class such as `retrospective_history` or `pit_observed` is not a substitute for this identity.

## Qualification options

One of the following must be accepted before the Twelve Data formal cohort can use the affected surface:

1. **Same-instrument history:** rebuild the historical feature/case universe from Twelve Data under the exact accepted session/candle semantics, then version the case universe and retrieval manifest.
2. **Deterministic equivalence proof:** preregister invariants and prove the HistData/Twelve Data transformation preserves each affected classifier/retrieval decision over a sufficiently broad fixed sample. The proof must be recorded before forward outcomes are examined.
3. **Deterministic normalization contract:** define and freeze a source-pair transformation using source-only evidence, then rerun the relevant retrospective cases and all acceptance tests under the transformed geometry. No outcome-tuned correction is permitted.

Absent one of those, affected values must resolve to unavailable/blocked rather than silently comparing unlike instruments.

## Parameter status

### Red — source-scale-sensitive and not yet transferable

- H1 ATR volatility bands: `20 bps` / `50 bps`
- analogue H1 ATR scale: `40 bps`
- analogue V1 M15 realized-vol scale: `30 bps`
- analogue V2 hard volatility-band gate
- any ATR-derived stop/target sizing that is promoted from research normalization to a live decision surface

### Amber — dimensionless/sign based but candle-semantic-sensitive

- recent/session range-position thresholds
- close-location thresholds
- M15 range/ATR ratio threshold
- bps return/body sign checks around zero
- trend-direction features derived from candle returns

These do not need numerical rescaling merely because the absolute quote differs, but they still require the accepted Twelve Data candle/session semantics to be frozen and versioned.

### Green — no market-price scale dependence identified in this audit

- pure identity/version/hash checks
- future/outcome exclusion rules
- append-only evidence permissions
- episode-independence bookkeeping

## Cohort rule

No parameter may be called `transport-only` merely because it is deterministic or because it was not optimized on future returns. For market-data changes, transferability is a separate proposition and carries the affirmative burden of proof defined in the Day 53 formal-forward freeze.

The audit must be rerun whenever the feed adapter, price basis, session calendar, candle construction, feature construction or retrieval geometry changes.
