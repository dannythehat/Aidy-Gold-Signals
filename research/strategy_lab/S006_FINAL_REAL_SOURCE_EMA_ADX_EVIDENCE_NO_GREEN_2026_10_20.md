# S006 | EMA Crossover plus ADX, original publisher 2025 / Jan–Sep2026 gold audit

**Date:** 20 October 2026. **Owner GREEN shortlist:** **NO.** **Source research screening:** **NOT RECOMMENDED FOR GREEN**. **AIDY scientific nine-factor verdict:** `ORANGE_INVESTIGATE`, score `NULL / 100`. **GoldThinker / paper / live admission:** **NO**.

## Critical source facts

- Original publisher upstream [sbrakni/MQL5-trading-bot-claude-experiment](https://github.com/sbrakni/MQL5-trading-bot-claude-experiment), frozen commit `3dab20e20a846edae9ac6fcf56d6b090dbba9f98`.
- The source Python research family `research/strategies.py:ema_trend` actually implements EMA fast/slow crossovers, optionally gated by Wilder ADX(14). This is NOT one of the two native strategies coded into the original `MQL5/Experts/ApexBreakout.mq5` EA, which only implements DONCHIAN and SESSION. **There is no original published XAUUSD EMA+ADX EA preset.**
- Author's **highest-placed published gold EMA crossover research** was EMA9 / EMA120 with `adx_min=0`, i.e. **ADX DISABLED**. Calling its profits the performance of an ADX-confirmed trading system would be materially wrong.
- Two *predeclared original publisher optimisation-grid* source variants with the **same EMA9/EMA120 and engine settings** have genuine ADX thresholds **20 and 25**. They are distinct candidates and have not been fitted to the newly replayed 2025/2026 source data.
- Frozen original code blobs: `strategies.py` = `9abe69680df34064923e01236cbf9b77d486c682`; `engine.py` = `41f1b5740314487ed6ea35b3307daf689d8abb6f`; `optimize.py` = `41dd3dc2ca42c4ba5ec58727ddf4676e68144b96`; published `grid_all.csv` = `651ecbaf2a4bf0288c37ec3216192c8d90a5f8b1`.

## Full trading instructions as actually sourced

1. Read each fully completed XAUUSD H1 candle close. Compute exponential moving averages with periods **9** and **120**.
2. **BUY crossover:** fast EMA(9) above slow EMA(120) now, at or below slow on previous H1 signal bar. **SELL crossover:** EMA(9) below EMA(120), previously at or above slow.
3. For actual ADX variants only, require publisher's Wilder **ADX(14) ≥20** or **≥25** on this closed H1 candle. For the unfiltered comparator, ADX0 means the ADX condition is not evaluated.
4. Original author source Python research engine enters at the next H1 OPEN at a synthetic bid-proxy fill, with nominal **1% of equity stop-distance risk**, original continuous-ounce notional leverage capped at 20×.
5. Protective initial stop **Wilder ATR14 ×2.0** from the research entry. Chandelier ATR trail **3.5×ATR** is updated on completed H1 candles; no preset profit target. On opposite crossover, source engine can close and reverse at the next hourly open. No independent signal-exit flag.
6. The original author model charges one synthetic **$0.45/oz all-in roundtrip cost**, which does not replicate actual bid/ask quote-side stop fills, spread gate, real MT5 lot rounding, broker execution fees or financing.

## Real-source independent replay protocol

- **History:** same 22 independently hash-checked original HistData XAUUSD monthly raw tick sources (Dec2024 source warm-up; full calendar 2025; Jan–Sep 2026), 10,725 fully completed H1 candles from genuine underlying BID/ASK data.
- **Original author Python `strategies.py` and `engine.py` executed directly** on real spot price histories. Independent original EMA/ADX Boolean signal arrays match on every H1 history row.
- **Six distinct research model experiments:** ADX0, ADX20 and ADX25 with independent hypothetical $10,000 starting cash for each of two periods. Monthly and full trade ledgers retained.
- Original author's historical Yahoo COMEX `GC=F` futures research was a **proxy**, not the original BID/ASK spot quote source used in this independent replay. The historical discovery/leaderboard and these now-reviewed periods must NOT be called virgin holdouts.
- Source run 39368697470 (all green), evidence [original author Python six-case trade, month and summary archive](https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/39368697470/artifacts/12240282329).
- Canonical AIDY source math run 39369073134 (all three CI jobs green), evidence [full 341 actual canonical price experts and nine-factor gate](https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/39369073134/artifacts/12240312561).
- Merged implementation, tests and reproducible action [PR #362](https://github.com/dannythehat/Aidy-Gold-Signals/pull/362), squash commit `763b02f5a91c95502ab7f790b2278c9ad8a27c3b`.

## Six original-author Python research model results

Each number is a separate research account, **not** native MT5 or cash profits.

| Original fixed source variant | Full 2025 source model | Jan–Sep2026 source model | Risk evidence |
|---|---:|---:|---|
| EMA9/120 ADX0 OFF, research comparator | +$780.81 · 103 trades · PF1.1289 | +$1,426.79 · 80 trades · PF1.3126 | 2025 marked DD −16.02%, 2026 −13.23%; **NO ADX CONDITION** |
| EMA9/120 ADX14≥20, actual S006 ADX research candidate | +$366.75 · 53 trades · PF1.1124 | +$176.53 · 43 trades · PF1.0666 | 2025 DD −15.28%, 2026 −14.86%; thin edge relative to mark-to-market drawdown |
| EMA9/120 ADX14≥25, more selective research candidate | −$774.91 · 36 trades · PF0.6615 | −$26.23 · 26 trades · PF0.9836 | 2025 DD −13.78%, 2026 −12.43%; both original-costed bands lose |

### Economic stress and genuinely observed historic entry spreads

| Source variant | 2025 median real entry spread/oz | 2026 median real entry spread/oz | Strictly above source author's $0.45/oz full roundtrip allowance |
|---|---:|---:|---|
| ADX0 OFF | $0.59 | $0.72 | 93/103 in 2025; 73/80 in 2026 |
| ADX≥20 | $0.61 | $0.69 | 47/53; 38/43 |
| ADX≥25 | $0.578 | $0.665 | 32/36; 23/26 |

**Frozen original-position cohort only**, keeping all author entries, exits and continuous-ounce sizes unchanged: a **$2.00/oz** roundtrip hypothetical full cost (vs original $0.45) reduces the ADX≥20 historical model to **−$69.80** for 2025 and **+$7.48** for Jan–Sep2026. ADX≥25 remains negative both years. **$2 vs $0.45 is about 4.44×, NOT merely doubled.** This is a cost sensitivity, not an executable replay at the new cost, since actual orders, stops, equity/sizing and market friction would differ.

## Real AIDY engine used, not just its existence

- Canonical `aidy.gold_toolbox_registry.build_gold_toolbox_manifest` called and self-verified. The current actual catalogue contains **34 known capabilities**, **not all historically wired** or executed.
- Canonical `aidy.gold_price_expert_math.build_price_expert_math_packet` and `verify_price_expert_math_packet` executed with genuine completed historical M15/H1/H4 candles at the entry instant for **every single 341 original-author Python trade** (103 + 80 + 53 + 43 + 36 + 26), using source-specific retrospective evidence and never modifying trades or falsely labelling it live PIT. Exact all-trade output SHA256 `44c24df414952e3bc016cb0e9459231688e64bb49ff0a2ae3835888047e80c9b`.
- Actual `aidy.strategy_lab_evidence_rating.rate_strategy_evidence` executed with the original owner **nine weighted factors**. It returned `ORANGE_INVESTIGATE`, `score_out_of_100: null`, `historical_profitability_qualified: false`, `automatically_authorised_for_live_trading: false`. The actual code refused to award an artificial score.
- Price mathematics is a source context/explanation layer, NOT a change to the publisher's EMA crossover logic. Other macro/news/rates expert modules require causal archived historical inputs and cannot be fabricated.

## Final disposition and record

**S006 is NOT qualified and NOT recommended for an owner GREEN shortlist now.** The original source leader is not ADX-enabled; actual ADX20 source variants have modest gains relative to approximately 15% marked drawdowns and cost sensitivity, while ADX25 lost in both tested windows. There is no original native EMA+ADX EA implementation; original source-Python model historic profits are not native broker execution.

**Current candidate screen: RED / NOT SELECTED**, retaining separate actual AIDY scientific `ORANGE_INVESTIGATE` because independent native broker execution and untouched holdout remain unavailable. The red shortlist *recommendation* is an owner portfolio-selection assessment, not a spurious AIDY /100 numerical verdict. Do not add S006 to GREEN, don't package a product brand, don't paper/live trade it, and don't relabel the better-looking **ADX0 OFF** research as ADX.

**Green shortlist tally remains 1 of 9**, The Channel Hunter (S005) only. Original source unchanged.

[Notion audit and detailed test protocol](https://app.notion.com/p/3ffe30f1e54081f7b38cda3538fe320b) • [AIDY strategy master scorecard](https://docs.google.com/spreadsheets/d/14EbIPxW5ZeueRX0vz0i6qG7BmlosL04x8-xXl3Hh6N4/edit)

Research author 20 October 2026. Unverified questions and OOS remain eligible for future separate investigation but cannot be hidden by a green label.
