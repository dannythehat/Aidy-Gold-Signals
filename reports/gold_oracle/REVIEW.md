# Original 83 source audit — batch 01 engineering receipt

Research only. Original IDs retained. No bot admitted, named, deployed or connected.

## Executed evidence

- Owner instructions fully read from `docs/oracle_hub/CODEX_83_GOLD_SYSTEMS_DEDUP_AND_BULK_TEST.md` at source tree `13428282bd972ce6e45679d92820e16433bedd08`.
- [Draft PR #374](https://github.com/dannythehat/Aidy-Gold-Signals/pull/374), isolated branch `codex/83-source-audit-batch01-20261028`. The owner-specified parent research branch already contained other unmerged work; this PR inherits that lineage.
- [Successful first authentic batch](https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/40684602595), code `ccc859c042453c7275217285ab187c93f52b3e92`: six IDs, three historical periods, two economic scenarios, 36 recorded cases. **Eighteen negative scenario results retained**, including defective-engine diagnostics; these are not 18 certified strategy failures.
- [Initial failed attempt](https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/40684079400): BigQuery authenticated but an added predicate compared STRING prices to numeric literals. Fixed numeric SAFE_CAST, fail-closed NULL provenance and literal SHA regex quantifiers. All twelve original 2023 R2 month reads passed and were reused, without downloading archives again.
- Local focused checks: 25 passed. Further common-cost and causal-sizing-probe CI receipt will be recorded separately; the first results are immutable.

## Coverage and honest limits

`83_source_and_duplicate_audit.csv` and `.json` contain exactly S001–S083. Current Drive scoreboard was read and reconciled: its 84th entry is the separately derived S005-C, not an additional original source ID. Earlier S001–S006 negative/disputed reports remain untouched and linked.

All **61 distinct source URLs** attempted: 17 GitHub repositories retrieved with commit/blob/file SHA evidence; 21 readable web pages without authenticated executable code; 23 direct-access failures. At ID level, these correspond to 33 code-retrieved, 22 page-only and 28 access-blocked entries. A source receipt is **not** a completed rule audit.

Detailed selected Python rule cards cover S005–S010. Twelve further source modules S020–S031 and their shared detection/exit dependencies were reviewed, with concrete rules and blockers recorded. Their exact equity sizing, selected timeframe and account semantics are incomplete; complete mechanics fingerprints are withheld. Fifteen other code-retrieved IDs still require full source-specific review. Page-only or blocked sources remain SOURCE_UNVERIFIABLE; no source rules or performance invented.

MQL source-page fallback succeeded for [S036–S039](https://www.mql5.com/en/code/77687) and [S040](https://www.mql5.com/en/code/77691), but both discovered native `.mq5` downloads returned HTTP403 locally. The first is an overlapping per-setup exit-comparison indicator; the second is an account-trading EA. Marketing backtest tables were not imported as AIDY results. Native code and parity remain required.

**All 83 fully source-audited: FALSE. All 83 backtested: FALSE.**

## Duplicate/family decisions

No exact duplicate pair or full parameter-variant pair has been frozen. No independent out-of-sample edge certified. Each original ID remains its own canonical ID pending proof.

| Shared-source group | Current disposition |
|---|---|
| S005–S009 | Five different signal functions in one pinned publisher module. Shared engine; selected S007/S008 settings are explicitly first source-grid combinations, not unique released gold presets. Related methodology/codebase does not prove duplicate mechanics. |
| S020–S031 | Twelve different source modules with different triggers. Shared setup/stop-first outcome engine. Missing account semantics and multiple causal/executable-fill issues. No independence claim. |
| S014–S015 | Source retrieved; per-method audit pending. |
| S036–S039 | Written parameter/exit alternatives identified; native code inaccessible. Provisional review only, no family frozen. |
| S041–S043 | Native source inaccessible. UNKNOWN. |
| S064–S065 | Shared TradingView page readable, executable Pine not retrieved. UNKNOWN. |

`family_graph.json` preserves 83 nodes and conservative review edges. `dedup_mechanics_review.json` preserves all 125 review pairs; none is an automatic alias, deletion or admission.

## Historical data and fidelity

2023: twelve original private R2 tick ZIPs independently re-read and hashed; all quotes validated, fixed EST UTC−05 interpreted, chronology inversions recorded, separate deterministic H1 derivative. 5,020 admitted H1 bars, 817 non-adjacent H1 transitions. Raw archives never rewritten.

2024/2025: authenticated BigQuery SELECT-only monthly original HistData M1 BID validation; 5,878 and 5,866 complete H1 bars respectively. Numeric OHLC aggregation and source/payload SHA gates applied. One immutable snapshot per source/year, reused across all six systems and cost scenarios.

These are **three sets of verified source months**, not three independently certified complete broker-calendar years. Partial hours excluded; gaps not repaired. No complete event-aligned ASK OHLC, broker calendar, financing schedule, lot/margin/stopout or native MT5 parity. 2025/2026 have already been examined; 2023 also is not claimed referee-sealed OOS.

S010 original SMA12/34 + RSI14 signals were checked against pinned publisher code. AIDY uses its existing next-H1-open fixed-unit accounting with illustrative spread/slippage/commission; publisher per-bar leverage accounting differs. No native original tick-fill parity claim. No strategy stop exists. Drawdown below is H1-close marked drawdown, not true intrabar worst equity.

| Independent $10,000 S010 historical model | Closed trades | Base net marked USD | Stress net marked USD | Base H1-close DD |
|---|---:|---:|---:|---:|
| 2023 R2-derived BID | 65 | 2,484.93 | 1,224.05 | −23.538% |
| 2024 BigQuery BID | 77 | 11,438.10 | 9,313.18 | −14.532% |
| 2025 BigQuery BID | 83 | 15,032.76 | 13,186.28 | −33.671% |

Each year has a fresh independent model account; these figures are not a combined track record or broker returns. S010 2025 reproduces the prior source model's net and H1-close DD.

### Apex source defects and controls

Pinned publisher `research/engine.py`, lines160–184, uses entry bar close `c[i]` for notional sizing at entry open. An adversarial test proves future-close changes can change entry quantity under the leverage cap. Original bytes and all original diagnostic losses are preserved. The defect may be inactive for a particular tape/parameter set: a separately identified two-reference causal-sizing sensitivity probe compares exact trades and equity, rather than assuming its actual effect.

Original Python close-bar exits also differ from the publisher's MQL next-bar implementation; floating ounces are not MT5 lot steps. Default per-setup engine warmup250 consumes the beginning of each yearly period. S005 figures therefore cannot be asserted equal to earlier December-warmed R2/native studies; tape, warmup and engine identity must match before comparing.

First-run Apex diagnostics preserve publisher $0.45/oz RT base and diagnostic $1.48 stress. S010 uses $0.47/$1.44 RT equivalents. These first-run engine-native cost assumptions are **not directly comparable**. A new common-cost run fixes all systems to $0.47/$1.44, retains both experiments, and reuses the same immutable snapshots. Funding, margin and quote timing remain unqualified in either run.

## Next executable queue and blockers

1. B01 S005–S010: immutable first-run ledgers retained. Common-cost/causal sizing sensitivity runs use already authenticated snapshots; no repeat source downloads.
2. B02 S020–S031: twelve related, different source modules. Admission blocked until selected timeframe/account risk and causal fill semantics are faithful. S021/S022 confirm on close but retrospectively book a broken-level intrabar entry; S024 full-series swing clustering requires prefix stability; FVG/OB fill gap semantics need native event checks. No fabricated dollar ledger for an R-only setup scorecard.
3. Remaining code-retrieved sources: audit originals and dependencies, keep failed studies, implement source-specific parity before replay. Protected/unavailable publisher sources require actual executable source or complete original written rules. A title, page description or commercial screenshot is insufficient.
4. Simultaneous portfolio/correlation: common-tape signal overlap traces emitted, but no independence declared. Shared broker margin, opposing positions, financing and aggregate risk remain blockers; no sum of six independent $10k models is called a master account.

No production runtime, D1, original R2 objects, broker account, server, funding, orders, protected main or rival Notion journal changed. GitHub reports this repository's visibility as **public**; no original ZIPs or full historical quote datasets are committed. Do not assume a private repository or publish proprietary publisher code here.
