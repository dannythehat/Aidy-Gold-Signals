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

## Proven credential exclusion — 19 August 2026

The repository secret historically named `AIDY_METAAPI_TOKEN` is **not an AIDY
market-data credential**. A bounded read-only provenance check against MetaAPI's
account inventory showed that it exposes exactly one account:

- MetaAPI name: `Super Signals owner demo`
- server: `VantageMarkets-Demo`
- MT5 login ending: `1913`
- platform: MT5

This matches the known Super Signals owner demo and therefore cannot satisfy the
AIDY ownership gate. The token must never be used to enable AIDY capture, even
though its GitHub secret name contains `AIDY`.

Future Day 3 live acceptance requires newly provisioned secrets named
`AIDY_DEDICATED_METAAPI_TOKEN` and `AIDY_DEDICATED_METAAPI_ACCOUNT_ID`. The
acceptance workflow maps those dedicated values into the runtime names only for
the controlled Cloudflare deployment. The old ambiguous secret name is not
accepted by the live workflow.

Safe evidence is stored in `ops/day3-source-provenance.md`; no token or full
MetaAPI account identifier is persisted there.

## OpenAI clarification

ChatGPT is not an AIDY runtime component. The OpenAI API is a future Day 21
reasoning service only. It is not used for storage, market capture or broker
execution.
