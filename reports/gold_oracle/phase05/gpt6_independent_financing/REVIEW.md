# GPT-6 independent AIDY funding-uncertainty test — 29 October 2026

**Executed read-only analysis**, directly from original CI trade ledgers pinned to AIDY PR #374. This is an additive stress test, **NOT** a new strategy backtest, native broker simulation, qualified winner, or trading deployment. Existing research and original ZIPs remain unchanged.

## Independent input verification
- **S016 20/20 Donchian, $10,000 stress model:** unchanged native Backtrader [account evidence](https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/40742581770), committed `reports/gold_oracle/phase04/native_accounts/ci_evidence.zip` SHA256 `d71b5f6ae6cf1beef0acbdb461c843f31d0593cc31004ab0108dc9617eee2324`. 30 closed trades + **one still-open position**, all counted. At this stress cost, recorded cash commission was $1.44 per ounce round-trip for each closed trade. The open position size comes from native fill records. Input cash/trade returns and yearly totals independently reconcile.
- **S083 001B multi-timeframe zone rejection, $10,000 BID/ASK stress model:** unchanged [cost-aware/gap-stop evidence](https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/40821266442), committed `reports/gold_oracle/phase05/S083_costs/ci_evidence.zip` SHA256 `acab30523d3edc3c18718ed5d573dd97ff94b04fe81f94a43ba9a01ddb75b562`. 61 closed trades and no open position. True recorded ounce sizes independently reconcile to $1.44 per ounce existing incremental round-trip charge and total P&L.
- All source research spans the already-examined 2023–2025 UTC historical quote periods, **NOT sealed OOS**. Source SHA validation fails closed before any metric.

## Method
For every recorded entry-to-exit interval, accumulate physical **ounces × fractional elapsed UTC calendar days**. Split cross-year positions exactly at 00:00 Jan 1 UTC. For S016, include the still-open long from its last actual fill to the last source quote, because native marked equity includes it. Then subtract an *additional hypothetical* USD-per-ounce-per-elapsed-day holding cost from the **existing** stressed marked equity/P&L, without altering trade signals, sizes, closing fills, future risk sizing or original source.

This is an incremental, **linear retrospective sensitivity**, NOT an actual broker swap schedule or full cash engine rerun. No real broker financing rate is known; overnight rollovers (including possible triple days), CFD margin/stop-out, broker lots, swap exemptions, time-zones and intraday re-capitalisation are deliberately unverified. Crucially, S016's source account is **fully paid stocklike**, so a CFD funding debit is not asserted to apply to that original account. Do not advertise these scenarios as executable USD-account profits.

## Reconciled results

| Hypothetical EXTRA holding USD / ounce / elapsed UTC day | S016 marked 2023–25 USD | S083 marked 2023–25 USD |
| ---: | ---: | ---: |
| 0.00 | +2,493.88 | +298.10 |
| 0.10 | +2,317.43 | +280.75 |
| 0.25 | +2,052.76 | +254.72 |
| 0.50 | +1,611.64 | +211.33 |
| 1.00 | +729.39 | +124.56 |
| 1.50 | -152.85 | +37.80 |
| 2.00 | -1,035.09 | -48.97 |

- S016 accumulated **1,764.485417 ounce-days** (including final open holding). USD/ounce/day three-year marked break-even of the model is **1.413375**. Observed allocation: 2023=548.000000, 2024=773.660417, 2025=442.825000 ounce-days.
- S083 accumulated **173.535530 ounce-days**. Three-year marked break-even rate **1.717806**. Observed allocation: 2023=75.251364, 2024=54.522206, 2025=43.761961 ounce-days.
- S016's originally positive **2024 +$548.97 becomes −$224.69 at hypothetical extra $1.00/oz/day**, so the “profitable in all three years” screen is not robust to some *illustrative* funding schedules. With extra $0.50 its 2024 is still +$162.14. The 2024 sign turns below zero above about $0.710/oz/day under this scenario's fixed-position convention.
- S083's original stressed **2023 −$9.61** is already negative; any extra positive debit worsens that year. Its apparent total gain is modest, sensitive to unverified broker terms.
- No new family was admitted or packaged. Baseline 0.00 reproduces both original marked totals. Recomputing actual independent account behaviour under swap requires real broker and platform terms plus rerunning original sources, rather than this table.

## Reproduction / CI

Run against original committed unchanged ZIP archives:

```bash
PYTHONPATH=src:. python -m pytest -q tests/test_oracle_gold_phase05_independent_financing.py
PYTHONPATH=src:. python scripts/oracle_gold/phase05_independent_funding_sensitivity.py --output artifacts/oracle_gold/phase05_gpt6_independent/financing_sensitivity.json
```

The new test suite validates original artifact hashes, trade-count/P&L reconciliation, inferred ounce exposure, positive S016 open account holdings, 2023/2024 crossing, negative/reverse inputs, rate-0 baseline and zero broker/Hub actions. Automated CI is in `.github/workflows/oracle-gold-phase05-gpt6-independent-financing.yml` and publishes machine-readable scenario evidence. This lives on the existing PR #374 research branch; it does not create an unrelated project or overwrite earlier reports.

## Decision
**S016:** KEEP as conditional research candidate, still no independent validation, rights/broker contracts or funding qualification. **S083:** WATCH/EXECUTION-BLOCKED, already negative in 2023, unverified financing and lot/margin. Both remain unqualified for paper, penny and Oracle Hub; neither is a new independent bot.
