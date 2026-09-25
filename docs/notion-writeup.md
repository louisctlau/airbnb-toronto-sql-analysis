# Toronto Airbnb — SQL Analysis

An end-to-end SQL analysis of Toronto's short-term rental market: ingest a real public dataset, profile its quality, then answer business questions with clean, portfolio-ready SQL — repeated across four monthly snapshots so every figure is comparable over time.

**Links:** [GitHub repo](https://github.com/louisctlau/airbnb-toronto-sql-analysis) · [Live dashboard](https://airbnb-toronto-sql-analysis-fcm6dzs4tnujlsprhnn7mm.streamlit.app/)

## Dataset

Source: [Inside Airbnb](https://insideairbnb.com/get-the-data/) — detailed listings file, Toronto. Four monthly snapshots, June → September 2026, with schemas verified identical (90 columns, same header order).

| Snapshot | Release | Scrape window | Listings |
|---|---|---|---|
| June 2026 | 2026-06-15 | Jun 16 → Jun 28 | 22,198 |
| July 2026 | 2026-07-14 | Jul 14 → Jul 16 | 22,212 |
| August 2026 | 2026-08-15 | Aug 15 → Aug 27 | 22,257 |
| September 2026 | 2026-09-16 | Sep 17 → Sep 18 | 22,050 |

The August snapshot goes deeper: `calendar.csv` (8,123,819 rows — every listing × 365 forward days) and `reviews.csv` (447,129 rows from 2023 onward) were imported as typed tables for calendar-unavailability and review-trend analysis.

## Key findings

**1. Entire-home prices fell four months straight.** Median $265 (June) → $256.91 → $254 → **$230** (September), a 13% slide. Private rooms were steadier ($85.50 → $81), so the entire-home premium narrowed from 3.10× to 2.84×. Waterfront Communities-The Island still dominates supply at ~17–18% of priced listings every month.

![Listings by neighbourhood](https://raw.githubusercontent.com/louisctlau/airbnb-toronto-sql-analysis/main/docs/charts/2026-09/listings_by_neighbourhood.png)

![Median price by room type](https://raw.githubusercontent.com/louisctlau/airbnb-toronto-sql-analysis/main/docs/charts/2026-09/median_price_by_room_type.png)

**2. The superhost price reversal.** In June, superhosts charged *less* than regular hosts on average ($273.80 vs $286.37). From July onward they consistently charge *more* (September: $247.73 vs $233.76, ~6% premium). Two and a half months of consistency makes June the outlier, not the rule. The quality gap holds throughout: ratings 4.87–4.89 vs 4.71–4.73, with superhosts earning ~1.5× the reviews per month.

![Superhost vs regular host](https://raw.githubusercontent.com/louisctlau/airbnb-toronto-sql-analysis/main/docs/charts/2026-09/superhost_vs_regular.png)

**3. The no-quote drift.** Listings without an active price rose from 17.7% (June) to 24.0% (September); the priced population is at a four-month low of 16,760 — the biggest structural change in the series.

**4. Calendar unavailability is an occupancy upper bound.** Calendar data (August) shows **47.8%** unavailability — bookings plus host blocks combined — ~2.4× Inside Airbnb's backward estimate (~20%); the estimate runs low in every neighbourhood. Winter is the bookable season (62% of days available in January); 56% of listings require 8–30-night minimum stays, consistent with Toronto's short-term rental rules.

![Calendar unavailability vs estimated occupancy](https://raw.githubusercontent.com/louisctlau/airbnb-toronto-sql-analysis/main/docs/charts/2026-08/occupancy_true_vs_estimate.png)

**5. Host concentration is stable.** ~53% of priced supply sits with single-listing hosts every month (avg $345/night) vs ~17% with 6+ listing operators (avg $211): casual hosts price high, professionals compete on volume.

**6. Review volume peaked in July 2026** at 24,685 reviews (up from 3,633 in January 2023). Fastest velocity: a Kensington-Chinatown private room with 92 reviews in 90 days.

![Review volume, 36 months](https://raw.githubusercontent.com/louisctlau/airbnb-toronto-sql-analysis/main/docs/charts/2026-08/review_volume_36mo.png)

## Techniques

The same 20-query pipeline runs on every snapshot: CTEs, window functions (`ROW_NUMBER()` for medians, `LAG()` for the marginal cost of an extra bedroom, `SUM() OVER ()` for market share), conditional aggregation, `CASE` bucketing, and time-series analysis with `STRFTIME`. Data-quality gates (duplicate IDs, negative prices, impossible review dates) run first and pass on all four months.

## Monthly reports

Full write-ups with all query output live on GitHub:

- [June 2026](https://github.com/louisctlau/airbnb-toronto-sql-analysis/blob/main/docs/findings.md)
- [July 2026](https://github.com/louisctlau/airbnb-toronto-sql-analysis/blob/main/docs/findings-2026-07.md)
- [August 2026](https://github.com/louisctlau/airbnb-toronto-sql-analysis/blob/main/docs/findings-2026-08.md) — includes the calendar & reviews deep dive
- [September 2026](https://github.com/louisctlau/airbnb-toronto-sql-analysis/blob/main/docs/findings-2026-09.md)

## Interactive dashboard

A 7-tab Streamlit app over all four snapshots: Overview, Neighbourhoods, Hosts, Pricing, Occupancy, Reviews, and an interactive value finder. It's deployed publicly — [open the live dashboard](https://airbnb-toronto-sql-analysis-fcm6dzs4tnujlsprhnn7mm.streamlit.app/).

## Automation

A monthly refresh script (plus a scheduled job running on the 20th of each month) probes Inside Airbnb for new releases, validates the schema, rebuilds the database, runs all 20 queries, regenerates the charts, drafts the findings report, and pushes everything to GitHub — so the analysis stays current with zero manual work.
