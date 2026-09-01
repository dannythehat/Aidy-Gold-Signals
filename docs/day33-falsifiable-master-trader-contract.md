# Day 33 — Falsifiable Master Trader V2 contract

Day 33 upgrades the Master Trader decision record without changing accepted Day-20 trade geometry or
promoting a new OpenAI gateway. The purpose is to make AIDY's stated decision mechanism testable
later without requesting or storing hidden chain-of-thought.

## Additive versioning

Day 20 V1 remains the authoritative source for the four action semantics, XAUUSD-only boundary,
market-entry geometry, stop/target ordering, management instructions, full-close scope, confidence
metadata, sizing prohibition and hidden-reasoning prohibition.

Day 33 introduces `aidy_master_trader_decision_v2_falsifiable` as a new version. V2 validation
constructs the corresponding V1 core decision and delegates that core to the accepted V1 validator.
It then validates the new falsifiability fields. V1 source code and historical records are not
mutated. The versioned reader accepts V1 or V2 and never fabricates V2 thesis fields for old V1 data.

## Actionable decision requirements

`new_trade`, `manage_trade` and `close_trade` require:

- a concise substantive `thesis` describing the claimed mechanism;
- an integer `expected_horizon_minutes` from 1 through 10,080;
- a substantive `counter_argument` expressing the strongest bounded case against the action;
- a structured `invalidation_condition` that can be evaluated against a model-context JSON object.

The five no-trade shadow fields must be null on an actionable decision.

## No-trade requirements

`no_trade` keeps all Day-20 neutral trade geometry. It has no actionable `thesis`, actionable
horizon or actionable invalidation condition. Instead it requires:

- a substantive `abstention_basis`;
- a mandatory `counter_argument` against abstaining;
- a `shadow_thesis` describing the hypothesis to observe without taking exposure;
- a `shadow_direction` of `long`, `short` or `flat`;
- a bounded `shadow_horizon_minutes`;
- a machine-evaluable `shadow_evaluation_condition`.

This keeps abstention first-class while creating a later counterfactual evaluation target.

## Machine-evaluable conditions

A condition is a strict five-field object:

- `condition_version` = `aidy_machine_evaluable_condition_v1`;
- `field_path` = a safe absolute JSON path beginning with `$.` and containing only named fields and
  numeric list indexes;
- `operator` = `eq`, `neq`, `lt`, `lte`, `gt` or `gte`;
- `value_type` = `number`, `text` or `boolean`;
- `value` = a matching scalar value.

Ordering operators are numeric-only. Wildcards, executable expressions, extra condition fields,
non-finite numbers and type mismatches are rejected. Runtime evaluation returns `True`, `False` or
`None`; missing or type-mismatched evidence propagates UNKNOWN rather than being treated as false.

## Concise auditability, not hidden reasoning

Thesis, counter-argument, abstention and shadow-thesis fields are bounded final statements. Very
short/generic placeholders are rejected deterministically. They are not chain-of-thought fields and
the schema contains no scratchpad, analysis or hidden-reasoning surface.

## Frozen boundaries

Day 33 does not:

- change the active Day-21 OpenAI gateway or prompt;
- promote Context V7 to the Master Trader;
- create a trading gate or execution path;
- add position sizing, account risk, broker/follower state or Super Signals coupling;
- claim predictive edge or profitability.

Gateway/prompt promotion requires a later explicit integration gate after this decision contract has
been accepted.

## Acceptance

Day 33 must pass changed-file Ruff, focused adversarial V2 tests, full repository regression and a
deterministic exact-head acceptance artifact. Acceptance proves all four representative V2 actions,
V1 historical readability with no silent upgrade, strict schema closure, true/false/UNKNOWN machine
condition semantics, immutable deterministic decision digests and the unchanged non-execution/safety
boundaries above.
