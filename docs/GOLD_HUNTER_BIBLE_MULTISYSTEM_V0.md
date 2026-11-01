# Gold Hunter Bible Multisystem Bot (research only)

New, **isolated** original XAUUSD research candidate. It does not alter the canonical AIDY signal engine, published GoldThinker work or any broker account. It NEVER places orders.

## Bible is a hard admission constraint

Every candidate must pass all four gates, in order:
1. **Market**: confirmed H4 higher-high/higher-low or lower-high/lower-low trend with D1 alignment, or a clearly bounded H4 range with >=2 touches on each side. Choppy/unknown -> no entry. Weekly confirmed pivots are potential veto barriers (B 51-80).
2. **Level**: proven prior H4 swing support/resistance, 21SMA dynamic support or real range boundary, with explicit engineering proximity tolerance (B 58-69, 85-108, 113-130).
3. **Signal**: closed H1 pin, engulf, inside or inside false-break, directionally compatible with market+level (B 70, 81-157). Pattern names alone never qualify.
4. **Risk**: stop beyond pattern and target at actual known opposing H4 swing/range boundary; prospective net >=2R (B 92-95, 133-135, 141-145, 153-163). No acceptable target -> no trade.

This yields **seven eligible strategy families in one portfolio:** trend pin, engulf, inside, inside false-break; range pin, engulf, false-break. Each can be benchmarked independently. Shared portfolio allows one position at a time and chooses the highest pre-trade reward/risk among concurrent eligible candidates. A maximum 0.5% theoretical starting-equity risk per new entry is the research hypothesis, not the author's prescribed sizing. H1 cadence with H4/D1/W1 context, not M1/M5 noise.

## Test evidence and scientific limits

Code is new and thresholds (swing radius 2, proximity 0.42 H4 ATR, stop buffer 0.08 ATR, range width/touches, risk and expiry) are **AI interpretations**, not proof that the Bible prescribed them. Original scanned book visual validation and independent chart parity are required before claiming exact source reproduction. The repository's annotated page-by-page notes were used as initial source navigation.

Isolated deterministic unit tests are fixtures, NOT profitable historical backtests. The workflow intentionally invokes AIDY's existing read-only all-month 2025 BigQuery source runner first, then tests all families individually and as a shared account in two cost scenarios. Missing credentials or data is a hard FAIL and creates a blocker receipt.

Model limits: historical BID OHLC, fixed synthetic ASK/spread, slippage, commission; no historically executable broker quote parity, intrabar chronology, swap, margin/forced liquidation or minimum-lot constraints. Stops trigger first when OHLC contains stop and target in the same H1. No invented time-based exit: positions open at the end of source history are CENSORED and marked as unrealised, not falsely closed. **No real trading is approved.** The first 2025 year is development evidence only, not sealed OOS; it is insufficient to establish sustained profitability or trade frequency.

## Reproduce local fixture tests

```powershell
py -m pip install pandas numpy pytest
$env:PYTHONPATH = 'src'
py -m pytest -q tests/test_bible_engine.py
```

## Authentic archive research via existing AIDY CI secrets

Workflow: `.github/workflows/gold-hunter-bible-2025-research.yml`. Fetches original 2025 XAUUSD HistData M1->H1 in existing 12-month `s010_run_12month_history.py` provenance gate and invokes `scripts/gold_hunter_2025_research.py`. Emits separate trade ledgers, JSON, source hashes and summary under `artifacts/gold_hunter/bible_2025/`.

No result is financially qualified until verified across other regimes, genuine untouched OOS, authentic BID/ASK, financing, executable lots and referee admission.