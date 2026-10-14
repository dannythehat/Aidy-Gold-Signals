# Day 06B — live Cloudflare metadata evidence

Date 2026-10-14. [Successful read-only Actions run](https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/38521220767).

The Cloudflare token listed two relevant bucket names: `aidy-memory-test` and `aidymemory`. This is **bucket catalogue metadata**, not contents or completeness of either bucket.

A read-only SQL aggregate against `aidy-ops-test.archive_outbox` found **85,662 archived entries with `gold/` key prefixes**. Earliest entry 2026-08-17T04:53:19.998Z; latest 2026-10-14T06:13:08.240999Z. This is the operational archive ledger, not a raw tick count. Some keys may point to snapshots, events, candles or research artefacts. Individual object access was previously proven for one existing snapshot; no complete R2 listing has been executed.

**What remains unknown:** paginated object inventories of both R2 buckets, objects outside D1 outbox, actual full tick ZIPs, total storage bytes by prefix, broker data on Windows/OVH and licensing. The full cross-storage audit remains PARTIAL.
