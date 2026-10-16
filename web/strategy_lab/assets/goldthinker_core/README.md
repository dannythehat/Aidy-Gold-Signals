# GOLDTHINKER — GLOBAL WEBSITE ARTWORK (excludes named systems)

**Asset register as at 2026-10-16:** 6 actual user-supplied PNG images received, original ZIP bytes preserved in owner-controlled Drive, 8 original brief tags still unfilled.

## Permanent originals and access

- **[Drive — GoldThinker Core Website Artwork](https://drive.google.com/drive/folders/1SOPmm07i2r6tONSBm15e9JjqHi49o0nN)**.
- **[Original user-uploaded ZIP, all 6 exact PNG files, unmodified](https://drive.google.com/file/d/1j9vnb0tmheD8V5CNiElB-wQZpqWUJIPU/view?usp=drivesdk)**. Source ZIP SHA256: `215d535164bcec182b2990ab110a76af69691c0477288d34fff4d431d55a8c76`. This preserves the exact owner source, independent of chat attachments.
- GoldThinker customer/research [operations register](https://docs.google.com/spreadsheets/d/1ri94tJaaEiPGbhRaFyA12kUUl4l3enP3jzOepX1RCsU/edit), **tab `17_CORE_WEBSITE_ARTWORK`** lists all 14 reserved tags, 6 present with file names and dimensions, and 8 correctly marked **PENDING**.
- Website-ready WebP derivatives and exact byte-level source/derivative SHA manifest are also saved in owner's ChatGPT Library folder `/GoldThinker Website Assets/Core Website v1/` as **`GOLDTHINKER_Main_Website_Assets_v1.zip`** alongside six extracted unchanged PNGs and `manifest.json`. Copy the WebPs to deployed static image storage during actual website build. The **original source ZIP in Drive is the cross-platform canonical original backup**, not a production CDN.

## Website asset map (use EXACT tags and uploaded names)

| Tag | Source image in preserved Drive ZIP | Pixel size | Exact intended website placement | Status |
|---|---|---:|---|---|
| GT-WEB-01 | `GOLDTHINKER_01_hero.png` | 2400×507 | Homepage primary hero / very wide masthead | READY |
| GT-WEB-02 | `GOLDTHINKER_02_mission_research.png` | 1800×644 | Brand introduction and mission | READY |
| GT-WEB-03 | — | — | Meet AIDY internal engine | **PENDING** |
| GT-WEB-04 | `GOLDTHINKER_03_research_lab.png` | 1800×618 | Gold Edge Hunt / research laboratory | READY |
| GT-WEB-05 | `GOLDTHINKER_04_verification_pipeline.png` | 1800×684 | How It Works, 5-stage verification explainer | READY |
| GT-WEB-06 | — | — | Independent challenge and verification close-up | **PENDING** |
| GT-WEB-07 | — | — | Customer PDF/report showcase | **PENDING** |
| GT-WEB-08 | — | — | Paper-trading monitoring | **PENDING** |
| GT-WEB-09 | `GOLDTHINKER_05_systems_discovery.png` | 1800×635 | Systems discovery section header, NOT overlay behind cards | READY |
| GT-WEB-10 | — | — | Premium master portfolio | **PENDING** |
| GT-WEB-11 | `GOLDTHINKER_06_frosted_dashboard_background.png` | 2100×900 | Quiet dashboard / account balances and trade table background | READY |
| GT-WEB-12 | — | — | Trust and independent research | **PENDING** |
| GT-WEB-13 | — | — | Join the Lab CTA | **PENDING** |
| GT-WEB-14 | — | — | Footer / contact low-contrast texture | **PENDING** |

## Developer handling

1. Keep these six named **core brand assets separate** from individually named system images. CROSSFIRE's seven system artworks are maintained in [its own official Drive folder](https://drive.google.com/drive/folders/19mU8r3Q8XcqLG9KLGcPjaH6dfpFs-UZ6) and [own GitHub asset map](https://github.com/dannythehat/Aidy-Gold-Signals/blob/main/web/strategy_lab/assets/crossfire/README.md).
2. Download the **canonical ZIP** above at website-build time and confirm SHA256. Use the WebP derivative pack from ChatGPT Library or regenerate/WebP-optimize only from the preserved originals.
3. Install under a future real website project's asset path, e.g. `public/images/goldthinker/core/`; the site is **not currently installed or launched by this asset import**. Record exact filename path in the future web build.
4. Uploaded `GT-WEB-01` is an ultra-wide `2400×507` masthead (~4.73:1). Do not stretch/crop to fake 16:9. Text/logo and small navigation-like labels are already baked in; implement real site navbar separately with care for duplicates.
5. `GT-WEB-05` verification art contains generic process words; neither image nor infographic itself certifies a strategy for user subscription or paper execution.
6. `GT-WEB-09` has large foreground headings and should introduce the systems **section**, not compete with actual CROSSFIRE or future cards in the grid.
7. `GT-WEB-11` is purely decorative. Any account equity, trade list or P&L must be real source-verified, labeled PAPER when appropriate and never embedded as made-up image text.
8. Asset screenshots are illustrative visual identity, not evidence of a physical lab, audited live accounts, promised returns or customer subscriptions.

**User-provided originals are preserved and indexed now.** Remaining 8 of the original 14 requested sections await separate submitted/generated assets; do not quietly assert they are already created.
