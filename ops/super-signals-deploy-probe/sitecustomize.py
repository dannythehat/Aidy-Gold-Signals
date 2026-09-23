import os, shutil, subprocess, sys
from pathlib import Path

def p(msg):
    print(msg, flush=True)

p("SUPER_SIGNALS_DEPLOY_PROBE=START")
token=bool(os.environ.get("CLOUDFLARE_API_TOKEN"))
account=bool(os.environ.get("CLOUDFLARE_ACCOUNT_ID"))
npx=bool(shutil.which("npx"))
p(f"CLOUDFLARE_API_TOKEN_PRESENT={1 if token else 0}")
p(f"CLOUDFLARE_ACCOUNT_ID_PRESENT={1 if account else 0}")
p(f"NPX_PRESENT={1 if npx else 0}")

marker=Path("ops/super-signals-deploy-probe/.performance_hotfix_deployed")
should_deploy=os.environ.get("SUPER_SIGNALS_DEPLOY_NOW")=="1"
if should_deploy and token and account and npx and not marker.exists():
    p("SUPER_SIGNALS_HOTFIX_DEPLOY=START")
    result=subprocess.run(
        ["npx","--yes","wrangler@4","deploy","--config","ops/super-signals-performance-hotfix/wrangler.jsonc"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    p("SUPER_SIGNALS_WRANGLER_OUTPUT_BEGIN")
    p(result.stdout)
    p("SUPER_SIGNALS_WRANGLER_OUTPUT_END")
    p(f"SUPER_SIGNALS_HOTFIX_DEPLOY_EXIT={result.returncode}")
    if result.returncode == 0:
        marker.write_text("deployed\n", encoding="utf-8")
        p("SUPER_SIGNALS_HOTFIX_DEPLOY=PASS")
    else:
        p("SUPER_SIGNALS_HOTFIX_DEPLOY=FAILED_BUT_BUILD_CONTINUES")

p("SUPER_SIGNALS_DEPLOY_PROBE=END")
