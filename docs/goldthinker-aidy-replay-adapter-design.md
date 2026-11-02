# AIDY selected-year replay adapter

Status: boundary only. No strategy executor is wired. This is not a backtest result.

## Call shape

`AidySelectedYearReplay.replay(selection, data_manifest) -> AidyReplayResult` is the adapter boundary in `src/aidy/goldthinker_factory_replay.py`. One versioned adapter serves one frozen strategy. It must recompute trades from that strategy's rules. It must not read or copy the MT5 deal ledger.

`ReplayRequest` is the binding the adapter has to honour inside that call:

- selected year and the selection SHA
- strategy source SHA (the frozen StrategySpec / original rule)
- adapter SHA
- quote dataset SHA and coverage, bid and ask, for that year only
- server clock and DST rule
- starting capital, lot size, margin model
- spread, commission and swap model

The output is a canonical list of the adapter's own trades (entry and exit time, direction, volume, price, costs, P&L), a hash of that list, and unmatched diagnostics. Reconciliation may then compare that list with the MT5 ledger. The adapter does not receive the ledger.

With no supported executor or no authenticated bid/ask history the result is `AIDY_REPLAY_UNAVAILABLE` / INCONCLUSIVE. It is never MATCH. Caller-supplied trades (`explicit_trade_list`) are not this adapter and cannot set `research_packaging_allowed`.

## First targets

S040 is the intended first smoke adapter. In this repository it is only a catalogue row: `research/strategy_lab/day33_gold_edge_83_snapshot.json` names it "Gold Breakout EA H4" and points at `https://www.mql5.com/en/code/77691`. There is no StrategySpec, no `.mq5`, and no compiled EA for S040 here. `S040SmokeReplay.replay` is a stub that raises unavailable and does not open MT5 output.

S016 is the later profitability candidate. It is not an adapter yet.

## Tests to add when an executor exists

- Intentional price, cost and dropped-trade mismatches against a frozen MT5 ledger.
- Trade count, including partial closes.
- A position still open at the selected year end (must not be forced flat).
- A tampered runner attestation or quote-dataset hash (must not reach MATCH).

Those tests are not implemented. The stub test only checks that S040 cannot replay.
