# Day 24 — Independent-Episode Historical Retrieval

## Role

Day 24 is a correctness hardening of historical analogue memory after the accepted Day 23 J1 baseline. It is not strategy tuning and it is not the elastic recovery branch, because the pre-registered Day 23 stop-work threshold did not fire.

Authoritative base: `9f0803040e49d58fe082a7de863d8647f7470b84`.

Frozen comparison input:

- Day 23 experiment: `day23-j1-j16-baseline-20260821-v1`
- exact 1,000-query manifest digest: `119d8c2a1a11cba44d8195fff81be640f7b9c084d0d7b8c28a61dedfa64e5ac5`
- exact historical-case snapshot digest: `bd3c81b54ec05b2150e6e6ecbdffbc3c1e4f943c6a23c9a8ee4977c1dc1c3a88`
- Day 17 numerical thresholds remain similarity `0.72`, component coverage `0.65`
- Day 18 comparison cap remains `max_results=200`

No frozen query may be removed, replaced, rebuilt, or modified during acceptance.

## Versioning

Day 24 does not silently mutate accepted Day 17/18 semantics. It creates explicit new versions:

- retrieval: `aidy_historical_analogue_retrieval_v2_independent_episodes`
- similarity: `aidy_gold_similarity_features_v2_decorrelated`
- evidence grade: `aidy_evidence_grade_v2_effective_independent_n`

The accepted v1 implementation remains reproducible as the Day 23 baseline.

## Purge and embargo

A candidate must first pass all accepted Day 17 PIT eligibility checks and have an identifiable complete 240-minute outcome window. Day 24 then applies a fixed 240-minute embargo before the query. A historical outcome window ending inside that embargo is excluded even when its outcome is technically available.

The embargo is fixed before measurement and is not tuned against outcomes or coverage.

## Hard structural gate

Before soft similarity, candidates must match known query structure on:

1. `regime.trend_structure`
2. `regime.volatility_band`
3. `market_structure_epoch` when the query carries that field

Unknown query trend/volatility fails closed. Unknown candidate trend/volatility is excluded. A known epoch mismatch is excluded.

Architecture V2 creates the canonical `market_structure_epoch` field on Day 25, so the exact frozen Day 23 queries cannot yet contain it. Day 24 does not invent or retrospectively backfill the field. Retrieval instead surfaces `market_structure_epoch_unavailable_pre_day25` explicitly. Once Day 25 supplies the query epoch, the installed gate becomes hard automatically.

## Low-dimensional decorrelated similarity

After hard gating, v2 uses only five soft components: session, event timing, H1 ATR, M15 range position, and setup-ID overlap. Trend and volatility are gates rather than repeated soft votes. Triple-timeframe direction, duplicate volatility/location votes and the currently uninformative quote-spread state are deliberately excluded from v2 similarity.

No learned embeddings, metric learning or dynamic time warping are permitted. Day 17 numerical threshold values are carried forward unchanged and are not re-optimized during Day 24.

## Episode-level deduplication

After gating and fixed similarity/coverage thresholds, the top `max_results` candidates form the pre-dedup raw selection. Complete 240-minute outcome windows are clustered into connected components of overlapping windows, matching the Day 23 episode definition.

Each episode contributes at most one returned analogue. Representative selection is deterministic: highest v2 similarity, then component coverage, then `case_id`.

Day 24 reports candidate raw N, eligible N, hard-gate pass N, sufficient pre-dedup N, pre-dedup raw N, Day-23-compatible Kish effective N and `effective_n/raw_n`, distinct independent episodes, grading effective N, temporal span/months, `NO_COMPARABLE_CASE`, exclusions and all gate relaxations.

## Evidence grading

Day 18 grade threshold magnitudes are retained, but sample-size rules are explicitly evaluated against effective independent episode N rather than raw match count. Returned matches are one representative per independent episode.

Outcome values remain forbidden from dataset-grade assignment. Already-knowable future outcome-window timestamps may be used only for purge, embargo and episode-independence accounting. A low effective N remains `insufficient` even if raw pre-dedup N is large.

## Acceptance interpretation

Because Day 23 stop-work did not fire, the emergency recovery thresholds (`median effective_n/raw_n >= 0.70` and median distinct episodes `>=10`) are not Day 24 pass/fail performance targets. Day 24 passes on correctness if the exact frozen comparison is reproduced and v2 demonstrably enforces the architecture above without leakage, hidden relaxation or non-determinism.

The measured Day 24 coverage and independent-N result must be reported exactly, including an adverse result. No threshold or gate may be weakened to improve `NO_COMPARABLE_CASE`, analogue count, evidence grade, signal count or trade frequency.
