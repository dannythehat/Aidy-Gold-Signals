from __future__ import annotations

import csv
import io
import json
import math
import os
import subprocess
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
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
    aggregate_tbbo_minutes,
    build_weekday_clock_baseline,
    normalize_minute,
    parse_databento_tbbo_jsonl,
)
from aidy.gc_shadow_spine import digest, normalize_databento_api_key, resolve_gc_contract_map
from aidy.gold_cycle_environment import build_cycle_environment
from aidy.gold_m15_price_structure_expert import build_m15_price_structure_expert
from aidy.gold_m5_price_structure_expert import build_m5_price_structure_expert
from aidy.gold_price_expert_math import build_price_expert_math_packet
from aidy.historical_backfill import (
    HistDataPeriod,
    build_research_candles,
    download_histdata_period,
    parse_histdata_m1,
    read_histdata_archive,
)
from aidy.market_sessions import session_code_at

WINDOW_COUNT = 120
WINDOW_MINUTES = 15
START = datetime(2023, 8, 1, 15, 0, tzinfo=UTC)
BASELINE_N = 20
TRAIN_N = 50
EMBARGO_N = 10
HOLDOUT_N = 40
MIN_VALID_HOLDOUT_N = 30
MAX_TOTAL_DATABENTO_COST_USD = Decimal("10.00")
DATABENTO_SYMBOLOGY_URL = "https://hist.databento.com/v0/symbology.resolve"
MODEL_VERSION = "build17_spot_plus_microstructure_logistic_v1"
OUTCOME_HORIZON_MINUTES = 14


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _utc(value: datetime | str) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return parsed.astimezone(UTC)


def _window_starts() -> list[datetime]:
    return [START + timedelta(weeks=index) for index in range(WINDOW_COUNT)]


def _requests() -> list[HistoricalRequest]:
    return [
        HistoricalRequest(
            schema="tbbo",
            start=start.isoformat(),
            end=(start + timedelta(minutes=WINDOW_MINUTES)).isoformat(),
        )
        for start in _window_starts()
    ]


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
        safe = response.text.replace(api_key, "***")[:1000]
        raise RuntimeError(
            f"Databento Build17 symbology failed HTTP {response.status_code}: {safe}"
        )
    payload = response.json()
    if not isinstance(payload, dict):
        raise TypeError("Databento symbology returned non-object")
    return payload


def _instrument_ids(payload: Mapping[str, Any]) -> list[str]:
    result = payload.get("result")
    if not isinstance(result, Mapping):
        raise TypeError("continuous symbology result missing")
    entries = result.get(GC_CONTINUOUS_SYMBOL)
    if not isinstance(entries, list):
        raise TypeError("continuous symbology entries missing")
    ids = sorted(
        {
            str(entry.get("s"))
            for entry in entries
            if isinstance(entry, Mapping) and str(entry.get("s") or "").isdigit()
        }
    )
    if not ids:
        raise RuntimeError("continuous symbology returned no instrument ids")
    return ids


def _contract_map(api_key: str, starts: Sequence[datetime]) -> dict[int, str]:
    start_date = min(starts).date().isoformat()
    end_date = (max(starts).date() + timedelta(days=2)).isoformat()
    continuous = _symbology_resolve(
        api_key,
        symbols=GC_CONTINUOUS_SYMBOL,
        stype_in="continuous",
        stype_out="instrument_id",
        start_date=start_date,
        end_date=end_date,
    )
    raw: dict[str, dict[str, Any]] = {}
    for instrument_id in _instrument_ids(continuous):
        raw[instrument_id] = _symbology_resolve(
            api_key,
            symbols=instrument_id,
            stype_in="instrument_id",
            stype_out="raw_symbol",
            start_date=start_date,
            end_date=end_date,
        )
    return resolve_gc_contract_map(continuous, raw)


def _download_microstructure(
    *,
    api_key: str,
    output_dir: Path,
) -> tuple[list[dict[str, Any]], Decimal, dict[int, str]]:
    starts = _window_starts()
    requests = _requests()
    quotes: list[Any] = []
    total = Decimal(0)
    with DatabentoHistoricalClient(api_key) as client:
        entitlement = client.assert_gc_entitlement()
        for request in requests:
            quote = client.estimate_cost(request, prior_committed_usd=total)
            if not quote.approved:
                raise RuntimeError("Databento request violates bounded historical policy")
            total += quote.quoted_cost_usd
            quotes.append(quote)
        if total > MAX_TOTAL_DATABENTO_COST_USD:
            raise RuntimeError(
                f"Build17 quote {total} exceeds one-off safety cap "
                f"{MAX_TOTAL_DATABENTO_COST_USD}"
            )

        contract_map = _contract_map(api_key, starts)
        receipts: list[dict[str, Any]] = []
        committed = Decimal(0)
        for index, (request, quote) in enumerate(zip(requests, quotes, strict=True)):
            # Re-bind the quote to the exact cumulative spend known before this request.
            rebound = client.estimate_cost(request, prior_committed_usd=committed)
            if rebound.quoted_cost_usd > quote.quoted_cost_usd:
                quote = rebound
            path = output_dir / "tbbo" / f"window_{index:03d}.jsonl"
            receipt = client.download_jsonl(request, quote=quote, output_path=path)
            committed += Decimal(str(receipt["quoted_cost_usd"]))
            receipts.append(
                {
                    "index": index,
                    "start": request.start,
                    "end": request.end,
                    "quoted_cost_usd": receipt["quoted_cost_usd"],
                    "sha256": receipt["sha256"],
                    "byte_count": receipt["byte_count"],
                    "path": str(path),
                }
            )
    if committed > MAX_TOTAL_DATABENTO_COST_USD:
        raise RuntimeError("Build17 actual committed Databento cost exceeded safety cap")
    return receipts, committed, contract_map


def _load_histdata(
    starts: Sequence[datetime],
    *,
    cache_dir: Path,
) -> tuple[dict[datetime, Any], list[dict[str, object]]]:
    years = sorted({stamp.year for stamp in starts})
    m1_by_time: dict[datetime, Any] = {}
    expert_rows: list[dict[str, object]] = []
    ingest_time = datetime(2026, 9, 21, 0, 0, tzinfo=UTC)
    for year in years:
        period = HistDataPeriod(year)
        path = download_histdata_period(period, cache_dir=cache_dir)
        archive = read_histdata_archive(path, period)
        bars, _stats = parse_histdata_m1(archive.payload_text)
        for bar in bars:
            m1_by_time[bar.open_time_utc] = bar
        derived = build_research_candles(
            bars,
            timeframes=("M5", "M15"),
            symbol="XAUUSD",
            archive=archive,
            ingested_at=ingest_time,
            backfill_run_id=f"build17-{year}",
        )
        for timeframe in ("M5", "M15"):
            expert_rows.extend(candle.to_row() for candle in derived[timeframe])
    expert_rows.sort(key=lambda row: (_utc(str(row["open_time_utc"])), str(row["timeframe"])))
    return m1_by_time, expert_rows


def _direction_from_packet(packet: Mapping[str, Any], timeframe: str) -> str:
    payload = packet["timeframes"][timeframe]
    values = payload["primitives"]["multi_lookback_returns"]["values"]
    for name in ("1_bar", "5_bar", "8_bar"):
        row = values.get(name)
        if isinstance(row, Mapping):
            direction = str(row.get("direction") or "").lower()
            if direction in {"bullish", "up"}:
                return "up"
            if direction in {"bearish", "down"}:
                return "down"
    return "flat"


def _environment(as_of: datetime, packet: Mapping[str, Any]) -> dict[str, Any]:
    m5 = _direction_from_packet(packet, "M5")
    m15 = _direction_from_packet(packet, "M15")
    return build_cycle_environment(
        as_of_utc=as_of,
        target_window_start_utc=as_of + timedelta(minutes=15),
        session_code=session_code_at(as_of),
        observed_state="neutral",
        gold_state={
            "market_structure": {
                "timeframes": {
                    "M5": {
                        "net_close_direction": m5,
                        "directional_persistence_ratio": "0.50",
                        "latest_close_range_position": "0.50",
                        "state": "known" if m5 in {"up", "down"} else "unknown",
                    },
                    "M15": {
                        "net_close_direction": m15,
                        "directional_persistence_ratio": "0.50",
                        "latest_close_range_position": "0.50",
                        "state": "known" if m15 in {"up", "down"} else "unknown",
                    },
                    "H1": {"net_close_direction": "flat", "state": "unknown"},
                    "H4": {"net_close_direction": "flat", "state": "unknown"},
                    "D1": {"net_close_direction": "flat", "state": "unknown"},
                }
            },
            "move_observation": {
                "five_minute_distribution_state": "unknown",
                "five_minute_range_state": "unknown",
                "windows": {
                    "5m": {"direction": m5, "return_bps": None},
                    "15m": {"direction": m15, "return_bps": None},
                    "60m": {"direction": "flat", "return_bps": None},
                },
            },
            "volatility": {"state": "unknown"},
            "scheduled_event_risk": {"state": "unknown", "timing_state": "unknown"},
        },
        semantic_context={
            "data_quality": {
                "quote_state": "known",
                "quote_freshness": "historical",
                "spread_state": "unknown",
            },
            "cross_market": {"series": {}},
        },
        regime={"compound_regime_key": "retrospective_build17"},
    )


def _vote_value(vote: str) -> int:
    return 1 if vote == "bullish" else -1 if vote == "bearish" else 0


def _spot_vote(
    *,
    as_of: datetime,
    expert_rows: Sequence[Mapping[str, Any]],
) -> tuple[int, dict[str, Any]]:
    # Only a bounded trailing context enters the packet. Future candles are
    # filtered again inside Build 4 by the frozen as-of.
    cutoff = as_of - timedelta(hours=8)
    rows = [
        row
        for row in expert_rows
        if cutoff <= _utc(str(row["open_time_utc"])) <= as_of
    ]
    packet = build_price_expert_math_packet(
        as_of=as_of,
        symbol="XAUUSD",
        candle_rows=rows,
        mode="retrospective",
    )
    env = _environment(as_of, packet)
    m5 = build_m5_price_structure_expert(
        global_environment=env,
        price_math_packet=packet,
    )
    m15 = build_m15_price_structure_expert(
        global_environment=env,
        price_math_packet=packet,
    )
    m5_vote = str(m5["expert_packet"]["conclusion"])
    m15_vote = str(m15["expert_packet"]["conclusion"])
    m5_value = _vote_value(m5_vote)
    m15_value = _vote_value(m15_vote)

    # M5 owns the 15-minute horizon. M15 is a secondary spot expert when M5
    # abstains; if both abstain, the latest completed M5 return is the frozen
    # OHLC-only fallback.
    if m5_value:
        score = m5_value
        source = "m5_expert"
    elif m15_value:
        score = m15_value
        source = "m15_expert_fallback"
    else:
        latest = _direction_from_packet(packet, "M5")
        score = 1 if latest == "up" else -1
        source = "m5_latest_completed_return_fallback"
    return score, {
        "m5_conclusion": m5_vote,
        "m15_conclusion": m15_vote,
        "spot_baseline_source": source,
        "price_math_packet_digest": packet["packet_digest"],
    }


def _outcome(
    start: datetime,
    m1_by_time: Mapping[datetime, Any],
) -> tuple[int, str] | None:
    entry = m1_by_time.get(start)
    final = m1_by_time.get(start + timedelta(minutes=OUTCOME_HORIZON_MINUTES))
    if entry is None or final is None:
        return None
    entry_close = Decimal(str(entry.close))
    final_close = Decimal(str(final.close))
    if entry_close <= 0:
        return None
    ret = (final_close / entry_close - Decimal(1)) * Decimal(10000)
    direction = 1 if ret > 0 else -1 if ret < 0 else 0
    if direction == 0:
        return None
    return direction, str(ret.quantize(Decimal("0.000001")))


def _select_micro_minute(
    *,
    path: Path,
    contract_map: Mapping[int, str],
    start: datetime,
) -> Any | None:
    trades = parse_databento_tbbo_jsonl(
        path.read_text(encoding="utf-8"),
        contract_by_instrument_id=contract_map,
    )
    minutes = aggregate_tbbo_minutes(trades)
    candidates = [row for row in minutes if row.minute_utc == start]
    if not candidates:
        return None
    return max(candidates, key=lambda row: row.trade_volume)


def _float(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    return parsed if math.isfinite(parsed) else 0.0


def _features(spot_score: int, normalized: Mapping[str, Any], minute: Any) -> list[float]:
    signed_z = _float(normalized.get("signed_trade_imbalance_z"))
    vwap_z = _float(normalized.get("vwap_distance_z"))
    volume_z = _float(normalized.get("volume_z"))
    spread_z = _float(normalized.get("spread_z"))
    raw_signed = _float(minute.signed_trade_imbalance)
    return [
        1.0,
        float(spot_score),
        signed_z,
        vwap_z,
        volume_z,
        spread_z,
        signed_z * volume_z,
        signed_z * spread_z,
        raw_signed,
    ]


def _sigmoid(value: float) -> float:
    value = max(-30.0, min(30.0, value))
    return 1.0 / (1.0 + math.exp(-value))


def _fit_logistic(rows: Sequence[Mapping[str, Any]]) -> list[float]:
    width = len(rows[0]["features"])
    weights = [0.0] * width
    learning_rate = 0.03
    l2 = 0.02
    epochs = 800
    n = float(len(rows))
    for _ in range(epochs):
        gradients = [0.0] * width
        for row in rows:
            x = row["features"]
            target = 1.0 if int(row["outcome_direction"]) > 0 else 0.0
            score = sum(weight * feature for weight, feature in zip(weights, x, strict=True))
            error = _sigmoid(score) - target
            for index, feature in enumerate(x):
                gradients[index] += error * feature
        for index in range(width):
            regularizer = 0.0 if index == 0 else l2 * weights[index]
            weights[index] -= learning_rate * (gradients[index] / n + regularizer)
    return weights


def _predict(weights: Sequence[float], features: Sequence[float]) -> int:
    score = sum(weight * feature for weight, feature in zip(weights, features, strict=True))
    return 1 if _sigmoid(score) >= 0.5 else -1


def _accuracy(rows: Sequence[Mapping[str, Any]], *, rich: bool, weights: Sequence[float]) -> tuple[int, int]:
    correct = 0
    for row in rows:
        prediction = (
            _predict(weights, row["features"])
            if rich
            else int(row["spot_score"])
        )
        correct += int(prediction == int(row["outcome_direction"]))
    return correct, len(rows)


def main() -> int:
    raw_key = os.environ.get("DATABENTO_API_KEY", "")
    if not raw_key.strip():
        raise RuntimeError("DATABENTO_API_KEY is required")
    api_key = normalize_databento_api_key(raw_key)
    root = Path(__file__).resolve().parents[1]
    output_dir = root / ".build17_phasea"
    output_dir.mkdir(parents=True, exist_ok=True)
    starts = _window_starts()

    receipts, committed, contract_map = _download_microstructure(
        api_key=api_key,
        output_dir=output_dir,
    )
    m1_by_time, expert_rows = _load_histdata(
        starts,
        cache_dir=output_dir / "histdata",
    )

    micro_minutes: list[Any | None] = []
    for receipt, start in zip(receipts, starts, strict=True):
        micro_minutes.append(
            _select_micro_minute(
                path=Path(str(receipt["path"])),
                contract_map=contract_map,
                start=start,
            )
        )

    baseline_minutes = [
        minute
        for minute in micro_minutes[:BASELINE_N]
        if minute is not None
    ]
    if len(baseline_minutes) < BASELINE_N:
        raise RuntimeError(
            f"Build17 baseline requires {BASELINE_N} genuine minutes; "
            f"got {len(baseline_minutes)}"
        )
    baseline = build_weekday_clock_baseline(
        baseline_minutes,
        minimum_bucket_n=BASELINE_N,
    )

    episodes: list[dict[str, Any]] = []
    for index in range(BASELINE_N, WINDOW_COUNT):
        minute = micro_minutes[index]
        if minute is None:
            continue
        normalized = normalize_minute(minute, baseline)
        if normalized.get("state") != "known":
            continue
        start = starts[index]
        outcome = _outcome(start, m1_by_time)
        if outcome is None:
            continue
        outcome_direction, outcome_return_bps = outcome
        as_of = start + timedelta(minutes=1)
        spot_score, spot_audit = _spot_vote(as_of=as_of, expert_rows=expert_rows)
        features = _features(spot_score, normalized, minute)
        if index < BASELINE_N + TRAIN_N:
            split = "train"
        elif index < BASELINE_N + TRAIN_N + EMBARGO_N:
            split = "embargo"
        else:
            split = "holdout"
        episodes.append(
            {
                "index": index,
                "independent_episode_id": f"build17-week-{index:03d}",
                "window_start_utc": start.isoformat(),
                "split": split,
                "contract_symbol": minute.contract_symbol,
                "spot_score": spot_score,
                "spot_audit": spot_audit,
                "microstructure_minute_digest": minute.as_dict()["minute_digest"],
                "normalization_digest": normalized["normalization_digest"],
                "features": features,
                "outcome_direction": outcome_direction,
                "outcome_return_bps": outcome_return_bps,
            }
        )

    train_rows = [row for row in episodes if row["split"] == "train"]
    holdout_rows = [row for row in episodes if row["split"] == "holdout"]
    embargo_rows = [row for row in episodes if row["split"] == "embargo"]
    if len(train_rows) < 40:
        raise RuntimeError(f"Build17 valid train cohort too small: {len(train_rows)}")
    if len(holdout_rows) < MIN_VALID_HOLDOUT_N:
        raise RuntimeError(f"Build17 valid holdout cohort too small: {len(holdout_rows)}")

    weights = _fit_logistic(train_rows)
    train_spot_correct, train_n = _accuracy(train_rows, rich=False, weights=weights)
    train_rich_correct, _ = _accuracy(train_rows, rich=True, weights=weights)
    holdout_spot_correct, holdout_n = _accuracy(holdout_rows, rich=False, weights=weights)
    holdout_rich_correct, _ = _accuracy(holdout_rows, rich=True, weights=weights)

    spot_acc = Decimal(holdout_spot_correct) / Decimal(holdout_n)
    rich_acc = Decimal(holdout_rich_correct) / Decimal(holdout_n)
    delta = rich_acc - spot_acc
    state = (
        "incremental_value_observed"
        if delta > 0
        else "null_no_incremental_value"
        if delta == 0
        else "microstructure_underperformed_spot"
    )

    holdout_rows_public = [
        {
            "independent_episode_id": row["independent_episode_id"],
            "window_start_utc": row["window_start_utc"],
            "spot_ohlc_correct": int(int(row["spot_score"]) == int(row["outcome_direction"])),
            "spot_plus_microstructure_correct": int(
                _predict(weights, row["features"]) == int(row["outcome_direction"])
            ),
            "outcome_return_bps": row["outcome_return_bps"],
            "contract_symbol": row["contract_symbol"],
        }
        for row in holdout_rows
    ]

    head_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        text=True,
    ).strip()
    evidence: dict[str, Any] = {
        "evidence_version": "aidy_build17_genuine_phasea_holdout_v1",
        "candidate_head_sha": head_sha,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "source_provider": "Databento",
        "source_dataset": DATABENTO_DATASET,
        "source_schema": "tbbo",
        "xau_reference_source": "HistData XAUUSD M1 retrospective history",
        "planned_window_count": WINDOW_COUNT,
        "baseline_planned_n": BASELINE_N,
        "train_planned_n": TRAIN_N,
        "embargo_planned_n": EMBARGO_N,
        "holdout_planned_n": HOLDOUT_N,
        "valid_train_n": len(train_rows),
        "valid_embargo_n": len(embargo_rows),
        "valid_holdout_n": holdout_n,
        "minimum_valid_holdout_n": MIN_VALID_HOLDOUT_N,
        "independent_weekly_windows": True,
        "baseline_frozen_before_training_outcomes": True,
        "holdout_tuning_allowed": False,
        "purge_required": True,
        "embargo_required": True,
        "model_version": MODEL_VERSION,
        "model_architecture_frozen_before_holdout": True,
        "model_weights": [round(value, 10) for value in weights],
        "model_digest": digest(
            {
                "version": MODEL_VERSION,
                "weights": [round(value, 10) for value in weights],
                "training_episode_ids": [
                    row["independent_episode_id"] for row in train_rows
                ],
            }
        ),
        "train_spot_accuracy": str(
            (Decimal(train_spot_correct) / Decimal(train_n)).quantize(Decimal("0.000001"))
        ),
        "train_spot_plus_microstructure_accuracy": str(
            (Decimal(train_rich_correct) / Decimal(train_n)).quantize(Decimal("0.000001"))
        ),
        "holdout_spot_ohlc_accuracy": str(spot_acc.quantize(Decimal("0.000001"))),
        "holdout_spot_plus_microstructure_accuracy": str(
            rich_acc.quantize(Decimal("0.000001"))
        ),
        "holdout_incremental_accuracy": str(delta.quantize(Decimal("0.000001"))),
        "holdout_state": state,
        "holdout_rows": holdout_rows_public,
        "genuine_trade_volume": True,
        "genuine_pretrade_bbo_spread": True,
        "known_aggressor_signed_trade_flow": True,
        "unknown_aggressor_side_imputed": False,
        "session_anchored_vwap": True,
        "matched_weekday_clock_normalization": True,
        "baseline_digest": baseline["baseline_digest"],
        "depth_claimed": False,
        "order_book_imbalance_claimed": False,
        "mbo_used": False,
        "mbp10_used": False,
        "databento_committed_cost_usd": str(committed),
        "databento_cost_cap_usd": str(MAX_TOTAL_DATABENTO_COST_USD),
        "download_performed": True,
        "historical_only": True,
        "recurring_subscription_enabled": False,
        "live_or_delayed_paid_feed_enabled": False,
        "paid_activation_performed": False,
        "formal_forward_evidence_created": False,
        "statistically_validated": False,
        "gate_promoted": False,
        "live_weight_granted": False,
        "live_money_execution_allowed": False,
        "api_key_recorded": False,
    }
    evidence["evidence_digest"] = digest(evidence)

    output = root / "build17_genuine_phasea_holdout.json"
    output.write_text(_canonical(evidence) + "\n", encoding="utf-8")
    print(_canonical(evidence))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
