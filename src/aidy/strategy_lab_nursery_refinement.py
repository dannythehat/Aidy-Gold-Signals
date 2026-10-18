"""PRIVATE AIDY refinement review to GoldThinker System Builder; no broker or publication."""
import hashlib
import json
import math
from pathlib import Path

SCHEMA = "goldthinker.nursery_refinement.v1"
METHOD = "CROSSFIRE_RISK_BALANCE_H1_SOURCED_2025_2026_v1"
VERSIONS = ("original", "prior_entry_only_half_guard", "hourly_state_half_new",
            "gentle_three_quarter_new", "half_new_plus_open_trim")
VALUES = {
    "2025": ((15032.76, -33.671), (7641.47, -32.557), (10048.65, -22.072),
             (12528.68, -27.955), (11306.03, -16.159)),
    "2026": ((8573.74, -44.068), (9312.00, -24.901), (10542.25, -28.828),
             (9587.42, -36.749), (5790.53, -19.847)),
}
LABELS = ("Original", "Legacy entry-only guard", "Balanced H1 new-entry half-size",
          "Gentler 75% new-entry", "Half-size new and existing-trade trim")
REPORT_URL = "https://github.com/dannythehat/Aidy-Gold-Signals/blob/main/docs/crossfire-2025-2026-hourly-risk-guard.md"

def checksum(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()

def build_refinement(source):
    """Only source-reproduced, frozen two-year CROSSFIRE packet is admissible."""
    if (not isinstance(source, dict) or source.get("method") != METHOD
            or source.get("status") != "HISTORICAL_RESEARCH_NO_PAPER_ORDERS"
            or source.get("source_years") != [2025, 2026]
            or source.get("excluded_years") != [2020, 2021]
            or source.get("modelled_vantage_costs_verified") is not False
            or source.get("broker_swaps_and_margin_stopout_modelled") is not False
            or source.get("no_optimization_claimed") is not True):
        raise ValueError("wrong or unqualified CROSSFIRE research evidence")
    years = source.get("years")
    if not isinstance(years, dict) or set(years) != {"2025", "2026"}:
        raise ValueError("missing original and cross-period evidence")
    comparison = {}
    receipts = {}
    for year in ("2025", "2026"):
        case = years[year]
        sha, n = case.get("source_csv_sha256"), case.get("h1_rows")
        if (not isinstance(sha, str) or len(sha) != 64
                or any(c not in "0123456789abcdef" for c in sha)
                or type(n) is not int or n < 4000):
            raise ValueError("incomplete source receipt")
        variants = case.get("scenarios", {}).get("assumed_bid_ask")
        if not isinstance(variants, dict) or set(variants) != set(VERSIONS):
            raise ValueError("missing original/refined case")
        comparison[year] = {}
        for i, name in enumerate(VERSIONS):
            row = variants[name]
            p, d = row.get("profit_usd"), row.get("max_dd_pct")
            ep, ed = VALUES[year][i]
            if (row.get("variant") != name or row.get("quote_case") != "assumed"
                    or type(p) not in (int, float) or type(d) not in (int, float)
                    or not math.isfinite(p) or not math.isfinite(d)
                    or abs(p - ep) > .005 or abs(d - ed) > .0005):
                raise ValueError("historical refinement result drift")
            comparison[year][name] = {
                "profit_usd": round(p, 2), "max_dd_pct": round(d, 3),
                "profit_change_vs_original_usd": round(p - VALUES[year][0][0], 2),
                "dd_improvement_pp": round(d - VALUES[year][0][1], 3)}
        receipts[year] = {"h1_rows": n, "source_csv_sha256": sha}
    draft = {
        "schema": SCHEMA, "system_id": "S010", "working_name": "CROSSFIRE",
        "source_method": METHOD, "source_packet_sha256": checksum(source),
        "source_receipts": receipts, "comparison": comparison,
        "refinements_detected": True,
        "proposed_compromise": "hourly_state_half_new",
        "proposal_rationale": "Lower historical marked DD in both 2025 and 2026, smaller 2025 profit, higher 2026 profit versus original.",
        "stage": "NURSERY_REVIEW", "school_admission_approved": False,
        "owner_version_decision": "PENDING", "selected_version": None,
        "account_connected": False, "paper_start_date": None,
        "paper_profit_usd": None, "real_trading_authorised": False,
        "paper_trading_authorised": False, "publication_authorised": False,
        "customer_copy_authorised": False,
        "risk_notes": [
            "Model-only BID execution and scenario cost assumptions; broker swaps and margin unverified.",
            "Open CROSSFIRE positions have no original protective stop; half-size applies only to NEXT new positions.",
            "No untouched out-of-sample validation of retrospectively refined 2025/2026 results.",
            "2025 half-size variant positive in 8/12 months; 2026 Jan-Sep positive in 5/9.",
        ],
        "source_report": REPORT_URL,
    }
    draft["draft_sha256"] = checksum(draft)
    return draft

def verify_draft(draft):
    if not isinstance(draft, dict) or draft.get("schema") != SCHEMA:
        raise ValueError("invalid Nursery draft")
    if draft.get("draft_sha256") != checksum({
            k: v for k, v in draft.items() if k != "draft_sha256"}):
        raise ValueError("Nursery source digest mismatch")
    if (draft["school_admission_approved"] is not False
            or draft["selected_version"] is not None
            or draft["account_connected"] is not False
            or draft["paper_start_date"] is not None
            or draft["paper_profit_usd"] is not None
            or draft["real_trading_authorised"] is not False
            or draft["paper_trading_authorised"] is not False
            or draft["publication_authorised"] is not False
            or draft["customer_copy_authorised"] is not False):
        raise ValueError("Nursery draft must never approve trading/publication")

def title(draft):
    verify_draft(draft)
    return "CROSSFIRE S010 — AIDY refinement package [" + draft["draft_sha256"][:12] + "]"

def markdown(draft):
    verify_draft(draft)
    s = [
        "# " + title(draft), "",
        "**PRIVATE: AIDY → GOLDTHINKER SYSTEM BUILDER.** "
        "Owner approval PENDING. No trading or publication authority.", "",
        "## Original versus actual tested variants",
        "| Year | Version | Model profit USD | Max marked DD | Profit vs original | DD improvement |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for year in ("2025", "2026"):
        for v, label in zip(VERSIONS, LABELS):
            x = draft["comparison"][year][v]
            s.append(f"| {year} | {label} | {x['profit_usd']:+,.2f} | "
                     f"{x['max_dd_pct']:.3f}% | "
                     f"{x['profit_change_vs_original_usd']:+,.2f} | "
                     f"{x['dd_improvement_pp']:+.3f} pp |")
    s.extend([
        "", "## Proposed compromise (NOT selected automatically)",
        "Balanced H1 guard: same original SMA12/34+RSI14 trade signals; "
        "update drawdown state every completed H1, use half original "
        "exposure (1.64x) on future new trades from 10% drawdown, "
        "restore 3.28x below 5% drawdown. Existing positions are NOT resized.",
        "", "## Limitations", *("- " + q for q in draft["risk_notes"]),
        "", "## Verified research link", draft["source_report"],
        "Research source SHA256: " + draft["source_packet_sha256"],
        "Package SHA256: " + draft["draft_sha256"],
        "", "## Internal System Builder follow-through",
        "- [ ] Review and accept Nursery source/rights, robustness and margin risk.",
        "- [ ] Owner signs chosen ORIGINAL or REFINED rule version; preserve alternatives.",
        "- [ ] Name, brand artwork and safe public non-replicable explanation.",
        "- [ ] Perform DataForSEO keyword research before system page writing.",
        "- [ ] Prepare homepage card and dedicated system page PRIVATE first.",
        "- [ ] Create one isolated demo account via separate secure broker screen.",
        "- [ ] Reconcile signal trigger parity, hard risk controls and actual orders.",
        "- [ ] Start the 90-day Infants clock on first verified paper execution.",
        "", "**All selections, account details and P&L remain unset.**",
    ])
    return "\n".join(s) + "\n"

def write_bundle(source, folder):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, PageBreak
    from reportlab.lib import colors
    p = build_refinement(source)
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "nursery_refinement_package.json").write_text(
        json.dumps(p, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (folder / "nursery_refinement_package.md").write_text(
        markdown(p), encoding="utf-8")
    pdf = folder / "nursery_refinement_internal_appendix.pdf"
    styles = getSampleStyleSheet()
    table_data = [["Variant", "2025 USD", "2025 DD", "2026 USD", "2026 DD"]]
    for v, label in zip(VERSIONS, LABELS):
        a, b = (p["comparison"][year][v] for year in ("2025", "2026"))
        table_data.append([label, f"{a['profit_usd']:+,.2f}",
                           f"{a['max_dd_pct']:.2f}%",
                           f"{b['profit_usd']:+,.2f}",
                           f"{b['max_dd_pct']:.2f}%"])
    table = Table(table_data, colWidths=[182, 82, 65, 82, 65])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#191b1d")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#e4bb66")),
        ("FONTSIZE", (0, 0), (-1, -1), 7.7),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.whitesmoke, colors.white]),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    story = [
        Paragraph("GOLDTHINKER / AIDY PRIVATE RESEARCH", styles["Title"]),
        Paragraph("CROSSFIRE S010 — Nursery Refinement Review", styles["Heading2"]),
        Paragraph("Frozen historical research comparison; NOT real broker P&amp;L, "
                  "NOT a paper deployment or owner approval.", styles["BodyText"]),
        Spacer(1, 16), table, Spacer(1, 15),
        Paragraph("Suggested compromise: H1-updated half-size new-entry guard; "
                  "original entry signals unchanged, no automatic live selection.",
                  styles["BodyText"]), PageBreak(),
        Paragraph("System Builder handover — INTERNAL ONLY", styles["Heading1"]),
        Paragraph("Nursery acceptance and owner version-selection are PENDING. "
                  "No demo login, broker orders, paper start or public JOIN.",
                  styles["BodyText"]),
    ]
    for w in p["risk_notes"]:
        story += [Spacer(1, 8), Paragraph("- " + w, styles["BodyText"])]
    story += [Spacer(1, 20),
              Paragraph("Evidence digest: " + p["draft_sha256"], styles["BodyText"])]
    SimpleDocTemplate(str(pdf), pagesize=A4, leftMargin=38, rightMargin=38).build(story)
    return p
