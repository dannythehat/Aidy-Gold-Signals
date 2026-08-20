# AIDY Day 20 — Master Trader Decision v1 Contract

## Purpose

Day 20 freezes the first machine-verifiable output language for the future OpenAI Master Trader.

Contract version: `aidy_master_trader_decision_v1`.

This day does **not** call OpenAI, publish Telegram messages, size positions, execute trades, or read follower/broker state. Day 21 owns the Responses API gateway. Later days own deterministic gates, context composition, decision ledgering, paper lifecycle, watcher management, Telegram publication and the owner-gated downstream provider integration.

## Core rule

A model decision is either valid under this exact contract or rejected.

There is no prose parser and no permissive interpretation of malformed combinations.

The contract supports exactly four first-class actions:

1. `new_trade`
2. `manage_trade`
3. `close_trade`
4. `no_trade`

A `no_trade` is a real decision and must be preserved later in the decision ledger just like a trade decision.

## Why the schema is flat

The Structured Outputs schema is one strict top-level object.

Every field is required. Fields that do not apply to a selected action are represented explicitly as `null` or an empty array. `additionalProperties=false`.

This gives Day 21 a simple strict JSON Schema while the deterministic Day 20 validator enforces the stronger cross-field/action semantics.

The model is not trusted to infer that an irrelevant field should be ignored. An unsafe combination is rejected.

## Common fields

Every model output contains:

- `contract_version`
- `action`
- `symbol`
- `evaluated_at_utc`
- `valid_until_utc`
- `confidence`
- `setup_taxonomy_version`
- `setup_codes`
- `reason_codes`
- `decision_summary`
- all action-specific fields, using explicit null/empty values when irrelevant

`symbol` is locked to `XAUUSD`.

`valid_until_utc` must be later than `evaluated_at_utc`.

`confidence` is a number from 0 to 1. It records the model's self-assessed decision confidence for later calibration and evaluation. It does **not** size risk and cannot unlock any position-sizing field.

`decision_summary` is a concise final rationale only, capped at 500 characters. The contract neither requests nor stores hidden chain-of-thought, scratchpads, private analysis traces or internal reasoning tokens.

## Decision IDs

The model does **not** invent its own new decision ID in Day 20.

The future gateway/decision ledger can allocate the durable ID outside the model response. This keeps infrastructure identity deterministic and outside model control.

`manage_trade` and `close_trade` must include `target_decision_id`, referencing the exact existing AIDY decision/trade being managed.

`new_trade` and `no_trade` require `target_decision_id=null`.

Day 24 owns the durable decision ledger. Day 32 later proves watcher-to-lifecycle mapping against exact existing trade state.

## Setup vocabulary

Day 20 imports the accepted Day 15 setup taxonomy directly:

`aidy_gold_setup_taxonomy_v1`

The JSON Schema enumerates all 20 accepted setup IDs.

A `new_trade` requires at least one accepted setup code. `no_trade` may contain no setup code, or may record one or more observed setups that the model deliberately declined to trade.

Setup detection still does not make the trading decision. OpenAI remains the future judgement layer.

## `new_trade`

V1 requirements:

- `direction`: `long` or `short`
- `entry_type`: exactly `market`
- `market_reference_price`: positive number
- `stop_loss`: mandatory positive number
- `targets`: 1–3 unique positive numbers
- at least one accepted Day 15 `setup_code`
- no management fields
- no close field
- no target decision ID

The market reference price is the decision-time analytical anchor. It is **not** a pending-order instruction and does not turn a market instruction into a limit/stop order.

Geometry:

Long:
- stop < market reference
- every target > market reference
- targets strictly increase

Short:
- stop > market reference
- every target < market reference
- targets strictly decrease

Pending/limit/stop entries are outside AIDY V1.

## `manage_trade`

`manage_trade` requires an explicit `target_decision_id`.

V1 output-language instructions are limited to:

- `move_stop`
- `replace_targets`
- `move_stop_and_targets`

Action payload rules:

`move_stop`
- `new_stop_loss` required
- `new_targets=[]`

`replace_targets`
- `new_stop_loss=null`
- `new_targets` contains 1–3 unique positive prices

`move_stop_and_targets`
- `new_stop_loss` required
- `new_targets` contains 1–3 unique positive prices

The Day 20 contract validates the shape and positivity only. It does not have the current theoretical trade state, so it does not pretend to prove direction-relative management geometry. Day 32 owns the exact state mapping and geometry gate.

## `close_trade`

`close_trade` requires:

- exact `target_decision_id`
- `close_scope="full"`

Partial close is not in AIDY V1.

All new-trade and management geometry fields must be neutral.

## `no_trade`

`no_trade` is first-class.

It can express deliberate restraint when:

- no accepted setup is present,
- setup evidence is ambiguous,
- data quality is weak,
- historical evidence is insufficient,
- macro/context evidence is adverse,
- or the model judges that no trade is earned.

All trade/management/close fields must be neutral.

This is critical for later no-trade evaluation and calibration.

## Reason codes

`reason_codes` contains 1–8 unique lower-case stable slugs.

Day 20 intentionally freezes the code format, not a prematurely exhaustive reason taxonomy. The prompt/context layer may constrain preferred codes later, while the ledger can still measure stable codes without storing hidden reasoning.

## Position sizing is prohibited

The model contract has no:

- lot/lot-size
- volume
- quantity/units
- position size
- risk amount
- risk percentage
- account balance/equity
- margin
- leverage

The deterministic validator also rejects these names if a hostile caller adds them.

SL and TP are thesis geometry. They are not follower position sizing.

Downstream risk sizing remains outside AIDY's Master Trader decision output.

## Hidden chain-of-thought is prohibited as a contract field

The contract does not ask for or retain:

- `analysis`
- `chain_of_thought`
- `hidden_reasoning`
- `reasoning_trace`
- `scratchpad`
- `thoughts`

A concise `decision_summary` is sufficient for auditability and later evaluation.

## Strict Structured Outputs wrapper

`master_trader_response_format()` exposes:

- `type=json_schema`
- `name=aidy_master_trader_decision_v1`
- `strict=true`
- the frozen Day 20 JSON Schema

Day 21 owns the actual OpenAI Responses API call, model/config pinning, timeout/retry handling, refusal/incomplete handling, cost/latency capture and server-side revalidation.

Day 21 must treat Structured Outputs as a syntactic guarantee, not a replacement for Day 20 semantic validation.

## Deterministic output integrity

Validated decisions can be hashed with canonical JSON/SHA-256 via `master_trader_decision_digest()`.

The model does not supply this digest. It is deterministic application evidence.

## Non-goals

Day 20 does not:

- call OpenAI
- choose a model
- define prompts
- compose the market context
- decide setup detector thresholds
- change historical similarity/evidence grades
- size follower risk
- read account/broker state
- execute MT5 orders
- publish Telegram
- implement pending orders
- implement partial closes
- modify Super Signals

The contract is the language boundary only.
