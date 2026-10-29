"""Confidential quote-cache transport; no plaintext market history in GitHub artifacts.

An ephemeral content key has two recipients: local research RSA public key,
and a context-separated HKDF wrapping key derived INSIDE CI from the existing
read-only GCP credential. The credential is never stored, exported or printed.
Future authorised CI can reuse snapshots without another source read. Source
evaluation steps receive no cloud credential. Key rotation fails closed.
"""
import argparse
import base64
import io
import json
import os
import tarfile
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

AAD = b"aidy-oracle83-private-history-cache-v1"


def ci_key():
    value = json.loads(os.environ.pop("AIDY_GCP_SERVICE_ACCOUNT_JSON"))["private_key"].encode()
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=AAD, info=b"snapshot-envelope-wrap").derive(value)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("mode", choices=("seal", "open-ci", "open-local"))
    p.add_argument("--source", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--key", type=Path)
    args = p.parse_args()
    oaep = padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=AAD)
    if args.mode == "seal":
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            for f in sorted(args.source.rglob("*")):
                if f.is_file():
                    tf.add(f, arcname=str(f.relative_to(args.source)))
        content_key, nonce, wrap_nonce = AESGCM.generate_key(256), os.urandom(12), os.urandom(12)
        public = serialization.load_pem_public_key(args.key.read_bytes())
        values = {"nonce": nonce, "wrap_nonce": wrap_nonce,
                  "ci_wrapped": AESGCM(ci_key()).encrypt(wrap_nonce, content_key, AAD),
                  "local_wrapped": public.encrypt(content_key, oaep),
                  "data": AESGCM(content_key).encrypt(nonce, buf.getvalue(), AAD)}
        args.out.write_text(json.dumps({"schema": AAD.decode(), **{k: base64.b64encode(v).decode() for k, v in values.items()}})+"\n")
    else:
        packet = json.loads(args.source.read_text())
        if packet.pop("schema") != AAD.decode():
            raise ValueError("Unknown market cache format")
        values = {k: base64.b64decode(v) for k, v in packet.items()}
        if args.mode == "open-ci":
            key = AESGCM(ci_key()).decrypt(values["wrap_nonce"], values["ci_wrapped"], AAD)
        else:
            private = serialization.load_pem_private_key(args.key.read_bytes(), password=None)
            key = private.decrypt(values["local_wrapped"], oaep)
        raw = AESGCM(key).decrypt(values["nonce"], values["data"], AAD)
        args.out.mkdir(parents=True, exist_ok=True)
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tf:
            for member in tf.getmembers():
                path = Path(member.name)
                if path.is_absolute() or ".." in path.parts or not member.isfile():
                    raise ValueError("Unsafe market cache bundle")
                target = args.out/path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(tf.extractfile(member).read())


if __name__ == "__main__":
    main()
