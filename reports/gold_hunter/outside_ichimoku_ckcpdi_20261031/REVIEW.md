# 31 October 2026 — NEW independent outside-source XAUUSD hunt: Ichimoku CK/CP/DI M30

**Decision: REJECT THIS FROZEN CAUSAL ADAPTATION AS A FOLLOWER-CANDIDATE; NATIVE AUTHOR EA UNQUALIFIED, NOT PROVEN TO LOSE.** No paper, no cent, no website, no orders. Do not tune this observed 2023–25 history and claim untouched OOS.

## Original external source / licence / dedup

- Author: Neo Malesa (`n30dyn4m1c`), original public [MIT Ichimoku CK/CP/DI MQL5 repo](https://github.com/n30dyn4m1c/ichimoku-chikou-kijun-crossover-ea).
- Executable source: `profitable-gold-m30.mq5` v1.78; Git **blob** SHA `7b9837c47a80928d21b6bee3e7b813d805c3e7e0`, verified in CI by `git hash-object`. MIT `LICENSE` blob `7874e8fc5b21f333b241466dbf0f0abc308d553b`. Public repository README is **not** performance evidence.
- Mechanic: Chikou span / 26-back Kijun cross → Chikou confirms beyond 26-back candle high/low → DI14 directional agreement → entry in original XM *server-clock* 08:00–11:00 window → exit on third opposite DI cross or any fresh CK cross. No source hard stop, no TP, fixed `Lots=0.10`, default Ichimoku 9/26/52. Several files in the original repo share this same CK/CP/DI mechanism: **one family**, not multiple independent bots. Distinct mechanism from old Donchian, Asian ORB, SMC FVG and prior G005 4H zones; **original83 full-rule overlap not yet exhaustively checked**, so independent-family count is provisional.
- AIDY **source-inspired independent interpretation**, NOT native MT5 tester parity. Source Chikou buffer displacement and `iADX` indicator seeding need original MQL5/MT5 side-by-side proof. Source clock is XM server, while this model fixes **08:00–11:00 UTC** as an explicit unverified proxy. Original source `0.10 lot` is **assumed 10oz** based on an unverified 100oz/lot standard contract. Missing native stop/gap/margin calls and actual PU Prime symbol/cent/standard lot specification. No source-funded swap schedule available.
- Inputs: authentic source-receipted **2023/2024/2025 AIDY original spot M1 BID+ASK**, 1,018,298 M1 rows, 33,718 complete M30 bars; incomplete 30min buckets dropped. Each year a separate $10,000 reference account with 88-bar initial warmup, no hindsight parameters, no synthetic quotes, no GC futures proxy. Year-end **open positions marked, not closed**.
- CI: [successful immutable 2023–25 source-attested run #41176316180](https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/41176316180), **12 tests passed**, original EA and licence hash verified, encrypted authenticated AIDY quotes reused read-only, trade and monthly ledgers published as [artifact #13032817530](https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/41176316180/artifacts/13032817530). Report SHA256 (canonical JSON): `1f68430301b09be7221c29cc138e19cd1d69b452751fe9588e72f309f53b4170`.
- Initial CI had a pandas mixed-row `isfinite` test failure; corrected on a **separate branch derived from PR #371** specifically to avoid another irrelevant G005/other original-source PR workflow sweep. All final 12 tests and full authentic quote execution passed. Prior original evidence untouched.

## Results — separate $10k annual accounts, USD MARKED net, all modelled costs as specified

| Year | Closed trades | Base (.05 USD/oz/side slip, no fee/funding) | Stress (.25 USD/oz/side + .14 USD/oz RT fee, **NO funding**) | Stress plus **HYPOTHETICAL 9% simple annual carry** |
|---|---:|---:|---:|---:|
| 2023 | 189 | +441.46 | **−582.54** | **−1,420.55** |
| 2024 | 199 | +1,745.04 | +667.04 | **−289.79** |
| 2025 | 189 | +1,554.16 | +530.16 | **−797.07** |

**All 3 years are already-examined retrospective development, not untouched OOS.** The 9% financing scenario is illustrative and is NOT a PU Prime or any actual broker quote. We intentionally report both **no-financing** and **with-financing** stress rather than silently treating assumed swap as actual. Real market BID/ASK already included; the additional execution charges are modelled.

| Year | No-funding stress PF | No-funding max M30-marked DD | With 9% carry PF | With 9% carry max M30-marked DD | With 9% carry closed-cash P&L |
|---|---:|---:|---:|---:|---:|
| 2023 | 0.932 | −25.844% | 0.847 | −29.623% | −1,471.33 |
| 2024 | 1.052 | −18.142% | 0.966 | −20.977% | −380.90 |
| 2025 | 1.017 | −38.184% | 0.952 | −42.934% | −989.73 |

All years end with one unclosed position, and the marked figure includes its contemporaneous BID/ASK liquidation value and accrued hypothetical funding. The 9%-scenario positive monthly closed-P&L counts are **5/12, 6/12 and 7/12** in 2023, 2024 and 2025 respectively; worst months are June 2023 **−$1,614.59**, February 2024 **−$1,085.65** and November 2025 **−$1,904.78**.

**Concentration check:** removing the single largest closed winner from the no-funding stressed cash P&L makes all three years negative: 2023 **−$1,483.80**, 2024 **−$230.31**, 2025 **−$1,451.55**. Thus even the two positive no-funding marked years do not offer strong trade-independent evidence. This is a retrospective fixed-size first-order concentration test, not a strategy rerun.

## Non-qualification and source-vs-AIDY parity gaps

1. Original MQL5 native tester, indicator Chikou `CopyBuffer(4, Kijun+1)` shift, broker-server 08–11 clock/DST and original `iADX` seeds not independently matched; source's 0.10 lot may differ from assumed 10oz. **Do not call this source-faithful broker execution.**
2. **No protective stop in original**. M30 close-to-close drawdown can materially understate intrabar or gap/stop-out exposure. No leverage/margin-call engine; source cannot be follower-qualified with such gaps.
3. Observed spot BID+ASK are authentic AIDY quotes, not PU Prime bid/ask/fills or swaps; 9% annual simple financing is hypothetical and may differ drastically from overnight broker swap schedules, triple days, and account type.
4. High turnover 577 closed trades across 3 years; no evidence of robust after-cost edge, no untouched holdout or native EA parity, weak PF and extreme loss months. This is **not** an affiliate-commercial candidate.
5. Existing original83 dedup and G001/G005/S005 results remain untouched. No retuning of G001/G005, no new independent winner count, no orders, no VPS writes, no GoldThinker promotion.

## Other new outside-source leads inspected in same hunt

- **PO3 mathematical price-grid rejection, [MIT original](https://github.com/n30dyn4m1c/po3-indicator)**: `PO3_Scalper.mq5` blob `3fbe3656a445969bf2bc1772fc19c07afbac19a2`, `PO3_Core.mqh` blob `0b08624f253c24fa994c2147a89acb9082a473a3`, MIT LICENSE blob `296949c39905a3e2499bb85938cfea3afed7cb9c`. Rejection of fixed 9-grid M1 and 27-grid M5 nested price levels with wick/body and ATR gates, server-time entry, source 0.10 lot, stop past wick. **ONE family** (two grids not two bots), untested. M1 quote replay is feasible; first compare against SMC/zone rejection overlap and validate `GOLD` symbol, broker digits, original clock and 0.1-lot risk. No edge claim.
- **RobertN1D order-flow / DOM / tick velocity ranker, [public source lead](https://github.com/RobertN1D/XAUUSD-GOLD-SCALPER-MT5-EA-FREE-SOURCE-CODE)**: README blob `a78d08e10eb076d460b48937d6e1bd4a21667bf4`, but the expected `GOLD-HFT-SCALPER.mq5` root path and `LICENSE` were **NOT FOUND** by direct GitHub file lookup. True historical broker DOM/tick velocity and first-release event data unavailable from the verified AIDY M1 OHLC quotes. **SOURCE / DATA BLOCKED**, no backtest, no licence assumption, no edge claim.
- **Zovrax Volume Profile indicator, [MIT source lead](https://github.com/Zovrax/MT5-volume-profile-indicator)**: README blob `662ee65ec0163203634f54c28dd5a87891daa504`, LICENSE blob `60e0bed002b325e9547f3dbb8274e2cb5cd3bda8`. Indicator/desktop volume-profile idea, **NOT a specified executable trading strategy**; source `VolumeProfile.mq5` at repo root not found. Genuine spot traded-volume/DOM absent in AIDY M1 quotes. **NO TEST**, not an independent bot.

**Next best research step:** audit the PO3 EA's exact `Rejects`, level-state and M1/M5 source execution rules, and test a frozen causal 2023–25 AIDY quote replay only if broker symbol/point and original server clock are explicitly labelled. Also obtain PU Prime real cent and standard contract/commission/swap/stop dimensions for any eventual follower-qualification. Do not re-run exhausted G005/G001.
