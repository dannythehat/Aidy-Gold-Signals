# Day 22 deterministic safety gates v1

Version: `aidy_deterministic_safety_gates_v1`

Day 22 places deterministic infrastructure checks on both sides of the Day 21
OpenAI gateway. The model is allowed to make trading judgement. It is never
allowed to decide whether evidence is fresh, complete, internally consistent,
duplicated, or safe enough to progress.

## Pre-model gate

`evaluate_pre_model_safety(...)` decides whether a market context may be sent
to OpenAI at all.

A context is blocked if any of these conditions is true:

- the instruction type is not explicitly supported;
- the Day 10 context version, XAUUSD symbol, or context hash is invalid;
- the context contains retrospective history or broker/follower state;
- the context timestamp is future-dated or older than the configured freshness
  limit;
- the same context hash was already processed;
- any required Gold timeframe is not genuinely `known`;
- the quote is unknown, stale, internally inconsistent, or its spread is
  unknown;
- macro-event evidence is unknown;
- any required cross-market series is missing, inconsistent, or more than seven
  days old;
- AIDY lifecycle evidence is unknown, incomplete, duplicated, or contradictory;
- recorded/computed session evidence is not explicitly consistent.

The gate checks the underlying evidence as well as Day 10's summary fields.
A rehashed packet cannot become admissible merely by changing a summary string
such as `quote_freshness` from `stale` to `fresh`.

Supported instruction types are:

- `market_evaluation`
- `active_signal_management`

A blocked pre-model result means **no model call**. It is not converted into a
synthetic trade opinion.

## Post-model gate

`evaluate_post_model_safety(...)` receives the immutable Day 10 context, the
successful pre-model receipt, the Day 21 gateway result, and optional current
Day 15 setup detection.

It blocks progression when:

- the pre-model receipt is missing, tampered, blocked, or belongs to another
  context;
- the context became stale while the model was running;
- the Day 21 gateway failed closed or did not admit publication;
- the Day 20 decision contract or decision digest is invalid;
- the model decision timestamp does not exactly match the source context;
- the decision is future-dated or expired;
- the action does not match the requested instruction type;
- `new_trade` cites a setup that is absent from the current authenticated Day 15
  detection or conflicts with its frozen direction;
- `manage_trade` or `close_trade` does not identify exactly one active AIDY
  originating decision.

Day 20 SL/TP geometry is revalidated post-model rather than trusted merely
because the provider used Structured Outputs.

## `no_trade`

A valid `no_trade` is a successful decision.

It returns:

- `decision_admitted = true`
- `actionable = false`
- `downstream_action = "no_action"`

This preserves abstention in the learning ledger without inventing an external
action.

## Confidence

Confidence is never inspected when deciding whether a gate passes. A
`confidence = 1.0` decision is blocked exactly like any other decision if its
evidence, action, target, timing, or geometry violates a deterministic gate.

## Multiple active AIDY signals

Day 22 does **not** impose an accidental one-trade-at-a-time policy. Multiple
distinct active AIDY signals are allowed. A lifecycle conflict exists only when
identities are missing/duplicated or state declarations contradict the active
signal list.

## Current live-data implication

The current independent Gold-API feed is indicative mid-only and does not
provide genuine live OHLC or spread. Therefore a real Day 10 live context may
currently fail Day 22 for missing technical timeframes and/or unknown spread.
That is expected safety behavior, not a reason to weaken the gates. A later
AIDY-owned independent live market-data improvement must close that evidence
gap before the Master Trader is expected to authorize real-time new trades.

## Boundaries

Day 22 does not:

- call OpenAI;
- publish Telegram messages;
- access broker, MT5, MetaAPI, Vantage, follower, balance, or account state;
- size positions;
- execute trades;
- use Super Signals;
- use future/evaluation-only research data;
- change Day 15 setup definitions or Day 20 decision semantics.

Day 23 may compose evidence only after a successful pre-model receipt and may
submit a model decision to the post-model gate after the Day 21 gateway returns.
