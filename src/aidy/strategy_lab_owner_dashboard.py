"""Day33 PRIVATE owner-view Gold Edge research dashboard.

Source of truth: 83 genuinely read-only Drive candidate rows as a frozen
dated snapshot, Day32 completed SYNTHETIC queue results, original source-hashed
Day29 REAL BID-only + synthetic financial example. No billing/public website.
"""
from __future__ import annotations

import hashlib
import html
import json
from pathlib import Path
from urllib.parse import urlparse

from aidy.strategy_lab_report_contract import verify_canonical_report

CATALOGUE_SCHEMA = "aidy.strategy_lab.gold_edge_frozen_catalogue.v1"
DASHBOARD_SCHEMA = "aidy.strategy_lab.owner_research_dashboard.v1"
EXPECTED_SOURCE = "14EbIPxW5ZeueRX0vz0i6qG7BmlosL04x8-xXl3Hh6N4"
NOT_TESTED = "NOT TESTED"
NONE = "—"
VALID_SOURCES = frozenset(("github.com", "www.tradingview.com",
                           "tradingview.com", "www.mql5.com", "mql5.com"))


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, ensure_ascii=True, separators=(",", ":"),
        allow_nan=False,
    ).encode()).hexdigest()


def _escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def _source_url(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("source URL must be literal link")
    parsed = urlparse(value)
    if (parsed.scheme != "https" or not parsed.hostname
            or parsed.username or parsed.password
            or parsed.port not in (None, 443)
            or parsed.hostname not in VALID_SOURCES):
        raise ValueError("unapproved external research source")
    return value


def _verify_catalogue(catalogue: dict) -> list[dict]:
    if (catalogue.get("schema") != CATALOGUE_SCHEMA
            or catalogue.get("source_spreadsheet_id") != EXPECTED_SOURCE
            or catalogue.get("source_sheet") != "SCOREBOARD"
            or catalogue.get("live_drive_sync") is not False
            or catalogue.get("frozen_date_utc") != "2026-10-15"):
        raise ValueError("live or unqualified Drive snapshot supplied")
    rows = catalogue.get("candidates")
    if not isinstance(rows, list) or len(rows) != 83:
        raise ValueError("original Gold Edge snapshot requires 83 source rows")
    for i, row in enumerate(rows, 1):
        if row["id"] != f"S{i:03d}" or not row["title"] or not row["family"]:
            raise ValueError("candidate ID, title or family manipulated")
        if (row["research_stage"] != NOT_TESTED
                or row["independent_aidy_score"] is not None
                or row["grade"] != "UNREVIEWED"
                or row["goldthinker_status"] != "NOT YET"):
            raise ValueError("unverified candidate incorrectly promoted")
        _source_url(row["source_url"])
        ease = row["provisional_setup_ease"]
        if ease is not None and (type(ease) is not int or not 1 <= ease <= 10):
            raise ValueError("non-qualified setup ease altered")
    return rows


def _verify_research(original: dict) -> dict:
    if (original.get("status") != "PASS"
            or original.get("scope")
            != "CANONICAL_AIDY_REPORT_REPLAY_NOT_GOLDTHINKER_PRODUCTION"
            or original.get("paper_and_live_performance_qualified") is not False
            or len(original.get("independent_real_historical_query_job_ids", [])) != 2):
        raise ValueError("original Day29 research receipt absent")
    r = original["report"]
    verify_canonical_report(r)
    if (r["identity"]["customer_can_connect"]
            or r["research"]["evidence_rating"]["score_out_of_100"] is not None
            or r["research"]["evidence_rating"]["governance"] != "ORANGE_INVESTIGATE"
            or not r["research"]["synthetic_historical_net_pnl_only"]
            or r["research"]["independently_qualified_real_strategy_profit"]
            or r["production"]["paper"]["forward_paper_pnl"] is not None
            or r["production"]["elite20"]["portfolio_pnl"] is not None):
        raise ValueError("unqualified research was promoted to trading success")
    return r


def build_snapshot(catalogue: dict, synthetic: list[dict], batch: dict,
                   original: dict) -> dict:
    rows = _verify_catalogue(catalogue)
    reference = _verify_research(original)
    if (batch.get("status") != "PASS"
            or batch.get("scope") != "PRIVATE_100_SYNTHETIC_JOBS_ONLY"
            or batch.get("unique_completed") != 100
            or batch.get("number_of_trial_families") != 10
            or len(synthetic) != 100
            or any(x.get("source_kind") != "INTERNAL_SYNTHETIC_DIAGNOSTIC_ONLY"
                   or x.get("profitability_verified") is not False
                   for x in synthetic)
            or batch.get("results_sha256") != _digest(synthetic)):
        raise ValueError("Day32 exact 100-result source comparison invalid")
    ids = [r["job_id"] for r in synthetic]
    if len(set(ids)) != 100 or any(len(x) != 64 for x in ids):
        raise ValueError("job audit identity lost")
    for row in synthetic:
        if (not row["strategy_id"].startswith("candidate_")
                or not row["family_id"].startswith("family_")
                or row["timeframe"] not in ("M5", "M15")
                or type(row["synthetic_diagnostic_score_bps"]) is not int
                or not -1000 <= row["synthetic_diagnostic_score_bps"] <= 1000
                or len(row["result_sha256"]) != 64):
            raise ValueError("unqualified synthetic result")
    candidates = []
    for row in rows:
        blockers = [
            "Original strategy rules/code not independently reproduced",
            "Independent costed trading and OOS evidence unavailable",
            "No forward-paper production validation",
        ]
        if row["source_audit"] == "DISCOVERY ONLY":
            blockers.insert(0, "Source not reviewed")
        candidates.append({
            "id": row["id"], "name": row["title"],
            "family": row["family"], "source_url": row["source_url"],
            "source_audit": row["source_audit"],
            "research_stage": NOT_TESTED,
            "aidy_score_100": None,
            "aidy_score_status": "NOT_INDEPENDENTLY_TESTED",
            "paper_net_pnl_usd": None,
            "goldthinker_system_name": None,
            "join_available": False,
            "setup_ease_provisional": row["provisional_setup_ease"],
            "setup_ease_is_performance": False,
            "blockers": blockers,
        })
    report = {
        "schema": DASHBOARD_SCHEMA,
        "title": "AIDY OWNER RESEARCH DESK",
        "owner_only": True,
        "not_a_public_website": True,
        "brand": {"engine": "AIDY", "future_customer": "GoldThinker"},
        "snapshot_utc_date": "2026-10-15",
        "catalogue_source": {
            "kind": "DATED_DRIVE_SCOREBOARD_SNAPSHOT_NOT_LIVE_SYNC",
            "spreadsheet_id": EXPECTED_SOURCE,
            "url": catalogue["source_url"],
            "count": len(candidates), "snapshot_sha256": _digest(catalogue),
        },
        "research_reference": {
            "original_run_id": reference["run_id"],
            "canonical_result_sha256": reference["canonical_result_sha256"],
            "as_of_utc": reference["as_of_utc"],
            "nine_factor_score": None,
            "nine_factor_status": "ORANGE_UNQUALIFIED_EXAMPLE_ONLY",
            "sample_cash_is_synthetic": True,
            "observed_real_strategy_profit": None,
            "forward_paper_profit": None,
            "elite20_profit": None,
            "day29_input_source_sha256":
                reference["provenance"]["source_sha256"]["day26_real_historical_bid"],
        },
        "batch": {
            "source_kind": "100_SYNTHETIC_QUEUE_DIAGNOSTICS_NOT_REAL_STRATEGIES",
            "status": "COMPLETED_SYNTHETIC",
            "total": len(synthetic),
            "queue_limits": {"total_parallel": 4, "per_family_parallel": 2},
            "result_source_sha256": batch["results_sha256"],
            "event_chain_tip_sha256": batch["event_chain_sha256"],
            "event_count": batch["event_count"],
            "experiments": synthetic,
            "not_mapped_to_gold_edge_candidate_ids": True,
        },
        "counts": {
            "candidate_backlog": len(candidates),
            "independently_qualified_strategies": 0,
            "unreviewed_or_untested_candidates": len(candidates),
            "synthetic_queue_experiments_completed": len(synthetic),
            "actual_paper_accounts": 0,
            "elite20_combined_account": None,
        },
        "links": {
            "gold_edge_sheet": catalogue["source_url"],
            "notion_master_tracker":
                "https://www.notion.so/3f9e30f1e540811ba4eafeb271ba4a47",
            "day29_evidence":
                "https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/38700714922",
            "day32_queue_evidence":
                "https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/38708535681",
        },
        "candidates": candidates,
        "billing": None,
        "customer_account_connection": None,
        "automatic_live_trading": False,
    }
    report["snapshot_sha256"] = _digest(report)
    return report


def verify_snapshot(s: dict) -> None:
    if s.get("schema") != DASHBOARD_SCHEMA:
        raise ValueError("invalid owner dashboard schema")
    checksum = s.get("snapshot_sha256")
    if checksum != _digest({k: v for k, v in s.items() if k != "snapshot_sha256"}):
        raise ValueError("owner dashboard provenance hash mismatch")
    if (not s["owner_only"] or not s["not_a_public_website"]
            or s["counts"]["independently_qualified_strategies"] != 0
            or s["counts"]["actual_paper_accounts"] != 0
            or s["research_reference"]["nine_factor_score"] is not None
            or s["automatic_live_trading"] is not False
            or s["billing"] is not None):
        raise ValueError("owner research fixture misrepresented as public trading")


def _link(text: str, url: str) -> str:
    safe = _source_url(url) if urlparse(url).hostname in VALID_SOURCES else url
    if not safe.startswith("https://") or urlparse(safe).scheme != "https":
        raise ValueError("insecure dashboard navigation target")
    return f'<a href="{_escape(safe)}" target="_blank" rel="noopener noreferrer">{_escape(text)}</a>'


def render_owner_html(snapshot: dict) -> str:
    verify_snapshot(snapshot)
    candidate_rows = []
    for item in snapshot["candidates"]:
        original = item["source_url"]
        source = _link("Source ↗", original) if original else "No source link"
        candidate_rows.append(
            f'<tr data-search="{_escape((item["id"]+" "+item["name"]+" "+item["family"]).lower())}"'
            f' data-stage="not-tested"><td class="mono">{_escape(item["id"])}</td>'
            f'<td><strong>{_escape(item["name"])}</strong><small>{_escape(item["family"])}</small></td>'
            f'<td>{_escape(item["source_audit"])}</td>'
            '<td><span class="flag">NOT TESTED</span></td>'
            '<td class="null">Not scored</td>'
            f'<td><details><summary>3 blockers</summary><ul>{"".join("<li>"+_escape(x)+"</li>" for x in item["blockers"])}</ul></details></td>'
            f'<td>{source}</td></tr>'
        )
    trial_rows = []
    for result in snapshot["batch"]["experiments"]:
        trial_rows.append(
            '<tr><td class="mono">'+_escape(result["strategy_id"])+'</td>'
            '<td>'+_escape(result["family_id"])+'</td>'
            '<td>'+_escape(result["timeframe"])+'</td>'
            '<td><span class="flag good">Synthetic complete</span></td>'
            '<td class="mono">'+_escape(result["synthetic_diagnostic_score_bps"])+'</td>'
            '<td><details><summary>SHA / audit</summary><code>'+_escape(result["job_id"])+
            '</code><code>'+_escape(result["result_sha256"])+'</code></details></td></tr>'
        )
    data = json.dumps({
        "counts": snapshot["counts"],
        "hash": snapshot["snapshot_sha256"],
    }, sort_keys=True)
    data = data.replace("<", "\\u003c").replace(">", "\\u003e")
    return """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,nofollow,noarchive">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>AIDY | Private Research Desk — Day 33</title>
<style>
:root{font-family:Inter,system-ui,-apple-system,Arial,sans-serif;color:#e8ebf1;background:#0a101c}
*{box-sizing:border-box}body{margin:0}a{color:#e7c17c}a:hover{color:#ffdfa1}
header{background:#101a2a;border-bottom:1px solid #273444;padding:26px max(3vw,20px)}
.shell{max-width:1480px;margin:auto}h1{font-size:clamp(26px,3vw,42px);margin:8px 0}h2{font-size:21px;margin:0}
.gold{color:#ddb568}.muted,small{color:#9facbf}small{display:block;font-size:12px;margin-top:5px}
.tag{display:inline-block;background:#2a261b;color:#f0c477;border:1px solid #604b28;padding:5px 9px;border-radius:99px;font-size:11px;letter-spacing:1px}
nav{display:flex;gap:14px;flex-wrap:wrap;margin-top:18px;font-size:13px}
main{max-width:1480px;margin:auto;padding:24px max(3vw,20px)}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:14px;margin-bottom:20px}
.kpi{background:#111c2d;border:1px solid #263648;border-radius:13px;padding:18px}
.kpi b{font-size:28px;display:block;margin-top:8px;color:#f2d293}.kpi span{font-size:12px;color:#9baac1}
.alert{border-left:3px solid #d4aa58;background:#211e1a;padding:15px 18px;margin:18px 0;border-radius:5px;line-height:1.5}
section{border:1px solid #273647;background:#111927;border-radius:13px;margin:24px 0;padding:20px;overflow:hidden}
section p{line-height:1.6;color:#aebbd0;font-size:13px}
.controls{display:flex;gap:12px;flex-wrap:wrap;margin:16px 0}input,select{background:#0c1523;color:#eef2f9;border:1px solid #34475a;border-radius:8px;padding:12px;min-width:180px}
input{flex:1}button{background:#222f41;color:#f0d293;border:1px solid #584a2f;border-radius:8px;padding:11px 14px;cursor:pointer}
.tablewrap{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:12px}th{text-align:left;color:#edcc8b;background:#1c2938}th,td{border-bottom:1px solid #2a3746;padding:11px 10px;vertical-align:top}
tbody tr:hover{background:#182437}.mono,code{font-family:ui-monospace,Consolas,monospace;font-size:11px}
code{display:block;word-break:break-all;margin:8px 0;color:#b8becb}.null{color:#9aabbc;font-style:italic}
.flag{display:inline-block;white-space:nowrap;border:1px solid #755e36;background:#372d1a;color:#e9b86f;padding:5px 8px;border-radius:6px;font-size:11px}
.flag.good{background:#14332e;border-color:#38675e;color:#95d3bf}
details summary{cursor:pointer;color:#e9c58d}ul{padding-left:18px}li{margin:6px 0;color:#d3d9df}
footer{border-top:1px solid #273647;margin-top:30px;padding:16px;color:#8395ad;font-size:12px}
@media(max-width:650px){th,td{padding:9px 7px}.kpis{grid-template-columns:repeat(2,minmax(0,1fr))}}
</style></head><body><header><div class="shell">
<span class="tag">OWNER-ONLY RESEARCH · PRIVATE CI ARTIFACT</span>
<h1><span class="gold">AIDY</span> Strategy Intelligence</h1>
<div class="muted">The Gold Edge Hunt / Owner research desk · Frozen 15 October 2026</div>
<nav><a href="#catalogue">83-source candidate backlog</a><a href="#experiments">100-job batch ledger</a>
<a href="#audit">Source &amp; blockers</a>""" + _link("Gold Edge workbook ↗",snapshot["links"]["gold_edge_sheet"]) + """</nav></div></header>
<main>
<div class="kpis">
<div class="kpi"><span>Original source candidates</span><b>83</b><small>Dated Google Drive scoreboard snapshot</small></div>
<div class="kpi"><span>Independent strategy passes</span><b>0</b><small>Not yet profit-qualified by AIDY</small></div>
<div class="kpi"><span>Completed batch diagnostics</span><b>100</b><small>Synthetic queue jobs only</small></div>
<div class="kpi"><span>Real forward-paper systems</span><b>0</b><small>GoldThinker production is separate</small></div>
</div>
<div class="alert"><b>Research integrity:</b> No profitable gold strategy has been independently demonstrated here. 
The 83 source candidates have NOT been tested. All 100 scored experiments are synthetic queue diagnostics; their numbers are NOT AIDY's nine-factor evidence scores, trading P&amp;L or paper profits. The source sheet is a frozen snapshot, not live Drive synchronisation.</div>
<section id="catalogue"><h2>Gold Edge candidate register</h2>
<p>Original sheet status is preserved, including unreviewed sources, unavailable ratings and publishing restrictions.
The owner can follow original source links, inspect blockers, or open the original workbook. No customer join, subscriptions or bot activation.</p>
<div class="controls"><input id="search" placeholder="Search ID, strategy, research family" aria-label="Search candidate strategies">
<select id="audit-filter" aria-label="Filter source audits"><option value="">All source audit levels</option><option value="DISCOVERY ONLY">Discovery only</option><option value="SOURCE REVIEWED">Source reviewed</option></select>
<button id="clear">Clear filters</button><span id="visible" class="muted"></span></div>
<div class="tablewrap"><table id="candidates"><thead><tr><th>Candidate ID</th><th>Source name / family</th><th>Source audit</th><th>AIDY stage</th><th>Evidence /100</th><th>Blockers</th><th>Original research</th></tr></thead>
<tbody>""" + "\n".join(candidate_rows) + """</tbody></table></div></section>
<section id="experiments"><h2>Durable batch experiments — NOT a strategy leaderboard</h2>
<p>These are 100 completed test jobs from the real Day32 scheduler; their deterministic numeric scores only check result comparison/restart logic. They have NO link to the 83 Gold Edge candidate IDs and contain NO trading profit.</p>
<div class="tablewrap"><table><thead><tr><th>Synthetic job</th><th>Trial family</th><th>Timeframe</th><th>Queue state</th><th>Diagnostic only</th><th>Original SHA receipts</th></tr></thead>
<tbody>""" + "\n".join(trial_rows) + """</tbody></table></div></section>
<section id="audit"><h2>Evidence, qualifications &amp; research blockers</h2>
<p>All 83 Gold Edge candidates require actual rule/source reproduction, realistic transaction costs, matched benchmarks, chronological independent OOS and forward paper qualification before any public GoldThinker identity. The existing Day29 sample evidence rating is <strong>ORANGE / unavailable</strong>, not a score for any of these 83 systems.</p>
<details open><summary>Original sources and audit hashes</summary><ul>
<li>Gold Edge research snapshot SHA256: <code>""" + _escape(snapshot["catalogue_source"]["snapshot_sha256"]) + """</code></li>
<li>100-job comparable result SHA256: <code>""" + _escape(snapshot["batch"]["result_source_sha256"]) + """</code></li>
<li>Queue event hash-chain tip: <code>""" + _escape(snapshot["batch"]["event_chain_tip_sha256"]) + """</code></li>
<li>AIDY original Day29 reference report SHA256: <code>""" + _escape(snapshot["research_reference"]["canonical_result_sha256"]) + """</code></li>
<li>Complete owner snapshot SHA256: <code>""" + _escape(snapshot["snapshot_sha256"]) + """</code></li></ul></details>
<p>Audit links: """ + " · ".join(_link(k.replace("_", " ").title()+" ↗",v) for k,v in snapshot["links"].items()) + """</p>
<p><strong>Scope:</strong> private downloadable offline report, not an internet-hosted login, billing service, customer GoldThinker website, real account or live Google Drive connector.</p></section>
</main><footer>GoldThinker is the future customer brand; AIDY is the independent scientific engine. No trading profits, customer licensing or automatic system deployment are implied.</footer>
<script id="owner-data" type="application/json">""" + data + """</script>
<script>
(function () {
  const search=document.getElementById('search'), filter=document.getElementById('audit-filter'),
  table=document.getElementById('candidates'), visible=document.getElementById('visible');
  function update(){
    const q=search.value.trim().toLowerCase(),audit=filter.value;
    let count=0;
    Array.from(table.tBodies[0].rows).forEach(function(row){
      const matches=(!q||row.dataset.search.includes(q))&&(!audit||row.cells[2].textContent===audit);
      row.hidden=!matches;
      if(matches)count++;
    });
    visible.textContent=count+' / 83 candidates shown';
  }
  search.addEventListener('input',update);
  filter.addEventListener('change',update);
  document.getElementById('clear').addEventListener('click',function(){search.value='';filter.value='';update()});
  update();
})();
</script></body></html>"""


def export_dashboard(snapshot: dict, out: Path) -> dict:
    verify_snapshot(snapshot)
    out.mkdir(parents=True, exist_ok=True)
    j = out / "owner_dashboard_data.json"
    h = out / "owner_research_dashboard.html"
    j.write_text(json.dumps(snapshot, indent=2, sort_keys=True)+"\n",encoding="utf-8")
    h.write_text(render_owner_html(snapshot), encoding="utf-8")
    digest = {"schema": DASHBOARD_SCHEMA, "source_sha256":snapshot["snapshot_sha256"],
              "files": {file.name: {
                  "sha256":hashlib.sha256(file.read_bytes()).hexdigest(),
                  "bytes":file.stat().st_size,
              } for file in (h, j)}}
    (out/"manifest.json").write_text(
        json.dumps(digest, indent=2, sort_keys=True)+"\n",encoding="utf-8"
    )
    return digest
