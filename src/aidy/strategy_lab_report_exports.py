"""Day30 AIDY -> GoldThinker auditable PDF/CSV/chart EXPORTS.

Every advertised figure comes from one frozen Day29 research receipt. This
module never presents internal synthetic trades as real XAUUSD performance.
Future forward paper accounts and GoldThinker Elite20 share NO fake balances.
"""
from __future__ import annotations

import csv
import io
import json
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
from pypdf import PdfReader
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from aidy.strategy_lab_report_contract import PERIODS, verify_canonical_report

SCHEMA = "aidy.strategy_lab.export_bundle.v1"
GOLD = "#D5AC4F"
MIDNIGHT = "#0F192A"
DARK = "#18243A"
TEXT = "#172238"
MUTED = "#667389"
BORDER = "#DBE2EC"
FONT = "Helvetica"
FONT_BOLD = "Helvetica-Bold"
MONEY = Decimal("0.01")
TRADE_HEADER = (
    "run_id", "canonical_result_sha256", "research_origin",
    "verified_journal_tip_sha256", "trade_number", "position_id", "direction",
    "opened_at_utc", "closed_at_utc", "gross_usd",
    "allocated_cash_costs_usd", "net_usd",
)
STRESS_HEADER = (
    "run_id", "canonical_result_sha256", "research_origin",
    "quote_snapshot_sha256", "cost_policy_sha256", "scenario",
    "extra_spread_ticks_per_side", "cash_charge_multiplier",
    "candidate_gross_quote_side_usd", "candidate_commission_usd",
    "candidate_slippage_usd", "candidate_funding_usd", "candidate_net_usd",
    "independent_blind_clock_long_net_usd", "blind_clock_short_net_usd",
    "independently_scheduled_same_session_long_net_usd",
    "candidate_minus_scheduled_naive_usd",
)


def _decimal(s: object) -> Decimal:
    if not isinstance(s, str) or not s or "e" in s.lower():
        raise ValueError("fixed-point source decimal text required")
    try:
        value = Decimal(s)
    except Exception as exc:
        raise ValueError("invalid source numeric text") from exc
    if not value.is_finite():
        raise ValueError("non-finite source numeric")
    return value


def _hash(data: bytes) -> str:
    return sha256(data).hexdigest()


def _csv_cell(value: object) -> str:
    if not isinstance(value, (str, int)):
        raise TypeError("CSV field requires trusted primitive")
    s = str(value)
    # Numeric negatives are legitimate; customer-supplied formula-like text is not.
    if s.startswith(("=", "+", "-", "@", "\t", "\r")) and not (
        s.startswith("-") and _is_negative_money(s)
    ):
        raise ValueError("unsafe spreadsheet formula or control payload")
    return s


def _is_negative_money(value: str) -> bool:
    try:
        return _decimal(value) <= 0
    except ValueError:
        return False


def _csv_bytes(header: tuple[str, ...], records: list[tuple[object, ...]]) -> bytes:
    target = io.StringIO(newline="")
    writer = csv.writer(target, lineterminator="\n")
    writer.writerow(header)
    for record in records:
        if len(record) != len(header):
            raise ValueError("CSV schema width mismatch")
        writer.writerow([_csv_cell(v) for v in record])
    return target.getvalue().encode("utf-8")


def validate_research_receipt(payload: dict) -> dict:
    if (not isinstance(payload, dict) or payload.get("status") != "PASS"
            or payload.get("scope") != "CANONICAL_AIDY_REPORT_REPLAY_NOT_GOLDTHINKER_PRODUCTION"
            or payload.get("paper_and_live_performance_qualified") is not False):
        raise ValueError("Day29 original source-qualified canonical receipt required")
    report = payload["report"]
    verify_canonical_report(report)
    research, prod, identity = report["research"], report["production"], report["identity"]
    if (identity["research_engine"] != "AIDY"
            or identity["customer_brand"] != "GoldThinker"
            or identity["subject_kind"] != "laboratory_reference_evidence_bundle"
            or identity["strategy_id"] is not None
            or identity["goldthinker_system_name"] is not None
            or identity["publication_allowed"] is not False
            or identity["customer_can_connect"] is not False
            or prod["paper"]["forward_paper_pnl"] is not None
            or prod["paper"]["account_id"] is not None
            or prod["elite20"]["portfolio_pnl"] is not None
            or prod["elite20"]["combined_account_id"] is not None
            or research["synthetic_historical_net_pnl_only"] is not True
            or research["independently_qualified_real_strategy_profit"] is not False
            or research["evidence_rating"]["score_out_of_100"] is not None
            or research["evidence_rating"]["governance"] != "ORANGE_INVESTIGATE"):
        raise ValueError("no unqualified GoldThinker system or paper/live P&L can be exported")
    if (len(research["trades"]) != research["accounting"]["closed_trades"]
            or len(research["cost_stress"]) != 3
            or set(research["periods"]) != set(PERIODS)
            or not report["provenance"]["numeric_field_lineage"]):
        raise ValueError("incomplete original journal, scenarios or provenance appendix")
    if report["output_contract"]["pdf"] != "DAY30_NOT_BUILT":
        raise ValueError("Day30 source receipt must retain original Day29 version identity")
    ledger = report["provenance"]["source_sha256"]["day24_sqlite_journal"]
    cash = research["accounting"]
    trades = research["trades"]
    gross = sum((_decimal(t["gross_usd"]) for t in trades), Decimal(0))
    fees = sum((_decimal(t["costs_usd"]) for t in trades), Decimal(0))
    net = sum((_decimal(t["net_usd"]) for t in trades), Decimal(0))
    if (gross != _decimal(cash["realized_gross_usd"])
            or fees != _decimal(cash["transaction_costs_usd"])
            or net != _decimal(cash["net_profit_usd"])
            or net != gross + fees
            or _decimal(cash["initial_capital_usd"]) + net
            != _decimal(cash["final_cash_usd"])
            or _decimal(cash["final_cash_usd"]) != _decimal(cash["final_equity_usd"])):
        raise ValueError("Day29 original financial accounting does not reconcile")
    for i, trade in enumerate(trades):
        if (_decimal(trade["gross_usd"]) + _decimal(trade["costs_usd"])
                != _decimal(trade["net_usd"])):
            raise ValueError("unreconciled trade")
        for key in ("gross_usd", "costs_usd", "net_usd"):
            field = report["provenance"]["numeric_field_lineage"].get(
                f"/research/trades/{i}/{key}"
            )
            if not field or field["source_sha256"] != ledger:
                raise ValueError("trade amount has no original journal path and hash")
    for period in PERIODS:
        block = research["periods"][period]
        indices = block["source_trade_indices"]
        if len(indices) != len(set(indices)) or any(
            type(i) is not int or not 0 <= i < len(trades) for i in indices
        ):
            raise ValueError("untrusted reporting period constituent indices")
        subtotal = sum((_decimal(trades[i]["net_usd"]) for i in indices), Decimal(0))
        if subtotal != _decimal(block["realised_net_pnl_usd"]):
            raise ValueError("realised period net differs from original journal trades")
        lineage = report["provenance"]["numeric_field_lineage"][
            f"/research/periods/{period}/realised_net_pnl_usd"
        ]
        if lineage["source_sha256"] != ledger or lineage["trade_indices"] != indices:
            raise ValueError("period has invalid original cash journal provenance")
    return report


def trade_csv(report: dict) -> bytes:
    trades = report["research"]["trades"]
    source = report["provenance"]["source_sha256"]["day24_sqlite_journal"]
    records = []
    for i, trade in enumerate(trades, 1):
        records.append((
            report["run_id"], report["canonical_result_sha256"],
            "INTERNAL_SYNTHETIC_JOURNAL_NOT_GOLD_TRADING", source,
            i, trade["position_id"], trade["direction"], trade["opened_at_utc"],
            trade["closed_at_utc"], trade["gross_usd"], trade["costs_usd"],
            trade["net_usd"],
        ))
    return _csv_bytes(TRADE_HEADER, records)


def scenarios_csv(report: dict) -> bytes:
    source = report["provenance"]["source_sha256"]
    records = []
    for row in report["research"]["cost_stress"]:
        records.append((
            report["run_id"], report["canonical_result_sha256"],
            "INTERNAL_SYNTHETIC_COST_STRESS_NOT_REAL_MARKET",
            source["day25_synthetic_quotes"], source["day25_cost_policy"],
            row["name"], row["extra_spread_ticks_per_side"],
            row["cash_charge_multiplier"],
            row["candidate_gross_quote_side_usd"], row["candidate_commission_usd"],
            row["candidate_slippage_usd"], row["candidate_funding_usd"],
            row["candidate_net_usd"], row["independent_blind_clock_long_net_usd"],
            row["blind_clock_short_net_usd"],
            row["independently_scheduled_same_session_long_net_usd"],
            row["candidate_minus_scheduled_naive_usd"],
        ))
    return _csv_bytes(STRESS_HEADER, records)


def _fig_theme(ax, title: str, subtitle: str):
    ax.set_facecolor("#FFFFFF")
    ax.set_title(title, loc="left", weight="bold", color=MIDNIGHT, fontsize=13, pad=22)
    ax.text(0, 1.04, subtitle, transform=ax.transAxes, fontsize=8, color=MUTED)
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color(BORDER)
    ax.grid(axis="y", color="#E6EBF3", linewidth=.7)
    ax.set_axisbelow(True)
    ax.tick_params(colors=MUTED, labelsize=8)


def equity_curve(path: Path, report: dict) -> None:
    trades = report["research"]["trades"]
    start = _decimal(report["research"]["accounting"]["initial_capital_usd"])
    balances = [start]
    for row in trades:
        balances.append(balances[-1] + _decimal(row["net_usd"]))
    x = range(len(balances))
    fig, ax = plt.subplots(figsize=(9.4, 3.5), dpi=155)
    _fig_theme(ax, "Synthetic ledger: realised cash after each close",
               "Engineering sample only - NOT real XAUUSD returns or paper account equity")
    ax.plot(list(x), [float(v) for v in balances], color=GOLD, linewidth=2.6, marker="o")
    ax.fill_between(list(x), [float(start)]*len(balances),
                    [float(v) for v in balances], color=GOLD, alpha=.13)
    ax.set_xticks(list(x), ["Start", "1", "2", "3", "4"])
    ax.yaxis.set_major_formatter(FuncFormatter(lambda n, pos: f"${n:,.0f}"))
    fig.tight_layout(pad=1.7)
    fig.savefig(path, dpi=155, facecolor="white")
    plt.close(fig)


def cost_chart(path: Path, report: dict) -> None:
    items = report["research"]["cost_stress"]
    names = [v["name"].title() for v in items]
    candidate = [float(_decimal(v["candidate_net_usd"])) for v in items]
    naive = [float(_decimal(v["independently_scheduled_same_session_long_net_usd"]))
             for v in items]
    x = list(range(len(items)))
    fig, ax = plt.subplots(figsize=(9.4, 3.5), dpi=155)
    _fig_theme(ax, "Cost stress: candidate vs independent clock strategy",
               "Separate synthetic source and time window - not an observed market edge")
    ax.bar([k-.18 for k in x], candidate, width=.35, color=GOLD, label="Candidate")
    ax.bar([k+.18 for k in x], naive, width=.35, color="#657990",
           label="Independently scheduled naive long")
    ax.set_xticks(x, names)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda n, pos: f"${n:,.0f}"))
    ax.legend(frameon=False, loc="upper right", fontsize=7)
    fig.tight_layout(pad=1.7)
    fig.savefig(path, dpi=155, facecolor="white")
    plt.close(fig)


def _build_pdf(path: Path, report: dict, curve: Path, stress: Path) -> None:
    W, H = A4
    navy = colors.HexColor(MIDNIGHT)
    slate = colors.HexColor(DARK)
    accent = colors.HexColor(GOLD)
    quiet = colors.HexColor(MUTED)
    line = colors.HexColor(BORDER)
    styles = {
        "title": ParagraphStyle("d30title", fontName=FONT_BOLD, fontSize=23,
                                leading=27, textColor=navy, spaceAfter=10),
        "h": ParagraphStyle("d30h", fontName=FONT_BOLD, fontSize=12, leading=16,
                             textColor=navy, spaceAfter=9, spaceBefore=12),
        "body": ParagraphStyle("d30body", fontName=FONT, fontSize=8.7,
                                leading=13.2, textColor=colors.HexColor(TEXT),
                                spaceAfter=8),
        "small": ParagraphStyle("d30small", fontName=FONT, fontSize=7.2,
                                 leading=10.8, textColor=quiet, spaceAfter=6),
        "banner": ParagraphStyle("d30banner", fontName=FONT_BOLD, fontSize=9,
                                  leading=13, textColor=navy, alignment=TA_CENTER),
        "label": ParagraphStyle("d30label", fontName=FONT_BOLD, fontSize=7.5,
                                 leading=11, textColor=navy, alignment=TA_LEFT),
    }
    doc = SimpleDocTemplate(str(path), pagesize=A4, topMargin=64,
                            bottomMargin=48, leftMargin=43, rightMargin=43,
                            title="AIDY - auditable reference research report",
                            author="AIDY Strategy Lab - GoldThinker research engine")
    avail = W-86

    def cells(rows, widths, *, header=True):
        table = Table(rows, colWidths=widths, repeatRows=1 if header else 0,
                      hAlign="LEFT")
        cmd = [
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("FONTSIZE", (0, 0), (-1, -1), 7.5),
            ("LEFTPADDING", (0, 0), (-1, -1), 9),
            ("RIGHTPADDING", (0, 0), (-1, -1), 9),
            ("TOPPADDING", (0, 0), (-1, -1), 9),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
            ("LINEBELOW", (0, -1), (-1, -1), .5, line),
        ]
        if header:
            cmd.extend([
                ("BACKGROUND", (0, 0), (-1, 0), slate),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white,
                                                      colors.HexColor("#F6F8FB")]),
            ])
        else:
            cmd.append(("ROWBACKGROUNDS", (0, 0), (-1, -1),
                        [colors.white, colors.HexColor("#F6F8FB")]))
        table.setStyle(TableStyle(cmd))
        return table

    def image(p):
        from PIL import Image as PILImage
        with PILImage.open(p) as raw:
            ratio = raw.height / raw.width
        return Image(str(p), width=avail, height=avail*ratio)

    m = report["research"]["accounting"]
    stories = [
        Paragraph("AIDY / GoldThinker", styles["small"]),
        Paragraph("Auditable strategy research", styles["title"]),
        Paragraph("INTERNAL SYNTHETIC ENGINEERING REFERENCE - NOT REAL GOLD PROFITS",
                  styles["banner"]),
        Spacer(1, 11),
        Paragraph(
            "The AIDY engine provides research evidence for future GoldThinker system "
            "pages. This sample uses one independently replayed <b>synthetic</b> cash "
            "journal and separately sourced historical gold <b>BID-only</b> data. "
            "It is NOT an approved strategy, real brokerage account, forward paper "
            "account or investment performance record.", styles["body"]
        ),
        cells([
            ["Original capital", "Net result", "Ending cash", "Completed trades"],
            [f"${m['initial_capital_usd']}", f"+${m['net_profit_usd']}",
             f"${m['final_cash_usd']}", str(m["closed_trades"])],
        ], [avail/4]*4),
        Paragraph("Realised performance by UTC reporting period", styles["h"]),
    ]
    rows = [["Period", "Net closed P&L (USD)", "Closed trades", "Wins"]]
    for period in PERIODS:
        obj = report["research"]["periods"][period]
        rows.append([period.replace("_", " ").title(),
                     obj["realised_net_pnl_usd"],
                     str(obj["closed_trades"]), str(obj["wins"])])
    stories.extend([
        cells(rows, [avail*.24, avail*.32, avail*.22, avail*.22]),
        Spacer(1, 9),
        image(curve),
        PageBreak(),
        Paragraph("Transaction-level audit", styles["title"]),
        Paragraph("Original internal synthetic SQLite cash ledger. Every number is "
                  "reconciled to original run and verified journal SHA256; all "
                  "trades below are illustrative.", styles["small"]),
    ])
    trades = [["Trade ID", "Closed (UTC)", "Gross", "Fees", "Net"]]
    for tr in report["research"]["trades"]:
        trades.append([
            tr["position_id"].replace("research_trade_", "#"),
            tr["closed_at_utc"].replace("T", " ")[:16],
            tr["gross_usd"], tr["costs_usd"], tr["net_usd"],
        ])
    stories.extend([
        cells(trades, [avail*.14, avail*.34, avail*.17, avail*.17, avail*.18]),
        Paragraph("Spread, slippage and cash-charge stress", styles["h"]),
        Paragraph("Candidate and independently scheduled clock controls are from "
                  "separate, predeclared synthetic quotation windows. These are "
                  "cost-accounting diagnostics, not demonstrated XAUUSD alpha.",
                  styles["small"]),
        image(stress),
    ])
    scenarios = [["Scenario", "Candidate net", "Naive long", "Candidate minus naive"]]
    for sc in report["research"]["cost_stress"]:
        scenarios.append([
            sc["name"].title(),
            sc["candidate_net_usd"],
            sc["independently_scheduled_same_session_long_net_usd"],
            sc["candidate_minus_scheduled_naive_usd"],
        ])
    stories.extend([
        Spacer(1, 9),
        cells(scenarios, [avail*.19, avail*.25, avail*.25, avail*.31]),
        PageBreak(),
        Paragraph("Evidence and source audit", styles["title"]),
        Paragraph("AIDY nine-factor research rating: ORANGE / INSUFFICIENT "
                  "INDEPENDENT TRADING EVIDENCE. Numeric score: UNAVAILABLE.",
                  styles["body"]),
        Paragraph("No customer subscription or connection, no verified "
                  "forward PAPER balance, and no GoldThinker Elite 20 combined "
                  "portfolio performance is asserted.", styles["body"]),
    ])
    factor_rows = [["Factor (owner policy)", "Weight", "Qualified result"]]
    for factor, weight in report["research"]["evidence_rating"]["factor_weights"]:
        finding = next(x for x in report["research"]["evidence_rating"]["factor_scores"]
                       if x["factor"] == factor)
        factor_rows.append([
            factor.replace("_", " ").title(), str(weight),
            finding["status"] + " - no independently qualified points",
        ])
    stories.extend([
        cells(factor_rows, [avail*.42, avail*.12, avail*.46]),
        Paragraph("Provenance appendix - original pinned sources", styles["h"]),
    ])
    sources = report["provenance"]["source_sha256"]
    for label, digest in sorted(sources.items()):
        stories.append(Paragraph(
            f"<b>{label.replace('_', ' ').title()}:</b> <font size='6'>{digest}</font>",
            styles["small"],
        ))
    stories.extend([
        Paragraph("Original canonical run and export integrity", styles["h"]),
        Paragraph(f"<b>Run:</b> {report['run_id']}", styles["small"]),
        Paragraph(f"<b>Canonical JSON SHA256:</b> "
                  f"{report['canonical_result_sha256']}", styles["small"]),
        Paragraph("Supporting exports: complete trades.csv, cost_scenarios.csv, "
                  "equity_curve.png, cost_stress.png, canonical_result.json "
                  "and byte-hashed manifest.json. All PDF displayed financial "
                  "figures are from the same immutable canonical result.",
                  styles["small"]),
        Paragraph("LIMITATIONS: Historical real data are retrospective BID-price "
                  "direction observations only, NOT broker executable BID/ASK fills. "
                  "Synthetic positive returns must never be marketed as a profitable "
                  "strategy. Portfolio balances cannot be obtained by adding "
                  "separate accounts. Owner approval and original publication rights "
                  "are mandatory before GoldThinker customer use.", styles["small"]),
    ])

    def background(canvas, document):
        canvas.saveState()
        canvas.setFillColor(navy)
        canvas.rect(0, H-34, W, 34, stroke=0, fill=1)
        canvas.setFillColor(accent)
        canvas.setFont(FONT_BOLD, 11)
        canvas.drawString(43, H-22, "AIDY  /  GOLDTHINKER RESEARCH")
        canvas.setStrokeColor(colors.HexColor(BORDER))
        canvas.line(43, 38, W-43, 38)
        canvas.setFillColor(quiet)
        canvas.setFont(FONT, 7)
        canvas.drawString(43, 27, "INTERNAL REFERENCE  |  NOT INVESTMENT OR LIVE TRADING RESULTS")
        canvas.drawRightString(W-43, 27, f"Page {document.page}")
        canvas.restoreState()

    doc.build(stories, onFirstPage=background, onLaterPages=background)


def _check_csv(path: Path, header: tuple[str, ...]) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if tuple(reader.fieldnames or ()) != header:
            raise ValueError("CSV header or source column order changed")
        rows = list(reader)
    if not rows or any(set(x) != set(header) for x in rows):
        raise ValueError("missing or invalid full CSV rows")
    return rows


def verify_export_bundle(out: Path, receipt: dict) -> dict:
    report = validate_research_receipt(receipt)
    manifest = json.loads((out/"manifest.json").read_text(encoding="utf-8"))
    if (manifest["schema"] != SCHEMA
            or manifest["canonical_result_sha256"] != report["canonical_result_sha256"]
            or manifest["canonical_run_id"] != report["run_id"]
            or manifest["reference_research_only"] is not True):
        raise ValueError("report export provenance was substituted")
    for name, entry in manifest["files"].items():
        if (name != Path(name).name or name not in {
            "canonical_result.json", "trades.csv", "cost_scenarios.csv",
            "equity_curve.png", "cost_stress.png", "research_report.pdf",
            "report_preview_page1.png",
        }):
            raise ValueError("unexpected export file")
        blob = (out/name).read_bytes()
        if _hash(blob) != entry["sha256"] or len(blob) != entry["bytes"]:
            raise ValueError("export file SHA / length mismatch")
    if len(manifest["files"]) != 7:
        raise ValueError("export bundle is missing mandatory files")
    if json.loads((out/"canonical_result.json").read_text(encoding="utf-8")) != report:
        raise ValueError("JSON report does not agree with journal-derived contract")
    trades = _check_csv(out/"trades.csv", TRADE_HEADER)
    if len(trades) != len(report["research"]["trades"]):
        raise ValueError("full trade history omitted from CSV")
    source = report["provenance"]["source_sha256"]
    for i, tr in enumerate(trades):
        original = report["research"]["trades"][i]
        if (tr["canonical_result_sha256"] != report["canonical_result_sha256"]
                or tr["verified_journal_tip_sha256"] != source["day24_sqlite_journal"]
                or tr["trade_number"] != str(i+1)
                or _decimal(tr["gross_usd"]) != _decimal(original["gross_usd"])
                or _decimal(tr["allocated_cash_costs_usd"])
                != _decimal(original["costs_usd"])
                or _decimal(tr["net_usd"]) != _decimal(original["net_usd"])):
            raise ValueError("CSV original transaction or journal SHA mismatch")
    net = sum((_decimal(t["net_usd"]) for t in trades), Decimal(0))
    if net != _decimal(report["research"]["accounting"]["net_profit_usd"]):
        raise ValueError("CSV trades do not reconcile to PDF/JSON net return")
    scenarios = _check_csv(out/"cost_scenarios.csv", STRESS_HEADER)
    if len(scenarios) != len(report["research"]["cost_stress"]):
        raise ValueError("scenario CSV is missing rows")
    for i, row in enumerate(scenarios):
        original = report["research"]["cost_stress"][i]
        if (row["quote_snapshot_sha256"] != source["day25_synthetic_quotes"]
                or row["cost_policy_sha256"] != source["day25_cost_policy"]
                or row["scenario"] != original["name"]
                or _decimal(row["candidate_net_usd"])
                != _decimal(original["candidate_net_usd"])
                or _decimal(row["candidate_minus_scheduled_naive_usd"])
                != _decimal(original["candidate_minus_scheduled_naive_usd"])):
            raise ValueError("scenario CSV source or numeric parity mismatch")
    pdf = PdfReader(str(out/"research_report.pdf"))
    if not 3 <= len(pdf.pages) <= 8:
        raise ValueError("incomplete or paginated incorrectly research PDF")
    text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    must_print = (
        report["run_id"], report["canonical_result_sha256"],
        "NOT REAL GOLD PROFITS", "GoldThinker Elite 20",
        "9.00", "13.00", "10013.00", "UNAVAILABLE",
    )
    if any(s not in text for s in must_print):
        raise ValueError("PDF lacks original journal numbers or scientific warnings")
    from PIL import Image as PILImage
    for name in ("equity_curve.png", "cost_stress.png", "report_preview_page1.png"):
        with PILImage.open(out/name) as image:
            image.verify()
        with PILImage.open(out/name) as image:
            if image.width < 1000 or image.height < 400:
                raise ValueError("report visual is too small")
    return {
        "status": "PASS",
        "source_canonical_sha256": report["canonical_result_sha256"],
        "source_run_id": report["run_id"],
        "verified_complete_trades": len(trades),
        "verified_cost_stress_scenarios": len(scenarios),
        "verified_pdf_pages": len(pdf.pages),
        "pdf_csv_json_net_profit_usd": str(net.quantize(MONEY)),
        "actual_forward_paper_pnl_available": False,
        "real_strategy_alpha_qualified": False,
        "goldthinker_master_portfolio_pnl_available": False,
        "file_shas": {k: v["sha256"] for k, v in manifest["files"].items()},
    }


def build_export_bundle(receipt: dict, out: Path) -> dict:
    report = validate_research_receipt(receipt)
    if not isinstance(out, Path):
        raise ValueError("destination must be an approved Path")  # noqa: TRY004
    out.mkdir(parents=True, exist_ok=True)
    (out/"canonical_result.json").write_text(
        json.dumps(report, indent=2, sort_keys=True)+"\n", encoding="utf-8"
    )
    (out/"trades.csv").write_bytes(trade_csv(report))
    (out/"cost_scenarios.csv").write_bytes(scenarios_csv(report))
    equity_curve(out/"equity_curve.png", report)
    cost_chart(out/"cost_stress.png", report)
    _build_pdf(out/"research_report.pdf", report,
               out/"equity_curve.png", out/"cost_stress.png")
    # Render the ACTUAL finished PDF via independent pdfium, not a designed
    # substitute image. Inspect all pages for blank/failed raster output.
    import pypdfium2 as pdfium
    from PIL import ImageStat
    original = pdfium.PdfDocument(str(out/"research_report.pdf"))
    if not 3 <= len(original) <= 8:
        raise ValueError("finished PDF failed length/raster sanity requirements")
    for index in range(len(original)):
        img = original[index].render(scale=2.0).to_pil().convert("RGB")
        if img.width < 800 or img.height < 1000 or not (
            ImageStat.Stat(img).stddev[0] > 6
        ):
            raise ValueError("PDF page rendered empty or unreadable")
        if index == 0:
            img.save(out/"report_preview_page1.png")
    filenames = (
        "canonical_result.json", "trades.csv", "cost_scenarios.csv",
        "equity_curve.png", "cost_stress.png", "research_report.pdf",
        "report_preview_page1.png",
    )
    manifest = {
        "schema": SCHEMA, "canonical_run_id": report["run_id"],
        "canonical_result_sha256": report["canonical_result_sha256"],
        "reference_research_only": True,
        "files": {
            name: {"sha256": _hash((out/name).read_bytes()),
                   "bytes": (out/name).stat().st_size} for name in filenames
        },
    }
    (out/"manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True)+"\n", encoding="utf-8"
    )
    return verify_export_bundle(out, receipt)
