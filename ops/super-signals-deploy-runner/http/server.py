from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path


def log(message: str) -> None:
    print(message, flush=True)


def deploy() -> int:
    token = bool(os.environ.get("CLOUDFLARE_API_TOKEN"))
    account = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
    if not token or not account or not shutil.which("git") or not shutil.which("npx"):
        log("SUPER_SIGNALS_WEBSITE_DEPLOY_PREREQS=FAIL")
        return 2

    child_env = os.environ.copy()
    child_env.pop("PYTHONPATH", None)
    child_env.pop("SUPER_SIGNALS_DEPLOY_NOW", None)

    with tempfile.TemporaryDirectory(prefix="ss-site-") as tmp:
        repo = Path(tmp) / "site"
        log("SUPER_SIGNALS_WEBSITE_CLONE=START")
        clone = subprocess.run(
            [
                "git", "clone", "--depth", "1", "--branch", "main",
                "https://github.com/dannythehat/super-signals-website.git",
                str(repo),
            ],
            env=child_env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        log(clone.stdout)
        log(f"SUPER_SIGNALS_WEBSITE_CLONE_EXIT={clone.returncode}")
        if clone.returncode != 0:
            return clone.returncode or 3

        log("SUPER_SIGNALS_WEBSITE_WRANGLER=START")
        deploy_result = subprocess.run(
            ["npx", "--yes", "wrangler@4", "deploy", "--config", "wrangler.jsonc"],
            cwd=str(repo),
            env=child_env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        log(deploy_result.stdout)
        log(f"SUPER_SIGNALS_WEBSITE_WRANGLER_EXIT={deploy_result.returncode}")
        return deploy_result.returncode


def serve(port: int) -> None:
    response = (
        b"HTTP/1.1 200 OK\r\n"
        b"Content-Type: text/plain\r\n"
        b"Content-Length: 2\r\n"
        b"Connection: close\r\n\r\nOK"
    )
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", port))
        sock.listen(16)
        log(f"SUPER_SIGNALS_DEPLOY_RUNNER_READY={port}")
        while True:
            conn, _ = sock.accept()
            with conn:
                try:
                    conn.recv(4096)
                    conn.sendall(response)
                except OSError:
                    pass


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("PORT", "10000"))
    code = deploy()
    if code == 0:
        log("SUPER_SIGNALS_WEBSITE_DEPLOY=PASS")
    else:
        log(f"SUPER_SIGNALS_WEBSITE_DEPLOY=FAIL:{code}")
    serve(port)


if __name__ == "__main__":
    main()
