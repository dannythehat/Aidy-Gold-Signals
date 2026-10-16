# CROSSFIRE S010 — UNCHANGED ORIGINAL: full 2021 down-year source test

Owner explicitly requested proper CROSSFIRE paper-readiness qualification, not another requirements recital. This PR **executes original S010 rules on real original 2021 XAUUSD HistData archived BID/ASK ticks**. It is the second-year test; original 2025 result remains frozen.

## Historical source

Read-only original private Cloudflare R2 tick ZIP archive, `aidy-memory-test/strategy-lab/histdata/xauusd/ticks/YYYYMM/HISTDATA_COM_ASCII_XAUUSD_T_YYYYMM.zip`, archived Jan2020–Sep2026. Matrix reads December2020 through December2021 (13 original EST-calendar source months; Dec2020 needed for full UTC Jan2021 first hours). R2 originals untouched. Each original ZIP and CSV payload SHA is saved as receipt. Source times are fixed EST UTC-5 (not a DST-switching EST/EDT input). Full source BID/ASK geometry checked. Historical Oct2021 known source-order inversion is handled transparently by earliest/latest quote per minute in a **separate derived snapshot** with recorded inversion count. Incomplete actual-source hours are excluded, not repaired or synthesised. Raw ZIPs never uploaded to GitHub as artifacts or to the user's Google Drive.

## Exact S010 rules

Independent frozen `src/aidy/strategy_lab_s010_backtest.py`: long-only SMA12 crossover above SMA34 if RSI14 below 70; exit qualifying downward crossover if RSI above 30. Completed H1 closed bar decides signal; **next actual source-derived H1 open BID** is modelled using the same historical source calculation as 2025. Exposure 3.28x, start hypothetical USD10,000, **no protective stop in published source**. Published source original code remains unchanged. Cost scenarios identical to frozen 2025 BID historical model: base model assumed spread $0.30/oz, slippage $0.05/oz EACH side, commission $0.07/oz roundtrip; cost stress $0.80 spread/$0.25 slip/$0.14 commission; 1x exposure baseline. 2021 observed original HistData H1 first-tick ASK and spread are separately preserved as evidence and summarised but are not represented as executable broker quote or fed into a backtest claiming Vantage equivalent execution.

## Automatic acceptance boundaries

A passing experiment requires all 13 source receipts and strict hashes; at least 3,500 real completed 2021 UTC H1 BID bars across every individual month; 12 monthly modelled P&L records; every trade event reconciles against the deterministic full-year original strategy engine; real-source SHA/geometry audit; independent complete trade ledger; two alternative cost sensitivity scenarios; explicit negative/positive result. Even if historical year profitable, it is NOT automatically eligible for paper until intelligent diagnosed tweak if justified, execution realism including historical true broker ASK, swaps, stopout/liquidation, and final owner risk review.

If the genuine source or credential is unavailable, CI must fail with a concrete source-stage error, NOT report invented 2021 profit. If 2021 is negative, the current two-year GoldThinker gate correctly stops automatic tweak promotion and paper approval. Nothing is altered in the 83-source register without independently accepted evidence.

## Engine details

- Source reader: `src/aidy/strategy_lab_crossfire_tick_2021.py`.
- Per-source job: `scripts/strategy_lab/crossfire_2021_derive_month.py`.
- Unchanged 2021 full-year run: `scripts/strategy_lab/crossfire_2021_collect_and_backtest.py`.
- 13 independent source and result artifacts: `.github/workflows/strategy-lab-crossfire-2021-real-backtest.yml`.
- Adversarial source tests: `tests/test_strategy_lab_crossfire_2021_ticks.py`.

## Current true status

2025 already empirically modelled with real historical BID data. 2021 verdict only when full source month matrix and annual original model actually runs. No MT5, no broker trades, no tweaks, no retroactive change to frozen 2025 research.
