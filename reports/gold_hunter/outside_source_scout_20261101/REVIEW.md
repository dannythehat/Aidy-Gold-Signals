# Outside-source scout, 1 November 2026 — not additional AIDY backtests

**Two primary executable public source leads inspected; neither is a new independent qualified Gold bot.** This source audit is separate from today's completed original NY ORB frozen improvement CI [#41187464561](https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/41187464561). The original 83 are only a duplication comparator, not today's scouting list.

## Scout A — andywarui/XAUUSD failed breakout trap

- Original source: [`andywarui/xau_bot/core/signal_generator.py`](https://github.com/andywarui/xau_bot/blob/main/core/signal_generator.py), **Git blob SHA `4eecdb775313993179e8f6c4e0b98ece6dce0c22`**; entrypoint [`main.py`](https://github.com/andywarui/xau_bot/blob/main/main.py) **blob SHA `6d61f24c660196ddd8ef5f45419a01f8caee9c7c`**.
- Mechanic: previous completed D1 high/low, H1 close beyond previous level by **$3**, next **two H1 closes** must reclaim level with opposite-colour candle; short after bull trap, long after bear trap; stop beyond breakout wick +$3, target opposite previous-day extreme. This is **failed breakout mean reversion**, NOT a long momentum breakout, but likely economically related to earlier liquidity-sweep/reclaim families. Source-signal overlap and P&L correlation must be established before counting a new independent bot.
- Source code reads last **closed** H1 candle (`iloc[-2]`) and previous D1 candle (`iloc[-2]`); `main.py` gates `process_candle` on a newly detected candle. A native MT5 platform/quote/parity test is still missing; do not claim any causal or execution certification based on inspection alone. Exact daily rollover and DST depend on broker.
- **No root `LICENSE` file found via GitHub contents API (404)**. Commercial redistribution/derivative rights unverified. **No AIDY trade ledger or P&L**. Status: **SCOUTED / LICENCE + FAMILY DEDUP BLOCKED**, not a qualified independent system.

## Scout B — Steinwealth/EasyTrendline M30

- Original [Pine v6 source](https://github.com/Steinwealth/EasyTrendline/blob/main/easy_trendline_xauusd_30m.pine), **Git blob SHA `6d55fda362ebe7da9c426aac614946be688f427b`**.
- Mechanic: pivot-derived dynamic trendline breakout, EMA50/200 directional gate, RSI-SMA threshold, ATR buffer and trailing exits; **long-only**, 95% equity sizing, pyramiding 4 and zero-tick slippage in original default. Author advertises **86.27% wins / +29.06% in Jan–Oct2025**. These are **UNVERIFIED AUTHOR CLAIMS**, not AIDY results. Source is structurally close to the already studied breakout + trend-filter family; cannot count as independent without actual signal overlap and source-faithful backtest.
- Source header calls it free to modify, but **no root `LICENSE` file found (GitHub API 404)**; rights and any redistribution permission need explicit legal verification. No original 2023/24/2026 spot BIDASK AIDY run. Status: **SCOUTED / POSSIBLE MECHANIC DUPLICATE + LICENCE BLOCKED**, not a winner.

## Source toolkit (NOT a third trading strategy)

[`vigilancetrent/quantflow`](https://github.com/vigilancetrent/quantflow) is an MIT-licensed general finance research library; its `LICENSE` **Git blob SHA `f2a988fd1a24574cf1ef3d5865d00f00fc595c9d`**. It advertises realised semivariance, Kyle lambda, VPIN and walk-forward CV. **It is not an executable XAUUSD system** and should never enter the candidate/winner count. VPIN/Kyle require real venue trades/volume or order flow; AIDY's spot BID/ASK M1 alone does not establish these. A semivariance exit can be proposed as a distinct *future* falsifiable experiment, but not retroactively claimed as an original proven trading rule.

**Decision:** No new P&L, no backtest launched for these unlicensed/possibly duplicate sources. Continue prioritising a genuinely independent **commercially usable, fully source-specified** gold mechanism with authenticated quote inputs. No live/demo/cent actions, no source copied into a packaged bot.
