# AIDY market-data ownership boundary

Decision date: 2026-08-17

## Locked decision

AIDY is an independent signal provider. It needs trustworthy XAUUSD quotes and
closed candles, but it does not need access to Vantage execution, follower
positions, broker orders or Super Signals account state.

The systems meet only later through Telegram:

`AIDY evidence -> OpenAI decision -> AIDY Telegram -> Super Signals -> Vantage DEMO`

## Enforced in code

- `MetaApiReadGateway` has quote/candle reads only; the positions endpoint is removed.
- New snapshots always write `position_state_json=NULL` to the retained legacy column.
- Snapshot R2 schema version 2 omits position state.
- Checked-in Worker capture is disabled.
- Checked-in scheduler Cron is disabled.
- Enabled capture fails closed unless
  `AIDY_MARKET_DATA_OWNERSHIP=aidy_dedicated`.

## Source-selection gate

Before live Day 3 continuity acceptance resumes, the owner must approve one of:

1. an independent non-broker XAUUSD market-data source; or
2. a separately owned AIDY-only MetaAPI/demo connection used only for quotes and
   candles.

No Super Signals secret may be copied or reused. No paid source is introduced
without owner approval.

## OpenAI clarification

ChatGPT is not an AIDY runtime component. The OpenAI API is a future Day 21
reasoning service only. It is not used for storage, market capture or broker
execution.
