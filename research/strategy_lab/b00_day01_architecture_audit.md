# B00 / Day 01 — Repository architecture audit
Date: 2026-10-14
Status: **PASSED (source-level inventory only)**. B00 overall stage remains DISCOVERY; Day 02 access proof remains pending.

## Snapshot and scope
- Audited private repository `dannythehat/Aidy-Gold-Signals`, default branch `main`, Git tree `199ebb9c6738d5cceeebe76c122e5b8a8ca7685c`.
- 723 files: 167 `src`, 157 `tests`, 85 `scripts`, 79 `docs`, 119 `.github`, 32 `migrations`, 37 `ops`. These are source paths, not a statement that every feature runs successfully.
- All operations were read-only inspection except creation of this isolated research evidence file and accompanying inventory on the feature branch.
- No Cloudflare, BigQuery, R2, broker or trading runtime was contacted; no automated test suite was executed in the service environment.

## Confirmed reusable code surfaces
| Area | Source | Status |
|---|---|---|
| HistData XAUUSD backfill and provenance | `src/aidy/historical_backfill.py`; `docs/historical-backfill-contract.md` | Present in repository |
| Point-in-time market recorder and operational persistence | `src/aidy/market_recorder.py`; `docs/storage-contract.md` | Present |
| Historical first-touch/MFE/MAE outcomes | `src/aidy/trade_outcomes.py` | Present; not cash-account performance |
| Frozen chronological/CPCV replay | `src/aidy/replay_evaluation.py`; `docs/day37-frozen-replay-cpcv-contract.md` | Present; source-level |
| Trial integrity and strategy promotion | `src/aidy/research_integrity.py`; `src/aidy/strategy_promotion.py` | Present; isolated research |
| Position paper lifecycle | `src/aidy/paper_simulator.py`; `docs/day46-paper-simulator-invalidation-contract.md` | Present; R-only, intentionally no account USD or lots |
| Tests and quality tooling | `tests/`; `pyproject.toml` | 157 test files; no current full test-run claim |

## Historical data acceptance, verified as *documented historic event*
- `ops/day5-live-acceptance-evidence.md` records 2024 355,592 and 2025 353,951 native XAUUSD M1 bid OHLC rows, **709,543 total**, backfilled 2026-08-19 into `aidy-signals.aidy_analytics_test.research_candles`.
- HistData Generic ASCII timestamps are defined as fixed EST (UTC-05:00, no DST) with UTC normalization. Historical-derived M5/M15/H1/H4/D1 bucket alignment is source-clock based, not arbitrary UTC buckets.
- Recorded source gap counts 307 in 2024 and 291 in 2025. These include potential weekends/closures and MUST NOT be interpreted as 598 bad-data outages without classifying sessions first.
- Day 27 `docs/day27-historical-spread-j3-contract.md` documents genuine XAUUSD historical bid/ask ticks for December 2024 and January 2025 only. It is not evidence of a complete two-year executable tick archive.
- **CURRENT live access, source completeness outside accepted windows and commercial redistribution/report licensing remain UNKNOWN until Day 02+**.

## Architecture and safety findings
Cloudflare Workers = AIDY runtime, D1 = operational metadata/outbox, R2 = immutable raw archive, BigQuery = analytical history; no direct MT5 execution or broker credentials in the AIDY intelligence boundary. Old architecture documentation can mention previous Gold-API feed; the README/current Gold-learning handoff identifies later Twelve Data market path. Neither is proof of today's deployment without runtime probe. No changes to these paths in this sprint.

## Ranked customer-audit gaps
1. **P0** — Confirm queryable historical dataset and permissible commercial research use, validated broker instrument/clock.
2. **P0** — Implement exact StrategySpec and strategy/source parity, including fail-closed unsupported rules.
3. **P0** — Broker-realistic bid/ask/commission/financing/margin, $10,000 account simulator and independently reconcilable cash/equity ledger.
4. **P0** — Immutable per-run result/ledger/report linkage and audit-grade score.
5. **P1** — Full 2024–25 bid/ask/tick coverage or honest conservative simulation/sensitivity limitations.
6. **P1** — Sandbox external script uploads, tenant isolation and customer data handling.
7. **P2** — Customer dashboard, billing and owner-billing exemption after the engine is validated.

## Day 01 acceptance
- [x] Enumerate real repository files and architecture, record immutable tree identity.
- [x] Identify reusable source modules with direct file citations.
- [x] Separate dated historical backfill evidence from a current warehouse access claim.
- [x] Identify trading simulation and report gaps without inventing working features.
- [x] Record limitations and preserve operational isolation.
- [ ] **B00 complete** — not yet. Day 02 warehouse smoke and Day 03 gap/owner sign-off pending.

**Disposition:** Day 01 SOURCE INVENTORY PASSED. Next: B00 / Day 02, read-only BigQuery/R2 access and data verification. This pass does not qualify any historical performance result or customer trading decision.
