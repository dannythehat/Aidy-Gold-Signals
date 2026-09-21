# AIDY Memory

Last updated: 2026-09-21

This is the root repo-memory pointer for AIDY's current live Gold-learning architecture.

**Authoritative detailed handoff:** `docs/current-gold-learning-state.md`

Read that document before changing:
- Gold cycle learning;
- cycle-start environment construction;
- contextual marker scoring;
- Gold movement learning;
- toolbox availability/usage;
- Provider Context;
- Cloudflare scheduled capture.

## What is live

AIDY's Gold learner now separates **facts known at cycle start** from **directional marker opinions**.

Before each eligible 15-minute target window, AIDY freezes a PIT-safe environment containing the factual state available at that decision time, including where available:
- session and session phase;
- completed M5/M15/H1/H4/D1 structure;
- recent 5m/15m/60m path;
- Gold price location relative to prior-day, Asia, active-session and opening-range references;
- distance/side relative to nearby structural and liquidity references;
- liquidity sweep/reclaim and breakout/reclaim state;
- realised-volatility/jump regime;
- scheduled-event timing/proximity;
- known cross-market availability;
- compound regime;
- explicit unknowns.

Exact prices/distances are retained for audit. Learning uses repeatable condition buckets so comparable environments accumulate meaningful samples.

The cycle brain then:
1. inspects the full canonical toolbox;
2. creates directional markers only where evidence legitimately supports a vote;
3. retrieves marker performance under the current environment;
4. applies bounded learned trust;
5. freezes AIDY's 15-minute view and reasoning;
6. waits for complete forward evidence;
7. scores the view and each marker;
8. updates environment-specific scorebooks.

## Scoring

Marker impact scores:
- +2 large correct move;
- +1 normal correct move;
- 0 unavailable/unscoreable;
- -1 normal incorrect move;
- -2 large incorrect move.

Current large-move threshold: `abs(realised 15m return) >= 5 bps`.

Plain accuracy is stored separately. Learned marker multipliers are bounded to 0.5x-1.5x and require sample depth before narrow environment scopes can dominate.

## Why this was built

A tool should not be labelled simply good or bad.

An M15 bearish marker near open space is a different setup from M15 bearish after a downside liquidity sweep/reclaim while H4 remains bullish. AIDY therefore learns **which evidence is trustworthy under which Gold environment**.

The intended long-term result is an auditable "impression brain":

`environment -> toolbox markers -> contextual trust -> view -> outcome -> per-marker learning -> improved future trust`

## Live deployment evidence

Successful canonical deploy run:
`35563762596`

Worker version:
`bf2baa31-ca7c-4c2a-8866-8945bc6bac6d`

Verified live versions:
- Gold cycle memory: `aidy_gold_cycle_memory_v3`
- cycle environment: `aidy_gold_cycle_environment_v2`
- contextual marker brain: `aidy_gold_contextual_marker_brain_v2`
- toolbox manifest: `aidy_gold_toolbox_manifest_v1`

The live 05:00 UTC cycle audit showed:
- bearish observed state;
- bearish AIDY view;
- reasoning present;
- 4 supporting reasons;
- 1 contradiction;
- 6 unavailable evidence items;
- **34 toolbox capabilities considered**;
- 4 directional surfaces used;
- future values used = 0;
- live-money execution allowed = 0.

## Permanent boundaries

Do not silently change:
- Super Signals execution;
- MetaAPI / MT5 / Vantage;
- owner risk rule: **1% per trade**;
- provider activation/best-side rules;
- formal-forward/live-money authority.

Formal forward remains OFF unless separately and explicitly graduated.

## Build completion rule

A Gold-learning build is not complete until:
1. implementation is merged;
2. tests/regression are green;
3. Cloudflare deployment is verified;
4. minute cron/health are verified;
5. repo-local memory is updated;
6. the separate `dannythehat/Memory` handoff is updated and reread.
