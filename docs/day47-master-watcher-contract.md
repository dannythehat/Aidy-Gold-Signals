# Day 47 — OpenAI Master Watcher contract

Day 47 adds the first **observation-only** OpenAI watcher for active AIDY paper signals. It does not add a new execution path and it deliberately does not finish the `manage_trade` / `close_trade` V2 action contract reserved for Day 48.

## Authoritative base

- Day 46 merged `main`: `512a397ca71ce49807e4046ee868ec09d4f3f467`
- Day 46 supplies the deterministic, restart-safe paper position state and immutable original thesis/invalidation snapshot.
- Day 35 supplies the verified counter-evidence-first hardened historical dossier.
- Day 33 supplies the falsifiable Master Trader V2 origin decision.

## Watched object

Only a verified Day 46 paper position in `open` or `partial` state can be watched. The watcher requires exact binding to the immutable ex-ante decision ledger record:

- originating AIDY `decision_id`;
- ex-ante digest;
- model-decision digest;
- direction and original entry geometry;
- original thesis;
- original expected horizon;
- original counter-argument;
- original machine-evaluable invalidation condition.

Closed paper positions fail closed before any model call.

## Fresh evidence gate

Each watcher cycle requires a fresh, authenticated PIT context:

- XAUUSD only;
- valid context hash;
- objective-only decision evidence;
- no retrospective-history payload in current context;
- no broker/follower state;
- `data_quality` present;
- Gold quote freshness explicitly `fresh`;
- context age no greater than **300 seconds**;
- context cannot predate the current paper state.

The historical dossier must be a valid Day 35 V2 dossier at the same timestamp and exact context hash. It must bind the exact paper position ID/state digest and retain counter-evidence, support evidence, uncertainty and invalidation inputs. `NO_COMPARABLE_CASE` remains valid evidence when honestly represented by the Day 35 dossier; missing or invalid historical evidence does not.

## Deterministic cadence and deduplication

Watcher cadence is frozen at **300 seconds** for Day 47.

A model call is suppressed when:

1. the exact combined watcher input has already produced an accepted watcher observation; or
2. a changed input arrives before 300 seconds have elapsed since the previous attempted watcher call for that position.

The watch-input identity hashes the immutable original decision/thesis, current paper-state digest, fresh context and hardened historical dossier. A changed context after the cadence is due can therefore earn a new observation while an unchanged state/context cannot generate repeated OpenAI cost.

Suppressed and blocked cycles log zero model calls and zero cost.

## OpenAI watcher output

The strict Day 47 output is an **observation**, not a Master Trader action. Allowed assessments are:

- `hold`
- `management_review`
- `close_review`

Allowed thesis assessments are:

- `intact`
- `weakened`
- `invalidated`
- `unknown`

Every observation must echo the exact position ID, originating decision ID, fresh context hash, paper-state digest and original-thesis digest. The schema has no `new_stop_loss`, `new_targets`, `close_scope`, lot size, risk sizing or account fields.

`management_action_emitted`, `publication_requested` and `execution_requested` are strict `false` values. Day 48 is the only planned gate allowed to convert a watcher observation into a validated `manage_trade` or `close_trade` V2 candidate.

## Thesis discipline

The original thesis and invalidation condition are immutable inputs. Day 47 can assess them but cannot rewrite them after observing price path.

Economic path and thesis validity remain separate concepts inherited from Day 46. A winning trade may have an invalidated thesis; an invalidated thesis may still require later Day 48 action validation. The watcher never treats either fact as automatic execution authority.

## OpenAI and cost boundary

The production adapter targets `gpt-5.6-sol` via the Responses API with strict Structured Outputs and `store=false`.

Every attempted model cycle records:

- model call count;
- provider attempt count;
- request/prompt/model identities;
- token usage when supplied;
- estimated USD cost;
- accepted observation digest or fail-closed reason.

Confidence is informational metadata only. It is not a safety gate and cannot control account risk, execution or publication.

## Side-effect boundary

Day 47 has no authority to:

- publish Telegram messages;
- execute MT5 orders;
- access a broker or follower account;
- access MetaAPI or Vantage;
- modify Super Signals;
- create formal Day 53 forward evidence;
- claim predictive edge.

## Acceptance

Day 47 passes only when the exact candidate head proves:

- static and compile checks pass;
- no execution integration is imported into the watcher module;
- focused adversarial watcher tests pass;
- the full repository regression passes;
- deterministic acceptance A/B artifacts are byte-identical;
- closed positions never call OpenAI;
- stale/missing/tampered evidence fails closed before calls;
- original thesis/invalidation mutation is rejected;
- duplicate input suppresses repeat calls even after cadence;
- changed input before cadence is suppressed;
- changed input after cadence can call once;
- calls, attempts and cost are logged;
- watcher output cannot smuggle Day 48 action geometry;
- publication/execution remain false;
- no formal forward evidence is created.
