import os, shutil, subprocess
from pathlib import Path

print("SUPER_SIGNALS_DEPLOY_PROBE=START")
token=bool(os.environ.get("CLOUDFLARE_API_TOKEN"))
account=bool(os.environ.get("CLOUDFLARE_ACCOUNT_ID"))
npx=bool(shutil.which("npx"))
print(f"CLOUDFLARE_API_TOKEN_PRESENT={1 if token else 0}")
print(f"CLOUDFLARE_ACCOUNT_ID_PRESENT={1 if account else 0}")
print(f"NPX_PRESENT={1 if npx else 0}")

marker=Path("ops/super-signals-deploy-probe/.performance_hotfix_deployed")
should_deploy=os.environ.get("SUPER_SIGNALS_DEPLOY_NOW")=="1"
if should_deploy and token and account and npx and not marker.exists():
    print("SUPER_SIGNALS_HOTFIX_DEPLOY=START")
    result=subprocess.run(
        [
            "npx","--yes","wrangler@4","deploy",
            "--config","ops/super-signals-performance-hotfix/wrangler.jsonc",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    print(result.stdout)
    print(f"SUPER_SIGNALS_HOTFIX_DEPLOY_EXIT={result.returncode}")
    if result.returncode != 0:
        os._exit(result.returncode or 1)
    marker.write_text("deployed\n", encoding="utf-8")
    print("SUPER_SIGNALS_HOTFIX_DEPLOY=PASS")

print("SUPER_SIGNALS_DEPLOY_PROBE=END")
