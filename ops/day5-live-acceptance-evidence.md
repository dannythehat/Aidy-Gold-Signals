# Day 5 historical XAUUSD backfill live-acceptance evidence

- Trigger commit: f8a1b8f1d1d496f7fd944339dfb8267129d4bbcc
- Observed at UTC: 2026-08-19T13:41:17Z
- Dependencies: PASS
- Code gate: PASS
- Code gate status: ruff=0 compile=0 pytest=0
- Structural retrospective/live boundary: PASS
- Credential preflight: PASS
- BigQuery dependency: PASS
- Two-year 2024-2025 backfill: PASS
- Forced 2025 idempotency: PASS
- Checkpoint resume: PASS
- BigQuery provenance/live contamination proof: PASS

## ruff
```text
All checks passed!
```

## compile
```text
```

## pytest
```text
........................................................................ [ 93%]
.....                                                                    [100%]
77 passed in 0.60s
```

## day5-first
```json
{"dataset": "aidy_analytics_test", "derivation_version": "aidy_histdata_source_aligned_v1", "location": "EU", "ok": true, "periods": ["2024", "2025"], "project": "aidy-signals", "results": [{"backfill_identity": "c87c543d801954d841241c52e6969f6ee84837e085d1f8aa227fbfdda7cbffd4", "candle_load_job_ids": ["614fbdce-e939-4a0b-8f1e-fa423ab3cac5", "8538d258-5495-446c-910f-1b3a694079e6", "47e61500-8d57-43c7-b5b0-052ef28dd00f", "026a9cc5-26c6-4545-a0e9-baf298e82169", "de00540f-b76d-48a7-870c-5061ba8ad503", "08c3efeb-686e-4d31-808e-f2ee3d8844ce", "60a62b46-579f-47ff-9daa-3c8950c6b853", "d6c842f7-5afe-4ee1-809c-bfa33d0ab0c3", "2ab0e0dc-dc85-406c-b23c-79a083d901ec", "4edb240a-fc54-4857-a5be-a0c2b0bb23a8"], "candle_merge_job_id": "a9968acd-424c-426c-83e0-2ae4581aef26", "chunk_key": "7eabbd9393acde7f0152420cde3af651d2d0567e8339032cb3f18bcc088ce74b", "duplicate_rows": 60, "first_open_time_utc": "2024-01-01T05:00:00+00:00", "gap_count": 307, "last_open_time_utc": "2024-12-31T21:57:00+00:00", "m1_rows": 355592, "manifest_load_job_ids": ["60626055-88ba-457e-9185-81c71eaa0f08"], "manifest_merge_job_id": "17135a1a-6ba1-4cbe-a529-ac29efba8933", "manifest_rows": 1, "max_gap_seconds": 266520, "out_of_order_rows": 1, "period": "2024", "query_bytes_processed": 300611931, "reconciliation": {"D1": {"identities": 313, "pit_eligible_rows": 0, "provenance_classes": 1, "rows": 313}, "H1": {"identities": 5933, "pit_eligible_rows": 0, "provenance_classes": 1, "rows": 5933}, "H4": {"identities": 1601, "pit_eligible_rows": 0, "provenance_classes": 1, "rows": 1601}, "M1": {"identities": 355592, "pit_eligible_rows": 0, "provenance_classes": 1, "rows": 355592}, "M15": {"identities": 23713, "pit_eligible_rows": 0, "provenance_classes": 1, "rows": 23713}, "M5": {"identities": 71133, "pit_eligible_rows": 0, "provenance_classes": 1, "rows": 71133}}, "request_signature": "3d1725e2435999fa7e1509dc990ab326fe1f4daa59ba3fc7b7ef83f2a06dc28a", "run_id": "6e592dfe-f157-44a4-8915-6a67a8ff7567", "source_file": "DAT_ASCII_XAUUSD_M1_2024.zip", "source_file_sha256": "6d47f5cb269e0c4f35c63c7532713aae7dcf98901f605458b00dd6a69e7105de", "source_payload_sha256": "03dec44d8965c88eeba54e8ef5d13e31f28deca6f01fa727f9db55641bee5480", "status": "loaded", "timeframe_counts": {"D1": 313, "H1": 5933, "H4": 1601, "M1": 355592, "M15": 23713, "M5": 71133}}, {"backfill_identity": "69ec906ff00c0cbbdec50f7505e4c3c33b82050ff18ed1394a605f96f64fcfe6", "candle_load_job_ids": ["e02aa5aa-60c1-4256-8922-aed6ff7d2baf", "52dc9b5a-8989-4cfd-8ccf-034d39c831e1", "8eb5fe41-f33d-4167-98bb-94d2cee7b412", "0d463f68-8091-4e73-901a-9db5e0d73ac5", "8acd3caf-de0e-4b5d-b71a-d3dd652cd42b", "6acb0a29-2567-49aa-b66c-ada254105797", "99cf3b98-788a-4953-971c-2673881eca16", "5addc267-f158-4b7e-9b47-2bd031d737f4", "bfe015dd-4a2a-493a-bbb9-f3ffb10237e7", "870dfd5e-f1d9-4e31-9d8e-a76f6609bfc1"], "candle_merge_job_id": "8d01573a-2145-4600-8b00-1de25b41179c", "chunk_key": "75437dc744171de0216f614d088cc1ad07ce6cb063cfdff683df216b33ed59f4", "duplicate_rows": 60, "first_open_time_utc": "2025-01-01T05:00:00+00:00", "gap_count": 291, "last_open_time_utc": "2025-12-31T21:57:00+00:00", "m1_rows": 353951, "manifest_load_job_ids": ["df111d49-ac90-4538-bef7-8eb59e77fccb"], "manifest_merge_job_id": "c22f42cf-b8d1-4774-83a5-81ab60ec20fa", "manifest_rows": 1, "max_gap_seconds": 262920, "out_of_order_rows": 1, "period": "2025", "query_bytes_processed": 329476092, "reconciliation": {"D1": {"identities": 312, "pit_eligible_rows": 0, "provenance_classes": 1, "rows": 312}, "H1": {"identities": 5905, "pit_eligible_rows": 0, "provenance_classes": 1, "rows": 5905}, "H4": {"identities": 1593, "pit_eligible_rows": 0, "provenance_classes": 1, "rows": 1593}, "M1": {"identities": 353951, "pit_eligible_rows": 0, "provenance_classes": 1, "rows": 353951}, "M15": {"identities": 23606, "pit_eligible_rows": 0, "provenance_classes": 1, "rows": 23606}, "M5": {"identities": 70810, "pit_eligible_rows": 0, "provenance_classes": 1, "rows": 70810}}, "request_signature": "3d1725e2435999fa7e1509dc990ab326fe1f4daa59ba3fc7b7ef83f2a06dc28a", "run_id": "c8f6c8a5-3e7b-405e-86f1-fb6c4a3356a5", "source_file": "DAT_ASCII_XAUUSD_M1_2025.zip", "source_file_sha256": "dd0b4dc6983c07fafd89ba83b0c7f514aa16977654eaeb4c9fc8884ed359d98e", "source_payload_sha256": "1b302280d4f95f9c8ecdbb293e5659ca8a86eed314a7a061635f9f73fe96c2bc", "status": "loaded", "timeframe_counts": {"D1": 312, "H1": 5905, "H4": 1593, "M1": 353951, "M15": 23606, "M5": 70810}}], "source": "histdata", "symbol": "XAUUSD", "timeframes": ["M1", "M5", "M15", "H1", "H4", "D1"]}

```

## day5-forced-repeat
```json
{"dataset": "aidy_analytics_test", "derivation_version": "aidy_histdata_source_aligned_v1", "location": "EU", "ok": true, "periods": ["2025"], "project": "aidy-signals", "results": [{"backfill_identity": "69ec906ff00c0cbbdec50f7505e4c3c33b82050ff18ed1394a605f96f64fcfe6", "candle_load_job_ids": ["670d52f3-5a35-41a0-adde-9be9d0953ae4", "558d35fb-a262-4d6d-9e69-c60ccfd4f4d5", "561dc90e-c130-4c9b-9f4f-8e3002161f89", "9e7ceba9-718f-48c7-9fe7-7b1e1bdc61d3", "8bd1a3f3-9e58-43cd-82d2-35fda5b2b9f6", "87bf5471-3014-4418-a154-89eb56baaa1c", "d10298d6-4d90-4340-929b-606e7b6b3ac2", "84ad63b6-2f4f-42ac-b4fc-8bb31652b191", "f6050aa4-52e8-43c0-a797-4da08a3c6169", "550022d3-cc06-405c-8b73-14a195d089ae"], "candle_merge_job_id": "f633ae17-8106-47fc-938f-3783bfe6a9d3", "chunk_key": "75437dc744171de0216f614d088cc1ad07ce6cb063cfdff683df216b33ed59f4", "duplicate_rows": 60, "first_open_time_utc": "2025-01-01T05:00:00+00:00", "gap_count": 291, "last_open_time_utc": "2025-12-31T21:57:00+00:00", "m1_rows": 353951, "manifest_load_job_ids": ["5a6b8711-c734-4855-a746-cfe00ccbc7e4"], "manifest_merge_job_id": "87bde80d-c555-4673-adec-b97a9d431135", "manifest_rows": 1, "max_gap_seconds": 262920, "out_of_order_rows": 1, "period": "2025", "query_bytes_processed": 359583840, "reconciliation": {"D1": {"identities": 312, "pit_eligible_rows": 0, "provenance_classes": 1, "rows": 312}, "H1": {"identities": 5905, "pit_eligible_rows": 0, "provenance_classes": 1, "rows": 5905}, "H4": {"identities": 1593, "pit_eligible_rows": 0, "provenance_classes": 1, "rows": 1593}, "M1": {"identities": 353951, "pit_eligible_rows": 0, "provenance_classes": 1, "rows": 353951}, "M15": {"identities": 23606, "pit_eligible_rows": 0, "provenance_classes": 1, "rows": 23606}, "M5": {"identities": 70810, "pit_eligible_rows": 0, "provenance_classes": 1, "rows": 70810}}, "request_signature": "3d1725e2435999fa7e1509dc990ab326fe1f4daa59ba3fc7b7ef83f2a06dc28a", "run_id": "ddcdc33f-63c0-4435-bac0-93359b772355", "source_file": "DAT_ASCII_XAUUSD_M1_2025.zip", "source_file_sha256": "dd0b4dc6983c07fafd89ba83b0c7f514aa16977654eaeb4c9fc8884ed359d98e", "source_payload_sha256": "1b302280d4f95f9c8ecdbb293e5659ca8a86eed314a7a061635f9f73fe96c2bc", "status": "loaded", "timeframe_counts": {"D1": 312, "H1": 5905, "H4": 1593, "M1": 353951, "M15": 23606, "M5": 70810}}], "source": "histdata", "symbol": "XAUUSD", "timeframes": ["M1", "M5", "M15", "H1", "H4", "D1"]}

```

## day5-checkpoint-rerun
```json
{"dataset": "aidy_analytics_test", "derivation_version": "aidy_histdata_source_aligned_v1", "location": "EU", "ok": true, "periods": ["2024", "2025"], "project": "aidy-signals", "results": [{"chunk_key": "7eabbd9393acde7f0152420cde3af651d2d0567e8339032cb3f18bcc088ce74b", "period": "2024", "request_signature": "3d1725e2435999fa7e1509dc990ab326fe1f4daa59ba3fc7b7ef83f2a06dc28a", "status": "checkpoint_skipped"}, {"chunk_key": "75437dc744171de0216f614d088cc1ad07ce6cb063cfdff683df216b33ed59f4", "period": "2025", "request_signature": "3d1725e2435999fa7e1509dc990ab326fe1f4daa59ba3fc7b7ef83f2a06dc28a", "status": "checkpoint_skipped"}], "source": "histdata", "symbol": "XAUUSD", "timeframes": ["M1", "M5", "M15", "H1", "H4", "D1"]}

```

## day5-bigquery-proof
```json
{"manifest_periods": [{"out_of_order_rows": 1, "pit_eligible_rows": 0, "row_count": 1, "source_period": "2024"}, {"out_of_order_rows": 1, "pit_eligible_rows": 0, "row_count": 1, "source_period": "2025"}], "market_candles_histdata_rows": 0, "research_groups": [{"pit_eligible_rows": 0, "provenance_classes": 1, "row_count": 313, "source_file": "DAT_ASCII_XAUUSD_M1_2024.zip", "timeframe": "D1"}, {"pit_eligible_rows": 0, "provenance_classes": 1, "row_count": 5933, "source_file": "DAT_ASCII_XAUUSD_M1_2024.zip", "timeframe": "H1"}, {"pit_eligible_rows": 0, "provenance_classes": 1, "row_count": 1601, "source_file": "DAT_ASCII_XAUUSD_M1_2024.zip", "timeframe": "H4"}, {"pit_eligible_rows": 0, "provenance_classes": 1, "row_count": 355592, "source_file": "DAT_ASCII_XAUUSD_M1_2024.zip", "timeframe": "M1"}, {"pit_eligible_rows": 0, "provenance_classes": 1, "row_count": 23713, "source_file": "DAT_ASCII_XAUUSD_M1_2024.zip", "timeframe": "M15"}, {"pit_eligible_rows": 0, "provenance_classes": 1, "row_count": 71133, "source_file": "DAT_ASCII_XAUUSD_M1_2024.zip", "timeframe": "M5"}, {"pit_eligible_rows": 0, "provenance_classes": 1, "row_count": 312, "source_file": "DAT_ASCII_XAUUSD_M1_2025.zip", "timeframe": "D1"}, {"pit_eligible_rows": 0, "provenance_classes": 1, "row_count": 5905, "source_file": "DAT_ASCII_XAUUSD_M1_2025.zip", "timeframe": "H1"}, {"pit_eligible_rows": 0, "provenance_classes": 1, "row_count": 1593, "source_file": "DAT_ASCII_XAUUSD_M1_2025.zip", "timeframe": "H4"}, {"pit_eligible_rows": 0, "provenance_classes": 1, "row_count": 353951, "source_file": "DAT_ASCII_XAUUSD_M1_2025.zip", "timeframe": "M1"}, {"pit_eligible_rows": 0, "provenance_classes": 1, "row_count": 23606, "source_file": "DAT_ASCII_XAUUSD_M1_2025.zip", "timeframe": "M15"}, {"pit_eligible_rows": 0, "provenance_classes": 1, "row_count": 70810, "source_file": "DAT_ASCII_XAUUSD_M1_2025.zip", "timeframe": "M5"}]}

```

## day5-first-stderr
```text
```

## day5-forced-repeat-stderr
```text
```

## day5-checkpoint-rerun-stderr
```text
```
