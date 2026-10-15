"""Day32 real 100-job SQLite reliability and resumption acceptance."""
from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

from aidy.strategy_lab_batch_queue import (
    LEASE_MS,
    MAX_INFLIGHT,
    MAX_NONTERMINAL,
    SYNTHETIC,
    Experiment,
    ResearchQueue,
)

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT/"artifacts/strategy_lab/day32_batch_queue_acceptance.json"
RESULTS = ROOT/"artifacts/strategy_lab/day32_100_synthetic_results.json"


def spec(i: int) -> Experiment:
    return Experiment(
        family_id=f"family_{i//10:02d}",
        strategy_id=f"candidate_{i:03d}",
        strategy_rules_sha256=hashlib.sha256(f"rules-{i}".encode()).hexdigest(),
        market_input_sha256=hashlib.sha256(b"fixture_100_v1").hexdigest(),
        timeframe="M5" if i % 2 == 0 else "M15",
        parameters={"test_number": i},
    )


def outcome(job: str) -> dict:
    return {"job_id": job, "source_kind": SYNTHETIC,
            "synthetic_diagnostic_score_bps": int(job[:8], 16) % 2001 - 1000}


def exercise(path: Path) -> tuple[dict, list[dict]]:
    q = ResearchQueue(path)
    jobs = [q.submit(spec(i), 1000) for i in range(100)]
    if len({j for j, _ in jobs}) != 100 or any(not fresh for _, fresh in jobs):
        raise ValueError("unique trial creation failed")
    deduped = sum(not q.submit(spec(i), 1000)[1] for i in range(20))
    overflow = False
    try:
        q.submit(spec(100), 1000)
    except ValueError as exc:
        overflow = "quota exceeded" in str(exc)
    if not overflow or q.counts()["QUEUED"] != MAX_NONTERMINAL:
        raise ValueError("queued trial quota not enforced")
    abandoned = [q.claim(f"worker_{i}", 2000) for i in range(MAX_INFLIGHT)]
    if any(j is None for j in abandoned) or q.claim("overfull", 2000):
        raise ValueError("worker pool quota not enforced")
    q.conn.close()
    now = 2000 + LEASE_MS + 1
    q = ResearchQueue(path)
    first = q.claim("recovery_worker", now)
    if first is None:
        raise ValueError("abandoned worker claims not recovered after restart")
    fenced = 0
    for job in abandoned:
        try:
            q.finish(job["job_id"], job["lease_token"], now, outcome(job["job_id"]))
        except ValueError:
            fenced += 1
    if fenced != MAX_INFLIGHT:
        raise ValueError("stale crash completion was permitted")
    failures = rounds = 0
    previously_failed: set[str] = set()
    peak_workers = peak_family = 0
    successes_since_restart = 0
    while q.counts()["SUCCEEDED"] < 100:
        rounds += 1
        if rounds > 300:
            raise ValueError("100-job run failed to converge")
        ready = [first] if first else []
        first = None
        while len(ready) < MAX_INFLIGHT:
            claimed = q.claim(f"worker_{rounds%4}", now)
            if claimed is None:
                break
            ready.append(claimed)
        if not ready:
            raise ValueError("lost all runnable queue slots")
        peak_workers = max(peak_workers, len(ready))
        families = [job["source"]["family_id"] for job in ready]
        peak_family = max(peak_family, *(families.count(k) for k in set(families)))
        for job in ready:
            if failures < 6 and job["job_id"] not in previously_failed:
                if q.fail(job["job_id"], job["lease_token"], now,
                          "SYNTHETIC_EXECUTION_ERROR") != "QUEUED":
                    raise ValueError("retry exhausted prematurely")
                failures += 1
                previously_failed.add(job["job_id"])
            else:
                q.finish(job["job_id"], job["lease_token"], now,
                         outcome(job["job_id"]))
                successes_since_restart += 1
        if successes_since_restart >= 30:
            q.conn.close()
            q = ResearchQueue(path)
            successes_since_restart = 0
    counts, values, event = q.counts(), q.compare(), q.verify_events()
    q.conn.close()
    if (counts != {"QUEUED": 0, "RUNNING": 0, "SUCCEEDED": 100, "DEAD": 0}
            or len(values) != 100 or failures != 6
            or peak_workers > MAX_INFLIGHT or peak_family > 2
            or event["event_count"] < 300
            or any(x["profitability_verified"] for x in values)):
        raise ValueError("actual 100-job completion, event chain or quotas failed")
    return {
        "status": "PASS",
        "scope": "PRIVATE_100_SYNTHETIC_JOBS_ONLY",
        "unique_completed": 100, "deduplicated_submissions": deduped,
        "overflow_blocked": overflow, "stale_worker_completions_fenced": fenced,
        "synthetic_retry_recoveries": failures,
        "observed_peak_workers": peak_workers,
        "observed_peak_family_workers": peak_family,
        "max_parallel_workers": MAX_INFLIGHT,
        "max_queue_nonterminal": MAX_NONTERMINAL,
        "number_of_trial_families": len({x["family_id"] for x in values}),
        "results_sha256": hashlib.sha256(
            json.dumps(values, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "event_count": event["event_count"],
        "event_chain_sha256": event["chain_tip_sha256"],
        "real_trading_alpha_verified": False,
        "goldthinker_paper_accounts": 0,
    }, values


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix="aidy-d32-") as root:
            a, values = exercise(Path(root)/"run1.sqlite")
            b, second = exercise(Path(root)/"run2.sqlite")
        if a != b or values != second:
            raise ValueError("two independent runs disagree")
        proof = a
        RESULTS.write_text(json.dumps(values, indent=2, sort_keys=True)+"\n",
                           encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        proof = {"status": "BLOCKED", "error_type": type(exc).__name__,
                 "error": str(exc)[:250], "real_trading_alpha_verified": False}
    OUT.write_text(json.dumps(proof, indent=2, sort_keys=True)+"\n",
                   encoding="utf-8")
    print(json.dumps(proof, sort_keys=True))
    return 0 if proof["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
