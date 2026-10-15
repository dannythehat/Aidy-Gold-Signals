"""Day25 executable acceptance over two real Day19 SQLite reference runs.

Synthetic fixed-window arithmetic controls, NOT real historical trading alpha.
"""
from __future__ import annotations

import json
import tempfile
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path

from aidy.strategy_lab_baselines_stress import compare_day19_fixed_window
from aidy.strategy_lab_bidask_execution import QuoteTape
from aidy.strategy_lab_broker_profile import BrokerProfile
from aidy.strategy_lab_reference_run import run_internal_reference

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "research/strategy_lab/fixtures"
OUT = ROOT / "artifacts/strategy_lab/day25_baselines_cost_stress_acceptance.json"
START = datetime(2026, 10, 14, 14, tzinfo=UTC)


def build_source_bundle():
    broker_path = FIXTURE / "day11_illustrative_broker_observation.json"
    broker_source = broker_path.read_bytes()
    raw = json.loads(broker_source)
    raw.pop("evidence_kind")
    raw.update({
        "schema_version": "aidy.broker_profile.v1",
        "profile_id": "synthetic_xauusd_standard", "revision": 1,
        "provenance": {
            "evidence_kind": "internal_fixture",
            "source_reference": str(broker_path),
            "source_sha256": sha256(broker_source).hexdigest(),
            "captured_at_utc": "2026-10-14T14:10:00Z",
            "evidence_label": "illustrative_not_live",
        },
    })
    profile = BrokerProfile.from_wire(raw)
    quotes_source = (FIXTURE / "day25_illustrative_two_window_bidask_quotes.json").read_bytes()
    quotes = QuoteTape.from_snapshot(
        quotes_source, expected_sha256=sha256(quotes_source).hexdigest()
    )
    candle_source = (FIXTURE / "day19_internal_closed_m1.json").read_bytes()
    return profile, broker_source, quotes, candle_source


def audit() -> dict:
    profile, broker_source, quotes, candles = build_source_bundle()
    cand_sha = sha256(candles).hexdigest()
    with tempfile.TemporaryDirectory(prefix="aidy-day25-") as temporary:
        matched = []
        reference_runs = []
        for n in range(2):
            path = Path(temporary) / f"cash_{n}.sqlite3"
            ref = run_internal_reference(
                closed_bar_source=candles, expected_closed_bar_sha256=cand_sha,
                quote_tape=quotes, broker_profile=profile,
                broker_source_bytes=broker_source, sqlite_path=path,
            )
            proof = compare_day19_fixed_window(
                ref, profile=profile, broker_source_bytes=broker_source,
                quote_tape=quotes, source_candle_sha256=cand_sha,
                entry_signal_closed_at_utc=START,
                exit_signal_closed_at_utc=START+timedelta(minutes=5),
                naive_session_entry_closed_at_utc=START+timedelta(minutes=10),
                naive_session_exit_closed_at_utc=START+timedelta(minutes=15),
            )
            matched.append(proof)
            reference_runs.append(ref)
        if matched[0] != matched[1] or reference_runs[0] != reference_runs[1]:
            raise ValueError("independent Day19 journals or comparator outputs differ")
        check = matched[0]
        expected = (
            ("base", "8.30", "-11.70", "18.30", "-10.00"),
            ("adverse", "7.54", "-12.46", "17.54", "-10.00"),
            ("severe", "6.60", "-13.40", "16.60", "-10.00"),
        )
        if tuple((x.name, str(x.candidate_net_usd),
                  str(x.blind_clock_short_net_usd),
                  str(x.independently_scheduled_same_session_long_net_usd),
                  str(x.candidate_minus_scheduled_naive_usd))
                 for x in check.scenario_results) != expected:
            raise ValueError("manually known Day25 cost stress values differ")
        if any(x.matched_exposure_difference_usd != 0 or
               x.candidate_net_usd != x.independent_blind_clock_long_net_usd
               for x in check.scenario_results):
            raise ValueError("invented profit over matched clock-long benchmark")
        if check.genuine_strategy_alpha_qualified or (
            check.independent_strategy_benchmark_completed
        ):
            raise ValueError("synthetic control cannot qualify independent alpha")
        return {
            "status": "PASS",
            "scope": "INTERNAL_SYNTHETIC_FIXED_WINDOW_ACCOUNTING_CONTROL",
            "day19_internal_candle_sha256": cand_sha,
            "day12_quote_snapshot_sha256": quotes.snapshot_sha256,
            "day11_broker_source_sha256": sha256(broker_source).hexdigest(),
            "independent_disk_backed_cash_journals": 2,
            "day19_verified_final_cash_usd": "10008.30",
            "reference_journal_tip_sha256": reference_runs[0].journal_tip_sha256,
            "benchmark_and_stress": check.to_wire(),
            "scheduled_naive_same_session_tested": True,
            "independent_real_market_benchmark_qualified": False,
            "independent_strategy_benchmark_completed": False,
            "genuine_strategy_alpha_qualified": False,
            "live_or_real_broker_attested": False,
        }


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    try:
        proof = audit()
    except Exception as exc:  # noqa: BLE001 - fail-closed stored CI artefact
        proof = {"status": "BLOCKED", "error_type": type(exc).__name__,
                 "message": str(exc)[:300]}
    OUT.write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    print(json.dumps(proof, sort_keys=True))
    return 0 if proof["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
