import os, shutil
print("SUPER_SIGNALS_DEPLOY_PROBE=START")
for name in ("CLOUDFLARE_API_TOKEN","CLOUDFLARE_ACCOUNT_ID","CF_API_TOKEN"):
    print(f"{name}_PRESENT={1 if os.environ.get(name) else 0}")
print(f"NPX_PRESENT={1 if shutil.which('npx') else 0}")
print(f"NODE_PRESENT={1 if shutil.which('node') else 0}")
print("SUPER_SIGNALS_DEPLOY_PROBE=END")
