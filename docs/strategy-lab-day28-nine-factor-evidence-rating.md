# Day 28 — Owner-original nine-factor evidence rating, honest unknowns and vetoes

**LOCKED B07 Day28 requirement:** "Nine weighted factors, confidence, honest unknown/insufficient cases"; PASS "Scores only after independently verified runs". Original owner policy (not the alternative SIX-component illustration in the institutional blueprint) has EXACT nine weights:

| Factor | Maximum points |
| --- | ---: |
| Net trading expectancy | 30 |
| Out-of-sample robustness | 15 |
| Performance across market conditions | 10 |
| Drawdown and risk | 10 |
| Realistic trading costs | 10 |
| Rule clarity | 10 |
| Adequate sample size | 5 |
| Broker compatibility | 5 |
| Independent reproducibility | 5 |
| **Total** | **100** |

## Implemented

- `src/aidy/strategy_lab_evidence_rating.py`: immutable typed ordered nine-factor contract, factor-by-factor evidence status `VERIFIED / UNKNOWN / INSUFFICIENT / CONTRADICTED`, exact integer points when independently qualified, otherwise literal `null`. Each verified factor must trace to its DISTINCT 64-hex source receipt, so a sole study cannot be presented as nine independent confirmations. The source identity, scoring policy, evidence model input and factor evidence are deterministic SHA256-pinned. This is a **scoring policy consumer, not a signature/verifier for arbitrary uploader assertions**.
- `EvidenceBasis` requires real independently qualified bid+ask **COSTED EXECUTED trade receipts**, unmodified source and rule SHA, true original trade-level net profitability, a genuinely fair matched exposure baseline, labelled chronology with a separately qualified OOS trade outcome, original trial-family registration, independent replay and at least 30 completed authentic trades before a numeric 0–100 is even considered. The 30-trade threshold is a governance *minimum*, not a sufficient statistical-significance guarantee. Incomplete evidence means `score_out_of_100=null`; never silently invent a zero or claim the nine factors were independently reviewed.
- Owner RED / ORANGE / GREEN: `RED_REJECT` when independently verified net expectancy <=0, independently verified matched benchmark advantage <=0 or unacceptable observed risk; with fully qualified and reviewed scoring, below 50 also RED. `ORANGE_INVESTIGATE` when incomplete, unqualified, still inconsistent, between thresholds or lacking critical green factors. `GREEN_HIGH_PRIORITY` is conditional on verified total >=80/100, positive costed net expectancy and benchmark advantage, no serious risk veto, plus key minimum earned factor points (expectancy >=21/30, OOS >=11/15, drawdown >=7/10, costs >=7/10, reproducibility >=4/5). Exact numeric values are **provisional versioned internal research policy gates, NOT owner-approved empirical calibration, probability of success or financial-regulatory approval**. A high research ranking NEVER activates live trading.
- Owner rule: **optimisation suggestions only for PROMISING high-priority strategies** with verified provenance and good performance. ORANGE and RED do not trigger variant generation. Even high-priority systems need **a separate customer's explicit permission** before any editing/tuning, and an owner-controlled live deployment approval distinct from research.
- The nine component scores in this layer are evidence-review inputs, not self-authenticating statistical estimators. Full "independently verified" qualification in production will require an actual trusted, access-controlled ingestion/attestation adapter binding archive+ledger+trial/benchmark references to independent recomputations. *Do not let an HTTP/user-provided boolean or arbitrary hand-authored SHA cause a public 100/100 or green*. This Day28 package gates its own real-source output, but it does not claim to deliver that still-future real broker/execution attester or every statistical estimator.

## Actual source-integrated acceptance — NO invented edge

- `scripts/strategy_lab/day28_evidence_rating_acceptance.py` reruns **Day24 TWO real SQLite journal replays of a purely synthetic 4-trade example**; Day25 actual source-pinned TWO reference SQLite journals and THREE spread/commission/slippage stress scenarios on SYNTHETIC quotes; **Day26 true retrospective source BID-only HistData 600 native M1 -> 120 fully closed M5 chronological expanding folds with 20-label one-time holdout**; and **Day27 true bid-only M5 historical regime breakdown of exactly 48 pre-registered DEVELOPMENT validation points**. It checks all upstream source hashes/lineage and refuses fake qualification upgrades. Two independent READ-ONLY BigQuery source fetches must replay the complete Day28 integrated output identically. This validates evidence orchestration and honest scientific status, **not** that a winning gold system exists.
- Accordingly, all nine original factors are `UNKNOWN` or `INSUFFICIENT` as trading SYSTEM performance scores; original sample/indicator calculations are transparent but **no actual independently verified original-market costed P&L/OOS economic edge has yet been delivered**. Official report is **`score_out_of_100=null`, `ORANGE_INVESTIGATE`, `optimisation_suggestions_eligible=false`, `automatically_authorised_for_live_trading=false`**. It is the *correct pass* to decline a numerical rating here. Trade/sample insufficiency is not renamed "bad" without evidence.
- Tests cover exact nine-factor weights, synthetic hard-no-score, incomplete and contradictory evidence, dangerous zero/negative expectancy, no fair benchmark, absent OOS/ledger/family or costs, numerically perfect scenario still blocked by serious risk, Green factor minima, RED/ORANGE thresholds, malformed nonfinite/boolean integer metrics, duplicate sources/factors, reproducibility, and full Day24–27 integration.
- An abstract **policy unit-test** may manually construct all "verified" factor and source booleans solely to test the arithmetic. That does **NOT establish a genuine external data audit, real sample, a research recommendation, deployability, or a customer-facing high score**. Such fixtures MUST never be used in production API, a website, a PDF, or any evidence of found gold alpha.

## Next steps already fixed by owner

Day29 B08 canonical reporting schema and real result/ledger provenance; Day30 B08 actual PDF/CSV/chart exports; Day31 B08 adversarial report checks. Later future inbound customer submission, genuine multi-timeframe robustness, opt-in changes for only *PROMISING* systems, and deferred post-build voluntary strategy licence/revenue-share questions are preserved in Notion. No outreach, customer rights or customer system edits are created by this build.

## Final acceptance evidence

**PENDING** actual passing CI, genuine historical source replay, protected-main merge and independent documentation rerun. Do not mark this Day28 technical build PASS until exact verified IDs, source SHA and tests are recorded.
