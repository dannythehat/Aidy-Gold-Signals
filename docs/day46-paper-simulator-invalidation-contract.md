# Day 46 — Deterministic paper simulator and invalidation evaluator

## Authoritative base

Day 46 starts from merged Day 45 `main` at `0b413c23eb5b720bce227bb62ca35787855fb81d`.

## Purpose

Day 46 creates a paper-only lifecycle for an admitted Master Trader V2 `new_trade` decision. It does not execute, publish or size a trade. The simulator exists so later watcher and management intelligence can observe a deterministic position state while research separately records whether the original falsifiable thesis was invalidated.

## Frozen contract

- Only a valid immutable Day 34 ex-ante ledger record with `cycle_disposition=decision_admitted` may open a position.
- The decision must use the falsifiable Master Trader V2 contract and action `new_trade`.
- Existing V1 trade geometry remains authoritative: XAUUSD market reference, one stop and one to three ordered targets.
- Market observations are chronological, point-in-time snapshots. Future/outcome/evaluation-only fields and broker/account/follower execution state are rejected.
- Duplicate identical observations are idempotent. A conflicting observation at an already-seen timestamp fails closed.
- Multi-target progress is deterministic. Each target represents one equal paper slice; realized performance is reported in R units only, never account currency or lot size.
- State history is digest-bound and append-only. Serialized state must round-trip exactly and a restarted run must reproduce the same state as uninterrupted replay.
- The Day 33 machine-evaluable invalidation condition is evaluated on every PIT observation. Missing/type-incompatible evidence remains UNKNOWN.
- Thesis invalidation is recorded independently from the economic position lifecycle. It cannot silently close the paper position or rewrite the original thesis.
- Final trade economics and thesis-validity outcomes are separate sections of the paper outcome payload.
- Final outcomes attach through the immutable Day 34 outcome-attachment mechanism and cannot mutate the ex-ante decision record.

## Explicit prohibitions

Day 46 has no broker, MT5, MetaAPI, Vantage, account, follower, Telegram or Super Signals authority or dependency. It creates no formal forward evidence and makes no predictive-edge claim. Formal private forward paper evidence remains a Day 53 boundary.

## Acceptance

Day 46 passes only if:

1. long and short one-to-three-target lifecycles are deterministic;
2. partial target then stop accounting closes only the remaining paper slices;
3. restart/restore replay is byte-identical to uninterrupted replay;
4. state-history tampering and timestamp conflicts fail closed;
5. PIT violations, outcome leakage and account/execution fields fail closed;
6. invalidation TRUE/FALSE/UNKNOWN semantics are retained without changing trade state;
7. a profitable trade can still record an invalidated thesis, proving economic and thesis outcomes are structurally separate;
8. outcome attachments verify against the original immutable ex-ante digest;
9. focused Day 46 tests and the full repository regression pass; and
10. deterministic acceptance artifacts are byte-identical across two independent runs.
