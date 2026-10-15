# Days 39–40 hardening — source-linked security continuation (15 October 2026)

**Problem fixed:** the previous Day40 checklist would produce `status=GO` from caller-supplied `{all ten gates: true}`, even though these claims were not independently verified. A hypothetical test was erroneously capable of creating a GO *label*. This release strictly returns `NO_GO` and explicitly counts true values as unverified assertions until a separate trusted real-provider/owner/legal source verifier is implemented. No text/boolean submitted by an untrusted customer can promote a candidate, authorise customer billing or enable trading.

**Actual new recovery engineering:** private AES-256-GCM encrypted SQLite snapshots with unique nonces, authenticated version tag, bound in-memory SQLite `backup/serialize` and integrity check. No plaintext intermediate backup is written to disk. Target snapshot files are created exclusively with mode 0600 on POSIX and never overwrite an existing path. `restore` decrypts and verifies checksum and SQLite integrity before writing to a separately designated new DB. Different backup keys and tampering fail closed. Separate synthetic test tenants are restored and access-checked with individually authenticated sessions.

**Actual cross-runner CI proof:** two independent ephemeral GitHub Actions machines transport only the encrypted **SYNTHETIC** fixture as a named remote GitHub artifact; the second runner downloads, decrypts, restores and checks both tenants, including cross-tenant denials. Fixed synthetic test keys are never suitable for production customer data. The resulting evidence must clearly state `production_remote_restore_certified=false`: this is an honest remote-transport rehearsal but NOT a real recovery drill against cloud-hosted AIDY customer records, managed secrets, KMS, backups or recovery time objectives. Existing `local_sqlite_backup` is limited to non-production isolated work and creates plaintext output; it is not an approved production backup method.

**Original acceptance remains blocked:** No Stripe/other payment account connected and no actual sandbox charge; Render workspace is unselected, the only visible Supabase project is an unrelated inactive Super Signals preview, so neither may be treated as an AIDY production environment. No qualified legal/IP/data rights review, independent penetration test, commercial infrastructure recovery, owner acceptance of Day03/06 and B00–B11 stages, or real consenting customer pilot. Original 83 strategy candidates remain untested until all original programme gates and final audit, as owner instructed.

The status of Day38, Day39 and Day40 remains PARTIAL/PARTIAL/NO_GO after these safety improvements. Do not label the entire 40-day programme complete.

## Acceptance evidence

- Hardening PR: pending final strict CI and protected-main merge
- Day40 forged all-true checklist: MUST be NO_GO
- Day39 encrypted local 2-tenant roundtrip and tamper tests: MUST PASS
- Day39 separate-runner encrypted synthetic artifact drill: MUST PASS; production remote restore false
- Original gold BID BigQuery immutable source double-read: MUST PASS; 83 candidates untouched
