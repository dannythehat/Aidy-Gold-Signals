"""Encrypt research-only source transport; never publish publisher plaintext.

Only a public recipient key is committed. Private key stays in local artifacts.
This is data transport, never authentication or a source-execution mechanism.
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


def main():
    p = argparse.ArgumentParser()
    p.add_argument("mode", choices=("encrypt", "decrypt"))
    p.add_argument("--key", required=True, type=Path)
    p.add_argument("--source", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    args = p.parse_args()
    oaep = padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None)
    if args.mode == "encrypt":
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            for path in sorted(args.source.rglob("*")):
                if path.is_file():
                    tf.add(path, arcname=str(path.relative_to(args.source)))
        key = AESGCM.generate_key(256)
        nonce = os.urandom(12)
        public = serialization.load_pem_public_key(args.key.read_bytes())
        packet = {"schema": "oracle.source.transport.rsa_aesgcm.v1", "key": public.encrypt(key, oaep),
                  "nonce": nonce, "data": AESGCM(key).encrypt(nonce, buf.getvalue(), b"oracle-research-source")}
        args.out.write_text(json.dumps({k: base64.b64encode(v).decode() if isinstance(v, bytes) else v for k, v in packet.items()})+"\n")
    else:
        packet = json.loads(args.source.read_text())
        if packet["schema"] != "oracle.source.transport.rsa_aesgcm.v1":
            raise ValueError("Unknown source transport format")
        private = serialization.load_pem_private_key(args.key.read_bytes(), password=None)
        key = private.decrypt(base64.b64decode(packet["key"]), oaep)
        raw = AESGCM(key).decrypt(base64.b64decode(packet["nonce"]), base64.b64decode(packet["data"]), b"oracle-research-source")
        args.out.mkdir(parents=True, exist_ok=True)
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tf:
            for member in tf.getmembers():
                path = Path(member.name)
                if path.is_absolute() or ".." in path.parts or not member.isfile():
                    raise ValueError("Unsafe source bundle path/type")
                target = args.out/path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(tf.extractfile(member).read())


if __name__ == "__main__":
    main()
