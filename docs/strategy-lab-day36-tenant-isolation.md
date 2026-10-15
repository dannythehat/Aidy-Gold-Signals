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

## Acceptance status

Scoped Day36 completion remains **PENDING** until actual GitHub CI, original real history/source checks, evidence gate and protected-main merge can be verified. A synthetic two-user local implementation does not automatically establish a secure public beta or complete owner-accepted B10 stage.

- Implementation PR: PENDING
- Original CI / merged SHA: PENDING
- Real customer hosted penetration test: NOT RUN
- Owner stage acceptance and public deployment: NOT APPROVED
