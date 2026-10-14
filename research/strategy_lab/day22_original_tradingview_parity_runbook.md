# Day 22 — Final original-TradingView reference acquisition and replay

**Owner day-level acceptance: still BLOCKED pending an original TradingView
export of this exact Pine source and a provenance/authenticity review.**
The adapter/tests and public-source discovery have been built and merged
separately; do not mark the day completed on illustrative CSV alone.

## What our independent research established

- Unauthenticated read-only TradingView published-strategy access was
  established in real [GitHub probe 38565620274](https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/38565620274)
  and expanded in [run 38565817716](https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/38565817716).
  Read-only snapshots include the exact provider-published Pine source hash,
  chart symbol/timeframe and TradingView's published strategy trade records.
- A [published original XAUUSD M5 strategy](https://www.tradingview.com/script/5q4PsY3a-XAUUSD-Scalping-AGRESIV/)
  returned `chart_symbol=OANDA:XAUUSD`, `chart_interval=5`,
  original public **Pine v5** source hash
  `a248d60146310879fb791b62d6ff0c402a037ffe3d3be13412911dc2661c3f57`,
  and **690 TradingView-native strategy report trade records**.
  This is authentic read-only platform publication data. It is **NOT a
  match** for our Pine v6 EMA(10/30) source: the v5 original has EMA(5/13),
  RSI(7), ATR(14), long/short entries and trailing stops. Its first and last
  published entry timestamps are 2025-08-31 23:25 and 2025-10-22 10:40 UTC.
  Comparing those trade rows against our unrelated source would be fake parity.
- Several more published pages were probed, including a misleading Gold EMA
  strategy published on Nasdaq futures (MNQ), and a supposed XAUUSD M5 hybrid
  whose snapshot is actually on OANDA:XAUUSD **30m**. All were quarantined.
- The unofficial open-source read-only `tradingview-sdk` uses undocumented
  site endpoints; it is a research aid, not endorsed by TradingView. CI
  `strategy-lab-day22-public-tv-probe.yml` is safe to invoke manually;
  it has no secrets or trading permissions.
- TinyFish public fetch confirms text from published community script pages,
  but no TradingView authenticated Pine Editor is connected. Metered browser
  automation has a negative wallet balance and no TradingView browser sign-in.
  There is therefore **no honest way to execute our unpublished exact
  source on the TradingView Pine engine without TradingView chart access**.

## Fully prepared original-export verification procedure

TradingView's own docs explicitly support `Export chart data` CSV containing
a script's `plot()` data-window outputs. The three script plot labels are
chosen to be stable CSV headers, and the parser rejects missing indicators.

1. Use the **exact** [instrumented Pine v6 source](../fixtures/day22_tradingview_exportable_v6.pine.txt),
   SHA-256 **`fd2955cfaf5fff3f39f22cc3ac2f39fca5c803f52c1414956b89d5996421c1f8`**,
   with no edits. Its three trailing plot calls export `AIDY_FAST_EMA`,
   `AIDY_SLOW_EMA` and `AIDY_LONG_SIGNAL`.
2. In TradingView Pine Editor (signed in), open a **standard candlestick**
   OANDA:XAUUSD chart, **5-minute** timeframe; paste the exact source and
   select **Add to chart**. Retain the chart's symbol/feed/timeframe
   identification, script title/source and version in a screenshot or
   stable chart link. Do **not** replace it with a different EMA strategy.
3. Load at least **350 contiguous 5-minute historical candles** in an active
   market session without missing bars. More bars are preferable; avoid
   weekend/session gaps in the first exported window.
4. Use TradingView **Download chart data…** on that exact chart to save its
   unmodified CSV; the file must include `time`, `close` and all three
   `AIDY_*` plot columns. Do not edit CSV or reformat timestamps after export.
   A TradingView subscription may be needed depending on the account.
5. The AIDY verifier is `scripts/strategy_lab/day22_check_native_tradingview_csv.py`.
   After placing the CSV on the connected checkout, from repository root:
   ```
   PYTHONPATH=src python scripts/strategy_lab/day22_check_native_tradingview_csv.py PATH_TO_UNMODIFIED_EXPORT.csv --receipt day22_parity_receipt.json
   ```
   For Windows PowerShell use:
   ```powershell
   $env:PYTHONPATH = "src"
   python .\scripts\strategy_lab\day22_check_native_tradingview_csv.py .\TradingView_XAUUSD_5m.csv --receipt .\day22_parity_receipt.json
   ```
6. On raw bytes, the validator pins source and CSV SHA-256, checks
   OANDA:XAUUSD/M5 chart metadata, UTC five-minute **bar-opening** timestamps,
   source-to-spec identity, all recorded EMA values against a separate
   Pine-like recursive EMA implementation from exported closes (after
   300-bar initialisation decay), and **every** exported signal (both
   positive and negative) against the independent StrategySpec predicate.
   The receipt is explicitly `CSV_VALUE_AND_SIGNAL_PARITY_UNATTESTED`
   until original-export provenance is independently checked.
7. Day22 can only tick once actual exported bars/signals reconcile **and**
   the source-running-on-TradingView chart provenance is corroborated by a
   real chart screenshot/link/account export linked to the immutable source
   and CSV bytes. A fake lookalike CSV is never acceptable, even if it
   passes mathematical checks. There must be a recorded accepted source,
   exact chart/feed, signal times and an immutable CI run showing the same.

## Actually completed code/tests

- Existing core adapter remains strict Pine v6, and now optionally admits
  **only three specific data-window plot calls**, never arbitrary extra source.
- `src/aidy/strategy_lab_tv_chart_csv.py` rejects tampered/duplicated CSV,
  non-UTC/time-gapped rows, nonfinite/negative values, wrong chart,
  missing plot headers, mismatched EMA values, and any changed signal flag.
- `tests/test_strategy_lab_tv_chart_csv.py` covers malicious/invalid inputs.
  These local CSV cases are **synthetic**; they show how authentic export can
  later be verified, not that an authentic export was already obtained.
- [Passing source-probe+CSV CI run 38567700816](https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/38567700816):
  118 targeted Day20/22 regression tests passed; source hash for new exact
  instrumented Pine `fd2955cfaf5fff3f39f22cc3ac2f39fca5c803f52c1414956b89d5996421c1f8`.
  The earlier Day22 [133-test run 38563858155](https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/38563858155)
  remains passed.

## Remaining genuine blocker

**TradingView itself has not yet executed this exact instrumented source on
the target OANDA:XAUUSD M5 chart in an accessible account**. The public
strategy report belongs to *different* Pine sources. Do not quietly redefine
the required "original TradingView reference signals match" acceptance
criterion to tick the day based on a synthetic or unrelated script.

Official instructions:
- https://www.tradingview.com/support/solutions/43000537255-how-to-export-chart-data/
- https://www.tradingview.com/pine-script-docs/faq/indicators/
