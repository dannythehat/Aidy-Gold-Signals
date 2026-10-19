# S005 | FINAL HISTORICAL EVIDENCE AUDIT | 19 October 2026

**OWNER DECISION: NOT QUALIFIED / DO NOT ADD / no paper / no real money / no GoldThinker promotion.** Source models show interesting positive Donchian research P&L, but native MT5 broker order execution and virgin out-of-sample validation are NOT certified. Session fails the 2025 positive screening requirement. AIDY's real nine-factor score remains NULL, not a fabricated number.

## Original author and two distinct source-frozen systems

- Author [sbrakni ApexBreakout](https://github.com/sbrakni/MQL5-trading-bot-claude-experiment), original commit `3dab20e20a846edae9ac6fcf56d6b090dbba9f98`; EA blob `db9ee1d2589cd1625c2d9f5b224ea4f1fad14442`; source Python engine and two author-set gold presets source blob SHA verified.
- Donchian H1: previous 24 H1 breakout plus EMA200 trend filter, opposite 12 H1 channel exit, initial stop ATR14 2.5×, nominal 1% risk, no fixed take profit, reversals allowed.
- Session H1: fixed 00–06 UTC range, 06–12 UTC breakout, ATR14 3× stop, no reversal. Original author's Python 21:00 H1 bar-close exits differ from original MQL5 first available tick after 21:00 H1 bar. Both independent systems were tested separately.
- Author original market-optimisation gold source `GC=F` COMEX futures proxy cannot prove spot XAUUSD. AIDY uses source SHA-checked original HistData spot gold BID/ASK history.

## Independently reproduced original Python and actual raw BID/ASK source

| Original strategy | Study | Source Python native economic MODEL | Authentic original raw BID/ASK frozen-original-trades revaluation | 2× extra friction revaluation | 3× extra friction revaluation | Source trades |
|---|---|---:|---:|---:|---:|---:|
| Donchian | Full 2025 | +$1,668.12 | **+$1,426.87** | +$1,282.31 | +$1,137.75 | 121 |
| Donchian | Jan–Sep2026 | +$2,360.70 | **+$2,254.96** | +$2,206.97 | +$2,158.99 | 80 |
| Session | Full 2025 | −$178.27 | **−$574.87** | −$763.81 | −$952.76 | 183 |
| Session | Jan–Sep2026 | +$2,408.28 | **+$2,183.17** | +$2,122.88 | +$2,062.59 | 113 |

All starting hypothetical research accounts $10,000, each period independent. The raw quote-side economic analysis is **NOT** a native MT5 broker account backtest, because original author source Python continuous-ounce position sizes and original entry/exit decisions are held fixed after revaluation. It uses actual original first BUY ASK / SELL BID, correct side actual market exit BID for longs / ASK for shorts, first actual stop-touch quote if earlier, explicit additional assumption $0.10/oz adverse slippage each side and $0.07/oz commission roundtrip. 2× and 3× stresses multiply these extras only. Source broker lot quantisation, margin, financing and changed future risk positions are NOT recalculated. **Do not use revalued frozen-cohort end balance as actually executable account equity.**

2025 original Python profit factors: Don 1.2568 / Session 0.9715. 2026: Don 1.5770 / Session 1.7459. Source-quote frozen-cohort profit factors: Don 1.2151 / 1.5427; Session 0.9112 / 1.6632. Historical mark-to-market DD under actual native original Python: Don −16.1151% / −9.4116%; Session ~−11.83% / −4.55%. No quote-side fully resimulated DD or equity is claimed.

## Real source fidelity, all 497 trade proofs

- 22 monthly immutable original XAUUSD HistData tick BID+ASK original ZIP SHA receipts confirmed, source clock fixed EST to UTC. Exactly 43,065 qualified source M15 candles and 10,725 complete H1. Stable external original raw tick timestamp sorting done on temporary copies without changing originals. FIVE months had source chronology inversions.
- Original author Python engine source and two gold presets actually executed on same authenticated historical spot prices. Independent Donchian long/short channel signal arrays exactly matched original Python computation. Dollar P&L for each of 497 original model trades reconciled.
- AIDY actual historical PriceMath executed one proven source-M15/H1/H4 as-of context on **all 497 source decisions**, 12 mathematics families. This is not all 34 catalogue tools running live, and no retroactive trade filtering performed.
- Actual raw historical **BID for long stops and ASK for short stops** analysed. All 129 original author reported stop exits corroborated; one further original missed stop crossed on Donchian 2025 `0112`, raw 2025-12-07 23:14:41.424 UTC BID 4193.385 below original source initial stop 4193.731960845. Source original later booked a signal exit. The revised fixed-original-cohort dollar figure for that single trade is −$123.632918 versus original Python −$108.511388.
- 454/497 original trade entry source quote spreads strictly exceeded original Python's total $0.45/oz roundtrip allowance. Exit ASK for shorts now separately observed in the authentic 497 real quote-side revaluation.
- **Actual native MQL5 source compiled** using official signed MetaQuotes Windows MetaEditor with **0 errors and 0 warnings**. Exact original author EA blob and both gold preset SHA verified. This is actual MQL5 source compilation, NOT a trading execution run.

## Evidence gates and limitations

| Gate | Audited disposition |
|---|---|
| Published original source, version, presets | VERIFIED |
| Original executable Python research economics | VERIFIED AS PUBLISHER PYTHON MODEL |
| True first original BID/ASK quotes across 497 trades | VERIFIED historical source |
| Author Python stop event / real market-side stop chronology | VERIFIED, ONE MATERIAL SOURCE MODEL DIVERGENCE FOUND |
| Original actual native MQL5 compile | VERIFIED, 0 errors/0 warnings |
| Native MQL5 EA Strategy Tester, exact symbol, MT5 broker history, deals, margin | NOT VERIFIED, DOES NOT FOLLOW FROM COMPILATION |
| Full broker-causal lot sizing/cash equity after revised fills and overnight swaps | NOT VERIFIED |
| Genuinely sealed independent OOS/6+ year historical regimes and forward production | NOT VERIFIED, previously examined 2025/2026 CANNOT be renamed virgin holdout |
| All AIDY toolbox 34 capabilities applied with true historical point-in-time signals | NOT CLAIMED, only relevant real source price maths and specific AIDY gates shown |
| Nine-factor quantitative score /100 | WITHHELD by actual AIDY policy |
| Admission to GoldThinker paper/live/marketing | **NO GO** |

The historical stage itself is **concluded with an adverse admission decision**, not another indefinite 'audit nearly done'. A later separate broker-native original EA trial or forward-history collection could challenge that status if an owner specifically chooses to reopen the system, but no existing underlying result is silently rewritten.

## Immutable reproducibility

- [Original publisher Python on genuine spot source](https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/39158986444)
- [All 497 true AIDY price-math original decisions](https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/39159785515)
- [Original raw tick historical first-stop chronology](https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/39195743159)
- [Real quote-side 497 source trade cohort and 3 risk cost bands, GREEN 26 jobs](https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/39198857672)
- [Native exact author MQL5 Windows MetaEditor source compile, GREEN](https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/39198857678)
- Original source fixed cohort quote revaluation SHA `58f481f3fff10780b464242d910986ea12ed1e411c1141561e1a833a254f064e`; original raw 497 stop experiment SHA `b0907976cba60714f1bb69715d553c2bf458d8ac442824efe6393bc1179ac884`.
- [Notion owner-facing final verdict](https://app.notion.com/p/3fee30f1e54081968930c9e055b2ad61); [complete S005 dossier](https://app.notion.com/p/3fde30f1e5408149803eee21c7e940a1); [master S005 AUDIT and strategy score rows](https://docs.google.com/spreadsheets/d/14EbIPxW5ZeueRX0vz0i6qG7BmlosL04x8-xXl3Hh6N4/edit).

No real broker account trading, copied subscriber orders, payments, deposits, live policy changes or public profits claimed.
