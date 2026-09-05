from pathlib import Path

root = Path(__file__).resolve().parents[2]
path = root / "src/aidy/provider_market_api.py"
text = path.read_text(encoding="utf-8")
old = 'PROVIDER_PUBLIC_KEY_B64URL = "itdRZAC8u-1N5NWEwqvMWtRT6WK4PeeyEpzIh4TDQ2w"'
new = 'PROVIDER_PUBLIC_KEY_B64URL = "L7ey29IgqbMwaqIS-eKGMoeLVE2Jbs1QRDMEHc1wXvw"'
if text.count(old) != 1:
    raise SystemExit(f"expected old public key once, got {text.count(old)}")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
