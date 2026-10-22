# Changelog

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
