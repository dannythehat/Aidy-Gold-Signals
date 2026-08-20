# AIDY OpenAI reasoning gateway v1

## Purpose

Day 21 implements the first deployed-intelligence boundary for AIDY Signals. It sends an already-composed, non-secret evidence bundle to the OpenAI Responses API and accepts only a Day 20 `aidy_master_trader_decision_v1` decision that survives both strict Structured Outputs and AIDY's deterministic semantic validator.

This layer does not publish Telegram messages, execute trades, read broker/follower state, or alter Super Signals.

## Frozen versions

- Gateway: `aidy_openai_reasoning_gateway_v1`
- Prompt: `aidy_master_trader_prompt_v1`
- Model: `gpt-5.6-sol`
- Reasoning effort: `medium`
- Decision contract: `aidy_master_trader_decision_v1`
- JSON schema: `aidy_master_trader_json_schema_v1`
- Setup taxonomy: `aidy_gold_setup_taxonomy_v1`
- API: OpenAI Responses API `/v1/responses`
- Provider storage: `store=false`

Every version above is emitted in reproducibility metadata. Prompt text has a SHA-256 digest. The Day 20 contract manifest digest is also recorded.

## Two validation layers

1. OpenAI Structured Outputs receives the exact Day 20 strict JSON schema.
2. The returned JSON is passed again through `validate_master_trader_decision`.

Structured Outputs is not trusted as a substitute for AIDY's semantic validation. A schema-valid response can still fail the deterministic validator if, for example, trade geometry or action-specific field combinations are unsafe.

## Fail-closed behavior

The gateway returns `status=failed_closed` and `publication_allowed=false` for:

- unsafe input evidence;
- network/transport failure after bounded retry;
- retryable provider failure after bounded retry;
- non-retryable API error;
- invalid provider JSON;
- provider status other than `completed`;
- provider error object;
- model refusal;
- missing or ambiguous output text;
- malformed structured-output JSON;
- Day 20 semantic-validator rejection.

No error body is treated as trading evidence. No fallback prose parser exists.

## Retry and timeout policy

- timeout: 90 seconds;
- maximum attempts: 2;
- retryable transport failures: yes, bounded;
- retryable HTTP statuses: 408, 409, 429 and 5xx;
- all other 4xx responses fail immediately;
- fixed v1 retry backoff: 0.5 seconds.

The gateway does not keep retrying until it gets a tradeable answer.

## Secret boundary

The OpenAI key is read only from the runtime environment variable `OPENAI_API_KEY`.

It must never be:

- committed to Git;
- written into an evidence bundle;
- included in OpenAI prompts or metadata;
- printed by the live probe;
- written into CI logs;
- stored in Notion;
- included in decision-ledger records.

The gateway rejects common secret-bearing field names and secret-like values before an API request is constructed. Its `repr` redacts the key.

The Day 21 pull-request acceptance workflow intentionally performs no paid OpenAI call and requires no API secret. A real provider smoke test is performed only in an environment where `OPENAI_API_KEY` has been configured as a proper secret.

## Runtime separation

Prompt evidence recursively rejects fields that imply external execution/follower state, including broker, MT5, MetaAPI, Vantage, Telegram, Super Signals, follower state, account balance, and account equity.

AIDY Master Trader is a signal-provider intelligence layer. It is not allowed to observe or optimize for downstream follower-account state.

## Request contract

`build_openai_request` sends:

- the pinned model;
- the pinned Master Trader instructions;
- one canonical JSON evidence bundle;
- reasoning effort `medium`;
- Day 20 strict `json_schema` Structured Outputs;
- low output verbosity;
- `max_output_tokens=1800`;
- `store=false`;
- only non-secret AIDY version identifiers in provider metadata.

The API key exists only in the HTTP Authorization header.

## Accepted result metadata

An accepted result records:

- normalized Day 20 structured decision;
- decision digest;
- request digest that excludes the API key;
- response ID;
- provider status/model;
- attempts;
- latency in milliseconds;
- input tokens;
- cached input tokens;
- output tokens;
- reasoning tokens;
- total tokens;
- estimated request cost;
- pricing-version identifier;
- model ID;
- reasoning effort;
- prompt version and digest.

Raw provider response bodies and hidden reasoning traces are not persisted by this gateway.

## Cost accounting v1

Pinned price constants for the Day 21 acceptance version:

- input: $5.00 / 1M tokens;
- cached input: $0.50 / 1M tokens;
- output: $30.00 / 1M tokens.

Cost is an auditable estimate from provider token counters and a versioned pricing table, not a billing-system substitute.

## Publication boundary

`publication_allowed=true` means only that the OpenAI response survived the Day 21 gateway plus the Day 20 decision validator.

It does not publish anything. Later deterministic safety gates, context composition, ledgering and Telegram publication remain separate roadmap stages.

## Live probe

`scripts/day21_openai_live_probe.py` is deliberately synthetic and non-trading. It reads `OPENAI_API_KEY` from the environment and asks the gateway to assess an intentionally insufficient-evidence packet. It prints only safe acceptance/reproducibility metadata and the returned action/digest.

The probe must never be modified to inline a key in source code or workflow YAML.
