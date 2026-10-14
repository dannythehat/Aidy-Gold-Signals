"""Independent, frozen GT-BIBLE RC1 parity engine. RESEARCH ONLY.

An independently written decision interpreter (not importing GoldThinker code).
Pinned data: a15ec4cec1c8c0f06e53befe4b22b55c75da000c
No network, trade execution, AIDY live data, or broker connections.
"""
from __future__ import annotations
import hashlib
import json
from fractions import Fraction as F
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "gt_bible_rc1_vendor" / "bible"
GT_COMMIT = "a15ec4cec1c8c0f06e53befe4b22b55c75da000c"
BUNDLE = "5dd0fdd440d673f358887b490f4b411f059b0fcc0b6955655da7796cc3394c80"


def N(v):
    return F(str(v))


def text_num(n, dp=0):
    if n is None:
        return None
    n = N(n)
    for i in range(dp, 13):
        v = n * 10 ** i
        if v.denominator == 1:
            k = int(v)
            sign = "-" if k < 0 else ""
            z = str(abs(k)).rjust(i+1, "0")
            return sign + (z[:-i] + "." + z[-i:] if i else z)
    return f"{n.numerator}/{n.denominator}"


def floor_to(x,tick):
    return x // tick * tick


def ceil_to(x,tick):
    return -((-x) // tick) * tick


def load():
    idx = json.loads((ROOT/"INDEX.json").read_text(encoding="utf-8"))
    if idx["bundle_sha256"] != BUNDLE:
        raise ValueError("Pinned bundle hash differs")
    ms = {}
    hs = {}
    for e in idx["manifests"]:
        m = json.loads((ROOT.parent / e["file"]).read_text(encoding="utf-8"))
        h = hashlib.sha256(json.dumps(m,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
        if h != e["sha256"]:
            raise ValueError(f"Manifest digest differs: {e['manifest_id']}")
        hs[e["manifest_id"]] = h
        ms[e["manifest_id"]] = m
    total = hashlib.sha256(json.dumps(hs,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
    if total != BUNDLE or len(ms) != 10:
        raise ValueError("Pinned manifest bundle mismatch")
    return ms


def shape(pid,side,bars,atr):
    z = []
    def chk(label,pred):
        if not pred:
            z.append(label)
    a=bars[0]
    ar=a["h"]-a["l"]
    if not all(b["h"]>b["l"] for b in bars):
        return False,["NO_SHAPE"],z
    if pid == "P03":
        body=abs(a["c"]-a["o"])
        lo=min(a["o"],a["c"])-a["l"]
        hi=a["h"]-max(a["o"],a["c"])
        chk("R>=0.50ATR",ar>=N(".50")*atr)
        chk("B<=0.33R",body<=N(".33")*ar)
        if side=="BULL":
            chk("LW>=0.66R",lo>=N(".66")*ar)
            chk("UW<=0.10R",hi<=N(".10")*ar)
            chk("C>=L+0.75R",a["c"]>=a["l"]+N(".75")*ar)
        else:
            chk("UW>=0.66R",hi>=N(".66")*ar)
            chk("LW<=0.10R",lo<=N(".10")*ar)
            chk("C<=H-0.75R",a["c"]<=a["h"]-N(".75")*ar)
    elif pid in ("P06","P07"):
        b=bars[1]
        pa=abs(a["c"]-a["o"])
        pb=abs(b["c"]-b["o"])
        if side=="BULL":
            chk("K1 bear",a["c"]<a["o"])
            chk("K2 bull",b["c"]>b["o"])
            chk("O2<=C1",b["o"]<=a["c"])
            chk("C2>=O1",b["c"]>=a["o"])
        else:
            chk("K1 bull",a["c"]>a["o"])
            chk("K2 bear",b["c"]<b["o"])
            chk("O2>=C1",b["o"]>=a["c"])
            chk("C2<=O1",b["c"]<=a["o"])
        chk("B2>B1",pb>pa)
        chk("B1>0.05R1",pa>N(".05")*ar)
    elif pid in ("P09","P22"):
        b=bars[1]
        chk("H2<H1",b["h"]<a["h"])
        chk("L2>L1",b["l"]>a["l"])
        if z:
            return False,["NO_SHAPE"],z
        if pid=="P22":
            for c in bars[2:5]:
                up=c["h"]>a["h"]
                down=c["l"]<a["l"]
                if not up and not down:
                    continue
                if up and down:
                    return False,["SWEEP_BOTH_SIDES"],z
                if (up and side=="BULL") or (down and side=="BEAR"):
                    return False,["SWEEP_WRONG_SIDE"],z
                if not (a["l"]<=c["c"]<=a["h"]):
                    return False,["NO_SWEEP"],z
                return True,[],z
            return False,["NO_SWEEP"],z
    else:
        raise ValueError(pid)
    return not z, ([] if not z else ["NO_SHAPE"]), z


def at_phrase(s,bars,own):
    lows=[b["l"] for b in bars]
    highs=[b["h"] for b in bars]
    lower=lambda:N(own["lower"]["lo"])
    upper=lambda:N(own["upper"]["hi"])
    options={
        "pin low":lambda:lows[0],"pin high":lambda:highs[0],
        "min(L1, L2)":lambda:min(lows[:2]),"max(H1, H2)":lambda:max(highs[:2]),
        "mother low (L1)":lambda:lows[0],"mother high (H1)":lambda:highs[0],
        "min(L1, L2, Lk)":lambda:min(lows),"max(H1, H2, Hk)":lambda:max(highs),
        "min(pin low, lower boundary lo)":lambda:min(lows[0],lower()),
        "max(pin high, upper boundary hi)":lambda:max(highs[0],upper()),
        "min(L1, L2, lower boundary lo)":lambda:min(lows[0],lows[1],lower()),
        "max(H1, H2, upper boundary hi)":lambda:max(highs[0],highs[1],upper()),
        "mother low":lambda:lows[0],"mother high":lambda:highs[0],
        "sweep candle low":lambda:lows[-1],"sweep candle high":lambda:highs[-1],
        "min(sweep candle low, lower boundary lo)":lambda:min(lows[-1],lower()),
        "max(sweep candle high, upper boundary hi)":lambda:max(highs[-1],upper()),
        "pattern extreme low":lambda:min(lows),"pattern extreme high":lambda:max(highs)}
    if s not in options:
        raise ValueError("Unexpected manifest phrase "+s)
    return options[s]()


def decide(m,common,s):
    side=s["side"]; tf=s["tf"]; d=1 if side=="BULL" else -1
    tick=N(s["tick"]); atr=N(s["atr"])
    dp=len(s["tick"].split(".")[1]) if "." in s["tick"] else 0
    bars=[{k:N(b[k]) for k in ("o","h","l","c")} for b in s["bars"]]
    out=dict(decision="NO_TRADE",reasons=[],failing_clauses=[],level_sources=[],
             arm=None,order=None)
    reasons=out["reasons"]
    if tf in m["timeframes"]["signal"]:
        out["arm"]="PRIMARY"
    elif tf in m["timeframes"].get("research_arm",[]):
        out["arm"]="RESEARCH_ARM"
    else:
        reasons.append("TF_NOT_ALLOWED")
        return out
    geo=m["geometry"]
    if "any_of" in geo:
        geo=next(x for x in geo["any_of"] if x["pattern_id"]==s["pattern_id"])
    pid=geo["pattern_id"]
    if isinstance(pid,dict):
        pid=pid[side]
    ok,why,failed=shape(pid,side,bars,atr)
    out["failing_clauses"]=failed
    if not ok:
        reasons.extend(why)
        return out
    out["extreme"]=text_num(at_phrase(geo["extreme"][side],bars,s.get("own") or {}),dp)
    own=s.get("own") or {}
    ms=m["market_structure"]
    if own.get("state") not in ms["own_state"][side]:
        reasons.append("OWN_STATE")
    if "own_position" in ms and own.get("position")!=ms["own_position"][side]:
        reasons.append("NOT_AT_BOUNDARY")
    align=ms["alignment"]
    if align in ("TREND","RANGE"):
        expected=common["higher_timeframe"]["alignment_map"][tf]
        states={k:(s.get("htf") or {}).get(k,{}).get("state") for k in expected}
        if any(v is None for v in states.values()):
            reasons.append("HTF_UNAVAILABLE")
        elif align=="TREND" and any(v!=("TREND_UP" if d==1 else "TREND_DOWN") for v in states.values()):
            reasons.append("HTF_DISAGREE")
        elif align=="RANGE" and any(v in ("CHOP","UNDETERMINED","TREND_DOWN" if d==1 else "TREND_UP") for v in states.values()):
            reasons.append("HTF_DISAGREE")
    elif align!="NONE":
        raise ValueError("Unexpected alignment "+align)
    lv=m["level"]
    if lv["set"]=="proven_weekly_level":
        if s.get("proven_weekly_level"):
            out["level_sources"]=["PROVEN_W1"]
        else:
            reasons.append("NO_LEVEL")
    elif lv["set"]=="range_level_set":
        if "NOT_AT_BOUNDARY" not in reasons and "OWN_STATE" not in reasons:
            out["level_sources"]=["RANGE_BOUNDARY"]
    else:
        allowed=common["levels"][lv["set"]]
        present=set(s.get("levels_at_extreme") or [])
        out["level_sources"]=[x for x in allowed if x in present]
        if len(out["level_sources"])<lv["minimum"]:
            reasons.append("NO_LEVEL")
    if reasons:
        return out
    e=m["entry"]
    if e["type"]=="MARKET_NEXT_TICK":
        entry=N(s["entry_price"])
    elif e["type"]=="LIMIT":
        mid=(bars[0]["h"]+bars[0]["l"])/2
        entry=floor_to(mid,tick) if d==1 else ceil_to(mid,tick)
    elif e["type"]=="STOP":
        entry=bars[0]["h"]+tick if d==1 else bars[0]["l"]-tick
    else:
        raise ValueError("Unexpected entry type")
    anchor=at_phrase(m["stop"]["anchor"][side],bars,own)
    buffer=max(N(".20"),N(".05")*atr)
    stop=floor_to(anchor-d*buffer,tick) if d==1 else ceil_to(anchor-d*buffer,tick)
    order=dict(type=e["type"],entry=text_num(entry,dp),stop=text_num(stop,dp),
               target=None,rr=None,target_source=None,valid_bars=e.get("valid_bars",0))
    out["order"]=order
    if (entry-stop)*d<=0:
        reasons.append("ENTRY_BEYOND_STOP")
        return out
    if m["target"]["rule"]=="NEXT_LEVEL":
        obs=[dict(o,lo=N(o["lo"]),hi=N(o["hi"])) for o in s.get("obstacles") or []]
        ahead=[o for o in obs if o["hi"]>entry] if d==1 else [o for o in obs if o["lo"]<entry]
        if not ahead:
            reasons.append("NO_TARGET")
            return out
        near=min(ahead,key=lambda o:o["lo"]) if d==1 else max(ahead,key=lambda o:o["hi"])
        edge=near["lo"] if d==1 else near["hi"]
        order["target_source"]=near.get("source")
        if (edge-entry)*d<=0:
            reasons.append("TARGET_ALREADY_PASSED")
            return out
    elif m["target"]["rule"]=="OPPOSITE_BOUNDARY":
        edge=N(own["upper"]["lo"]) if d==1 else N(own["lower"]["hi"])
        order["target_source"]="RANGE_BOUNDARY"
        if (edge-entry)*d<=0:
            reasons.append("TARGET_ALREADY_PASSED")
            return out
    else:
        raise ValueError("Unexpected target rule")
    target=floor_to(edge,tick) if d==1 else ceil_to(edge,tick)
    rr=(target-entry)*d/((entry-stop)*d)
    order.update(target=text_num(target,dp),rr=text_num(rr),rr_decimal=f"{float(rr):.4f}")
    if rr<N(m["min_rr"]):
        reasons.append("RR_BELOW_2")
        return out
    out["decision"]="RECORD_ONLY" if m["execution_class"]=="RECORD_ONLY" else "TRADE"
    return out


def verify_golden():
    ms=load()
    results=[]
    mismatches=[]
    for p in sorted((ROOT/"golden").glob("GT-BIBLE-*.json")):
        g=json.loads(p.read_text(encoding="utf-8"))
        m=ms[g["manifest_id"]]
        for v in g["vectors"]:
            got=decide(m,ms["GT-BIBLE-COMMON"],v["snapshot"])
            exp=v["expect"]
            fields=["decision","reasons","arm","level_sources","failing_clauses"]
            errors=[k for k in fields if k in exp and got.get(k)!=exp[k]]
            if "order" in exp:
                errors.extend("order."+k for k,value in exp["order"].items()
                              if not got["order"] or got["order"].get(k)!=value)
            for k in ("target_source","valid_bars"):
                if k in exp and (not got["order"] or got["order"].get(k)!=exp[k]):
                    errors.append(k)
            if errors:
                mismatches.append({"case":v["id"],"wrong_fields":errors,"expected":exp,"got":got})
            results.append(v["id"])
    status="PASS" if len(results)==43 and not mismatches else "FAIL"
    return {"status":status,"bundle_sha256":BUNDLE,"gt_commit":GT_COMMIT,
            "golden_vectors":len(results),"mismatches":mismatches,
            "test_type":"Independent Python implementation, synthetic frozen snapshots, NOT historical backtest"}


if __name__=="__main__":
    r=verify_golden()
    Path("artifacts").mkdir(exist_ok=True)
    Path("artifacts/gt_bible_rc1_independent_golden.json").write_text(json.dumps(r,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps(r,sort_keys=True))
    if r["status"]!="PASS":
        raise SystemExit(1)
