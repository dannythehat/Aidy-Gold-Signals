# AIDY objective market-context packet v1 contract

Decision date: 2026-08-20
Day 10 implementation: 2026-08-20

## Purpose

Day 10 creates one canonical, versioned, point-in-time factual contract for all later AIDY intelligence. It composes already accepted evidence and deterministic features rather than re-deriving them.

The packet is an observation contract, not a trading opinion. It contains no direction recommendation, setup claim, confidence, causal explanation or future outcome.

## Version

- Context packet: `aidy_market_context_v1`
- Context hash: SHA-256 over canonical JSON
- Day 6 PIT query: `aidy_pit_asof_v1`
- Day 7 Gold features: `aidy_gold_features_v1`
- Day 8 macro window: `aidy_macro_event_window_v1`
- Day 9 cross-market query: `aidy_cross_market_asof_v1`

## Required input boundary

A Day 10 packet accepts only:

1. a valid PIT Day 7 Gold feature packet for the same symbol and as-of timestamp;
2. official macro/Fed event rows filtered point-in-time through the existing Day 6 revision semantics;
3. Day 9 cross-market observations from the enabled Federal Reserve/Treasury series;
4. optional AIDY-owned theoretical signal-lifecycle state.

Retrospective research feature packets are rejected. The packet never reads or accepts follower MT5 positions, broker orders, balances, equity, margin, account state, MetaAPI/Vantage state or Super Signals state.

## Packet sections

The canonical packet contains:

- identity/version fields and the evaluation timestamp;
- the complete validated Gold feature packet, including multi-timeframe structure, range/session context, quote state and Day 7 provenance;
- deterministic session context;
- high-impact macro/Fed timing context;
- enabled cross-market facts;
- AIDY's own theoretical signal-lifecycle context when available;
- explicit data-quality and missing-evidence flags;
- reconstruction provenance;
- deterministic context hash.

The packet explicitly declares `retrospective_history_included=false` and `broker_follower_state_included=false`.

## Deterministic hash rule

The context hash is calculated as follows:

1. normalize datetimes to UTC ISO-8601 text and decimal lifecycle prices to canonical decimal strings;
2. sort unordered evidence into deterministic logical order;
3. serialize JSON with sorted object keys and compact separators;
4. exclude only the top-level `context_hash` field itself;
5. SHA-256 the resulting UTF-8 bytes.

The same factual evidence must therefore produce the same complete packet and hash regardless of input list ordering. Any material change in packet evidence or state must change the hash.

## Gold integrity rule

The supplied Day 7 feature packet is not trusted only because it has the right shape. Day 10 verifies:

- feature definition version;
- PIT mode and `pit_observed` provenance;
- `pit_eligible=true`;
- exact symbol/as-of match;
- the Day 7 `feature_packet_digest` against the packet contents.

A tampered or retrospective feature packet is rejected.

## Missing evidence semantics

Unknown must remain different from known-empty.

Examples:

- no usable Gold candles means each affected timeframe remains `state=unknown`;
- unavailable quote age means quote freshness is `unknown`, not fresh;
- unsupported Gold-API spread remains `unknown`;
- an unavailable cross-market series remains an explicit `state=unknown` series;
- absent AIDY lifecycle input is `evidence_state=unknown`, not proof of zero active signals;
- macro rows may produce `clear_current_window` only when the caller explicitly states that the macro evidence query itself is known/available.

An empty macro row set with `macro_evidence_state=unknown` remains timing `unknown`.

## Macro/Fed event timing rule

The Day 10 event layer is timing context only. It does not claim surprise, importance magnitude, market impact or causality.

For the agreed high-impact event classes, revisions are selected only from observations knowable at the packet as-of timestamp. Future revisions cannot leak backwards.

A calendar poll's `first_observed_at` timestamp is evidence knowability, not the event time. Re-fetching a schedule shortly before a decision must not create a false "recent event" window. Scheduled events are classified from their official scheduled time. Release observations may use reliable published/first-observed timing when appropriate.

Default descriptive event window in v1 is 60 minutes before and 180 minutes after the event. This is context metadata for later intelligence and is not itself a trading gate.

## AIDY lifecycle boundary

Day 10 reserves a narrow contract for AIDY's own theoretical/paper signal lifecycle so later Master Trader/Watcher work can know what AIDY itself has already instructed.

Allowed state is limited to AIDY identifiers and theoretical instruction state such as direction, market entry, entry price, SL, targets and AIDY timestamps. Active signals are deterministically sorted before hashing.

External execution/account fields are rejected recursively. This prevents Day 10 or later AIDY intelligence from accidentally becoming dependent on follower or broker state.

## Data quality

The packet records factual quality descriptors rather than silently filling gaps. V1 includes:

- missing Gold timeframes;
- quote availability, age and freshness;
- spread known/unknown state;
- macro evidence availability;
- missing enabled cross-market series and their observation ages;
- AIDY signal-lifecycle evidence availability;
- explicit machine-readable quality flags.

The current quote staleness reference defaults to 300 seconds, matching the accepted AIDY evidence configuration. Later safety gates may decide what to do with stale/unknown evidence; Day 10 only describes it.

## Provenance

Every fact remains traceable through the accepted upstream contracts.

The context provenance bundle carries:

- Day 7 feature packet digest and Gold source links;
- macro-event evidence/load/archive/payload identifiers for relevant current-window/next-event facts;
- Day 9 provenance for every enabled cross-market series;
- an AIDY lifecycle state digest.

Day 10 does not strip upstream provenance to make the packet smaller. Later model-context composition may choose a bounded presentation, but the canonical evidence packet remains reconstructable.

## Acceptance gate

Day 10 passes only when automated tests prove:

1. identical evidence produces an identical packet and hash, including under reordered inputs;
2. changed evidence changes the context hash;
3. missing data remains explicit unknown;
4. retrospective Gold features and tampered feature packets are rejected;
5. future macro revisions cannot leak into earlier contexts;
6. calendar refresh timestamps cannot create false event windows;
7. broker/follower/account state is rejected;
8. enabled cross-market facts retain provenance;
9. the full existing project test suite remains green.

## Downstream contract

Day 11 regime classification and all later case-building, analogue retrieval, Master Trader, replay, evaluation and Master Watcher work should consume this canonical Day 10 observation language rather than independently rebuilding market truth.
