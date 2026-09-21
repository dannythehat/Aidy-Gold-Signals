from __future__ import annotations

import json
import math
import os
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
from google.cloud import bigquery
from google.oauth2 import service_account

from aidy.databento_gc import (
    DATABENTO_DATASET,
    GC_CONTINUOUS_SYMBOL,
    DatabentoHistoricalClient,
    HistoricalRequest,
)
from aidy.gc_microstructure import (
    aggregate_tbbo_minutes,
    build_weekday_clock_baseline,
    normalize_minute,
    parse_databento_tbbo_jsonl,
    verify_weekday_clock_baseline,
)
from aidy.gc_shadow_spine import normalize_databento_api_key, resolve_gc_contract_map
from aidy.gold_futures_microstructure_expert import summarise_incremental_holdout

BASELINE_COUNT = 20
HOLDOUT_COUNT = 40
BASELINE_START = datetime(2024, 8, 20, 15, 0, tzinfo=UTC)
HOLDOUT_START = datetime(2025, 1, 7, 15, 0, tzinfo=UTC)
GC_LOOKBACK_MINUTES = 15
XAU_LOOKBACK_MINUTES = 61
XAU_OUTCOME_MINUTES = 15
FREE_CREDIT_PHASE_A_CAP_USD = Decimal("1.00")
DATABENTO_SYMBOLOGY_URL = "https://hist.databento.com/v0/symbology.resolve"
PHASE_A_STUDY_VERSION = "aidy_build17_genuine_phasea_holdout_v1"


def _anchors(start: datetime, count: int) -> list[datetime]:
    return [start + timedelta(weeks=index) for index in range(count)]


def _symbology_resolve(
    api_key: str,
    *,
    symbols: str,
    stype_in: str,
    stype_out: str,
    start_date: str,
    end_date: str,
) -> dict[str, Any]:
    response = httpx.post(
        DATABENTO_SYMBOLOGY_URL,
        auth=httpx.BasicAuth(api_key, ""),
        timeout=30.0,
        data={
            "dataset": DATABENTO_DATASET,
            "symbols": symbols,
            "stype_in": stype_in,
            "stype_out": stype_out,
            "start_date": start_date,
            "end_date": end_date,
        },
        headers={"User-Agent": "AIDY-Signals/Build17"},
    )
    if response.is_error:
        safe = response.text.replace(api_key, "***")[:600]
        raise RuntimeError(
            f"Databento Build17 symbology failed with HTTP {response.status_code}: {safe}"
        )
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("Databento Build17 symbology returned non-object payload")
    return payload


def _continuous_ids(payload: dict[str, Any]) -> list[str]:
    result = payload.get("result")
    if not isinstance(result, dict):
        raise RuntimeError("Databento continuous resolution lacks result mapping")
    entries = result.get(GC_CONTINUOUS_SYMBOL)
    if not isinstance(entries, list):
        raise RuntimeError("Databento continuous resolution lacks GC entries")
    ids = sorted(
        {
            str(entry.get("s"))
            for entry in entries
            if isinstance(entry, dict) and str(entry.get("s") or "").isdigit()
        }
    )
    if not ids:
        raise RuntimeError("Databento continuous resolution produced no instrument IDs")
    return ids


def _contract_map(api_key: str, anchor: datetime) -> dict[int, str]:
    start_date = anchor.date().isoformat()
    end_date = (anchor.date() + timedelta(days=1)).isoformat()
    continuous = _symbology_resolve(
        api_key,
        symbols=GC_CONTINUOUS_SYMBOL,
        stype_in="continuous",
        stype_out="instrument_id",
        start_date=start_date,
        end_date=end_date,
    )
    raw: dict[str, dict[str, Any]] = {}
    for instrument_id in _continuous_ids(continuous):
        raw[instrument_id] = _symbology_resolve(
            api_key,
            symbols=instrument_id,
            stype_in="instrument_id",
            stype_out="raw_symbol",
            start_date=start_date,
            end_date=end_date,
        )
    return resolve_gc_contract_map(continuous, raw)


def _download_window(
    client: DatabentoHistoricalClient,
    api_key: str,
    anchor: datetime,
    *,
    output_dir: Path,
    prior_committed: Decimal,
) -> tuple[list[Any], Decimal, dict[str, Any]]:
    request = HistoricalRequest(
        schema="tbbo",
        start=(anchor - timedelta(minutes=GC_LOOKBACK_MINUTES)).isoformat(),
        end=anchor.isoformat(),
    )
    quote = client.estimate_cost(request, prior_committed_usd=prior_committed)
    if not quote.approved:
        raise RuntimeError(f"Build17 quote rejected by free-credit policy: {quote.as_dict()}")
    projected = prior_committed + quote.quoted_cost_usd
    if projected > FREE_CREDIT_PHASE_A_CAP_USD:
        raise RuntimeError(
            "Build17 free-credit Phase-A cap exceeded: projected " + str(projected)
        )
    path = output_dir / f"{anchor:%Y%m%dT%H%M%SZ}.jsonl"
    receipt = client.download_jsonl(request, quote=quote, output_path=path)
    mapping = _contract_map(api_key, anchor)
    trades = parse_databento_tbbo_jsonl(
        path.read_text(encoding="utf-8"),
        contract_by_instrument_id=mapping,
    )
    if not trades:
        raise RuntimeError(f"Build17 no genuine TBBO trades at {anchor.isoformat()}")
    minutes = aggregate_tbbo_minutes(trades)
    return minutes, projected, receipt


def _bq_client() -> tuple[Any, Any, str, str]:
    raw = os.environ.get("AIDY_GCP_SERVICE_ACCOUNT_JSON")
    if not raw:
        raise RuntimeError("AIDY_GCP_SERVICE_ACCOUNT_JSON is required")
    info = json.loads(raw)
    credentials = service_account.Credentials.from_service_account_info(info)
    project = str(info["project_id"])
    dataset = os.environ.get("AIDY_BIGQUERY_DATASET", "aidy_analytics_test")
    location = os.environ.get("AIDY_BIGQUERY_LOCATION", "EU")
    client = bigquery.Client(project=project, credentials=credentials, location=location)
    return client, bigquery, project, dataset


def _load_xau_windows(anchors: list[datetime]) -> dict[datetime, list[dict[str, Any]]]:
    client, bq, project, dataset = _bq_client()
    table = f"{project}.{dataset}.research_candles"
    sql = f"""
      WITH anchors AS (
        SELECT anchor FROM UNNEST(@anchors) AS anchor
      )
      SELECT
        a.anchor AS anchor_utc,
        c.open_time_utc,
        c.open,
        c.high,
        c.low,
        c.close
      FROM anchors a
      JOIN `{table}` c
        ON c.open_time_utc >= TIMESTAMP_SUB(a.anchor, INTERVAL {XAU_LOOKBACK_MINUTES} MINUTE)
       AND c.open_time_utc < TIMESTAMP_ADD(a.anchor, INTERVAL {XAU_OUTCOME_MINUTES} MINUTE)
      WHERE c.source = 'histdata'
        AND c.symbol = 'XAUUSD'
        AND c.timeframe = 'M1'
        AND c.provenance_class = 'retrospective_history'
        AND c.pit_eligible = FALSE
      ORDER BY anchor_utc, c.open_time_utc
    """
    config = bq.QueryJobConfig(
        query_parameters=[bq.ArrayQueryParameter("anchors", "TIMESTAMP", anchors)]
    )
    grouped: dict[datetime, list[dict[str, Any]]] = defaultdict(list)
    for row in client.query(sql, job_config=config).result():
        anchor = row["anchor_utc"].astimezone(UTC)
        grouped[anchor].append(
            {
                "open_time_utc": row["open_time_utc"].astimezone(UTC),
                "open": Decimal(str(row["open"])),
                "high": Decimal(str(row["high"])),
                "low": Decimal(str(row["low"])),
                "close": Decimal(str(row["close"])),
            }
        )
    return dict(grouped)


def _close_map(rows: list[dict[str, Any]]) -> dict[datetime, Decimal]:
    return {row["open_time_utc"]: row["close"] for row in rows}


def _spot_prediction(anchor: datetime, rows: list[dict[str, Any]]) -> str | None:
    closes = _close_map(rows)
    end = closes.get(anchor - timedelta(minutes=1))
    if end is None:
        return None
    returns: list[Decimal] = []
    for horizon in (5, 15, 60):
        start = closes.get(anchor - timedelta(minutes=horizon + 1))
        if start in {None, Decimal(0)}:
            return None
        returns.append((end / start) - Decimal(1))
    votes = [1 if value > 0 else -1 if value < 0 else 0 for value in returns]
    score = sum(votes)
    if score > 0:
        return "up"
    if score < 0:
        return "down"
    for index in (1, 0, 2):
        if votes[index] > 0:
            return "up"
        if votes[index] < 0:
            return "down"
    return None


def _outcome(anchor: datetime, rows: list[dict[str, Any]]) -> tuple[str | None, Decimal | None]:
    closes = _close_map(rows)
    start = closes.get(anchor - timedelta(minutes=1))
    end = closes.get(anchor + timedelta(minutes=14))
    if start in {None, Decimal(0)} or end is None:
        return None, None
    ret_bps = (end / start - Decimal(1)) * Decimal(10000)
    if ret_bps > 0:
        return "up", ret_bps
    if ret_bps < 0:
        return "down", ret_bps
    return None, ret_bps


def _mean(values: list[Decimal]) -> Decimal | None:
    return None if not values else sum(values, Decimal(0)) / Decimal(len(values))


def _micro_signal(minutes: list[Any], baseline: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
    normalized = [normalize_minute(minute, baseline) for minute in minutes]
    known = [row for row in normalized if row.get("state") == "known"]
    signed = [
        Decimal(str(row["signed_trade_imbalance_z"]))
        for row in known
        if row.get("signed_trade_imbalance_z") is not None
    ]
    vwap = [
        Decimal(str(row["vwap_distance_z"]))
        for row in known
        if row.get("vwap_distance_z") is not None
    ]
    avg_signed = _mean(signed)
    avg_vwap = _mean(vwap)
    signal: str | None = None
    if avg_signed is not None and avg_vwap is not None:
        if avg_signed > 0 and avg_vwap > 0 and (
            abs(avg_signed) >= Decimal(1) or abs(avg_vwap) >= Decimal(1)
        ):
            signal = "up"
        elif avg_signed < 0 and avg_vwap < 0 and (
            abs(avg_signed) >= Decimal(1) or abs(avg_vwap) >= Decimal(1)
        ):
            signal = "down"
    return signal, {
        "known_minute_n": len(known),
        "avg_signed_trade_imbalance_z": None if avg_signed is None else str(avg_signed),
        "avg_vwap_distance_z": None if avg_vwap is None else str(avg_vwap),
        "signal": signal,
    }


def _exact_binomial_two_sided(successes: int, trials: int) -> Decimal | None:
    if trials <= 0:
        return None
    observed = math.comb(trials, successes)
    total = 2**trials
    probability = sum(
        math.comb(trials, k)
        for k in range(trials + 1)
        if math.comb(trials, k) <= observed
    ) / total
    return Decimal(str(min(1.0, probability)))


def main() -> int:
    baseline_anchors = _anchors(BASELINE_START, BASELINE_COUNT)
    holdout_anchors = _anchors(HOLDOUT_START, HOLDOUT_COUNT)
    all_anchors = baseline_anchors + holdout_anchors
    xau = _load_xau_windows(holdout_anchors)

    raw_secret = os.environ.get("DATABENTO_API_KEY", "")
    if not raw_secret.strip():
        raise RuntimeError("DATABENTO_API_KEY is required")
    api_key = normalize_databento_api_key(raw_secret)
    os.environ["DATABENTO_API_KEY"] = api_key

    output_dir = Path("/tmp/build17_phasea_tbbo")
    output_dir.mkdir(parents=True, exist_ok=True)
    committed = Decimal(0)
    windows: dict[datetime, list[Any]] = {}
    receipts: list[dict[str, Any]] = []

    with DatabentoHistoricalClient.from_env() as client:
        entitlement = client.assert_gc_entitlement()
        for anchor in all_anchors:
            minutes, committed, receipt = _download_window(
                client,
                api_key,
                anchor,
                output_dir=output_dir,
                prior_committed=committed,
            )
            windows[anchor] = minutes
            receipts.append(
                {
                    "anchor_utc": anchor.isoformat(),
                    "quoted_cost_usd": receipt["quoted_cost_usd"],
                    "byte_count": receipt["byte_count"],
                    "sha256": receipt["sha256"],
                }
            )

    baseline_minutes = [minute for anchor in baseline_anchors for minute in windows[anchor]]
    baseline = build_weekday_clock_baseline(baseline_minutes)
    if not verify_weekday_clock_baseline(baseline):
        raise RuntimeError("Build17 genuine baseline verification failed")

    rows: list[dict[str, Any]] = []
    episode_details: list[dict[str, Any]] = []
    for anchor in holdout_anchors:
        spot = _spot_prediction(anchor, xau.get(anchor, []))
        actual, ret_bps = _outcome(anchor, xau.get(anchor, []))
        micro, micro_detail = _micro_signal(windows[anchor], baseline)
        if spot is None or actual is None:
            continue
        rich = micro or spot
        episode_id = f"build17-{anchor:%Y%m%dT%H%MZ}"
        rows.append(
            {
                "independent_episode_id": episode_id,
                "split": "holdout",
                "spot_ohlc_correct": int(spot == actual),
                "spot_plus_microstructure_correct": int(rich == actual),
            }
        )
        episode_details.append(
            {
                "independent_episode_id": episode_id,
                "anchor_utc": anchor.isoformat(),
                "spot_prediction": spot,
                "microstructure_signal": micro,
                "rich_prediction": rich,
                "actual_direction": actual,
                "gold_return_15m_bps": None if ret_bps is None else str(ret_bps),
                **micro_detail,
            }
        )

    split = {
        "manifest_version": "aidy_chronological_split_manifest_v1",
        "split_digest": "build17-genuine-phasea-weekly-v1",
        "purge_required": True,
        "embargo_required": True,
        "holdout_tuning_allowed": False,
    }
    summary = summarise_incremental_holdout(rows, split_binding=split)
    spot_only_wins = sum(
        row["spot_ohlc_correct"] == 1 and row["spot_plus_microstructure_correct"] == 0
        for row in rows
    )
    rich_only_wins = sum(
        row["spot_ohlc_correct"] == 0 and row["spot_plus_microstructure_correct"] == 1
        for row in rows
    )
    discordant = spot_only_wins + rich_only_wins
    p_value = _exact_binomial_two_sided(rich_only_wins, discordant)

    result = {
        "ok": True,
        "evidence_version": PHASE_A_STUDY_VERSION,
        "source_provider": "Databento",
        "source_dataset": DATABENTO_DATASET,
        "source_schema": "tbbo",
        "entitlement": entitlement,
        "baseline_window_count": BASELINE_COUNT,
        "holdout_window_count": HOLDOUT_COUNT,
        "baseline_first_anchor_utc": baseline_anchors[0].isoformat(),
        "baseline_last_anchor_utc": baseline_anchors[-1].isoformat(),
        "holdout_first_anchor_utc": holdout_anchors[0].isoformat(),
        "holdout_last_anchor_utc": holdout_anchors[-1].isoformat(),
        "gc_lookback_minutes": GC_LOOKBACK_MINUTES,
        "target_horizon_minutes": XAU_OUTCOME_MINUTES,
        "weekday_clock_baseline_digest": baseline["baseline_digest"],
        "baseline_outcome_fields_used": baseline["outcome_fields_used"],
        "ordinary_session_activity_can_count_as_alpha": baseline[
            "ordinary_session_activity_can_count_as_alpha"
        ],
        "frozen_spot_baseline": {
            "features": ["5m_return_sign", "15m_return_sign", "60m_return_sign"],
            "rule": "majority_vote_then_15m_5m_60m_tiebreak",
        },
        "frozen_microstructure_overlay": {
            "features": [
                "matched_clock_signed_trade_imbalance_z",
                "matched_clock_vwap_distance_z",
            ],
            "rule": "override spot only when both averaged signs agree and either absolute z >= 1",
        },
        "incremental_holdout": summary,
        "paired_discordance": {
            "rich_only_correct": rich_only_wins,
            "spot_only_correct": spot_only_wins,
            "discordant_n": discordant,
            "exact_two_sided_p_value": None if p_value is None else str(p_value),
        },
        "eligible_holdout_episode_n": len(rows),
        "downloaded_window_n": len(receipts),
        "free_credit_used_usd": str(committed),
        "free_credit_phase_a_cap_usd": str(FREE_CREDIT_PHASE_A_CAP_USD),
        "paid_subscription_enabled": False,
        "live_subscription_enabled": False,
        "depth_claimed": False,
        "order_book_imbalance_claimed": False,
        "formal_forward_evidence_created": False,
        "gate_promoted": False,
        "live_weight_granted": False,
        "statistically_validated": False,
        "future_values_used_for_features": False,
        "episode_details": episode_details,
        "download_receipts": receipts,
    }
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
