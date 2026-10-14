# Day 06B corrective storage inventory

Status: PARTIAL. Executed 14 October 2026.

[Real BigQuery metadata audit](https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/38521058882) succeeded.

| BigQuery table | Stored rows from live table metadata |
|---|---:|
| research_candles | 914462 (all timeframes combined) |
| research_bidask_minute_quotes | 58961 |
| research_bidask_manifest | 2 |
| market_candles | 0 |
| _stage_market_candles | 0 |
| _stage_day27_bidask_minute_quotes | 0 |
| market_snapshots | 1 |

The 709543 native M1 records (2024-25) were separately confirmed by an actual data query. Research bid/ask data currently confirmed in this dataset consists of December 2024 and January 2025, deliberately loaded for Day27 experiment. The two-month figure is NOT proof that other tick files do not exist in Cloudflare storage, local computers, Vantage or other accounts.

Outstanding: complete paginated R2 object listing, D1 operational data inventory, Windows/OVH local archives, broker historical downloads and licensing. Past verification retrieved ONE R2 archived snapshot, not a comprehensive R2 inventory. These locations remain UNKNOWN until independently queried. Do not mark all-storage discovery complete.
