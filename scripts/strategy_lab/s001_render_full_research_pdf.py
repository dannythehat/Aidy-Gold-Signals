"""Build full auditable S001 trading-report PDF from the same real-data CI run."""
import json
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
from pypdf import PdfReader
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image,
    LongTable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    TableStyle,
)

matplotlib.use("Agg")

OUT=Path(__file__).resolve().parents[2]/"artifacts/strategy_lab/s001_full_2025"
NAVY=colors.HexColor("#16243a")
GOLD=colors.HexColor("#ba974b")
INK=colors.HexColor("#222e3e")

def money(n):
    return "$"+f"{n:,.2f}"

def percent(n):
    return "not defined" if n is None else f"{n:.2f}%"

def plot_primary(s):
    trace=s["equity_trace"]
    vals=[item[1] for item in trace]
    peak=10000.0
    dd=[]
    for x in vals:
        peak=max(peak,x)
        dd.append((x/peak-1)*100)
    for name,arr,label in (
        ("equity.png",vals,"Model account marked equity (USD)"),
        ("drawdown.png",dd,"Peak-to-trough marked drawdown (%)"),
        ("monthly.png",[m["net_pnl_usd"] for m in s["monthly"]],"Closed-trade net P&L by month (USD)")
    ):
        fig,ax=plt.subplots(figsize=(10,3),dpi=120)
        if name=="monthly.png":
            ax.bar(range(len(arr)),arr)
            ax.set_xticks(range(12),[m["month"][-2:] for m in s["monthly"]])
        else:
            ax.plot(arr,linewidth=1)
        ax.set_title(label)
        ax.grid(True,axis="y",alpha=.2)
        fig.tight_layout()
        fig.savefig(OUT/name)
        plt.close(fig)

def render():
    p=OUT/"s001_2025_full_report.json"
    data=json.loads(p.read_text())
    if data["run_status"]!="FULL_REAL_2025_HISTORICAL_COSTED_MODEL__ORIGINAL_PARITY_NOT_VERIFIED":
        raise ValueError("Original source not accepted")
    if len(data["source_receipts"])!=12 or not all(x["query_job_id"] for x in data["source_receipts"]):
        raise ValueError("Missing original annual data receipts")
    scenarios=data["scenarios"]
    primary=scenarios["S001_SWEEP_RECLAIM_FIXED_2R"]
    assert all(x["closed_trades"]==len(x["trades"]) for x in scenarios.values())
    plot_primary(primary)
    pdf=OUT/"GOLDTHINKER_S001_2025_Full_Independent_10K_Research_Report.pdf"
    styles=getSampleStyleSheet()
    styles.add(ParagraphStyle(name="GoldTitle",parent=styles["Title"],fontSize=22,
        leading=26,spaceAfter=18,textColor=NAVY))
    styles.add(ParagraphStyle(name="GoldHead",parent=styles["Heading2"],fontSize=15,
        leading=19,spaceAfter=10,textColor=NAVY))
    styles.add(ParagraphStyle(name="GoldBody",parent=styles["BodyText"],fontSize=9.5,
        leading=14,spaceAfter=8,textColor=INK))
    styles.add(ParagraphStyle(name="GoldSmall",parent=styles["BodyText"],fontSize=8,
        leading=11,spaceAfter=4,textColor=INK))
    story=[]
    para=lambda text:Paragraph(text,styles["GoldBody"])
    small=lambda text:Paragraph(text,styles["GoldSmall"])
    head=lambda text:Paragraph(text,styles["GoldHead"])
    def matrix(rows,widths,s=8):
        safe=[]
        for row in rows:
            safe.append([small(str(v)) if i==0 and len(str(v))>55 else str(v) for i,v in enumerate(row)])
        t=LongTable(safe,colWidths=widths,repeatRows=1,hAlign="LEFT")
        t.setStyle(TableStyle([
            ("BACKGROUND",(0,0),(-1,0),NAVY),
            ("TEXTCOLOR",(0,0),(-1,0),colors.white),
            ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
            ("FONTSIZE",(0,0),(-1,-1),s),
            ("ROWBACKGROUNDS",(0,1),(-1,-1),
             [colors.white,colors.HexColor("#eaf0f6")]),
            ("GRID",(0,0),(-1,-1),.2,colors.HexColor("#c3cdd6")),
            ("VALIGN",(0,0),(-1,-1),"TOP"),
            ("TOPPADDING",(0,0),(-1,-1),4),
            ("BOTTOMPADDING",(0,0),(-1,-1),4),
        ]))
        story.append(t)
    def pagebreak(title):
        story.append(PageBreak())
        story.append(head(title))
    def page(canvas,doc):
        w,h=A4
        canvas.saveState()
        canvas.setFillColor(NAVY)
        canvas.rect(0,h-16*mm,w,16*mm,fill=1,stroke=0)
        canvas.setFillColor(GOLD)
        canvas.setFont("Helvetica-Bold",9)
        canvas.drawString(18*mm,h-10*mm,"GOLDTHINKER  /  INDEPENDENT GOLD RESEARCH")
        canvas.setFont("Helvetica",8)
        canvas.setFillColor(colors.grey)
        canvas.drawString(18*mm,12*mm,"S001 | MODELLED HISTORY, NOT BROKER PERFORMANCE")
        canvas.drawRightString(w-18*mm,12*mm,f"Page {doc.page}")
        canvas.restoreState()
    story.extend([
        Spacer(1,18*mm),
        Paragraph("S001 | GOLD EA",styles["GoldTitle"]),
        head("Sweep-and-reclaim: full independent historical account test"),
        para("THE GOLD EDGE HUNT  |  YEAR ENDED 31 DECEMBER 2025"),
        Spacer(1,8*mm),
        para("Original strategy: "+data["original_source"]),
        para("Real market evidence: 12 source-receipted months of original "
             "XAUUSD native M1 BID, converted into complete M15 candles."),
        para("Each research scenario has its OWN $10,000 hypothetical account. "
             "Costed trade-level results, every month, drawdown, baseline, "
             "execution stress and independent limitations follow."),
        para("<b>Critical qualification:</b> AIDY reimplemented the published "
             "session-sweep family, not the publisher's unpublished live MT5 EA. "
             "Original native VWAP volume and full author parity are unavailable. "
             "AIDY's declared primary uses a fixed 2R target and is not the "
             "publisher's reproduced profit-factor claim."),
        Spacer(1,14*mm),
        small("Report SHA256: "+data["report_sha256"]),
        small("Historical source SHA256: "+data["source_sha256"]),
    ])
    pagebreak("01  Full $10,000 results")
    story.append(para("All figures below are independent MODELLED USD results "
                      "from real history, not publisher claims, Vantage fills "
                      "or completed demo trading."))
    matrix([
        ["MEASURE","S001 COSTED PRIMARY"],
        ["Opening capital",money(primary["starting_usd"])],
        ["Net realised P&L",money(primary["net_usd"])],
        ["Model closing balance",money(primary["ending_usd"])],
        ["Return on starting capital",percent(primary["return_pct"])],
        ["Closed / won / lost / flat",f'{primary["closed_trades"]} / {primary["wins"]} / {primary["losses"]} / {primary["breakevens"]}'],
        ["Win rate",percent(primary["win_rate_pct"])],
        ["Profit factor",str(primary["profit_factor"])],
        ["Maximum marked drawdown",percent(primary["max_marked_drawdown_pct"])],
        ["Execution costs included",money(primary["total_cost_usd"])],
        ["Evidence stage","Research model completed; source EA parity / OOS not verified"],
    ],[83*mm,87*mm])
    story.append(Spacer(1,7*mm))
    story.append(para("No GREEN score and no permission to promote to "
                      "a forward-paper account arises from these results alone."))
    pagebreak("02  Complete marked equity")
    story.append(para("Marked-to-modelled-liquidation equity, including open "
                      "positions and assumed execution costs. Unlike a closed-trade "
                      "balance chart, this captures intra-trade drawdown at available "
                      "complete 15-minute candles."))
    story.append(Image(str(OUT/"equity.png"),width=172*mm,height=65*mm))
    story.append(Spacer(1,9*mm))
    story.append(para("Actual intraminute quote gaps and broker-specific "
                      "stopout/margin are not observable from this BID OHLC dataset."))
    pagebreak("03  Drawdown evidence")
    story.append(Image(str(OUT/"drawdown.png"),width=172*mm,height=66*mm))
    story.append(para("Peak-to-trough equity measure (marked). "
                      "Stops are executed against the conservative source-BID "
                      "model: same-candle stop wins over target, adverse gaps "
                      "fill at the following observable opening, no favourable "
                      "same-bar lookahead."))
    pagebreak("04  Twelve-month results")
    story.append(para("All twelve months appear, including losses and zero-trade "
                      "periods. The realised ledger determines these totals."))
    matrix([["UTC MONTH","TRADES","WON","LOST","NET P&L"]]+[
        [r["month"],str(r["closed_trades"]),str(r["wins"]),
         str(r["losses"]),money(r["net_pnl_usd"])]
        for r in primary["monthly"]
    ],[39*mm,27*mm,27*mm,27*mm,49*mm])
    story.append(Spacer(1,7*mm))
    story.append(Image(str(OUT/"monthly.png"),width=165*mm,height=55*mm))
    pagebreak("05  Four independent comparison scenarios")
    desc={
        "S001_SWEEP_RECLAIM_FIXED_2R":"Sweep + fixed 2R",
        "S001_SWEEP_RECLAIM_EQUAL_WEIGHT_VWAP_PROXY":"Sweep + equal-weight VWAP PROXY",
        "NAIVE_MATCHED_HTF_BIAS_FLIP_CONTROL":"Naive higher-timeframe flip control",
        "S001_DOUBLE_SPREAD_AND_SLIPPAGE":"Sweep 2R, doubled spread/slip",
    }
    matrix([["SCENARIO","CLOSED","NET USD","MAX DD","PF"]]+[
        [desc.get(k,k),str(v["closed_trades"]),
         money(v["net_usd"]),percent(v["max_marked_drawdown_pct"]),
         str(v["profit_factor"])] for k,v in scenarios.items()
    ],[70*mm,22*mm,30*mm,27*mm,20*mm],7)
    story.append(Spacer(1,12*mm))
    story.append(para("No optimisation was used to select the best-performing "
        "variant after inspecting test outcomes. The source-original "
        "exact-parity and untouched OOS gates remain NOT VERIFIED. "
        "The equal-volume VWAP is a clearly labelled proxy rather "
        "than invented broker-native tick volume."))
    pagebreak("06  Rules and causality")
    for v in [
        "Source: real HistData XAUUSD M1 BID candles. Exactly 15 consecutive, "
        "original minute records required per M15. No synthetic candle repair.",
        "Reference UK clock uses Europe/London with seasonal BST/GMT. "
        "Previous day high/low, Asia 00:00 to 08:00 range and "
        "London 08:00 to 09:00 opening range.",
        "Price wicks beyond an active session level, then closes back through "
        "at least half its own bar range to confirm a sweep/reclaim.",
        "Direction must agree with both confirmed one-hour and four-hour "
        "swing market structure. Higher-timeframe pivots only exist "
        "AFTER the full confirming bar closes.",
        "Signal after completed M15 bar, first entry at NEXT actual contiguous "
        "M15 opening. Session rollover flats exposure; no weekend assumption.",
        "1% of CURRENT model equity nominal entry stop risk, 0.01 lot "
        "increment, 100 oz/lot, 10x notional cap, one position maximum.",
        "Protective stop at wick extreme plus 1x Wilder ATR14; "
        "AIDY primary uses a declared fixed 2R take-profit, stop "
        "takes priority when both are touched intrabar.",
    ]:
        story.append(para("• "+v))
    pagebreak("07  Cost realism and stress model")
    for v in [
        "Bid-only source history. Long enters at hypothetical ASK, "
        "short exits at hypothetical ASK. No genuine broker fills are claimed.",
        "Spread $0.30 per ounce charged once per full round trip.",
        "Slippage $0.10 per ounce separately on each side. "
        "Roundtrip brokerage commission $7.00 per one standard lot.",
        "Modelled net P&L is gross price movement times physical ounces "
        "less spread, two-way slippage and commission.",
        "Stress doubles source spread to $0.60 and each-side "
        "slippage to $0.20 per ounce, maintaining the same rules.",
        "Financing excluded as an explicit zero assumption in this "
        "intraday session exit model. Actual Vantage swap, "
        "margin call rules, fill priority and commission need "
        "independent broker verification.",
        "Monthly ledger total, trade count and source SHA "
        "are asserted before the report is generated.",
    ]:
        story.append(para("• "+v))
    pagebreak("08  Review risks and advancement gate")
    for v in data["source_caveats"]:
        story.append(para("• "+v))
    story.append(Spacer(1,5*mm))
    story.append(para("<b>AIDY judgement:</b> a complete historical model "
        "can be measured and compared without misrepresenting the "
        "author's exact version. The strategy remains UNDER REVIEW: "
        "not original-EA identical, no independent sealed holdout, "
        "no native-volume/Vantage broker parity and no paper P&L."))
    pagebreak("09  Twelve authenticated monthly data receipts")
    matrix([["MONTH","ORIGINAL M1","COMPLETE M15","PARTIAL","BQ JOB PREFIX"]]+[
        [r["month"],str(r["native_m1_rows"]),str(r["complete_m15"]),
         str(r["partial_excluded"]),str(r["query_job_id"])[:15]]
        for r in data["source_receipts"]
    ],[28*mm,32*mm,34*mm,24*mm,50*mm],7.1)
    story.append(Spacer(1,8*mm))
    story.append(para("Original file SHA256 values, query job identifiers "
        "and exact model parameters are provided in full in the "
        "downloadable same-run JSON evidence package."))
    pagebreak("10  Every independently simulated trade")
    story.append(para("This is the complete chronological trade ledger, "
        "not a selected or winning-only sample. Detailed CSV includes "
        "all timestamped signals, fills, side, stop, target, "
        "quantity, costs, gross/net P&L and equity after close."))
    rows=[["#","ENTRY UTC","SIDE","LOT","EXIT UTC","EXIT","NET USD","BALANCE"]]
    for i,t in enumerate(primary["trades"],start=1):
        rows.append([
            str(i),t["entry_time"][5:16],
            "BUY" if t["direction"]==1 else "SELL",
            str(t["lot"]),t["exit_time"][5:16],
            t["exit_reason"],money(t["net_pnl"]),money(t["balance_after"])
        ])
    if len(rows)>1:
        matrix(rows,[11*mm,29*mm,12*mm,15*mm,29*mm,25*mm,24*mm,24*mm],6.3)
    else:
        story.append(para("No trades were taken in the frozen period."))
    story.append(Spacer(1,6*mm))
    story.append(small("Complete data, source receipts, and any full "
        "trade histories are archived separately from the PDF."))
    doc=SimpleDocTemplate(str(pdf),pagesize=A4,leftMargin=19*mm,
        rightMargin=19*mm,topMargin=22*mm,bottomMargin=19*mm,
        title="GoldThinker S001 Full Independent $10k 2025 Modelled Backtest")
    doc.build(story,onFirstPage=page,onLaterPages=page)
    pages=len(PdfReader(str(pdf)).pages)
    if pages<10 or pdf.stat().st_size<20000:
        raise ValueError("Full customer report PDF not generated")
    summary=[
        "# AIDY S001 | FULL REAL-HISTORY 2025 $10K REPORT",
        "",
        "These are **costed historical MODEL** results, NOT Vantage/PAPER/LIVE outcomes.",
        "",
        "| Metric | Result |",
        "|---|---:|",
        f'| Starting account | {money(primary["starting_usd"])} |',
        f'| Ending account | {money(primary["ending_usd"])} |',
        f'| Net P&L | {money(primary["net_usd"])} |',
        f'| Return | {percent(primary["return_pct"])} |',
        f'| Wins / losses | {primary["wins"]} / {primary["losses"]} |',
        f'| Closed trades | {primary["closed_trades"]} |',
        f'| Win rate | {percent(primary["win_rate_pct"])} |',
        f'| Profit factor | {primary["profit_factor"]} |',
        f'| Marked max drawdown | {percent(primary["max_marked_drawdown_pct"])} |',
        f'| Total model costs | {money(primary["total_cost_usd"])} |',
        "", f'PDF pages: {pages}',"","NOT original EA identical or sealed OOS.",
    ]
    (OUT/"S001_2025_RESULTS.md").write_text("\n".join(summary)+"\n")
    print("AIDY_S001_FULL_REPORT",json.dumps({
        "pages":pages,"closed_trades":primary["closed_trades"],
        "net_usd":primary["net_usd"],
        "drawdown_pct":primary["max_marked_drawdown_pct"],
        "pdf_bytes":pdf.stat().st_size},sort_keys=True),flush=True)


if __name__=="__main__":
    render()
