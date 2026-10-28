# Gold Bot Packaging — canonical engineer handoff

**Owner-approved DESIGN only, 28 Oct 2026; server not installed and partner's fork not received.**

Full detailed [Notion child blueprint](https://app.notion.com/p/407e30f1e540811ebe77dc39bbb2288b) under the [Oracle Hub GOLD master agreement](https://app.notion.com/p/407e30f1e5408178bb79eea9c758b018).

## One bot, one independently versioned release

Never ship an entire AIDY clone or the friend's private crypto engine as an individual bot. Take the precise source-reviewed, pinned strategy implementation. Its immutable `S###` ID, distinctive mechanic-derived name and slug, upstream source/license/commit, configuration, source-data restrictions, multi-year AIDY reports, test evidence and generated file hashes must travel together.

Proposed content (strict release allowlist):
```text
manifest.json
README.md
strategy/bot.py           # Python only if this is verified original/adaptation
strategy/EA.mq5          # MQL5 only if actual source-native
config/defaults.json
contracts/signal-v1.json
tests/
evidence/
assets/icon.svg           # only with original reviewed rights
deployment/windows/
requirements.lock
SHA256SUMS.json
```

The attached JSON Schema is at `contracts/oracle_hub_gold_bot_manifest_v1.schema.json`. It enforces the safety of a RESEARCH_ONLY package; real account routing belongs in a distinct, audited **stage deployment**, never in the immutable release. A source SHA256 proves byte integrity, not permission or publisher provenance. No broker secrets, account passwords or private keys anywhere in a zip.

## Proposed Windows host layout — NOT INSTALLED
```text
C:\OracleHub\Gold\
  00_Inbox\
  01_Registry\
  02_Packages\S###\version\
  03_Paper_Testing\S###__slug\{worker,state,logs,reports}
  04_Cent_Testing\S###__slug\{worker,state,logs,reports}
  05_Approved\S###__slug\{worker,state,logs,reports}
  06_Oracle_Master\
  07_Quarantine\
  08_Backups\
  09_Hub_Exports\
  shared\
```

A bot promotion leaves the previous stage's ledger untouched. Reference the same immutable release digest, initialise a new per-stage identity and fresh state, and separately verify account permissions. Folder presence does not qualify trading. `00_Inbox` contains untrusted files, never executed.

## Proposed dashboard card and link contract

After the actual private fork + README is obtained and inspected, adapt to its real routes. **Not yet deployed**:

- GOLD homepage cards grouped into **Paper Testing**, **Cent Testing**, **Approved**.
- Every tile: original mechanism-based name, unique approved icon, immutable S### key, stage, last verified heartbeat, dated daily/weekly/monthly metrics, closed vs open P&L and provenance. No historical-only bot gets a live tile.
- Click icon or name to proposed `/hub/gold/bots/{slug}` with full stage-specific statement and trade history; show a link back to proposed `/hub/gold`.
- Read-only candidate listing and account routes are separate. Do not infer active account from a folder or artificially populate a demo balance.
- Suggested API (not implemented): `GET /api/gold/bots`, `GET /api/gold/bots/{slug}`, and `GET /api/gold/bots/{slug}/performance?period=day|week|month`. Real fork route schema prevails.

## Signals versus execution

A strategy returns a typed intent for the verified completed bar and its own frozen code version. A separately reviewed gateway, not the strategy, manages the specific demo, cent or master account. Persist unique intent/order/deal IDs and reconcile before retrying ambiguous broker responses. Oracle master has its own exposure and P&L, not summed paper ledgers.

## Handover for every future AI

1. Read this page, parent Notion, AIDY original source report and source licence.
2. Verify several years of reproducible historical performance and all failures; **83 discovered ≠ 83 qualified**.
3. Give strong candidates an original name/icon; map to immutable S### source and version.
4. Build release, provenance/test manifests, hashes and repeatable offline tests; do not add guessed live code to the original.
5. Inspect actual friend's private fork and deployment README before changing homepage/UI routes.
6. Validate real Windows host capability, original broker symbol, account type, contract units and stage isolation; no execution from build alone.
7. Stage in Paper only after owner-approved verified demo credentials; review after one **complete profitable paper month** and appropriate sample/drawdown, not automatic promotion.
8. Cent funded test requires separate explicit owner permission and an actual broker account whose XAUUSD sizing allows small risk. Exact cent time threshold not yet owner-fixed.
9. Approved and Oracle master allocation each require independent statements and explicit owner review.
10. Daily / weekly / calendar monthly reports keep historical AIDY, demo, real-cent and master reconciled P&L separate. Never publish invented/stale live metrics.

Primary current status: partner fork missing, general Contabo remote administration unverified, 83 discovery research queue (CI passed) not activated, no individual Gold Oracle paper/cent deployment established.
