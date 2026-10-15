# Day 34 — B09 GoldThinker review-only evidence handoff

**Locked owner requirement:** Export evidence-qualified AIDY candidates for **separate Claude and owner review**. **PASS:** no auto-trading, no live promotion. Customer subscriptions, paper accounts, GoldThinker naming and Elite 20 remain separate future features.

## Actual engineering

`src/aidy/strategy_lab_goldthinker_handoff.py` provides a typed, immutable review-only proposal. Every potential proposal must trace to the original unchanged strategy rules/source, matched baseline, independently costed trade ledger, chronological OOS trial registry, nine original Day28 verified factor reviews and a positive meaningful net-of-cost advantage. The actual Day28 nine-factor scorer is REPLAYED rather than trusting a claimed "GREEN" flag. Review rights must be separately verified. In addition, original evidence is authenticated through an INTERNAL HMAC-SHA256 receipt signed by a trusted private research issuer; a customer cannot send `verified=true` or a made-up hash and release a strategy.

**Trust boundary:** This is a source/handoff POLICY consumer, not an independent strategy executor or trusted independent benchmark verifier. The privileged issuer that validates genuinely authenticated source inputs is NOT implemented here; the HMAC key and actual issuer must remain isolated from uploader services. Production pipelines must NOT call `issue_internal_receipt` on user-supplied qualification flags. Positive-path unit tests use transparently hypothetical fixtures and local nonproduction test keys only; none of those qualified-looking test inputs establishes an actual profitable XAUUSD strategy. Real Stage-B10 customer input/tenant safeguards and sandboxing are separate future days.

A qualified, internally attested future entry MAY be exported for **PENDING Claude review / PENDING owner review** only. Every packet and record has exact source/run/rules/trial/ledger/benchmark hashes and deterministic packet SHA; all customer joins, trading, broker orders, auto-paper production, auto-live promotion, GoldThinker naming and Elite20 allocation are **FALSE / null**. Paper production is only a later separately owner-approved prospective step after actual source/rights validation. Any test fixture, ORANGE/RED evidence, missing cost/OOS/baseline trial, nonpositive returns, unmatched SHA, uncertain strategy rights or invalid HMAC is excluded. No strategy is silently optimised.

`scripts/strategy_lab/day34_private_handoff_acceptance.py` calls **real Day33 acceptance**: owner Drive 83-candidate source snapshot, genuine read-only XAUUSD BID-only historical archive replayed twice via BigQuery, and two completely independent synthetic 100-job research queue runs. The actual result has **zero research-qualified systems**; all 83 original candidates are STILL UNTESTED. The 100 queue jobs are not 100 strategy performance results. Day34 then produces these real machine-readable owner audit outputs:
- `artifacts/strategy_lab/day34/handoff_for_separate_owner_and_claude_review.json` — empty qualified review queue, explicitly **NO DEPLOYMENT** and all operations blocked.
- `artifacts/strategy_lab/day34/source_candidate_blockers.json` — actual 83 source candidates and individual missing-evidence blockers (read only; no profitability testing).
- `artifacts/strategy_lab/day34/review_checkpoint.md` — required future separate Claude/owner review checklist and explicit absence of approved paper accounts.
- `artifacts/strategy_lab/day34_handoff_acceptance.json` — source/provenance SHA, real BigQuery job IDs, acceptance status and exact 83/0 counts.

`.github/workflows/strategy-lab-day34-handoff.yml` independently tests forged customer source/ratings, altered source HMAC, fixture policy, negative expectancy, missing licence/rights, duplicate or overlimit proposals, attempted premature GoldThinker system name/publication/broker controls and original Day28–33 regressions. CI reruns the **real** 83-candidate + historical source evidence, not merely mocked acceptance, before recording Day34 as a scoped technical pass.

## Scope and owner sequencing

We are **NOT testing any of the 83 collected strategies for profitability** before completion of all 40 builds and the laboratory-wide audit. Original Day34 is only the **handoff safety wall** ready for qualified research later. AIDY is the laboratory engine, GoldThinker is the future customer-facing brand. A real qualified strategy would first need separate owner-reviewed FORWARD PAPER production, then sustained production pass and rights confirmation, then naming, public individual offers, and optional independent eligibility for the **one-account** GoldThinker Elite20 portfolio. No 20-strategy auto-allocation or connected customers today.

## Final evidence

**PENDING CI + protected-main merger.** Fill verified actual PRs/test run IDs, original source digests and owner Notion tracker only after green full acceptance.
