# Day 50 — Private AIDY Telegram publisher

Day 50 creates the first outbound AIDY provider surface. The configured private Telegram group label is **AI Signal**.

## Publication boundary

The publisher is not a trading-decision layer. It accepts only a verified immutable Day 34 ex-ante ledger record whose cycle disposition is `decision_admitted`, whose OpenAI gateway snapshot is accepted with `publication_allowed=true`, and whose post-model safety receipt passed with `decision_admitted=true`.

Only these Master Trader actions are eligible:

- `new_trade`
- `manage_trade`
- `close_trade`

`no_trade`, pre-model blocked, model failed, post-model blocked, replay, shadow, historical and failed source states are non-publishing states.

## Provider formatting

Messages are deterministic and intentionally compact:

- new trade: symbol, BUY/SELL, market reference, SL, TP1–TP3 and immutable trade decision ID;
- manage trade: target trade decision ID, stop/target changes and immutable update decision ID;
- close trade: full-close instruction, target trade decision ID and immutable close decision ID.

Confidence, hidden reasoning, thesis text, analogue details and internal evaluation metadata are not included in provider messages.

## Identity and idempotency

A deterministic `publication_id` binds publisher version, immutable decision ID, ex-ante digest, destination chat ID and message digest. A verified existing receipt for the same publication is returned without another Telegram send. A receipt for a different publication or message fails closed.

Day 50 keeps only a minimal transport receipt. Day 51 owns the full publication/delivery ledger and retry-attempt history.

## Telegram transport

Acceptance uses `SimulatedTelegramTransport` only. The real Bot API transport exists but requires an explicit bot token and numeric Telegram chat ID at runtime. The token is never stored in publication envelopes, receipts or messages, and transport failures suppress provider URL/body details so the token cannot leak through exceptions.

No real Telegram post is part of Day 50 CI acceptance.

## System separation

The publisher has no broker, MT5, MetaAPI, Vantage, follower-account or Super Signals dependency. Telegram is the only outbound provider surface. Super Signals remains a future downstream consumer and is not modified by Day 50.

Day 50 creates engineering evidence only. It does not start Architecture V2 formal forward-performance evidence; that begins at Day 53 under its frozen cohort rules.
