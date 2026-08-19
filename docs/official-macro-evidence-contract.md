# AIDY official macro-event evidence contract

Decision date: 2026-08-19
Day 8 implementation: 2026-08-19

## Purpose

Day 8 records high-impact US macro/Fed timing and release evidence from free official sources so later Gold research can reconstruct what AIDY actually knew around events. This is evidence capture only. It does not infer surprise, market impact, causality, forecasts or trade direction.

## Official-source allowlist

AIDY Day 8 uses only:

- Federal Reserve: monthly Board event calendars and the existing official monetary-policy RSS feed.
- Bureau of Labor Statistics: official release calendar ICS and official RSS feeds for Employment Situation, CPI, PPI, JOLTS and Employment Cost Index.
- Bureau of Economic Analysis: official release schedule and current-release pages for GDP, Personal Income and Outlays/PCE and International Trade.

No paid news, economic-calendar or broker API is introduced.

## Evidence classes

The initial high-impact classes are:

- `fomc_decision`
- `fomc_press_conference`
- `cpi`
- `ppi`
- `employment_situation`
- `jolts`
- `employment_cost_index`
- `gdp`
- `personal_income_outlays_pce`
- `international_trade`

## Point-in-time rules

Schedule and release observations are separate facts.

- `scheduled_at` may describe a future event because an official calendar can legitimately make that schedule knowable in advance.
- `published_at` is stored only when the official source exposes a reliable publication timestamp. If only a date is exposed, the publication clock remains unknown instead of being invented.
- `first_observed_at` is AIDY's knowability timestamp and is stamped only after the HTTP response containing that observation is available to AIDY.
- Later source changes are append-only revisions. They never overwrite what was knowable earlier.
- Event-window reconstruction first filters revisions by `first_observed_at <= as_of`, then chooses the latest eligible revision. A later revision cannot leak backwards.

## FOMC timing rule

Federal Reserve monthly calendar pages can display a two-day FOMC meeting. The decision timestamp is the official 2:00 p.m. release day, not the first day of the meeting. The press conference timestamp is the official 2:30 p.m. release-day entry.

FOMC schedule logical IDs are month-scoped. If the Federal Reserve changes a same-month release day, the new payload retains the same logical external ID and therefore becomes revision 2 rather than a separate unrelated event.

## Storage and provenance

Every observation uses the existing AIDY event-evidence path:

1. D1 append-only event row with revision index and `first_observed_at`.
2. Archive-outbox pointer committed with the evidence.
3. Immutable R2 archive object.
4. Later BigQuery export through the existing Day 4 evidence contract.

Source URL/ID, headline, structured fields and payload digest are preserved. Raw source-derived event payloads remain archived through the existing R2 path.

## Runtime boundary

The official macro recorder is an independent bounded component in the existing Cloudflare recorder cycle. Its default cadence is 900 seconds. A source failure is isolated and cannot stop broker-free Gold price capture or archive retries.

The runtime uses the revision-safe `fomc_calendar_parser.py` for FOMC timing. The older helper in `official_macro.py` is not the active recorder parser.

## Event-window reconstruction

`aidy_macro_event_window_v1` reconstructs an event window around a requested center timestamp using only observations knowable by the requested `as_of` timestamp. It returns scheduled, published and first-observed timestamps plus immutable evidence provenance where available.

Unavailable timing remains null/unknown. The layer does not calculate or fabricate economic surprise, importance or causal explanations.

## Day 8 acceptance

Day 8 may pass only when:

1. the full project suite and Day 8 parser/PIT fixtures pass;
2. official live endpoints respond and produce current real observations for the agreed classes;
3. the real Federal Reserve calendar parser proves the release-day rule for a live FOMC month;
4. revision fixtures prove pre-revision reconstruction returns the earlier schedule and post-revision reconstruction returns the later schedule;
5. the existing D1 event path remains append-only/idempotent and event-window reconstruction is PIT-safe;
6. no paid calendar/news source or broker/Super Signals dependency appears in Day 8;
7. failures remain isolated from the market recorder.
