# Day 14 — No-Trade Counterfactual v1 Contract

## Purpose

Day 14 evaluates future `no_trade` decisions without teaching AIDY hindsight bias.

A Gold move after a `no_trade` decision is **not** evidence that the decision missed a trade. A record may be labelled `missed_opportunity` only when a versioned contemporaneous setup assessment says a setup was present, its structural risk geometry was valid at the decision timestamp, and the later price path produced a deterministic target-before-stop outcome.

This layer is research/evaluation only. It is not a runtime decision input and it does not create setup truth.

## Versions

- setup eligibility adapter: `aidy_no_trade_setup_eligibility_v1`
- counterfactual record: `aidy_no_trade_counterfactual_v1`
- distribution: `aidy_no_trade_counterfactual_distribution_v1`
- horizons: 15, 60 and 240 minutes
- primary classification horizon: 240 minutes

## Critical Day 15 boundary

Day 14 does **not** define the Gold setup taxonomy and does **not** detect setups.

Day 15 owns the versioned setup taxonomy and deterministic PIT-safe candidate-setup detector. Day 14 defines only the interface that later Day 15 evidence must satisfy.

Until a saved or deterministically reconstructed Day 15 assessment exists for a real decision timestamp, price movement after that timestamp cannot retrospectively create a valid setup. Such cases remain `indeterminate`.

## Contemporaneous setup eligibility evidence

`aidy_no_trade_setup_eligibility_v1` is PIT-safe evidence and therefore carries:

- `pit_eligible=true`
- `future_derived=false`
- `decision_input_allowed=true`
- exact `as_of_utc`
- taxonomy version
- detector version
- source Day 10 context hash
- source Day 11 regime digest
- setup state
- risk state
- candidate setup identifiers
- direction when known
- market-entry trade geometry only when setup is present and risk is valid
- stable reason codes
- SHA-256 evidence digest

The setup evidence timestamp must exactly match the `no_trade` decision timestamp.

The source context/regime digests establish the contract for later Day 15 evidence. Day 14 does not claim that manually constructed fixture evidence is historical truth.

### Setup states

- `present`
- `absent`
- `ambiguous`
- `unknown`

### Risk states

- `valid`
- `invalid`
- `unknown`
- `not_applicable`

A `present` setup may have valid, invalid or unknown risk evidence.

An `absent` setup has no direction or trade geometry and uses `risk_state=not_applicable`.

An `ambiguous` setup keeps direction/risk unresolved and requires at least two candidate setup identifiers.

An `unknown` setup keeps direction/risk unresolved.

## Candidate trade geometry

Day 14 v1 supports only market-entry candidate geometry:

- `entry_type=market`
- entry
- mandatory stop loss
- one to three ordered targets

The market entry must equal the decision-time anchor price.

Day 14 does not use balance, equity, margin, follower state, broker state, MT5, MetaAPI or position sizing. Risk evidence here means valid price geometry only.

## Future path evidence

Every counterfactual record always builds Day 12 Move Detective labels at:

- 15 minutes
- 60 minutes
- 240 minutes

When setup is `present` and risk is `valid`, Day 14 also builds Day 13 trade-outcome labels over the same horizons.

Future evidence remains:

- `evaluation_only=true`
- `future_derived=true`
- `pit_eligible=false`
- `decision_input_allowed=false`

The Day 14 record is available only after the 240-minute horizon because it contains all three future windows.

## Classification rules

Classification is deterministic per horizon.

### Missed opportunity

Allowed only when all are true:

1. setup state was `present` at decision time
2. risk state was `valid`
3. market-entry trade geometry was valid and anchored to the decision price
4. the future horizon is complete
5. Day 13 proves `target_before_stop` or `target_only`

Reason: `valid_setup_target_before_stop`

Directional movement, MFE, terminal return or a later rally/selloff alone can never create this label.

### Good restraint

Produced when:

- setup state was `absent`
  - `no_valid_setup_at_decision`
- setup was present but structural risk was invalid
  - `risk_invalid_at_decision`
- valid setup/risk existed but Day 13 proves stop before any target
  - `valid_setup_stop_before_target`

A later move does not punish an `absent` or risk-invalid setup.

### Indeterminate

Produced when:

- setup evidence is `unknown`
- setup evidence is `ambiguous`
- risk evidence is `unknown`
- future horizon is incomplete
- stop and first target occur in the same M1 bar and intrabar order is unknowable
- valid setup/risk exists but neither stop nor target provides a decisive outcome
- future outcome state is otherwise unknown

Indeterminate is a first-class result, not an error to be forced into a win/loss label.

## Intrabar ambiguity

Day 13 OHLC ambiguity policy remains authoritative.

If stop and first target are first observed in the same M1 bar, Day 14 returns:

`indeterminate / stop_target_same_bar_order_unknown`

Day 14 never invents an intrabar sequence.

Simultaneous multiple targets do not by themselves invalidate a `missed_opportunity` classification if at least one target is deterministically before the stop.

## Physical separation

The schema contract is named:

`research_no_trade_counterfactuals`

This is a schema contract only. Day 14 does not claim a new BigQuery table was provisioned.

The contract contains no `first_observed_at` decision-time field and every record is explicitly non-PIT. Passing a Day 14 record into the Day 10 signal-lifecycle input is rejected.

## Determinism and integrity

Setup evidence and counterfactual records have canonical SHA-256 digests.

Inputs are normalized so ordering of:

- research candle rows
- candidate setup identifiers
- reason codes

does not change the resulting record.

Tampered evidence or counterfactual records fail validation.

## Acceptance fixtures

The Day 14 gate covers:

- large future move after absent setup => `good_restraint`
- same future move with unknown setup => `indeterminate`
- ambiguous setup => `indeterminate`
- valid long setup + target before stop => `missed_opportunity`
- valid short setup + target before stop => `missed_opportunity`
- valid setup + stop before target => `good_restraint`
- same-bar stop/target => `indeterminate`
- valid setup with no decisive level outcome => `indeterminate`
- incomplete 4h future path => `indeterminate`
- present setup with invalid risk => `good_restraint`
- present setup with unknown risk => `indeterminate`
- timestamp mismatch and non-market geometry rejection
- future-field injection rejection even after re-hashing
- deterministic output under row reordering
- physical research/PIT separation
- Day 10 leakage rejection
- tamper-resistant distribution/storage

## Explicit non-claims

Day 14 does not claim:

- that a setup existed historically unless contemporaneous detector evidence proves it
- that future direction itself means a trade was missed
- realized P&L
- broker fills
- execution quality
- causal explanation
- strategy profitability
- account-level risk or sizing
