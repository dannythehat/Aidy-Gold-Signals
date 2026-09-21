from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from pathlib import Path
from typing import Any

import httpx
from google.cloud import bigquery
from google.oauth2 import service_account

from aidy.gc_microstructure import (
    aggregate_tbbo_minutes,
    build_weekday_clock_baseline,
    normalize_minute,
    parse_databento_tbbo_jsonl,
    verify_weekday_clock_baseline,
)
from aidy.gc_shadow_spine import normalize_databento_api_key
from aidy.gold_cycle_environment import build_cycle_environment
from aidy.gold_futures_microstructure_expert import summarise_incremental_holdout
from aidy.gold_m5_price_structure_expert import build_m5_price_structure_expert
from aidy.gold_m15_price_structure_expert import build_m15_price_structure_expert
from aidy.gold_price_expert_math import build_price_expert_math_packet

DATABENTO_DATASET = "GLBX.MDP3"
DATABENTO_SYMBOL = "GC.n.0"
DATABENTO_SCHEMA = "tbbo"
DATABENTO_BASE_URL = "https://hist.databento.com/v0"
EVIDENCE_VERSION = "aidy_build17_genuine_microstructure_holdout_v1"
TARGET_EPISODES = 64
TRAIN_EPISODES = 32
HOLDOUT_EPISODES = 32
PRE_WINDOW_MINUTES = 15
OUTCOME_MINUTES = 15
SPOT_LOOKBACK_HOURS = 16
ANCHOR_HOUR_UTC = 15
ANCHOR_MINUTE_UTC = 0
ELIGIBLE_WEEKDAYS = (1, 3)
MICRO_FLOW_Z_THRESHOLD = Decimal("0.75")
MICRO_VWAP_Z_THRESHOLD = Decimal("0.25")
MAX_SINGLE_REQUEST_USD = Decimal("5.00")
DEFAULT_MAX_TOTAL_USD = Decimal("150.00")
MIN_M1_LOOKBACK_ROWS = 700
SOURCE_RANGE_START = date(2025, 1, 1)
SOURCE_RANGE_END = date(2026, 1, 1)


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _digest(value: object) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _decimal(value: Any) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise RuntimeError(f"invalid decimal: {value!r}") from exc
    if not parsed.is_finite():
        raise RuntimeError(f"non-finite decimal: {value!r}")
    return parsed


def _utc(value: datetime | str) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _load_spot_rows() -> list[dict[str, Any]]:
    raw = os.environ.get("AIDY_GCP_SERVICE_ACCOUNT_JSON", "")
    if not raw.strip():
        raise RuntimeError("AIDY_GCP_SERVICE_ACCOUNT_JSON is required")
    info = json.loads(raw)
    creds = service_account.Credentials.from_service_account_info(info)
    project = str(info["project_id"])
    dataset = os.environ.get("AIDY_BIGQUERY_DATASET", "aidy_analytics_test").strip()
    location = os.environ.get("AIDY_BIGQUERY_LOCATION", "EU").strip()
    client = bigquery.Client(project=project, credentials=creds, location=location)
    table = f"{project}.{dataset}.research_candles"
    quote = chr(96)
    query = (
        "SELECT open_time_utc, open, high, low, close "
        f"FROM {quote}{table}{quote} "
        "WHERE source='histdata' AND timeframe='M1' "
        f"AND open_time_utc >= TIMESTAMP('{SOURCE_RANGE_START.isoformat()}T00:00:00Z') "
        f"AND open_time_utc < TIMESTAMP('{SOURCE_RANGE_END.isoformat()}T00:00:00Z') "
        "ORDER BY open_time_utc"
    )
    rows = []
    for row in client.query(query).result():
        rows.append(
            {
                "open_time_utc": _utc(row["open_time_utc"]),
                "open": _decimal(row["open"]),
                "high": _decimal(row["high"]),
                "low": _decimal(row["low"]),
                "close": _decimal(row["close"]),
            }
        )
    if not rows:
        raise RuntimeError("BigQuery returned no HistData XAUUSD M1 rows")
    return rows


def _aggregate(rows: list[dict[str, Any]], *, minutes: int, timeframe: str) -> list[dict[str, Any]]:
    groups: dict[datetime, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        stamp = row["open_time_utc"]
        bucket_minute = (stamp.minute // minutes) * minutes
        bucket = stamp.replace(minute=bucket_minute, second=0, microsecond=0)
        groups[bucket].append(row)
    output: list[dict[str, Any]] = []
    for bucket, values in sorted(groups.items()):
        ordered = sorted(values, key=lambda item: item["open_time_utc"])
        if len(ordered) != minutes:
            continue
        identity_body = {
            "timeframe": timeframe,
            "bucket": bucket.isoformat(),
            "inputs": [item["open_time_utc"].isoformat() for item in ordered],
        }
        identity = _digest(identity_body)
        output.append(
            {
                "symbol": "XAUUSD",
                "timeframe": timeframe,
                "open_time_utc": bucket,
                "open": str(ordered[0]["open"]),
                "high": str(max(item["high"] for item in ordered)),
                "low": str(min(item["low"] for item in ordered)),
                "close": str(ordered[-1]["close"]),
                "source": "histdata_build17_aggregate",
                "research_identity": f"build17:{identity}",
                "provenance_class": "retrospective_history",
                "pit_eligible": False,
                "source_file_sha256": None,
                "source_payload_sha256": identity,
                "derivation_version": "build17_spot_aggregate_v1",
            }
        )
    return output


def _direction(current: Decimal, previous: Decimal) -> str:
    if current > previous:
        return "up"
    if current < previous:
        return "down"
    return "flat"


def _return_bps(current: Decimal, previous: Decimal) -> Decimal:
    if previous == 0:
        return Decimal(0)
    return (current / previous - Decimal(1)) * Decimal(10000)


def _spot_environment(
    *,
    anchor: datetime,
    m5_rows: list[dict[str, Any]],
    m15_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    m5_closes = [_decimal(row["close"]) for row in m5_rows]
    m15_closes = [_decimal(row["close"]) for row in m15_rows]
    m5_dir = _direction(m5_closes[-1], m5_closes[-2]) if len(m5_closes) >= 2 else "flat"
    m15_dir = _direction(m15_closes[-1], m15_closes[-2]) if len(m15_closes) >= 2 else "flat"
    ret5 = _return_bps(m5_closes[-1], m5_closes[-2]) if len(m5_closes) >= 2 else Decimal(0)
    ret15 = _return_bps(m15_closes[-1], m15_closes[-2]) if len(m15_closes) >= 2 else Decimal(0)
    ret60 = _return_bps(m15_closes[-1], m15_closes[-5]) if len(m15_closes) >= 5 else Decimal(0)
    return build_cycle_environment(
        as_of_utc=anchor,
        target_window_start_utc=anchor + timedelta(minutes=15),
        session_code="london_new_york_overlap",
        observed_state="neutral",
        gold_state={
            "market_structure": {
                "timeframes": {
                    "M5": {"net_close_direction": m5_dir, "state": "known"},
                    "M15": {"net_close_direction": m15_dir, "state": "known"},
                    "H1": {"net_close_direction": "flat", "state": "unknown"},
                    "H4": {"net_close_direction": "flat", "state": "unknown"},
                    "D1": {"net_close_direction": "flat", "state": "unknown"},
                }
            },
            "move_observation": {
                "five_minute_distribution_state": "unknown",
                "five_minute_range_state": "unknown",
                "windows": {
                    "5m": {"direction": m5_dir, "return_bps": str(ret5)},
                    "15m": {"direction": m15_dir, "return_bps": str(ret15)},
                    "60m": {
                        "direction": "up" if ret60 > 0 else "down" if ret60 < 0 else "flat",
                        "return_bps": str(ret60),
                    },
                },
            },
            "volatility": {"state": "unknown"},
            "scheduled_event_risk": {"state": "unknown", "timing_state": "unknown"},
        },
        semantic_context={
            "data_quality": {
                "quote_state": "known",
                "quote_freshness": "historical_research",
                "spread_state": "unknown",
            },
            "cross_market": {"series": {}},
        },
        regime={"compound_regime_key": "build17_historical_holdout"},
    )


def _combine_spot_prediction(
    *,
    m5_conclusion: str,
    m15_conclusion: str,
    m15_rows: list[dict[str, Any]],
) -> str:
    directional = {"bullish", "bearish"}
    if m5_conclusion in directional and m15_conclusion == m5_conclusion:
        return m5_conclusion
    if m15_conclusion in directional:
        return m15_conclusion
    if m5_conclusion in directional:
        return m5_conclusion
    latest = _decimal(m15_rows[-1]["close"])
    prior = _decimal(m15_rows[-2]["close"])
    return "bullish" if latest >= prior else "bearish"


def _spot_candidate(
    all_rows: list[dict[str, Any]],
    *,
    anchor: datetime,
) -> dict[str, Any] | None:
    lookback_start = anchor - timedelta(hours=SPOT_LOOKBACK_HOURS)
    outcome_end = anchor + timedelta(minutes=OUTCOME_MINUTES)
    window = [row for row in all_rows if lookback_start <= row["open_time_utc"] < outcome_end]
    pre = [row for row in window if row["open_time_utc"] < anchor]
    outcome = [row for row in window if anchor <= row["open_time_utc"] < outcome_end]
    if len(pre) < MIN_M1_LOOKBACK_ROWS or len(outcome) < OUTCOME_MINUTES:
        return None
    m5 = _aggregate(pre, minutes=5, timeframe="M5")
    m15 = _aggregate(pre, minutes=15, timeframe="M15")
    if len(m5) < 50 or len(m15) < 50:
        return None
    packet = build_price_expert_math_packet(
        as_of=anchor,
        symbol="XAUUSD",
        candle_rows=m5 + m15,
        mode="retrospective",
    )
    environment = _spot_environment(anchor=anchor, m5_rows=m5, m15_rows=m15)
    m5_expert = build_m5_price_structure_expert(
        global_environment=environment,
        price_math_packet=packet,
    )
    m15_expert = build_m15_price_structure_expert(
        global_environment=environment,
        price_math_packet=packet,
    )
    m5_conclusion = str(m5_expert["expert_packet"]["conclusion"])
    m15_conclusion = str(m15_expert["expert_packet"]["conclusion"])
    spot_prediction = _combine_spot_prediction(
        m5_conclusion=m5_conclusion,
        m15_conclusion=m15_conclusion,
        m15_rows=m15,
    )
    outcome_start = pre[-1]["close"]
    outcome_close = outcome[-1]["close"]
    outcome_return = _return_bps(outcome_close, outcome_start)
    outcome_direction = "bullish" if outcome_return >= 0 else "bearish"
    return {
        "anchor_utc": anchor.isoformat(),
        "weekday_utc": anchor.weekday(),
        "spot_prediction": spot_prediction,
        "m5_conclusion": m5_conclusion,
        "m15_conclusion": m15_conclusion,
        "outcome_direction": outcome_direction,
        "outcome_return_15m_bps": str(outcome_return),
        "spot_ohlc_correct": int(spot_prediction == outcome_direction),
        "spot_price_math_digest": packet["packet_digest"],
    }


def _select_candidates(all_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    day = SOURCE_RANGE_START
    while day < SOURCE_RANGE_END:
        if day.weekday() in ELIGIBLE_WEEKDAYS:
            anchor = datetime.combine(
                day,
                time(ANCHOR_HOUR_UTC, ANCHOR_MINUTE_UTC),
                tzinfo=UTC,
            )
            candidate = _spot_candidate(all_rows, anchor=anchor)
            if candidate is not None:
                candidates.append(candidate)
        day += timedelta(days=1)
    if len(candidates) < TARGET_EPISODES:
        raise RuntimeError(
            f"Only {len(candidates)} eligible frozen spot episodes; need {TARGET_EPISODES}"
        )
    selected = candidates[-TARGET_EPISODES:]
    train = selected[:TRAIN_EPISODES]
    holdout = selected[TRAIN_EPISODES:]
    if len(holdout) != HOLDOUT_EPISODES:
        raise RuntimeError("Build17 holdout split size changed")
    train_counts: dict[int, int] = defaultdict(int)
    for row in train:
        train_counts[int(row["weekday_utc"])] += 1
    if any(train_counts[weekday] < 12 for weekday in ELIGIBLE_WEEKDAYS):
        raise RuntimeError(f"Insufficient weekday baseline episodes: {dict(train_counts)}")
    return selected


def _databento_client(api_key: str) -> httpx.Client:
    return httpx.Client(
        base_url=DATABENTO_BASE_URL,
        auth=httpx.BasicAuth(api_key, ""),
        timeout=httpx.Timeout(90.0),
        headers={"User-Agent": "AIDY-Signals/Build17"},
    )


def _request_params(anchor: datetime) -> dict[str, str]:
    start = anchor - timedelta(minutes=PRE_WINDOW_MINUTES)
    return {
        "dataset": DATABENTO_DATASET,
        "symbols": DATABENTO_SYMBOL,
        "schema": DATABENTO_SCHEMA,
        "stype_in": "continuous",
        "start": start.isoformat(),
        "end": anchor.isoformat(),
    }


def _quote(client: httpx.Client, params: dict[str, str]) -> Decimal:
    response = client.get("/metadata.get_cost", params=params)
    response.raise_for_status()
    return _decimal(response.json())


def _download(
    client: httpx.Client,
    *,
    params: dict[str, str],
    path: Path,
) -> dict[str, Any]:
    form = {
        **params,
        "encoding": "json",
        "compression": "none",
        "pretty_px": "true",
        "pretty_ts": "true",
        "map_symbols": "true",
    }
    hasher = sha256()
    byte_count = 0
    with client.stream("POST", "/timeseries.get_range", data=form) as response:
        response.raise_for_status()
        with path.open("wb") as handle:
            for chunk in response.iter_bytes():
                if not chunk:
                    continue
                handle.write(chunk)
                hasher.update(chunk)
                byte_count += len(chunk)
    return {"path": str(path), "byte_count": byte_count, "sha256": hasher.hexdigest()}


def _instrument_contract_map(raw_text: str) -> dict[int, str]:
    result: dict[int, str] = {}
    for raw_line in raw_text.splitlines():
        try:
            row = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict) or str(row.get("action") or "").upper() != "T":
            continue
        header = row.get("hd") if isinstance(row.get("hd"), dict) else {}
        instrument = row.get("instrument_id", header.get("instrument_id"))
        symbol = row.get("symbol") or row.get("raw_symbol") or row.get("stype_out_symbol")
        try:
            instrument_id = int(instrument)
        except (TypeError, ValueError):
            continue
        symbol_text = str(symbol or "").strip().upper()
        if symbol_text.startswith("GC") and symbol_text != "GC.N.0":
            result[instrument_id] = symbol_text
    return result


def _micro_cue(normalized_rows: list[dict[str, Any]]) -> dict[str, Any]:
    tail = normalized_rows[-5:]
    flow_values = [
        _decimal(row["signed_trade_imbalance_z"])
        for row in tail
        if row.get("signed_trade_imbalance_z") is not None
    ]
    vwap_values = [
        _decimal(row["vwap_distance_z"])
        for row in tail
        if row.get("vwap_distance_z") is not None
    ]
    if not flow_values or not vwap_values:
        return {
            "cue": None,
            "mean_flow_z": None,
            "mean_vwap_z": None,
            "thresholds_frozen_before_holdout": True,
        }
    mean_flow = sum(flow_values, Decimal(0)) / Decimal(len(flow_values))
    mean_vwap = sum(vwap_values, Decimal(0)) / Decimal(len(vwap_values))
    if mean_flow >= MICRO_FLOW_Z_THRESHOLD and mean_vwap >= MICRO_VWAP_Z_THRESHOLD:
        cue = "bullish"
    elif mean_flow <= -MICRO_FLOW_Z_THRESHOLD and mean_vwap <= -MICRO_VWAP_Z_THRESHOLD:
        cue = "bearish"
    else:
        cue = None
    return {
        "cue": cue,
        "mean_flow_z": str(mean_flow),
        "mean_vwap_z": str(mean_vwap),
        "flow_z_threshold": str(MICRO_FLOW_Z_THRESHOLD),
        "vwap_z_threshold": str(MICRO_VWAP_Z_THRESHOLD),
        "thresholds_frozen_before_holdout": True,
    }


def _split_binding(selected: list[dict[str, Any]]) -> dict[str, Any]:
    body = {
        "manifest_version": "aidy_chronological_split_manifest_v1",
        "binding_kind": "build17_genuine_gc_holdout_v1",
        "episode_digest": _digest([row["anchor_utc"] for row in selected]),
        "train_episode_count": TRAIN_EPISODES,
        "holdout_episode_count": HOLDOUT_EPISODES,
        "train": "chronological_first_32_normalization_only",
        "holdout": "chronological_final_32_frozen",
        "purge_required": True,
        "embargo_required": True,
        "holdout_tuning_allowed": False,
    }
    body["split_digest"] = _digest(body)
    return body


def main() -> int:
    output_dir = Path(os.environ.get("BUILD17_OUTPUT_DIR", "build17_genuine"))
    output_dir.mkdir(parents=True, exist_ok=True)
    max_total = _decimal(os.environ.get("BUILD17_MAX_SPEND_USD", str(DEFAULT_MAX_TOTAL_USD)))
    if max_total <= 0 or max_total > DEFAULT_MAX_TOTAL_USD:
        raise RuntimeError("Build17 max spend must be >0 and <= owner-approved $150 cap")

    all_spot = _load_spot_rows()
    selected = _select_candidates(all_spot)
    split = _split_binding(selected)

    api_key = normalize_databento_api_key(os.environ.get("DATABENTO_API_KEY", ""))
    if not api_key:
        raise RuntimeError("DATABENTO_API_KEY is required")

    quote_rows: list[dict[str, Any]] = []
    with _databento_client(api_key) as client:
        total_quote = Decimal(0)
        for episode in selected:
            anchor = _utc(episode["anchor_utc"])
            params = _request_params(anchor)
            cost = _quote(client, params)
            if cost > MAX_SINGLE_REQUEST_USD:
                raise RuntimeError(
                    f"Build17 request {anchor.isoformat()} quoted {cost}, above single-request cap"
                )
            total_quote += cost
            quote_rows.append(
                {
                    "anchor_utc": anchor.isoformat(),
                    "quoted_cost_usd": str(cost),
                    "request_digest": _digest(params),
                }
            )

        quote_evidence = {
            "owner_approved_hard_cap_usd": str(DEFAULT_MAX_TOTAL_USD),
            "run_cap_usd": str(max_total),
            "episode_count": len(selected),
            "total_quoted_cost_usd": str(total_quote),
            "single_request_cap_usd": str(MAX_SINGLE_REQUEST_USD),
            "all_requests_quoted_before_download": True,
            "quotes": quote_rows,
        }
        (output_dir / "cost_quote.json").write_text(
            _canonical_json(quote_evidence) + "\n",
            encoding="utf-8",
        )
        if total_quote > max_total:
            raise RuntimeError(
                f"Build17 total Databento quote {total_quote} exceeds hard cap {max_total}; no download started"
            )

        all_minutes_by_anchor: dict[str, list[Any]] = {}
        receipts: list[dict[str, Any]] = []
        actual_committed = Decimal(0)
        raw_dir = output_dir / "raw"
        raw_dir.mkdir(exist_ok=True)

        for index, episode in enumerate(selected):
            anchor = _utc(episode["anchor_utc"])
            params = _request_params(anchor)
            fresh_cost = _quote(client, params)
            original_cost = _decimal(quote_rows[index]["quoted_cost_usd"])
            if fresh_cost > original_cost:
                raise RuntimeError(
                    f"Databento quote increased for {anchor.isoformat()}; refusing download"
                )
            if actual_committed + fresh_cost > max_total:
                raise RuntimeError("Build17 cumulative fresh quote exceeds hard cap")
            path = raw_dir / f"episode_{index:03d}.jsonl"
            receipt = _download(client, params=params, path=path)
            actual_committed += fresh_cost
            raw_text = path.read_text(encoding="utf-8")
            contract_map = _instrument_contract_map(raw_text)
            if not contract_map:
                raise RuntimeError(f"No auditable raw GC symbol map for {anchor.isoformat()}")
            trades = parse_databento_tbbo_jsonl(
                raw_text,
                contract_by_instrument_id=contract_map,
            )
            minutes = aggregate_tbbo_minutes(trades)
            if len(minutes) < 5:
                raise RuntimeError(
                    f"Too few genuine GC microstructure minutes for {anchor.isoformat()}: {len(minutes)}"
                )
            all_minutes_by_anchor[episode["anchor_utc"]] = minutes
            receipts.append(
                {
                    "anchor_utc": anchor.isoformat(),
                    "fresh_quoted_cost_usd": str(fresh_cost),
                    "receipt": receipt,
                    "resolved_contracts": sorted({item.contract_symbol for item in minutes}),
                    "trade_rows": len(trades),
                    "microstructure_minutes": len(minutes),
                }
            )

    train_minutes = []
    for episode in selected[:TRAIN_EPISODES]:
        train_minutes.extend(all_minutes_by_anchor[episode["anchor_utc"]])
    baseline = build_weekday_clock_baseline(train_minutes)
    if not verify_weekday_clock_baseline(baseline):
        raise RuntimeError("Build17 genuine weekday/clock baseline failed verification")

    holdout_rows: list[dict[str, Any]] = []
    episode_evidence: list[dict[str, Any]] = []
    for episode in selected[TRAIN_EPISODES:]:
        minutes = all_minutes_by_anchor[episode["anchor_utc"]]
        normalized = [normalize_minute(item, baseline) for item in minutes]
        cue = _micro_cue(normalized)
        spot_prediction = str(episode["spot_prediction"])
        rich_prediction = str(cue["cue"] or spot_prediction)
        outcome = str(episode["outcome_direction"])
        row = {
            "independent_episode_id": episode["anchor_utc"],
            "split": "holdout",
            "spot_ohlc_correct": int(spot_prediction == outcome),
            "spot_plus_microstructure_correct": int(rich_prediction == outcome),
        }
        holdout_rows.append(row)
        episode_evidence.append(
            {
                **episode,
                "microstructure_cue": cue,
                "spot_plus_microstructure_prediction": rich_prediction,
                "spot_plus_microstructure_correct": row["spot_plus_microstructure_correct"],
                "microstructure_minute_count": len(minutes),
                "normalized_known_count": sum(item.get("state") == "known" for item in normalized),
                "contract_symbols": sorted(set(item.contract_symbol for item in minutes)),
            }
        )

    summary = summarise_incremental_holdout(holdout_rows, split_binding=split)
    evidence = {
        "evidence_version": EVIDENCE_VERSION,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "source_spot": "BigQuery research_candles source=histdata XAUUSD M1",
        "source_futures_provider": "Databento",
        "source_futures_dataset": DATABENTO_DATASET,
        "source_futures_schema": DATABENTO_SCHEMA,
        "continuous_symbol": DATABENTO_SYMBOL,
        "episode_selection_frozen_before_databento_download": True,
        "eligible_weekdays_utc": list(ELIGIBLE_WEEKDAYS),
        "anchor_time_utc": f"{ANCHOR_HOUR_UTC:02d}:{ANCHOR_MINUTE_UTC:02d}",
        "pre_window_minutes": PRE_WINDOW_MINUTES,
        "outcome_minutes": OUTCOME_MINUTES,
        "target_episode_count": TARGET_EPISODES,
        "train_episode_count": TRAIN_EPISODES,
        "holdout_episode_count": HOLDOUT_EPISODES,
        "spot_comparator": {
            "m5_expert": "aidy_gold_m5_price_structure_expert_v1",
            "m15_expert": "aidy_gold_m15_price_structure_expert_v1",
            "combination_policy": "agreement_then_M15_then_M5_then_latest_M15_return",
            "frozen_before_holdout": True,
        },
        "microstructure_augmentation": {
            "features": [
                "known-side signed aggressor imbalance z",
                "request-window anchored VWAP distance z",
            ],
            "tail_minutes": 5,
            "flow_z_threshold": str(MICRO_FLOW_Z_THRESHOLD),
            "vwap_z_threshold": str(MICRO_VWAP_Z_THRESHOLD),
            "cue_overrides_spot_when_available": True,
            "thresholds_frozen_before_holdout": True,
        },
        "weekday_clock_baseline_digest": baseline["baseline_digest"],
        "split_binding": split,
        "cost": {
            "hard_cap_usd": str(max_total),
            "all_requests_quoted_before_download": True,
            "total_initial_quote_usd": str(
                sum((_decimal(row["quoted_cost_usd"]) for row in quote_rows), Decimal(0))
            ),
            "total_fresh_committed_quote_usd": str(
                sum((_decimal(row["fresh_quoted_cost_usd"]) for row in receipts), Decimal(0))
            ),
            "paid_live_subscription_activated": False,
            "recurring_subscription_activated": False,
        },
        "holdout_summary": summary,
        "holdout_episodes": episode_evidence,
        "request_receipts": receipts,
        "depth_claimed": False,
        "order_book_imbalance_claimed": False,
        "unknown_aggressor_side_imputed": False,
        "retrospective_holdout_only": True,
        "statistically_validated": False,
        "formal_forward_evidence_created": False,
        "gate_promoted": False,
        "live_weight_granted": False,
        "paid_feed_activation_allowed_by_this_result": False,
        "owner_approval_required_for_phase_b": True,
    }
    evidence["evidence_digest"] = _digest(evidence)
    (output_dir / "genuine_holdout_evidence.json").write_text(
        _canonical_json(evidence) + "\n",
        encoding="utf-8",
    )

    for path in raw_dir.glob("*.jsonl"):
        path.unlink()

    print(
        _canonical_json(
            {
                "ok": True,
                "evidence_digest": evidence["evidence_digest"],
                "total_quote_usd": evidence["cost"]["total_initial_quote_usd"],
                "holdout_summary": summary,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
