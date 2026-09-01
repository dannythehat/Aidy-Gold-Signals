# Day 51 — Publication ledger, idempotency and delivery-state audit

Day 51 turns Day 50's publisher into durable operational infrastructure. Trading-decision truth and Telegram-delivery truth remain separate by design.

## Production storage

Cloudflare D1 owns the operational publication ledger via `migrations/d1/0003_publication_ledger.sql`.

For each publication AIDY persists:

- immutable `publication_id` and originating `decision_id`;
- exact outbound message text plus message/envelope digests;
- AI Signal group label and numeric Telegram chat ID;
- action/source identity;
- creation time and final delivery state;
- attempt count, lease state, Telegram message ID, sent time and transport metadata;
- append-only attempt records;
- append-only reconciliation events.

The existing Wrangler D1 binding already points at `migrations/d1`, so normal `wrangler d1 migrations apply AIDY_OPS ...` deployment applies Day 51's schema.

## Delivery state machine

`pending` → send attempt → one of:

- `sent` — terminal success; retries return the existing state and do not call Telegram again;
- `delivery_uncertain` — transport outcome may be ambiguous, so automatic resend is blocked;
- `permanent_failed` — configuration/identity failure, blocked until corrected;
- `retryable_failed` — explicitly confirmed safe for another attempt.

An active D1 lease prevents concurrent workers from blindly sending the same publication at the same time.

## Why uncertain delivery exists

Telegram Bot API `sendMessage` does not accept an application idempotency key. If the network disappears after Telegram accepts a message but before AIDY receives the response, blindly retrying can create a duplicate.

AIDY therefore fails closed. An ambiguous outcome becomes `delivery_uncertain`. A reconciliation event must establish either:

- `confirmed_sent` — record the observed Telegram message ID and suppress all future sends; or
- `confirmed_not_sent` — release the publication to `retryable_failed`, permitting a new attempt.

This is stricter than naïve retry logic and preserves the Day 51 acceptance requirement that duplicate retries do not duplicate provider messages.

## Decision/delivery separation

Delivery operations never mutate the Day 34 ex-ante decision record, Master Trader thesis, confidence, setup evidence, or outcome evaluation.

A decision can remain analytically valid even when Telegram delivery fails. Conversely, successful Telegram delivery does not make a trading judgement valid.

`no_trade` never reaches the Day 50 publication envelope and therefore produces zero external publication attempts.

## Runtime wiring

The production call path is intentionally small:

```python
store = D1PublicationLedgerStore(env.AIDY_OPS)
transport = TelegramBotTransport(bot_token=env.AIDY_TELEGRAM_BOT_TOKEN)
result = await deliver_with_ledger(
    envelope,
    store=store,
    transport=transport,
    now_utc=datetime.now(UTC),
)
```

`envelope` must already be a verified Day 50 publication envelope derived from an admitted immutable decision. Day 52 owns end-to-end orchestration from watcher through publisher/ledger.

## Security and system boundary

- Telegram token is supplied at runtime only and is never persisted in D1 rows, attempts or reconciliation events.
- Exact provider text is persisted so publication can be reconstructed and audited.
- No broker, MT5, MetaAPI, Vantage, follower-account or Super Signals dependency is introduced.
- Day 51 remains engineering/operational evidence. Formal Architecture V2 forward-performance evidence still begins only at Day 53.
