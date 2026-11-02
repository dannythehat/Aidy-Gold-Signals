# MT5 runner Ed25519 keys

Procedure only. Do not put a private key, a seed, or a key file in this repository or on a shared machine.

The Windows research runner is the only place that holds the private key. `config/goldthinker_factory_runner_trust.json` stores public keys: `runner_id`, `key_id`, and `ed25519_public_key_hex`, plus `revoked_key_ids`. The committed file lists no runners and no revoked ids. This repository does not mint a `RUNNER` attestation. `sign_attestation` rejects that provenance class. A runner attestation is produced on the runner, with a launch/exit receipt and the tester journal.

## Generate

On the runner, in a private directory that is not synced and not committed:

```
python -c "from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
k = Ed25519PrivateKey.generate()
open('runner-ed25519.private','wb').write(k.private_bytes_raw())
open('runner-ed25519.public','wb').write(k.public_key().public_bytes_raw())
print(k.public_key().public_bytes_raw().hex())"
```

Copy only the printed public hex into a reviewed change of the trust store, with a new `key_id` and the runner's `runner_id`. Restrict the private file to the runner account. The runner signs each year's attestation with that private key. The signature covers `system_id`, a unique `nonce`, and `issued_at`, plus the SHA-256 of the report, ledger, EA, ini, inputs, broker profile, data source, tester journal, and launch/exit receipt, and the terminal build, timestamps, and year. The journal text has to name the same EA, ini, report, year, and build that the signature names. The launch receipt has to name the same start, exit, exit code, year, and build.

## Rotate

1. Generate a new key pair on the runner. Choose a new `key_id`.
2. Add the new public key to the trust store. Leave the old public key in place until in-flight runs signed by it are no longer accepted.
3. Point the runner at the new private key. New attestations use the new `key_id`.
4. Remove the old public key from the trust store in a later reviewed change. Delete the old private file on the runner.

To revoke a key before that removal, add its `key_id` to `revoked_key_ids`. Verification rejects a revoked id even if the public key is still listed. Do not reuse a revoked id.

If a private key is copied off the runner, treat it as compromised: stop using it, add its `key_id` to `revoked_key_ids`, remove its public key, and generate a replacement. Do not commit either file.

A signature that checks out against this store is still self-reported. Nothing in this repository observes the Windows runner, so verification leaves `verified` false. Selection then stops at `RUNNER_SIGNED_SELF_REPORTED_PENDING_VERIFICATION` or `BLOCKED_REAL_MT5_PROVENANCE`. It does not emit `SELECTED_PENDING_INDEPENDENT_EVIDENCE`.
