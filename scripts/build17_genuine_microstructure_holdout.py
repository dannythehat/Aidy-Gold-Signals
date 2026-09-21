from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import httpx

from aidy.databento_gc import (
    DATABENTO_DATASET,
    GC_CONTINUOUS_SYMBOL,
    DatabentoHistoricalClient,
    HistoricalRequest,
)
from aidy.gc_microstructure import (
    MinuteMicrostructure,
    aggregate_tbbo_minutes,
    build_weekday_clock_baseline,
    normalize_minute,
    parse_databento_tbbo_jsonl,
)
from aidy.gc_shadow_spine import (
    digest,
    normalize_databento_api_key,
    resolve_gc_contract_map,
)
from aidy.gold_cycle_environment import build_cycle_environment
from aidy.gold_futures_microstructure_expert import summarise_incremental_holdout
from aidy.gold_m5_price_structure_expert import build_m5_price_structure_expert
from aidy.gold_price_expert_math import build_price_expert_math_packet
from aidy.market_sessions import session_code_at

DATABENTO_SYMBOLOGY_URL = "https://hist.databento.com/v0/symbology.resolve"
TARGET_VALID_EPISODES = 61
BASELINE_EPISODES = 20
DEV_EPISODES = 10
EMBARGO_EPISODES = 1
HOLDOUT_EPISODES = 30
MAX_CANDIDATE_WEEKS = 90
MAX_TOTAL_DATABENTO_SPEND_USD = Decimal(75)
ANCHOR_HOUR_UTC = 15
ANCHOR_MINUTE_UTC = 15
MICRO_MINUTE_OFFSET = -1
OUTCOME_HORIZON_MINUTES = 15
OUTCOME_NEUTRAL_BPS = Decimal(1)

MICRO_RULES = (
    "tie_break_1_0p5",
    "override_1p5_0p5",
    "veto_1_0p5",
)

SPLIT_BINDING = {
    "manifest_version": "aidy_chronological_split_manifest_v1",
    "split_digest": "build17-genuine-weekly-holdout-v1",
    "purge_required": True,
    "embargo_required": True,
    "holdout_tuning_allowed": False,
}


def _utc(value: datetime | str) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return parsed.astimezone(UTC)


def _decimal(value: Any) -> Decimal | None:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _fmt(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value.quantize(Decimal("0.000001")), "f")


def _direction_from_return(value: Decimal) -> str:
    if value >= OUTCOME_NEUTRAL_BPS:
        return "bullish"
    if value <= -OUTCOME_NEUTRAL_BPS:
        return "bearish"
    return "neutral"


def _expert_direction(value: str) -> str:
    return value if value in {"bullish", "bearish"} else "neutral"


def micro_vote(normalized: dict[str, Any], rule_id: str) -> str:
    signed = _decimal(normalized.get("signed_trade_imbalance_z"))
    vwap = _decimal(normalized.get("vwap_distance_z"))
    if signed is None or vwap is None:
        return "neutral"
    if rule_id in {"tie_break_1_0p5", "veto_1_0p5"}:
        signed_threshold = Decimal(1)
        vwap_threshold = Decimal("0.5")
    elif rule_id == "override_1p5_0p5":
        signed_threshold = Decimal("1.5")
        vwap_threshold = Decimal("0.5")
    else:
        raise ValueError(f"unknown micro rule: {rule_id}")

    if signed >= signed_threshold and vwap >= vwap_threshold:
        return "bullish"
    if signed <= -signed_threshold and vwap <= -vwap_threshold:
        return "bearish"
    return "neutral"


def combine_prediction(spot: str, micro: str, rule_id: str) -> str:
    spot = _expert_direction(spot)
    if rule_id == "tie_break_1_0p5":
        return micro if spot == "neutral" and micro != "neutral" else spot
    if rule_id == "override_1p5_0p5":
        return micro if micro != "neutral" else spot
    if rule_id == "veto_1_0p5":
        if spot == "neutral":
            return micro
        if micro != "neutral" and micro != spot:
            return "neutral"
        return spot
    raise ValueError(f"unknown micro rule: {rule_id}")


def choose_rule(dev_rows: list[dict[str, Any]]) -> dict[str, Any]:
    scored: list[dict[str, Any]] = []
    for rule_id in MICRO_RULES:
        correct = 0
        for row in dev_rows:
            micro = micro_vote(row["normalized"], rule_id)
            rich = combine_prediction(row["spot_prediction"], micro, rule_id)
            correct += int(rich == row["outcome_direction"])
        accuracy = Decimal(correct) / Decimal(len(dev_rows)) if dev_rows else Decimal(0)
        scored.append(
            {
                "rule_id": rule_id,
                "correct": correct,
                "sample_n": len(dev_rows),
                "accuracy": _fmt(accuracy),
            }
        )
    scored.sort(key=lambda row: (-Decimal(str(row["accuracy"])), str(row["rule_id"])))
    return {"selected": scored[0]["rule_id"], "candidates": scored}


def _latest_full_tbbo_day(dataset_range: dict[str, Any]) -> date:
    schema = dataset_range.get("schema")
    if not isinstance(schema, dict):
        raise TypeError("Databento dataset range has no schema map")
    tbbo = schema.get("tbbo")
    if not isinstance(tbbo, dict):
        raise TypeError("Databento entitlement has no TBBO range")
    end = _utc(str(tbbo["end"]))
    target = end.date() - timedelta(days=1)
    while target.weekday() >= 5:
        target -= timedelta(days=1)
    return target


def _candidate_mondays(latest_day: date) -> list[datetime]:
    cursor = latest_day
    while cursor.weekday() != 0:
        cursor -= timedelta(days=1)
    values = [
        datetime.combine(
            cursor - timedelta(weeks=index),
            time(ANCHOR_HOUR_UTC, ANCHOR_MINUTE_UTC),
            tzinfo=UTC,
        )
        for index in range(MAX_CANDIDATE_WEEKS)
    ]
    return sorted(values)


def _symbology_resolve(
    api_key: str,
    *,
    symbols: str,
    stype_in: str,
    stype_out: str,
    day: date,
) -> dict[str, Any]:
    response = httpx.post(
        DATABENTO_SYMBOLOGY_URL,
        auth=httpx.BasicAuth(api_key, ""),
        timeout=20.0,
        data={
            "dataset": DATABENTO_DATASET,
            "symbols": symbols,
            "stype_in": stype_in,
            "stype_out": stype_out,
            "start_date": day.isoformat(),
            "end_date": (day + timedelta(days=1)).isoformat(),
        },
        headers={"User-Agent": "AIDY-Signals/Build17-Genuine-Holdout"},
    )
    if response.is_error:
        safe = response.text.replace(api_key, "***")[:1000]
        raise RuntimeError(
            f"Databento symbology failed with HTTP {response.status_code}: {safe}"
        )
    payload = response.json()
    if not isinstance(payload, dict):
        raise TypeError("Databento symbology returned non-object")
    return payload


def _instrument_ids(payload: dict[str, Any]) -> list[str]:
    result = payload.get("result")
    if not isinstance(result, dict):
        return []
    entries = result.get(GC_CONTINUOUS_SYMBOL)
    if not isinstance(entries, list):
        return []
    return sorted(
        {
            str(row.get("s"))
            for row in entries
            if isinstance(row, dict) and str(row.get("s", "")).isdigit()
        }
    )


def _contract_map(api_key: str, day: date) -> dict[int, str]:
    continuous = _symbology_resolve(
        api_key,
        symbols=GC_CONTINUOUS_SYMBOL,
        stype_in="continuous",
        stype_out="instrument_id",
        day=day,
    )
    raw: dict[str, dict[str, Any]] = {}
    for instrument_id in _instrument_ids(continuous):
        raw[instrument_id] = _symbology_resolve(
            api_key,
            symbols=instrument_id,
            stype_in="instrument_id",
            stype_out="raw_symbol",
            day=day,
        )
    resolved = resolve_gc_contract_map(continuous, raw)
    return {int(key): value for key, value in resolved.items()}


def _bigquery_client() -> tuple[Any, Any, str]:
    from google.cloud import bigquery
    from google.oauth2 import service_account

    secret = os.environ.get("AIDY_GCP_SERVICE_ACCOUNT_JSON", "")
    if not secret.strip():
        raise RuntimeError("AIDY_GCP_SERVICE_ACCOUNT_JSON is required")
    info = json.loads(secret)
    project = str(info.get("project_id") or "")
    if not project:
        raise RuntimeError("service account project_id is missing")
    credentials = service_account.Credentials.from_service_account_info(info)
    location = os.environ.get("AIDY_BIGQUERY_LOCATION", "EU")
    client = bigquery.Client(
        project=project,
        credentials=credentials,
        location=location,
    )
    return client, bigquery, project


def _candidate_anchors(
    client: Any,
    bigquery: Any,
    *,
    project: str,
    dataset: str,
) -> list[datetime]:
    table = f"{project}.{dataset}.research_candles"
    sql = f"""
        SELECT DISTINCT TIMESTAMP_ADD(open_time_utc, INTERVAL 1 MINUTE) AS anchor_utc
        FROM `{table}`
        WHERE source = 'histdata'
          AND symbol = 'XAUUSD'
          AND timeframe = 'M1'
          AND EXTRACT(DAYOFWEEK FROM TIMESTAMP_ADD(open_time_utc, INTERVAL 1 MINUTE)) = 2
          AND EXTRACT(HOUR FROM TIMESTAMP_ADD(open_time_utc, INTERVAL 1 MINUTE)) = @hour
          AND EXTRACT(MINUTE FROM TIMESTAMP_ADD(open_time_utc, INTERVAL 1 MINUTE)) = @minute
        ORDER BY anchor_utc DESC
        LIMIT @limit
    """
    config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("hour", "INT64", ANCHOR_HOUR_UTC),
            bigquery.ScalarQueryParameter("minute", "INT64", ANCHOR_MINUTE_UTC),
            bigquery.ScalarQueryParameter("limit", "INT64", MAX_CANDIDATE_WEEKS),
        ]
    )
    anchors = [_utc(row["anchor_utc"]) for row in client.query(sql, job_config=config).result()]
    return sorted(anchors)


def _research_rows_for_anchor(
    client: Any,
    bigquery: Any,
    *,
    project: str,
    dataset: str,
    anchor: datetime,
) -> dict[str, list[dict[str, Any]]]:
    table = f"{project}.{dataset}.research_candles"
    sql = f"""
        SELECT research_identity, provenance_class, pit_eligible, symbol, timeframe,
               open_time_utc, open, high, low, close, source,
               source_file_sha256, source_payload_sha256, derivation_version
        FROM `{table}`
        WHERE source = 'histdata'
          AND symbol = 'XAUUSD'
          AND timeframe IN ('M1','M5','M15','H1','H4','D1')
          AND open_time_utc >= @start
          AND open_time_utc < @end
        ORDER BY open_time_utc, timeframe, research_identity
    """
    config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter(
                "start", "TIMESTAMP", anchor - timedelta(hours=8)
            ),
            bigquery.ScalarQueryParameter(
                "end",
                "TIMESTAMP",
                anchor + timedelta(minutes=OUTCOME_HORIZON_MINUTES),
            ),
        ]
    )
    grouped = {name: [] for name in ("M1", "M5", "M15", "H1", "H4", "D1")}
    for row in client.query(sql, job_config=config).result():
        value = dict(row.items())
        value["open_time_utc"] = _utc(value["open_time_utc"]).isoformat()
        timeframe = str(value.get("timeframe") or "")
        if timeframe in grouped:
            grouped[timeframe].append(value)
    return grouped


def _row_by_open(
    candles: list[dict[str, Any]],
    open_time: datetime,
) -> dict[str, Any] | None:
    for candle in candles:
        if _utc(candle["open_time_utc"]) == open_time:
            return candle
    return None


def _return_row(
    price_packet: dict[str, Any],
    timeframe: str,
    lookback: str,
) -> dict[str, Any] | None:
    timeframes = price_packet.get("timeframes")
    if not isinstance(timeframes, dict):
        return None
    payload = timeframes.get(timeframe)
    if not isinstance(payload, dict):
        return None
    primitives = payload.get("primitives")
    if not isinstance(primitives, dict):
        return None
    returns = primitives.get("multi_lookback_returns")
    if not isinstance(returns, dict):
        return None
    values = returns.get("values")
    if not isinstance(values, dict):
        return None
    row = values.get(lookback)
    return row if isinstance(row, dict) else None


def _direction_for_frame(price_packet: dict[str, Any], timeframe: str) -> str:
    row = _return_row(price_packet, timeframe, "5_bar")
    return str(row.get("direction") or "unknown") if row is not None else "unknown"


def _return_for_frame(price_packet: dict[str, Any], timeframe: str) -> str | None:
    row = _return_row(price_packet, timeframe, "1_bar")
    if row is None:
        return None
    value = row.get("return_bps")
    return str(value) if value is not None else None


def _spot_prediction(
    *,
    anchor: datetime,
    month_candles: dict[str, list[Any]],
) -> tuple[str, str]:
    rows = [
        dict(candle)
        for timeframe in ("M1", "M5", "M15", "H1", "H4", "D1")
        for candle in month_candles[timeframe]
    ]
    packet = build_price_expert_math_packet(
        as_of=anchor,
        symbol="XAUUSD",
        candle_rows=rows,
        mode="retrospective",
    )
    timeframes: dict[str, Any] = {}
    for timeframe in ("M5", "M15", "H1", "H4", "D1"):
        timeframes[timeframe] = {
            "net_close_direction": _direction_for_frame(packet, timeframe),
            "state": packet["timeframes"][timeframe]["state"],
        }

    movement = {
        "five_minute_distribution_state": "unknown",
        "five_minute_range_state": "unknown",
        "windows": {
            "5m": {
                "direction": _direction_for_frame(packet, "M5"),
                "return_bps": _return_for_frame(packet, "M5"),
            },
            "15m": {
                "direction": _direction_for_frame(packet, "M15"),
                "return_bps": _return_for_frame(packet, "M15"),
            },
            "60m": {
                "direction": _direction_for_frame(packet, "H1"),
                "return_bps": _return_for_frame(packet, "H1"),
            },
        },
    }
    environment = build_cycle_environment(
        as_of_utc=anchor,
        target_window_start_utc=anchor + timedelta(minutes=OUTCOME_HORIZON_MINUTES),
        session_code=session_code_at(anchor),
        observed_state=_direction_for_frame(packet, "M15"),
        gold_state={
            "market_structure": {"timeframes": timeframes},
            "move_observation": movement,
            "volatility": {"state": "unknown"},
            "scheduled_event_risk": {"state": "unknown"},
            "unknowns": ["retrospective_build17_nonprice_context"],
        },
        semantic_context={
            "data_quality": {
                "quote_state": "unknown",
                "quote_freshness": "unknown",
                "spread_state": "unknown",
            },
            "cross_market": {"series": {}},
        },
        regime={"compound_regime_key": "retrospective_build17"},
    )
    expert = build_m5_price_structure_expert(
        global_environment=environment,
        price_math_packet=packet,
    )
    conclusion = str(expert["expert_packet"]["conclusion"])
    return _expert_direction(conclusion), str(expert["expert_packet"]["packet_digest"])


def _outcome(
    *,
    anchor: datetime,
    month_candles: dict[str, list[Any]],
) -> tuple[str, str] | None:
    m1 = month_candles["M1"]
    start = _row_by_open(m1, anchor - timedelta(minutes=1))
    end = _row_by_open(
        m1,
        anchor + timedelta(minutes=OUTCOME_HORIZON_MINUTES - 1),
    )
    if start is None or end is None:
        return None
    start_close = Decimal(str(start["close"]))
    end_close = Decimal(str(end["close"]))
    if start_close <= 0:
        return None
    value = (end_close / start_close - Decimal(1)) * Decimal(10000)
    return _direction_from_return(value), _fmt(value) or "0"


def _download_micro_minute(
    *,
    client: DatabentoHistoricalClient,
    api_key: str,
    anchor: datetime,
    output_dir: Path,
    prior_spend: Decimal,
) -> tuple[MinuteMicrostructure | None, Decimal, dict[str, Any]]:
    start = anchor + timedelta(minutes=MICRO_MINUTE_OFFSET)
    end = anchor
    request = HistoricalRequest(
        schema="tbbo",
        start=start.isoformat(),
        end=end.isoformat(),
    )
    quote = client.estimate_cost(request, prior_committed_usd=prior_spend)
    if not quote.approved:
        raise RuntimeError(
            f"Databento request rejected by existing research spend policy at {anchor.isoformat()}"
        )
    if prior_spend + quote.quoted_cost_usd > MAX_TOTAL_DATABENTO_SPEND_USD:
        raise RuntimeError("Build 17 genuine holdout hit the $75 research spend cap")
    path = output_dir / f"tbbo-{anchor.date().isoformat()}.jsonl"
    receipt = client.download_jsonl(request, quote=quote, output_path=path)
    contract_map = _contract_map(api_key, anchor.date())
    trades = parse_databento_tbbo_jsonl(
        path.read_text(encoding="utf-8"),
        contract_by_instrument_id=contract_map,
    )
    minutes = aggregate_tbbo_minutes(trades)
    target = start.replace(second=0, microsecond=0)
    exact = [row for row in minutes if row.minute_utc == target]
    minute = exact[0] if len(exact) == 1 else None
    return minute, prior_spend + quote.quoted_cost_usd, {
        "anchor_utc": anchor.isoformat(),
        "quoted_cost_usd": str(quote.quoted_cost_usd),
        "request_digest": request.request_digest,
        "receipt_sha256": receipt["sha256"],
        "trade_rows": len(trades),
        "minute_count": len(minutes),
        "contract_symbols": sorted({row.contract_symbol for row in minutes}),
    }


def _evaluate_rows(
    rows: list[dict[str, Any]],
    *,
    baseline: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    normalized_rows: list[dict[str, Any]] = []
    for row in rows:
        normalized_rows.append(
            {
                **row,
                "normalized": normalize_minute(row["micro_minute"], baseline),
            }
        )

    dev_start = BASELINE_EPISODES
    dev_end = dev_start + DEV_EPISODES
    embargo_end = dev_end + EMBARGO_EPISODES
    dev = normalized_rows[dev_start:dev_end]
    holdout = normalized_rows[embargo_end:embargo_end + HOLDOUT_EPISODES]
    rule = choose_rule(dev)

    holdout_rows: list[dict[str, Any]] = []
    detailed: list[dict[str, Any]] = []
    for row in holdout:
        micro = micro_vote(row["normalized"], str(rule["selected"]))
        rich = combine_prediction(
            row["spot_prediction"],
            micro,
            str(rule["selected"]),
        )
        spot_correct = int(row["spot_prediction"] == row["outcome_direction"])
        rich_correct = int(rich == row["outcome_direction"])
        holdout_rows.append(
            {
                "split": "holdout",
                "independent_episode_id": row["episode_id"],
                "spot_ohlc_correct": spot_correct,
                "spot_plus_microstructure_correct": rich_correct,
            }
        )
        detailed.append(
            {
                "episode_id": row["episode_id"],
                "anchor_utc": row["anchor_utc"],
                "spot_prediction": row["spot_prediction"],
                "micro_vote": micro,
                "rich_prediction": rich,
                "outcome_direction": row["outcome_direction"],
                "outcome_return_bps": row["outcome_return_bps"],
                "spot_correct": spot_correct,
                "rich_correct": rich_correct,
                "normalized": row["normalized"],
            }
        )

    summary = summarise_incremental_holdout(
        holdout_rows,
        split_binding=SPLIT_BINDING,
    )
    return {
        "dev_rule_selection": rule,
        "holdout_summary": summary,
        "split": {
            "normalization_train_n": BASELINE_EPISODES,
            "dev_n": DEV_EPISODES,
            "embargo_n": EMBARGO_EPISODES,
            "holdout_n": HOLDOUT_EPISODES,
        },
    }, detailed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="build17_genuine_holdout.json")
    parser.add_argument("--raw-dir", default="/tmp/build17_databento")
    args = parser.parse_args()

    raw_secret = os.environ.get("DATABENTO_API_KEY", "")
    if not raw_secret.strip():
        raise RuntimeError("DATABENTO_API_KEY is required")
    api_key = normalize_databento_api_key(raw_secret)
    os.environ["DATABENTO_API_KEY"] = api_key

    raw_dir = Path(args.raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    head_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    bq_client, bigquery, project = _bigquery_client()
    dataset = os.environ.get("AIDY_BIGQUERY_DATASET", "aidy_analytics_test")
    candidates = _candidate_anchors(
        bq_client,
        bigquery,
        project=project,
        dataset=dataset,
    )

    episodes: list[dict[str, Any]] = []
    purchases: list[dict[str, Any]] = []
    spend = Decimal(0)

    with DatabentoHistoricalClient.from_env() as client:
        entitlement = client.assert_gc_entitlement()
        client.dataset_range()

        for anchor in candidates:
            if len(episodes) >= TARGET_VALID_EPISODES:
                break
            month_candles = _research_rows_for_anchor(
                bq_client,
                bigquery,
                project=project,
                dataset=dataset,
                anchor=anchor,
            )
            outcome = _outcome(anchor=anchor, month_candles=month_candles)
            if outcome is None:
                continue
            spot_prediction, spot_digest = _spot_prediction(
                anchor=anchor,
                month_candles=month_candles,
            )
            minute, spend, purchase = _download_micro_minute(
                client=client,
                api_key=api_key,
                anchor=anchor,
                output_dir=raw_dir,
                prior_spend=spend,
            )
            purchases.append(purchase)
            if minute is None:
                continue
            outcome_direction, outcome_return = outcome
            episodes.append(
                {
                    "episode_id": f"build17-{anchor.date().isoformat()}",
                    "anchor_utc": anchor.isoformat(),
                    "spot_prediction": spot_prediction,
                    "spot_packet_digest": spot_digest,
                    "outcome_direction": outcome_direction,
                    "outcome_return_bps": outcome_return,
                    "micro_minute": minute,
                }
            )

    if len(episodes) < TARGET_VALID_EPISODES:
        raise RuntimeError(
            f"Build 17 needs {TARGET_VALID_EPISODES} valid weekly episodes; got {len(episodes)}"
        )

    episodes = episodes[-TARGET_VALID_EPISODES:]
    baseline_minutes = [row["micro_minute"] for row in episodes[:BASELINE_EPISODES]]
    baseline = build_weekday_clock_baseline(
        baseline_minutes,
        minimum_bucket_n=BASELINE_EPISODES,
    )
    evaluation, detailed = _evaluate_rows(episodes, baseline=baseline)
    holdout = evaluation["holdout_summary"]

    evidence = {
        "evidence_version": "aidy_build17_genuine_microstructure_holdout_v1",
        "candidate_head_sha": head_sha,
        "source_provider": "Databento",
        "source_dataset": DATABENTO_DATASET,
        "source_schema": "tbbo",
        "xau_baseline_source": "BigQuery_research_candles_HistData_XAUUSD_plus_Build5_M5_expert",
        "weekly_anchor": "Monday_15:15_UTC",
        "target_valid_episodes": TARGET_VALID_EPISODES,
        "valid_episode_count": len(episodes),
        "normalization_train_n": BASELINE_EPISODES,
        "dev_n": DEV_EPISODES,
        "embargo_n": EMBARGO_EPISODES,
        "holdout_n": HOLDOUT_EPISODES,
        "databento_total_quoted_spend_usd": str(spend),
        "databento_spend_cap_usd": str(MAX_TOTAL_DATABENTO_SPEND_USD),
        "user_authorized_ceiling_usd": "150",
        "existing_research_policy_cap_respected": spend <= MAX_TOTAL_DATABENTO_SPEND_USD,
        "entitlement": entitlement,
        "split_binding": SPLIT_BINDING,
        "baseline_digest": baseline["baseline_digest"],
        "dev_rule_selection": evaluation["dev_rule_selection"],
        "holdout_summary": holdout,
        "holdout_detail": detailed,
        "purchases": purchases,
        "genuine_microstructure": True,
        "spot_ohlc_expert_baseline": True,
        "purge_required": True,
        "embargo_required": True,
        "holdout_tuning_allowed": False,
        "formal_forward_evidence_created": False,
        "statistically_validated": False,
        "gate_promoted": False,
        "live_weight_granted": False,
        "paid_live_feed_activated": False,
        "depth_claimed": False,
        "order_book_imbalance_claimed": False,
    }
    evidence["evidence_digest"] = digest(evidence)

    serializable = json.loads(
        json.dumps(
            evidence,
            default=lambda value: value.as_dict()
            if isinstance(value, MinuteMicrostructure)
            else str(value),
        )
    )
    Path(args.output).write_text(
        json.dumps(serializable, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "ok": True,
                "valid_episode_count": len(episodes),
                "quoted_spend_usd": str(spend),
                "selected_rule": evaluation["dev_rule_selection"]["selected"],
                "holdout_state": holdout["state"],
                "holdout_n": holdout["sample_n"],
                "spot_accuracy": holdout["spot_ohlc_accuracy"],
                "rich_accuracy": holdout["spot_plus_microstructure_accuracy"],
                "incremental_accuracy": holdout["incremental_accuracy"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
