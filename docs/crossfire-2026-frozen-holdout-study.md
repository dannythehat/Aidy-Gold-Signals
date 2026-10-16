# CROSSFIRE S010 | PRE-REGISTERED JAN–SEP 2026 REAL GOLD STUDY

Owner 16 October 2026: 2021 historical gold was COVID-era, so test the genuinely later Jan–Sep 2026 data before a possible isolated USD10k MT5 PAPER trial. The 2021/2025 source studies remain intact. Freeze exactly THREE configurations and no tuning once 2026 is inspected.

## Source and exact boundary
- First 9 COMPLETE UTC months of 2026: Jan 1 00:00 through October 1 00:00 exclusive.
- 10 private Cloudflare R2 original HistData XAUUSD BID/ASK EST-fixed archives: Dec2025 + Jan–Sep2026. October 2026 has NOT been archived and cannot be invented. Records source ZIP/PAYLOAD SHA, raw ticks, source-order inversion count and UTC H1 derived snapshot fingerprints. Original raw ZIPs remain byte-unchanged, source-order inversions repaired only in separately derived UTC minute/hour views.
- All nine 2026 months require real complete source H1 bars. HistData source BID/ASK does NOT establish executable historical Vantage pricing.

## Frozen strategies — no search or parameters changed after results
1. ORIGINAL: MA12/MA34 positive crossover, RSI14 below 70 to buy, corresponding qualifying negative crossover RSI above 30 to exit. Long only, 3.28x leverage, signal on CLOSED H1; trade at following H1 open. No stop.
2. ATR3_INITIAL_STOP: Exactly ORIGINAL plus one FIXED initial stop at entry BID minus 3 times ATR(14) measured over the previous 14 completed H1 bars. On H1 BID low crossing stop, model stop or worse opened-gap BID fill and adverse slip/cost; no trailing, no ATR parameter grid.
3. RISING_SMA200_FILTER: Original entries only when previous closed H1 close above previous H1 SMA200 AND SMA200 has risen compared with 24 completed H1 bars earlier. Same original exits. No optimisation.

Earlier conversational 2021/2025 tweak figures are preliminary and not guaranteed reproducible under these explicit frozen definitions; 2026 is independent current research not a claim that earlier variants were exact-code replicated.

## Execution and required honesty
All 3 have frozen base per-oz spread USD0.30, adverse slip USD0.05 each side, round trip fee USD0.07, leverage 3.28x. Stress USD0.80 spread, USD0.25 adverse slip per side, USD0.14 round trip fee. Real HistData source hourly ASK/open spread distribution recorded separately. No historically attested Vantage ASK, swaps, financing, margin call/forced liquidation in reported model P&L. No MT5 connection, broker order, subscription or real/live trading.

## Pre-registered 2026 paper-candidate screen
The ATR3 version qualifies only for CONDITIONAL PAPER TRIAL REVIEW if base NET P&L >USD0, max marked drawdown better than -35%, at least 30 completed trades, AND stressed cost case net P&L >USD0. This is NOT automatic approval. Actual broker swap, real quotes, hard stopout, account isolation and owner GO gates remain. If loss, report loss and don't silently optimise.

Source output includes 10 individual original source receipts, 9 monthly model portfolios, original vs two variants and 3 stress scenarios, all underlying source-derived BID/ASK H1 CSV and 3 trade-CSV ledgers, full JSON evidence SHA and truthfully classified decision.

Workflow: https://github.com/dannythehat/Aidy-Gold-Signals/actions/workflows/strategy-lab-crossfire-2026-frozen-holdout.yml
