# AIDY actual gold-system processing — connected research proof

**Focus:** AIDY processes systems. Not payments, subscribers, or launch bureaucracy.

## What exists and what this change connects

The existing AIDY repository has separate StrategySpec/registry, rule validation,
restricted strategy adapters, next-open execution model, costs/ledger, archived
XAUUSD historical data and reporting. Day32 batch queue previously accepted
synthetic scheduler diagnostics only: its 100 jobs were NOT 100 gold system tests.

This release integrates a controlled **multi-system historical processing runner**
with the existing authenticated 2025 native HistData M1 BID read-only BigQuery
workflow, source-provenance receipts, costed execution, per-trade ledgers,
per-calendar-month metrics, marked equity/drawdown and independently distinct
output files. No arbitrary or untrusted code is executed.

Two explicit mechanical rule families are verified on the **same 2025 source**:

1. **S010 original** — exact unchanged published MA12/34 + RSI14 logic,
   source-reviewed independently earlier. Its full 2025 result MUST match the
   original prior 12-month runner exactly in the full nested record, including
   every trade, monthly result, equity snapshot and costs; changed results
   FAIL. Base and stress model scenarios, leverage 3.28x, 10k reference capital.
2. **LAB_DONCHIAN_20_10** — independently AIDY-authored deterministic system
   testing whether completed H1 close is above the prior 20 *complete H1 highs*
   to enter long; completed H1 close below the previous 10 H1 lows for exit;
   market entry/exits at NEXT H1 open, 1.0x leverage and per-system fresh
   separate 10k account. It is a **LAB EXAMPLE**, not S005, S040 or a
   reproduction of any original source catalogue strategy. No parameter
   tuning or optimization is allowed by this integration.

Both use the same costed account and marked-equity model, with identical
illustrative base/stress price/commission/slippage assumptions per ounce.
Each gets an independent ledger with trade-by-trade USD results, monthly
account changes, drawdown and 1x buy/hold comparison.

## Required source-connected acceptance

[Dedicated workflow](../.github/workflows/strategy-lab-multi-system-real-gold.yml)
must first run the same original 2025 all-twelve-month read-only BigQuery
source retrieval as S010 historical research; incomplete/invalid source fails
closed. Second stage consumes the **actual generated H1 CSV** and original
source report in the SAME GitHub runner, checks 12 monthly query receipts,
validates all H1 rows, replays two models, and independently confirms full
original S010 result equality. Save JSON research packet, SHA receipt and
four separate trade CSV ledgers. Unit tests exercise mechanical input
validation, genuinely causal Donchian timing, unknown/duplicate family
rejection, missing source, and original S010 backward compatibility.

## Scope and limitations

- This is proof that AIDY can process **multiple distinct mechanical rule
  families** from verified historical prices, not that all 83 candidates
  have been loaded, source-ported, backtested, or scored.
- Existing Pine, MQL, Python predicate and written-rule adapters have bounded
  grammars; generic automatic source-to-broker execution remains unsupported.
  An unreviewed external strategy cannot be relabelled as this lab Donchian rule.
- Historical execution is BID-price replay plus **illustrative ASK and fee**
  scenarios. No Vantage swap, leverage liquidation, broker fill or real
  customer paper results are verified; models are not investment guarantees.
- Scientific evidence needs per-original-system source fidelity, broker
  costs, sufficient independent samples, untouched OOS and risk qualification.
  Real system output is separate from customers and GoldThinker public claims.
- Results and code never contact MT5 or place paper/live orders.

**Where to add another strategy:** Author a separately reviewed, frozen,
closed-bar causal signal compiler and source-identity mapping; add its exact
source/model tests and register it explicitly in the bounded supported
processor. Unsupported inputs fail, rather than produce a made-up P&L.

**This work deliberately excludes Day38 payment changes and does not mark
the 40-day launch checklist complete.** It solves a real research execution
integration task rather than a commercial launch dependency.
