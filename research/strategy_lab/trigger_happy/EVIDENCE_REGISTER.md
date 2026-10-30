# Trigger Happy TH-001 — preserved genuine-source exploratory evidence

Research branch: `research/trigger-happy-v0-1-20261030`  
Last verified: 2026-10-30.  
Status: **RESEARCH FAIL ON FROZEN v0.1 BASELINE; NOT PAPER READY**. 
NO BROKER ORDERS OR LIVE FUNDS INVOLVED.

## Immutable hypothesis and simulation settings
See [STRATEGY_SPEC.md](STRATEGY_SPEC.md). Detector $3 midpoint delta within 1,500ms; three independent 0.01-lot equal-sized legs with TP +$2/+4/+8, SL $4; BID to exit buys, ASK to exit sells; 200ms delayed first-following-quote modeled market entry; max observed spread $0.80; 10s cooldown; 5min expiry. Source: original fixed-EST HistData BID/ASK tick ZIPs, preserved byte-for-byte; separate stable sorted derivative where needed. Model assumes 100 oz per standard lot, no verified broker contract equivalence. Explicit additional model fee sensitivity $10/lot round trip. Original and derived SHA-256 from authentic replay logs.

## Genuine archived source results

| Month | Original quote rows | Triggers | Filled bundles | Closed legs | TP legs | STOP legs | TIME legs | Gross/net with observed bid/ask but $0 added fees (USD) | +hypothetical $10/lot round-trip fee (USD) | Source order inversions | Evidence |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 2025-01 | 5,798,226 | 0 | 0 | 0 | 0 | 0 | 0 | +0.000 | +0.000 | 0 | [run 41009735523](https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/41009735523) |
| 2026-06 | 8,214,093 | 220 | 209 | 627 | 229 | 333 | 65 | -521.649 | -584.349 | 1,402 | [run 41010084732](https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/41010084732) |
| 2026-07 | 7,351,807 | 101 | 97 | 291 | 95 | 151 | 45 | -260.059 | -289.159 | 10,546 | [same run](https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/41010084732) |
| 2026-08 | 5,213,048 | 104 | 98 | 294 | 92 | 158 | 44 | -319.034 | -348.434 | 2,707 | [same run](https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/41010084732) |
| 2026-09 | 6,290,184 | 135 | 127 | 381 | 115 | 199 | 67 | -424.613 | -462.713 | 13,293 | [run 41009890096](https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/41009890096) |
| **Total measured** | **32,867,358** | **560** | **531** | **1,593** | **531** | **841** | **221** | **-1,525.355** | **-1,684.655** | **27,948** | |

The January 2025 case has **zero qualifying triggers**, not a "zero-loss, successful strategy". Do not treat this as profitable. 2026-06 through 2026-09 all lose, so pooled accounting does not conceal negative months. Source quote bid/ask spreads are incorporated, but software models are NOT broker executions; no measured entry ACK or market impact, broker commissions, swaps, order rejection, margin or actual fill parity.

### Original source SHA-256
- 2025-01: `8653c8c14951e5b84315090f7e813ff38325223b59e1ad8c702e4e4fb78af51d`
- 2026-06: `611cd22a1d0af9b15e64804be127500930ffe682e3c8d3eb216e6bc4eab87ad4`
- 2026-07: `8d5d3190186612450411499dae3478a4a96c9dc1f8fe44a40f077aa12c72b4d3`
- 2026-08: `2dea6c1f5ad0ece8d7f34b5838b952f4e65ea556265833ab36a24f0223aa03cc`
- 2026-09: `dbebbaefb5d8b04cf56e35d60682e21a75b9605f9bffaa2e8b2483aa7ff5f3bf`

### Normalized derived timestamp-sorted CSV SHA-256
- 2025-01: `9d8dccbd0975d19bac3ab69694d0d9ce73a62dcf54ca8359d1d21bb3ae9b34` — **UNVERIFIED TRANSCRIPTION**; consult the actual January job rather than trusting this value here.
- 2026-06: `4227bb631fa8b2ed4a88cd0e5555b9263a1e8b1e822d7461a3b59b34ab30a871`
- 2026-07: `710484be28735c8813d2394493255b6f851c8bcddb20d5194c4751ebad118148`
- 2026-08: `2a0535a8ddb023bb9760d33fd27e4582dc61aa10d84101dabcfb5a71cdfd39f1`
- 2026-09: `11a8080deeb48a7d370543b9125d3764e56507907373a62bf98d04bc42b4b140`

## Interpretation and unresolved tests
- The proposed shock does occur in recent gold periods, but the frozen model exhibits negative expectancy under studied assumptions.
- No evidence that any different latency/TP/SL/timeout configuration is profitable. Do not silently optimise away these losses.
- Because January 2025 and four consecutive 2026 months are not a randomized or independent holdout design, these are **exploratory/source-backed simulations**, not a definitive statistical classification of the general market mechanism.
- Distinguish directional continuation measured in source MID from *executable*, latency-delayed ask/bid profitability. Follow-up should study post-shock excursions and times to reach TP/SL, matched same-clock controls, fee/slippage/latency stress and separate untouched holdouts.
- Existing original83 source catalogue and PR #374 are preserved and independent. No automatic paper deployment or commercial promotion.
