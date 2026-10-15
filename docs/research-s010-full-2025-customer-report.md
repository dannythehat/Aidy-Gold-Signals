# S010 - 12-month customer-grade independent AIDY gold backtest

**Authorised request:** Owner explicitly rejects a one-hour signal test and requests ONE complete system over months with paid-customer style PDF and actual trade P&L. S010 is a complete published long-only system with defined entry/exit (despite no original protective stop). No broker orders.

## Original strategy code, frozen parameters
Public MIT source: https://github.com/AluminumShark/Tick-Backtest, files `main.py`, `src/strategy.py`, `src/backtest_engine.py` audited before implementation. Original `main.py`: MA12/MA34, RSI14, leverage 3.28, long-only and initial equity $10,000. A long entry is a golden cross with RSI below 70; exit to flat is death cross with RSI above 30. The system has NO published stop-loss; it may experience serious losses. DO NOT add a stop or RSI exit unless source specifies. Use completed H1 signal with next H1-open fill to avoid same-bar hindsight.

## Period / data / model
Pre-register full UTC calendar 2025 Jan-Dec (12 months, not hourly test). Real independently immutable HistData XAUUSD native M1 BID prices in AIDY BigQuery, verified source metadata and source fixed EST -> UTC; aggregate complete H1 only and count excluded partial hours. Original publisher tick-level mid/ASK series was not provided. Our source is materially different from their original ticks: exact replication or point-in-time OOS parity MUST NOT be claimed. 12 original monthly SELECT jobs with a 1.5GB per-month BigQuery scan safety cap.

Scenarios (not actual observed broker costs):
1. Original leverage 3.28x, assumed spread $0.30 per oz, $0.05 adverse slippage per side, $0.07 commission per oz round-trip.
2. Same leverage with cost stress: $0.80 spread, $0.25 adverse slippage per side, $0.14 commission.
3. 1.0x base costs.
No overnight swap, margin calls, liquidation or source ASK tick provenance: hard risk qualifications. Mark open positions at BID at the end of 2025; separately count only actually closed trades. Buy & hold 1x BID benchmark shown, not as risk-matched alpha.

## Paid customer PDF contract
Release only if all 12 original source months and a complete reconciled trade ledger exist; never construct a fake customer report on synthetic candles. PDF generated in GitHub Actions from the real machine-readable result includes branded cover, precise rules, 12-month mark-to-market equity and DD charts, all months positive/negative, monthly P&L and returns, win/loss and profit factor, spread/slip/commission stress and benchmarking, complete trade ledger, BigQuery job IDs/source SHA and limitations.

**Security/approval:** This user-authorised one-off research job is not a blanket stage approval or a qualified commercial release. It does not enable customer portal billing or live/paper broker trading. No manipulation of the original 83 systems' `VERIFIED` metrics. AIDY trading strategy pass and GoldThinker publication remains owner-governed.

## Evidence checkpoint
- [Research PR](https://github.com/dannythehat/Aidy-Gold-Signals/pulls?q=is%3Apr+S010) - dedicated strict GitHub Actions workflow archives PDF + CSV + full source data/provenance and genuine ledger. Actual CI outcome must be linked when available.
