# AIDY Blind Gold Learning Exam

## Purpose

Measure whether AIDY becomes measurably better at understanding XAUUSD over time, rather than merely accumulating data. This is a research-only, forward/PIT-safe programme. It cannot alter broker execution, live-money authority, or Super Signals risk sizing.

## Non-negotiable rules

1. Every exam prediction is frozen before its outcome window begins.
2. Only evidence available at `evaluated_at_utc` may be used.
3. Learning cards become available only after their outcome is attached; the same episode can never retrieve its own learning card.
4. Historical numeric price levels from provider profiles are not execution evidence.
5. No active exam batch may be tuned after outcomes are revealed.
6. AIDY gets no credit for abstaining unless abstention itself was preregistered with an expected market state.
7. Improvement is evaluated on later unseen chronological batches, not on the training/history batch.

## Exam dimensions

Each eligible frozen episode should record, where supported by the contemporaneous context:

- market structure: bullish trend, bearish trend, range, mixed/uncertain;
- liquidity/session state: Asia, London, New York, overlap/transition, thin/maintenance/event-distorted where available;
- volatility state: contraction/low, normal, expansion/high;
- expected next behaviour: continuation, reversal, range persistence, breakout/expansion, failed breakout/sweep, uncertain;
- directional expectation: long, short, flat/uncertain;
- horizon: 15m, 30m, 60m, 240m where the frozen decision supports it;
- invalidation condition;
- calibrated confidence, if AIDY emitted one before the outcome;
- provider interaction: provider identity, direction, communication/management footprint, and PIT-safe conditional evidence when present.

## Difficulty ladder

- Level 1: ordinary session, clear structure, no major event distortion.
- Level 2: session transition or volatility expansion/contraction.
- Level 3: breakout versus false breakout, liquidity sweep, regime transition.
- Level 4: macro/event window or conflicting price/macro evidence.
- Level 5: provider disagreement/consensus combined with provider-specific conditional history and market state.

Difficulty must be assigned from frozen features, never from how dramatic the later outcome looked.

## Scoring

Score separate capabilities instead of one vanity accuracy number:

- direction accuracy for non-flat directional forecasts;
- behaviour/state classification accuracy when a preregistered class exists;
- Brier score for binary/probabilistic claims when confidence is present;
- calibration error by confidence bucket;
- realized R for admitted trade geometry where existing forward-outcome rules make it score-eligible;
- no-trade shadow directional result;
- provider-conditioned lift versus the same provider's unconditional baseline;
- regime-conditioned lift versus unconditional directional baseline;
- abstention rate and performance after abstention.

Never fabricate a score for a field AIDY did not actually predict ex ante.

## Learning test

Chronologically split score-eligible episodes into sequential unseen batches. The first eligible batch is the baseline. Later batches are evaluated only using learning available before each episode.

AIDY is `learning_observed` only if later unseen batches improve on preregistered primary metrics with adequate sample size. A growing number of learning cards is not evidence of becoming smarter.

Report four states:

- `insufficient_evidence`: not enough independent score-eligible episodes;
- `memory_accumulating`: outcomes/cards are growing but predictive improvement is not established;
- `learning_candidate`: later unseen performance is better but sample/significance gates are not yet met;
- `learning_observed`: preregistered forward improvement gates are met on unseen data.

A regression state must also be surfaced when later performance deteriorates materially.

## Provider coverage gate

Provider-conditioned claims require PIT-safe context coverage and minimum independent samples. Providers with sparse context remain `insufficient_evidence`; they must not be silently pooled into a flattering aggregate.

## Current production gap this programme is intended to expose

AIDY already stores immutable episodes, outcomes and learning cards. Provider Intelligence also stores behavioural fingerprints and market-context attachments. The blind exam must measure whether those memories and contexts improve later unseen decisions. If learning cards are merely stored/exposed but not used by the decision process, the result must explicitly say `memory_accumulating`, not `learning_observed`.

## Safety boundary

Research only. `live_money_execution_allowed=false`. No change to Super Signals' 1% live-risk rule. Any future promotion of learned behaviour requires a separate governed forward-evidence gate.