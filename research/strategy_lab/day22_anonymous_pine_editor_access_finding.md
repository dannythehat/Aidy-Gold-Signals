# Day 22 — Direct anonymous TradingView Pine engine access finding

Date: 14 October 2026. This is a **real external browser access finding**,
not a TradingView platform signal-parity pass.

## Method and observed UI

The research GitHub Action ran on a clean hosted Linux browser with no
TradingView cookies, credentials or account connection. It navigated to
`https://www.tradingview.com/chart/?symbol=OANDA%3AXAUUSD&interval=5`:

- The **actual TradingView XAUUSD 5-minute chart** returned HTTP **200**.
- Its visible **Pine** control opened the actual **Pine Editor** with editable
  Monaco text area and a visible `button[title="Add to chart"]`.
- It loaded original local AIDY calibration source bytes from
  `research/strategy_lab/fixtures/day22_tradingview_exportable_v6.pine.txt`,
  SHA256 **`fd2955cfaf5fff3f39f22cc3ac2f39fca5c803f52c1414956b89d5996421c1f8`**,
  into the anonymous editor as an attempted user-script interaction.
- **Critical observation:** Clicking the native **Add to chart** button
  opened TradingView's own **Sign in** panel showing **Email**, **Sign up**.
  It did not produce a TradingView compiled source or strategy signals.
- Monaco's normal auto-indentation affected later lines when multiline text
  was inserted using keyboard events. A future authenticated end-to-end probe
  would need an exact editor-content hash check before attempting compilation.
  **The original source was not executed or validated by TradingView.**

Actual independently archived GitHub Action:
[run 38572774400](https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/38572774400),
job `115882005282`. Its output includes chart identity, Pine panel
controls, original source SHA, UI result after clicking Add-to-chart, and
visible provider **Sign in** prompt.

The follow-on source guard checks that signed-out add-to-chart explicitly
reports `native_add_to_chart_login_required=true` with
`pine_script_executed_by_provider=false` and
`original_platform_signal_parity_qualified=false`.
The browser experiment has **no financial or brokerage account permissions**.

## Consequences for AIDY's inbound business model

- Do **not** require customers to obtain TradingView chart exports or
  operate TradingView to submit a strategy. Day22 [customer-intake
  PR #271](https://github.com/dannythehat/Aidy-Gold-Signals/pull/271)
  accepts Pine file/text source hashes and asks ordinary-language clarification
  questions without a provider account.
- The Day22 restricted Pine parser, original-reference-verification code and
  read-only customer intake are all implemented, tested and merged, but
  **their internal synthetic fixture checks cannot prove the exact original
  TradingView source's platform signal timings**.
- The published third-party Gold script's original provider-native trade
  report is for a *different* source and is not a substitute.
- A genuine original-platform calibration run of the supported exact script
  requires a permitted authenticated TradingView Pine environment.
  We must not use the owner's email/account or create/supply credentials
  without explicit control of that account and safe handling.
- The **Day22 Notion checkbox stays unchecked** under its existing
  `Original TradingView reference signals match` criterion. This is an
  access/provenance prerequisite of a higher external-fidelity claim, not a
  customer intake feature gap.

Do not weaken provider parity acceptance, assert signal match without an
original run, or block customers from submitting scripts in the meantime.
