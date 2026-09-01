# Day 52 — End-to-end fidelity, restart and reconciliation

Day 52 connects the previously accepted AIDY components into one standalone provider runtime without starting Day 53 forward-performance evidence.

## Runtime paths

### New market evaluation

`PIT context -> Context Composer V2 -> k=3 falsifiable Master Trader V2 -> deterministic safety -> immutable Day 34 ex-ante record -> Day 46 paper position -> Day 50 provider envelope -> Day 51 durable delivery ledger`

The V2 runtime is additive. Historical V1 gateway, safety and self-consistency contracts remain unchanged and readable. Current runtime decisions use the falsifiable V2 contract required by the paper simulator and Master Watcher.

### Active signal management

`fresh PIT context -> Context Composer V2 -> Master Watcher -> k=3 falsifiable Master Trader V2 -> Day 48 management validation -> immutable Day 34 management ex-ante record -> paper-management state transition -> Day 50 provider update -> Day 51 durable delivery ledger`

The Watcher never publishes or executes. Day 48 still must validate the exact originating decision ID, immutable original thesis/invalidation, current watcher reason and risk-reducing geometry before a management decision can become an admitted provider update.

## Durable restart journal

Cloudflare D1 migration `0004_end_to_end_cycles.sql` records one deterministic cycle identity per instruction/source/subject/context. It stores exact immutable artifacts rather than re-generating them:

- k=3 self-consistency result and digest;
- Day 34 ex-ante JSON, digest and decision ID;
- opening paper state and digest;
- watcher receipt and digest;
- Day 48 management action and digest;
- Day 50/51 publication ID and final orchestration state.

A restart with an existing ex-ante record reuses that record. It does not call OpenAI again. An already-sent publication returns the stored identity without calling Telegram again. A publication with uncertain delivery remains blocked by the Day 51 reconciliation rule.

If a restart occurs after the decision is durable but before publication, the exact stored decision may resume publication only while its original context remains fresh and the decision remains unexpired. A stale or expired decision fails closed instead of being posted late.

## k=3 abstention semantics

When k=3 has no safe semantic majority, Day 52 records the complete three-sample self-consistency result and stops. It does not invent a synthetic model `no_trade` decision merely to satisfy the Day 34 schema. A real majority `no_trade` is ledgered normally and never published.

## Paper management continuity

Day 46 predates management and defines opening/market-observation paper state. Day 52 therefore adds a bounded paper-management adapter for accepted Day 48 actions:

- `manage_trade` can deterministically update the active paper stop/remaining targets while retaining a verifiable Day 46 state and immutable original thesis;
- `close_trade` creates a terminal management-close record rather than pretending it was a target or stop closure;
- a terminal management close cannot be watched again.

This keeps management semantics explicit without rewriting the accepted Day 46 historical contract.

## Publication boundary

Only `source_state=live_admitted` with explicit publication enablement can reach the Day 50 envelope. The following states can never reach Telegram even if a caller mistakenly asks to publish:

- `shadow`
- `replay`
- `dry_run`
- `private_forward`

`no_trade`, pre-model blocks, model failures, self-consistency abstentions, watcher holds/suppressions and invalid management actions also produce zero external publication.

Day 51 remains the final delivery authority. Normal retries are exactly-once; ambiguous network outcomes become `delivery_uncertain` and cannot blindly resend.

## Standalone boundary

Day 52 does not import or access broker, account, MT5, MetaAPI, Vantage, follower or Super Signals state. AIDY remains a signal provider only.

## Day 53 remains off

Day 52 is engineering and operational acceptance. It does not schedule the trading-intelligence runtime automatically, does not send a real Telegram message during CI, and does not create formal forward-performance evidence. Day 53 remains the explicit first formal private forward paper cohort.

## Acceptance

The exact candidate head must pass:

- static and import-boundary checks;
- focused Day 52 adversarial tests;
- full repository regression;
- one-to-one admitted-decision/publication identity assertions;
- restart with zero duplicate model decision and zero duplicate Telegram call;
- stale-context and model-outage fail-closed tests;
- no-trade and no-safe-majority tests;
- shadow/replay/private-forward leakage tests;
- watcher/management identity and state-continuity tests;
- deterministic A/B evidence output comparison.

Static-check defects discovered during Day 52 are corrected in source; acceptance rules are not relaxed or bypassed.

Only an exact-head green candidate may merge to `main`.
