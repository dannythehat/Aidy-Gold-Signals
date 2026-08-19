# Day 6 PIT as-of reconstruction live-acceptance evidence

- Trigger commit: c202b53f5b9f4bf8f73fa762772785d45817f151
- Observed at UTC: 2026-08-19T14:04:24Z
- Dependencies: PASS
- Code gate: PASS
- Code gate status: ruff=0 compile=0 pytest=0
- Structural PIT boundary: PASS
- Credential preflight: PASS
- BigQuery dependency: PASS
- Warehouse anchor/control rows: PASS
- Before first snapshot -> explicit unknown: PASS
- At first snapshot -> known with provenance: PASS
- Retrospective history excluded: NOT_REACHED_OR_FAILED

## ruff
```text
All checks passed!
```

## compile
```text
```

## pytest
```text
........................................................................ [ 76%]
......................                                                   [100%]
94 passed in 0.50s
```

## day6-warehouse-anchor
```json
{"dataset": "aidy_analytics_test", "first_captured_at": "2026-08-19T11:22:23.452999+00:00", "project": "aidy-signals", "research_pit_eligible_rows": 0, "research_rows": 914462, "snapshot_rows": 1}

```

## day6-before
```json
{"as_of_utc": "2026-08-19T11:22:23.452998+00:00", "availability": {"data": null, "state": "unknown"}, "candles": [], "events": [], "query_ids": {"candles": "859ddaa72f1c3acd268c88561c0c33f0a8ea3ec00d34213b54d9a64fef91d4bd", "events": "27a8ffcfaa3240728a1878d0b56556b2640e302f82afa81ca4bae17b81ce4197", "snapshot": "b38ac268e30f39780c6e3932f174fbd7a46813d3417055da2b3781c41cd23768"}, "query_version": "aidy_pit_asof_v1", "retrospective_history_included": false, "snapshot": {"fact": null, "provenance": null, "state": "unknown"}, "symbol": "XAUUSD", "warehouse": {"dataset": "aidy_analytics_test", "project": "aidy-signals"}}

```

## day6-at
```json
{"as_of_utc": "2026-08-19T11:22:23.452999+00:00", "availability": {"data": {"candles": "separate_research_feed", "cross_market": "not_configured_phase0", "external_event_observation_count": 0, "external_events": "point_in_time_linked", "market_data_source": "gold_api", "market_state": "open", "orders": "not_captured_phase0", "price_type": "indicative_mid", "quote": "available"}, "snapshot_evidence_id": "ff131afc-45c9-4038-978a-69c3892fa611", "state": "known"}, "candles": [], "events": [], "query_ids": {"candles": "859ddaa72f1c3acd268c88561c0c33f0a8ea3ec00d34213b54d9a64fef91d4bd", "events": "27a8ffcfaa3240728a1878d0b56556b2640e302f82afa81ca4bae17b81ce4197", "snapshot": "b38ac268e30f39780c6e3932f174fbd7a46813d3417055da2b3781c41cd23768"}, "query_version": "aidy_pit_asof_v1", "retrospective_history_included": false, "snapshot": {"fact": {"archive_key": "gold/snapshots/2026/08/19/20260819T112223.452999Z-ff131afc-45c9-4038-978a-69c3892fa611-c66e97aba2974c9bf9fe1ca44ee17ef699498a9aa5656cf1f4c75e0c9358d4f5.json", "ask": null, "bid": null, "capture_status": "complete", "captured_at": "2026-08-19T11:22:23.452999+00:00", "data_availability": {"candles": "separate_research_feed", "cross_market": "not_configured_phase0", "external_event_observation_count": 0, "external_events": "point_in_time_linked", "market_data_source": "gold_api", "market_state": "open", "orders": "not_captured_phase0", "price_type": "indicative_mid", "quote": "available"}, "event_observation_ids": [], "evidence_id": "ff131afc-45c9-4038-978a-69c3892fa611", "latest_d1_id": null, "latest_h1_id": null, "latest_h4_id": null, "latest_m15_id": null, "latest_m1_id": null, "latest_m5_id": null, "load_identity": "584cf33cabe983b15023548a977db9aa9a6a705e8a9347cbad8670b5647aa610", "market_data_source": "gold_api", "mid": "4370.5", "payload_digest": "c66e97aba2974c9bf9fe1ca44ee17ef699498a9aa5656cf1f4c75e0c9358d4f5", "quote_age_seconds": 16.452999, "quote_time": "2026-08-19T11:22:07+00:00", "record_type": "snapshot", "schema_version": 2, "session_code": "london", "spread": null, "symbol": "XAUUSD"}, "provenance": {"archive_key": "gold/snapshots/2026/08/19/20260819T112223.452999Z-ff131afc-45c9-4038-978a-69c3892fa611-c66e97aba2974c9bf9fe1ca44ee17ef699498a9aa5656cf1f4c75e0c9358d4f5.json", "evidence_id": "ff131afc-45c9-4038-978a-69c3892fa611", "load_identity": "584cf33cabe983b15023548a977db9aa9a6a705e8a9347cbad8670b5647aa610", "payload_digest": "c66e97aba2974c9bf9fe1ca44ee17ef699498a9aa5656cf1f4c75e0c9358d4f5", "record_type": "snapshot", "schema_version": 2}, "state": "known"}, "symbol": "XAUUSD", "warehouse": {"dataset": "aidy_analytics_test", "project": "aidy-signals"}}

```
