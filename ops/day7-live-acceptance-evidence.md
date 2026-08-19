# Day 7 deterministic Gold feature engine final acceptance

- Trigger commit: ccdb0aeb638cba7eb8d355d74faf0501d3a80bba
- Observed at UTC: 2026-08-19T14:38:16Z
- Dependencies: PASS
- Code gate: PASS
- Code gate status: ruff=0 compile=0 pytest=0
- Structural boundary: PASS
- Credential preflight: PASS
- BigQuery dependency: PASS
- Warehouse anchors: PASS
- Deterministic retrospective packet: PASS
- PIT packet / no retrospective leakage: PASS

## ruff
```text
All checks passed!
```

## compile
```text
```

## pytest
```text
........................................................................ [ 64%]
.......................................                                  [100%]
111 passed in 0.71s
```

## warehouse anchor
```json
{"dataset": "aidy_analytics_test", "gold_api_pit_candle_rows": 0, "pit_as_of": "2026-08-19T11:22:23.452999+00:00", "pit_snapshot_evidence_id": "ff131afc-45c9-4038-978a-69c3892fa611", "pit_snapshot_load_identity": "584cf33cabe983b15023548a977db9aa9a6a705e8a9347cbad8670b5647aa610", "pit_snapshot_session_code": "london", "project": "aidy-signals", "research_as_of": "2025-12-31T21:57:00+00:00", "research_pit_eligible_rows": 0, "research_rows": 914462}

```

## compact packet evidence
```json
{
  "pit": {
    "as_of_utc": "2026-08-19T11:22:23.452999+00:00",
    "feature_packet_digest": "24d8ceaca3377d2e76feeb6617a2c990cea0281f401ee79cd903a3008353e4a4",
    "pit_candle_source": "gold_api",
    "pit_eligible": true,
    "quote_context": {
      "ask": null,
      "bid": null,
      "capture_status": "complete",
      "computed_session_code": "london",
      "mid": "4370.5",
      "quote_age_seconds": 16.452999,
      "quote_state": "available",
      "quote_time": "2026-08-19T11:22:07+00:00",
      "recorded_session_code": "london",
      "session_code_consistent": true,
      "source_identity": "584cf33cabe983b15023548a977db9aa9a6a705e8a9347cbad8670b5647aa610",
      "spread": null,
      "state": "known"
    },
    "timeframe_states": {
      "D1": "unknown",
      "H1": "unknown",
      "H4": "unknown",
      "M1": "unknown",
      "M15": "unknown",
      "M5": "unknown"
    },
    "warehouse_input_rows": 0
  },
  "research": {
    "alignment": {
      "bearish_timeframes": 4,
      "bullish_timeframes": 2,
      "directions": {
        "D1": "bearish",
        "H1": "bearish",
        "H4": "bearish",
        "M1": "bullish",
        "M15": "bearish",
        "M5": "bullish"
      },
      "flat_timeframes": 0,
      "known_timeframes": 6,
      "state": "mixed"
    },
    "as_of_utc": "2025-12-31T21:57:00+00:00",
    "feature_packet_digest": "43a58c4266961c703fd2fe3062f6b76aae3450561076fd56ea18e20a245133a4",
    "pit_eligible": false,
    "session_code": "new_york",
    "session_range_bars": 298,
    "timeframes": {
      "D1": {
        "atr_14_bps": "177.725749",
        "bars_available": 625,
        "realized_vol_20_bps": "106.760267",
        "return_1_bps": "-32.818646",
        "return_5_bps": "-422.278779",
        "source_identity_count": 21
      },
      "H1": {
        "atr_14_bps": "48.342875",
        "bars_available": 2048,
        "realized_vol_20_bps": "43.741883",
        "return_1_bps": "12.367133",
        "return_5_bps": "-9.806557",
        "source_identity_count": 21
      },
      "H4": {
        "atr_14_bps": "85.827013",
        "bars_available": 2048,
        "realized_vol_20_bps": "74.833167",
        "return_1_bps": "12.367133",
        "return_5_bps": "-32.818646",
        "source_identity_count": 21
      },
      "M1": {
        "atr_14_bps": "3.196967",
        "bars_available": 2048,
        "realized_vol_20_bps": "1.670411",
        "return_1_bps": "0.694753",
        "return_5_bps": "9.628612",
        "source_identity_count": 21
      },
      "M15": {
        "atr_14_bps": "17.792556",
        "bars_available": 2048,
        "realized_vol_20_bps": "9.372746",
        "return_1_bps": "9.04861",
        "return_5_bps": "-5.360249",
        "source_identity_count": 21
      },
      "M5": {
        "atr_14_bps": "8.643455",
        "bars_available": 2048,
        "realized_vol_20_bps": "7.12386",
        "return_1_bps": "3.530348",
        "return_5_bps": "15.316198",
        "source_identity_count": 21
      }
    },
    "warehouse_input_rows": 10865
  }
}
```
