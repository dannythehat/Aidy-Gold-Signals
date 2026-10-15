# Day37 — B10 private customer research result dashboard and authorised downloads

**Locked owner acceptance:** progress, saved tests, downloadable results, system versions/revisions, repeatable job and download access.

## Built

- src/aidy/strategy_lab_customer_results.py: trusted-only internal job creation bound to a previously server-revalidated Day36 tenant draft and its exact original source SHA; server derives client tenant from valid session on every read. Synthetic test job lifecycle has immutable SHA-linked chronological status events and fail-closed transitions. It cannot fabricate REAL independent profit validation.
- Customer job version increments for separate research submissions of the same source; job lists, event history and report attachments are tenant-filtered. Every attachment is encrypted with tenant/artifact-specific AES-GCM AAD; byte SHA-256 validated at download.
- Trusted internal issuer-only JSON, CSV and PDF artifact attachment path with MIME/extension/size restrictions, PDF header sanity, no unapproved reports while queued/running. Only BLOCKED, FAILED or SYNTHETIC_ACCEPTANCE_ONLY results are publishable in current implementation; no independent real-profit attestor is supplied.
- Repeatable private ZIP export with fixed dates, sorted filenames and canonical immutable research progress JSON; identical authorised requests produce identical bytes, while cross-tenant guesses fail identically.
- GoldThinker-branded responsive **offline** per-tenant HTML research snapshot. Safe output uses server-rendered escaped values; it is not a publicly hosted website. File downloads are fulfilled only by authenticated service calls, not links with guessable IDs.
- tests/test_strategy_lab_customer_results.py: two-user independent data isolation, original source hash gates, unpublished/forged privileged reports, status transition gates, immutable versions/events, no directory traversal, content rejections, tamper-proof encrypted blobs, expiry/logout and repeated SHA-stable downloads.
- scripts/strategy_lab/day37_results_access_acceptance.py: two synthetic users each submit identical synthetic private rules, receive independent BLOCKED reports, independently archive and reject six other-tenant read/export attacks; writes no sensitive identity or source to acceptance artifact.
- GitHub scoped workflow runs actual Day36, Day35 and prior independent research controls, plus two real read-only BigQuery XAUUSD BID archive replays and unchanged 83 original candidate source register.

## Non-negotiable security limitations

This is **an actual importable private research results service and HTML generator**, not a deployed customer SaaS site or payment/trading system. It has no HTTP API, public OIDC login, live worker queue, hosted authenticated downloadable link or independent third-party report attestor. The delivered tests intentionally use synthetic submissions with P&L null or blocked and NEVER classify them as real validated XAUUSD systems.

The original source, licence and runner qualification controls remain separate. A real secure deployment must add owned infrastructure/ingress, encrypted object store and backup policy, continuous authenticated access checks for every signed download, revocation and expiry, malware screening, request rate limits and auditable customer deletion before B10 full stage and any controlled pilot are acceptable.

No real customer has provided consent. Never infer GoldThinker live/paper trade capability, Elite 20, company revenue, research-qualified GREEN results, or subscription permission from this component. Do not test original 83 candidate strategies for profit until the complete 40-day build and owner audit.

## Evidence gate

Implementation source PR, test CI and semantic gate must all PASS and be merged to protected main before Day37 is called scoped technical pass. Stage owner acceptance / production deployment remain distinct.

- PR / merge: PENDING
- Scoped CI, total tests and actual source replay: PENDING
- Authenticated production customer HTTP portal: NOT BUILT
- Owner B10 stage approval: NOT GIVEN
