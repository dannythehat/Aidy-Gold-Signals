# CROSSFIRE (S010) — official website artwork registry

**Registered:** 16 October 2026 | **Status:** asset-ready, **website NOT built**, paper trading NOT started.

**Permanent owner-controlled Google Drive sources:**

- [All seven individually named original artwork PNGs](https://drive.google.com/drive/folders/19mU8r3Q8XcqLG9KLGcPjaH6dfpFs-UZ6).
- [Complete v1 website asset ZIP — 7 original PNG + 7 optimized WebP + preview + manifest](https://drive.google.com/file/d/1-7726GEbkYGUz5Oap_KBJmpSYoVBUZl2/view?usp=drivesdk) within [GoldThinker System Reviews & Customer Tiles](https://drive.google.com/drive/folders/1-aYD4o8_x_sLo3Uc4Q2qZ3j7Xr27I3JZ).
- [GoldThinker operations register](https://docs.google.com/spreadsheets/d/1ri94tJaaEiPGbhRaFyA12kUUl4l3enP3jzOepX1RCsU/edit) -> tab **16_WEBSITE_ARTWORK** holds seven per-image links, placement, and WEBP filenames. S010 tab **10_CUSTOMER_TILES** includes official artwork folder.

**ZIP checksum SHA256:** `782363d63f082fa3ec2f533dd344fc05f1ea370e5fa43ce1119a311880aa9766`.
Individual original images have SHA256 receipts in the included `CROSSFIRE_Official_Artwork_Collection/manifest.json`.

## Image-to-website map

| Asset | Use | PNG from Drive | Optimised WebP inside ZIP |
| --- | --- | --- | --- |
| 01 signature hero | CROSSFIRE dedicated page masthead | [PNG](https://drive.google.com/file/d/1_3oVATNebRuevh38HcNAt-tGkC80bUPX/view) | `crossfire-01-signature-hero.webp` |
| 02 system catalogue | GoldThinker systems grid card | [PNG](https://drive.google.com/file/d/1lVCL6iUhTCOWzlADF-MhsH8AzyOYmv9y/view) | `crossfire-02-system-catalogue-card.webp` |
| 03 inside methodology | CROSSFIRE mechanics | [PNG](https://drive.google.com/file/d/1Q-u3XVTJ5dSTBZnf352HlujXdgYzdGqJ/view) | `crossfire-03-inside-methodology.webp` |
| 04 balanced risk | Risk/adaptive sizing explainer | [PNG](https://drive.google.com/file/d/1LJ4MtCoYdTFxXZrbMRun-TnlrB2NHPGn/view) | `crossfire-04-balanced-risk.webp` |
| 05 dashboard background | Future source-verified balance, trade and P&L overlay | [PNG](https://drive.google.com/file/d/1H3D4vFUFY3XYaLmijyYLqWt_A0_uKUkF/view) | `crossfire-05-dashboard-backdrop.webp` |
| 06 crossover emblem | Brand icon/avatar/system badge | [PNG](https://drive.google.com/file/d/160OJdJVxR4LgebmbWnTyO1Tz-96XaW9c/view) | `crossfire-06-crossover-emblem.webp` |
| 07 original campaign | Alternate hero/promo/social | [PNG](https://drive.google.com/file/d/14p484knFybLdcHBp_TGwFeHfbbPgEhYg/view) | `crossfire-07-original-campaign-art.webp` |

## Integration instructions for the future website build

1. Download v1 ZIP from Drive and confirm its SHA256. Extract `CROSSFIRE_Official_Artwork_Collection/website_webp` to the site's actual static asset storage (e.g. `public/images/systems/crossfire/`). The seven **original PNGs** remain in owner-controlled Drive with the full v1 ZIP and can be used for social/editorial versions.
2. Use explicit mapped filenames. Preserve text safe zones, avoid flattening real trades/metrics onto a background. Cards should link to the system's evidence and readable mechanics instead of inventing performance statistics.
3. CROSSFIRE's visual signature is MA12/34 crossover reticle + RSI14 + metallic-gold bull. The Balanced **new-order exposure** guard halves new-trade exposure at account peak-to-equity drawdown ≥10% and restores normal sizing when the drawdown is below 5%; it does **not** place a protective stop on all open orders or prevent liquidation.
4. CROSSFIRE is **research-only** until verified paper trading begins. Historical model profits are **not** paper account profit or customer net returns. Show paper field as **Not started** until reconciled broker simulation accounts exist.
5. **Google Drive is a preservation/source library**, not a production CDN. At website-build time, publish these WebPs into authenticated build assets / appropriate web storage; avoid directly embedding Drive download/view links as live site image URLs.

This step deliberately does **not** publish a website, launch MT5 connections, place orders, sell strategy subscriptions, or claim live-paper P&L. It creates permanent retrievable owner-owned visual assets and an explicit developer build map.
