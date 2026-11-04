# Changelog

## 2026-11-04

- Sidebar now shows the next scheduled data update (the 20th of each month, rolling forward automatically).

## 2026-10-30

Trends view extension (the "Trends (all months)" page itself predates this
change; these are new sections on it):

- **Overall median price:** all-room-type median nightly price, June–September
  2026 ($184.96 → $177.00 → $175.26 → $161.00), alongside the existing
  entire-home and private-room median series.
- **Room-type mix:** share of listings by room type over time — entire-home
  share eased from 68.6% to 67.9% while private rooms rose from 31.1% to
  31.7%; hotel and shared rooms stay under 1% combined.
- **Neighbourhood median trajectories:** all-room-type median price over time
  for the eight neighbourhoods with the most listings in the latest snapshot,
  with a neighbourhood × month table of the same values.
- **Future-proof month order:** the Trends page now derives its month list
  from the snapshot set instead of a hardcoded list, so the next monthly
  snapshot appears automatically once the refresh adds it.

## 2026-10-22

Dashboard content and functionality update (all figures recomputed live in
SQL from the committed bundle; September 2026 headline metrics unchanged):

- **Overview — "What changed" panel:** September 2026 vs August 2026
  deltas — listings added/removed (listing-ID membership), net listings,
  overall median price change, Superhost share delta, and the top-3
  neighbourhood median-price movers (with listing counts for both months).
- **Pricing — estimated upper-bound revenue:** per-listing estimated
  monthly revenue (nightly price × unavailable nights in the next 30 days;
  unavailable days mix bookings with host blocks, so this is an estimated
  upper bound, not actual earnings). Citywide medians for entire homes and
  private rooms, plus a top-15 neighbourhood table, with no-price listings
  excluded and counted in a footnote.
- **Hosts — professionalization trend:** share of listings run by
  multi-listing hosts (≥2 and ≥5 listings), single-listing-host share and
  entire-home share, trended across all four snapshots (Jun–Sep 2026).
- **Occupancy — forward availability panel:** median share of days still
  bookable over the next 30/60/90 days, citywide and by neighbourhood,
  from each listing's availability-window fields (the day-by-day calendar
  exists only for the August snapshot). Occupancy elsewhere in the app
  remains framed as calendar unavailability — an upper bound on occupancy.
- **Neighbourhoods — comparator:** pick 2–4 neighbourhoods for a
  side-by-side table (listings, entire-home and private-room medians,
  Superhost share, occupancy upper bound, reviews per listing per month)
  plus a grouped median-price chart by room type.
- **View SQL everywhere:** every chart and table section now carries a
  collapsed "View SQL" expander showing the exact query the app runs for
  it; pandas-aggregated visuals say so, and the one precomputed section
  (review word counts) states plainly that no query runs at page load.
- **Trends view:** the tab bar no longer renders in "Trends (all months)"
  view. Trends is a standalone page; previously the seven tabs were drawn
  above it but left empty (the script stops after the trend charts), so
  they looked broken. The tab bar now appears only in single-month views.

## 2026-09-30

- Keep-alive GitHub Actions workflow removed; keep-alive moved to
  scheduled real-browser visits instead.

## 2026-09-28

- Overview legend now uses human-readable room-type labels.
- Keep-alive workflow added (later removed, see 2026-09-30).

## 2026-09-25

- Occupancy framing corrected throughout: calendar unavailability is an
  upper bound on occupancy, never "true" or "booked" occupancy.

## 2026-09-23 — first deployment

- End-to-end SQL analysis of Toronto Airbnb listings, published with the
  Streamlit dashboard: monthly snapshots June–September 2026, seven tabs
  (Overview, Neighbourhoods, Hosts, Pricing, Occupancy, Reviews, Value
  finder), a month-over-month Trends page, and a self-contained data bundle
  so the deployed app needs no external database.
- Monthly refresh automation set up (20th of each month) to add each new
  snapshot and rewrite the findings prose.
