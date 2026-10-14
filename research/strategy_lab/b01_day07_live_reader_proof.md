# B01 Day 07 — Real historical data-read interface: acceptance

Status: **DAY 07 READER CHECKS PASSED** on 14 October 2026. Research branch only; no production merge and no historical table writes.

## Built
- `src/aidy/strategy_lab_history_reader.py`: parameterised bounded read-only BigQuery M1 SELECT; validates source archive SHA-256 identity, original source timestamp, source file, source dataset, retrospective provenance and bid-only basis before emitting any bars.
- Source-local alignment uses **HistData fixed EST (UTC−05:00, without US DST)**, not `America/New_York`, UTC modulo H4, broker/server clocks, or Vantage clock.
- Derives M5/M15/H1/H4 (and supports strictly complete D1 windows) from **complete closed native M1** only; both interval boundaries must align; incomplete leading/trailing periods and any unknown minute gap fail closed.
- For every bar, `available_at_utc` is the actual end timestamp; future/open candles and premature higher-timeframe reads reject.
- The `input_digest` includes exact source records, archive and payload hashes, price fields and requested UTC window. `Window.expected_digest` explicitly rejects changed underlying data on replay. **This is a content-frozen read contract, not proof BigQuery tables are physically immutable.**
- No interpolation, synthetic ask pricing, holiday-calendar guesses or Vantage session assumptions.

## Actual GitHub CI and historical warehouse proof
- [Day 07 successful acceptance workflow](https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/38524910498), job `115722880290`; Ruff and source compilation passed, **32 focused tests passed**.
- Live real BigQuery source: `aidy-signals.aidy_analytics_test.research_candles` on **6 January 2025, 13:00–17:00 UTC**.
- Reproducible native M1 input size: **240 rows**; M1=240, M5=48, M15=16, H1=4, H4=1. All five views agree on input digest `1bb0e65faded9bc0df4d641ec1e00dff712aa912fc1b577283bc5682ed33f6b7`.
- Source archive SHA: `dd0b4dc6983c07fafd89ba83b0c7f514aa16977654eaeb4c9fc8884ed359d98e`.
- BigQuery replay with `expected_digest` passed; verification job `14f3d6e2-4454-4ff5-a438-fdb245b10a87`.
- First actual query job `6b4d716a-a5da-4845-a050-00ac15a1a84c`. Authoritative complete JSON: workflow artifact `b01-day07-real-reader-evidence`.

## Honest limitations / follow-up
1. Actual sample windows M1/M5/M15/H1/H4 were verified. **D1 source midnight alignment was unit tested, but no real D1 trading-day sample was certified**, since daily periods can have maintenance gaps. D1 remains blocked unless an authoritative session-aware day definition and missing-minute policy is qualified.
2. Historical session/holiday calendar remains unqualified. This reader rejects a missing M1 minute **even when that minute is a legitimate market closure**. This is intentional safety, not a two-year universal replay engine yet.
3. The underlying BigQuery table is **not claimed immutable**. A pinned `expected_digest` guarantees fail-closed reads when data differs; permanent content-addressed source archives / partition manifests and retention controls remain separate work.
4. Bid-only OHLC, not historical Vantage executable fills. Broker clock, ask/spread acquisition and commercial data licences still outstanding.
5. Live data and broker positions remain untouched. The historical tick-source acquisition is a separate workflow and its current completion must be checked independently.

Day 07 reader acceptance is therefore **PASSED for the numbered code/test/live-sample deliverables**, not a sign-off on B01, D1 sessions, execution model or owner stage acceptance.
