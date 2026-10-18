# S001 GoldEA, first AIDY source-eligibility investigation (18 October 2026)

Scope: the FIRST strategy from the owner's original 83-row AIDY scoreboard.
Original source: https://github.com/eamonnkennedy93-blip/GoldEA, original pinned
file blob SHAs in the audit runner.

## What actually runs
- Pull-request CI reads original January 2025 XAUUSD native M1 BID rows from
  the already qualified read-only BigQuery archive, with query dry run and
  1.5 GB maximum bytes billed.
- Independently verifies source provenance and partial-versus-complete
  15-minute candle coverage. Archives data only as counts + original hashes.
- Emits source-read JSON and Markdown with a fixed, explicit BLOCKED strategy
  verdict, and does not insert any simulated trade results.
- No broker orders, Cloudflare writes, production job changes or external
  publisher code execution. No PDF profit report until rules are qualified.

## Why AIDY cannot currently award S001 performance figures
1. Published system depends on MetaTrader 5 tick_volume-based anchored VWAP,
   whereas the frozen BigQuery original historical series is BID M1 OHLC,
   without proven original native MT5 tick_volume or ASK executable fills.
2. Published backtester unconditionally imports entry_refinement.py which is
   not in the public repo, even though the README describes it as optional.
3. The funded/live MQL5 Expert Advisor is not in the public repository.
4. Published PF 1.30, 183 OOS trades and benchmark PF 1.09 are source author
   claims, not an independent AIDY $10k account result.
5. No LICENSE is included. Rights to commercialise or redistribute are unknown.

The AIDY nine-factor GREEN evidence rating, independent net P&L, win-rate,
max drawdown, robustness and external-source parity remain NULL/NOT VERIFIED.

## What unlocks the next step
A separately reviewed source-faithful M15/H1/H4 causal parser, independent
historical native tick volume and quote-side evidence, confirmed execution
and exact entry/stop/exit variants from the author's code, broker time zone
and trade-receipt parity; then chronological OOS, benchmark and cost stress.

Do not imply that a *data acquisition PASS* is a *strategy backtest PASS*.
The original S001 candidate remains in the queue; S010/CROSSFIRE and all
other 82 candidate systems are unchanged by this branch.
