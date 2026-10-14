# Day 06 — Genuine XAUUSD bid/ask archive coverage: REAL BigQuery audit

Date: 2026-10-14. Scope: current BigQuery research_bidask_manifest and research_bidask_minute_quotes, read-only.

## Verified outcome

**PASS for coverage inventory and bid/ask basic geometry**, not proof of two years' tick/quote coverage or Vantage fills.

| Period | Manifest tick rows | Last genuine tick per minute stored | Invalid bid/ask geometry | Timestamp duplicate |
|---|---:|---:|---:|---:|
| December 2024 | 5,090,073 | 28,764 | 0 | 0 |
| January 2025 | 5,798,226 | 30,197 | 0 | 0 |
| Total | 10,888,299 | 58,961 | 0 | 0 |

- Live BigQuery run: https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/38520532374
- Query job IDs: manifest `5696f675-4e5c-4418-946a-2630123a2261`; quotes `cfcf35e9-c55f-4d64-8609-0c6bf37d2ade`.
- Source accepted as HistData Generic ASCII tick bid/ask, fixed EST UTC-5; original full raw tick archives were previously loaded under documented Day 27 pipeline. Per-minute analytical rows represent **only the final real tick of each UTC minute**.
- Historical full 2024/2025 M1 candles are BID OHLC. Do not assume ASK OHLC or genuine fills outside the verified Dec 2024 / Jan 2025 windows.
- No invalid bid/ask spread geometry found in the stored minute-level quotes. Individual raw tick geometry beyond archived acceptance was not re-audited by this query.
- Source-use rights documented for internal research; **commercial redistribution and service terms NOT verified**.
- HistData quote spread does not equal Vantage broker's executable spread, slippage or commissions.

## Required next actions
1. B01 session and source clock qualification (Day 07): actual source calendar and valid candle availability.
2. B03 cost model: explicitly tag quote provenance and a broker-fee assumption. Never present a modeled spread outside these windows as observed.
3. Later source acquisition: broaden 2024/25 actual bid/ask tick coverage subject to licence and budget, or clearly constrain verified executable-cost runs to true quote-covered windows.
4. GoldThinker/Vantage clock and specific symbol contract must be separately qualified before broker-specific strategy claims.
