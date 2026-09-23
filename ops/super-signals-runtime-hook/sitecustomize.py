from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def _runtime_deploy_start() -> bool:
    port = str(os.environ.get("PORT") or "").strip()
    args = [str(x) for x in sys.argv]
    if port and args and args[0] == "-m" and port in args[1:]:
        return True
    if args and Path(args[0]).name == "receiver.py":
        return True
    return False


if _runtime_deploy_start():
    print("SUPER_SIGNALS_RUNTIME_DEPLOY=START", flush=True)
    token = bool(os.environ.get("CLOUDFLARE_API_TOKEN"))
    account = str(os.environ.get("CLOUDFLARE_ACCOUNT_ID") or "").strip()
    print(f"CLOUDFLARE_API_TOKEN_PRESENT={1 if token else 0}", flush=True)
    print(f"CLOUDFLARE_ACCOUNT_ID_PRESENT={1 if bool(account) else 0}", flush=True)

    if token and account and shutil.which("git") and shutil.which("npx"):
        child_env = os.environ.copy()
        child_env.pop("PYTHONPATH", None)
        with tempfile.TemporaryDirectory(prefix="ss-site-") as tmp:
            repo = Path(tmp) / "site"
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
            print(clone.stdout, flush=True)
            print(f"SUPER_SIGNALS_RUNTIME_CLONE_EXIT={clone.returncode}", flush=True)
            if clone.returncode == 0:
                deploy = subprocess.run(
                    ["npx", "--yes", "wrangler@4", "deploy", "--config", "wrangler.jsonc"],
                    cwd=str(repo),
                    env=child_env,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                )
                print(deploy.stdout, flush=True)
                print(f"SUPER_SIGNALS_RUNTIME_WRANGLER_EXIT={deploy.returncode}", flush=True)
                if deploy.returncode == 0:
                    print("SUPER_SIGNALS_RUNTIME_DEPLOY=PASS", flush=True)
                else:
                    print("SUPER_SIGNALS_RUNTIME_DEPLOY=FAIL", flush=True)
    else:
        print("SUPER_SIGNALS_RUNTIME_DEPLOY_PREREQS=FAIL", flush=True)
