# 2 November 2026 — AIDY independent PO3 27-grid source screen (negative)

**Successful actual CI:** [run 41400258358](https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/41400258358), **7 regression tests passed**, original authenticated AIDY BID/ASK M1 historical replay for 2023, 2024, 2025. Immutable [source-receipt, signal and trade artifact 13120893613](https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/41400258358/artifacts/13120893613). [Draft PR #378](https://github.com/dannythehat/Aidy-Gold-Signals/pull/378) targets existing Gold Hunter PR #371's research branch, NOT main. Original PR #371, PR #374, ORB, G001, G005, Super Signals, brokers and production are unchanged.

## Original source, identity and rights

- Original author **Neo Malesa**, [n30dyn4m1c/po3-indicator](https://github.com/n30dyn4m1c/po3-indicator). [PO3_Scalper.mq5](https://github.com/n30dyn4m1c/po3-indicator/blob/main/PO3_Scalper.mq5), verified Git blob **3fbe3656a445969bf2bc1772fc19c07afbac19a2**. [MIT licence](https://github.com/n30dyn4m1c/po3-indicator/blob/main/LICENSE), Git blob **296949c39905a3e2499bb85938cfea3afed7cb9c**, copyright 2026 Neo Malesa.
- Original EA: **ONE** PO3 integer-price-grid wick-rejection family, not two bots. A track = $9 grid M1; B track = $27 grid M5. Original fixed 0.1 XM micro lots, broker-point-dependent spread/stop floors, two-track interaction, 08–21 broker-server time, Friday 20 flatten, ATR14, wick/body/overshoot, 27-state flip, premium/discount, stop beyond wick, next-grid target.
- **This frozen independent AIDY test is B track ONLY**: 27-grid M5 rejection, 14 ATR, 300-bar state, 30-bar recent flip, 0.25 ATR zone with 0.25-grid cap, 50% wick, 45% maximum body, $9 maximum candle, 1.2 ATR overshoot, 0.35 ATR stop buffer, 1R minimum and next-grid target. Source-derived independent rewrite, **NOT full original EA or broker-native replication**.
- Existing original R2 authenticated spot XAUUSD BIDASK M1 derivatives from CI run 40819738674, decrypted with pinned AIDY snapshot decoder commit **1eb0f678c3158b4a76993ec14ffa7e760d101a0c**. Every original monthly manifest, ZIP identity, original M1 CSV SHA and chronology validated by existing source reader. Complete M5 bars require five actual M1 minutes. Original receipts and hashes in artifact summary.
- [Research script](https://github.com/dannythehat/Aidy-Gold-Signals/blob/gold-hunter-po3-source-screen-20261102/scripts/gold_hunter_po3_27_original_source_screen.py), [7 tests](https://github.com/dannythehat/Aidy-Gold-Signals/blob/gold-hunter-po3-source-screen-20261102/tests/test_gold_hunter_po3_27_original_source_screen.py), [isolated CI workflow](https://github.com/dannythehat/Aidy-Gold-Signals/blob/gold-hunter-po3-source-screen-20261102/.github/workflows/gold-hunter-po3-27-original-source-screen.yml). No earlier strategy retuned.

## Frozen annual 1-oz modelled results, NOT broker P&L

| Source year | Original M1 minutes | Signal tape | Modelled fills | Stressed net USD | PF | Closed-event equity DD | Remove largest winner |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2023 | 308,753 | 435 | 272 | **−229.14** | 0.6313 | −2.637% | −255.18 |
| 2024 | 355,593 | 422 | 324 | **−124.93** | 0.8634 | −1.829% | −150.82 |
| 2025 | 353,952 | 30 | 28 | **−30.70** | 0.6943 | −0.650% | −55.52 |

- Separate hypothetical $10,000 annual resets, **1 physical ounce** per position for comparison, NOT original 0.1 XM micro lot or real standard-lot sizing. Full intratrade marked DD and native stop/gap parity are NOT measured. Displayed DD is **closed-event equity only**, an incomplete risk measure.
- Assumed costs: actual observed source BID/ASK, extra $0.25/oz entry and stop/Friday exit slippage, $0.14/oz roundtrip fee, hypothetical 9% annual notional holding debit; conservative stop-first if stop and target touch within the same M1 minute. Not verified PU Prime terms. 08–21 UTC and Friday 20 UTC are **proxies for unverified broker-server time**; point assumed $0.01. ATR seed is an approximation to MT5 Wilder, not proven identical. True tick order, 9-grid interaction and real margin are absent.
- Exit breakdown: 2023 243 stop / 14 target / 15 Friday flat; 2024 282 / 28 / 14; 2025 24 / 3 / 1. The collapse to 28 modelled fills in 2025, including 37,893 spread-screened M5 observations, demands caution about broker point/spread conventions and regime comparability. It is NOT evidence the original full EA would trade only 28 times.
- Fees plus carry do not fully explain the negative results. Before those charges, with slippage still included: 2023 −$168.06, 2024 −$47.58, 2025 −$25.57.
- Every monthly net, trade, signal and original source receipt is retained in the immutable artifact. **2026 M1 and A track not run.** No untouched OOS remains for the examined 2023–25 years.

## Scientific verdict

**REJECT this frozen 27-grid M5 1-oz costed proxy as a profitable follower candidate:** all three retrospective years negative, PF below 1 in all, and trade frequency unstable. **Do NOT claim the original author's full dual-track EA loses:** original A track, server clock, contract units, native broker fills and MT5 parity remain unverified. Do not retune the examined years and rebrand the family. One PO3 family only. Zero historically qualified bots, zero paper/cent/Hub approvals, zero orders.

## Three more outside leads inspected, not AIDY tested or qualified

1. [olivertwigg/XAU-RSI-Reversal-50-EMA-Bot](https://github.com/olivertwigg/XAU-RSI-Reversal-50-EMA-Bot): shared strategy.py blob **94572f9140568adc58520b07f96aae57bcaf8cb3**, MIT LICENSE **b4f7413ea8c325fea41cbe9968233fa3ad9abfe7**. M5 RSI14 crosses above 63 to short / below 37 to long, daily EMA50 bias, $10 stop, RSI-dependent exit, cooldown/news filter. Source docstring still mentions fixed $8 TP but actual code uses RSI exit: documentation inconsistency. **Related RSI reversion family**, not independently countable against existing RSI_RECLAIM. No AIDY P&L.
2. [omidram/trading-bot](https://github.com/omidram/trading-bot): original src/signals.py blob **742a37fe5076949eda8193d79ebeb031b3058efe**, src/cycle.py **4be29d05c78fd9f3fc2829f9d4d69716a10267d9**, src/backtest.py **af88582108a1bb2399603f54ccfd45702fa09359**, MIT LICENSE **14fac913ccf80234b1848540089a3bbcb6e5283d**. Signal-bar/key-bar with spike/channel/range source mechanics and source-native next-bar entry. **Investigate as one multi-pattern family**, not four bots. Eight-trade README sample is not reliable performance evidence.
3. [eamonnkennedy93-blip/GoldEA](https://github.com/eamonnkennedy93-blip/GoldEA): README blob **26291ed4042bfaad49a2dc16a441c7546d03f7bf** claims sweep/reclaim, session levels, HTF/anchored VWAP and PF1.30 on 183 trades. Original LICENSE endpoint returns **404**. Commercial rights unverified; mechanism overlaps earlier SMC/liquidity sweep family. **Blocked for commercial use, untested in AIDY**. Author PF not our verified result.

## Next

Prefer independent causal mechanisms beyond price-grid/RSI/session variants. Next promising MIT source: omidram market-cycle/key-bar, only after strict family dedup and source-frozen execution. Alternatively authentic CFTC release-as-of or real-yield vintage mechanism if data available without paid vendors. Preserve unchanged ORB/G005/G001. No UI, packaging, merging or broker orders.
