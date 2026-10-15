# Day38 — B11 compute billing and entitlements — PARTIAL / EXTERNAL PAYMENT BLOCKED

**LOCKED OWNER PASS:** Meter usage, plans/credits, owner billing exemption, **real sandbox payment** and owner free-access test. The real sandbox requirement cannot be replaced by an invented webhook or synthetic paid flag.

## Implemented and verified only as internal module

- src/aidy/strategy_lab_compute_entitlements.py: tenant-authenticated monthly UTC compute unit meter; finite per-tenant cap; atomic BEGIN IMMEDIATE updates; SHA-bound source job usage idempotency; conflicting replay rejected; no cross-tenant unit leakage; internal private plan name; trusted admin grants only; private per-tenant usage summary.
- Explicit owner BILLING exemption does not remove compute caps, independent evidence qualification or privacy; no automatic customer role or owner flag. Service/admin and scheduler keys independent of Day36 secrets.
- No prices, payment link, paid state, currency-charged record, provider charge or real subscription may be set by this module. All early records are explicitly PREVIEW_INTERNAL; cannot mark a simulated receipt as real payment.
- tests/test_strategy_lab_compute_entitlements.py covers owner cap, guest isolation, cross-tenant job IDs, same-job idempotence, conflicts and rejected invalid units, session revocation, admin/scheduler secret forgery, monthly accounting and forced paid-flag rejection.
- scripts/strategy_lab/day38_billing_preview_acceptance.py generates a real executed synthetic owner exemption/usage proof and explicitly returns status PARTIAL_EXTERNAL_PAYMENT_BLOCKED.
- Dedicated GitHub CI tests Day28–37 regressions and reruns original read-only gold historical archive twice. Original 83 candidates remain completely untested.

## Required to finish Day38 — not waived

1. Owner approval of an appropriate merchant/test-mode payment provider, authorised integration and sandbox configuration. Stripe was discovered as an optional connector; it is **not connected or approved** merely by displaying an option. No test credentials are ever requested in chat or committed.
2. Build authenticated server-side checkout/session initiation and webhook signature verification bound to the actual provider's API and chosen products. Use unique request idempotency, explicit tenant relation, asynchronous payment state machine, invoice/refund/dispute handling, no trust in client-supplied paid flags.
3. Actually perform and independently verify a provider **test-mode** transaction or subscription lifecycle, receipt/charge ID, webhook identity, status, cancellation and reconciliation. Verify owner billing-exempt path using the same underlying research engine, not exemption from research or compute safety.
4. Agree plans, entitlements, spend ceilings, free-credit and retention terms only after real measured infrastructure unit costs and owner approval. Legal/tax/merchant obligations reviewed separately.

**Verdict:** Engineering preview meter can pass its own tests, but original Day38 is **NOT PASSED**, B11 stage NOT ACCEPTED, public pricing NOT CONFIGURED, real sandbox payment NOT RUN. No real customer subscription, independent performance claims or trading product launch. This cannot be counted as one of the 40 completed days.

## Evidence

- Source PR: PENDING
- CI, actual source replay, synthetic unit tests: PENDING
- Actual provider sandbox transaction: BLOCKED pending provider connection and owner approval
- Protected-main isolated code merge: PENDING
- Full Day38 PASS / owner stage acceptance: NOT CLAIMED
