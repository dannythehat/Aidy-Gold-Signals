# Day 48 — thesis-aware manage_trade / close_trade V2

Day 48 converts an accepted Day 47 watcher observation into a strictly validated paper-management action. It does not give AIDY broker authority and it does not publish anything.

## Required bindings

Every admitted management record binds all of the following identities:

- exact originating AIDY `decision_id` / `target_decision_id`
- immutable Day 34 ex-ante digest
- active Day 46 paper position ID and state digest
- accepted Day 47 watcher receipt and observation digest
- exact fresh PIT context hash used by the watcher
- immutable original thesis, counter-argument and machine-evaluable invalidation condition

A mismatch fails closed. Management cannot target another active AIDY signal.

## Watcher relationship

`manage_trade` requires a Day 47 `management_review` observation. `close_trade` requires `close_review`. The management decision must include the watcher thesis relationship (`thesis_intact`, `thesis_weakened`, `thesis_invalidated`, or `thesis_unknown`) and preserve at least one current watcher reason code.

The original thesis and invalidation condition are copied exactly from the originating V2 `new_trade`. They cannot be rewritten after seeing the price path.

## Geometry

Day 48 retains the existing V2 action language:

- `move_stop`
- `replace_targets`
- `move_stop_and_targets`
- full `close_trade`

A stop change may reduce risk only. For a long, the new stop cannot be below the current stop and must remain below current mid. For a short, the inverse rule applies. Replacement targets must remain on the profitable side of current mid, stay strictly ordered, and cannot create more remaining target legs than the active paper state currently has.

Day 48 records a deterministic projected transition. It does not mutate a broker position.

## Ledger

Every admitted action receives a deterministic `aidy_mgmt_*` ID and immutable ledger digest binding the originating decision, watcher evidence, current context, paper state, exact V2 decision and projected transition. Replays with the same evidence are idempotent; conflicting payloads under the same action identity are rejected.

## Hard boundaries

- paper-only
- no account sizing
- no broker, MT5, MetaAPI, Vantage or follower state
- no Telegram publication
- no Super Signals modification
- confidence remains metadata only
- no formal forward-performance claim is created by this engineering gate
