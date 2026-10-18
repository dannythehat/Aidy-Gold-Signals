# S003 | Breakout Follow Trend 101 | Initial AIDY economic screen

**Screen: FAILED EDGE-QUALITY GATE. NO PAPER, NO LIVE, NO GREEN.**

Original public source:
- Pine v6 source SHA `6e2155c878f90fdd1cdcedcf7b00848828d1458d`
- MT5 source SHA `2d6e0eee1a2f49ff61bdc4d6edbba233b50a56dd`
- README SHA `6e673537a16731a597ba51cc2b6305ba5e25574e`

The author *actual code defaults* are **12:00 to 18:00 America/New_York, cooldown 6 bars**, EMA200, Bollinger15/1.5, ATR18 2x protective stop, 2R target, 1% compounding initial stop risk, native volume above volume-SMA15, 50% partial at 1.6R when minimum lot permits, one position and a 1% realised daily-loss entry lock. The README's high-win preset is **00:00 to 15:00 / cooldown 3**, and is **NOT** the default. Predeclared it as a SEPARATE scenario rather than silently changing source rules.

## Independently screened retrospective model ($10,000 starting capital per period)

| 2025 FULL | Trades | Wins | Net model USD | End model USD | Net PF | Max marked DD |
|---|---:|---:|---:|---:|---:|---:|
| Actual executable defaults | 118 | 45 | **+$211.99** | $10,211.99 | 1.0296 | -12.041% |
| Same defaults, doubled spread and slippage | 114 | 43 | **-$314.41** | $9,685.59 | 0.9553 | -11.306% |
| README preset, separate | 424 | 151 | **-$2,872.94** | $7,127.06 | 0.8749 | -36.669% |
| Same defaults without source volume gate control | 194 | 69 | **-$1,507.65** | $8,492.35 | 0.8650 | -26.456% |

| 2026 JAN-SEPT | Trades | Wins | Net model USD | End model USD | Net PF | Max marked DD |
|---|---:|---:|---:|---:|---:|---:|
| Actual executable defaults | 97 | 37 | **+$39.56** | $10,039.56 | 1.0075 | -6.898% |
| Same defaults, doubled spread and slippage | 97 | 36 | **-$494.25** | $9,505.75 | 0.9097 | -7.970% |
| README preset, separate | 338 | 128 | **+$923.02** | $10,923.02 | 1.0473 | -20.565% |
| Same defaults without source volume gate control | 156 | 52 | **-$1,621.98** | $8,378.02 | 0.8271 | -21.188% |

## What actually ran and what is still unqualified

- These results were independently replayed **LOCALLY** against 22 authentic historical HistData XAUUSD source archive derivative files (December 2024 for warmup, all 2025 and January–September 2026), with original receipt month, bar count and full derived M15 SHA256 verified for each month. Each period has its own hypothetical $10,000 model account.
- The local evidence includes every closed model ticket, monthly reconciliations, marked drawdown, matched no-volume control and explicit doubled-spread/slippage sensitivity. **The exact GitHub Actions S003 job was not yet run at the time this summary was committed.** It is not honest to call these GitHub CI-certified author native fills.
- Source historical M15 BID/ASK prices come from HistData, not Pepperstone, Vantage or TradingView. The authentic HistData source tick count is NOT native MT5 tick volume. Original 100% Pine/MQL5 parity has **not** been verified.
- Intrabar ASK extrema for short position stops/targets are approximated as historic BID extrema plus the corresponding authentic bar maximum observed spread. Broker ask-tick/stop execution chronology is **not** independently proven. With entry-bar event ordering unknowable from candles, the independent model starts evaluating stops/targets from the next candle. This is a stated approximation, not source-exact broker execution.
- Risk in the model compounds nominally from current account equity at 1% initial ATR stop, 0.01 lot steps and an additional disclosed 10x notional cap. Model adds $0.10/oz per-side slippage and $7/lot roundtrip commissions; no broker financing, margin liquidation or Friday gap fill records have been verified.
- The apparent default-model profit of $211.99 for a -12.041% drawdown in 2025 and $39.56 for -6.898% in 2026 is not economically persuasive. Profits disappear when costs are doubled. The very different README preset is not robust across both years.
- No approved independent alpha, no paper account promotion. **RED / FAILED INITIAL EDGE SCREEN / DO NOT ADD**. Avoid adaptive parameter mining and wasting work on an unpromising screen.

Source-validation GitHub PR: https://github.com/dannythehat/Aidy-Gold-Signals/pull/340

This file is an internal *local* research-screen summary, not a customer-facing research PDF or a native MT5/Pine parity test.
