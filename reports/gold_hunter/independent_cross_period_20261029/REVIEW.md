# GPT-6 independent Gold Hunter original-CI cross-period audit — 29 October 2026

**Completed:** Recovered and independently rechecked 2026 GitHub Actions outputs for PR #370 and PR #371 against complete-2025 original-BID runs. This is an original-evidence audit, NOT a new account backtest or untouched out-of-sample result. No order, deployment, 83-ID Oracle catalogue change, duplicate-verdict overwrite or production change.

## Original authenticated CI evidence, hash pinned

| Branch | Period | Original run | Source basis | CI |
|---|---|---|---|---|
| [PR #370](https://github.com/dannythehat/Aidy-Gold-Signals/pull/370) | 2025 full year | [40665596315](https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/40665596315) | 5,866 H1 BID rows, 12 source receipts; synthetic ASK | PASS |
| PR #370 | Jan–Sep 2026 | [40665596333](https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/40665596333) | 4,382 H1 rows, 10 receipts including Dec-2025 warmup; observed ASK at H1 open and pessimistic H1 maximum spread | PASS |
| [PR #371](https://github.com/dannythehat/Aidy-Gold-Signals/pull/371) | 2025 full year | [40671701827](https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/40671701827) | Same original 2025 BID snapshot | PASS |
| PR #371 | Jan–Sep 2026 | [40671702112](https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/40671702112) | Same original 2026 BID/ASK source receipts | PASS |

The new auditor pins all four original report SHA256s, four concatenated complete stress-model JSON/trade-ledger SHA256s, source CSV SHA256, source row/month counts, and trade-count/cash reconciliation. It fails closed on changed evidence. In BOTH years, all nine shared stress-case ledgers in PR370 and PR371 are exactly identical, including the frozen five. Six regression tests passed locally; read-only CI downloads the original artifacts and regenerates machine-readable evidence.

## Actual stressed-cost research model outcomes (USD, separate $10k starting accounts)

| Distinct hypothesis | 2025 full year stress | Jan–Sep 2026 stress | Tested-version disposition |
|---|---:|---:|---|
| **DONCHIAN_TREND** | **+$738.45**, 118 trades, PF 1.17 | **+$634.88**, 74 trades, PF 1.23 | **INVESTIGATE**: positive both observed periods |
| **PREV_DAY_BREAKOUT** | **+$564.68**, 109 trades, PF 1.14 | **+$1,406.27**, 65 trades, PF 1.63 | **INVESTIGATE**: positive both but correlated with Donchian |
| ASIA_RANGE_BREAK | −$230.96, 156 trades | +$1,669.89, 103 trades | INVESTIGATE/unstable: 2025 stress loses |
| ADX_DI_POWER | −$68.52, 50 trades | +$903.12, 32 trades | INVESTIGATE/unstable: 2025 stress loses |
| VOL_COMPRESSION_BREAK | +$422.77, 61 trades | −$138.20, 46 trades | INVESTIGATE/unstable: 2026 stress loses |
| EMA_PULLBACK | −$335.56, 101 trades | −$163.01, 76 trades | REJECT tested version |
| RSI_RECLAIM | +$37.66, 172 trades | −$518.14, 115 trades | REJECT tested version |
| EMA_RSI_CROSS | −$85.23, 43 trades | −$478.67, 33 trades | REJECT tested version |
| BOLLINGER_REENTRY | −$887.49, 116 trades | −$95.27, 93 trades | REJECT tested version |
| ASIA_LIQUIDITY_SWEEP | +$423.92, 149 trades | −$1,196.66, 105 trades | REJECT tested version |

All ten are independently implemented source-inspired research hypotheses, not publisher-native source-certified bots or forward-validated strategies. Rejecting a tested version does not prove all versions of its broad method fail.

## Composites are not additional independent bots

| Composite/model | 2025 base | 2025 stress | Jan–Sep 2026 base | Jan–Sep 2026 stress |
|---|---:|---:|---:|---:|
| Frozen **ALL_FIVE** | +$2,749.40 | +$2,107.88 | −$373.22 | **−$491.40** |
| **ALL_TEN** | +$3,126.04 | +$2,164.93 | −$129.17 | **−$239.09** |
| **DONCHIAN_ASIA_BREAK** (PR370) | +$848.15 | +$700.94 | +$1,314.39 | +$1,178.15 |
| **DONCHIAN_PLUS_SESSIONS** (PR370) | +$1,637.56 | +$1,107.62 | +$497.66 | +$359.41 |
| **SESSION_PAIR** | +$3,091.18 | +$1,653.10 | +$627.55 | +$481.96 |

**ALL_TEN 2026:** 168 stressed closes, PF 0.959, marked model drawdown −16.579%, worst realised month −$951.62, 6/9 positive months, zero months at +10% or higher, and −$421.13 after removing its largest winner. In 2025: 226 stressed closes, PF 1.263, DD −10.112%, worst month −$685.90, 8/12 positive months, zero months at +10% or higher.

**DONCHIAN_ASIA_BREAK** is a one-position-priority combination of Donchian and Asia-range signals, not a third independent profitable bot. It is positive in both examined periods, but standalone Asia-range loses 2025 stress. This is not a sum of separately funded accounts.

**MEAN_REVERSION is an exact alias of BOLLINGER_REENTRY** in both branches and years. Original source explicitly maps MEAN_REVERSION to the single BOLLINGER_REENTRY arm, and the complete stress models and trade ledgers are identical. Never count it as an 11th independent method. This is distinct from the Oracle 83-ID catalogue's 125 REVIEW flags, which are not 125 confirmed duplicates.

**Donchian versus previous-day breakout dependence:** 2025 same-hour/same-side overlap 31 of 118 Donchian vs 109 previous-day trades, monthly realised P&L correlation 0.7913 and four joint losing months. Jan–Sep 2026 overlap 20 of 74 vs 65, correlation 0.8085 and four joint losing months. Different mechanics do not prove uncorrelated edges.

## Limits and next engineering

2025 is complete 12-month BID-derived with synthetic ASK. Jan–Sep 2026 is nine months with genuine opening ASK and conservative hour-maximum spread, not event-aligned intrabar ASK. These quote/execution assumptions differ. Both are previously examined DEVELOPMENT periods, NOT sealed untouched holdout. Exact upstream source-code parity, native MT5 order chronology, actual broker minimum lots, swaps, financing, margin and stopout remain unverified. Models reset independently to $10k; do not sum them as executable master account returns. No consistent 10% net/month established.

Next: source-faithful 2023/24 tests with original BID/ASK receipts and frozen rules, then real broker-specific execution costs, lot/margin and funding. Prioritise Donchian and previous-day breakout as two CORRELATED conditional investigations. Test Donchian+Asia only as an alternative allocation, not a new family. Preserve all original 83 catalogue IDs and separate Oracle audit evidence.

**Zero historically qualified, packaged, paper, cent, funded or Oracle Hub approved bots from this audit. No merge, server changes, broker connection or orders.**
