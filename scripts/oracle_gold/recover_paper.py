"""Try the two observed public SSRN delivery links; preserve every failure."""
import argparse
import hashlib
import json
from pathlib import Path

from scripts.oracle_gold.recover_sources import get


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True, type=Path)
    a = p.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    attempts = []
    for suffix in ("&mirid=1", "&type=2"):
        url = "https://papers.ssrn.com/sol3/Delivery.cfm?abstractid=6650958"+suffix
        try:
            raw, receipt = get(url)
            if not raw.startswith(b"%PDF-"):
                raise ValueError("Delivery response is not a PDF")
            (a.out/"S078_original.pdf").write_bytes(raw)
            attempts.append(receipt)
            break
        except Exception as exc:  # noqa: BLE001 - keep each real access failure
            attempts.append({"url": url, "error_type": type(exc).__name__,
                             "http_status": getattr(exc, "code", None)})
    report = {"id": "S078", "attempts": attempts,
              "pdf_obtained": (a.out/"S078_original.pdf").exists(),
              "executable_code_obtained": False}
    if report["pdf_obtained"]:
        report["pdf_sha256"] = hashlib.sha256((a.out/"S078_original.pdf").read_bytes()).hexdigest()
    (a.out/"receipt.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
