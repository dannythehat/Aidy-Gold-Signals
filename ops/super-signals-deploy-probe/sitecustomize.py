import os, shutil, subprocess, tempfile
from pathlib import Path

def p(msg):
    print(msg, flush=True)

p("SUPER_SIGNALS_DEPLOY_PROBE=START")
token=bool(os.environ.get("CLOUDFLARE_API_TOKEN"))
account=bool(os.environ.get("CLOUDFLARE_ACCOUNT_ID"))
npx=bool(shutil.which("npx"))
git=bool(shutil.which("git"))
p(f"CLOUDFLARE_API_TOKEN_PRESENT={1 if token else 0}")
p(f"CLOUDFLARE_ACCOUNT_ID_PRESENT={1 if account else 0}")
p(f"NPX_PRESENT={1 if npx else 0}")
p(f"GIT_PRESENT={1 if git else 0}")

marker=Path("ops/super-signals-deploy-probe/.website_worker_deployed")
should_deploy=os.environ.get("SUPER_SIGNALS_DEPLOY_NOW")=="1"
if should_deploy and token and account and npx and git and not marker.exists():
    p("SUPER_SIGNALS_WEBSITE_DEPLOY=START")
    with tempfile.TemporaryDirectory(prefix="ss-site-") as tmp:
        repo=Path(tmp)/"site"
        clone=subprocess.run(
            ["git","clone","--depth","1","--branch","main","https://github.com/dannythehat/super-signals-website.git",str(repo)],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        )
        p("SUPER_SIGNALS_GIT_CLONE_OUTPUT_BEGIN")
        p(clone.stdout)
        p("SUPER_SIGNALS_GIT_CLONE_OUTPUT_END")
        p(f"SUPER_SIGNALS_GIT_CLONE_EXIT={clone.returncode}")
        if clone.returncode==0:
            deploy=subprocess.run(
                ["npx","--yes","wrangler@4","deploy","--config","wrangler.jsonc"],
                cwd=str(repo),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            p("SUPER_SIGNALS_WRANGLER_OUTPUT_BEGIN")
            p(deploy.stdout)
            p("SUPER_SIGNALS_WRANGLER_OUTPUT_END")
            p(f"SUPER_SIGNALS_WEBSITE_DEPLOY_EXIT={deploy.returncode}")
            if deploy.returncode==0:
                marker.write_text("deployed\n", encoding="utf-8")
                p("SUPER_SIGNALS_WEBSITE_DEPLOY=PASS")
            else:
                p("SUPER_SIGNALS_WEBSITE_DEPLOY=FAILED")
        else:
            p("SUPER_SIGNALS_WEBSITE_CLONE=FAILED")

p("SUPER_SIGNALS_DEPLOY_PROBE=END")
