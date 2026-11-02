# S040 source recovery

Status: `FALLBACK_PIN_NOT_APPROVED`. Not a StrategySpec. Not approved. Nothing here was built, and PR #374 was not changed.

The original `GoldBreakoutEA.mq5` bytes are not in this repository. They stay in the agent store only.

## Register values

Read-only check of `reports/gold_oracle/phase05/review/83_strategy_register.json` on `codex/83-source-audit-batch01-20261028`, row `S040`, `native_compilation[0]`. These three values are present:

- source SHA-256 `a904aa1a7db85fd006a3989671025ce022fc304584da3fbda7116621770dc105`
- EX5 SHA-256 `963d53fbd317d078682d50b69ff549c0b77ce2819cc9ea6b374c67afd63a1b50`
- compile log SHA-256 `dffdd5e13c4b2501140a09ecbb986a4a2257a83f9af42dd360fa9577a7bf1a68`

`source_url` is `https://www.mql5.com/en/code/download/77691/GoldBreakoutEA.mq5`. `status` is `NATIVE_COMPILED`. `source_modified` is false.

## Recovery

Actions run `40821870250` still has artifact `oracle-phase05-native-S040-entry-parity` (artifact id `12875495178`, not expired, expires 2027-01-27). The archive has the compile log and `native_metaeditor_report.json`. It does not contain `GoldBreakoutEA.mq5` or an EX5.

The log file in that artifact hashes to `747aace9bc9b8994d0d51435995b4ec6d4a8b493827bf47543c58fd3f0678240`. That matches the artifact report's `log_sha256`, not the register's log hash. The artifact report's `ex5_sha256` is `a65c0a98f64d7e578b4eaaee53fcd71a8e33ab3000a06147cfc91fb4ce684090`, not the register's EX5 hash. The artifact report's `source_sha256` is the same value as the register.

The bytes used for the source hash are the official download `https://www.mql5.com/en/code/download/77691/GoldBreakoutEA.mq5` (page `https://www.mql5.com/en/code/77691`). Length 18508. Computed SHA-256:

`a904aa1a7db85fd006a3989671025ce022fc304584da3fbda7116621770dc105`

That matches the register source hash exactly.

## Licence

The source header sets `#property copyright "Ali Rajput"` and does not grant a licence. The Code Base page does not show a licence. It links to the MQL5 terms of use. The Code Base index says: "Download and study published code examples, develop your own indicators and Expert Advisors." That is not a clear permission to commit these bytes, or a line-by-line derivative of them, into this repository.

From https://www.mql5.com/en/about/terms, the clauses linked from the page:

> 3.9. You agree that You will not reproduce, duplicate, copy, sell, trade or resell the content of the website www.mql5.com, unless you have been specifically permitted to do so in a separate agreement with MetaQuotes Ltd. [...] You may not modify the Content in any way or publicly display, reproduce or distribute it.

> 3.13. [...] You agree that You will not, and will not allow any third party to, (I) copy, sell, license, distribute, transfer, modify, adapt, translate, prepare derivative works from, decompile, reverse engineer, disassemble or otherwise attempt to derive the source code of the software located on the website www.mql5.com, unless otherwise permitted [...]

> 3.15. In using the website www.mql5.com or MQL5 Services, You are not granted any intellectual property rights or rights in or to the website www.mql5.com or MQL5 Services or to any related content, including materials, documentation, products or services. Any other use of the content shall be allowed only subject to respective owner's authorization or when this is provided by law.

The licence check fails. No StrategySpec was written, because a line-by-line spec would be a committed derivative of the source.

## Fallback pin

S016 is pinned only. It is not approved and it was not built.

- Repo: `waihin26/Systematic-Commodity-Trading`
- Commit: `dad1684dd421ccaf134f73b9315a951a02938bd3` (2025-08-03, "Update README.md")
- Path: `strategies/gold_donchian_channel_strategy.py`
- GitHub blob SHA: `3e7b05b26b69b4cea4b0e671849add774e41bd70`
- URL: https://github.com/waihin26/Systematic-Commodity-Trading/blob/dad1684dd421ccaf134f73b9315a951a02938bd3/strategies/gold_donchian_channel_strategy.py

Label: `FALLBACK_NOT_APPROVED`.
