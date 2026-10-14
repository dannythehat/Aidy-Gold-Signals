"""Day23 actual historical M1 -> closed M5 cross-language MQL predicate audit.

No MetaTrader binary, DLL, login or customer source execution. The reference
is genuine previously qualified HistData price history, NOT native MT EA parity.
"""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

from aidy.strategy_lab_history_reader import ReadResult, Window, read_bigquery_window
from aidy.strategy_lab_mql_adapter import admit_mql_closed_cross, evaluate_mql_closed_cross
from aidy.strategy_lab_tv_chart_csv import _ema
from aidy.strategy_lab_written_rule_intake import ClosedIndicatorSample

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "research/strategy_lab/fixtures"
OUTPUT = ROOT / "artifacts/strategy_lab/day23_real_mql_audit.json"


def _admit(lang: str):
    ext = "mq4" if lang == "mql4" else "mq5"
    name = f"day23_internal_closed_cross.{ext}"
    raw = (FIXTURES / name).read_bytes()
    ref = "research/strategy_lab/fixtures/" + name
    spec = json.loads((FIXTURES / "strategy_spec_v1_sample.json").read_text())
    digest = sha256(raw).hexdigest()
    spec["origin"]["source_language"] = lang
    spec["origin"]["source_sha256"] = digest
    spec["origin"]["source_snapshot_ref"] = ref
    spec["origin"]["interpretation_notes"] = [
        "Internal MQL pure source only; no EA, no native terminal or fill qualification."
    ]
    spec["long"]["exit"]["close_on_opposite_signal"] = True
    admitted = admit_mql_closed_cross(
        raw, json.dumps(spec, sort_keys=True), expected_source_sha256=digest,
        source_ref=ref, source_language=lang,
    )
    return admitted


def audit_read_only_history(history: ReadResult) -> dict:
    bars = history.bars
    if (len(bars) <= 50 or len(bars) * 5 != history.native_m1_rows
            or not history.source_archive_hashes or len(history.input_digest) != 64
            or history.provenance != "retrospective_history" or history.pit_eligible
            or any(b.price_basis != "bid" for b in bars)):
        raise ValueError("MQL history requires genuine qualified native bid M1")
    for i, b in enumerate(bars):
        if (b.open_time_utc.tzinfo is None
                or b.open_time_utc.utcoffset() != timedelta(0)
                or b.available_at_utc - b.open_time_utc != timedelta(minutes=5)
                or i and b.open_time_utc != bars[i-1].available_at_utc):
            raise ValueError("MQL history requires continuous fully closed M5 bars")
    closes = tuple(b.close for b in bars)
    fast = _ema(closes, 10)
    slow = _ema(closes, 30)
    independent_fast = [closes[0]]
    independent_slow = [closes[0]]
    for price in closes[1:]:
        independent_fast.append(independent_fast[-1] + Decimal(2) / 11 * (price - independent_fast[-1]))
        independent_slow.append(independent_slow[-1] + Decimal(2) / 31 * (price - independent_slow[-1]))
    for i, (f, s) in enumerate(zip(fast, slow, strict=True)):
        if (abs(f - independent_fast[i]) > Decimal("0.000000001")
                or abs(s - independent_slow[i]) > Decimal("0.000000001")):
            raise ValueError("independent EMA method differs")
    trace = tuple(ClosedIndicatorSample(
        b.available_at_utc, fast[i], slow[i],
    ) for i, b in enumerate(bars))
    oracle_entry = [
        trace[i].closed_at_utc.isoformat().replace("+00:00", "Z")
        for i in range(50, len(trace))
        if independent_fast[i-1] <= independent_slow[i-1]
        and independent_fast[i] > independent_slow[i]
    ]
    oracle_exit = [
        trace[i].closed_at_utc.isoformat().replace("+00:00", "Z")
        for i in range(50, len(trace))
        if independent_fast[i-1] >= independent_slow[i-1]
        and independent_fast[i] < independent_slow[i]
    ]
    results = {}
    for lang in ("mql4", "mql5"):
        mql = _admit(lang)
        check = evaluate_mql_closed_cross(mql, trace)
        if (check["entry_signals_utc"] != oracle_entry
                or check["opposite_cross_exit_signals_utc"] != oracle_exit):
            raise ValueError(f"{lang} source vs independent historical oracle divergence")
        results[lang] = {
            "original_source_sha256": mql.source_sha256,
            "canonical_spec_sha256": mql.spec_sha256,
            "entry_signals_utc": check["entry_signals_utc"],
            "opposite_cross_exit_signals_utc": check["opposite_cross_exit_signals_utc"],
        }
    if results["mql4"]["entry_signals_utc"] != results["mql5"]["entry_signals_utc"]:
        raise ValueError("MQL4/MQL5 cross-implementation entry signal divergence")
    if results["mql4"]["opposite_cross_exit_signals_utc"] != results["mql5"]["opposite_cross_exit_signals_utc"]:
        raise ValueError("MQL4/MQL5 cross-implementation exit predicate divergence")
    return {
        "status": "PASS", "type": "REAL_HISTORY_INTERNAL_MQL_PREDICATE_PARITY",
        "source_archive_hashes": list(history.source_archive_hashes),
        "historical_input_sha256": history.input_digest,
        "native_m1_count": history.native_m1_rows,
        "closed_m5_count": len(bars),
        "first_open_utc": bars[0].open_time_utc.isoformat(),
        "last_closed_utc": bars[-1].available_at_utc.isoformat(),
        "oracle_entry_signals_utc": oracle_entry,
        "oracle_opposite_exit_signals_utc": oracle_exit,
        "source_results": results,
        "native_mt4_mt5_compiler_or_terminal_parity_verified": False,
        "trade_or_full_stop_target_exit_parity_verified": False,
        "broker_orders_executed": False,
        "customer_metatrader_login_required": False,
    }


def main() -> int:
    from google.cloud import bigquery
    from google.oauth2 import service_account

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    try:
        credentials = json.loads(os.environ["AIDY_GCP_SERVICE_ACCOUNT_JSON"])
        client = bigquery.Client(
            project=credentials["project_id"], location="EU",
            credentials=service_account.Credentials.from_service_account_info(credentials),
        )
        start = datetime(2025, 1, 6, 11, tzinfo=UTC)
        end = start + timedelta(minutes=600)
        read, first_job = read_bigquery_window(client, Window(start, end, end, 5))
        evidence = audit_read_only_history(read)
        replay, second_job = read_bigquery_window(
            client, Window(start, end, end, 5, expected_digest=read.input_digest),
        )
        if replay != read:
            raise ValueError("frozen source replay returned different bars")
        evidence["first_bigquery_job_id"] = first_job
        evidence["replay_bigquery_job_id"] = second_job
        evidence["read_only"] = True
    except Exception as exc:  # noqa: BLE001 - fail-closed auditable result
        evidence = {"status": "BLOCKED", "error_type": type(exc).__name__,
                    "message": str(exc)[:400],
                    "native_mt4_mt5_compiler_or_terminal_parity_verified": False}
    OUTPUT.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(evidence, sort_keys=True))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
