# CROSSFIRE S010 — H1-updated risk sizing research, 2025 and 2026 only

Owner brief: reduce original gold system's 33%/44% historical drawdown while protecting strong profitability; approximately 10% per month is an aspirational return, **not** a monthly guarantee or a selection target to overfit.

## Real source and original parity

- 2025 verified HistData native M1 BID -> 5866 fully sourced H1 candles: [frozen original real-data workflow](https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/38745844838).
- 2026 Jan-Sep verified original R2 HistData BID/ASK -> 4382 fully sourced H1 candles: [frozen 2026 workflow](https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/38851611865).
- 2020 and 2021 explicitly **excluded** from the risk-balance exercise per owner.
- Source trading rules unchanged: original long-only MA12/34 crossover with RSI14 filter, opposite crossover exits, original max 3.28x exposure.
- Validate exact 2025 +$15,032.76 and 2026 +$8,573.74 original model, **and** reproduce prior entry-only guard to cent (2025 +$7,641.47, 2026 +$9,312.00). A drift is CI FAIL.

## The two identified risk-design gaps

Previously we applied 50% sizing while marked account DD >=10%, restoring at DD <5%. But flag state was only updated at new-entry times. That stale logic crippled 2025 recovery.

**Balanced H1 rule (one changed risk-management dimension):** Update the DD flag on every **completed H1** mark, then size the *next* new entries at 1.64x if DD>=10%; return to 3.28x when DD<5%. NO retroactive lookahead, no automatic resize of existing positions, no new direction, SMA or RSI changes.

Also tested exactly two targeted alternatives against that balanced rule: a gentler 2.46x new-entry brake and an extra one-time 50% reduction of a currently held position at the next H1 open after DD>=10%. This is a bounded mechanism comparison, not an unrestricted backtest parameter sweep.

## Independently reproduced price-model comparisons

| Version | 2025 P&L (USD10k start) | 2025 H1 marked DD | 2026 P&L (USD10k start) | 2026 H1 marked DD |
|---|---:|---:|---:|---:|
| Original 3.28x | +$15,032.76 | -33.67% | +$8,573.74 | -44.07% |
| Previous stale/entry-only guard | +$7,641.47 | -32.56% | +$9,312.00 | -24.90% |
| **H1-updated half-size new-entry guard** | **+$10,048.65** | **-22.07%** | **+$10,542.25** | **-28.83%** |
| Gentler 75% exposure (2.46x) | +$12,528.68 | -27.96% | +$9,587.42 | -36.75% |
| H1-half new entry + one-time half of held trade | +$11,306.03 | -16.16% | +$5,790.53 | -19.85% |

HistData recorded ASK-entry sensitivity in 2026: original +$8,145.56 / -44.52%; H1-updated balanced guard +$10,244.60 / -29.12%. ASK is genuine third-party historic quote but not verified executable Vantage ASK. Fixed adverse slip and commission remain scenario assumptions.

2025 balanced guard 8/12 months positive and only 4/12 returned >=10%. 2026 balanced guard 5/9 months positive and only 3/9 >=10%, with large positive January-March and losing April-June/September. **No claim of consistent monthly income**.

Extra H1-low drawdown diagnostic (held longs marked to worst H1 BID low): 2025 balanced -22.37%; 2026 balanced -29.50%; this is NOT broker stopout certification.

## Required risk boundary before controlled $10k MT5 paper

- Historical simulations pre-viewed 2025/2026; this optimisation is **retrospective**, not genuinely unseen out-of-sample validation.
- There is NO verified Vantage broker overnight swap table, executable spread/volume slippage, full contract/margin terms and stopout/liquidation engine, and no account-level stop-loss guarantee.
- Especially important: an open position already at 3.28x can move violently before H1 close; the sizing rule only affects **new** trades. The peak-equity brake does not cap ultimate liquidation.
- A paper implementation must read account balance/equity and per-position exposure, reconcile end-of-candle UTC/MT5 broker clock, persist high-water mark across crashes, and include a separate hard overall risk kill-switch with owner-reviewed margin rules.
- No MT5 demo account has been started and no broker order may be placed by this research workflow. Individual GoldThinker subscription remains **LOCKED**.

## Reproduce

- [Source engine](../src/aidy/strategy_lab_crossfire_balanced_guard.py)
- [Runner](../scripts/strategy_lab/crossfire_balance_2025_2026_reproduce.py)
- [Historical two-source artifact CI](../.github/workflows/crossfire-balanced-risk-research.yml)
- [Drive tracker](https://docs.google.com/spreadsheets/d/1ri94tJaaEiPGbhRaFyA12kUUl4l3enP3jzOepX1RCsU/edit) tab `15_DRAWDOWN_RESEARCH`: append new experiments without overwriting older or original rows.

**Outcome: historically promising risk-balanced hypothesis, not production or paper qualification.**

## 18 October 2026 — PRIVATE Nursery refinement → System Builder packaging (implementation)

The real original-vs-five-variant, two-year frozen-source reproduction has an additional **private** downstream handover in the same GitHub Actions run: `nursery_refinement_package.json` (source and draft SHA, all variants, no invented approval), `nursery_refinement_package.md` (side-by-side review, operator checklist, brand/SEO/account tasks) and `nursery_refinement_internal_appendix.pdf` (two-page printable final research appendix). They are produced by `src/aidy/strategy_lab_nursery_refinement.py` **only after** the runner has independently reproduced the fixed figures against the two previously verified source-artifact datasets. The test fixture is never an accepted profitable strategy. This workflow remains PR research, not a broker or website deployment.

**Decision is not automatic:** `hourly_state_half_new` is the proposed risk-balanced compromise, but `selected_version=null`, `school_admission_approved=false`, `paper_trading_authorised=false`, `publication_authorised=false` and `customer_copy_authorised=false`. The proposed variant is historically promising, not source-validated for a real Vantage broker and not an owner-frozen approved paper version. All mechanical parameters stay in private research; public GoldThinker copy stays non-replicable.

**Private Notion staging** uses the existing [GoldThinker System Builder](https://app.notion.com/p/3fde30f1e5408141a04df260c00ecfef) and [CROSSFIRE paper-account preflight](https://app.notion.com/p/3fde30f1e540810daee1c17321cea8b8). The operator can save the generated Markdown/JSON/PDF to the dedicated Notion dossier after verifying the source digest. This branch does NOT install an unauthorised Notion service integration or claim automatic private page creation. A future owner-approved Notion service connection can read this exact immutable package without running new strategy calculations.

## 18 October 2026 — OWNER LOCK: GoldThinker uses CROSSFIRE BALANCED variant

**Authoritative owner decision:** In the private GoldThinker product, CROSSFIRE **S010** must use the already-reproduced **`hourly_state_half_new`** variant, not the unguarded original and not whichever variant happens to show the most profit. This is a fixed **platform version choice for packaging and paper-account preparation**, not proof that the original research passes Nursery, nor automatic broker order permission. The original and all other retrospective experiment ledgers must stay unchanged for traceability and comparison.

**Balanced means exactly:** Update the drawdown-brake state after each *completed H1* mark. At marked drawdown >=10%, size the *next new* entries at 1.64x rather than the original 3.28x; restore 3.28x when drawdown recovers below 5%. No existing open trade is automatically cut; a separate account risk kill switch/forced-stopout preflight remains necessary. Both-year historic results and substantial residual drawdowns (2025 -22.072%; Jan–Sep 2026 -28.828%) are retained and clearly labelled as model-only, not broker-real.

**All future GoldThinker systems:** before System Builder packaging, AIDY must compare the original with adequately tested risk-reduction refinements. GoldThinker chooses an evidence-supported, owner-approved **balanced risk configuration**, not blindly the highest historical profit. If no balanced variant has been credibly tested and accepted, **HOLD** the platform package and perform further risk analysis; do not invent a balance policy or secretly change strategy rules. An independently sourced provider-selection system such as Super Signals must get a source-specific risk framework, not copied CROSSFIRE indicator settings.

Implementation: `src/aidy/strategy_lab_goldthinker_balanced_policy.py` produces a separate immutable bound `goldthinker_platform_version_selection.json` and owner decision Markdown in the existing source-checked report artifact. The original Nursery research file remains an unapproved historical report. The platform selection confirms **version chosen**, but explicitly keeps `paper_execution_authorised=false`, `account_connected=false`, `broker_risk_and_margin_verified=false`, `funded_live_trading_authorised=false` and no paper start date. The actual owner choice is recorded in [private Notion](https://app.notion.com/p/3fde30f1e54081a59773fc9e71920cfe). No broker connection is activated.
