# S004 | Four-phase volatility pullback window | AIDY initial $10,000 audit

**INITIAL SCREEN FAILED: insufficient real executable sample and oversized source minimum trade. No paper-trading promotion, no customer PDF.**

## Proven model evidence

Historical source: 22 authenticated original HistData XAUUSD BID/ASK ZIP months (December 2024 warm-up, January 2025 to September 2026), converted to genuinely completed **M5** candles. Original market-derived M5 ledger sha256: `46219b6e2121a299b7c95e026354a642c3f44b58fad8ba7e6b7302d950d30fe8`.

**Original author Backtrader class was executed, not reconstructed from an invented rule family**. Original source blob `8f3289f5e25107e0bf73f1d4f355908b9b96cc82` from repo commit `4ab0213c5e6dd3ffb486a67f9b07bef788cdbd02`.

| $10,000 model period | Completed trades | Wins/Losses | Margin rejects | Net P&L | Ending model equity | Profit factor | Max marked drawdown |
|---|---:|---:|---:|---:|---:|---:|---:|
| Full 2025, original code | 5 | 3/2 | 6 | +$946.62 | $10,946.62 | 1.3689 | -16.1324% |
| Full 2025, 2x observed spread/slippage cost model | 5 | 3/2 | 6 | +$758.12 | $10,758.12 | 1.2827 | -16.6184% |
| Jan-Sep 2026, original code | 0 | 0/0 | 1 | $0.00 | $10,000.00 | N/A | 0.0000% |
| Jan-Sep 2026, 2x cost model | 0 | 0/0 | 1 | $0.00 | $10,000.00 | N/A | 0.0000% |

2025 realised months: Jan +$1,139.31 (1 trade), Feb +$665.27 (2 trades), Mar +$1,038.39 (1 trade), May **-$1,896.34** (1 trade). May's single loss was approximately 19% of starting $10k, violating the nominal source 1%-per-trade description. Six additional 2025 attempted trades were rejected by the modelled broker margin checks. January-September 2026 did not create a single qualifying filled trade. Its one attempted order was **100 oz × $4,164.385/oz = $416,438.50 notional**, rejected for insufficient margin with a $10,000 account and the source's nominal 30x leverage.

## SOURCE AUDIT WARNINGS

- Published README presents LONG stop **2.5× ATR** and TP **12× ATR**, but the actual code defaults **4.5× ATR stop** and **6.5× ATR TP**, with **short entries disabled**, LONG ATR maximum **$2.00**, 3-red-candle pullback and just **one M5 breakout-window bar**. There was no silent rule substitution.
- Original author backtested a **$100,000 account** with **175 trades claimed for 2020-2025**, which cannot establish performance with our $10,000 capital restriction.
- Original source enforces a minimum **ONE 100-oz gold contract**, even when the 1%-stop-based computed number would be smaller. Source code has a 30x leverage broker assumption. Consequently a $10k model cannot safely or consistently size a position to 1%-at-stop and becomes ineligible as gold rises.
- Source data are the original authenticated HistData source BID prices. Historical original source BID/ASK quotes inform a **median source spread + assumed $0.10/oz additional slippage each side + $7/lot roundtrip fees**. Native author CSV, Vantage stop/commission/margin, financing, and exact intrabar BID/ASK chronology are NOT claimed as independently matched.
- Original `SunriseOgle` class was loaded from pinned source and exercised through the publisher's own GenericCSVData adapter with audit-only execution instrumentation. **No original trading logic or defaults were rewritten.** Backtrader margin and order fills are still a historical model, not genuine Vantage receipts.
- Both test bands started from an **independently reset hypothetical $10,000 account**. A zero-return 2026 period with zero fills is *not* interpreted as a successful profitable year or a measured profit factor.

**AIDY VERDICT:** **RED / FAILED INITIAL $10K FEASIBILITY AND TWO-PERIOD ROBUSTNESS / DO NOT ADD.** One 2025 profit on only five accepted trades, severe account risk and no 2026 fills cannot qualify for paper trading. Reject and continue to next candidate.

Audit evidence: https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/39154947507/artifacts/12146652366

Full original historical M5 source pipeline: https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/39154372333
