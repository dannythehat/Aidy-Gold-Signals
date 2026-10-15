"""Day31 actual tamper-and-reject execution against Day30 source-verified downloads.

One real Day30 acceptance run -> true historical BigQuery source x2 -> PDF,
then clone actual exports and deliberately forge CSV/PDF/canonical results.
Independent human review is REQUIRED separately and is not self-signed.
"""
from __future__ import annotations

import csv
import io
import json
import shutil
import tempfile
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas

from aidy.strategy_lab_report_adversarial import (
    audit_outcome_json, independent_report_audit, no_trade_analysis,
    write_review_packet,
)
from aidy.strategy_lab_report_contract import _hash
from scripts.strategy_lab.day29_canonical_report_acceptance import OUT as DAY29_OUT
from scripts.strategy_lab.day30_actual_exports_acceptance import (
    OUT as DAY30_OUT,
    main as day30_main,
)

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT/"artifacts/strategy_lab/day31_adversarial_acceptance.json"
REVIEW = ROOT/"artifacts/strategy_lab/day31_human_review_pending.md"


def _resign(path: Path, name: str) -> None:
    file = path/name
    mf = path/"manifest.json"
    manifest = json.loads(mf.read_text(encoding="utf-8"))
    manifest["files"][name] = {
        "sha256": sha256(file.read_bytes()).hexdigest(),
        "bytes": file.stat().st_size,
    }
    mf.write_text(json.dumps(manifest, sort_keys=True, indent=2)+"\n",
                  encoding="utf-8")


def _forged_csv(path: Path, name: str, field: str, new_value: str) -> None:
    file = path/name
    with file.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        header, rows = reader.fieldnames, list(reader)
    if header is None or not rows or field not in header:
        raise ValueError("attack could not access targeted original CSV field")
    rows[0][field] = new_value
    with file.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=header, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    _resign(path, name)


def _forged_pdf(path: Path) -> None:
    file = path/"research_report.pdf"
    writer = PdfWriter()
    for page in PdfReader(str(file)).pages:
        writer.add_page(page)
    extra = io.BytesIO()
    pdf = canvas.Canvas(extra)
    pdf.drawString(80, 710, "VERIFIED LIVE PROFIT: fabricated claim")
    pdf.save()
    extra.seek(0)
    writer.add_page(PdfReader(extra).pages[0])
    with file.open("wb") as output:
        writer.write(output)
    _resign(path, "research_report.pdf")


def _receipt_mutation(receipt: dict, kind: str) -> dict:
    trial = deepcopy(receipt)
    if kind == "fabricated_paper_pnl":
        trial["report"]["production"]["paper"]["forward_paper_pnl"] = "9999999.00"
    elif kind == "fabricated_master_pnl":
        trial["report"]["production"]["elite20"]["portfolio_pnl"] = "9000000.00"
    elif kind == "fake_research_score":
        trial["report"]["research"]["evidence_rating"]["score_out_of_100"] = 100
    elif kind == "user_enabled":
        trial["report"]["identity"]["customer_can_connect"] = True
    elif kind == "removed_original_source_lineage":
        trial["report"]["provenance"]["numeric_field_lineage"] = {}
    elif kind == "zero_trades_with_positive_total":
        trial["report"]["research"]["trades"] = []
    else:
        raise ValueError("unsupported adversarial mutation")
    trial["report"]["canonical_result_sha256"] = _hash({
        k: v for k, v in trial["report"].items()
        if k != "canonical_result_sha256"
    })
    return trial


def _do_attacks(real_dir: Path, original: dict) -> list[dict]:
    attacks: list[dict] = []
    attempts = [
        ("commission_rehashed", "cost_scenarios.csv", "candidate_commission_usd", "-99.00"),
        ("slippage_rehashed", "cost_scenarios.csv", "candidate_slippage_usd", "99.00"),
        ("cost_multiplier_rehashed", "cost_scenarios.csv", "cash_charge_multiplier", "99"),
        ("spread_ticks_rehashed", "cost_scenarios.csv", "extra_spread_ticks_per_side", "999"),
        ("clock_control_rehashed", "cost_scenarios.csv", "independent_blind_clock_long_net_usd", "9999.00"),
        ("trade_open_time_rehashed", "trades.csv", "opened_at_utc", "2023-01-01T00:00:00Z"),
        ("trade_direction_rehashed", "trades.csv", "direction", "short"),
        ("trade_identifier_rehashed", "trades.csv", "position_id", "fake-position-ID"),
    ]
    for name, source, field, changed in attempts:
        with tempfile.TemporaryDirectory(prefix="aidy-d31-") as folder:
            forged = Path(folder)/"copied"
            shutil.copytree(real_dir, forged)
            _forged_csv(forged, source, field, changed)
            try:
                independent_report_audit(forged, original)
            except ValueError as exc:
                attacks.append({
                    "name": name, "outcome": "REJECTED",
                    "rejection_type": type(exc).__name__,
                })
            else:
                raise ValueError(f"tampered CSV field was accepted: {name}")
    with tempfile.TemporaryDirectory(prefix="aidy-d31-") as folder:
        forged = Path(folder)/"pdf"
        shutil.copytree(real_dir, forged)
        _forged_pdf(forged)
        try:
            independent_report_audit(forged, original)
        except ValueError as exc:
            if "forbidden fabricated" not in str(exc):
                raise ValueError("forged PDF was blocked for wrong reason") from exc
            attacks.append({
                "name": "forged_live_profit_pdf_rehashed",
                "outcome": "REJECTED", "rejection_type": type(exc).__name__,
            })
        else:
            raise ValueError("forged profit PDF appendix was accepted")
    for kind in (
        "fabricated_paper_pnl", "fabricated_master_pnl",
        "fake_research_score", "user_enabled",
        "removed_original_source_lineage", "zero_trades_with_positive_total",
    ):
        changed = _receipt_mutation(original, kind)
        try:
            independent_report_audit(real_dir, changed)
        except (ValueError, KeyError) as exc:
            attacks.append({
                "name": kind, "outcome": "REJECTED",
                "rejection_type": type(exc).__name__,
            })
        else:
            raise ValueError(f"false positive source qualification accepted: {kind}")
    with tempfile.TemporaryDirectory(prefix="aidy-d31-") as folder:
        forged = Path(folder)/"missing"
        shutil.copytree(real_dir, forged)
        (forged/"cost_scenarios.csv").unlink()
        try:
            independent_report_audit(forged, original)
        except FileNotFoundError as exc:
            attacks.append({
                "name": "missing_cost_csv",
                "outcome": "REJECTED", "rejection_type": type(exc).__name__,
            })
        else:
            raise ValueError("incomplete report was accepted")
    return attacks


def main() -> int:
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    try:
        if day30_main() != 0:
            raise ValueError("Day30 original live BigQuery PDF build failed")
        original = json.loads(DAY29_OUT.read_text(encoding="utf-8"))
        if original.get("status") != "PASS":
            raise ValueError("source canonical research not verified")
        if no_trade_analysis([])["status"] != "NO_TRADES_INSUFFICIENT_EVIDENCE":
            raise ValueError("zero trading history was represented as performance")
        attacks = _do_attacks(DAY30_OUT, original)
        proof = audit_outcome_json(DAY30_OUT, original, attacks)
        if len(attacks) != 16 or proof["attacks_rejected"] != 16:
            raise ValueError("not all seventeen? attack intents executed")
        proof["source_verified_bigquery_queries"] = original[
            "independent_real_historical_query_job_ids"
        ]
        proof["all_adversarial_tests_executed"] = attacks
        proof["day31_engineering_tests_passed"] = True
        proof["day31_human_review_pending"] = True
        write_review_packet(REVIEW, proof, attacks)
        # Human reviewer cannot be inferred from automated acceptance.
        if proof["independent_human_review_complete"] is not False:
            raise ValueError("automated software falsely attested independent human review")
    except Exception as exc:  # noqa: BLE001 - explicit documented blocker
        proof = {
            "status": "BLOCKED", "error_type": type(exc).__name__,
            "message": str(exc)[:400], "overall_owner_day31_stage_pass": False,
            "independent_human_review_complete": False,
        }
    EVIDENCE.write_text(json.dumps(proof, indent=2, sort_keys=True)+"\n",
                        encoding="utf-8")
    print(json.dumps({
        "status": proof["status"],
        "attacks": proof.get("attacks_rejected"),
        "result": proof.get("canonical_result_sha256"),
        "human_review_complete": proof["independent_human_review_complete"],
        "blocker": proof.get("message"),
    }, sort_keys=True))
    return 0 if proof["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
