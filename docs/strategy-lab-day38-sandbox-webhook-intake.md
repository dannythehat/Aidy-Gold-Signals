# B11 Day38 — optional signed sandbox event intake (engineering partial)

**Status: ENGINEERING FIXTURE ONLY. The original Day38 remains BLOCKED.**

A disabled-by-default optional Stripe-style test-mode signed Checkout webhook receipt journal is now available at `src/aidy/strategy_lab_sandbox_payment_intake.py`. **Stripe is a possible technical adapter, not an owner-selected or approved merchant.** No Stripe connection, API request, checkout creation, provider-produced sandbox payment, billing terms, subscription activation, or public website deployment has occurred.

## Implemented

- Require an authorised operator to pre-register a known `cs_test_` Checkout Session against an existing Day36 tenant ID in the isolated private SQLite registry; session registration is **not** evidence the provider created it.
- Verify an *unmodified raw-body* timestamped `t`/`v1` HMAC-SHA256 event signature against a separately supplied endpoint signing secret; enforce five-minute tolerance and reject forged, old or future timestamps.
- Accept only `checkout.session.completed`, with both event and session `livemode=false`, correct tenant metadata, registered test session, and payment status `paid`. Reject unknown or conflicting tenants, invalid IDs, duplicates in JSON, altered event IDs, additional completions, unsupported events and oversized payloads.
- Store test-event digest, event/session/tenant binding and `SIGNED_TEST_EVENT_UNRECONCILED` status transactionally; atomically deduplicate retries. Secret keys are never stored in DB.
- Return `actual_provider_delivery_verified=false`, `provider_api_reconciliation_verified=false`, `paid_access_unlocked=false`, `original_day38_passed=false`, `public_launch_allowed=false`. Do not alter `ComputeEntitlements.try_mark_paid()`. No broker, customer or live payment actions.

**Security limitation:** A synthetic test fixture can be HMAC-signed locally. Passing those tests does not prove real Stripe event delivery, charge, invoice, entitlement, refund, tax or subscription lifecycle. Future financial privilege must require independent provider API reconciliation, owner-selected products and a separate reviewed production implementation.

## Scope that remains genuinely missing

1. Owner choice/approval of actual merchant and test account; plans, pricing, VAT/tax/legal framework and legitimate commercial-source data rights.
2. Real authenticated server-side checkout creation, configured secret storage and TLS webhook endpoint, secure payout/account lifecycle, cancellation/refund/invoice workflows and rate-limited hosted deployment.
3. **Actual** completed two-customer sandbox test purchase/subscription, test provider receipts, independent API reconciliation, owner billing exemption, owner approval and fully verified B11.
4. Day39 production remote restore/incident/security/legal sign-off, Day40 consenting customer pilot, and Day03/06 formal acceptance remain outstanding.

## Tests

Run `PYTHONPATH=src python -m pytest -q tests/test_strategy_lab_sandbox_payment_intake.py` and the dedicated pull-request CI. Tests use local fake signing secrets and fake Stripe-shaped events only. None contacts a payment account or grants financial privileges.

Reference: [official Stripe guidance](https://docs.stripe.com/events/manage-webhook-endpoints#signature-errors): raw request body and endpoint-specific signing secret must be used for verification.
