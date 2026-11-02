# Synthetic MT5 fixtures

These files are authored stand-ins for MetaTrader 5 Strategy Tester reports.
`source_kind` is `SYNTHETIC_FIXTURE`. They are not broker output, not a real
terminal build, and not evidence of profit.

`synthetic_GT_TEST01_2023_real_ticks.htm` is UTF-8 so it can be reviewed in
git. Real tester `.htm` files are often UTF-16; the extractor accepts that
encoding, and the unit tests cover it. The book is two flat XAUUSD round
turns plus the opening balance deal, with the same column layout as an
English Strategy Tester Deals table.
