"""Full source-ledger AIDY S001 2025/26 two-period PDF."""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pypdf import PdfReader
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image, LongTable, PageBreak, Paragraph, SimpleDocTemplate, Spacer, TableStyle,
)

BASE=Path("artifacts/strategy_lab/s001_full_2025_2026")
DARK=colors.HexColor("#172535")
GOLD=colors.HexColor("#b89448")
PALE=colors.HexColor("#eef2f7")
def cash(x):
    return "$"+f"{x:,.2f}"
def pct(x):
    return "N/A" if x is None else f"{x:.3f}%"

def visualise(year,c):
    series=[x[1] for x in c["equity_trace"]]
    peak=10000.
    dd=[]
    for val in series:
        peak=max(peak,val)
        dd.append(100*(val/peak-1))
    for name,values,label in (
        ("equity",series,"Marked equity USD"),
        ("drawdown",dd,"Max marked drawdown %"),
        ("monthly",[x["net_pnl_usd"] for x in c["monthly"]],"Monthly realised net USD")
    ):
        fig,ax=plt.subplots(figsize=(10.5,3.2),dpi=140)
        if name=="monthly":
            ax.bar(range(len(values)),values)
            ax.set_xticks(range(len(values)),[x["month"][5:] for x in c["monthly"]])
        else:ax.plot(values,linewidth=1)
        ax.grid(axis="y",alpha=.2)
        ax.set_title(year+" "+label)
        fig.tight_layout()
        fig.savefig(BASE/(year+"_"+name+".png"))
        plt.close(fig)

def build():
    r=json.loads((BASE/"S001_two_period_full_aidy_evidence.json").read_text())
    assert r["status"]=="TWO_PERIOD_AUTHENTIC_TICK_SOURCE_MODEL_COMPLETE__MT5_PARITY_NOT_VERIFIED"
    assert r["unique_source_months"]==22
    p={year:r["independent_period_results"][year]["scenarios"]
       ["published_default_vwap_exit"] for year in ("2025","2026")}
    for year,data in p.items():
        assert len(data["monthly"])==(12 if year=="2025" else 9)
        visualise(year,data)
    st=getSampleStyleSheet()
    st.add(ParagraphStyle(name="T",fontName="Helvetica-Bold",fontSize=23,
        leading=28,spaceAfter=15,textColor=DARK))
    st.add(ParagraphStyle(name="H",fontName="Helvetica-Bold",fontSize=15,
        leading=19,spaceBefore=7,spaceAfter=9,textColor=DARK))
    st.add(ParagraphStyle(name="B",fontName="Helvetica",fontSize=9.2,
        leading=13,spaceAfter=8))
    st.add(ParagraphStyle(name="S",fontName="Helvetica",fontSize=7.2,
        leading=10,spaceAfter=4))
    body=lambda t:Paragraph(t,st["B"])
    head=lambda t:Paragraph(t,st["H"])
    small=lambda t:Paragraph(t,st["S"])
    story=[]
    def tab(rows,widths,fs=7.8):
        x=LongTable([[str(cell) for cell in row] for row in rows],colWidths=widths,repeatRows=1,hAlign="LEFT")
        x.setStyle(TableStyle([
            ("BACKGROUND",(0,0),(-1,0),DARK),
            ("TEXTCOLOR",(0,0),(-1,0),colors.white),
            ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
            ("FONTSIZE",(0,0),(-1,-1),fs),
            ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,PALE]),
            ("TOPPADDING",(0,0),(-1,-1),4),
            ("BOTTOMPADDING",(0,0),(-1,-1),4),
            ("VALIGN",(0,0),(-1,-1),"TOP"),
        ]))
        story.append(x)
    def section(text):
        story.append(PageBreak());story.append(head(text))
    def art(year,kind):
        story.append(Image(str(BASE/(year+"_"+kind+".png")),
                           width=166*mm,height=65*mm))
    def page(canvas,doc):
        w,h=A4
        canvas.saveState()
        canvas.setFillColor(DARK)
        canvas.rect(0,h-15*mm,w,15*mm,stroke=0,fill=1)
        canvas.setFont("Helvetica-Bold",9)
        canvas.setFillColor(GOLD)
        canvas.drawString(20*mm,h-9*mm,"GOLDTHINKER  |  THE GOLD EDGE HUNT")
        canvas.setFont("Helvetica",7.5)
        canvas.setFillColor(colors.grey)
        canvas.drawString(20*mm,11*mm,"RESEARCH MODEL, NOT LIVE OR BROKER P&L")
        canvas.drawRightString(w-20*mm,11*mm,"PAGE "+str(doc.page))
        canvas.restoreState()
    story.extend([
        Spacer(1,25*mm),Paragraph("S001 / GOLD EA",st["T"]),
        head("Two-period original-source trading-system audit"),
        body("FULL YEAR 2025 AND JANUARY TO SEPTEMBER 2026"),
        Spacer(1,8*mm),
        body("Original third-party research: eamonnkennedy93-blip/GoldEA. "
          "AIDY independently reconstructs the default M15 sweep-and-reclaim "
          "signal, confirmed H1/H4 swings, anchored source-volume weighted "
          "VWAP exit and author-defined ATR stop. NO invented 2R target."),
        body("Both years use the SAME original archived HistData BID/ASK source "
          "ticks. Each starts with a separate hypothetical $10,000 account "
          "and pays modelled costs. There is no combining years or systems."),
        body("Critical qualification: recorded HistData tick count is NOT "
          "the author's Vantage or MT5 native broker tick volume, so "
          "exact live EA equivalence is NOT verified. AIDY uses "
          "realistic next-M15-open entry after signal closure."),
        Spacer(1,15*mm),
        small("Report evidence SHA256: "+r["sha256"]),
        small("Real historical source SHA256: "+r["verified_combined_m15_sha256"]),
    ])
    section("01 / Historical results and AIDY qualification")
    tab([["MEASURE","2025 FULL","2026 JAN-SEP"]]+[
        [label,formatting(p["2025"][key]),formatting(p["2026"][key])]
        for label,key,formatting in (
          ("Initial reference capital","start_usd",cash),
          ("Net realised model P&L","net_usd",cash),
          ("End model account","end_usd",cash),
          ("Return","return_pct",pct),
          ("Closed trades","closed_trades",str),
          ("Wins","wins",str),("Losses","losses",str),
          ("Win rate","win_rate_pct",pct),
          ("Net trade profit factor","profit_factor",str),
          ("Max marked equity drawdown","max_marked_drawdown_pct",pct),
          ("Total execution charges","total_assumed_cost_usd",cash),
        )
    ],[86*mm,41*mm,41*mm],8.1)
    story.append(Spacer(1,7*mm))
    story.append(body("AIDY EVIDENCE GRADE: ORANGE / RESEARCH ONLY. "
        "The reconstructed original default exit has been tested for both "
        "periods but publisher/MT5-native parity and untouched out-of-sample "
        "qualification remain outstanding. Not authorised for paper or live."))
    for year in ("2025","2026"):
        section(year+" / 02 Marked account equity")
        story.append(body("Every genuine complete M15 candle contributes "
             "to the marked equity path. Drawdowns include open trade exposure."))
        art(year,"equity")
        section(year+" / 03 Marked peak-to-trough drawdown")
        art(year,"drawdown")
        story.append(body("Marked price risk is NOT Vantage broker liquidation, "
             "margin stopout or real order-slippage history."))
        section(year+" / 04 Every monthly trading result")
        tab([["MONTH","CLOSED","WINS","LOSSES","NET USD"]]+[
            [x["month"],x["closed_trades"],x["wins"],x["losses"],
             cash(x["net_pnl_usd"])] for x in p[year]["monthly"]
        ],[39*mm,29*mm,27*mm,27*mm,46*mm])
        story.append(Spacer(1,8*mm));art(year,"monthly")
    section("08 / Matched baseline and transaction cost stress")
    tab([["SOURCE-PERIOD EXPERIMENT","TRADES","NET USD","DD %","PF"]]+[
        [year+" "+label,
         x["closed_trades"],cash(x["net_usd"]),
         pct(x["max_marked_drawdown_pct"]),x["profit_factor"]]
        for year in ("2025","2026")
        for label,key in (
            ("Default VWAP-cross","published_default_vwap_exit"),
            ("Naive H1/H4 flip","naive_htf_flip_control"),
            ("Double costs","double_observed_spread_slippage")
        )
        for x in [r["independent_period_results"][year]["scenarios"][key]]
    ],[79*mm,18*mm,30*mm,23*mm,18*mm],7.4)
    story.append(Spacer(1,9*mm))
    story.append(body("The source's naive higher-timeframe direction flip "
        "provides a separately costed baseline. Doubling actual "
        "source-observed initial spreads and adverse execution slippage "
        "tests fragility. No fixed 2R or hidden optimization."))
    section("09 / Published original rule semantics")
    for statement in (
        "M15 sweep/reclaim execution. H1 5 left, 3 right confirmed pivot; "
        "H4 3 left, 2 right pivot; last two confirmed highs and lows "
        "must agree on direction. Right-side pivots cannot be used early.",
        "Previous UK-calendar-day extrema and finished Asia 00:00-08:00 "
        "and London opening 08:00-09:00 ranges in Europe/London time.",
        "Pending wick sweep remains until the market closes back "
        "through its level by at least 50 percent of the reclaim "
        "candle's own range; pending states reset daily.",
        "VWAP anchored after the latest confirmed H1 swing, calculated "
        "from typical source M15 price, weighted by authenticated "
        "HistData source tick counts (NOT identical broker MT5 volume).",
        "Publisher's actual indicators.py Wilder ATR smoothing, "
        "including the unusual original unnormalised initial seed.",
        "Original published DEFAULT EXIT: VWAP crossover, protective "
        "ATR stop or session close. No fixed R target in the original "
        "Python backtest default. Source code's same-candle entry "
        "is conservatively moved to first following M15 opening in AIDY.",
        "No M5 entry refinement, ADX, VWAP proximity or volatility-ratio "
        "gates, as these are optional/rejected unpublished additions.",
    ):story.append(body("- "+statement))
    section("10 / $10,000 accounting and execution")
    for statement in (
        "Separate $10,000 hypothetical account at 1 January of each band; "
        "1 percent of current account equity allocated as nominal "
        "stop risk; one position; 100 oz per lot, lot step 0.01, "
        "10x maximum nominal market exposure.",
        "Bid OHLC and recorded HistData source open ASK per complete M15; "
        "one source-recorded round-trip spread; $0.10/oz adverse "
        "slippage at EACH side; $7/standard-lot round trip commission.",
        "Source-correct next-bar entry and conservative stop-first "
        "intrabar priority; a stop jumped by a candle gap executes "
        "at the adverse source opening, not a falsely favourable stop.",
        "Financing assumed zero for the flat-session model. "
        "No attested Vantage broker commission, swap, margin, "
        "full native MT5 tick-volume, entry rejection or stopout evidence.",
        "All monthly realised net P&L reconciles to the full "
        "chronological immutable trade rows. Losing months retained.",
    ):story.append(body("- "+statement))
    section("11 / Research caveats and independent recommendation")
    for statement in r["limitation_notes"]:
        story.append(body("- "+statement))
    section("12 / All 22 original authenticated source archives")
    tab([["SOURCE MONTH","TICK ROWS","M15 BARS","EXCLUDED","ZIP SHA PREFIX"]]+[
        [x["fixed_est_month"],x["source_tick_rows"],
         x["complete_m15"],x["excluded_partial_m15"],
         x["original_zip_sha256"][:12]]
        for x in r["market_source_receipts"]
    ],[28*mm,31*mm,28*mm,27*mm,54*mm],7.2)
    for year in ("2025","2026"):
        section(year+" / FULL CLOSED-TRADE AUDIT LEDGER")
        story.append(body("Every trade is shown below in chronological "
            "sequence, including losers and friction. The matching "
            "source evidence CSV adds exact signal time, lot, "
            "stop distance, observed quote spread, gross USD, "
            "fees and running account balance."))
        trades=p[year]["trades"]
        if not trades:
            story.append(body("NO CLOSED TRADES"))
        else:
            tab([["#","ENTRY UTC","SIDE","LOT","EXIT UTC","WHY","NET USD","BALANCE"]]+[
                [i,t["entry_time"][5:16],
                 "LONG" if t["direction"]==1 else "SHORT",
                 t["lot"],t["exit_time"][5:16],
                 "VWAP" if t["exit_reason"]=="native_volume_sourced_vwap_cross"
                 else t["exit_reason"],
                 cash(t["net_pnl"]),cash(t["balance_after"])]
                for i,t in enumerate(trades,1)
            ],[11*mm,28*mm,17*mm,14*mm,28*mm,23*mm,22*mm,25*mm],6.55)
    story.append(Spacer(1,10*mm))
    story.append(body("END. Results are research model evidence, "
        "NOT broker profits, licence approval or trading authorisation."))
    outfile=BASE/"GOLDTHINKER_S001_Full_2025_2026_Original_Rules_AIDY_Report.pdf"
    pdf=SimpleDocTemplate(str(outfile),pagesize=A4,
        topMargin=22*mm,bottomMargin=20*mm,leftMargin=19*mm,
        rightMargin=19*mm,title="S001 Original Source Rules 2025-2026 AIDY GoldThinker",
        author="AIDY Strategy Lab")
    pdf.build(story,onFirstPage=page,onLaterPages=page)
    pages=len(PdfReader(str(outfile)).pages)
    if pages<14 or outfile.stat().st_size<20000:
        raise ValueError("Full two-period PDF not accepted")
    print("S001_REAL_TWO_PERIOD_PDF",json.dumps({
        "pages":pages,"bytes":outfile.stat().st_size,
        "2025_net_usd":p["2025"]["net_usd"],
        "2026_net_usd":p["2026"]["net_usd"]}),flush=True)

if __name__=="__main__":
    build()
