"""Day22 independent Pine-subset signal audit on genuine read-only XAUUSD M1.

Uses a *different* EMA recurrence and a separate crossover oracle alongside
the production importer. This is real-data internal reproducibility, NOT an
attestation that TradingView executed this script or produced these values.
"""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

from aidy.strategy_lab_history_reader import ReadResult, Window, read_bigquery_window
from aidy.strategy_lab_pine_adapter import admit_pine_subset, compare_pine_to_spec
from aidy.strategy_lab_tv_chart_csv import _ema
from aidy.strategy_lab_written_rule_intake import ClosedIndicatorSample

ROOT = Path(__file__).resolve().parents[2]
SOURCE_PATH = ROOT / "research/strategy_lab/fixtures/day22_internal_pine_v6.pine.txt"
SPEC_PATH = ROOT / "research/strategy_lab/fixtures/strategy_spec_v1_sample.json"
SOURCE_REF = "research/strategy_lab/fixtures/day22_internal_pine_v6.pine.txt"
EVIDENCE_PATH = ROOT / "artifacts/strategy_lab/day22_real_history_ema_audit.json"


def audit_closed_bars(result: ReadResult) -> dict:
    """Fail closed on source identity, continuity, numerical and decision drift."""
    bars = result.bars
    if (result.provenance != "retrospective_history" or result.pit_eligible
            or len(bars) <= 50 or result.native_m1_rows != len(bars) * 5
            or not result.input_digest or not result.source_archive_hashes
            or any(b.price_basis != "bid" for b in bars)):
        raise ValueError("unqualified historical M5 input")
    for i, bar in enumerate(bars):
        if (bar.available_at_utc - bar.open_time_utc != timedelta(minutes=5)
                or bar.open_time_utc.tzinfo is None
                or bar.open_time_utc.utcoffset() != timedelta(0)
                or i and bar.open_time_utc != bars[i-1].available_at_utc):
            raise ValueError("historical M5 not fully closed or contiguous")

    source = SOURCE_PATH.read_bytes()
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    source_hash = sha256(source).hexdigest()
    spec["origin"]["source_language"] = "pine"
    spec["origin"]["source_sha256"] = source_hash
    spec["origin"]["source_snapshot_ref"] = SOURCE_REF
    spec["origin"]["interpretation_notes"] = [
        "Internal Pine signal fragment only; external source engine and exits unverified."
    ]
    admitted = admit_pine_subset(
        source, source_sha256=source_hash, source_ref=SOURCE_REF,
        spec_json=json.dumps(spec, sort_keys=True),
    )
    closes = tuple(b.close for b in bars)
    trace = tuple(ClosedIndicatorSample(
        b.available_at_utc,
        fast, slow,
    ) for b, fast, slow in zip(
        bars, _ema(closes, admitted.fast_period), _ema(closes, admitted.slow_period),
        strict=True,
    ))
    # Independent algebraic recurrence: EMA_new = EMA_old + alpha*(close-EMA_old).
    # Different from the production series-weighted smoothing implementation.
    independent = []
    for period in (admitted.fast_period, admitted.slow_period):
        alpha = Decimal(2) / Decimal(period + 1)
        values = [closes[0]]
        for close in closes[1:]:
            values.append(values[-1] + alpha * (close - values[-1]))
        independent.append(tuple(values))
    for i, point in enumerate(trace):
        if (abs(point.fast_ema - independent[0][i]) > Decimal("0.000000001")
                or abs(point.slow_ema - independent[1][i]) > Decimal("0.000000001")):
            raise ValueError("independent EMA recurrence diverged")

    actual = compare_pine_to_spec(admitted, trace)
    oracle = tuple(
        trace[i].closed_at_utc for i in range(50, len(trace))
        if independent[0][i-1] <= independent[1][i-1]
        and independent[0][i] > independent[1][i]
    )
    if actual != oracle:
        raise ValueError("independent crossover timestamps diverged")
    return {
        "status": "PASS",
        "validation": "REAL_HISTORICAL_M1_TO_M5_INTERNAL_SOURCE_SIGNAL_PARITY",
        "external_tradingview_parity_qualified": False,
        "broker_fills_qualified": False,
        "customer_login_required": False,
        "pine_source_sha256": source_hash,
        "typed_strategy_spec_sha256": admitted.spec_sha256,
        "historical_input_sha256": result.input_digest,
        "source_archive_sha256": list(result.source_archive_hashes),
        "native_m1_count": result.native_m1_rows,
        "closed_m5_count": len(bars),
        "first_open_utc": bars[0].open_time_utc.isoformat(),
        "last_closed_utc": bars[-1].available_at_utc.isoformat(),
        "signals_utc": [d.isoformat() for d in actual],
        "signal_count": len(actual),
        "ema_seed_scope": "first_observed_close_not_full_tradingview_chart_history",
    }


def main() -> int:
    from google.cloud import bigquery
    from google.oauth2 import service_account

    EVIDENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        credential = json.loads(os.environ["AIDY_GCP_SERVICE_ACCOUNT_JSON"])
        client = bigquery.Client(
            project=credential["project_id"], location="EU",
            credentials=service_account.Credentials.from_service_account_info(credential),
        )
        start = datetime(2025, 1, 6, 13, tzinfo=UTC)
        end = start + timedelta(minutes=600)
        window = Window(start, end, end, 5)
        result, job_id = read_bigquery_window(client, window)
        evidence = audit_closed_bars(result)
        replay, replay_job = read_bigquery_window(
            client, Window(start, end, end, 5, expected_digest=result.input_digest)
        )
        if replay != result:
            raise ValueError("same historical source digest returned different bars")
        evidence["first_read_bigquery_job_id"] = job_id
        evidence["frozen_replay_bigquery_job_id"] = replay_job
        evidence["read_only"] = True
    except Exception as exc:  # noqa: BLE001 - explicit fail-closed evidence
        evidence = {"status": "BLOCKED", "error_type": type(exc).__name__,
                    "message": str(exc)[:400],
                    "external_tradingview_parity_qualified": False}
    EVIDENCE_PATH.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(evidence, sort_keys=True))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
