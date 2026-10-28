"""Build a deterministic, NEVER-DEPLOYING Oracle Gold source package.

A compliant manifest plus source code is still not scientific qualification,
broker permission, licence clearance, a signed publisher release or a runnable
demo. This tool never starts a strategy, fetches internet code or sends orders.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import stat
import zipfile

import jsonschema

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "contracts/oracle_hub_gold_bot_manifest_v1.schema.json"
MANDATORY = {
    "manifest.json", "README.md", "config/defaults.json",
    "contracts/signal-v1.json", "requirements.lock",
}


def _accepted_path(path: str, entrypoint: str) -> bool:
    if path in MANDATORY or path == entrypoint:
        return True
    bits = Path(path).parts
    if not bits:
        return False
    parent, suffix = bits[0], Path(path).suffix.lower()
    if parent == "tests":
        return suffix in (".py", ".json", ".md")
    if parent == "evidence":
        return suffix in (".json", ".md", ".csv")
    if parent == "assets":
        return suffix in (".svg", ".webp")
    if parent == "deployment" and len(bits) >= 3 and bits[1] == "windows":
        return suffix in (".md", ".ps1", ".json")
    return False


def build(source: Path, destination: Path) -> tuple[Path, str]:
    source = source.resolve(strict=True)
    if not source.is_dir():
        raise ValueError("Source must be a directory")
    info = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(info, schema)
    if info["ui"]["detail_slug"] != info["slug"]:
        raise ValueError("Homepage slug must agree with release identity")

    payload: dict[str, bytes] = {}
    for file in source.rglob("*"):
        if file.is_symlink():
            raise ValueError("Symbolic links are forbidden in immutable packages")
        if file.is_dir():
            continue
        rel = file.relative_to(source).as_posix()
        if not _accepted_path(rel, info["entrypoint"]):
            raise ValueError(f"Unreviewed file in source package: {rel}")
        if file.stat().st_size > 20_000_000:
            raise ValueError(f"Oversized package member: {rel}")
        data = file.read_bytes()
        if file.suffix.lower() not in (".webp",):
            if b"-----BEGIN PRIVATE KEY-----" in data or re.search(
                rb"(?:PASSWORD|API_KEY|SECRET_TOKEN)\s*[:=]\s*[^\s\"']{6,}",
                data, flags=re.IGNORECASE
            ):
                raise ValueError(f"Potential plaintext secret in {rel}")
        payload[rel] = data
    missing = MANDATORY.union({info["entrypoint"]}) - set(payload)
    if missing:
        raise ValueError(f"Missing mandatory files: {sorted(missing)}")
    if not any(x.startswith("tests/") for x in payload):
        raise ValueError("Package has no tests")
    if not any(x.startswith("evidence/") for x in payload):
        raise ValueError("Package has no research evidence summary")

    sums = {path: hashlib.sha256(data).hexdigest()
            for path, data in sorted(payload.items())}
    payload["SHA256SUMS.json"] = (
        json.dumps(sums, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")

    outname = f"GoldBot-{info['strategy_id']}-{info['slug']}-{info['version']}.zip"
    destination.mkdir(parents=True, exist_ok=True)
    out = destination / outname
    if out.exists() or (destination / (outname + ".sha256")).exists():
        raise FileExistsError("Version already built: create a new immutable version")
    try:
        with zipfile.ZipFile(out, "x", compression=zipfile.ZIP_DEFLATED,
                             compresslevel=9) as archive:
            for name, data in sorted(payload.items()):
                member = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                member.compress_type = zipfile.ZIP_DEFLATED
                member.external_attr = (stat.S_IFREG | 0o444) << 16
                archive.writestr(member, data, compress_type=zipfile.ZIP_DEFLATED,
                                 compresslevel=9)
        sha = hashlib.sha256(out.read_bytes()).hexdigest()
        (destination / (outname + ".sha256")).write_text(
            sha + "  " + outname + "\n", encoding="ascii")
    except BaseException:
        out.unlink(missing_ok=True)
        raise
    return out, sha


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    path, sha = build(args.source, args.output)
    print(json.dumps({
        "artifact": str(path),
        "sha256": sha,
        "broker_orders": 0,
        "installed_to_server": False,
        "execution_enabled": False,
        "package_is_signed": False,
        "scientific_qualification_verified_by_packager": False,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
