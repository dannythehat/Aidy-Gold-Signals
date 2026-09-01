# Day 49 — management replay and do-nothing counterfactual

Day 49 measures management separately from entry quality. It does not assume an intervention is beneficial merely because one trade worked.

## Frozen benchmark

The counterfactual benchmark is `aidy_management_do_nothing_benchmark_v1`: replay the originating Day 46 trade with its original entry, stop and targets and apply **no watcher management actions**. The same market-observation sequence is used for both paths.

The benchmark identity is fixed before evaluation. Changing it creates a new experiment version rather than silently changing historical scores.

## Managed replay

The managed path starts from the same originating trade. At each timestamp the market observation is applied first, then any exact Day 48 management action tied to that same PIT context is applied. This order is deterministic and versioned.

- identical duplicate management action records are idempotent
- multiple different actions at the same timestamp fail closed
- actions without an exact same-timestamp/context replay observation fail closed
- actions after deterministic closure fail closed
- stop changes may only preserve/reduce risk
- replacement targets require an unambiguous one-to-one mapping to remaining paper legs
- state can be serialized/restored with a digest for restart testing

## Evaluation

Each completed episode reports two distinct objects:

1. **Entry quality** — the unchanged-trade outcome.
2. **Management quality** — the managed outcome and `managed R − unchanged R`.

A cohort report includes raw episode count, unique episode count, episode-independent/effective N, mean unchanged R, mean managed R, mean management delta R, and segmentation by regime and setup family.

Repeated episodes sharing one independence cluster count once toward effective N. The default sufficiency floor is 30 effective independent episodes. An insufficient cohort remains insufficient; the threshold is not lowered.

## Promotion boundary

Day 49 is an evaluation layer only. A single lucky intervention cannot promote a management rule, and even a sufficient cohort does not auto-promote. Promotion remains a later explicit architecture/owner decision.

No broker, account, follower, Telegram or Super Signals execution state is introduced. This remains paper-only and creates no formal forward-performance claim.
