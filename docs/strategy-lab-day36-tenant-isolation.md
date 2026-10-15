# Day 36 — B10 authenticated private tenant vault (isolated scoped build)

**Original requirement:** authentication, secret protection, upload quarantine, retention, two-user isolation, adversarial security.

## Working implementation

- src/aidy/strategy_lab_tenant_vault.py: separate tenant and user identities, salted scrypt password derivation, 32-byte random server-issued sessions stored only as HMAC hashes, server-derived tenant principal, expiry and revocation, bounded password-failure lockout, trusted-only provisioning protected by an independent secret. Read/list/delete do not accept a client-supplied tenant ID.
- AES-GCM private authenticated encryption with fresh nonce and tenant/record-specific associated data. Encryption/session/provisioning keys are injected by a trusted server, never stored in SQLite. Database permissions restricted on POSIX.
- Inert client drafts revalidated with Day35 server-side validation and exact canonical JSON comparison. Maliciously rehashed authorisation flags, unknown rules, binaries and source mutations fail closed. Source text never executes, imports, fetches a URL, calls a broker or flows into Day34 HMAC evidence issuer.
- SQLite keeps tenant-scoped encrypted source, true source SHA, bounded expiry, deletion and privileged expiry purge. No real customer data used.
- tests/test_strategy_lab_tenant_vault.py: two-user independent and same-source isolation; forged token, SQL-shaped IDs, cross-tenant read/delete; encrypted-source exposure, ciphertext tampering; credential and privilege forgery; logout/session expiry, lockout, admin key/expiry failures.
- scripts/strategy_lab/day36_tenant_security_acceptance.py: synthetic two-user privacy proof, machine-readable SHA-256 acceptance, no secret bytes exported.
- GitHub workflow strategy-lab-day36-tenant-isolation.yml: strict Ruff and Python syntax, Day28-35 regressions, original real read-only BigQuery source replay twice, zero profit testing of original 83 strategies.

## Honest security/launch boundaries

This is an **importable locally isolated private service library**, NOT a public GoldThinker authentication website, deployed customer HTTP API, externally audited production IAM or strong OS-level sandbox for customer-supplied code. The upload quarantine consists of server-revalidated inert text encrypted in SQLite. Arbitrary Python/Pine/MQL execution remains entirely disabled. A future arbitrary-code engine requires microVM-grade or equivalent isolation, no secrets or networking, resource constraints and independent penetration testing.

Production requires separately deployed OIDC/MFA or equivalent identity, abuse/rate limits at ingress, independent secret store, key rotation, restricted backup/WAL handling and restore proof, malware scanning, encrypted backups, secure deletion policy, data rights, customer authorisation and operations monitoring. SQLite row deletion does NOT prove historical WAL/backup cryptographic erasure. A Day35 normalized UTF8-SIG upload cannot guarantee restoration of the original byte stream; it is rejected until a trusted original upload path preserves and hashes the exact submitted bytes.

No hosted customer tenancy, no real-money trading, no paper accounts, no AIDY-generated profitability verdicts, no customer billing, no verified third-party source rights and no GoldThinker Elite20 have been deployed. Keep all 83 original candidates untouched pending full programme plus independent audit.

## Audited scoped acceptance (15 October 2026)

**Original implementation CI PASS** at source head ca88f83fe7f7839c08ccf6ed37d96a7b3519503c:
- [Day36 actual security and source CI run 38723690441](https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/38723690441): **272 automated tests PASS**, strict Ruff and Python compile PASS, two-user synthetic private encrypted vault probe PASS, source-immutability acceptance PASS; actual original Day34 read-only BigQuery historical gold source replayed twice and original 83 Gold Edge candidates **NOT** profitability-tested.
- [Evidence Semantic Change Gate 38723690472](https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/38723690472): PASS.
- One initial attempt [38723557373](https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/38723557373) correctly FAILED strict lint for a typing import; it was corrected before this PASS.
- Unrelated broad Day53 worker/adapter checks on the same head returned **FAIL**, including a Python test-import/path collection failure in the worker workflow. They are NOT represented as passing, and must be tracked independently rather than changing unrelated production code under B10 scope.
- Original secure source SHA/P&L guards still report 83 untested strategies, 0 independently evidence-qualified, no paper/live/customer deployment. The two-user demonstration is synthetic test accounts only.

**Scope truth:** Dedicated original Day36 checks pass. This does not certify a production-hosted customer authentication service, actual malware sandbox, physical erasure from backups, multi-node ops, a live tenant service or completion of full B10 customer-product stage.

**PR:** [#302 — Day36 private tenant privacy build](https://github.com/dannythehat/Aidy-Gold-Signals/pull/302).
**Protected-main merge:** PENDING verification after final documentation CI.
**Owner B10 stage sign-off / launch:** NOT APPROVED.
