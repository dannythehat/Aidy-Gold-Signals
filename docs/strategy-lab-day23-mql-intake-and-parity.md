# Day 23 — Source-bound MQL4 and MQL5 intake, signal and opposite-cross exit reproduction

Date: 14 October 2026. Owner direction: build the actual independently testable AIDY adapter and customer-led submission service; no owner/customer MetaTrader login, code compilation, chart export or trading account is an onboarding condition.

## Engineering deliverables

- `src/aidy/strategy_lab_mql_adapter.py`: safe bounded original-source SHA256 admission for `mql4`/`.mq4` and `mql5`/`.mq5`, explicit exact pure function grammar for closed EMA(10)/EMA(30) crossover **entry** and opposite cross **exit**; match entire programme and reject any added code. No execution of MQL files.
- `src/aidy/strategy_lab_customer_mql_intake.py`: safely inspect any customer .mq4/.mq5 UTF-8 source as *data*, fingerprint it, return supported-subset / reconstruction-required results and readable questions about rule timing, exits, risk, sessions and broker costs. This is a library and CLI, not a public customer portal. `scripts/strategy_lab/day23_triage_customer_mql.py` is the read-only CLI.
- Frozen, internally authored pure predicate fixtures `research/strategy_lab/fixtures/day23_internal_closed_cross.mq4` and `.mq5`. These are **not** customer EAs or audited third-party strategies. Both versions contain the same restricted two Boolean formulas; this only proves AIDY's interpretation of those formulas.
- `scripts/strategy_lab/day23_real_mql_audit.py`: read genuine frozen-source HistData XAUUSD bid M1 from the already verified 2025-01-06 11:00–21:00 UTC warehouse interval, derive only complete M5 candles, use independent Decimal EMA mathematical recurrences and compare the admitted MQL4/MQL5 entry/exit event **timestamps** and StrategySpec entry signals. A second read-only BigQuery query must reproduce the original input hash.
- `tests/test_strategy_lab_mql_adapter.py` and `tests/test_strategy_lab_day23_real_mql.py`: failure cases, exact source SHA binding, source syntax whitelist, both language claims, hostile file strings, changed StrategySpec/EMA or execution settings, input gap/future-bar/invalid EMA, seed scope and forbidden promotion to broker parity.

## Hard qualification boundary — especially important for MQL4 vs MQL5

**This is a pure Boolean signal/exit-predicate adapter, not a compiled Expert Advisor, complete stop/target trade engine or native MetaTrader Strategy Tester certification.**

Official MetaQuotes language references show why it would be unsafe to interpret arbitrary native indicator calls as interchangeable: MQL4 `iMA` returns an indicator **value** for a given bar shift ([MQL4 manual](https://docs.mql4.com/indicators/ima)), while MQL5 `iMA` creates an indicator **handle** that requires correctly indexed `CopyBuffer` access ([MQL5 iMA](https://www.mql5.com/en/docs/indicators/ima); [CopyBuffer manual](https://www.mql5.com/en/docs/series/copybuffer)). The restricted source subset does not pretend to execute either API and instead consumes an explicitly verified closed indicator trace. It matches pure predicates, **not** native platform EMA buffer construction.

The source file contains only entry/exit **conditions**. It does not implement actual `OrderSend`, `CTrade`, MT4/MT5 event callbacks, order state, opposite-signal close execution, protective stops, targets, trailing, maximum-hold exit, commissions, swap, broker order execution or price fills. The broader typed StrategySpec can declare some of those rules, but they are **not** automatically inferred from this source. Any source with such instructions is rejected by the subset parser and routed to questions/manual reconstruction.

**Native MT4/MT5 source-identical signal/time/exit parity is UNVERIFIED until an independently captured source-identical terminal run is available.** AIDY internal calculations on actual HistData are valuable independent qualification but are not a provider-generated reference report. This is not a reason to ask owner or customers to create broker accounts or supply credentials.

## Acceptance and reproducibility

- **Scoped internal technical acceptance:** run the actual CI workflow `.github/workflows/strategy-lab-day23-mql.yml` with real BigQuery credentials in the existing trusted GitHub environment, require all tests and genuine historical read-only/replay verification, merge to protected `main` and record job/run IDs, source hashes and exact observed entry/exit times in Notion.
- **External broker/provider execution acceptance:** separately OPEN; no native terminal execution, broker equivalence or full exit-order parity claim. Profitability is never inferred from predicate agreement.
- **One customer submission must not be blocked solely for not knowing MT4/MT5.** AIDY can receive a submitted script and identify what we can and cannot confidently reproduce. Advanced native parity requires independent evidence and owner-controlled engineering infrastructure, not compulsory customer platform signup.
