# Gold X9 isolated research status - 3 November 2026

## What this PR actually contains
- An independently authored Python replay of tutorial v6.3 Strategy 9 against original HistData XAUUSD BID/ASK ticks stored in AIDY R2.
- Original fixed EST timestamp parsing is reused from AIDY's authenticated source adapter. Raw monthly ZIPs remain untouched. A disk-backed stable chronological merge sort handles recorded source timestamp inversions.
- Pending stop-order placement on 15-minute scans from confirmed H1 five-left/five-right fractals without future candles, execution at observed ASK/BID, initial 2% hard SL, 0.7% TP, M1 breakeven/trailing/salvage approximations and per-tick protective exit checks.
- Actual simulated closed trades and a single shared account ledger with fees, observed minute-level equity drawdown, reconciled cash and trade attribution, monthly profits and losses, and hashes of source archives.
- R2 work only executes in GitHub Actions when repository secrets are present. No funded account, broker terminal, executable trading order or production worker is touched.

## Exact fidelity boundaries
This is NOT the compiled MrCapFree Gold X9 v6.2 original EX5, not all 9 strategies, not a native MT5 Strategy Tester report and not a replication of the creator's returns. The v6.2 original binary is in the owner's separate handover archive with SHA256 21730d50f49ae6343d024d19804b4bec4f3af9ca211a38cc644065b1fa3e6f40. It has not been placed in this GitHub repository or CI runner.

S1-S8 factory parameter vectors are not available in tutorial parts 1 or 2. Original v6.2 has additional portfolio risk profiles, global equity protection, TP trailing, lot sizing and news filter. Do not invent S1-S8 vectors. This approximation also omits native margin, stop/freeze requirements, pending order modification parity, swaps, broker weekend/holiday calendars, terminal restart recovery, broker midnight timezone parity and exact creator intrabar stop-modification sequencing. Their absence can materially change performance. The 0.01-lot, 100oz contract, $0.01 point, 50-point max spread, assumed $7/lot roundtrip commission, zero swap, and UTC midnight proxy are NOT attested broker inputs.

H1 structural swing input uses true original BID ticks; quote timestamps are UTC as reconstructed from fixed EST. The creator's spoken 0.02% versus 0.1% minimum clearance conflict is an explicit --clearance-pct experiment, initially 0.1%.

## Reproducible CI campaign
The workflow runs:
1. Five fast synthetic unit tests of timestamp ordering, causal pivot confirmation and exits. These are NOT historical performance evidence.
2. Authenticated historical ticks from January 2022 and September 2026 with baseline and double-stress commission/slippage, capital $10,000 and 0.01 lot. These are two monthly windows, NOT full 2022-2026 or an all-nine backtest.
3. Evidence artifacts: summary.json, trades.csv and CI logs, tied to archive SHA256. Failed credentials, source, or replay fail closed without financial conclusions.

## Original demo and portfolio still required
Original native MT5 Strategy Tester S1-S9 plus combined nine-strategy tests, real broker ticks, native .set exports, orders/deals/equity/journals. Run only on an isolated terminal without funded account access. The complete user-authored original handover with all source files is saved in their ChatGPT Library as GOLD_X9_FULL_HANDOVER_FOR_NEXT_AI_2026-11-01.zip.

Separate from NY ORB research, the other 83 strategies and all live/penny accounts. Not approved for production or trading.
