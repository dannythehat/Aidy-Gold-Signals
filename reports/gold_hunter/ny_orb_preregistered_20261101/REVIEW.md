# Gold Hunter NY ORB EMA50/5R — frozen improvement falsification, 1 November 2026

**Verdict: RESEARCH / NOT QUALIFIED.** The previously blocked GitHub artifact read succeeded on **retry of the same frozen run**; no parameter changes or 2024-based tuning. [GitHub Actions run #41187464561, attempt 2](https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/41187464561), **SUCCESS**, 11 regression tests PASS. Machine-readable artifact **#13072932115**, `gold-hunter-ny-orb-2022-2026-fixed-hypotheses-complete-evidence`, contains 72 complete scenario ledgers and `summary.json`, schema `aidy.dev_ny_orb_hypothesis_controls_2022_2026.v1`, checksum `e794060b15f9a56435a87ee7ad7ce3cbc7e392e3ef46ab3f08963312fb8f71a6`. The earlier CI attempt failed at GitHub artifact download, not strategy performance.

**Do not count 72 independent tests or bots.** There are **two source-repaired clock interpretations** × **six predeclared variants** × **five distinct chronological quote periods** (2022, 2023, 2024, 2025, Jan–Sep 2026), plus **one overlapping continuous Jan2025–Sep2026 account**. These are 12 related hypotheses in one original-source-inspired family, not 12 independent winning strategies. All periods have been examined; no untouched OOS remains in this suite.

## New York-local DST repaired clock: complete marked net USD on independent $10k annual accounts

| Frozen variant | 2022 | 2023 | 2024 | 2025 | Jan–Sep 2026 | 2025–Sep2026 continuous | Worst five-period H1 DD |
|---|---:|---:|---:|---:|---:|---:|---:|
| BASE_2PCT | -250.27 | +1,613.85 | -2,417.36 | +4,139.06 | +4,151.33 | +9,832.13 | -43.752% |
| RISK_HALF_PCT | +44.75 | +399.97 | -564.39 | +709.28 | +830.89 | +1,481.61 | -12.198% |
| BREAK_BUFFER_025 | +93.86 | +3,425.06 | -1,417.91 | +2,280.54 | +3,729.55 | +6,811.07 | -28.151% |
| RANGE_WIDTH_15 | -520.57 | +1,858.90 | -1,967.41 | +5,102.76 | +4,480.75 | +12,158.42 | -40.161% |
| EMA_STRENGTH_10 | -1,180.73 | +2,167.90 | -1,966.51 | +4,003.36 | +3,698.57 | +9,281.65 | -40.324% |
| BUFFER_WIDTH_LOW | +11.80 | +611.77 | -154.92 | +464.22 | +760.23 | +1,194.55 | -6.433% |

**All six variants lose in 2024** under the New York-local DST clock. The largest original 2024 DD -43.752% shrinks to -12.198% at 0.5% risk alone and -6.294% with buffer+width+0.5% risk, but neither is profitable in 2024. Only `RISK_HALF_PCT` and `BUFFER_WIDTH_LOW` meet the script's deliberately *provisional* mechanical screen (4/5 positive periods and worst H1 DD no worse than 20%). This **does not** mean scientific profitability or approval.

## Fixed UTC repaired clock: complete marked net USD

| Frozen variant | 2022 | 2023 | 2024 | 2025 | Jan–Sep 2026 | 2025–Sep2026 continuous | Worst five-period H1 DD |
|---|---:|---:|---:|---:|---:|---:|---:|
| BASE_2PCT | -1,753.83 | +1,733.48 | -2,342.92 | +5,549.92 | +4,413.47 | +12,246.27 | -43.517% |
| RISK_HALF_PCT | -380.56 | +459.06 | -566.90 | +995.39 | +960.36 | +1,841.14 | -12.233% |
| BREAK_BUFFER_025 | -2,783.88 | +2,406.35 | -1,244.64 | -444.89 | +2,713.94 | +2,162.24 | -32.435% |
| RANGE_WIDTH_15 | -2,111.22 | +2,008.89 | -1,807.28 | +7,623.33 | +5,351.15 | +16,916.86 | -39.827% |
| EMA_STRENGTH_10 | -1,602.07 | +2,553.13 | -1,819.00 | +6,083.46 | +4,272.51 | +13,038.18 | -39.936% |
| BUFFER_WIDTH_LOW | -570.51 | +377.79 | -52.10 | +5.47 | +638.87 | +644.34 | -7.447% |

**All six fixed-clock variants lose in 2022 and 2024**, except none. The fixed-clock `BUFFER_WIDTH_LOW` 2025 gain of +$5.47 is economically immaterial and is not a reliable edge. Neither clock survives all five disjoint periods profitably.

## The apparently safer New York combined filter: why it is still unqualified

`BUFFER_WIDTH_LOW` freezes 0.25 ATR breakout clearance + 1.5 ATR minimum range width + 0.5% equity risk. It is a **parameter/filter variant of the same NY ORB family**. Actual closed trades and P&L:

| Historical source period | Closed trades | Marked net | PF (closed) | Max H1 DD |
|---|---:|---:|---:|---:|
| 2022 | 27 | +$11.80 | 1.010 | -6.433% |
| 2023 | 14 | +$611.77 | 2.193 | -2.121% |
| 2024 | 22 | -$154.92 | 0.827 | -6.294% |
| 2025 | 20 | +$464.22 | 1.724 | -2.843% |
| Jan–Sep 2026 | 14 | +$760.23 | 3.253 | -2.080% |
| **One continuous Jan2025–Sep2026 account** | **34 closed + one open** | **+$1,194.55 marked** | **2.186 (closed)** | **-2.843%** |

The continuous account is *not* the sum of two separately reset annual accounts. It has +$1,198.67 realized on closed trades and an open position marked to the last source quote. The 2026-only account similarly has +$764.35 realized vs +$760.23 marked. The overlapping continuous period must not be counted as a sixth independent success. The 2022 +$11.80 result is fragile: removing its single largest closed winner of +$251.22 leaves approximately **-$239.42**. 2024 is unprofitable with 22 trades and PF below 1. No evidence for the owner's aspirational 10% *net monthly* objective.

## Source and verification

- 2022 original R2 tick month receipts, all 12 months, **5,859 complete H1** (December 2021 warmup unavailable); 2023 **5,020** completed H1 (early source warmup absent), 2024 **5,878**, 2025 **5,866**. Authenticated original BID/ASK source manifests are embedded in the artifact; original 2023/24/25 hourly SHA256: `3760de058f1fbf99e3b3257d8146ee05ff552a8a5f6575084cbeadcc41bbe17e`, `5a7f8ed1b94dd87bbb25786adc8e2920d6308b9070a3333856e241ee45139aba`, `fb989d6538a788fb63a776a91b6edbf2214d317d32a8323efb605ceaff75e5df`. Jan–Sep2026 original tick-derived H1 SHA256 `fffff26b3560ac0cf9d41bd1f4139f782e9482fe3f8105a7db7d4559e3aed265`. **No original October 2026 M1 quote source exists in the evidence**.
- All previously published 2023/24/25/Jan–Sep2026 baseline P&L for both clocks were independently asserted **unchanged** by the new script, and 2022 New York original baseline -$250.27 independently reproduced.
- The original article's literal clock is contradictory and gives **zero signals by construction**. Both repaired interpretations, 120 H1 timeout, 5R/EMA50/ATR and filters are AIDY adaptations, **not author-native GC=F futures parity**.
- Execution is original quote **BID/ASK-derived**, $0.25/oz assumed slippage *per side*, $0.14/oz roundtrip commission and **hypothetical 9% annual carry**, NOT observed PU Prime swap, contract, lot/margin, or broker-native stops. Intrahour price-extreme/ASK alignment is approximate, and stop-first H1 gap sequencing is conservative but not tick-native.
- Independently inspected the downloaded CI ZIP: **73 entries = 72 scenario JSON files + summary**, all 72 reported closed-trade counts reconcile to their individual ledgers, all realized P&L sums reconcile within 2 cents, and non-open cases have no material marked/realized discrepancy. The source CI itself passed **11 tests** and saved the artifact.
- Research-only. No code retuning, no 2024 fitting, no paper/demo/cent/live orders, no merge, no GoldThinker performance claims, no bot qualification.

## Decision and next independent work

**REJECT the original 2%-risk ORB as a follower-ready system; INVESTIGATE the 0.5%-risk/filter family only as a drawdown-control experiment, not a profitable independent bot.** The 2024 negative regime remains unresolved, and the 2022 low-profit year is highly winner-concentrated. Do **not** run another filter grid over the same years or call this an untouched holdout. Prefer a genuinely different source-led mechanism, an independent unseen chronological quote period when legally available, or a properly specified broker-native cost/parity experiment with owner approval before any forward stage.
