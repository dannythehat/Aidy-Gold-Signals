"""Generate customer-grade, evidence-labelled PDF from a verified S010 run only.

No demo figures: every number comes from full_independent_research.json,
which itself must record 12 native historical source months and a complete
trade ledger. This is independent modelled backtesting, not investor advice,
a live account statement or exact publisher tick-level replication.
"""
from __future__ import annotations

import hashlib
import html
import json
from datetime import datetime
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    HRFlowable,
    Image,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from aidy.strategy_lab_s010_backtest import STARTING_USD

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT/"artifacts/strategy_lab/s010_paid_customer_example"
PDF=OUT/"GOLDTHINKER_S010_2025_Full_Independent_Research_Report.pdf"
INK=colors.HexColor("#16212c")
GOLD=colors.HexColor("#a58345")
GREY=colors.HexColor("#506172")
PAPER=colors.HexColor("#f6f7f5")
PALE=colors.HexColor("#e7e9e9")
GOOD=colors.HexColor("#176d64")
BAD=colors.HexColor("#aa4a42")


def fmt(n, symbol="$", digits=2):
    return f"{symbol}{float(n):,.{digits}f}"


def safe(value):
    return html.escape(str(value),quote=True)


def make_plot(data,stem,title,ylabel,kind="line"):
    OUT.mkdir(parents=True,exist_ok=True)
    img=OUT/(stem+".png")
    fig,ax=plt.subplots(figsize=(10.4,3.6),dpi=125)
    fig.patch.set_facecolor("#ffffff")
    ax.set_facecolor("#ffffff")
    if kind=="bar":
        keys=[x[0] for x in data]
        vals=[float(x[1]) for x in data]
        bar= ax.bar(keys,vals,color=["#b15142" if v<0 else "#315f64" for v in vals],
                    width=0.58)
        ax.bar_label(bar,labels=[f"{v:+.1f}%" for v in vals],fontsize=7,padding=3)
        ax.axhline(0,color="#888",lw=0.6)
        ax.tick_params(axis="x",rotation=45)
    else:
        vals=[float(p[1]) for p in data]
        ax.plot(range(len(vals)),vals,color="#16475a" if stem=="s010_equity" else "#b15142",lw=1.65)
        if stem=="s010_drawdown":ax.fill_between(range(len(vals)),vals,0,color="#e3bdb7",alpha=.45)
        ax.set_xlim(0,max(1,len(vals)-1))
        n=len(data)
        xs=list(range(0,n,max(1,n//10)))
        if xs[-1]!=n-1:xs.append(n-1)
        ax.set_xticks(xs,[data[i][0] for i in xs],fontsize=7)
    ax.grid(axis="y",linewidth=.4,color="#d6dadb")
    ax.spines[["top","right","left"]].set_visible(False)
    ax.tick_params(axis="y",labelsize=8)
    ax.set_title(title,loc="left",fontsize=12,fontweight="bold",color="#182634",pad=15)
    ax.set_ylabel(ylabel,fontsize=8,color="#536273")
    fig.tight_layout(pad=2.0)
    fig.savefig(img,bbox_inches="tight")
    plt.close(fig)
    return img


def run():
    data=json.loads((OUT/"full_independent_research.json").read_text(encoding="utf-8"))
    if (data.get("status")!="PASS_REAL_12_MONTH_HISTORICAL_RESEARCH"
            or len(data.get("source_receipts",[]))!=12
            or data.get("reference_account_usd")!=10000
            or data.get("original_publisher_bid_ask_ticks_available")
            or data.get("exact_original_tick_engine_parity")
            or data.get("independently_qualified_profitable")
            or any(len(s["monthly"])!=12 for s in data["scenarios"].values())):
        raise ValueError("Not a real 12-month research source; refuse to publish PDF")
    base=data["scenarios"]["published_3p28x_base"]
    stress=data["scenarios"]["published_3p28x_stress"]
    low=data["scenarios"]["unlevered_1x_base"]
    if base["closed_trades"]!=len(base["trades"]) or not base["equity"]:
        raise ValueError("Trade ledger absent or incomplete")

    styles=getSampleStyleSheet()
    styles.add(ParagraphStyle(name="CoverKicker",fontName="Helvetica-Bold",
                              fontSize=11,leading=16,textColor=GOLD,spaceAfter=15))
    styles.add(ParagraphStyle(name="CoverTitle",fontName="Helvetica-Bold",
                              fontSize=30,leading=37,textColor=INK,spaceAfter=21))
    styles.add(ParagraphStyle(name="SectionGT",fontName="Helvetica-Bold",fontSize=17,
                              leading=23,textColor=INK,spaceBefore=10,spaceAfter=12))
    styles.add(ParagraphStyle(name="SubGT",fontName="Helvetica-Bold",fontSize=10,
                              leading=15,textColor=INK,spaceBefore=11,spaceAfter=7))
    styles.add(ParagraphStyle(name="BodyGT",fontName="Helvetica",fontSize=8.8,
                              leading=14,textColor=INK,spaceAfter=8))
    styles.add(ParagraphStyle(name="SmallGT",fontName="Helvetica",fontSize=7.4,
                              leading=11,textColor=GREY,spaceAfter=6))
    styles.add(ParagraphStyle(name="MetricGT",fontName="Helvetica-Bold",fontSize=13,
                              leading=20,textColor=INK))
    styles.add(ParagraphStyle(name="WarnGT",fontName="Helvetica-Bold",fontSize=9,
                              leading=14,textColor=BAD,spaceAfter=12))
    st=styles
    story=[]
    def P(s,style="BodyGT"):
        story.append(Paragraph(s,st[style]))
    def gap(h=8):story.append(Spacer(1,h))
    def table(headers,rows,widths=None,fontsize=7.5):
        head=[Paragraph(safe(x),st["SmallGT"]) for x in headers]
        values=[head]
        for row in rows:
            values.append([Paragraph(safe(x),st["SmallGT"]) for x in row])
        t=Table(values,colWidths=widths,repeatRows=1,hAlign="LEFT")
        t.setStyle(TableStyle([
            ("BACKGROUND",(0,0),(-1,0),PAPER),
            ("TEXTCOLOR",(0,0),(-1,0),INK),
            ("LINEBELOW",(0,0),(-1,0),1,GOLD),
            ("LINEBELOW",(0,1),(-1,-1),.3,PALE),
            ("VALIGN",(0,0),(-1,-1),"TOP"),
            ("TOPPADDING",(0,0),(-1,-1),6),
            ("BOTTOMPADDING",(0,0),(-1,-1),6),
            ("LEFTPADDING",(0,0),(-1,-1),5),
            ("RIGHTPADDING",(0,0),(-1,-1),5),
        ]))
        story.append(t)
    def section(name,subtitle=None):
        P(safe(name),"SectionGT")
        if subtitle:P(safe(subtitle),"SmallGT")
    def chart(path):
        from PIL import Image as PillowImage
        im=PillowImage.open(path);ratio=im.height/im.width
        story.append(Image(str(path),width=175*mm,height=175*mm*ratio))
    def new():story.append(PageBreak())

    # Cover
    gap(30)
    P("GOLDTHINKER  /  INDEPENDENT STRATEGY RESEARCH","CoverKicker")
    P("Gold trading system<br/>S010: MA Crossover + RSI","CoverTitle")
    story.append(HRFlowable(width="100%",thickness=2,color=GOLD))
    gap(19)
    P("FULL CUSTOMER-STYLE HISTORICAL RESEARCH REPORT","CoverKicker")
    P("Test period: 1 January - 31 December 2025 (12 calendar months)<br/>"
      "Instrument: XAU/USD | Native M1 BID -> independently derived H1 bars<br/>"
      "Reference account: USD 10,000 | Source-published leverage: 3.28x<br/>"
      "Source: AluminumShark / Tick-Backtest (MIT), independently implemented.")
    gap(22)
    P("<b>Evidence class: REAL HISTORICAL BID-BASED RESEARCH; MODELLED EXECUTION COSTS.</b>",
      "WarnGT")
    P("This is not a broker statement, an audited live result, a sealed out-of-sample "
      "study or a claim that the author's tick-data backtest was reproduced exactly. "
      "The publisher's original BID/ASK tick CSV is unavailable; spread, "
      "slippage and commission are scenario assumptions. "
      "The original strategy has no protective stop loss.")
    gap(12)
    P("AIDY is the independent research engine. GoldThinker is the future customer-facing "
      "brand. This example is not approved for production, paper or live trading.","SmallGT")
    P("Report hash (input research evidence): "+safe(data["research_sha256"]),"SmallGT")
    new()

    section("01  Executive review")
    P("The study used original historical XAUUSD BID prices and the documented S010 "
      "MA12/MA34 with RSI14 signal filters, without reoptimisation. "
      "Execution is the next available H1 candle OPEN after signal confirmation; "
      "the source's own results use different underlying tick data and backtest mechanics.")
    table(["Reference measure","Independent base case","Meaning"],[
        ("Starting capital",fmt(base["initial_usd"]),"Hypothetical USD"),
        ("Ending marked equity",fmt(base["ending_marked_equity_usd"]),"Includes any unrealised position"),
        ("Marked P&L",fmt(base["net_marked_pnl_usd"]),"Net of assumed costs"),
        ("Return",fmt(base["marked_return_pct"],symbol="",digits=2)+"%","Not live return"),
        ("Maximum equity drawdown",fmt(base["max_marked_drawdown_pct"],symbol="",digits=2)+"%","Marked hourly, includes floating P&L"),
        ("Completed trades",base["closed_trades"],"From realised entry-exit records"),
        ("Wins / losses / breakevens",f'{base["wins"]} / {base["losses"]} / {base["breakeven"]}',"Net of assumed costs"),
        ("Win rate",f'{base["win_rate_pct"]}%' if base["win_rate_pct"] is not None else "Undefined","Based only on closed trades"),
        ("Profit factor",str(base["profit_factor"]) if base["profit_factor"] is not None else "Undefined","After assumed execution costs"),
        ("Execution expenses paid",fmt(base["sum_paid_execution_cost_usd"]),"Assumed spread/slippage/commission"),
    ],widths=[58*mm,43*mm,70*mm])
    gap(14)
    P("VERDICT  /  RESEARCH-ONLY, NOT INDEPENDENTLY QUALIFIED","WarnGT")
    P("Even favourable historical returns would NOT establish a commercial system. "
      "Original tick-ASK parity, broker time alignment, financing and margin "
      "liquidation, walk-forward qualification, held-out unseen data, account "
      "security and licence/operational acceptance are outstanding.")
    if base["open_position"]:
        P("An open/unrealised position remains at the historical period end. Its "
          "floating P&L is inside ending equity but is NOT a closed trade.","WarnGT")
    new()

    section("02  Strategy specification / frozen source")
    table(["Component","Source-pinned definition"],[
        ("Source repository","https://github.com/AluminumShark/Tick-Backtest"),
        ("Author files","main.py; src/strategy.py; src/backtest_engine.py"),
        ("Market","XAUUSD; independent HistData BID, not source author's ticks"),
        ("Signal interval","One hour (H1), completed candle only"),
        ("Entry condition","SMA12 crosses ABOVE SMA34, with RSI14 < 70; long only"),
        ("Exit condition","SMA12 crosses BELOW SMA34, with RSI14 > 30; flat"),
        ("Holding policy","Retain existing state until qualifying opposite crossover"),
        ("Protective stop","NONE in original published main.py"),
        ("Sizing","3.28x marked account equity at entry; oz held until qualifying exit"),
        ("RSI math","Pandas EWM(com=13,min_periods=14), source-compatible"),
        ("Execution clock","Signal at bar close, execute at next available bar open"),
        ("Ask / slippage / fees","Scenario-implied; NOT observed from historical ticks"),
        ("Reoptimisation","NO; original posted settings unchanged"),
    ],widths=[45*mm,126*mm])
    gap(12)
    P("Potentially material source difference: the author builds H1 from BID/ASK tick MID "
      "prices and uses percentage-return accounting; this independent model builds "
      "H1 using original HistData native BID M1, enters at next open, "
      "accounts in USD/oz and models ASK using an assumed spread. "
      "As a result the entry/exit counts and reported P&L may legitimately differ.")
    new()

    # Charts
    section("03  Full-year marked equity", "Source: 2025 verified BID -> next-open execution. USD 10,000 start.")
    eq=base["equity"]
    stride=max(1,len(eq)//700)
    sampled=[(x["time"][:10],x["equity"]) for x in eq[::stride]]
    if sampled[-1][0]!=eq[-1]["time"][:10]:
        sampled.append((eq[-1]["time"][:10],eq[-1]["equity"]))
    chart(make_plot(sampled,"s010_equity","Marked account equity","USD"))
    P("Curve marks account equity at the end of each verified H1 candle. "
      "Cost charges occur on entry and exit. Unclosed exposure is marked, not counted "
      "as a completed winning trade. A broker margin call is NOT included.","SmallGT")
    vals=pd.Series([float(x["equity"]) for x in eq])
    dd=((vals/vals.cummax().clip(lower=STARTING_USD))-1)*100
    chart(make_plot([(x["time"][:10],float(d)) for x,d in zip(eq[::stride],dd.iloc[::stride])],
                    "s010_drawdown","Peak-to-trough marked drawdown","%"))
    new()

    section("04  Monthly distribution and trading activity")
    mon=base["monthly"]
    chart(make_plot([(m["month"][5:],m["return_pct"]) for m in mon],
        "s010_monthly_returns","Monthly marked account return","%",kind="bar"))
    table(["Month 2025","Start USD","End USD","P&L USD","Return","Trades closed"],[
        (m["month"],fmt(m["starting_equity"]),fmt(m["ending_equity"]),
         fmt(m["net_change_usd"]),f'{m["return_pct"]:+.2f}%',m["closed_trades"])
        for m in mon
    ],widths=[28*mm,31*mm,31*mm,31*mm,24*mm,26*mm])
    P("Monthly returns include marked floating equity and can differ from total "
      "closed trade profit in that month. No month is omitted for poor returns.","SmallGT")
    new()

    section("05  Execution-cost sensitivity and benchmarks")
    table(["Case","End USD","Return","Max DD","Closed trades"],[
        (s["costs"]["label"]+" / "+str(s["leverage"])+"x",
         fmt(s["ending_marked_equity_usd"]),
         f'{s["marked_return_pct"]:+.2f}%',
         f'{s["max_marked_drawdown_pct"]:.2f}%',
         s["closed_trades"])
        for s in (base,stress,low)
    ],widths=[63*mm,31*mm,24*mm,24*mm,29*mm])
    gap(12)
    table(["Cost element (per 1 oz)","Base scenario","Stress scenario"],[
      ("BUY ask markup (spread)",fmt(base["costs"]["spread_usd_per_oz"]),
       fmt(stress["costs"]["spread_usd_per_oz"])),
      ("Adverse slip, EACH side",fmt(base["costs"]["slippage_usd_per_oz_each_side"]),
       fmt(stress["costs"]["slippage_usd_per_oz_each_side"])),
      ("Round-trip commission",fmt(base["costs"]["commission_usd_per_oz_round_trip"]),
       fmt(stress["costs"]["commission_usd_per_oz_round_trip"])),
      ("Swap / financing / margin call","EXCLUDED","EXCLUDED"),
    ],widths=[66*mm,51*mm,54*mm])
    P("Unleveraged buy-and-hold of XAUUSD BID over available beginning/end prices: "
      f'<b>{base["gold_buy_hold_1x_pct"]:+.2f}%</b>. Benchmark is directional '
      "and not exposure-, risk- or financing-matched; it does not imply alpha.")
    P("Caution: without actual historical broker ASK ticks, commission schedules, "
      "overnight financing or margin rules these outputs are cost assumptions, "
      "not broker-net customer payouts. The stress case measures sensitivity to "
      "cost assumptions, not a worst-case tail risk bound.")
    new()

    section("06  Full chronological closed-trade ledger",
            "Each row uses confirmed-entry next H1 open and a later qualifying-exit next H1 open. Amounts USD.")
    trades=base["trades"]
    if trades:
        cols=[23*mm,28*mm,28*mm,24*mm,21*mm,21*mm,26*mm]
        rows=[]
        for t in trades:
            rows.append([t["id"],t["entry_utc"][:16].replace("T"," "),
                         t["exit_utc"][:16].replace("T"," "),
                         f'{t["units_oz"]:.3f}',fmt(t["gross_usd"]),
                         fmt(t["spread_slippage_commission_usd"]),
                         fmt(t["net_usd"])])
        table(["#","Entry UTC","Exit UTC","Oz","Gross","Costs","Net"],rows,widths=cols)
    else:
        P("No completed source-rule exits within the pre-registered period.")
    new()

    section("07  Source-quality and reproducibility audit")
    P(f'Native original BID data: <b>{sum(r["observed_native_m1_rows"] for r in data["source_receipts"]):,} '
      f'M1 records</b>. Complete usable H1 candles: <b>{base["bars"]:,}</b>. '
      "Only complete 60-minute source-aligned UTC hours are admitted; "
      "weekend market closures were not filled with fabricated candles.")
    table(["UTC month","Native M1","Valid H1","Partial excluded","Source hash prefix"],[
      (r["calendar_month_utc"],f'{r["observed_native_m1_rows"]:,}',
       r["complete_h1"],r["partial_hour_excluded"],
       r["monthly_source_sha256"][:16]+"...")
      for r in data["source_receipts"]
    ],widths=[28*mm,30*mm,28*mm,32*mm,53*mm])
    gap(12)
    P("Original source: aidy-signals.aidy_analytics_test.research_candles; "
      "source=histdata; price_basis=bid; source EST_FIXED_UTC_MINUS_05 "
      "converted to UTC; original native M1 source identity checked per "
      "monthly query before H1 aggregation. SHA256 source payload, source "
      "archive hashes and separate BigQuery job IDs are preserved in "
      "the downloadable accompanying provenance JSON.")
    P("Research SHA256: "+safe(data["research_sha256"]),"SmallGT")
    new()

    section("08  Independent research verdict and client risk disclosures")
    P("The purpose of this example is to show what an evidence-first customer "
      "report looks like, including losses, unfavourable periods and limitations. "
      "It does not certify that the strategy has a repeatable trading advantage.")
    table(["Required independent gate","Present result"],[
        ("Fully sourced entry and exit rules","PASS for posted long-only MA/RSI main.py"),
        ("Full 12-month real BID candles","Verified native HistData historical rows"),
        ("Costed trade-level audit trail","Modelled BID/ASK spread, slip and commission"),
        ("Historical ASK and real broker costs","NOT VERIFIED"),
        ("Original author's tick data parity","NOT VERIFIED - original tick CSV absent"),
        ("Protective stop / position hard loss limit","ABSENT IN ORIGINAL SYSTEM"),
        ("Point-in-time sealed out-of-sample test","NOT SATISFIED; historical period public"),
        ("Walk-forward / independently held-out research","NOT SATISFIED"),
        ("Real market execution and financing","NOT TESTED"),
        ("AIDY commercial strategy certification","NOT GRANTED"),
        ("Customer live / paper order authority","NOT GRANTED; zero broker orders"),
    ],widths=[74*mm,97*mm])
    gap(12)
    P("The author stated that 2025 was an out-of-sample validation year for "
      "its own train-on-2024 study; this NEW independent evaluation uses "
      "publicly published parameters and does NOT make 2025 an unseen sample. "
      "Historical results can be harmed by market changes, spread variation, "
      "slippage, large gaps and margin calls. No guaranteed financial outcome.")
    P("STATUS: RESEARCH COMPLETE FOR THIS DEFINED MODEL; NOT A QUALIFIED OR "
      "CUSTOMER-DEPLOYABLE GOLDTHINKER STRATEGY.","WarnGT")
    new()

    section("09  Evidence package / handover reference")
    P("This PDF is accompanied by the machine-readable full account curve, "
      "every completed trade, three cost scenarios, source archive receipts, "
      "original H1 BID bars and original-source links. "
      "The evidence is retained for independent challenge, not substituted "
      "with decorative demo statistics.")
    P("Original strategy source: https://github.com/AluminumShark/Tick-Backtest")
    P("Google Drive research register: AIDY Gold Strategy Lab - source ID S010.")
    P("Reproduction method: AIDY S010 2025 fixed source parameters / "
      "per-month BigQuery native M1 -> complete H1 only -> Pandas source "
      "RSI and SMA -> next-open bid-based cash and mark-to-market USD book.")
    P("All figures in this PDF were populated from the generated "
      "full_independent_research.json; if that file is absent or lacks "
      "12 months, PDF generation MUST abort rather than create invented results.")
    P("Report issuance date: "+datetime.now().strftime("%d %B %Y")+".")
    gap(14)
    P("GoldThinker  /  AIDY STRATEGY LAB","CoverKicker")

    def footer(canvas,doc):
        canvas.saveState()
        width,_=A4
        canvas.setStrokeColor(PALE)
        canvas.line(19*mm,15*mm,width-19*mm,15*mm)
        canvas.setFont("Helvetica",7)
        canvas.setFillColor(GREY)
        canvas.drawString(19*mm,11*mm,"AIDY INDEPENDENT RESEARCH  |  HISTORICAL MODELLED COSTS  |  NOT LIVE")
        canvas.drawRightString(width-19*mm,11*mm,"PAGE "+str(doc.page))
        canvas.restoreState()

    doc=BaseDocTemplate(str(PDF),pagesize=A4,
        rightMargin=19*mm,leftMargin=19*mm,
        topMargin=16*mm,bottomMargin=19*mm,
        title="GoldThinker - S010 2025 Full Independent Strategy Research",
        author="AIDY Strategy Lab / GoldThinker",subject="Historical research, 2025, no broker orders")
    frame=Frame(19*mm,19*mm,172*mm,259*mm,id="normal",leftPadding=0,
                rightPadding=0,topPadding=0,bottomPadding=0)
    doc.addPageTemplates(PageTemplate(id="Pages",frames=frame,onPage=footer))
    doc.build(story)
    print("S010_PDF_CREATED",json.dumps({
        "name":PDF.name,"bytes":PDF.stat().st_size,
        "pdf_sha256":hashlib.sha256(PDF.read_bytes()).hexdigest(),
        "input_source_sha256":data["research_sha256"],"trades":len(trades),
        "real_calendar_months":12,
        "customer_report_has_verified_broker_ask":False,
        "customer_report_has_actual_strategy_profit_certification":False,
    },sort_keys=True),flush=True)


if __name__=="__main__":
    run()
