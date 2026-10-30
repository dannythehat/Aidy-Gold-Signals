# TRIGGER HAPPY — AIDY research strategy TH-001
Version: **0.1 (hypothesis frozen before real-data outcome review)**  
Status: **RESEARCH ONLY — not historically validated, not forward-paper or live enabled**  
Owner observation: abrupt XAUUSD price changes (~USD 3 or more within 1.5 seconds) sometimes precede substantial continuation in the same direction.

## Separation
- AIDY private research candidate, distinct from the 83-source Gold Oracle PR #374 catalogue and from Super Signals.
- This spec creates **no broker orders**, alters **no live strategy**, and is **not** GoldThinker product/admission or proof of profitability.
- An independent candidate ID; no duplicate claim relative to other momentum systems without code/semantic comparison.

## Hypothesis / null
H1: after a causal >= $3.00 midpoint movement in <= 1.5 seconds, same-direction continuation is frequent and large enough to pay for three exits and all transaction costs even with delayed fills.  
H0: after observed spread, delay, slippage, stop gaps and fees, the configuration has no positive out-of-sample expectancy relative to controls.

## Frozen v0.1 entry rules
1. Subscribe to **real two-sided XAUUSD bid/ask ticks with subsecond original timestamps**, in chronological order. Never use M1 OHLC to assert a 1.5-second move.
2. For each eligible tick take MID=(BID+ASK)/2; compare against the earliest eligible prior quote in the last **1,500 milliseconds**. At least two distinct timestamped observations required. Positive MID difference >=3.00 triggers a BUY; <=-3.00 triggers a SELL. First crossing only. Do not look into future ticks.
3. Ignore malformed/inverted quotes and prohibit triggering if BID/ASK spread > **$0.80** (explicit research assumption, not a verified Vantage rate). Record skipped candidates.
4. Only one 3-leg bundle at a time; cooldown **10 seconds** from signal; no averaging-down, pyramiding or reversal while open.
5. Submit hypothetical market order for three equal 0.01-lot legs. Entry **not on the triggering quote**: first observed subsequent tick at least **200ms** after the trigger; if no eligible fill within 3 seconds, cancel. BUY executes at observed ASK; SELL at BID. The 200ms delay is hypothetical, not measured brokerage latency.
6. All TP/SL levels are anchored to **each actual executable entry**. For BUY: +$2/+4/+8 targets and -$4 stop; for SELL: -$2/-4/-8 targets and +$4 stop, on each of three legs.
7. Exit long legs using BID, short legs using ASK. Stop crossings execute at **observed quote**, including worse-than-stop gaps; TP crossings credit at **target level, not an invented price improvement**. Stop check has priority. If a leg remains open at **5 minutes** after entry, exit at first later executable quote. At data end do not silently assume exit.
8. Retain per-leg and bundle ledger with trigger snapshot, bid/ask spread, detection delta, latency, fill and closure timestamps, exit reason and explicit fees. Required actual Vantage contract/commission/swap parity is separately unverified. Example model $/price move per leg requires contract ounces per lot.

## Variables to test, without retroactive relabelling of baseline
- Baseline: $3/1.5s, 200ms latency, spread cutoff $0.80, target +2/+4/+8, stop -4, 5-minute timeout, 10-second cooldown.
- Prespecified robustness: entry delay 50/200/500/1000ms; thresholds $2/$3/$4/$5; detection windows 0.5/1.5/3 seconds; realistic fees; wider spread; 0.2/0.5/1.0 adverse price-unit slip sensitivity. These are RELATED VARIANTS, not independent bots.
- Control: matched same-session randomized entry and direction, plus raw post-spike continuation statistics before execution.
- Report BOTH directions separately; per-session/day/month/year, regimes and high-impact announcement windows; compare to controls.

## Data availability and blockers (based on inspected AIDY repository, 2026-10-30)
- AIDY documented **81 original raw HistData two-sided XAUUSD tick archives (2020-01 to 2026-09)** in private Cloudflare R2, about **389.66 million raw rows**; download/reconciliation receipts do not by themselves establish fit-for-execution, licensing or subsecond stamp completeness.
- Raw source archives include **chronological inversions**; original ZIPs must remain immutable and a separately hashed, deterministic, stable chronological derived stream must be prepared before replay. The backtest rejects inversions.
- The existing BigQuery **minute-quote** derivatives (last quote each minute) are **not** suitable for this trigger.
- No access to the private original R2 ZIP content or live broker fills is assumed by this spec. No real tick backtest result exists in this submission.

## Prepaper acceptance requirements
1. Source integrity / per-month coverage and exact timestamp precision, quote validity, timezone, spread statistics and monotonic derived order are independently verified.
2. Exact causal event reconstruction and synthetic/unit tests demonstrate latency, stop gaps, each TP, long/short symmetry, no duplicate stacking, no lookahead and unresolved open positions.
3. Chronological train/validation/untouched holdout with embargo around overlapping shocks, multiple-threshold correction, actual COSTED 2020–26 yearly ledger and news-volatility strata, not only a pooled positive total.
4. Practical execution review: Vantage symbol contract, tick speed, order ACK latency, 3-leg handling, volume limits, freeze levels, re-quotes, spread spikes, slippage and margin.
5. Only **after** above research review: forward-paper candidate on a separate isolated recording service with actual quote ingress and delayed simulated bid/ask fills, not connected to funded accounts.

## Core unknown
The user's observation may be correct about continuation *after the burst* but untradable at the actual delayed ask/bid. We must measure that explicitly rather than treating a directionally correct signal as an executable winner.
